"""RGB veto contract and both Harness closure paths, without model/Isaac calls."""
import asyncio
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib
from unittest.mock import patch

from haiclaw.core import Evidence
from haiclaw.harness import Harness
from haiclaw.providers.harness_fixture import FixtureTools
from haiclaw.providers.person_detector import PersonBox, PersonDetectionResult
from haiclaw.providers.person_gate import PersonGateAdapter, detector_config, with_person_gate
from haiclaw.providers.single_frame_vlm import Interpretation


def png_bytes():
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', 2, 2, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + b'\xff\xff\xff' * 2) * 2)) + chunk(b'IEND', b''))


def detected(evidence, **changes):
    result = dict(status='detected', reason='fixture RGB detector', evidence_id=evidence.id,
                  episode=evidence.episode, generation=evidence.generation, source=evidence.source,
                  capture_time=evidence.capture_time, artifact=evidence.artifact,
                  frame_sha256=hashlib.sha256(Path(evidence.artifact).read_bytes()).hexdigest(),
                  model_path='/fixture/person.pt', model_sha256='fixture-hash',
                  confidence_threshold=.25, image_size=640, device='cpu', frame_size=(2, 2),
                  boxes=(PersonBox((0., 0., 2., 2.), .9, 0),), latency_wall_seconds=.001)
    result.update(changes)
    return result


class RawAdapter:
    def __init__(self, posture='standing', *, limited=False, visible='yes'):
        self.posture, self.limited, self.visible = posture, limited, visible
        self.records = []

    async def infer(self, evidence):
        observation = Interpretation(self.visible, self.posture, (),
            ('occluded',) if self.limited else (), self.limited, (evidence.id,))
        record = dict(status='ok', raw_response='unaltered Qwen response',
                      interpretation=asdict(observation), latency_wall_seconds=.002)
        self.records.append(record)
        return observation, record


class Detector:
    def __init__(self, **changes):
        self.changes, self.calls = changes, 0

    async def infer(self, evidence):
        self.calls += 1
        return detected(evidence, **self.changes)


class SequencePlanner:
    def __init__(self, actions):
        self.actions, self.states = list(actions), []

    async def choose(self, state):
        self.states.append(state)
        tool, target = self.actions.pop(0)
        return dict(tool=tool, target=target, reason='Use fresh image or another available viewpoint.')


class GatedTools(FixtureTools):
    def __init__(self, adapter, image):
        super().__init__()
        self.adapter, self.image = adapter, image

    async def observe(self, camera, episode):
        evidence, _, _ = await super().observe(camera, episode)
        evidence = replace(evidence, artifact=str(self.image))
        observation, record = await self.adapter.infer(evidence)
        return evidence, observation, record


class PersonGateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.image = Path(self.temp.name) / 'rgb.png'
        self.image.write_bytes(png_bytes())
        self.evidence = Evidence('frame-1', 'episode-1', 'body', 1., 1., str(self.image))

    async def test_disabled_is_exact_passthrough_and_never_calls_detector(self):
        raw, detector = RawAdapter(), Detector()
        gate = PersonGateAdapter(raw, detector, enabled=False)
        observation, record = await gate.infer(self.evidence)
        self.assertIs(record, raw.records[0])
        self.assertEqual(observation.posture, 'standing')
        self.assertEqual(detector.calls, 0)
        self.assertEqual(gate.detector_calls, 0)
        self.assertEqual(gate.records, [])

    async def test_supported_dataclass_preserves_raw_and_effective_interpretation(self):
        class DataclassDetector(Detector):
            async def infer(self, evidence):
                return PersonDetectionResult(**detected(evidence))
        raw = RawAdapter('lying')
        gate = PersonGateAdapter(raw, DataclassDetector(), enabled=True)
        observation, record = await gate.infer(self.evidence)
        self.assertEqual(observation.posture, 'lying')
        self.assertEqual(record['interpretation'], raw.records[0]['interpretation'])
        self.assertEqual(record['raw_response'], raw.records[0]['raw_response'])
        self.assertNotIn('person_gate', raw.records[0])
        self.assertTrue(record['person_gate']['presence_corroborated'])
        self.assertFalse(record['person_gate']['posture_verified'])
        self.assertFalse(record['person_gate']['identity_verified'])
        self.assertEqual(record['effective_interpretation'], asdict(observation))

    async def test_non_support_and_all_provenance_mismatches_deny_claim(self):
        cases = [dict(status='not_detected', boxes=()), dict(status='multiple_people', boxes=({}, {})),
                 dict(status='error'), dict(status='unavailable'), dict(status='missing'),
                 dict(status='detected', boxes=()), dict(status='detected', boxes=None),
                 dict(status='detected', boxes='invalid'), dict(evidence_id='other'), dict(episode='old'),
                 dict(generation=1), dict(source='fixed'), dict(capture_time=0.), dict(frame_sha256='other'),
                 dict(artifact='/another/frame.png')]
        for changes in cases:
            with self.subTest(changes=changes):
                raw = RawAdapter('lying')
                effective, record = await PersonGateAdapter(raw, Detector(**changes), enabled=True).infer(self.evidence)
                self.assertEqual((effective.person_visible, effective.posture), ('uncertain', 'unknown'))
                self.assertTrue(effective.needs_more_observation)
                self.assertTrue(effective.observation_limitations)
                self.assertEqual(record['status'], 'ok')
                self.assertEqual(record['interpretation']['posture'], 'lying')
                self.assertFalse(record['person_gate']['presence_corroborated'])

    async def test_archive_candidates_are_retained_without_changing_gate_decision(self):
        raw_boxes = (PersonBox((0., 0., 2., 2.), .9, 0), PersonBox((0., 0., 1., 1.), .2, 0))
        gate = PersonGateAdapter(RawAdapter('lying'), Detector(raw_boxes=raw_boxes,
            archive_confidence=.05, confidence_threshold=.6, nms_iou=.7, max_det=300), enabled=True)
        observation, record = await gate.infer(self.evidence)
        self.assertEqual(observation.posture, 'lying')
        self.assertTrue(record['person_gate']['presence_corroborated'])
        self.assertEqual(len(record['person_gate']['detector']['boxes']), 1)
        self.assertEqual(len(record['person_gate']['detector']['raw_boxes']), 2)

    async def test_empty_detector_result_is_denied_not_absence(self):
        class Empty(Detector):
            async def infer(self, evidence):
                return {}
        observation, record = await PersonGateAdapter(RawAdapter(), Empty(), enabled=True).infer(self.evidence)
        self.assertEqual(observation.person_visible, 'uncertain')
        self.assertFalse(record['person_gate']['presence_corroborated'])

    async def test_detector_exception_is_separate_from_successful_qwen(self):
        class Broken(Detector):
            async def infer(self, evidence):
                raise RuntimeError('fixture detector failed')
        observation, record = await PersonGateAdapter(RawAdapter(), Broken(), enabled=True).infer(self.evidence)
        self.assertEqual(record['status'], 'ok')
        self.assertEqual(record['person_gate']['detector']['status'], 'error')
        self.assertEqual(observation.posture, 'unknown')

    async def test_changed_frame_cannot_support_prior_qwen_interpretation(self):
        image = self.image
        class Mutating(Detector):
            async def infer(self, evidence):
                response = detected(evidence)
                image.write_bytes(png_bytes() + b'changed')
                return response
        observation, record = await PersonGateAdapter(RawAdapter(), Mutating(), enabled=True).infer(self.evidence)
        self.assertEqual(observation.posture, 'unknown')
        self.assertFalse(record['person_gate']['presence_corroborated'])

    async def test_positive_detector_never_upgrades_unknown_or_limited_qwen(self):
        for raw in (RawAdapter('unknown', visible='uncertain'), RawAdapter('lying', limited=True)):
            with self.subTest(raw=raw.__dict__):
                observation, record = await PersonGateAdapter(raw, Detector(), enabled=True).infer(self.evidence)
                self.assertEqual(asdict(observation), raw.records[0]['interpretation'])
                self.assertFalse(record['person_gate']['interpretation_changed'])

    async def test_detector_timeout_blocks_and_prevents_queued_retries(self):
        class Stalled(Detector):
            async def infer(self, evidence):
                self.calls += 1
                await asyncio.sleep(10)
        raw, detector = RawAdapter(), Stalled()
        gate = PersonGateAdapter(raw, detector, enabled=True, timeout=.01)
        first, first_record = await gate.infer(self.evidence)
        second, second_record = await gate.infer(replace(self.evidence, id='next'))
        self.assertEqual(first.posture, 'unknown')
        self.assertEqual(second.posture, 'unknown')
        self.assertEqual(first_record['person_gate']['detector']['status'], 'timeout')
        self.assertEqual(second_record['person_gate']['detector']['status'], 'unavailable')
        self.assertEqual(detector.calls, 1)
        self.assertEqual(gate.detector_calls, 1)
        self.assertEqual(len(raw.records), 2)

    async def test_explicit_cancellation_is_not_successful_gate_output(self):
        started = asyncio.Event()
        class Slow(Detector):
            async def infer(self, evidence):
                started.set()
                await asyncio.sleep(10)
        gate = PersonGateAdapter(RawAdapter(), Slow(), enabled=True)
        task = asyncio.create_task(gate.infer(self.evidence))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(gate.records, [])

    async def test_harness_blocks_both_inspection_and_danger_closure(self):
        for posture in ('standing', 'lying'):
            with self.subTest(posture=posture):
                gate = PersonGateAdapter(RawAdapter(posture), Detector(status='not_detected', boxes=()), enabled=True)
                tools = GatedTools(gate, self.image)
                planner = SequencePlanner([('inspect', 'east_inspection'), ('observe', 'body'), ('escalate', '')])
                result = await Harness('ep', planner, tools, finish_on_inspection_answer=True).run()
                self.assertIsNone(result['inspection_answer'])
                self.assertEqual(result['state'], 'escalated_unknown')
                self.assertFalse(result['evidence_records'][0]['accepted'])
                self.assertEqual(result['context_snapshot']['payload']['questions']['presence']['state'], 'unresolved')

    async def test_supported_and_off_paths_retain_standing_and_lying_semantics(self):
        for enabled in (False, True):
            for posture in ('standing', 'lying'):
                with self.subTest(enabled=enabled, posture=posture):
                    gate = PersonGateAdapter(RawAdapter(posture), Detector(), enabled=enabled)
                    tools = GatedTools(gate, self.image)
                    planner = SequencePlanner([('inspect', 'east_inspection'), ('observe', 'body')])
                    result = await Harness('ep', planner, tools, finish_on_inspection_answer=True).run()
                    self.assertIsNotNone(result['inspection_answer'])
                    self.assertEqual(result['state'], 'danger_confirmed' if posture == 'lying' else 'escalated_unknown')
                    self.assertNotEqual(result['state'], 'resolved_safe')

    async def test_gate_rejection_releases_arrival_and_allows_different_view(self):
        gate = PersonGateAdapter(RawAdapter(), Detector(status='not_detected', boxes=()), enabled=True)
        tools = GatedTools(gate, self.image)
        planner = SequencePlanner([('inspect', 'east_inspection'), ('observe', 'body'),
                                   ('inspect', 'southeast_inspection'), ('observe', 'body'), ('escalate', '')])
        result = await Harness('ep', planner, tools, finish_on_inspection_answer=True).run()
        self.assertEqual(tools.moves, ['east_inspection', 'southeast_inspection'])
        self.assertIsNone(planner.states[2]['required_next_evidence'])
        self.assertIn(('inspect', 'southeast_inspection'),
                      [(tool['tool'], tool['target']) for tool in planner.states[2]['available_tools']])
        self.assertFalse(planner.states[2]['camera_feedback']['body']['clear_subject'])
        self.assertIsNone(result['inspection_answer'])
        self.assertFalse(any(event['kind'] == 'rejected' for event in result['trace']))
        public = str(planner.states)
        for forbidden in (str(self.image), 'frame_sha256', 'model_path', 'actual_posture', 'segmentation'):
            self.assertNotIn(forbidden, public)

    async def test_late_detector_output_cannot_close_after_harness_deadline(self):
        class Late(Detector):
            async def infer(self, evidence):
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    await asyncio.sleep(.02)
                return detected(evidence)
        gate = PersonGateAdapter(RawAdapter('lying'), Late(), enabled=True)
        tools = GatedTools(gate, self.image)
        planner = SequencePlanner([('observe', 'body')])
        harness = Harness('ep', planner, tools, budget=.03, finish_on_inspection_answer=True)
        result = await harness.run()
        await asyncio.sleep(.04)
        self.assertEqual(result['state'], 'escalated_unknown')
        self.assertIsNone(result['inspection_answer'])
        self.assertEqual(harness.memory, [])
        self.assertEqual(harness.evidence_records, [])


class PersonGateConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.weights = self.root / 'fixture.pt'
        self.weights.write_bytes(b'local fixture')
        self.path = self.root / 'config.json'
        self.config = dict(model_path=str(self.weights),
            model_sha256=hashlib.sha256(self.weights.read_bytes()).hexdigest(), confidence=.6,
            image_size=640, device='cpu', timeout_seconds=10)

    def read(self, config):
        self.path.write_text(json.dumps(config))
        return detector_config(self.path)

    def test_legacy_config_normalizes_explicit_freeze_parameters(self):
        config = self.read(dict(self.config, confidence=.25))
        self.assertEqual((config['archive_confidence'], config['nms_iou'], config['max_det']), (.25, .7, 300))
        self.assertNotIn('archive_confidence', json.loads(self.path.read_text()))

    def test_archive_config_is_passed_to_detector_unchanged(self):
        config = self.read(dict(self.config, archive_confidence=.05, nms_iou=.7, max_det=300))
        with patch('haiclaw.providers.person_detector.LocalPersonDetector') as constructor:
            gate = with_person_gate(RawAdapter(), config)
        constructor.assert_called_once_with(str(self.weights), confidence=.6, image_size=640,
            device='cpu', archive_confidence=.05, nms_iou=.7, max_det=300)
        self.assertTrue(gate.enabled)
        self.assertEqual(gate.timeout, 10)

    def test_bad_archive_config_does_not_freeze(self):
        for field, value in [('archive_confidence', .61), ('archive_confidence', 0),
                             ('archive_confidence', None), ('archive_confidence', True),
                             ('archive_confidence', float('nan')), ('nms_iou', 0),
                             ('nms_iou', 1.01), ('nms_iou', True), ('max_det', 0),
                             ('max_det', True), ('max_det', 300.), ('max_det', 10001),
                             ('typo_archive_confidence', .05)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.read(dict(self.config, **{field: value}))
        for malformed in ([], None, {}):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                self.read(malformed)


if __name__ == '__main__':
    unittest.main()
