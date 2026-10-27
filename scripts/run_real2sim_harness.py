"""Native asyncio baseline: real Spark decisions and Real2Sim inspection tools."""
import argparse
import asyncio
import fcntl
import hashlib
import json
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from haiclaw.harness import Harness
from haiclaw.providers.harness_planner import OllamaPlanner
from haiclaw.providers.ollama import make_adapter
from real2sim_harness_tools import Real2SimTools
from qwen_events import emit as qwen_emit

async def run(args):
    cfg=json.loads((ROOT/'configs/harness_real2sim.json').read_text())
    model=json.loads((ROOT/'configs/vlm_local.json').read_text())
    if args.max_steps is not None:cfg['max_steps']=args.max_steps
    cfg['camera_policy']=args.camera_policy
    cfg['enabled_cameras']=['body'] if args.camera_policy=='body-only' else ['fixed','body']
    episode=str(uuid.uuid4());out=ROOT/'artifacts/harness'/episode;out.mkdir(parents=True)
    live=ROOT/'artifacts/live_real2sim';live.mkdir(parents=True,exist_ok=True)
    def emit(event):
        event=dict(event,mode='real2sim',planner='ollama',runtime='native_asyncio',trigger=cfg['trigger'])
        line=json.dumps(event,ensure_ascii=False)+'\n'
        for path in (out/'events.jsonl',live/'harness.jsonl'):
            with path.open('a') as f:f.write(line)
        if event['kind'] in ('decision','tool_result','terminal','finished','aborted'):print(line,flush=True)
    tools=Real2SimTools(make_adapter(model,event_sink=qwen_emit),cfg['locations'],out/'frames',cameras=cfg['enabled_cameras'])
    initial=await tools.snapshot()
    if not initial['playing'] or not initial.get('ready'):raise RuntimeError('Start the Real2Sim monitor and wait for Spot')
    if initial['navigation']['status'] in ('moving','failed'):raise RuntimeError('Resolve active movement or navigation fault before starting')
    files=['src/haiclaw/harness.py','src/haiclaw/context.py','src/haiclaw/tool_contracts.py','src/haiclaw/providers/harness_planner.py','src/haiclaw/providers/ollama.py','scripts/real2sim_navigation.py','scripts/real2sim_harness_tools.py','scripts/run_real2sim_harness.py']
    manifest=dict(runtime='native_asyncio',config=cfg,model_config=model,initial_snapshot=initial,
        files={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    for name in files:
        path=out/'source'/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes((ROOT/name).read_bytes())
    (live/'latest_harness.json').write_text(json.dumps(dict(episode=episode,path=str(out))))
    planner=OllamaPlanner(model)
    harness=Harness(episode,planner,tools,budget=cfg['budget_seconds'],wall_budget=cfg['wall_budget_seconds'],
        operation_timeout=cfg['operation_timeout_seconds'],motion_timeout=cfg['motion_timeout_seconds'],
        max_steps=cfg['max_steps'],max_age=cfg['max_evidence_age_seconds'],emit=emit,view_retry_budget=cfg['view_retry_budget'],
        goal='An operator requests inspection of the worker. Determine presence and observable posture using fresh camera evidence; no person-loss event has been asserted. Move to another viewpoint if needed, or hand off unresolved uncertainty.')
    try:
        await harness.run()
    finally:
        report=harness.report()
        report.update(runtime='native_asyncio',mode='real2sim',trigger=cfg['trigger'],config=cfg,
            model=model['model'],motion_records=tools.motion_records,planner_records=planner.records)
        (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(out/'result.json',flush=True)
    # A clean unresolved handoff completes a run, but is never a successful diagnosis.
    return 0 if report['completed'] and report['agent_cycle_exercised'] else 1

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--max-steps',type=int)
    p.add_argument('--camera-policy',choices=['all','body-only'],default='all',help='Explicit sensor ablation; body-only hides the fixed-camera tool, not the worker')
    args=p.parse_args()
    if args.max_steps is not None and not 1<=args.max_steps<=100:p.error('max-steps must be in 1..100')
    lock=ROOT/'artifacts/closed_loop/runner.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:p.error('A TRACE harness is already running')
        raise SystemExit(asyncio.run(run(args)))
