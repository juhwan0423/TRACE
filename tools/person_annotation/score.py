"""Score a frozen human review against cached detections. No model invocation."""
import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def iou(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union > 0 else 0.


def fraction(k, n):
    return dict(numerator=k, denominator=n, value=k/n if n else None)


def score(rows, confidence=.25, overlap=.5):
    if not 0 < overlap <= 1 or not 0 < confidence <= 1:
        raise ValueError('Threshold must be in (0,1]')
    values=[]
    for row in rows:
        a,d=row['annotation'],row['detector']
        valid=d['status'] in ('detected','not_detected','multiple_people')
        boxes=[b for b in d.get('boxes',[]) if b['confidence'] >= confidence] if valid else []
        overlaps=[iou(a['box'], b['xyxy']) for b in boxes] if a['presence']=='visible' else []
        matched=bool(overlaps and max(overlaps)>=overlap)
        # At higher thresholds this is cached post-NMS filtering, not re-inference.
        gate=valid and len(boxes)==1
        values.append(dict(id=row['id'],trial_id=row['trial_id'],evidence_id=row['evidence_id'],
            presence=a['presence'],posture=a['posture'],prior_exposure=a['prior_exposure'],source=d.get('source'),
            detector_valid=valid,boxes=len(boxes),target_matched=matched,best_iou=max(overlaps,default=0.),
            gate_pass=gate,gate_iou_match=gate and matched,
            unmatched_boxes=len(boxes)-int(matched) if a['presence']!='uncertain' else None))
    visible=[r for r in values if r['presence']=='visible'];absent=[r for r in values if r['presence']=='absent']
    valid_absent=[r for r in absent if r['detector_valid']]
    readable=[r for r in visible if r['posture'] in ('standing','lying')]
    def recall(rs):return fraction(sum(r['target_matched'] for r in rs),len(rs))
    known=[r for r in values if r['presence']!='uncertain' and r['detector_valid']]
    return dict(confidence=confidence,iou_threshold=overlap,frames=len(rows),
        visible=len(visible),absent=len(absent),uncertain=len(values)-len(visible)-len(absent),
        detector_errors=sum(not r['detector_valid'] for r in values),
        recall=recall(visible),standing_recall=recall([r for r in visible if r['posture']=='standing']),
        lying_recall=recall([r for r in visible if r['posture']=='lying']),
        absent_any_false_positive=fraction(sum(r['boxes']>0 for r in valid_absent),len(valid_absent)),
        absent_singleton_gate_pass=fraction(sum(r['gate_pass'] for r in valid_absent),len(valid_absent)),
        readable_gate_rejection=fraction(sum(not r['gate_pass'] for r in readable),len(readable)),
        visible_correct_singleton=fraction(sum(r['gate_iou_match'] for r in visible),len(visible)),
        visible_singleton_below_iou=sum(r['gate_pass'] and not r['target_matched'] for r in visible),
        object_precision=fraction(sum(r['target_matched'] for r in known),sum(r['boxes'] for r in known)),
        unmatched_boxes=sum(r['unmatched_boxes'] for r in known),
        per_frame=values)


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def load(review, detections):
    a=json.loads((review/'annotations.json').read_text());m=json.loads((review/'private_manifest.json').read_text())
    d=json.loads(detections.read_text())
    if a['manifest_sha256']!=sha(review/'private_manifest.json') or m['source_sha256']!=sha(detections):
        raise ValueError('Manifest/source digest mismatch')
    frames=m['frames']; ids=[f['id'] for f in frames]
    if len(set(ids))!=len(ids) or set(ids)!=set(a['annotations']):
        raise ValueError('Missing/duplicate annotation IDs')
    keyed={(r['trial_id'],r['detector']['evidence_id']):r for r in d['rows']}
    if len(keyed)!=len(d['rows']) or len(keyed)!=len(frames):raise ValueError('Duplicate or unmatched detection IDs')
    rows=[]
    # Shared UI validation checks finite in-bounds boxes and mandatory content.
    from server import validate
    for f in frames:
        ann=a['annotations'][f['id']]; validate(ann,f)
        if not ann['done']:raise ValueError('Unfinalized annotation')
        det=keyed[(f['trial_id'],f['evidence_id'])]['detector']
        if f['sha256']!=det['frame_sha256'] or sha(Path(f['path']))!=f['sha256'] or f['size']!=det['frame_size']:
            raise ValueError('Frame binding or size mismatch')
        if det['confidence_threshold']!=.25:raise ValueError('Unexpected cached detector threshold')
        rows.append(dict(**f,annotation=ann,detector=det))
    return rows


def main():
    p=argparse.ArgumentParser();p.add_argument('--review',type=Path,required=True);p.add_argument('--detections',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    rows=load(args.review,args.detections)
    result=dict(role='retrospective_single_reviewer_development_audit',
        matching='One annotated visible worker per frame; one best IoU match >=0.5; extra boxes are unmatched',
        annotation_sha256=sha(args.review/'annotations.json'),manifest_sha256=sha(args.review/'private_manifest.json'),
        detections_sha256=sha(args.detections),scorer_sha256=sha(Path(__file__)),
        trial_count=len({r['trial_id'] for r in rows}),visible_trial_count=len({r['trial_id'] for r in rows if r['annotation']['presence']=='visible'}),
        prior_exposure_frames=sum(r['annotation']['prior_exposure'] for r in rows),
        baseline=score(rows),
        by_camera={s:score([r for r in rows if r['detector']['source']==s]) for s in sorted({r['detector']['source'] for r in rows})},
        exploratory_cached_thresholds=[{k:v for k,v in score(rows,confidence=c).items() if k!='per_frame'} for c in (.4,.5,.6,.7,.8,.9)],
        limitations=['Single researcher review, not independent adjudication or simulator segmentation truth',
          '61 correlated frames from 10 prior development executions; only 7 visible frames',
          'Human boxes enclose visible extent, so this is a visible-box IoU evaluation',
          'Threshold analysis uses same development labels and filters cached post-NMS boxes; no new inference or held-out evidence',
          'Detector-only proxy; no closed-loop effect or newly prevented Qwen error established'])
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in result['baseline'].items() if k!='per_frame'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
