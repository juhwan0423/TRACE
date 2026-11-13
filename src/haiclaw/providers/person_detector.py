"""Independent, RGB-only person presence corroboration using explicit local weights.

This adapter never reads simulator annotations or infers identity, posture, safety,
or absence from a missed detection. Multiple detections are ambiguous for TRACE's
single-worker task. Callers must separately enforce frame freshness and episode
binding, and must not call a positive detection a posture ground truth.

The optional Ultralytics backend is imported only on first detection. Launch it
with YOLO_OFFLINE=true, YOLO_AUTOINSTALL=false, and a project-local YOLO_CONFIG_DIR.
No weights, packages, settings, or images are downloaded by this adapter.
"""
import asyncio
from dataclasses import asdict, dataclass
import hashlib
import io
import math
import os
from pathlib import Path
import threading
import time


class DetectorUnavailable(RuntimeError):
    """A missing dependency, checkpoint, or offline launch configuration."""


@dataclass(frozen=True)
class PersonBox:
    xyxy: tuple[float, float, float, float]
    confidence: float
    class_id: int


@dataclass(frozen=True)
class PersonDetectionResult:
    status: str  # detected / not_detected / multiple_people / unavailable / error
    reason: str
    evidence_id: str
    episode: str
    generation: int
    source: str
    capture_time: float
    artifact: str
    frame_sha256: str | None
    model_path: str
    model_sha256: str | None
    confidence_threshold: float
    image_size: int
    device: str
    frame_size: tuple[int, int] | None  # native (width, height), before resizing
    boxes: tuple[PersonBox, ...]
    latency_wall_seconds: float
    # This is a bounded post-NMS archive, not raw network logits or pre-NMS
    # proposals. ``boxes`` alone determines online gate status.
    raw_boxes: tuple[PersonBox, ...] = ()
    archive_confidence: float | None = None
    nms_iou: float = .7
    max_det: int = 300
    raw_boxes_stage: str = 'post_nms_person_candidates'
    raw_boxes_at_capacity: bool = False

    @property
    def single_person(self):
        """One supported presence candidate; not an identity or posture claim."""
        return self.status == 'detected' and len(self.boxes) == 1

    @property
    def supports_person_presence(self):
        return self.status in {'detected', 'multiple_people'} and bool(self.boxes)

    def to_dict(self):
        return asdict(self)


def _ultralytics_factory(model_path):
    # Require the launch configuration BEFORE import: Ultralytics initializes its
    # configuration and network/autoinstall flags at import time. Do not edit a
    # user's ~/.config/Ultralytics or silently install optional dependencies.
    if os.environ.get('YOLO_OFFLINE', '').lower() not in {'true', '1'}:
        raise DetectorUnavailable('launch with YOLO_OFFLINE=true before importing ultralytics')
    if os.environ.get('YOLO_AUTOINSTALL', '').lower() not in {'false', '0'}:
        raise DetectorUnavailable('launch with YOLO_AUTOINSTALL=false')
    config_dir = os.environ.get('YOLO_CONFIG_DIR')
    if not config_dir or not Path(config_dir).is_dir() or not os.access(config_dir, os.W_OK):
        raise DetectorUnavailable('explicit writable project-local YOLO_CONFIG_DIR required')
    try:
        from ultralytics import YOLO
        from ultralytics import utils
    except ImportError as exc:
        raise DetectorUnavailable('ultralytics and its dependencies must be installed locally') from exc
    if getattr(utils, 'ONLINE', True) or getattr(utils, 'AUTOINSTALL', True):
        raise DetectorUnavailable('ultralytics was imported before offline settings; restart the process')
    return YOLO(model_path, task='detect')


def _sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


class LocalPersonDetector:
    """Serialized detector with fail-closed results and exact encoded-frame hashes.

    ``detect(evidence)`` is synchronous. ``infer(evidence)`` keeps an asyncio event
    loop responsive using a thread; cancellation does NOT stop native inference.
    A caller needing hard timeouts should own a bounded worker subprocess. The
    inference backend receives only decoded RGB pixels, never the evidence ID,
    source path, episode, simulator metadata, or evaluation annotations.

    ``model_factory`` is an optional local test double accepting an absolute .pt
    path. Production callers should leave it unset. Only trusted local checkpoints
    should be supplied to a PyTorch model loader.
    """

    def __init__(self, model_path, *, confidence=.25, image_size=640, device='cpu',
                 archive_confidence=None, nms_iou=.7, max_det=300,
                 model_factory=None, max_image_bytes=10 * 1024 * 1024,
                 max_image_pixels=16_777_216):
        if not isinstance(model_path, (str, Path)) or not str(model_path) or '://' in str(model_path):
            raise ValueError('explicit local .pt checkpoint path required')
        self.model_path = Path(model_path).expanduser().resolve()
        if self.model_path.suffix.lower() != '.pt':
            raise ValueError('only explicit local .pt checkpoints are supported')
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 < confidence <= 1:
            raise ValueError('confidence must be in (0, 1]')
        if archive_confidence is None:
            archive_confidence = confidence
        if (type(archive_confidence) not in (int, float) or not math.isfinite(archive_confidence)
                or not 0 < archive_confidence <= confidence):
            raise ValueError('archive_confidence must be in (0, confidence]')
        if type(nms_iou) not in (int, float) or not math.isfinite(nms_iou) or not 0 < nms_iou <= 1:
            raise ValueError('nms_iou must be in (0, 1]')
        if type(max_det) is not int or not 1 <= max_det <= 10000:
            raise ValueError('max_det must be an integer in [1, 10000]')
        if type(image_size) is not int or not 32 <= image_size <= 4096 or image_size % 32:
            raise ValueError('image_size must be a multiple of 32 between 32 and 4096')
        if not isinstance(device, str) or not device.strip():
            raise ValueError('explicit inference device required')
        if type(max_image_bytes) is not int or max_image_bytes <= 0 or type(max_image_pixels) is not int or max_image_pixels <= 0:
            raise ValueError('positive image bounds required')
        self.confidence, self.image_size, self.device = float(confidence), image_size, device
        self.archive_confidence, self.nms_iou, self.max_det = float(archive_confidence), float(nms_iou), max_det
        self.max_image_bytes, self.max_image_pixels = max_image_bytes, max_image_pixels
        self._factory = model_factory or _ultralytics_factory
        self._model = None
        self._model_sha256 = None
        self._person_class_ids = ()
        self._lock = threading.Lock()

    def _load_model(self):
        if not self.model_path.is_file():
            raise DetectorUnavailable('checkpoint missing; automatic downloads disabled')
        current_hash = _sha256_file(self.model_path)
        if self._model is not None:
            if current_hash != self._model_sha256:
                raise ValueError('checkpoint changed after initialization')
            return
        self._model_sha256 = current_hash
        model = self._factory(str(self.model_path))
        if _sha256_file(self.model_path) != current_hash:
            raise ValueError('checkpoint changed during initialization')
        names = model.names
        if isinstance(names, (list, tuple)):
            names = dict(enumerate(names))
        if not isinstance(names, dict):
            raise ValueError('detector must expose its class names')
        ids = []
        for key, name in names.items():
            if str(name).strip().lower() == 'person':
                try:
                    class_id = int(key)
                except (ValueError, TypeError) as exc:
                    raise ValueError('invalid person class id') from exc
                if class_id < 0 or str(key) != str(class_id):
                    raise ValueError('invalid person class id')
                ids.append(class_id)
        if not ids:
            raise ValueError('checkpoint has no class named person')
        self._person_class_ids = tuple(sorted(ids))
        self._model = model

    def _boxes(self, result, width, height):
        raw = result.boxes
        if raw is None:
            raise ValueError('detector returned no detection boxes structure')
        coordinates = raw.xyxy.tolist()
        scores = raw.conf.tolist()
        classes = raw.cls.tolist()
        if len(coordinates) != len(scores) or len(scores) != len(classes):
            raise ValueError('inconsistent detection arrays')
        boxes = []
        for xyxy, score, class_id in zip(coordinates, scores, classes):
            if len(xyxy) != 4:
                raise ValueError('invalid box dimensions')
            values = tuple(float(x) for x in xyxy)
            score, class_value = float(score), float(class_id)
            if not all(math.isfinite(x) for x in (*values, score, class_value)):
                raise ValueError('nonfinite detection')
            if class_value != int(class_value) or not 0 <= score <= 1:
                raise ValueError('invalid class id or confidence')
            if int(class_value) not in self._person_class_ids or score < self.archive_confidence:
                continue
            x1, y1, x2, y2 = values
            if not 0 <= x1 < x2 <= width or not 0 <= y1 < y2 <= height:
                raise ValueError('person box outside native RGB frame')
            boxes.append(PersonBox(values, score, int(class_value)))
        return tuple(sorted(boxes, key=lambda box: (-box.confidence, box.xyxy)))

    def detect(self, evidence):
        started = time.monotonic()
        frame_hash, frame_size, boxes, raw_boxes = None, None, (), ()
        status, reason = 'error', 'inference not completed'
        with self._lock:
            try:
                if (not isinstance(evidence.id, str) or not evidence.id or
                        not isinstance(evidence.source, str) or not evidence.source or
                        not math.isfinite(evidence.capture_time)):
                    raise ValueError('invalid evidence provenance')
                artifact = Path(evidence.artifact)
                with artifact.open('rb') as stream:
                    image_bytes = stream.read(self.max_image_bytes + 1)
                frame_hash = hashlib.sha256(image_bytes).hexdigest()
                if len(image_bytes) > self.max_image_bytes:
                    # This is a prefix, not the full frame; never mislabel it.
                    frame_hash = None
                    raise ValueError('image exceeds configured byte bound')
                try:
                    from PIL import Image
                except ImportError as exc:
                    raise DetectorUnavailable('Pillow must be installed locally') from exc
                with Image.open(io.BytesIO(image_bytes)) as decoded:
                    if decoded.format != 'PNG' or getattr(decoded, 'n_frames', 1) != 1:
                        raise ValueError('one PNG RGB camera frame required')
                    if decoded.mode != 'RGB':
                        raise ValueError('RGB camera image required, not masks/depth/RGBA')
                    width, height = decoded.size
                    if width * height > self.max_image_pixels:
                        raise ValueError('image exceeds configured pixel bound')
                    frame_size = (width, height)
                    image = decoded.copy()
                self._load_model()
                results = self._model.predict(
                    source=image, classes=list(self._person_class_ids), conf=self.archive_confidence,
                    iou=self.nms_iou, max_det=self.max_det,
                    imgsz=self.image_size, device=self.device, verbose=False, save=False,
                    save_txt=False, save_crop=False, stream=False)
                if len(results) != 1:
                    raise ValueError('one prediction result per RGB frame required')
                if tuple(results[0].orig_shape) != (height, width):
                    raise ValueError('prediction dimensions do not match evidence')
                raw_boxes = self._boxes(results[0], width, height)
                boxes = tuple(box for box in raw_boxes if box.confidence >= self.confidence)
                status = 'detected' if len(boxes) == 1 else 'multiple_people' if boxes else 'not_detected'
                reason = {
                    'detected': 'one person candidate; identity and posture unverified',
                    'multiple_people': 'multiple person candidates; target association ambiguous',
                    'not_detected': 'no person candidate above threshold; not proof of absence',
                }[status]
            except (DetectorUnavailable, FileNotFoundError, ImportError) as exc:
                status, reason = 'unavailable', f'{type(exc).__name__}: {exc}'
            except Exception as exc:
                status, reason = 'error', f'{type(exc).__name__}: {exc}'
            return PersonDetectionResult(
                status=status, reason=reason[:1000], evidence_id=evidence.id,
                episode=evidence.episode, generation=evidence.generation,
                source=evidence.source, capture_time=evidence.capture_time,
                artifact=str(evidence.artifact), frame_sha256=frame_hash,
                model_path=str(self.model_path), model_sha256=self._model_sha256,
                confidence_threshold=self.confidence, image_size=self.image_size,
                device=self.device, frame_size=frame_size, boxes=boxes,
                latency_wall_seconds=time.monotonic() - started,
                raw_boxes=raw_boxes, archive_confidence=self.archive_confidence,
                nms_iou=self.nms_iou, max_det=self.max_det,
                raw_boxes_at_capacity=len(raw_boxes) >= self.max_det)

    async def infer(self, evidence):
        return await asyncio.to_thread(self.detect, evidence)
