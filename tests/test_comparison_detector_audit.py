"""Post-trial archive integrity and frozen recipe tests; no model or simulator."""
import asyncio
import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tracebot.core import Evidence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import comparison_detector_audit as audit
import run_real2sim_comparison as runner


class Detector:
    def __init__(self, factory):
        self.factory, self.calls = factory, []

    async def infer(self, evidence):
        self.calls.append(evidence)
        return self.factory(evidence)


class DetectorArchiveTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / 'detector_audit.json'
        self.checkpoint = self.root / 'fixture.pt'
        self.checkpoint.write_bytes(b'checkpoint provenance only')
        self.config = dict(model_path=str(self.checkpoint),
            model_sha256=hashlib.sha256(self.checkpoint.read_bytes()).hexdigest(),
            confidence=.6, archive_confidence=.05, nms_iou=.7, max_det=300,
            image_size=640, device='cpu', timeout_seconds=1)

    def evidence(self, index=0):
        frame = self.root / f'frame-{index}.png'
        # The fake detector only hashes the exact artifact; no image decoder.
        frame.write_bytes(f'fixture camera bytes {index}'.encode())
        return Evidence(f'e-{index}', 'fixture-episode', 'body', float(index),
                        float(index), str(frame), generation=2)

    def detection(self, evidence, **changes):
        value = dict(status='detected', reason='fixture only', evidence_id=evidence.id,
            episode=evidence.episode, generation=evidence.generation, source=evidence.source,
            capture_time=evidence.capture_time, artifact=str(evidence.artifact),
            frame_sha256=hashlib.sha256(Path(evidence.artifact).read_bytes()).hexdigest(),
            model_path=self.config['model_path'], model_sha256=self.config['model_sha256'],
            confidence_threshold=.6, archive_confidence=.05, nms_iou=.7, max_det=300,
            image_size=640, device='cpu', frame_size=[100, 100], latency_wall_seconds=.1,
            raw_boxes_stage='post_nms_person_candidates', raw_boxes_at_capacity=False,
            boxes=[dict(xyxy=[1, 1, 10, 10], confidence=.8, class_id=0)],
            raw_boxes=[dict(xyxy=[1, 1, 10, 10], confidence=.8, class_id=0),
                       dict(xyxy=[20, 20, 30, 30], confidence=.1, class_id=0)])
        value.update(changes)
        return value

    async def test_archives_every_capture_including_qwen_failures_without_changing_online_costs(self):
        evidence = [self.evidence(i) for i in range(3)]
        report = dict(captured_evidence=[asdict(e) for e in evidence], evidence_records=[
            dict(evidence=asdict(evidence[0]), inference=dict(status='invalid'), valid=False)],
            wall_seconds=9, person_gate_cost=dict(enabled=False, calls=0, latency_wall_seconds=0),
            planner_call_latencies=[2, 3], vision_call_latencies=[4])
        original = copy.deepcopy(report)
        detector = Detector(self.detection)
        result = await audit.archive_frames(report, self.config, self.output, self.root, detector)
        saved = json.loads(self.output.read_text())
        self.assertEqual(report, original)
        self.assertEqual(len(detector.calls), 3)
        self.assertEqual(result['posttrial_calls'], 3)
        self.assertTrue(saved['complete'])
        self.assertTrue(saved['excluded_from_online_cost'])
        self.assertEqual([row['evidence']['id'] for row in saved['rows']], ['e-0', 'e-1', 'e-2'])
        self.assertTrue(all(row['origin'] == 'posttrial_only' for row in saved['rows']))

    async def test_matching_online_record_is_reused_with_all_candidates(self):
        evidence = self.evidence()
        detection = self.detection(evidence)
        report = dict(captured_evidence=[asdict(evidence)], evidence_records=[
            dict(evidence=asdict(evidence), inference=dict(person_gate=dict(detector=detection)))])
        detector = Detector(self.detection)
        result = await audit.archive_frames(report, self.config, self.output, self.root, detector)
        self.assertEqual(detector.calls, [])
        self.assertEqual(result['reused_online'], 1)
        saved = json.loads(self.output.read_text())
        self.assertEqual(saved['rows'][0]['detector'], detection)

    async def test_wrong_online_binding_or_recipe_is_recomputed_not_reused(self):
        evidence = self.evidence()
        cases = [dict(episode='old'), dict(generation=0), dict(evidence_id='different'),
                 dict(source='fixed'), dict(capture_time=99), dict(artifact='/old/frame.png'),
                 dict(frame_sha256='different'), dict(model_sha256='different'),
                 dict(model_path='/different/model.pt'), dict(confidence_threshold=.25),
                 dict(archive_confidence=.25), dict(nms_iou=.5), dict(max_det=30),
                 dict(image_size=320), dict(device='cuda'), dict(raw_boxes=None)]
        for index, changes in enumerate(cases):
            with self.subTest(changes=changes):
                report = dict(captured_evidence=[asdict(evidence)], evidence_records=[dict(
                    evidence=asdict(evidence), inference=dict(person_gate=dict(detector=self.detection(evidence, **changes))))])
                detector = Detector(self.detection)
                result = await audit.archive_frames(report, self.config,
                    self.root / f'audit-{index}.json', self.root, detector)
                self.assertEqual(result['reused_online'], 0)
                self.assertEqual(len(detector.calls), 1)

    async def test_invalid_last_result_is_saved_but_archive_not_complete(self):
        evidence = self.evidence()
        detector = Detector(lambda e: self.detection(e, status='error', reason='fixture inference error'))
        with self.assertRaises(RuntimeError):
            await audit.archive_frames(dict(captured_evidence=[asdict(evidence)]), self.config,
                                       self.output, self.root, detector)
        saved = json.loads(self.output.read_text())
        self.assertFalse(saved['complete'])
        self.assertEqual(len(saved['rows']), 1)
        self.assertEqual(saved['rows'][0]['detector']['status'], 'error')

    async def test_missing_capture_inventory_fails_and_leaves_audit(self):
        evidence = self.evidence()
        report = dict(evidence_records=[dict(evidence=asdict(evidence), inference=dict(status='error'))])
        detector = Detector(self.detection)
        with self.assertRaises((ValueError, RuntimeError)):
            await audit.archive_frames(report, self.config, self.output, self.root, detector)
        self.assertTrue(self.output.exists())
        self.assertFalse(json.loads(self.output.read_text())['complete'])
        self.assertEqual(detector.calls, [])

    async def test_missing_frame_fails_and_preserves_error_in_audit(self):
        evidence = self.evidence()
        detection = self.detection(evidence)
        Path(evidence.artifact).unlink()
        report = dict(captured_evidence=[asdict(evidence)], evidence_records=[
            dict(evidence=asdict(evidence), inference=dict(person_gate=dict(detector=detection)))])
        with self.assertRaises((OSError, ValueError, RuntimeError)):
            await audit.archive_frames(report, self.config, self.output, self.root, Detector(self.detection))
        saved = json.loads(self.output.read_text())
        self.assertFalse(saved['complete'])
        self.assertEqual(len(saved['rows']), 1)
        self.assertIn('audit_error', saved['rows'][0])

    async def test_cancellation_does_not_mark_archive_complete(self):
        evidence = self.evidence()
        started = asyncio.Event()
        class Stalled:
            async def infer(self, frame):
                started.set()
                await asyncio.sleep(10)
        task = asyncio.create_task(audit.archive_frames(
            dict(captured_evidence=[asdict(evidence)]), self.config, self.output, self.root, Stalled()))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        saved = json.loads(self.output.read_text())
        self.assertFalse(saved['complete'])

    async def test_existing_audit_cannot_be_overwritten(self):
        self.output.write_text('preserve prior audit')
        detector = Detector(self.detection)
        with self.assertRaises(FileExistsError):
            await audit.archive_frames(dict(captured_evidence=[]), self.config, self.output, self.root, detector)
        self.assertEqual(self.output.read_text(), 'preserve prior audit')
        self.assertEqual(detector.calls, [])


class ConfirmatoryRecipeTests(unittest.TestCase):
    def setUp(self):
        self.manifest = dict(evaluation_role='confirmatory', repetitions=1,
            preflight_complete=True, archive_all_detector_frames=True, scenarios=[
                dict(actual_posture=posture, answerable=index < 8)
                for posture in ('standing', 'lying') for index in range(10)])
        self.config = dict(fixed_gate=True, evaluator_capture=True, evaluator_calibration={'fixture': True})
        self.detector = dict(confidence=.6, archive_confidence=.05, nms_iou=.7, max_det=300)

    def test_frozen_sixty_percent_recipe_is_exact(self):
        runner.validate_confirmatory_gate(self.manifest, self.config, self.detector)
        for key, value in (('confidence', .25), ('archive_confidence', .1), ('nms_iou', .5), ('max_det', 100)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                runner.validate_confirmatory_gate(self.manifest, self.config, dict(self.detector, **{key: value}))

    def test_preflight_archive_and_balanced_postures_are_required(self):
        cases = [dict(preflight_complete=False), dict(archive_all_detector_frames=False),
                 dict(repetitions=2), dict(scenarios=self.manifest['scenarios'][:-1])]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                runner.validate_confirmatory_gate(dict(self.manifest, **changes), self.config, self.detector)
        altered = copy.deepcopy(self.manifest)
        altered['scenarios'][0]['answerable'] = False
        with self.assertRaises(ValueError):
            runner.validate_confirmatory_gate(altered, self.config, self.detector)


class DetectorArchiveRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_gate_verification_exception_leaves_failed_physical_sample(self):
        tools = object.__new__(runner.TrackedTools)
        tools.fixed_gate = True
        tools.pose_samples = []
        tools.gate_samples = [dict(ready=True)]
        tools.remote = AsyncMock(side_effect=RuntimeError('physics tensor unavailable'))
        state = dict(now=12.5, pose=[0., 0., 0.])
        with patch.object(runner.Real2SimTools, 'snapshot', AsyncMock(return_value=state)):
            with self.assertRaisesRegex(RuntimeError, 'physics tensor unavailable'):
                await tools.snapshot()
        self.assertEqual(len(tools.gate_samples), 2)
        self.assertFalse(tools.gate_samples[-1]['ready'])
        self.assertIn('physics tensor unavailable', tools.gate_samples[-1]['error'])
        self.assertEqual(tools.pose_samples, [dict(time=12.5, pose=[0., 0., 0.])])

    async def test_archive_failure_keeps_online_result_and_blocks_resume(self):
        scene = dict(scenario_id='condition-1', condition='fixture', actual_posture='lying',
                     answerable=True, geometry_evidence='fixture-only')
        cfg = dict(locations={'view': {}}, budget_seconds=300, wall_budget_seconds=900,
                   operation_timeout_seconds=180, motion_timeout_seconds=240,
                   max_steps=12, max_evidence_age_seconds=45, view_retry_budget=2,
                   evaluator_capture=True, evaluator_calibration={'fixture': True})
        frozen = dict(manifest=dict(scenarios=[scene], evaluation_role='development',
                                   archive_all_detector_frames=True),
                      config=cfg, model_config={'model': 'same-qwen'}, person_gate_config={})
        entry = dict(trial_id='t0000', scene_id='condition-1', scenario_id='group-1',
                     repetition_id='condition-1:0', policy='agent_gate_off')
        tools = MagicMock(motion_records=[], pose_samples=[], captured_evidence=[], gate_samples=[])
        tools.distance.return_value = 1.25
        policy = MagicMock(records=[])
        host = MagicMock()
        host.run = AsyncMock()
        host.report.return_value = dict(wall_seconds=7, trace=[])
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(runner, 'prepare_scene', AsyncMock(return_value={})), \
             patch.object(runner, 'remote', AsyncMock()), \
             patch.object(runner, 'make_adapter', return_value=MagicMock()), \
             patch.object(runner, 'TrackedTools', return_value=tools), \
             patch.object(runner, 'OllamaPlanner', return_value=policy), \
             patch.object(runner, 'Harness', return_value=host), \
             patch('tracebot.comparison_records.normalize_report',
                   side_effect=lambda report, **kwargs: dict(kwargs, status='completed', wall_latency_s=7)), \
             patch.object(audit, 'archive_frames', AsyncMock(side_effect=RuntimeError('archive fixture failure'))):
            with self.assertRaisesRegex(RuntimeError, 'archive fixture failure'):
                await runner.run_trial(Path(temp), frozen, entry)
            trial = Path(temp) / 'trials' / 't0000'
            online_record = json.loads((trial / 'record.json').read_text())
            self.assertEqual(online_record['status'], 'completed')
            self.assertEqual(online_record['wall_latency_s'], 7)
            self.assertEqual(online_record['person_gate_cost']['calls'], 0)
            marker = json.loads((trial / 'integrity_or_availability_error.json').read_text())
            self.assertTrue(marker['exclude_from_confirmatory_claims'])
            self.assertEqual(marker['stage'], 'posttrial_detector_archive')


class GroundingAnnotationCompletionTests(unittest.TestCase):
    def claim(self, trial_id='t0001', answer='lying', **extra):
        return dict(trial_id=trial_id, inspection_question_answer=answer,
                    normalization={'answer_evidence_ids': [trial_id+'-frame']}, **extra)

    def test_wrong_late_or_failed_assertions_still_need_human_posture_review(self):
        for extra in (dict(actual_posture='standing'), dict(status='error'),
                      dict(status='timeout'), dict(answer_wall_s=9999)):
            with self.subTest(extra=extra):
                row = self.claim(**extra)
                annotations = {'t0001': dict(claim_target_present=True, claim_observed_posture=None)}
                self.assertFalse(runner.grounding_annotations_complete([row], annotations))

    def test_only_explicit_human_posture_labels_complete_positive_target_assertion(self):
        rows = [self.claim()]
        for posture in ('standing', 'lying', 'unreadable'):
            with self.subTest(posture=posture):
                annotations = {'t0001': dict(claim_target_present=True, claim_observed_posture=posture)}
                self.assertTrue(runner.grounding_annotations_complete(rows, annotations))
        for posture in (None, '', 'unknown', 'uncertain'):
            with self.subTest(posture=posture):
                annotations = {'t0001': dict(claim_target_present=True, claim_observed_posture=posture)}
                self.assertFalse(runner.grounding_annotations_complete(rows, annotations))

    def test_absent_target_assertions_and_nonclaims_need_no_human_posture_label(self):
        rows = [self.claim('absent', 'standing'), self.claim('abstain', 'unknown')]
        self.assertTrue(runner.grounding_annotations_complete(rows,
            {'absent': dict(claim_target_present=False, claim_observed_posture=None)}))
        self.assertTrue(runner.grounding_annotations_complete(rows[1:], {}))

    def test_missing_presence_remains_incomplete_even_with_human_posture(self):
        row = self.claim(answer='standing')
        for annotations in ({}, {'t0001': dict(claim_target_present=None, claim_observed_posture='standing')}):
            with self.subTest(annotations=annotations):
                self.assertFalse(runner.grounding_annotations_complete([row], annotations))

    def test_one_unreviewed_assertion_prevents_full_completion(self):
        rows = [self.claim('reviewed', 'lying'), self.claim('unreviewed', 'standing')]
        annotations = {'reviewed': dict(claim_target_present=True, claim_observed_posture='lying'),
                       'unreviewed': dict(claim_target_present=True, claim_observed_posture=None)}
        self.assertFalse(runner.grounding_annotations_complete(rows, annotations))

    def test_claim_without_cited_frames_is_known_unsupported_not_pending_review(self):
        row = dict(trial_id='t0001', inspection_question_answer='lying',
                   normalization={'answer_evidence_ids': []})
        self.assertTrue(runner.grounding_annotations_complete([row], {}))


if __name__ == '__main__':
    unittest.main()
