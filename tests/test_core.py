"""Core semantic regression tests using synthetic evidence only."""
from dataclasses import replace
import unittest
from tracebot.core import Evidence, Decision, Incident, Observation, State
from tracebot.providers.perception import LossTracker


def evidence(t=2., name='f', source='robot'):
    return Evidence(name, 'episode', source, t, t, 'fixture/' + name)


def decision(name='f', posture='upright_active', insufficient=False):
    return Decision(True, posture, (), insufficient, (name,))


class IncidentTests(unittest.TestCase):
    def test_arrival_requires_fresh_evidence(self):
        i = Incident('episode', 0, 10)
        i.motion('arrived', 1)
        self.assertEqual(i.state, State.VERIFYING)
        i.accept(evidence(), decision(), 2)
        self.assertEqual(i.state, State.SAFE)

    def test_immediate_danger(self):
        i = Incident('episode', 0, 10)
        i.accept(evidence(), decision(posture='lying'), 2)
        self.assertEqual(i.state, State.DANGER)
        self.assertEqual(i.events[-1]['time'], 2)

    def test_sensor_stall_deadline(self):
        i = Incident('episode', 0, 10)
        i.tick(10)
        self.assertEqual(i.state, State.UNKNOWN)

    def test_duplicate_stale_foreign_evidence(self):
        i = Incident('episode', 0, 10)
        i.motion('arrived', 1)
        i.accept(evidence(), decision(insufficient=True), 2)
        self.assertFalse(i.accept(evidence(), decision(), 2))
        self.assertFalse(i.accept(replace(evidence(3), episode='old'), decision(), 3))
        self.assertFalse(i.accept(evidence(1.5, 'older'), decision('older'), 3))
        self.assertEqual(i.state, State.VERIFYING)

    def test_newer_unusable_frame_does_not_suppress_other_camera_danger(self):
        i = Incident('episode', 0, 10)
        i.accept(replace(evidence(4, 'blur', 'fixed'), quality=.1), decision('blur', insufficient=True), 4)
        i.accept(evidence(3, 'danger'), decision('danger', 'lying'), 4)
        self.assertEqual(i.state, State.DANGER)

    def test_delayed_visible_frame_does_not_clear_latest_loss(self):
        tracker = LossTracker()
        tracker.update(Observation(evidence(0), 'visible'))
        tracker.update(Observation(evidence(5), 'occluded'))
        tracker.update(Observation(evidence(2), 'visible'))
        self.assertTrue(tracker.lost)

    def test_unusable_frames_do_not_advance_valid_watermark(self):
        for source in ('fixed', 'robot'):
            for mode in ('quality', 'insufficient', 'reason', 'invisible', 'refs'):
                with self.subTest(source=source, mode=mode):
                    i = Incident('episode', 0, 10)
                    frame = evidence(4, 'bad', source)
                    judgement = decision('bad')
                    if mode == 'quality':
                        frame = replace(frame, quality=.2)
                    elif mode == 'reason':
                        frame = replace(frame, reason='blur')
                    elif mode == 'insufficient':
                        judgement = replace(judgement, insufficient_evidence=True)
                    elif mode == 'invisible':
                        judgement = replace(judgement, person_visible=False)
                    else:
                        judgement = replace(judgement, evidence_refs=('wrong',))
                    i.accept(frame, judgement, 4)
                    self.assertEqual(i.latest_by_source[source], 4)
                    self.assertNotIn(source, i.latest_valid_by_source)
                    self.assertTrue(i.accept(evidence(3, 'danger'), decision('danger', 'lying'), 4))
                    self.assertEqual(i.state, State.DANGER)

    def test_same_source_valid_newer_evidence_rejects_older_danger(self):
        i = Incident('episode', 0, 10)
        # No arrival, so upright evidence alone cannot close.
        i.accept(evidence(4, 'new'), decision('new'), 4)
        self.assertFalse(i.accept(evidence(3, 'old'), decision('old', 'lying'), 4))
        self.assertEqual(i.latest_valid_by_source['robot'], 4)
        self.assertEqual(i.state, State.OPEN)

    def test_valid_watermark_is_source_specific(self):
        i = Incident('episode', 0, 10)
        i.accept(evidence(4, 'fixed', 'fixed'), decision('fixed'), 4)
        self.assertTrue(i.accept(evidence(3, 'danger'), decision('danger', 'lying'), 4))
        self.assertEqual(i.state, State.DANGER)

    def test_same_capture_timestamp_from_different_sources_is_independent(self):
        i = Incident('episode', 0, 10)
        i.accept(evidence(3, 'fixed', 'fixed'), decision('fixed'), 3)
        self.assertTrue(i.accept(evidence(3, 'danger'), decision('danger', 'lying'), 3))

    def test_unusable_new_frame_still_prevents_old_safe_closure(self):
        i = Incident('episode', 0, 10)
        i.motion('arrived', 1)
        i.accept(evidence(4, 'bad', 'fixed'), decision('bad', insufficient=True), 4)
        self.assertFalse(i.accept(evidence(3, 'safe'), decision('safe'), 4))
        self.assertEqual(i.state, State.VERIFYING)

    def test_same_frame_alias_cannot_upgrade_bad_evidence(self):
        i = Incident('episode', 0, 10)
        frame = evidence()
        i.accept(frame, decision(insufficient=True), 2)
        self.assertFalse(i.accept(replace(frame, id='alias'), decision('alias', 'lying'), 2))

    def test_incident_generation_rejects_previous_response(self):
        i = Incident('episode', 0, 10, generation=1)
        self.assertFalse(i.accept(evidence(), decision(posture='lying'), 2))
        self.assertEqual(i.seen_ids, set())
        self.assertTrue(i.accept(replace(evidence(), generation=1), decision(posture='lying'), 2))

    def test_loss_tracks_all_states_and_equal_timestamp(self):
        tracker = LossTracker()
        tracker.update(Observation(evidence(0), 'visible'))
        self.assertTrue(tracker.update(Observation(evidence(3), 'unavailable')))
        for capture in (1, 2, 3):
            tracker.update(Observation(evidence(capture), 'visible'))
            self.assertTrue(tracker.lost)
        self.assertEqual(tracker.latest_capture, 3)
        self.assertEqual(len(tracker.history), 2)
        tracker.update(Observation(evidence(4), 'visible'))
        self.assertFalse(tracker.lost)
        self.assertTrue(tracker.update(Observation(evidence(6), 'occluded')))
        self.assertEqual(tracker.loss_sequence, 2)
        tracker.update(Observation(evidence(5), 'visible'))
        self.assertTrue(tracker.lost)

    def test_reset_rejects_old_callback_before_new_first_frame(self):
        tracker = LossTracker(episode='episode')
        tracker.update(Observation(evidence(0), 'visible'))
        tracker.reset(episode='new-episode')
        self.assertEqual(tracker.generation, 1)
        tracker.update(Observation(evidence(100), 'visible'))
        self.assertIsNone(tracker.last)
        new = replace(evidence(0), episode='new-episode', generation=1)
        tracker.update(Observation(new, 'visible'))
        self.assertEqual(tracker.last.evidence, new)
        tracker.update(Observation(replace(new, capture_time=2, received_time=2), 'occluded'))
        tracker.update(Observation(replace(evidence(200), generation=1), 'visible'))
        self.assertTrue(tracker.lost)

    def test_reset_same_episode_requires_new_generation(self):
        tracker = LossTracker()
        tracker.update(Observation(evidence(0), 'visible'))
        tracker.reset()
        tracker.update(Observation(evidence(10), 'visible'))
        self.assertIsNone(tracker.last)
        tracker.update(Observation(replace(evidence(0), generation=1), 'visible'))
        self.assertIsNotNone(tracker.last)

    def test_other_camera_cannot_reacquire_tracked_stream(self):
        tracker = LossTracker()
        tracker.update(Observation(evidence(0), 'visible'))
        tracker.update(Observation(evidence(3), 'occluded'))
        tracker.update(Observation(evidence(4, source='other'), 'visible'))
        self.assertTrue(tracker.lost)
        self.assertEqual(tracker.latest_capture, 3)

    def test_failed_motion_invalidates_prior_arrival(self):
        for status in ('moving', 'failed', 'timed_out', 'cancelled'):
            with self.subTest(status=status):
                i = Incident('episode', 0, 10)
                i.motion('arrived', 1)
                i.motion(status, 2)
                self.assertIsNone(i.arrived_at)
                self.assertFalse(i.accept(evidence(3), decision(), 3))
                i.tick(10)
                self.assertEqual(i.state, State.UNKNOWN)

    def test_motion_attempt_rejects_old_completion(self):
        i = Incident('episode', 0, 10)
        first = i.motion('moving', 0)
        i.motion('failed', 1, attempt_id=first)
        self.assertIsNone(i.motion('arrived', 2, attempt_id=first))
        second = i.motion('moving', 3)
        self.assertNotEqual(first, second)
        self.assertIsNone(i.motion('arrived', 4, attempt_id=first))
        self.assertIsNone(i.arrived_at)
        i.motion('arrived', 5, attempt_id=second)
        self.assertIsNone(i.motion('failed', 5, attempt_id=first))
        self.assertEqual(i.arrived_at, 5)
        self.assertFalse(i.accept(evidence(5, 'before'), decision('before'), 5))
        self.assertTrue(i.accept(evidence(6, 'fresh'), decision('fresh'), 6))

    def test_duplicate_arrival_does_not_reset_freshness_barrier(self):
        i = Incident('episode', 0, 10)
        attempt = i.motion('moving', 0)
        i.motion('arrived', 1, attempt_id=attempt)
        i.motion('arrived', 2, attempt_id=attempt)
        self.assertEqual(i.arrived_at, 1)
        self.assertTrue(i.accept(evidence(), decision(), 2))

    def test_danger_at_deadline_wins_regardless_of_timer_order(self):
        for timer_first in (False, True):
            with self.subTest(timer_first=timer_first):
                i = Incident('episode', 0, 10)
                if timer_first:
                    i.tick(10)
                frame = replace(evidence(9), received_time=10)
                self.assertTrue(i.accept(frame, decision(posture='lying'), 10))
                self.assertEqual(i.state, State.DANGER)
                self.assertEqual(sum(event['local_alert'] for event in i.events), 1)
                self.assertFalse(i.accept(frame, decision(posture='lying'), 10))
                i.tick(11)
                self.assertEqual(i.state, State.DANGER)
                self.assertEqual(len(i.events), 2 if timer_first else 1)
                self.assertEqual(i.events[-1]['alert_update'], timer_first)

    def test_boundary_insufficient_and_safe_do_not_prevent_unknown(self):
        for mode in ('safe', 'insufficient', 'stale', 'wrong_generation', 'low_quality'):
            with self.subTest(mode=mode):
                i = Incident('episode', 0, 10)
                i.motion('arrived', 1)
                frame = evidence(9)
                judgement = decision(posture='lying')
                if mode == 'safe':
                    judgement = decision()
                elif mode == 'insufficient':
                    judgement = decision(posture='lying', insufficient=True)
                elif mode == 'stale':
                    frame = evidence(2)
                elif mode == 'wrong_generation':
                    frame = replace(frame, generation=1)
                else:
                    frame = replace(frame, quality=.1)
                self.assertFalse(i.accept(frame, judgement, 10))
                self.assertEqual(i.state, State.UNKNOWN)

    def test_late_danger_does_not_rewrite_deadline_outcome(self):
        for timer_first in (False, True):
            i = Incident('episode', 0, 10)
            if timer_first:
                i.tick(10)
            self.assertFalse(i.accept(evidence(9), decision(posture='lying'), 10.001))
            self.assertEqual(i.state, State.UNKNOWN)

    def test_invalid_evidence_does_not_starve_timer(self):
        for frame in (replace(evidence(), quality=float('nan')),
                      replace(evidence(), quality=2),
                      replace(evidence(), received_time=1),
                      replace(evidence(), episode='other')):
            i = Incident('episode', 0, 10)
            self.assertFalse(i.accept(frame, decision(posture='lying'), 10))
            self.assertEqual(i.state, State.UNKNOWN)

    def test_clock_is_monotonic(self):
        i = Incident('episode', 0, 10)
        i.tick(5)
        with self.assertRaises(ValueError):
            i.accept(evidence(), decision(), 4)
        with self.assertRaises(ValueError):
            i.tick(float('nan'))


class AsyncIncidentTests(unittest.IsolatedAsyncioTestCase):
    async def test_vlm_cache_is_generation_scoped(self):
        from tracebot.providers.vlm import VLMAdapter

        async def transport(last, frame):
            return dict(person_visible=True,
                        observable_posture='lying' if frame.generation else 'upright_active',
                        distress_cues=[], insufficient_evidence=False, evidence_refs=[frame.id])

        adapter = VLMAdapter(transport)
        old = evidence()
        new = replace(old, generation=1)
        self.assertEqual((await adapter.infer('episode', None, old)).observable_posture, 'upright_active')
        result = await adapter.infer('episode', None, new)
        self.assertEqual(result.observable_posture, 'lying')
        self.assertEqual(await adapter.infer('episode', None, new), result)
        self.assertEqual(adapter.calls, 2)

    async def test_old_inflight_response_cannot_close_new_generation(self):
        import asyncio
        from tracebot.providers.vlm import VLMAdapter
        started, release = asyncio.Event(), asyncio.Event()

        async def transport(last, frame):
            started.set()
            await release.wait()
            return dict(person_visible=True, observable_posture='upright_active',
                        distress_cues=[], insufficient_evidence=False, evidence_refs=[frame.id])

        adapter = VLMAdapter(transport)
        old_frame = evidence()
        pending = asyncio.create_task(adapter.infer('episode', None, old_frame))
        await started.wait()
        current = Incident('episode', 0, 10, generation=1)
        current.motion('arrived', 1)
        release.set()
        self.assertFalse(current.accept(old_frame, await pending, 2))
        self.assertEqual(current.state, State.VERIFYING)
        current.tick(10)
        self.assertEqual(current.state, State.UNKNOWN)

    async def test_vlm_timeout_does_not_block_deadline(self):
        import asyncio
        from tracebot.providers.vlm import VLMAdapter, VLMConfig
        started, never = asyncio.Event(), asyncio.Event()

        async def transport(last, frame):
            started.set()
            await never.wait()

        adapter = VLMAdapter(transport, VLMConfig(timeout=.01))
        current = Incident('episode', 0, 10)
        pending = asyncio.create_task(adapter.infer('episode', None, evidence(9)))
        await started.wait()
        current.tick(10)
        self.assertEqual(current.state, State.UNKNOWN)
        result = await pending
        self.assertTrue(result.insufficient_evidence)
        self.assertFalse(current.accept(evidence(9), result, 10))
        self.assertEqual(current.state, State.UNKNOWN)
