"""Post-trial detector archive. Never feeds a planner or counts as online cost."""
import asyncio
from dataclasses import asdict, is_dataclass
import hashlib
import json
from pathlib import Path
import time

from haiclaw.core import Evidence
from haiclaw.providers.person_gate import configure_detector_environment, with_person_gate


def bound(record, evidence):
    try:
        frame_hash=hashlib.sha256(Path(evidence.artifact).read_bytes()).hexdigest()
    except OSError:
        return False
    return (record.get('frame_sha256') == frame_hash
            and all(record.get(k) == getattr(evidence, k) for k in
                    ('episode', 'generation', 'source', 'capture_time', 'artifact'))
            and record.get('evidence_id') == evidence.id)


def valid_detection(detection, evidence, config):
    expected=dict(model_path=config['model_path'], model_sha256=config['model_sha256'],
                  confidence_threshold=config['confidence'], archive_confidence=config['archive_confidence'],
                  nms_iou=config['nms_iou'], max_det=config['max_det'],
                  image_size=config['image_size'], device=config['device'])
    return (isinstance(detection,dict) and detection.get('status') in ('detected','not_detected','multiple_people')
            and detection.get('raw_boxes_stage')=='post_nms_person_candidates'
            and isinstance(detection.get('raw_boxes'),(list,tuple))
            and all(detection.get(k)==v for k,v in expected.items()) and bound(detection,evidence))


async def archive_frames(report, config, output, root, detector=None):
    output = Path(output)
    if output.exists():
        raise FileExistsError('Do not overwrite a detector audit')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(dict(schema='posttrial_detector_archive/1', complete=False,
        phase='inventory_validation_pending', expected_frames=None, recorded_frames=0, rows=[]),indent=2))
    configure_detector_environment(root)
    detector = detector or with_person_gate(None, config).detector
    online = {}
    for record in report.get('evidence_records', []):
        detection = record.get('inference', {}).get('person_gate', {}).get('detector')
        if detection is not None:
            online[record['evidence']['id']] = detection
    captured = report.get('captured_evidence')
    if not isinstance(captured,list):
        raise ValueError('Captured evidence inventory is required, including an explicit empty list')
    if len({e['id'] for e in captured}) != len(captured):
        raise ValueError('Duplicate captured evidence ID')
    capture_ids={e['id'] for e in captured}
    if any(r['evidence']['id'] not in capture_ids for r in report.get('evidence_records',[])):
        raise ValueError('Inference record missing from captured evidence inventory')
    frame_dir=output.parent/'frames'
    if frame_dir.is_dir() and ({p.resolve() for p in frame_dir.glob('*.png')} !=
                               {Path(e['artifact']).resolve() for e in captured}):
        raise ValueError('PNG inventory differs from captured evidence inventory')
    rows = []
    def persist():
        data = dict(schema='posttrial_detector_archive/1', phase='after_harness_finished',
                    excluded_from_online_cost=True, expected_frames=len(captured), recorded_frames=len(rows),
                    complete=len(rows)==len(captured) and all(r.get('validated') is True for r in rows), rows=rows)
        temporary=output.with_suffix('.tmp')
        temporary.write_text(json.dumps(data,indent=2))
        temporary.replace(output)
    persist()
    for value in captured:
        row=dict(evidence=value, validated=False)
        rows.append(row)
        try:
            evidence=Evidence(**value)
            evaluator_dir=output.parent/'evaluator'
            if evaluator_dir.is_dir():
                saved=json.loads((evaluator_dir/(evidence.id+'.json')).read_text())
                if saved.get('frame_sha256')!=hashlib.sha256(Path(evidence.artifact).read_bytes()).hexdigest():
                    raise ValueError('RGB changed since paired evaluator capture')
            detection=online.get(evidence.id)
            reused=valid_detection(detection,evidence,config)
            if not reused:
                started=time.monotonic()
                result=await asyncio.wait_for(detector.infer(evidence),config['timeout_seconds'])
                if time.monotonic()-started>config['timeout_seconds']:
                    raise TimeoutError('Late offline detector result discarded')
                detection=asdict(result) if is_dataclass(result) else dict(result)
            row.update(origin='online_gate' if reused else 'posttrial_only', detector=detection)
            if not valid_detection(detection,evidence,config):
                raise RuntimeError('Incomplete, wrong-recipe or unbound detector archive')
            row['validated']=True
            persist()
        except BaseException as error:
            row.update(validated=False,audit_error=type(error).__name__+': '+str(error))
            persist()
            raise
    return dict(captured_frames=len(captured), reused_online=sum(r.get('origin')=='online_gate' for r in rows),
                posttrial_calls=sum(r.get('origin')=='posttrial_only' for r in rows))
