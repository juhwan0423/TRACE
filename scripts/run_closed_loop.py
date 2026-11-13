"""Live Isaac/Spot/Nav2/Qwen loop. Requires the owned Spot context and camera helpers."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tracebot.core import Evidence, Observation
from tracebot.closed_loop import ClosedLoop
from tracebot.providers.ollama import make_adapter


async def remote(code, *, raw=False, timeout=60., **args):
    async def request():
        reader, writer = await asyncio.open_connection('127.0.0.1', 8226)
        try:
            writer.write(json.dumps(dict(context='spot', code=code, args=args)).encode())
            await writer.drain()
            writer.write_eof()
            reply = json.loads(await reader.read())
            if reply.get('status') != 'ok':
                raise RuntimeError(reply.get('evalue', str(reply)))
            output = reply.get('output', '').strip()
            if raw:
                return output
            return json.loads(output.splitlines()[-1]) if output else None
        finally:
            writer.close()
            await writer.wait_closed()
    return await asyncio.wait_for(request(), timeout)


async def run(args):
    from qwen_events import emit
    adapter = make_adapter(json.loads((ROOT / 'configs/vlm_local.json').read_text()), event_sink=emit)
    episode = str(uuid.uuid4())
    loop = ClosedLoop(episode, adapter, budget=args.budget)
    output = ROOT / 'artifacts/closed_loop' / episode
    output.mkdir(parents=True)
    report = dict(episode=episode, evaluation_case=args.case, mode='live_simulation',
                  clock='simulation_seconds', model='qwen3-vl:8b', observations=[],
                  localization='simulator ground truth', sensor='PhysX collision rays',
                  actor='stylized mannequin', completed=False)

    def save():
        report.update(loop.report())
        (output / 'result.json').write_text(json.dumps(report, indent=2, ensure_ascii=False))

    async def capture_observe():
        frame = await remote('print(json.dumps(await trace_capture(after)))',
                             after=max(-1., loop.tracker.latest_capture))
        e = Evidence(str(uuid.uuid4()), episode, 'fixed_camera', **frame)
        observation, record = await adapter.infer(e)
        snapshot = await remote('print(json.dumps(trace_snapshot()))')
        # Inference failure is sensor unavailable, never positive detection.
        visibility = ('visible' if observation.person_visible == 'yes' else
                      'occluded' if observation.person_visible == 'no' else 'unavailable')
        report['observations'].append(dict(frame=frame, inference=record, visibility=visibility))
        triggered = loop.observe(Observation(e, visibility), snapshot['now'])
        save()
        return visibility, triggered

    try:
        await remote('await trace_present()')
        visible, _ = await capture_observe()
        if visible != 'visible':
            raise RuntimeError('Initial person not detected by Qwen; no synthetic loss injected')
        # Scenario generator only; case/pose never enter the perception or incident inputs.
        await remote('await trace_occlude(case)', case=args.case)
        triggered = False
        for _ in range(3):
            _, triggered = await capture_observe()
            if triggered:
                break
        if not triggered:
            raise RuntimeError('No observed loss event; navigation was not started')
        print('loss detected; starting Nav2', flush=True)
        try:
            await remote('inspection.start(); print(json.dumps(trace_snapshot()))')
        except Exception:
            snapshot = await remote('print(json.dumps(trace_snapshot()))')
            loop.motion('failed', snapshot['now'], loop.attempt)
            raise
        motion_reported = False
        submitted = False
        wall_end = time.monotonic() + args.wall_timeout
        while not loop.done:
            snapshot = await remote('print(json.dumps(trace_snapshot()))')
            now = snapshot['now']
            if not snapshot['playing'] or now < loop.incident.now:
                raise RuntimeError('Simulation paused/reset; rejecting old episode evidence')
            nav = snapshot['navigation']
            report['navigation'] = nav
            if not motion_reported and nav['status'] != 'moving':
                when = nav['arrived_at'] if nav['status'] == 'arrived' else now
                loop.motion(nav['status'], when, loop.attempt)
                motion_reported = True
                print('navigation:', nav['status'], flush=True)
            if nav.get('evidence') and not submitted and not loop.done:
                frame = nav['evidence']
                e = Evidence(str(uuid.uuid4()), episode, 'spot_body_camera',
                             frame['capture_time'], frame['received_time'], frame['artifact'])
                loop.submit(e)
                submitted = True
                print('fresh body RGB submitted to Qwen', flush=True)
            loop.tick(now)
            save()
            if time.monotonic() >= wall_end:
                raise TimeoutError('Wall watchdog expired; unresolved, never safe')
            await asyncio.sleep(.2)
        report['completed'] = True
        report['inference_submitted'] = submitted
        report['fresh_body_inference'] = submitted and any(
            entry['inference']['status'] == 'ok' for entry in loop.vlm.audit)
        print('incident:', loop.incident.state.value, flush=True)
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'
        print(report['error'], flush=True)
    finally:
        try:
            await remote('inspection.cancel(); demo.hold(); demo.save()')
        except Exception as error:
            report['stop_error'] = str(error)
        if loop.vlm:
            tasks = [task for _, task in loop.vlm.pending.values()]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        save()
        print(output / 'result.json', flush=True)
    return 0 if report['completed'] and report.get('fresh_body_inference') else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=['normal_work', 'lying_on_floor', 'insufficient_view'],
                        default='lying_on_floor')
    parser.add_argument('--budget', type=float, default=180.)
    parser.add_argument('--wall-timeout', type=float, default=900.)
    args = parser.parse_args()
    import math
    if not all(math.isfinite(x) and x > 0 for x in (args.budget, args.wall_timeout)):
        parser.error('finite positive timeouts required')
    import fcntl
    lock_path = ROOT / 'artifacts/closed_loop/runner.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('Another closed-loop runner is active')
        raise SystemExit(asyncio.run(run(args)))
