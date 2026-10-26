"""Simulation-clock incident coordinator; adapters own transport and sensing."""
import math
from haiclaw.core import Incident, TERMINAL
from haiclaw.providers.perception import LossTracker
from haiclaw.providers.single_frame_vlm import IncidentVLM


class ClosedLoop:
    def __init__(self, episode, adapter, budget=180., grace=1., max_age=45.):
        if not all(math.isfinite(x) for x in (budget, grace, max_age)) or budget <= 0 or grace < 0 or max_age <= 0:
            raise ValueError('positive budget/max_age and nonnegative grace required')
        self.tracker = LossTracker(grace=grace, episode=episode)
        self.adapter, self.budget, self.max_age = adapter, budget, max_age
        self.incident = self.vlm = None
        self.attempt = None

    def observe(self, observation, now):
        self.tick(now)
        if self.incident is not None:
            return False
        if not self.tracker.update(observation):
            return False
        self.incident = Incident(self.tracker.episode, now, now + self.budget,
                                 generation=self.tracker.generation)
        self.vlm = IncidentVLM(self.incident, self.adapter, self.max_age)
        self.attempt = self.incident.motion('moving', now)
        return True

    def motion(self, status, now, attempt):
        if self.incident is None:
            raise RuntimeError('no incident')
        return self.incident.motion(status, now, attempt_id=attempt)

    def submit(self, evidence):
        if self.vlm is None:
            raise RuntimeError('no incident')
        return self.vlm.submit(evidence)

    def tick(self, now):
        if self.vlm:
            return self.vlm.tick(now)

    @property
    def done(self):
        return self.incident is not None and self.incident.state in TERMINAL

    def report(self):
        i = self.incident
        return dict(state=i.state.value if i else 'monitoring',
                    opened=i.opened if i else None, deadline=i.deadline if i else None,
                    events=i.events if i else [], audit=self.vlm.audit if self.vlm else [])
