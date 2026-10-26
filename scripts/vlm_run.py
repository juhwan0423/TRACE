"""Explicit Gemini single-image evaluation on saved post-arrival RGB evidence.

Default is an offline request preview: zero API calls. Incident clock is replayed
at 1x wall time from the capture timestamp, not a live Kit clock connection.
"""
import argparse
import asyncio
import base64
import hashlib
import html
import json
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from haiclaw.core import Evidence, Incident, TERMINAL
from haiclaw.providers.single_frame_vlm import SingleFrameVLM, IncidentVLM, request_payload
from haiclaw.providers.gemini import GeminiTransport, MODEL, gemini_payload, response_text


def load_case(path):
    data=json.loads(Path(path).read_text())
    evidence=data.get('evidence')
    if data.get('status')!='arrived' or not evidence or not data['arrived_at']<evidence['capture_time']<=evidence['received_time']:
        raise ValueError('verified post-arrival image metadata required')
    image=Path(evidence['artifact']).resolve()
    if not image.is_file():
        raise ValueError('evidence image missing')
    return data,image


async def run_case(path, args, adapter):
    nav,image=load_case(path)
    capture=nav['evidence']['capture_time']
    evidence_id=str(uuid.uuid4())  # Opaque: never encode the scenario label.
    e=Evidence(evidence_id,str(uuid.uuid4()),'spot_body_camera',capture,nav['evidence']['received_time'],str(image))
    request=gemini_payload(request_payload(image,evidence_id,capture,MODEL))
    report=dict(mode='actual_api' if adapter else 'dry_run_no_inference', model=MODEL,
                clock_mode='offline_incident_replay_1x_wall', image=str(image), evidence_id=evidence_id,
                capture_time=capture, navigation_goal_id=nav['goal_id'],
                image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
                request_metadata=json.loads(request['contents'][0]['parts'][0]['text']),
                final_incident_state=None, raw_response=None, interpretation=None, events=[])
    if adapter is None:
        report['blocker']='API not executed; use GEMINI_API_KEY and --allow-api'
        return report
    i=Incident(e.episode,nav['arrived_at']-1,capture+args.incident_budget)
    attempt=i.motion('moving',nav['arrived_at']-.5)
    i.motion('arrived',nav['arrived_at'],attempt_id=attempt)
    c=IncidentVLM(i,adapter,max_age=args.incident_budget)
    start=time.monotonic()
    c.submit(e)
    while c.pending or i.state not in TERMINAL:
        c.tick(e.received_time+time.monotonic()-start)
        await asyncio.sleep(.02)
    inference=c.audit[0]['inference']
    report.update(final_incident_state=i.state.value, events=i.events, audit=c.audit,
                  raw_response=inference['raw_response'], interpretation=inference['interpretation'],
                  latency_wall_seconds=inference['latency_wall_seconds'], inference_status=inference['status'])
    return report


def write_view(results, output):
    cards=[]
    for result in results:
        encoded=base64.b64encode(Path(result['image']).read_bytes()).decode()
        detail=html.escape(json.dumps(result,ensure_ascii=False,indent=2))
        title=html.escape(result.get('scenario','unlabeled'))
        cards.append(f'<article><h2>{title}</h2><p>{html.escape(result["mode"])}</p>'
                     f'<img alt="입력 RGB" src="data:image/png;base64,{encoded}">'
                     f'<p>사건 상태: {html.escape(str(result["final_incident_state"]))}</p><pre>{detail}</pre></article>')
    (output/'index.html').write_text('''<!doctype html><html lang="ko"><meta charset="utf-8">
<title>HAI-CLAW 단일 프레임 관측</title><style>body{font-family:system-ui;background:#eef2f5;padding:24px}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:20px}article{background:white;padding:20px;border-radius:12px}
img{width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}</style>
<h1>HAI-CLAW 단일 프레임 관측</h1><p>dry_run은 실제 추론이 아닙니다. 시나리오 이름은 평가용이며 모델에 전달되지 않습니다.</p><main>'''+''.join(cards)+'</main></html>')


async def main():
    config=json.loads((ROOT/'configs/vlm.json').read_text())
    if config['provider']!='gemini' or config['model']!=MODEL:
        raise ValueError('This runner requires the reviewed Gemini ER 2 configuration')
    parser=argparse.ArgumentParser(description=__doc__)
    inputs=parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--nav-result',type=Path)
    inputs.add_argument('--cases',type=Path)
    parser.add_argument('--allow-api',action='store_true',help='Send RGB to Gemini; may incur API charges')
    parser.add_argument('--timeout',type=float,default=config['timeout_seconds'])
    parser.add_argument('--incident-budget',type=float,default=config['incident_budget_seconds'])
    args=parser.parse_args()
    import math
    if not math.isfinite(args.incident_budget) or not 0<args.incident_budget<=300:
        parser.error('incident budget must be 0..300 seconds')
    cases=json.loads(args.cases.read_text()) if args.cases else [{'nav_result':str(args.nav_result)}]
    # Preflight all images before any potentially billable request.
    for case in cases:
        nav, image = load_case(case['nav_result'])
        request_payload(image, 'preflight', nav['evidence']['capture_time'], MODEL)
    adapter=None
    if args.allow_api:
        transport=GeminiTransport(allow_api=True,timeout=args.timeout)
        adapter=SingleFrameVLM(transport,MODEL,args.timeout,decoder=response_text)
    output=ROOT/'artifacts/vlm'/f'run_{time.time_ns()}'
    output.mkdir(parents=True)
    results=[]
    for case in cases:
        result=await run_case(case['nav_result'],args,adapter)
        result['scenario']=case.get('scenario','unlabeled')  # Evaluation/display only, AFTER inference.
        results.append(result)
        (output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
        write_view(results,output)
    print(output/'index.html')


if __name__=='__main__':
    asyncio.run(main())
