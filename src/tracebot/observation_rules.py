"""Conservative question-scoped exceptions to descriptive observation caveats.

Only whole clauses describing face visibility or camera direction are exempt.
Unknown caveats and mixed clauses still block. This does not verify identity,
establish safety, or override explicit uncertainty or the independent detector.
"""
import re

RULE_VERSION = 'trace-context/2-scoped-limitations'
_NON_POSTURE = tuple(re.compile(p) for p in (
    r"(?:(?:the )?person(?:'s)? )?face (?:is )?not visible",
    r"(?:the )?person(?:'s)? face (?:is )?not visible",
    r"(?:the )?person (?:is )?(?:viewed|seen) from (?:behind|(?:the )?(?:back|rear))",
    r"(?:the )?person (?:is )?facing away from (?:the )?camera",
    r"(?:view|viewed|seen) from (?:behind|(?:the )?(?:back|rear))",
    r"(?:rear|back)[ -]view",
    r"low[ -]angle(?: (?:camera )?(?:view|perspective))?",
))


def posture_limitations_block(limitations):
    for text in limitations:
        if not isinstance(text, str):
            return True
        clauses = re.split(r'[,;.]|\band\b', text.lower().strip())
        clauses = [' '.join(c.split()) for c in clauses if c.strip()]
        if not clauses or any(not any(p.fullmatch(c) for p in _NON_POSTURE) for c in clauses):
            return True
    return False


def clear_posture_observation(observation):
    return (observation.person_visible == 'yes'
            and observation.posture in ('standing', 'lying', 'seated')
            and observation.needs_more_observation is False
            and not posture_limitations_block(observation.observation_limitations))
