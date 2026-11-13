"""Author visible→occluded worker poses; let actual camera loss trigger TRACE.

Scenario poses and condition labels are evaluator-only. This script neither
resets Spot nor feeds scenario truth to the inspection runner.
"""
import argparse
import asyncio
import fcntl
import json
import math
from pathlib import Path
import signal
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from real2sim_harness_tools import Real2SimTools, remote
from real2sim_worker import CAPTURE


async def stop_child(child):
    if child is None or child.returncode is not None:
        return
    child.send_signal(signal.SIGINT)  # Existing runner cancels only its own goal.
    try:
        await asyncio.wait_for(child.wait(), timeout=20)
    except asyncio.TimeoutError:
        # Kill only our child process; never issue a global simulator stop.
        child.terminate()
        try:
            await asyncio.wait_for(child.wait(), timeout=5)
        except asyncio.TimeoutError:
            child.kill()
            await child.wait()
        raise RuntimeError('Child required forced termination; inspect its final navigation state')


async def run(args):
    output = ROOT/'artifacts/occlusion_demo'/str(uuid.uuid4())
    output.mkdir(parents=True)
    restore = f'{sys.executable} {ROOT}/scripts/real2sim_worker.py restore'
    report = dict(condition=args.condition, scenario='authored static pose, not physical fall',
                  output=str(output), completed=False, restore_command=restore, transitions=[])
    child = None
    tools = Real2SimTools(None, {'entrance': dict(yaw=-math.pi/2)}, output/'setup_frames')
    lock_path = ROOT/'artifacts/closed_loop/runner.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open('a')

    def save():
        (output/'evaluator.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))

    async def apply(label, position, rotation):
        value = await remote(
            'value=real2sim_worker_scenario.apply(position,rotation,0); '
            'print(json.dumps(dict(scenario=value,snapshot=real2sim_navigation.snapshot())))',
            position=position, rotation=rotation, timeout=40)
        event = dict(label=label, wall_time_unix=time.time(), **value)
        report['transitions'].append(event)
        save()
        print(json.dumps(dict(evaluator_transition=label, sim_time=value['snapshot']['now'])), flush=True)
        capture = await remote(CAPTURE, output_dir=str(output/label), measure=True, timeout=40)
        event['capture'] = capture
        save()

    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('A TRACE runner is already active; scene was not changed')
        initial = await tools.snapshot()
        report['initial_snapshot'] = initial
        if (not initial.get('ready') or not initial['playing'] or not initial.get('pose')
                or initial['navigation']['status'] in ('moving', 'failed')):
            raise RuntimeError('A ready, playing, stationary Spot without navigation faults is required')
        entrance = await remote('print(json.dumps(real2sim_navigation.points[0]))')
        pose = initial['pose']
        heading_error = abs(math.atan2(math.sin(pose[2]+math.pi/2), math.cos(pose[2]+math.pi/2)))
        if math.dist(pose[:2], entrance) > .2 or heading_error > .15:
            print('Walking to entrance along the existing corridor.', flush=True)
            result = await asyncio.wait_for(tools.inspect('entrance'), timeout=args.navigation_timeout)
            report['entrance_navigation'] = tools.motion_records
            if result['status'] != 'arrived':
                raise RuntimeError('Entrance navigation did not arrive: '+result['status'])
        await remote('exec(worker_source); print(json.dumps(real2sim_worker_scenario.state()))',
                     worker_source=(ROOT/'scripts/real2sim_worker_scene.py').read_text(), timeout=40)
        await apply('visible', [-1.05, -.45, .03], [0, 0, 0])
        command = [sys.executable, str(ROOT/'scripts/run_real2sim_loss_inspection.py'),
                   '--config', args.config, '--loss-grace', str(args.loss_grace),
                   '--runner-lock-fd', str(lock.fileno())]
        report['runner_command'] = command
        # Parent and child share one locked open-file description without a gap.
        child = await asyncio.create_subprocess_exec(*command, cwd=ROOT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            limit=1024*1024, start_new_session=True, pass_fds=(lock.fileno(),))
        report['child_pid'] = child.pid
        save()
        started = time.monotonic()
        hidden = False
        with (output/'runner.log').open('w') as log:
            while True:
                elapsed = time.monotonic()-started
                if elapsed >= args.timeout or not hidden and elapsed >= args.visible_timeout:
                    raise TimeoutError('Demo deadline; no synthetic detection or loss was injected')
                try:
                    line = await asyncio.wait_for(child.stdout.readline(), timeout=1)
                except asyncio.TimeoutError:
                    continue
                if not line:
                    break
                text = line.decode(errors='replace').rstrip()
                print(text, flush=True)
                log.write(text+'\n'); log.flush()
                try:
                    event = json.loads(text)
                except json.JSONDecodeError:
                    if text.endswith('/result.json') and Path(text).is_file():
                        report['inspection_result'] = text
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get('episode'):
                    report['episode'] = event['episode']
                if (not hidden and event.get('kind') == 'monitor_observation'
                        and event.get('visibility_status') == 'visible'):
                    report['positive_visibility_event'] = event
                    rotation = [0, 90, 90] if args.condition == 'lying' else [0, 0, 0]
                    await apply('hidden_'+args.condition, [-5.5, -.3, .03], rotation)
                    hidden = True
                save()
        report['child_exit_code'] = await child.wait()
        if report.get('inspection_result'):
            result = json.loads(Path(report['inspection_result']).read_text())
            report.update(completed=bool(result.get('completed')), inspection_state=result.get('state'))
        if not hidden or child.returncode:
            raise RuntimeError('Demo did not complete; inspect runner.log and evaluator.json')
        return 0 if report['completed'] else 1
    except asyncio.CancelledError:
        report.update(error='cancelled', completed=False)
        raise
    except Exception as error:
        report.update(error=type(error).__name__+': '+str(error), completed=False)
        print(report['error'], flush=True)
        return 1
    finally:
        try:
            await stop_child(child)
        except Exception as error:
            report['shutdown_error'] = str(error)
            report['completed'] = False
        if child is not None:
            report['child_exit_code'] = child.returncode
            # SIGINT can save a result after stdout consumption has stopped.
            # Recover only the UUID reported by this child, never a latest file.
            try:
                episode = str(uuid.UUID(report['episode']))
                candidate = ROOT/'artifacts/loss_inspection'/episode/'result.json'
                if candidate.is_file():
                    result = json.loads(candidate.read_text())
                    if result.get('episode') == episode:
                        report.update(inspection_result=str(candidate), inspection_state=result.get('state'))
            except (KeyError, ValueError, OSError) as error:
                if 'episode' in report:
                    report['result_recovery_error'] = str(error)
        lock.close()
        save()
        print('Evaluator record: '+str(output/'evaluator.json'), flush=True)
        print('Inspection result: '+report.get('inspection_result', 'not produced'), flush=True)
        print('Restore authored worker pose only while Spot is stationary:\n'+restore, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--condition', choices=['lying', 'standing'], default='lying')
    parser.add_argument('--config', default='configs/harness_occlusion_real2sim.json')
    parser.add_argument('--loss-grace', type=float, default=3.)
    parser.add_argument('--navigation-timeout', type=float, default=240.)
    parser.add_argument('--visible-timeout', type=float, default=300.)
    parser.add_argument('--timeout', type=float, default=2100.)
    args = parser.parse_args()
    if any(not math.isfinite(value) or value <= 0 for value in
           (args.loss_grace, args.navigation_timeout, args.visible_timeout, args.timeout)):
        parser.error('Grace and timeouts must be finite and positive')
    raise SystemExit(asyncio.run(run(args)))
