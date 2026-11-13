"""Injected asynchronous adapter. Default mock; never creates network clients."""
import asyncio
from dataclasses import dataclass
from tracebot.core import Decision


def validate(data, ref):
    if not isinstance(data, dict) or set(data) != {
        'person_visible', 'observable_posture', 'distress_cues',
        'insufficient_evidence', 'evidence_refs'}:
        raise ValueError('unexpected schema')
    if (type(data['person_visible']) is not bool or type(data['insufficient_evidence']) is not bool or
        data['observable_posture'] not in ('upright_active', 'lying', 'unknown') or
        not isinstance(data['distress_cues'], list) or
        any(type(x) is not str for x in data['distress_cues']) or data['evidence_refs'] != [ref]):
        raise ValueError('invalid values or evidence reference')
    return Decision(data['person_visible'], data['observable_posture'], tuple(data['distress_cues']),
                    data['insufficient_evidence'], tuple(data['evidence_refs']))


def unknown(ref):
    return Decision(False, 'unknown', (), True, (ref,))


@dataclass(frozen=True)
class VLMConfig:
    provider: str = 'mock'
    endpoint: str | None = None
    model: str | None = None
    timeout: float = .1


class VLMAdapter:
    def __init__(self, transport, config=VLMConfig()):
        self.transport, self.config = transport, config
        self.tasks = {}
        self.calls = 0

    async def infer(self, episode, last_observation, frame):
        key = (episode, frame.generation, frame.source, frame.capture_time, frame.artifact)
        if key not in self.tasks:
            self.calls += 1
            self.tasks[key] = asyncio.create_task(self._call(last_observation, frame))
        return await asyncio.shield(self.tasks[key])

    async def _call(self, last, frame):
        try:
            response = await asyncio.wait_for(self.transport(last, frame), self.config.timeout)
            return validate(response, frame.id)
        except (Exception, asyncio.CancelledError):
            return unknown(frame.id)

    def reset(self):
        for task in self.tasks.values():
            task.cancel()
        self.tasks.clear()
