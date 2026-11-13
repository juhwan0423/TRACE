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
from tracebot.harness import Harness
from tracebot.providers.harness_planner import OllamaPlanner
from tracebot.providers.ollama import make_adapter
from tracebot.providers.person_gate import detector_config, with_person_gate, configure_detector_environment
from real2sim_harness_tools import Real2SimTools
from qwen_events import emit as qwen_emit

async def run(args):
    cfg=json.loads((ROOT/'configs/harness_real2sim.json').read_text())
    model=json.loads((ROOT/'configs/vlm_local.json').read_text())
    if args.max_steps is not None:cfg['max_steps']=args.max_steps
    if getattr(args,'finish_on_inspection_answer',None) is not None:
        cfg['finish_on_inspection_answer']=args.finish_on_inspection_answer
    cfg['camera_policy']=args.camera_policy
    cfg['enabled_cameras']=['body'] if args.camera_policy=='body-only' else ['fixed','body']
    episode=str(uuid.uuid4());out=ROOT/'artifacts/harness'/episode;out.mkdir(parents=True)
    live=ROOT/'artifacts/live_real2sim';live.mkdir(parents=True,exist_ok=True)
    def emit(event):
        event=dict(event,mode='real2sim',planner='ollama',runtime='native_asyncio',trigger=cfg['trigger'],camera_policy=cfg['camera_policy'])
        line=json.dumps(event,ensure_ascii=False)+'\n'
        for path in (out/'events.jsonl',live/'harness.jsonl'):
            with path.open('a') as f:f.write(line)
        if event['kind'] in ('decision','tool_result','terminal','finished','aborted'):print(line,flush=True)
    adapter=make_adapter(model,event_sink=qwen_emit)
    gate_path=getattr(args,'person_gate_config',None)
    if gate_path:
        configure_detector_environment(ROOT)
        cfg['person_gate']=detector_config(gate_path)
        adapter=with_person_gate(adapter,cfg['person_gate'])
    tools=Real2SimTools(adapter,cfg['locations'],out/'frames',cameras=cfg['enabled_cameras'])
    initial=await tools.snapshot()
    if not initial['playing'] or not initial.get('ready'):raise RuntimeError('Start the Real2Sim monitor and wait for Spot')
    if initial['navigation']['status'] in ('moving','failed'):raise RuntimeError('Resolve active movement or navigation fault before starting')
    files=['src/tracebot/harness.py','src/tracebot/context.py','src/tracebot/tool_contracts.py','src/tracebot/providers/harness_planner.py','src/tracebot/providers/ollama.py','scripts/real2sim_navigation.py','scripts/real2sim_monitor_scene.py','scripts/real2sim_harness_tools.py','scripts/run_real2sim_harness.py']
    files += ['src/tracebot/providers/person_gate.py','src/tracebot/providers/person_detector.py']
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
        finish_on_inspection_answer=cfg.get('finish_on_inspection_answer',False),
        goal='An operator requests inspection of the worker. Determine presence and observable posture using fresh camera evidence; no person-loss event has been asserted. Move to another viewpoint if needed, or hand off unresolved uncertainty.')
    try:
        await harness.run()
    finally:
        report=harness.report()
        report.update(runtime='native_asyncio',mode='real2sim',trigger=cfg['trigger'],config=cfg,
            model=model['model'],motion_records=tools.motion_records,planner_records=planner.records)
        report['person_gate_cost']=dict(enabled=bool(gate_path),
            calls=getattr(adapter,'detector_calls',0),
            latency_wall_seconds=sum(getattr(adapter,'detector_latencies',[])))
        (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(out/'result.json',flush=True)
    # A clean unresolved handoff completes a run, but is never a successful diagnosis.
    return 0 if report['completed'] and report['agent_cycle_exercised'] else 1

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--max-steps',type=int)
    p.add_argument('--camera-policy',choices=['all','body-only'],default='all',help='Explicit sensor ablation; body-only hides the fixed-camera tool, not the worker')
    p.add_argument('--person-gate-config',type=Path,help='Opt-in independent RGB person veto; same Qwen model/prompt')
    p.add_argument('--finish-on-inspection-answer',action=argparse.BooleanOptionalAction,default=None,
        help='Finish the operator request once fresh presence/posture answers exist; does not establish overall safety')
    args=p.parse_args()
    if args.max_steps is not None and not 1<=args.max_steps<=100:p.error('max-steps must be in 1..100')
    lock=ROOT/'artifacts/closed_loop/runner.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a') as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB) # 락 잡기 시도
        except BlockingIOError:p.error('A TRACE harness is already running') # 실패 시 종료
        raise SystemExit(asyncio.run(run(args))) # 끝나면 결과로 종료, 종료코드를 사람에게 넘기기 위해 raise SystemExit을 사용하는 것.
