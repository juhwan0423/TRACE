import asyncio
import unittest
from haiclaw.closed_loop import ClosedLoop
from haiclaw.core import Evidence, Observation, State
from haiclaw.providers.single_frame_vlm import Interpretation


class Adapter:
    async def infer(self, evidence):
        await asyncio.sleep(0)
        return Interpretation('yes', 'lying', (), (), False, (evidence.id,)), {'status': 'ok'}


def frame(t, visibility, episode='e'):
    return Observation(Evidence(str(t), episode, 'fixed', t, t, f'{t}.png'), visibility)


class ClosedLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_loss_motion_fresh_inference(self):
        loop = ClosedLoop('e', Adapter(), budget=10)
        self.assertFalse(loop.observe(frame(0, 'visible'), 0))
        self.assertTrue(loop.observe(frame(2, 'occluded'), 2))
        self.assertFalse(loop.observe(frame(3, 'occluded'), 3))
        loop.motion('arrived', 4, loop.attempt)
        loop.submit(Evidence('new', 'e', 'body', 5, 5, 'fresh.png'))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        loop.tick(6)
        self.assertEqual(loop.incident.state, State.DANGER)

    async def test_arrival_alone_never_closes(self):
        loop = ClosedLoop('e', Adapter(), budget=5)
        loop.observe(frame(0, 'visible'), 0)
        loop.observe(frame(2, 'unavailable'), 2)
        loop.motion('arrived', 3, loop.attempt)
        with self.assertRaises(ValueError):
            loop.submit(Evidence('old', 'e', 'body', 2, 3, 'old.png'))
        loop.tick(7)
        self.assertEqual(loop.incident.state, State.UNKNOWN)

    async def test_slow_inference_does_not_block_deadline(self):
        class Slow:
            async def infer(self, evidence):
                await asyncio.sleep(10)
        loop = ClosedLoop('e', Slow(), budget=4)
        loop.observe(frame(0, 'visible'), 0)
        loop.observe(frame(2, 'occluded'), 2)
        loop.motion('arrived', 3, loop.attempt)
        loop.submit(Evidence('new', 'e', 'body', 4, 4, 'fresh.png'))
        loop.tick(6)
        self.assertEqual(loop.incident.state, State.UNKNOWN)
        for _, task in loop.vlm.pending.values():
            task.cancel()
        await asyncio.gather(*(task for _, task in loop.vlm.pending.values()), return_exceptions=True)

    async def test_wrong_episode_cannot_trigger_motion(self):
        loop = ClosedLoop('e', Adapter())
        loop.observe(frame(0, 'visible'), 0)
        self.assertFalse(loop.observe(frame(2, 'occluded', episode='old'), 2))
        self.assertIsNone(loop.incident)
