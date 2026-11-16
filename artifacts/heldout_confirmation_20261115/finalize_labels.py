"""Freeze the user's blinded labels (no edits) and map them to support_annotations.json, same
format as 2026-11-09. Verifies image/source hashes and exact cited-frame bindings."""
import hashlib,json,shutil,sys,datetime
from pathlib import Path
h=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
for c in sys.argv[1:]:
    c=Path(c);r=c/'human_posture_review_20261115';m=json.loads((r/'private_manifest.json').read_text());a=json.loads((r/'annotations.json').read_text())
    assert a['manifest_sha256']==h(r/'private_manifest.json')
    assert all(h(p)==v for p,v in m['source_hashes'].items()),'source changed'
    seg=json.loads((c/'segmentation_support_annotations.json').read_text());out={}
    assert len(a['annotations'])==len(m['cases'])
    for case in m['cases']:
        lab=a['annotations'][case['id']];assert h(case['path'])==case['sha256']
        s=seg[case['trial_id']];assert set(s['evidence_ids'])==set(case['evidence_ids']) and s['claim_target_present'] is True
        assert lab['posture'] in ('standing','lying','unreadable')
        out[case['trial_id']]=dict(evidence_ids=case['evidence_ids'],claim_target_present=True,claim_observed_posture=lab['posture'],source='user_blinded_rgb_review',review_id=case['id'],prior_exposure=lab['prior_exposure'],note=lab['note'])
    f=r/'finalized_v1';f.mkdir(exist_ok=False)
    for n in ('annotations.json','private_manifest.json','history.jsonl'):shutil.copy2(r/n,f/n)
    (f/'support_annotations.json').write_text(json.dumps(out,indent=1));(c/'support_annotations.json').write_text(json.dumps(out,indent=1))
    (f/'provenance.json').write_text(json.dumps(dict(finalized_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),review='Single user blinded RGB review (same rater as 2026-11-08/09); not multiple-rater adjudication',hashes={n:h(f/n) for n in ('annotations.json','private_manifest.json','history.jsonl')}),indent=1))
    print(c.name,len(out))
