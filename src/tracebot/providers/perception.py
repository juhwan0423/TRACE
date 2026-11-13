from collections import deque
from pathlib import Path
import math
from tracebot.core import Observation


class LossTracker:
    """One camera/subject stream; reacquisition does not resolve an Incident.

    Capture times strictly increase across ALL visibility states. Reset advances
    generation so late callbacks cannot bind the new stream, even if they arrive
    before its first frame. Producers must stamp generation at capture/request.
    """
    def __init__(self, grace=1., history=8, *, episode=None, generation=0):
        self.grace = grace
        self.history = deque(maxlen=history)
        self.episode = episode
        self.generation = generation
        self.stream = None
        self.last = None
        self.lost = False
        self.latest_capture = -math.inf
        self.loss_sequence = 0

    def update(self, observation):
        e = observation.evidence
        stream = (e.source, e.subject, observation.track_id)
        if (e.generation != self.generation or
            self.episode is not None and e.episode != self.episode or
            self.stream is not None and stream != self.stream or
            observation.visibility not in {'visible', 'occluded', 'unavailable'} or
            not all(math.isfinite(t) for t in (e.capture_time, e.received_time)) or
            e.received_time < e.capture_time or e.capture_time <= self.latest_capture):
            return False
        self.episode = e.episode
        self.stream = stream
        self.latest_capture = e.capture_time
        self.history.append(observation)
        if observation.visibility == 'visible':
            self.last, self.lost = observation, False
            return False
        if self.last and e.capture_time - self.last.evidence.capture_time >= self.grace and not self.lost:
            self.lost = True
            self.loss_sequence += 1
            return True
        return False

    def reset(self, *, episode=None):
        self.generation += 1
        self.episode = episode
        self.stream = None
        self.history.clear()
        self.last = None
        self.lost = False
        self.latest_capture = -math.inf
        self.loss_sequence = 0


class YoloProvider:
    def __init__(self, model_path):
        path = Path(model_path)
        if path.suffix != '.pt' or not path.is_file():
            raise ValueError('explicit existing local .pt weights required; downloads disabled')
        from ultralytics import YOLO
        self.model = YOLO(str(path), task='detect')

    def observe(self, image, evidence):
        results = self.model.predict(image, classes=[0], verbose=False)
        boxes = results[0].boxes
        if len(boxes) == 0:
            return Observation(evidence, 'occluded')
        best = max(boxes, key=lambda b: float(b.conf[0]))
        return Observation(evidence, 'visible', bbox=tuple(best.xyxy[0].tolist()), confidence=float(best.conf[0]))
