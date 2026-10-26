from dataclasses import dataclass, field
from enum import Enum
import math


class State(str, Enum):
    OPEN = 'open'
    VERIFYING = 'verifying'
    SAFE = 'resolved_safe'
    DANGER = 'danger_confirmed'
    UNKNOWN = 'escalated_unknown'


TERMINAL = {State.SAFE, State.DANGER, State.UNKNOWN}


@dataclass(frozen=True)
class Evidence:
    id: str
    episode: str
    source: str
    capture_time: float
    received_time: float
    artifact: str
    subject: str = 'person-1'
    quality: float = 1.0
    reason: str = ''
    generation: int = 0  # Increment when resetting/reopening an incident stream.


@dataclass(frozen=True)
class Observation:
    evidence: Evidence
    visibility: str  # visible / occluded / unavailable
    track_id: str = 'person-1'
    bbox: tuple | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class Decision:
    person_visible: bool
    observable_posture: str
    distress_cues: tuple[str, ...]
    insufficient_evidence: bool
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class Action:
    kind: str
    target_id: str | None
    reason: str


@dataclass
class Incident:
    episode: str
    opened: float
    deadline: float
    subject: str = 'person-1'
    state: State = State.OPEN
    latest_capture: float = -math.inf
    arrived_at: float | None = None
    seen_ids: set = field(default_factory=set)
    seen_frames: set = field(default_factory=set)
    events: list = field(default_factory=list)
    now: float = -math.inf
    generation: int = 0
    latest_by_source: dict = field(default_factory=dict)
    latest_valid_by_source: dict = field(default_factory=dict)
    motion_attempt: int = 0
    motion_status: str | None = None

    def _advance(self, now):
        if not math.isfinite(now) or now < self.now:
            raise ValueError('simulation time must be finite and monotonic')
        self.now = now

    def tick(self, now):
        self._advance(now)
        if now >= self.deadline and self.state not in TERMINAL:
            self._finish(State.UNKNOWN, now, 'deadline without confirmation')

    def _finish(self, state, now, reason):
        # A timer-first boundary correction updates the existing local alert.
        alert_update = self.state == State.UNKNOWN and state == State.DANGER
        self.state = state
        self.events.append(dict(time=now, state=state.value, reason=reason,
                                local_alert=not alert_update and state in {State.DANGER, State.UNKNOWN},
                                alert_update=alert_update))

    def motion(self, status, now, *, attempt_id=None):
        """Start with moving, then tag async callbacks with the returned attempt id.

        A direct initial arrived notification remains supported for fixture callers.
        Failure/cancellation invalidates arrival; a new attempt requires moving.
        """
        if status not in {'moving', 'arrived', 'failed', 'timed_out', 'cancelled'}:
            raise ValueError('invalid motion status')
        self.tick(now)
        if self.state in TERMINAL:
            return None
        if status == 'moving':
            if attempt_id is not None:
                raise ValueError('moving creates an attempt; do not supply attempt_id')
            self.motion_attempt += 1
            self.arrived_at = None
        elif (attempt_id is not None and attempt_id != self.motion_attempt or
              self.motion_status in {'failed', 'timed_out', 'cancelled'}):
            return None
        elif status == 'arrived' and self.motion_status == 'arrived':
            return self.motion_attempt  # Duplicate completion is not a new arrival.
        self.state = State.VERIFYING
        self.motion_status = status
        self.arrived_at = now if status == 'arrived' else None
        self.events.append(dict(time=now, motion=status, attempt_id=self.motion_attempt,
                                request_fresh_frame=status == 'arrived'))
        return self.motion_attempt

    def accept(self, evidence, decision, now, max_age=3.0):
        """Use fresh conclusive evidence, scoped by episode/generation/source.

        At now == deadline, danger wins over unknown even if tick ran first.
        Safe evidence never closes at/after the deadline. After the boundary,
        terminal states cannot be revised. Invalid input still runs the timer.
        """
        self._advance(now)
        boundary_unknown = self.state == State.UNKNOWN and now == self.deadline
        if self.state in TERMINAL and not boundary_unknown:
            return False
        if now > self.deadline:
            self.tick(now)
            return False
        e = evidence
        key = (e.source, e.capture_time, e.artifact)
        if (e.episode != self.episode or e.generation != self.generation or e.subject != self.subject or
            e.id in self.seen_ids or key in self.seen_frames or
            not all(math.isfinite(x) for x in (e.capture_time, e.received_time, e.quality)) or
            not math.isfinite(max_age) or max_age < 0 or
            not 0 <= e.quality <= 1 or not e.source or not e.artifact or
            not self.opened <= e.capture_time <= e.received_time <= now or
            now - e.capture_time > max_age):
            self.tick(now)
            return False
        self.seen_ids.add(e.id)
        self.seen_frames.add(key)
        self.latest_capture = max(self.latest_capture, e.capture_time)
        self.latest_by_source[e.source] = max(self.latest_by_source.get(e.source, -math.inf), e.capture_time)
        conclusive = (decision.observable_posture in {'lying', 'upright_active'} or bool(decision.distress_cues))
        if (decision.evidence_refs != (e.id,) or decision.insufficient_evidence or
            not decision.person_visible or not conclusive or e.quality < .7 or e.reason or
            e.capture_time <= self.latest_valid_by_source.get(e.source, -math.inf)):
            self.tick(now)
            return False
        self.latest_valid_by_source[e.source] = e.capture_time
        if decision.distress_cues or decision.observable_posture == 'lying':
            self._finish(State.DANGER, now, 'current visible danger evidence: ' + e.id)
            return True
        if (now < self.deadline and self.arrived_at is not None and
            self.motion_status == 'arrived' and e.capture_time > self.arrived_at and
            e.capture_time >= self.latest_capture):
            self._finish(State.SAFE, now, 'fresh post-arrival activity evidence: ' + e.id)
            return True
        self.tick(now)
        return False
