"""Matched-arm execution and immutable detector provenance fixtures; no servers."""
import asyncio
from contextlib import redirect_stdout
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import run_real2sim_comparison as runner


def manifest():
    return dict(policies=['agent_gate_off', 'agent_gate_on'], repetitions=2, seed=314,
                evaluation_role='development', scenarios=[dict(
                    scenario_id=f'placement-{i}', condition='visible', actual_posture='standing',
                    answerable=True, position=[i, 0, .03], rotation=[0, 0, 0],
                    geometry_evidence='fixture-only') for i in range(4)])


def config():
    return dict(view_retry_budget=2, max_steps=12, budget_seconds=300,
                wall_budget_seconds=900, operation_timeout_seconds=180,
                motion_timeout_seconds=240, max_evidence_age_seconds=45,
                fixed_order=['entrance', 'west', 'door'],
                locations={name: {'yaw': 0} for name in ('entrance', 'west', 'door')})


class GateFreezeTests(unittest.TestCase):
    def setUp(self):
        temp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root, self.out = temp / 'workspace', temp / 'frozen'
        self.root.mkdir()
        self.sources = [self.root / 'scripts' / name for name in ('real2sim_navigation.py', 'real2sim_monitor_scene.py')]
        for source in self.sources:
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('# gate freeze fixture\n')
        self.checkpoint = self.root / 'model.pt'
        self.checkpoint.write_bytes(b'fixture-only; never passed to torch')
        self.detector = dict(model_path=str(self.checkpoint), model_sha256=runner.digest(self.checkpoint),
                             confidence=.25, image_size=640, device='cpu', timeout_seconds=10)
        runtime = dict(files={str(p.relative_to(self.root)): runner.digest(p) for p in self.sources})
        identity = dict(model={'digest': 'qwen-fixture'}, ollama={'version': 'fixture'})
        self.enterContext(patch.object(runner, 'ROOT', self.root))
        self.enterContext(patch.object(runner, 'source_files', return_value=self.sources))
        self.enterContext(patch.object(runner, 'model_identity', return_value=identity))
        self.enterContext(patch.object(runner, 'remote', AsyncMock(return_value=runtime)))
        self.versions = self.enterContext(patch.object(runner, 'version', side_effect=lambda name: name + '-fixture'))
        for name, value in [('manifest', manifest()), ('config', config()), ('model', {'model': 'qwen-fixture'}), ('detector', self.detector)]:
            runner.write_json(self.root / (name + '.json'), value)
        self.args = SimpleNamespace(output=self.out, manifest=self.root / 'manifest.json',
                                    config=self.root / 'config.json', model=self.root / 'model.json',
                                    person_gate_config=self.root / 'detector.json')

    def freeze(self):
        with redirect_stdout(io.StringIO()):
            runner.freeze(self.args)

    def test_gate_pairs_are_complete_reproducible_and_order_balanced(self):
        schedule = runner.schedule_trials(manifest())
        self.assertEqual(schedule, runner.schedule_trials(manifest()))
        self.assertEqual(len(schedule), 16)
        first = []
        for a, b in zip(schedule[::2], schedule[1::2]):
            self.assertEqual((a['scene_id'], a['repetition_id']), (b['scene_id'], b['repetition_id']))
            self.assertEqual({a['policy'], b['policy']}, {'agent_gate_off', 'agent_gate_on'})
            first.append(a['policy'])
        self.assertEqual(first.count('agent_gate_on'), first.count('agent_gate_off'))

    def test_freeze_requires_explicit_detector_config(self):
        self.args.person_gate_config = None
        with self.assertRaisesRegex(ValueError, 'person-gate-config'):
            self.freeze()
        self.assertFalse(self.out.exists())

    def test_freeze_rejects_mixed_unmatched_gate_arm(self):
        value = manifest()
        value['policies'] = ['trace', 'agent_gate_on']
        runner.write_json(self.args.manifest, value)
        with self.assertRaisesRegex(ValueError, 'exactly its two'):
            self.freeze()
        self.assertFalse(self.out.exists())

    def test_checkpoint_mismatch_rejected_before_freeze(self):
        self.checkpoint.write_bytes(b'changed checkpoint')
        with self.assertRaisesRegex(ValueError, 'checkpoint hash mismatch'):
            self.freeze()
        self.assertFalse(self.out.exists())

    def test_freeze_stores_detector_config_and_live_version_mismatch_is_rejected(self):
        self.freeze()
        frozen = runner.verify_frozen(self.out, live=True)
        self.assertEqual(frozen['person_gate_config'], dict(self.detector, archive_confidence=.25,nms_iou=.7,max_det=300))
        self.assertEqual(frozen['detector_packages']['ultralytics'], 'ultralytics-fixture')
        self.versions.side_effect = lambda name: 'changed' if name == 'torch' else name + '-fixture'
        with self.assertRaisesRegex(RuntimeError, 'dependency version changed'):
            runner.verify_frozen(self.out, live=True)

    def test_changed_checkpoint_after_freeze_is_rejected(self):
        self.freeze()
        self.checkpoint.write_bytes(b'changed after freeze')
        with self.assertRaisesRegex(RuntimeError, 'Detector checkpoint changed'):
            runner.verify_frozen(self.out, live=True)


class GatePlannerParityTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_gate_arms_construct_same_planner_and_wrap_only_on(self):
        m, cfg = manifest(), config()
        frozen = dict(manifest=m, config=cfg, model_config={'model': 'same-qwen'}, person_gate_config={'fixture': True})
        entries = runner.schedule_trials(m)[:2]
        tools = MagicMock(motion_records=[], pose_samples=[])
        tools.distance.return_value = 0
        policy = MagicMock(records=[])
        harness = MagicMock()
        harness.run = AsyncMock()
        harness.report.return_value = dict(wall_seconds=.2, trace=[])
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(runner, 'prepare_scene', AsyncMock(return_value={'fixture': True})), \
             patch.object(runner, 'remote', AsyncMock()), \
             patch.object(runner, 'make_adapter', return_value=MagicMock()), \
             patch.object(runner, 'with_person_gate', return_value=MagicMock(detector_calls=0, detector_latencies=[])) as gate, \
             patch.object(runner, 'configure_detector_environment') as environment, \
             patch.object(runner, 'TrackedTools', return_value=tools), \
             patch.object(runner, 'OllamaPlanner', return_value=policy) as planner, \
             patch.object(runner, 'FixedOrderVerificationPlanner') as fixed, \
             patch.object(runner, 'CameraOnlyPlanner') as camera, \
             patch.object(runner, 'Harness', return_value=harness) as host, \
             patch('haiclaw.comparison_records.normalize_report', side_effect=lambda report, **kwargs: dict(kwargs)):
            for entry in entries:
                await runner.run_trial(Path(temp), frozen, entry)
            self.assertEqual(planner.call_count, 2)
            self.assertTrue(all(call.args == (frozen['model_config'],) for call in planner.call_args_list))
            fixed.assert_not_called()
            camera.assert_not_called()
            gate.assert_called_once()
            environment.assert_called_once()
            self.assertEqual(gate.call_args.args[1], frozen['person_gate_config'])
            self.assertEqual(host.call_args_list[0].kwargs, host.call_args_list[1].kwargs | {'emit': host.call_args_list[0].kwargs['emit']})


if __name__ == '__main__':
    unittest.main()
