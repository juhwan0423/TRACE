from dataclasses import dataclass
from haiclaw.core import Action


@dataclass(frozen=True)
class Candidate:
    id: str
    travel_seconds: float
    expected_resolution: float
    observation_seconds: float = 1.
    risk_cost: float = .1


def choose(policy, remaining, candidates):
    if policy == 'fixed':
        return Action('wait', None, 'fixed deadline escalation')
    feasible = [c for c in candidates if c.travel_seconds + c.observation_seconds < remaining]
    if not feasible:
        return Action('wait', None, 'no candidate fits remaining deadline')
    if policy in ('rule', 'reacquisition'):
        selected = feasible[0]
        reason = 'configured first feasible verification waypoint'
    elif policy == 'proposed':
        def score(c):
            return c.expected_resolution / (c.travel_seconds + c.observation_seconds) - c.risk_cost
        selected = max(feasible, key=score)
        reason = f'resolution/time-risk heuristic score={score(selected):.4f}; assumed priors, not learned'
    else:
        raise ValueError(policy)
    return Action('inspect', selected.id, reason)
