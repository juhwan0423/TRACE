"""Observe fixed-camera person loss, then request a bounded Real2Sim inspection.

Uses existing local Qwen, cameras and navigation. Does not move the worker,
reset the scene, install models, or infer a safety verdict from non-detection.
"""
import argparse
import asyncio
from dataclasses import asdict
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from haiclaw.core import Observation
from haiclaw.harness import Harness
from haiclaw.providers.harness_planner import OllamaPlanner
from haiclaw.providers.ollama import make_adapter
from haiclaw.providers.perception import LossTracker
from qwen_events import emit as qwen_emit
from real2sim_harness_tools import Real2SimTools


def open_runner_lock(path, inherited_fd=None):
    """Own a new lock handle or consume the descriptor inherited from our parent.

    flock ownership is shared by the inherited open-file description. Closing
    this handle does not unlock a descriptor still held by the demo parent.
    """
    path = Path(path)
    if inherited_fd is None:
        handle = path.open('a')
    else:
        if type(inherited_fd) is not int or inherited_fd < 3:
            raise ValueError('Invalid inherited runner lock descriptor')
        expected, actual = path.stat(), os.fstat(inherited_fd)
        if ((expected.st_dev, expected.st_ino) != (actual.st_dev, actual.st_ino)
                or not stat.S_ISREG(actual.st_mode)):
            raise ValueError('Inherited descriptor does not refer to the TRACE runner lock')
        handle = os.fdopen(inherited_fd, 'a')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        handle.close()
        raise
    return handle


def load_harness_config(path):
    path = Path(path)
    if not path.is_absolute():
        path = ROOT/path
    cfg = json.loads(path.read_text())
    locations = cfg.get('locations')
    if not isinstance(locations, dict) or not locations:
        raise ValueError('Harness config requires named inspection locations')
    for name, location in locations.items():
        if name not in ('entrance', 'west', 'cage', 'door'):
            raise ValueError('Unknown Real2Sim inspection target: '+str(name))
        if (not isinstance(location, dict) or type(location.get('yaw')) not in (int, float)
                or not math.isfinite(location['yaw'])
                or not isinstance(location.get('description'), str)
                or not location['description'].strip()):
            raise ValueError('Each inspection target requires finite yaw and a description')
    return cfg, path.resolve()


def history_item(evidence, observation, record):
    """Only observed facts and opaque IDs enter planner memory, never scene truth."""
    return dict(evidence_id=evidence.id, camera=evidence.source, viewpoint='fixed',
                capture_time=evidence.capture_time, status=record['status'],
                observation=asdict(observation), historical=True)


class FixedLossEvidence:
    """Require positive visibility before confirmed non-visibility in one stream.

    Inference failures/uncertainty are logged but cannot impersonate a missing
    person. Non-visibility describes camera coverage, not absence or an accident.
    """
    def __init__(self, episode, grace):
        self.tracker = LossTracker(grace=grace, episode=episode)
        self.last_seen = None
        self.seen_ids = set()
        self.latest_capture = -math.inf

    def add(self, evidence, observation, record, now):
        e = evidence
        valid = (e.episode == self.tracker.episode and e.generation == self.tracker.generation
                 and e.source == 'fixed' and e.subject == 'person-1'
                 and e.id not in self.seen_ids
                 and all(math.isfinite(x) for x in (e.capture_time, e.received_time, now))
                 and e.capture_time <= e.received_time <= now
                 and e.capture_time > self.latest_capture
                 and tuple(observation.evidence_ids) == (e.id,))
        if not valid:
            return None, 'unusable_for_visibility_loss'
        self.seen_ids.add(e.id)
        self.latest_capture = e.capture_time
        if record.get('status') != 'ok' or observation.person_visible not in ('yes', 'no'):
            return None, 'unusable_for_visibility_loss'
        visibility = 'visible' if observation.person_visible == 'yes' else 'occluded'
        triggered = self.tracker.update(Observation(e, visibility))
        if visibility == 'visible':
            self.last_seen = history_item(e, observation, record)
        if not triggered:
            return None, 'visible' if visibility == 'visible' else 'not_visible'
        current = history_item(e, observation, record)
        return dict(kind='observed_visibility_loss', source='fixed',
                    last_seen_capture_time=self.last_seen['capture_time'],
                    nonvisible_capture_time=e.capture_time, detected_at=now,
                    gap_sim_seconds=e.capture_time-self.last_seen['capture_time'],
                    grace_sim_seconds=self.tracker.grace,
                    evidence_ids=[self.last_seen['evidence_id'], e.id],
                    observations=[self.last_seen, current]), 'loss_triggered'


async def monitor_loss(tools, episode, *, grace, sample_interval, sim_timeout,
                       wall_timeout, observation_timeout, emit, save_observation,
                       poll_interval=.2):
    initial = await asyncio.wait_for(tools.snapshot(), timeout=5)
    start_sim = previous = initial['now']
    if not math.isfinite(start_sim):
        raise RuntimeError('Invalid simulation clock')
    if initial.get('navigation', {}).get('status') in ('moving', 'failed'):
        raise RuntimeError('Resolve active movement or navigation fault before monitoring')
    wall_end = time.monotonic() + wall_timeout
    detector = FixedLossEvidence(episode, grace)

    async def checked_snapshot():
        nonlocal previous
        remaining = wall_end-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Visibility monitor wall deadline without a loss trigger')
        snapshot = await asyncio.wait_for(tools.snapshot(), timeout=min(5, remaining))
        now = snapshot['now']
        if not math.isfinite(now) or now < previous or not snapshot['playing']:
            raise RuntimeError('Simulation paused/reset or clock invalid during monitoring')
        previous = now
        if now-start_sim >= sim_timeout:
            raise TimeoutError('Visibility monitor simulation deadline without a loss trigger')
        return snapshot

    emit(dict(kind='monitor_started', sim_time=start_sim,
              message='Waiting for real positive fixed-camera visibility before loss can trigger'))
    while True:
        await checked_snapshot()
        emit(dict(kind='monitor_capture_started', sim_time=previous))
        pending = asyncio.create_task(tools.observe('fixed', episode))
        operation_end = time.monotonic() + observation_timeout
        try:
            while not pending.done():
                snapshot = await checked_snapshot()
                if time.monotonic() >= operation_end:
                    raise TimeoutError('Fixed-camera observation timeout')
                await asyncio.wait({pending}, timeout=poll_interval)
            evidence, observation, record = pending.result()
            snapshot = await checked_snapshot()
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
        loss, status = detector.add(evidence, observation, record, snapshot['now'])
        entry = dict(evidence=asdict(evidence), observation=asdict(observation),
                     inference=record, visibility_status=status,
                     inference_completed_sim_time=snapshot['now'])
        save_observation(entry)
        emit(dict(kind='monitor_observation', sim_time=snapshot['now'],
                  evidence_id=evidence.id, capture_time=evidence.capture_time,
                  person_visible=observation.person_visible, posture=observation.posture,
                  inference_status=record['status'], visibility_status=status))
        if loss:
            if snapshot.get('navigation', {}).get('status') in ('moving', 'failed'):
                raise RuntimeError('Loss recorded but active/faulted navigation prevents inspection')
            emit(loss)
            return loss
        # Sampling interval is measured between frame captures on the simulator clock.
        while snapshot['now'] < evidence.capture_time + sample_interval:
            await asyncio.sleep(poll_interval)
            snapshot = await checked_snapshot()


async def run(args):
    cfg, config_path = load_harness_config(args.config)
    model = json.loads((ROOT / 'configs/vlm_local.json').read_text())
    if args.max_steps is not None:
        cfg['max_steps'] = args.max_steps
    cfg.update(trigger='observed_fixed_camera_visibility_loss', camera_policy=args.camera_policy,
               enabled_cameras=['body'] if args.camera_policy == 'body-only' else ['fixed', 'body'])
    episode = str(uuid.uuid4())
    output = ROOT / 'artifacts/loss_inspection' / episode
    output.mkdir(parents=True)
    live = ROOT / 'artifacts/live_real2sim'
    live.mkdir(parents=True, exist_ok=True)
    report = dict(episode=episode, mode='real2sim', perception='qwen_fixed_camera',
                  trigger=cfg['trigger'], config=cfg, monitor_config=vars(args),
                  model=model['model'], completed=False, state='monitoring',
                  loss=None, observations=[], error=None)

    def save():
        (output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))

    def emit(event):
        event = dict(event, episode=episode, mode='real2sim', trigger=cfg['trigger'],
                     camera_policy=args.camera_policy, runtime='native_asyncio', planner='ollama')
        line = json.dumps(event, ensure_ascii=False) + '\n'
        for path in (output / 'events.jsonl', live / 'harness.jsonl'):
            with path.open('a') as handle:
                handle.write(line)
        if event['kind'] in ('monitor_started', 'monitor_capture_started', 'monitor_observation',
                             'observed_visibility_loss', 'decision', 'tool_start', 'tool_result',
                             'finished', 'aborted'):
            print(line, end='', flush=True)

    def save_observation(entry):
        report['observations'].append(entry)
        save()

    files = ['scripts/run_real2sim_loss_inspection.py', 'scripts/real2sim_harness_tools.py',
             'scripts/real2sim_navigation.py', 'scripts/real2sim_monitor_scene.py',
             'src/haiclaw/providers/perception.py', 'src/haiclaw/harness.py',
             'src/haiclaw/context.py', 'src/haiclaw/providers/harness_planner.py',
             'src/haiclaw/providers/single_frame_vlm.py', 'src/haiclaw/providers/ollama.py']
    manifest = dict(config=cfg, config_path=str(config_path),
                    config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
                    monitor_config=vars(args), model_config=model,
                    files={name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files})
    for name in files:
        target = output / 'source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT/name).read_bytes())
    (output/'source/selected_harness_config.json').write_bytes(config_path.read_bytes())
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2))
    (live/'latest_loss_inspection.json').write_text(json.dumps(dict(episode=episode, path=str(output))))
    adapter = make_adapter(model, event_sink=qwen_emit)
    tools = Real2SimTools(adapter, cfg['locations'], output/'frames')
    harness = None
    save()
    try:
        initial = await asyncio.wait_for(tools.snapshot(), timeout=5)
        if not initial.get('ready') or not initial['playing']:
            raise RuntimeError('Start Real2Sim monitor and wait for Spot readiness')
        manifest['initial_snapshot'] = initial
        (output/'manifest.json').write_text(json.dumps(manifest, indent=2))
        loss = await monitor_loss(tools, episode, grace=args.loss_grace,
                                  sample_interval=args.sample_interval, sim_timeout=args.monitor_sim_timeout,
                                  wall_timeout=args.monitor_wall_timeout,
                                  observation_timeout=args.observation_timeout,
                                  emit=emit, save_observation=save_observation)
        report['loss'] = loss
        report['state'] = 'inspection_requested'
        save()
        tools.cameras = tuple(cfg['enabled_cameras'])
        planner = OllamaPlanner(model)
        goal = (f"The fixed camera last visibly observed the worker at simulation time "
                f"{loss['last_seen_capture_time']:.3f}; a real fixed-camera image at "
                f"{loss['nonvisible_capture_time']:.3f} no longer showed the person. "
                "This is a visibility-loss event, not proof of absence, injury or safety. "
                "Historical observations explain the request but cannot establish the current state. "
                "Use fresh evidence and available inspection viewpoints to determine current presence "
                "and observable posture, or hand off unresolved uncertainty.")
        harness = Harness(episode, planner, tools, budget=cfg['budget_seconds'],
                          wall_budget=cfg['wall_budget_seconds'], operation_timeout=cfg['operation_timeout_seconds'],
                          motion_timeout=cfg['motion_timeout_seconds'], max_steps=cfg['max_steps'],
                          max_age=cfg['max_evidence_age_seconds'], emit=emit,
                          view_retry_budget=cfg['view_retry_budget'],
                          finish_on_inspection_answer=cfg.get('finish_on_inspection_answer', False), goal=goal)
        await harness.run(initial_observations=loss['observations'])
        report.update(completed=harness.completed, state=harness.report()['state'],
                      harness=harness.report(), planner_records=planner.records,
                      motion_records=tools.motion_records)
    except asyncio.CancelledError:
        report.update(error='cancelled', state='aborted', completed=False)
        raise
    except Exception as error:
        report.update(error=type(error).__name__+': '+str(error), state='aborted', completed=False)
        emit(dict(kind='aborted', error=report['error']))
    finally:
        if harness is not None:
            report['harness'] = harness.report()
            report['motion_records'] = tools.motion_records
        save()
        print(output/'result.json', flush=True)
    # A completed unknown handoff is an executed experiment, never a confirmed discovery.
    return 0 if report['completed'] else 1


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runner-lock-fd', type=int, default=None, help=argparse.SUPPRESS)
    p.add_argument('--config', default='configs/harness_real2sim.json',
                   help='Separate harness config; relative paths resolve within TRACE')
    p.add_argument('--camera-policy', choices=['all', 'body-only'], default='all',
                   help='Inspection camera catalog after loss; monitoring always uses the fixed camera')
    p.add_argument('--loss-grace', type=float, default=3., help='Minimum simulation seconds since last positive fixed-camera observation')
    p.add_argument('--sample-interval', type=float, default=2., help='Minimum simulation seconds between frame captures')
    p.add_argument('--monitor-sim-timeout', type=float, default=300.)
    p.add_argument('--monitor-wall-timeout', type=float, default=900.)
    p.add_argument('--observation-timeout', type=float, default=180.)
    p.add_argument('--max-steps', type=int)
    return p


if __name__ == '__main__':
    command = parser()
    args = command.parse_args()
    if any(not math.isfinite(getattr(args, key)) or getattr(args, key) <= 0 for key in
           ('loss_grace', 'sample_interval', 'monitor_sim_timeout', 'monitor_wall_timeout', 'observation_timeout')):
        command.error('Monitoring intervals and limits must be finite and positive')
    if args.max_steps is not None and not 1 <= args.max_steps <= 100:
        command.error('max-steps must be in 1..100')
    lock_path = ROOT/'artifacts/closed_loop/runner.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = open_runner_lock(lock_path, args.runner_lock_fd)
    except BlockingIOError:
        command.error('A TRACE harness is already running')
    except (OSError, ValueError) as error:
        command.error(str(error))
    with handle:
        raise SystemExit(asyncio.run(run(args)))
