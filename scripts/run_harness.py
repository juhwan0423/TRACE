"""TRACE agent harness: fixture tests or real Qwen + Isaac tool execution."""
import argparse
import asyncio
from dataclasses import asdict
import fcntl
import json
import os
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tracebot.harness import Harness
from tracebot.providers.harness_fixture import FixtureTools,FixturePlanner
from tracebot.providers.harness_planner import OllamaPlanner
from tracebot.providers.ollama import make_adapter
from tracebot.providers.perception import LossTracker
from tracebot.core import Observation
from qwen_events import emit as qwen_emit

async def main(args):
    if args.mode == 'live' and os.environ.get('TRACE_SCENE', 'real2sim') == 'real2sim':
        raise RuntimeError('Use scripts/run_real2sim_harness.py for the native Real2Sim harness; this legacy live runner generates old-scene experiments.')
    cfg=json.loads((ROOT/'configs/harness.json').read_text())
    model_cfg=json.loads((ROOT/'configs/vlm_local.json').read_text())
    episode=str(uuid.uuid4());out=ROOT/'artifacts/harness'/episode;out.mkdir(parents=True)
    import hashlib
    paths=['src/tracebot/harness.py','src/tracebot/providers/harness_planner.py','scripts/run_harness.py','scripts/harness_live_tools.py','configs/harness.json']
    (out/'code_manifest.json').write_text(json.dumps({p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},indent=2))
    latest=ROOT/'artifacts/live/harness.jsonl';latest.parent.mkdir(parents=True,exist_ok=True)
    def emit(event):
        event=dict(event,mode=args.mode,planner=args.planner)
        line=json.dumps(event,ensure_ascii=False)+'\n'
        for path in (out/'events.jsonl',latest):
            with path.open('a') as f:f.write(line)
        if event['kind'] in ('decision','tool_result','terminal','finished'):
            print(json.dumps(event,ensure_ascii=False),flush=True)
    planner=OllamaPlanner(model_cfg) if args.planner=='ollama' else FixturePlanner()
    initial=[];bootstrap=[];tools=None
    if args.mode=='live':
        from run_closed_loop import remote
        from harness_live_tools import LiveTools
        # Never replace a stage; require the previously prepared, owned context.
        check=await remote("import carb.settings; print(json.dumps(dict(owner=carb.settings.get_settings().get('/haiclaw/workspace'), snapshot=trace_snapshot())))",timeout=5)
        if check['owner']!=str(ROOT):raise RuntimeError('Not the owned TRACE workspace')
        if (check['snapshot'].get('navigation') or {}).get('status')=='moving':
            raise RuntimeError('Navigation already active; refusing new experiment')
        tools=LiveTools(make_adapter(model_cfg,event_sink=qwen_emit),cfg['locations'])
        # Experiment generator creates truth; only real perceived loss enters the agent.
        tracker=LossTracker(grace=1.,episode=episode)
        try:
            emit(dict(kind='bootstrap',episode=episode,sim_time=None,wall_elapsed=0,stage='initial camera observation'))
            await remote('await trace_present()',timeout=60)
            e,obs,record=await tools.observe('fixed',episode)
            if obs.person_visible!='yes':raise RuntimeError('Initial person not detected')
            tracker.update(Observation(e,'visible'))
            bootstrap.append(dict(evidence=asdict(e),inference=record))
            emit(dict(kind='bootstrap',episode=episode,sim_time=None,stage='observe loss'))
            await remote('await trace_occlude(case)',case=args.case,timeout=30)
            for _ in range(3):
                e,obs,record=await tools.observe('fixed',episode)
                bootstrap.append(dict(evidence=asdict(e),inference=record))
                visibility='visible' if obs.person_visible=='yes' else 'occluded' if obs.person_visible=='no' else 'unavailable'
                if tracker.update(Observation(e,visibility)):
                    initial=[dict(evidence_id=e.id,camera='fixed',capture_time=e.capture_time,
                                  status=record['status'],observation=asdict(obs))]
                    break
            if not initial:raise RuntimeError('No observed person-loss event')
        except BaseException as error:
            try:await tools.stop()
            finally:
                emit(dict(kind='aborted',episode=episode,sim_time=None,error=str(error)))
                (out/'bootstrap.json').write_text(json.dumps(dict(completed=False,error=str(error),observations=bootstrap),ensure_ascii=False,indent=2))
                (out/'result.json').write_text(json.dumps(dict(episode=episode,mode=args.mode,planner=args.planner,
                    completed=False,state=None,agent_decisions=0,agent_cycle_exercised=False,error=str(error)),ensure_ascii=False,indent=2))
            raise
    else:
        tools=FixtureTools(fail_first=args.fail_first,limited=args.limited)
        initial=[dict(camera='fixed',status='fixture',observation=dict(person_visible='no',posture='unknown',observation_limitations=['occluded']))]
    (out/'bootstrap.json').write_text(json.dumps(dict(mode=args.mode,observations=bootstrap),ensure_ascii=False,indent=2))
    harness=Harness(episode,planner,tools,budget=args.budget or cfg['budget_seconds'],
        wall_budget=cfg['wall_budget_seconds'],operation_timeout=cfg['operation_timeout_seconds'],
        motion_timeout=cfg['motion_timeout_seconds'],max_steps=cfg['max_steps'],max_age=cfg['max_evidence_age_seconds'],emit=emit)
    try:
        report=await harness.run(initial)
    finally:
        report=harness.report()
        report['planner_records']=getattr(planner,'records',[])
        report['motion_records']=getattr(tools,'motion_records',[])
        report.update(mode=args.mode,planner=args.planner,locations=cfg['locations'],
                      evaluation_case=args.case if args.mode=='live' else 'fixture',
                      model=model_cfg['model'] if args.planner=='ollama' else None)
        (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        print(out/'result.json',flush=True)
    return 0 if report['completed'] and report['agent_cycle_exercised'] else 1

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['fixture','live'],default='fixture')
    p.add_argument('--planner',choices=['fixture','ollama'],default='ollama')
    p.add_argument('--case',choices=['lying_on_floor','normal_work','insufficient_view'],default='lying_on_floor')
    p.add_argument('--budget',type=float)
    p.add_argument('--fail-first',action='store_true');p.add_argument('--limited',action='store_true')
    args=p.parse_args()
    import math
    if args.budget is not None and (not math.isfinite(args.budget) or args.budget<=0):p.error('positive finite budget required')
    if args.mode=='live' and args.planner!='ollama':p.error('live mode requires model planner')
    lock=ROOT/'artifacts/closed_loop/runner.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:p.error('A baseline or harness runner is already active')
        raise SystemExit(asyncio.run(main(args)))
