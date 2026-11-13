"""Explicit simulator-reset trials; never called by the agent's tool catalog."""
import argparse
import asyncio
import fcntl
import json
from pathlib import Path
import time
from run_real2sim_harness import ROOT, run
from real2sim_harness_tools import remote


async def repeat(args):
    records=[]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    for trial in range(1,args.repetitions+1):
        initial=await remote('print(json.dumps(real2sim_navigation.snapshot()))')
        if initial['navigation']['status']=='moving':raise RuntimeError('An operator movement is active')
        reset=await remote('print(json.dumps(real2sim_navigation.reset_to_entrance()))')
        deadline=time.monotonic()+30
        while True:
            await asyncio.sleep(.2)
            state=await remote('print(json.dumps(real2sim_navigation.snapshot()))')
            if not state['playing'] or state['navigation']['status']=='failed':raise RuntimeError('Simulator reset failed')
            if state['now']-reset['now']>=6:break
            if time.monotonic()>deadline:raise TimeoutError('Simulation did not settle')
        # Align authored worker/door animation phase; this does not reset all PhysX state.
        await remote('omni.timeline.get_timeline_interface().set_current_time(0.0); print(json.dumps({"phase":omni.timeline.get_timeline_interface().get_current_time()}))')
        code=await run(args)
        latest=json.loads((ROOT/'artifacts/live_real2sim/latest_harness.json').read_text())
        records.append(dict(trial=trial,returncode=code,**latest))
        args.output.write_text(json.dumps(dict(runs=records,
            reset_protocol='Reset Spot to entrance; settle six simulation seconds; set authored animation phase to zero. Existing physics scene persists, so trials are not exact full-state replicas.'),indent=2))
        if code:return code
    return 0


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repetitions',type=int,default=2)
    parser.add_argument('--max-steps',type=int,default=6)
    parser.add_argument('--camera-policy',choices=['all','body-only'],default='all')
    parser.add_argument('--finish-on-inspection-answer',action=argparse.BooleanOptionalAction,default=None)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 1<=args.repetitions<=10:parser.error('repetitions must be 1..10')
    if not 1<=args.max_steps<=100:parser.error('max-steps must be 1..100')
    lock=ROOT/'artifacts/closed_loop/runner.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:parser.error('A TRACE harness is already running')
        raise SystemExit(asyncio.run(repeat(args)))
