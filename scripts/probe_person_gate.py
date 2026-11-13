"""Fresh Qwen + RGB detector smoke on archived frames, never a policy comparison."""
import argparse
import asyncio
from dataclasses import asdict
import fcntl
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tracebot.core import Evidence
from tracebot.providers.ollama import make_adapter
from tracebot.providers.person_gate import detector_config, with_person_gate, configure_detector_environment


async def run(args):
    config = detector_config(args.detector_config)
    model = json.loads(args.model_config.read_text())
    paths = [Path(x).resolve() for x in json.loads(args.frames.read_text())]
    if not paths or any(not p.is_file() for p in paths):
        raise ValueError('Existing archived frame paths required')
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = dict(role='development_integration_smoke', closed_loop=False,
        detector=config, model=model,
        frames=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths],
        selection_note=args.selection_note,
        packages={n:version(n) for n in ('ultralytics','torch','torchvision','Pillow')},
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in [Path(__file__), *sorted((ROOT/'src/tracebot/providers').glob('*.py'))]},
        comparison='one fresh Qwen call per image; raw and gated interpretations of that same call; no adaptive-agent effect measured')
    (args.output/'protocol.json').write_text(json.dumps(protocol,indent=2))
    configure_detector_environment(ROOT)
    adapter = with_person_gate(make_adapter(model),config)
    rows=[]
    for index,p in enumerate(paths):
        evidence = Evidence(str(uuid.uuid4()),'person-gate-smoke','archived_rgb',0.,0.,str(p))
        effective, record = await adapter.infer(evidence)
        row=dict(index=index,evidence=asdict(evidence),inference=record,effective=asdict(effective))
        rows.append(row)
        (args.output/'results.json').write_text(json.dumps(rows,indent=2))
        print(json.dumps(dict(index=index,vlm_status=record['status'],
            raw_person_visible=record['interpretation']['person_visible'],
            raw_posture=record['interpretation']['posture'],effective_posture=effective.posture,
            detector_status=record['person_gate']['detector']['status'],
            interpretation_changed=record['person_gate']['interpretation_changed'],
            qwen_seconds=record['latency_wall_seconds'],
            detector_seconds=record['person_gate']['detector_latency_wall_seconds'])),flush=True)
    return 0 if all(r['inference']['status']=='ok' and r['inference']['person_gate']['detector']['status']
                    not in ('error','unavailable','timeout') for r in rows) else 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frames',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--selection-note',required=True)
    p.add_argument('--model-config',type=Path,default=ROOT/'configs/vlm_local.json')
    p.add_argument('--detector-config',type=Path,default=ROOT/'configs/person_gate_yolo11n.json')
    args=p.parse_args()
    lock=ROOT/'artifacts/closed_loop/runner.lock';lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        raise SystemExit(asyncio.run(run(args)))
