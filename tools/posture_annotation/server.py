"""Blinded human posture review of exact cited RGBs; no model/simulator calls."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[2]
COHORT = ROOT/'artifacts/comparisons/20261108_gate060_01'
DEFAULT = COHORT/'human_posture_review_20261109'
EXPECTED_COUNT = 10

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def atomic(path, value):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)

def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory/'private_manifest.json'
    if not path.exists():
        sources = [COHORT/'records.json', COHORT/'segmentation_support_annotations.json', COHORT/'protocol.json']
        records, support = [json.loads(p.read_text()) for p in sources[:2]]
        cases = []
        for record in records:
            tid = record['trial_id']; a = support[tid]
            if record['inspection_question_answer'] not in ('standing', 'lying') or a['claim_target_present'] is not True:
                continue
            refs = record['normalization']['answer_evidence_ids']
            if refs != a['evidence_ids'] or len(refs) != 1:
                raise ValueError('This packet requires exactly one bound cited image per claim')
            report = json.loads((COHORT/'trials'/tid/'result.json').read_text())
            evidence = next(e for e in report['captured_evidence'] if e['id'] == refs[0])
            image = Path(evidence['artifact']).resolve()
            if image.parent != (COHORT/'trials'/tid/'frames').resolve():
                raise ValueError('Image outside trial frames')
            digest = sha(image)
            if digest != a['frame_results'][0]['frame_sha256']:
                raise ValueError('Cited image hash mismatch')
            cases.append(dict(trial_id=tid, evidence_ids=refs, path=str(image), sha256=digest))
        if len(cases) != EXPECTED_COUNT:
            raise ValueError(f'Expected {EXPECTED_COUNT} positive-target posture claims, got {len(cases)}')
        random.Random(20261109).shuffle(cases)
        for i,c in enumerate(cases): c['id'] = f'P{i+1:02}'
        atomic(path, dict(schema=1, role='posthoc_human_posture_readability',
            source_hashes={str(p):sha(p) for p in sources}, cases=cases,
            selection='All positive-target posture assertions; policy and answer hidden; not an independent review cohort'))
    manifest = json.loads(path.read_text())
    for p,h in manifest['source_hashes'].items():
        if sha(p) != h: raise ValueError('Source changed since packet creation')
    for c in manifest['cases']:
        if sha(c['path']) != c['sha256']: raise ValueError('Review image changed')
    return manifest

def validate(value):
    if not isinstance(value, dict) or value.get('posture') not in ('standing','lying','unreadable'):
        raise ValueError('Choose a posture or unreadable')
    if type(value.get('prior_exposure', False)) is not bool:
        raise ValueError('Invalid exposure flag')
    note=value.get('note','')
    if not isinstance(note,str) or len(note)>2000: raise ValueError('Invalid note')
    return dict(posture=value['posture'], prior_exposure=value.get('prior_exposure',False),
                note=note, updated_at=datetime.now(timezone.utc).isoformat())

def make_server(directory, port):
    manifest=prepare(directory); cases={c['id']:c for c in manifest['cases']}
    path=directory/'annotations.json'; manifest_hash=sha(directory/'private_manifest.json')
    state=json.loads(path.read_text()) if path.exists() else dict(schema=1, manifest_sha256=manifest_hash, annotations={})
    if state['manifest_sha256']!=manifest_hash: raise ValueError('Annotation manifest mismatch')
    for cid,a in state['annotations'].items():
        if cid not in cases: raise ValueError('Unknown saved case')
        validate(a)
    if not path.exists(): atomic(path,state)
    token=secrets.token_urlsafe(32); lock=threading.Lock()
    html=Path(__file__).with_name('index.html').read_text().replace('__TOKEN__',token)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def send(self,data,content_type='application/json; charset=utf-8',status=200):
            if not isinstance(data,bytes): data=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status); self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            if self.path=='/': return self.send(html.encode(),'text/html; charset=utf-8')
            if self.path=='/api/state':
                with lock: return self.send(dict(cases=list(cases),annotations=state['annotations']))
            if self.path=='/export':
                with lock: return self.send(state)
            cid=self.path.removeprefix('/image/')
            if self.path.startswith('/image/') and cid in cases:
                data=Path(cases[cid]['path']).read_bytes()
                if hashlib.sha256(data).hexdigest()!=cases[cid]['sha256']:
                    return self.send(dict(error='Image hash changed'),status=409)
                return self.send(data,'image/png')
            return self.send(dict(error='Not found'),status=404)
        def do_POST(self):
            if self.path!='/api/save' or self.headers.get('X-Annotation-Token')!=token:
                return self.send(dict(error='Forbidden'),status=403)
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=12000: raise ValueError('Invalid request size')
                payload=json.loads(self.rfile.read(size)); cid=payload['id']
                if cid not in cases: raise ValueError('Unknown case')
                a=validate(payload['annotation'])
                with lock:
                    with (directory/'history.jsonl').open('a') as log:
                        log.write(json.dumps(dict(id=cid,annotation=a),ensure_ascii=False)+'\n'); log.flush(); os.fsync(log.fileno())
                    updated=dict(state,annotations=dict(state['annotations'],**{cid:a}))
                    atomic(path,updated); state.update(updated)
                return self.send(dict(saved=True,annotation=a))
            except (ValueError,KeyError,TypeError) as e: return self.send(dict(error=str(e)),status=400)
            except OSError: return self.send(dict(error='Disk save failed; retry'),status=500)
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--directory',type=Path)
    parser.add_argument('--cohort',type=Path,default=COHORT)
    parser.add_argument('--expected-count',type=int,default=EXPECTED_COUNT)
    parser.add_argument('--port',type=int,default=6174); args=parser.parse_args()
    COHORT=args.cohort.resolve(); EXPECTED_COUNT=args.expected_count
    if EXPECTED_COUNT < 1: parser.error('Expected count must be positive')
    if args.directory is None: args.directory=COHORT/'human_posture_review_20261109'
    args.directory.mkdir(parents=True,exist_ok=True)
    with (args.directory/'server.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        server=make_server(args.directory,args.port)
        print(f'Posture review: http://127.0.0.1:{server.server_port}',flush=True)
        server.serve_forever()
