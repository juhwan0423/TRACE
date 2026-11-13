"""Independent RGB presence veto; never a posture/identity/safety oracle.

The raw VLM record is retained. Only the interpretation consumed by the host
changes. No simulator state or evaluation annotations enter this module.
"""
import asyncio
from dataclasses import asdict, is_dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import time

RULE_VERSION = 'rgb-person-veto/1'


class PersonGateAdapter:
    def __init__(self, adapter, detector=None, *, enabled=False, timeout=10.):
        if type(enabled) is not bool or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Explicit boolean and finite positive detector timeout required')
        if enabled and detector is None:
            raise ValueError('Enabled gate requires an independent detector')
        self.adapter, self.detector = adapter, detector
        self.enabled, self.timeout = enabled, timeout
        self.records = []
        self.detector_calls, self.detector_latencies = 0, []
        self._detector_timed_out = False

    async def infer(self, evidence):
        if not self.enabled:
            # The baseline does not pay for or see detector results.
            return await self.adapter.infer(evidence)
        started = time.monotonic()
        try:
            frame_hash = hashlib.sha256(Path(evidence.artifact).read_bytes()).hexdigest()
        except OSError:
            frame_hash = None
        # Both arms always query the same VLM on the full frame. No crop,
        # prompt change or early detector rejection saves a VLM call here.
        observation, original = await self.adapter.infer(evidence)
        if asyncio.current_task().cancelling():
            raise asyncio.CancelledError
        detection_started = time.monotonic()
        try:
            if self._detector_timed_out:
                # A native worker may still be running after coroutine timeout.
                # Never pile more threads behind that stalled detector.
                detection = {'status': 'unavailable', 'reason': 'prior detector timeout; restart adapter after inspection'}
            else:
                self.detector_calls += 1
                detection = await asyncio.wait_for(self.detector.infer(evidence), self.timeout)
                detection = asdict(detection) if is_dataclass(detection) else dict(detection)
        except asyncio.TimeoutError:
            self._detector_timed_out = True
            detection = {'status': 'timeout'}
        except asyncio.CancelledError:
            raise
        except Exception as error:
            detection = {'status': 'error', 'error': type(error).__name__ + ': ' + str(error)}
        finally:
            self.detector_latencies.append(time.monotonic() - detection_started)
        detector_seconds = time.monotonic() - detection_started
        if detector_seconds > self.timeout:
            self._detector_timed_out = True
            detection = dict(detection, status='timeout', late_result_discarded=True)
        try:
            after_hash = hashlib.sha256(Path(evidence.artifact).read_bytes()).hexdigest()
        except OSError:
            after_hash = None
        bound = (frame_hash is not None and frame_hash == after_hash
                 and detection.get('frame_sha256') == frame_hash
                 and detection.get('evidence_id') == evidence.id
                 and detection.get('episode') == evidence.episode
                 and detection.get('generation') == evidence.generation
                 and detection.get('source') == evidence.source
                 and detection.get('capture_time') == evidence.capture_time
                 and detection.get('artifact') == str(evidence.artifact))
        boxes = detection.get('boxes')
        supported = (bound and detection.get('status') == 'detected'
                     and isinstance(boxes, (list,tuple)) and len(boxes) == 1)
        status = detection.get('status', 'missing')
        reason = ('independent person detection corroborates presence only' if supported else
                  'independent person detection unavailable: ' + str(status)
                  if status in ('timeout', 'error', 'unavailable', 'missing') else
                  'independent person detection does not match this frame' if not bound else
                  'independent person detection does not identify one unambiguous person: ' + str(status))
        effective = observation if supported else replace(observation,
            person_visible='uncertain', posture='unknown', visible_risk_cues=(),
            observation_limitations=tuple(observation.observation_limitations) + (reason,),
            needs_more_observation=True)
        gate = dict(enabled=True, rule_version=RULE_VERSION,
                    presence_corroborated=bool(supported), reason=reason,
                    interpretation_changed=effective != observation,
                    detector=detection, detector_latency_wall_seconds=detector_seconds,
                    total_adapter_latency_wall_seconds=time.monotonic() - started,
                    posture_verified=False, identity_verified=False)
        # Keep original status: the host uses valid Qwen completion to release
        # the post-arrival observation requirement and allow another viewpoint.
        record = dict(original, effective_interpretation=asdict(effective), person_gate=gate)
        self.records.append(record)
        return effective, record


def detector_config(path):
    """Explicit project config, local checkpoint and frozen digest only."""
    cfg = json.loads(Path(path).read_text())
    required = {'model_path', 'model_sha256', 'confidence', 'image_size', 'device', 'timeout_seconds'}
    optional = {'archive_confidence', 'nms_iou', 'max_det'}
    if not isinstance(cfg, dict) or not required <= set(cfg) or set(cfg) - required - optional:
        raise ValueError('Detector config fields mismatch')
    if (type(cfg['confidence']) not in (int,float) or not math.isfinite(cfg['confidence'])
            or not 0 < cfg['confidence'] <= 1):
        raise ValueError('Detector confidence must be in (0, 1]')
    # Resolve legacy defaults before freezing so the complete inference recipe
    # is recorded. Existing .25 configs still infer and decide at .25.
    cfg.setdefault('archive_confidence', cfg['confidence'])
    cfg.setdefault('nms_iou', .7)
    cfg.setdefault('max_det', 300)
    if (type(cfg['archive_confidence']) not in (int, float) or not math.isfinite(cfg['archive_confidence'])
            or not 0 < cfg['archive_confidence'] <= cfg['confidence']):
        raise ValueError('Detector archive_confidence must be in (0, confidence]')
    if (type(cfg['nms_iou']) not in (int, float) or not math.isfinite(cfg['nms_iou'])
            or not 0 < cfg['nms_iou'] <= 1):
        raise ValueError('Detector nms_iou must be in (0, 1]')
    if type(cfg['max_det']) is not int or not 1 <= cfg['max_det'] <= 10000:
        raise ValueError('Detector max_det must be an integer in [1, 10000]')
    if type(cfg['image_size']) is not int or not 32 <= cfg['image_size'] <= 4096 or cfg['image_size'] % 32:
        raise ValueError('Detector image_size must be a multiple of 32 in [32,4096]')
    if not isinstance(cfg['device'],str) or not cfg['device'].strip():
        raise ValueError('Explicit detector device required')
    if (type(cfg['timeout_seconds']) not in (int,float) or not math.isfinite(cfg['timeout_seconds'])
            or cfg['timeout_seconds'] <= 0):
        raise ValueError('Finite positive detector timeout required')
    model = Path(cfg['model_path'])
    if not model.is_absolute() or not model.is_file() or model.suffix != '.pt':
        raise ValueError('Existing absolute local .pt checkpoint required')
    if hashlib.sha256(model.read_bytes()).hexdigest() != cfg['model_sha256']:
        raise ValueError('Detector checkpoint hash mismatch')
    return cfg


def with_person_gate(adapter, config):
    from .person_detector import LocalPersonDetector
    detector = LocalPersonDetector(config['model_path'], confidence=config['confidence'],
        image_size=config['image_size'], device=config['device'],
        archive_confidence=config.get('archive_confidence', config['confidence']),
        nms_iou=config.get('nms_iou', .7), max_det=config.get('max_det', 300))
    return PersonGateAdapter(adapter, detector, enabled=True, timeout=config['timeout_seconds'])


def configure_detector_environment(project_root):
    """Process-local settings; never write global Ultralytics configuration."""
    directory = Path(project_root) / 'artifacts/person_detector/settings'
    directory.mkdir(parents=True, exist_ok=True)
    os.environ.update(YOLO_OFFLINE='true', YOLO_AUTOINSTALL='false',
                      YOLO_CONFIG_DIR=str(directory.resolve()))
