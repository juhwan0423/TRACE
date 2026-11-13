"""CPU fixtures for immutable schedules and missing planned-trial accounting."""
import copy
import asyncio
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import run_real2sim_comparison as runner


def manifest():
    return dict(policies=['fixed_order', 'trace'], repetitions=2, seed=123,
                evaluation_role='development', scenarios=[dict(
                    scenario_id=f's{i}', condition='visible', actual_posture='standing',
                    answerable=True, position=[i, 0, .03], rotation=[0, 0, 0],
                    geometry_evidence='external-fixture-only') for i in range(3)])


def config():
    return dict(view_retry_budget=2, max_steps=12, budget_seconds=300,
                wall_budget_seconds=900, operation_timeout_seconds=180,
                motion_timeout_seconds=240, max_evidence_age_seconds=45,
                fixed_order=['west', 'door', 'entrance'],
                locations={name: dict(yaw=0, description='Public fixed viewpoint')
                           for name in ('west', 'door', 'entrance')})


def frozen_fixture():
    m = manifest()
    return dict(manifest=m, config=config(), model_config={},
                schedule=runner.schedule_trials(m), runtime_provenance={'fixture': True})


class ScheduleTests(unittest.TestCase):
    def test_complete_paired_counterbalanced_reproducible_schedule(self):
        m = manifest()
        schedule = runner.schedule_trials(m)
        self.assertEqual(schedule, runner.schedule_trials(m))
        self.assertEqual(len(schedule), 12)
        self.assertEqual(len({r['trial_id'] for r in schedule}), 12)
        first = []
        for a, b in zip(schedule[::2], schedule[1::2]):
            self.assertEqual((a['scenario_id'], a['repetition_id']), (b['scenario_id'], b['repetition_id']))
            self.assertEqual({a['policy'], b['policy']}, {'trace', 'fixed_order'})
            first.append(a['policy'])
        self.assertEqual(first.count('trace'), first.count('fixed_order'))

    def test_truth_changes_do_not_change_schedule_or_goal(self):
        original = manifest()
        changed = copy.deepcopy(original)
        for s in changed['scenarios']:
            s.update(position=[-5, -4, .03], actual_posture='lying', answerable=False)
        self.assertEqual(runner.schedule_trials(original), runner.schedule_trials(changed))
        self.assertIn('no person-loss event', runner.GOAL)

    def test_posture_variants_share_placement_cluster_without_colliding_pairs(self):
        m = manifest()
        variants = []
        for original in m['scenarios']:
            for posture in ('standing', 'lying'):
                variants.append(dict(original, scenario_id=original['scenario_id'] + '-' + posture,
                                     independent_group_id=original['scenario_id'], actual_posture=posture))
        m['scenarios'] = variants
        schedule = runner.schedule_trials(m)
        self.assertEqual(len(schedule), 24)
        self.assertEqual(len({r['scenario_id'] for r in schedule}), 3)
        self.assertEqual(len({r['scene_id'] for r in schedule}), 6)
        self.assertEqual(len({(r['scenario_id'], r['repetition_id'], r['policy']) for r in schedule}), 24)
        for a, b in zip(schedule[::2], schedule[1::2]):
            self.assertEqual(a['scene_id'], b['scene_id'])
            self.assertEqual(a['scenario_id'], b['scenario_id'])
            self.assertEqual(a['repetition_id'], b['repetition_id'])
            self.assertTrue(a['repetition_id'].startswith(a['scene_id'] + ':'))

    def test_duplicate_scene_and_missing_geometry_rejected(self):
        m = manifest()
        m['scenarios'][1]['scenario_id'] = m['scenarios'][0]['scenario_id']
        with self.assertRaises(ValueError):
            runner.schedule_trials(m)
        m = manifest()
        m['scenarios'][0]['geometry_evidence'] = ''
        with self.assertRaises(ValueError):
            runner.schedule_trials(m)

    def test_completely_missing_scenario_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            m = manifest()
            runner.write_json(out / 'protocol.json', dict(manifest=m, schedule=runner.schedule_trials(m)))
            summary = runner.summarize(out, verify=False)
            self.assertEqual(summary['planned_trials'], 12)
            self.assertEqual(len(summary['missing_planned_trials']), 12)
            self.assertFalse(summary['comparison_complete'])
            self.assertFalse(summary['schedule_complete'])

    def test_external_truth_relative_clocks_and_no_safe_claim(self):
        scene = manifest()['scenarios'][0]
        truth = runner.external_truth(scene, {'budget_seconds': 300}, 'development')
        self.assertEqual(truth['incident_start_sim_s'], 0)
        self.assertEqual(truth['deadline_sim_s'], 300)
        self.assertIsNone(truth['danger_onset_sim_s'])
        self.assertFalse(truth['safe_closure_supported'])
        self.assertIsNone(truth['assertion_supported'])


class FreezeIntegrityTests(unittest.TestCase):
    """Every endpoint and source tree is replaced; these never contact a server."""
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp) / 'workspace'
        self.root.mkdir()
        self.out = Path(self.temp) / 'frozen'
        self.sources = [self.root / name for name in (
            'scripts/real2sim_navigation.py', 'scripts/real2sim_monitor_scene.py',
            'src/haiclaw/harness.py')]
        for i, path in enumerate(self.sources):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'# immutable fixture source {i}\n')
        self.runtime = dict(files={str(p.relative_to(self.root)): runner.digest(p)
                                   for p in self.sources[:2]}, instance='fixture-owned')
        self.identity = dict(model={'digest': 'fixture-model'}, ollama={'version': 'fixture'},
                             endpoint='http://invalid.example/api/chat')
        self.enterContext(patch.object(runner, 'ROOT', self.root))
        self.enterContext(patch.object(runner, 'source_files', return_value=self.sources))
        self.model = self.enterContext(patch.object(runner, 'model_identity', return_value=self.identity))
        self.remote = self.enterContext(patch.object(runner, 'remote', new=AsyncMock(return_value=self.runtime)))
        self.args = SimpleNamespace(output=self.out, manifest=self.root / 'manifest.json',
                                    config=self.root / 'config.json', model=self.root / 'model.json')
        runner.write_json(self.args.manifest, manifest())
        runner.write_json(self.args.config, config())
        runner.write_json(self.args.model, {'model': 'fixture', 'endpoint': 'http://invalid.example/api/chat'})

    def freeze(self):
        with redirect_stdout(io.StringIO()):
            runner.freeze(self.args)
        return runner.read_json(self.out / 'protocol.json')

    def test_exact_bytes_are_bundled_and_offline_verification_needs_no_server(self):
        protocol = self.freeze()
        for name, expected in protocol['files'].items():
            self.assertEqual(runner.digest(self.out / 'source' / name), expected)
        self.model.reset_mock()
        self.remote.reset_mock()
        self.assertEqual(runner.verify_frozen(self.out), protocol)
        self.model.assert_not_called()
        self.remote.assert_not_called()
        with self.assertRaises(FileExistsError):
            self.freeze()

    def test_source_change_during_freeze_cannot_make_snapshot_hash_disagree(self):
        original = self.sources[0].read_bytes()
        async def mutate_after_sources_read(*args, **kwargs):
            self.sources[0].write_text('# changed while endpoint queried\n')
            return self.runtime
        self.remote.side_effect = mutate_after_sources_read
        protocol = self.freeze()
        name = str(self.sources[0].relative_to(self.root))
        self.assertEqual((self.out / 'source' / name).read_bytes(), original)
        self.assertEqual(protocol['files'][name], hashlib.sha256(original).hexdigest())
        with self.assertRaisesRegex(RuntimeError, 'Source differs'):
            runner.verify_frozen(self.out)

    def test_protocol_and_snapshot_tampering_rejected(self):
        self.freeze()
        protocol = self.out / 'protocol.json'
        original = protocol.read_bytes()
        protocol.write_bytes(original + b' ')
        with self.assertRaisesRegex(RuntimeError, 'protocol changed'):
            runner.verify_frozen(self.out)
        protocol.write_bytes(original)
        snapshot = self.out / 'source' / self.sources[0].relative_to(self.root)
        snapshot.write_text('# corrupted saved source\n')
        with self.assertRaises(RuntimeError):
            runner.verify_frozen(self.out)

    def test_loaded_remote_source_must_match_before_freeze(self):
        self.runtime['files']['scripts/real2sim_navigation.py'] = 'different-runtime'
        with self.assertRaisesRegex(RuntimeError, 'Live attachment source differs'):
            self.freeze()
        self.assertFalse(self.out.exists())

    def test_live_model_change_rejected_without_weakening_offline_checks(self):
        self.freeze()
        self.model.return_value = dict(self.identity, model={'digest': 'changed'})
        with self.assertRaisesRegex(RuntimeError, 'Model digest'):
            runner.verify_frozen(self.out, live=True)
        runner.verify_frozen(self.out)


class FailureAndResumeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.out = Path(self.temp)
        self.frozen = frozen_fixture()
        self.entry = dict(self.frozen['schedule'][0], policy='fixed_order')
        self.frozen['schedule'] = [self.entry]

    def mock_execution(self):
        self.prepare = self.enterContext(patch.object(runner, 'prepare_scene', new=AsyncMock(return_value={'fixture': True})))
        self.remote = self.enterContext(patch.object(runner, 'remote', new=AsyncMock(return_value={})))
        self.enterContext(patch.object(runner, 'make_adapter', return_value=object()))
        captures = []
        class FakeTools:
            def __init__(self, adapter, locations, output):
                self.adapter = adapter
                self.motion_records = []
                self.pose_samples = []
            def distance(self):
                return 4.2
        class FakeHarness:
            def __init__(self, episode, planner, tools, **kwargs):
                captures.append(dict(episode=episode, kwargs=kwargs))
                planner.latencies.append(2.0)
                tools.adapter.latencies.append(3.0)
            async def run(self):
                return None
            def report(self):
                return dict(executed_tools=7, wall_seconds=12, trace=[], completed=True)
        self.enterContext(patch.object(runner, 'TrackedTools', FakeTools))
        self.enterContext(patch.object(runner, 'Harness', FakeHarness))
        return captures

    async def test_normalization_failure_preserves_actual_execution_costs(self):
        captures = self.mock_execution()
        with patch('haiclaw.comparison_records.normalize_report', side_effect=ValueError('fixture malformed report')):
            with self.assertRaisesRegex(ValueError, 'fixture malformed report'):
                await runner.run_trial(self.out, self.frozen, self.entry)
        trial = self.out / 'trials' / self.entry['trial_id']
        record = runner.read_json(trial / 'record.json')
        self.assertEqual(record['status'], 'error')
        self.assertEqual(record['tool_calls'], 7)
        self.assertEqual(record['distance_m'], 4.2)
        self.assertEqual(record['planner_latency_s'], 2)
        self.assertEqual(record['vision_latency_s'], 3)
        self.assertEqual(record['wall_latency_s'], 12)
        self.assertEqual(record['failure_stage'], 'report_normalization')
        report = runner.read_json(trial / 'result.json')
        self.assertEqual(report['config'], self.frozen['config'])
        self.assertEqual(captures[0]['kwargs']['max_steps'], 12)
        self.assertEqual(captures[0]['kwargs']['view_retry_budget'], 2)
        self.assertEqual(captures[0]['kwargs']['goal'], runner.GOAL)
        for private_key in ('actual_posture', 'position', 'rotation', 'answerable'):
            self.assertNotIn(private_key, captures[0]['kwargs'])
        self.remote.assert_awaited_once()

    async def test_pre_tool_setup_failure_is_retained_and_not_run(self):
        with patch.object(runner, 'prepare_scene', new=AsyncMock(side_effect=RuntimeError('fixture setup failed'))), \
             patch.object(runner, 'make_adapter') as adapter, \
             patch.object(runner, 'remote', new=AsyncMock()) as remote:
            with self.assertRaisesRegex(RuntimeError, 'fixture setup failed'):
                await runner.run_trial(self.out, self.frozen, self.entry)
        record = runner.read_json(self.out / 'trials' / self.entry['trial_id'] / 'record.json')
        self.assertEqual(record['status'], 'error')
        self.assertEqual(record['tool_calls'], 0)
        self.assertIsNone(record['distance_m'])
        self.assertEqual(record['failure_stage'], 'setup')
        adapter.assert_not_called()
        remote.assert_awaited_once_with('print(json.dumps(real2sim_worker_scenario.restore()))')

    async def test_partial_setup_and_cleanup_failures_both_remain_auditable(self):
        with patch.object(runner, 'prepare_scene', new=AsyncMock(side_effect=RuntimeError('fixture failed after actor apply'))), \
             patch.object(runner, 'make_adapter') as adapter, \
             patch.object(runner, 'remote', new=AsyncMock(side_effect=RuntimeError('fixture restore guard refused'))) as remote:
            with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):
                await runner.run_trial(self.out, self.frozen, self.entry)
        trial = self.out / 'trials' / self.entry['trial_id']
        self.assertEqual(runner.read_json(trial / 'runner_error.json')['message'], 'fixture failed after actor apply')
        self.assertEqual(runner.read_json(trial / 'cleanup_error.json')['error'], 'fixture restore guard refused')
        record = runner.read_json(trial / 'record.json')
        self.assertEqual(record['status'], 'error')
        self.assertEqual(record['failure_stage'], 'setup')
        self.assertEqual(record['tool_calls'], 0)
        self.assertEqual(record['runner_error'], 'fixture failed after actor apply')
        adapter.assert_not_called()
        remote.assert_awaited_once_with('print(json.dumps(real2sim_worker_scenario.restore()))')

    async def test_cleanup_failure_stops_and_preserves_completed_record(self):
        self.mock_execution()
        self.remote.side_effect = RuntimeError('fixture restore failed')
        record = dict(self.entry, status='completed')
        with patch('haiclaw.comparison_records.normalize_report', return_value=record):
            with self.assertRaises(RuntimeError):
                await runner.run_trial(self.out, self.frozen, self.entry)
        trial = self.out / 'trials' / self.entry['trial_id']
        self.assertTrue((trial / 'cleanup_error.json').exists())
        self.assertEqual(runner.read_json(trial / 'record.json'), record)

    async def test_changed_runtime_before_trial_prevents_execution(self):
        with patch.object(runner, 'verify_frozen', return_value=self.frozen), \
             patch.object(runner, 'remote', new=AsyncMock(return_value={'different': True})), \
             patch.object(runner, 'run_trial', new=AsyncMock()) as execute:
            with self.assertRaisesRegex(RuntimeError, 'Live scene attachment changed'):
                await runner.run(SimpleNamespace(output=self.out))
        execute.assert_not_awaited()

    async def test_midtrial_integrity_failure_is_marked_not_summarized(self):
        async def executed(out, frozen, entry):
            runner.write_json(out / 'trials' / entry['trial_id'] / 'record.json', dict(entry))
        with patch.object(runner, 'verify_frozen', side_effect=[self.frozen, self.frozen, RuntimeError('source changed')]), \
             patch.object(runner, 'remote', new=AsyncMock(return_value=self.frozen['runtime_provenance'])), \
             patch.object(runner, 'run_trial', new=AsyncMock(side_effect=executed)), \
             patch.object(runner, 'summarize') as summarize:
            with self.assertRaisesRegex(RuntimeError, 'source changed'):
                await runner.run(SimpleNamespace(output=self.out))
        trial = self.out / 'trials' / self.entry['trial_id']
        self.assertTrue(runner.read_json(trial / 'integrity_or_availability_error.json')['exclude_from_confirmatory_claims'])
        self.assertTrue((trial / 'record.json').exists())
        summarize.assert_not_called()

    async def test_resume_refuses_flagged_or_interrupted_trial_without_retry(self):
        trial = self.out / 'trials' / self.entry['trial_id']
        trial.mkdir(parents=True)
        for marker in ('integrity_or_availability_error.json', 'cleanup_error.json'):
            runner.write_json(trial / 'record.json', dict(self.entry))
            runner.write_json(trial / marker, {'error': 'fixture audit required'})
            with patch.object(runner, 'verify_frozen', return_value=self.frozen), \
                 patch.object(runner, 'remote', new=AsyncMock()) as remote, \
                 patch.object(runner, 'run_trial', new=AsyncMock()) as execute:
                with self.assertRaises(RuntimeError):
                    await runner.run(SimpleNamespace(output=self.out))
            execute.assert_not_awaited()
            remote.assert_not_called()
            (trial / marker).unlink()
        (trial / 'record.json').unlink()
        with patch.object(runner, 'verify_frozen', return_value=self.frozen), \
             patch.object(runner, 'run_trial', new=AsyncMock()) as execute:
            with self.assertRaisesRegex(RuntimeError, 'Interrupted trial'):
                await runner.run(SimpleNamespace(output=self.out))
        execute.assert_not_awaited()

    async def test_resume_skips_existing_failure_without_replacing_it(self):
        trial = self.out / 'trials' / self.entry['trial_id']
        runner.write_json(trial / 'record.json', dict(self.entry, status='error', runner_error='retained failure'))
        original = (trial / 'record.json').read_bytes()
        with patch.object(runner, 'verify_frozen', return_value=self.frozen), \
             patch.object(runner, 'run_trial', new=AsyncMock()) as execute:
            await runner.run(SimpleNamespace(output=self.out))
        execute.assert_not_awaited()
        self.assertEqual((trial / 'record.json').read_bytes(), original)

    async def test_summary_refuses_relabelled_trial_and_preserves_integrity_marker(self):
        entry = self.entry
        other = dict(entry, trial_id='paired', policy='trace')
        self.frozen['schedule'] = [entry, other]
        runner.write_json(self.out / 'protocol.json', self.frozen)
        scene = next(s for s in self.frozen['manifest']['scenarios'] if s['scenario_id'] == entry['scenario_id'])
        for item in (entry, other):
            trial = self.out / 'trials' / item['trial_id']
            runner.write_json(trial / 'record.json', dict(item, status='error', inspection_question_answer='unknown',
                              safety_verdict='unknown', alert_kind='none', alert_sim_s=None))
            runner.write_json(trial / 'external_truth.json', runner.external_truth(scene, config(), 'development'))
        trial = self.out / 'trials' / entry['trial_id']
        path = trial / 'record.json'
        original = runner.read_json(path)
        runner.write_json(path, dict(original, policy='camera_only'))
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            runner.summarize(self.out, verify=False)
        runner.write_json(path, original)
        runner.write_json(trial / 'integrity_or_availability_error.json', {'error': 'fixture source changed'})
        with redirect_stdout(io.StringIO()):
            summary = runner.summarize(self.out, verify=False)
        self.assertTrue(summary['schedule_complete'])
        self.assertFalse(summary['comparison_complete'])
        self.assertTrue(summary['integrity_blocked_trials'])
        self.assertEqual(summary['records'], 2)


if __name__ == '__main__':
    unittest.main()
