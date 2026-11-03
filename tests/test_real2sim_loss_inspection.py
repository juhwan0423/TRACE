"""CPU-only visibility-trigger tests. No simulator, network, or model is used."""
import asyncio
import contextlib
from dataclasses import replace
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from haiclaw.core import Evidence
from haiclaw.providers.single_frame_vlm import Interpretation
from run_real2sim_loss_inspection import FixedLossEvidence, load_harness_config, monitor_loss, open_runner_lock
import demo_real2sim_occlusion as demo


def sample(stamp, visible, *, episode='ep', status='ok'):
    e = Evidence('frame-'+str(stamp), episode, 'fixed', stamp, stamp, 'fixture://frame')
    o = Interpretation(visible, 'standing' if visible == 'yes' else 'unknown', (),
                       () if visible == 'yes' else ('outside observed coverage',),
                       visible != 'yes', (e.id,))
    return e, o, dict(status=status)


class RunnerLockTests(unittest.TestCase):
    def test_inherited_lock_blocks_independent_contender_through_handoff(self):
        script_dir = str(Path(__file__).resolve().parents[1]/'scripts')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'runner.lock'
            parent = open_runner_lock(path)
            self.addCleanup(parent.close)
            contender = '''import fcntl,sys
with open(sys.argv[1], 'a') as lock:
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: sys.exit(7)
'''
            def contend():
                return subprocess.run([sys.executable, '-c', contender, str(path)], timeout=5).returncode
            self.assertEqual(contend(), 7)
            child_code = '''import sys
sys.path.insert(0, sys.argv[1])
from run_real2sim_loss_inspection import open_runner_lock
with open_runner_lock(sys.argv[2], int(sys.argv[3])):
    print('locked', flush=True)
    sys.stdin.readline()
'''
            child = subprocess.Popen([sys.executable, '-c', child_code, script_dir, str(path),
                                      str(parent.fileno())], pass_fds=(parent.fileno(),),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'locked')
                self.assertEqual(contend(), 7)  # Parent and child both retain it.
                parent.close()
                self.assertEqual(contend(), 7)  # Child alone retains the same lock.
                child.communicate('\n', timeout=5)
                self.assertEqual(child.returncode, 0)
                self.assertEqual(contend(), 0)  # All shared descriptors closed.
            finally:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=5)

    def test_inherited_descriptor_for_another_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'runner.lock'
            path.touch()
            with (Path(directory)/'other').open('a') as other:
                with self.assertRaisesRegex(ValueError, 'does not refer'):
                    open_runner_lock(path, other.fileno())


class DemoRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_recovers_only_own_child_result_saved_during_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'scripts').mkdir()
            (root/'scripts/real2sim_worker_scene.py').write_text('# fixture')
            episode = str(uuid.uuid4())
            own_result = root/'artifacts/loss_inspection'/episode/'result.json'
            class FakeTools:
                def __init__(self, *args):
                    self.motion_records = []
                async def snapshot(self):
                    return dict(now=1, ready=True, playing=True, pose=[0, 0, -demo.math.pi/2],
                                navigation=dict(status='idle'))
            async def remote(code, **kwargs):
                if 'points[0]' in code:
                    return [0, 0]
                if 'apply(position' in code:
                    return dict(snapshot=dict(now=2), scenario={})
                return {}
            class Stream:
                first = True
                async def readline(self):
                    if self.first:
                        self.first = False
                        return (json.dumps(dict(kind='monitor_started', episode=episode))+'\n').encode()
                    raise asyncio.CancelledError()
            class Child:
                pid = 123
                returncode = None
                stdout = Stream()
            child = Child()
            async def spawn(*args, **kwargs):
                return child
            async def stop(owned_child):
                self.assertIs(owned_child, child)
                own_result.parent.mkdir(parents=True)
                own_result.write_text(json.dumps(dict(episode=episode, state='aborted', completed=False)))
                child.returncode = 130
            args = demo.argparse.Namespace(condition='lying', config='fixture.json', loss_grace=3,
                                          navigation_timeout=10, visible_timeout=10, timeout=20)
            with (patch.object(demo, 'ROOT', root), patch.object(demo, 'Real2SimTools', FakeTools),
                  patch.object(demo, 'remote', remote), patch.object(demo, 'stop_child', stop),
                  patch.object(asyncio, 'create_subprocess_exec', spawn),
                  contextlib.redirect_stdout(io.StringIO())):
                with self.assertRaises(asyncio.CancelledError):
                    await demo.run(args)
            report = json.loads(next((root/'artifacts/occlusion_demo').glob('*/evaluator.json')).read_text())
            self.assertEqual(report['inspection_result'], str(own_result))
            self.assertEqual(report['inspection_state'], 'aborted')
            self.assertEqual(report['child_exit_code'], 130)
            self.assertEqual(report['error'], 'cancelled')
            self.assertFalse(report['completed'])


class LossEvidenceTests(unittest.TestCase):
    def test_separate_config_rejects_arbitrary_targets_and_nonfinite_yaw(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'config.json'
            for name, yaw in (('arbitrary', 0), ('west', float('nan')), ('west', '0')):
                path.write_text(json.dumps(dict(locations={name: dict(yaw=yaw, description='View')})))
                with self.assertRaises(ValueError):
                    load_harness_config(path)
            path.write_text(json.dumps(dict(locations={'west': dict(yaw=-.8, description='West view')})))
            self.assertEqual(load_harness_config(path)[0]['locations']['west']['yaw'], -.8)

    def test_no_prior_visible_person_cannot_trigger(self):
        detector = FixedLossEvidence('ep', 3)
        for stamp in (1, 5, 10):
            self.assertIsNone(detector.add(*sample(stamp, 'no'), stamp)[0])

    def test_loss_is_bound_to_real_prior_and_current_capture_times(self):
        detector = FixedLossEvidence('ep', 3)
        detector.add(*sample(1, 'yes'), 1)
        self.assertIsNone(detector.add(*sample(3, 'no'), 3)[0])
        loss, status = detector.add(*sample(5, 'no'), 8)
        self.assertEqual(status, 'loss_triggered')
        self.assertEqual(loss['evidence_ids'], ['frame-1', 'frame-5'])
        self.assertEqual(loss['gap_sim_seconds'], 4)
        self.assertEqual(loss['detected_at'], 8)
        self.assertTrue(all(item['historical'] for item in loss['observations']))
        self.assertNotIn('artifact', loss['observations'][0])

    def test_reacquisition_restarts_grace(self):
        detector = FixedLossEvidence('ep', 3)
        for stamp, visible in ((1, 'yes'), (3, 'no'), (4, 'yes')):
            detector.add(*sample(stamp, visible), stamp)
        self.assertIsNone(detector.add(*sample(5, 'no'), 5)[0])
        self.assertEqual(detector.add(*sample(8, 'no'), 8)[0]['last_seen_capture_time'], 4)

    def test_failure_unknown_wrong_episode_and_old_frame_cannot_create_loss(self):
        detector = FixedLossEvidence('ep', 3)
        detector.add(*sample(5, 'yes'), 5)
        for item in (sample(9, 'uncertain'), sample(10, 'no', status='timeout'),
                     sample(11, 'no', episode='old'), sample(3, 'no')):
            self.assertIsNone(detector.add(*item, 12)[0])
        self.assertIsNotNone(detector.add(*sample(13, 'no'), 13)[0])

    def test_wrong_reference_or_future_timestamp_cannot_create_loss(self):
        detector = FixedLossEvidence('ep', 3)
        detector.add(*sample(1, 'yes'), 1)
        e, o, record = sample(5, 'no')
        self.assertIsNone(detector.add(e, replace(o, evidence_ids=('wrong',)), record, 5)[0])
        self.assertIsNone(detector.add(e, o, record, 4)[0])

    def test_uncertain_new_frame_still_prevents_older_nonvisible_replay(self):
        detector = FixedLossEvidence('ep', 3)
        detector.add(*sample(1, 'yes'), 1)
        detector.add(*sample(10, 'uncertain'), 10)
        self.assertIsNone(detector.add(*sample(8, 'no'), 11)[0])
        self.assertIsNotNone(detector.add(*sample(12, 'no'), 12)[0])


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_frame_history_returns_loss_without_calling_navigation(self):
        class Tools:
            now = 0
            async def snapshot(self):
                return dict(now=self.now+.1, playing=True, navigation=dict(status='idle'))
            async def observe(self, camera, episode):
                self.now += 4
                return sample(self.now, 'yes' if self.now == 4 else 'no', episode=episode)
        events, observations = [], []
        loss = await monitor_loss(Tools(), 'ep', grace=3, sample_interval=.001,
                                  sim_timeout=100, wall_timeout=1, observation_timeout=1,
                                  emit=events.append, save_observation=observations.append,
                                  poll_interval=.001)
        self.assertEqual(loss['evidence_ids'], ['frame-4', 'frame-8'])
        self.assertEqual(len(observations), 2)
        self.assertEqual(events[-1]['kind'], 'observed_visibility_loss')

    async def test_sim_deadline_cancels_slow_inference_before_trigger(self):
        class Tools:
            now = 0
            cancelled = False
            async def snapshot(self):
                self.now += 1
                return dict(now=self.now, playing=True, navigation=dict(status='idle'))
            async def observe(self, *args):
                try:
                    await asyncio.sleep(10)
                finally:
                    self.cancelled = True
        tools = Tools()
        with self.assertRaisesRegex(TimeoutError, 'simulation deadline'):
            await monitor_loss(tools, 'ep', grace=3, sample_interval=1, sim_timeout=5,
                               wall_timeout=1, observation_timeout=1,
                               emit=lambda e: None, save_observation=lambda e: None,
                               poll_interval=.001)
        self.assertTrue(tools.cancelled)

    async def test_paused_simulation_never_starts_a_capture(self):
        class Tools:
            async def snapshot(self):
                return dict(now=0, playing=False, navigation=dict(status='idle'))
            async def observe(self, *args):
                raise AssertionError('must not capture while paused')
        with self.assertRaisesRegex(RuntimeError, 'paused/reset'):
            await monitor_loss(Tools(), 'ep', grace=3, sample_interval=1, sim_timeout=5,
                               wall_timeout=1, observation_timeout=1,
                               emit=lambda e: None, save_observation=lambda e: None)


if __name__ == '__main__':
    unittest.main()
