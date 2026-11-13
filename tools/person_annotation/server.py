"""Loopback-only, blinded annotation of archived person-detector frames."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import secrets
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / 'artifacts/person_detector/manual_review_20261108'
SOURCE = ROOT / 'artifacts/person_detector/20261108_legacy_all_frames/results.json'


def atomic(path, value):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def prepare(directory, source=SOURCE):
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / 'private_manifest.json'
    if not manifest.exists():
        rows = json.loads(source.read_text())['rows']
        random.Random(20261108).shuffle(rows)
        frames = []
        for i, row in enumerate(rows):
            d = row['detector']
            p = Path(d['artifact'])
            if hashlib.sha256(p.read_bytes()).hexdigest() != d['frame_sha256']:
                raise ValueError('Archived image hash mismatch')
            frames.append(dict(id=f'F{i+1:03}', path=str(p), sha256=d['frame_sha256'],
                               size=d['frame_size'], trial_id=row['trial_id'], evidence_id=d['evidence_id']))
        atomic(manifest, dict(schema_version=1, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                             role='retrospective_human_rgb_annotation', frames=frames))
    data = json.loads(manifest.read_text())
    for frame in data['frames']:
        if hashlib.sha256(Path(frame['path']).read_bytes()).hexdigest() != frame['sha256']:
            raise ValueError('Archived image changed since packet creation')
    return data


def validate(value, frame):
    if not isinstance(value, dict):
        raise ValueError('Invalid annotation')
    presence = value.get('presence')
    posture = value.get('posture')
    done = value.get('done')
    box = value.get('box')
    if presence not in (None, 'visible', 'absent', 'uncertain'):
        raise ValueError('Invalid presence')
    if posture not in (None, 'standing', 'lying', 'unreadable') or type(done) is not bool:
        raise ValueError('Invalid posture or completion')
    if box is not None:
        if not isinstance(box, list) or len(box) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in box):
            raise ValueError('Invalid box')
        x1, y1, x2, y2 = box
        w, h = frame['size']
        if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
            raise ValueError('Box outside image or zero size')
    if presence != 'visible' and (box is not None or posture is not None):
        raise ValueError('Only visible target can have box/posture')
    if done and (presence is None or (presence == 'visible' and (box is None or posture is None))):
        raise ValueError('Complete visible cases need box and posture')
    flags = {k: value.get(k, False) for k in ('occluded', 'truncated', 'prior_exposure')}
    if any(type(x) is not bool for x in flags.values()):
        raise ValueError('Invalid flags')
    note = value.get('note', '')
    if not isinstance(note, str) or len(note) > 2000:
        raise ValueError('Invalid note')
    return dict(presence=presence, posture=posture, box=box, done=done, **flags,
                note=note, updated_at=datetime.now(timezone.utc).isoformat())


def make_server(directory, port):
    manifest = prepare(directory)
    frames = {f['id']: f for f in manifest['frames']}
    path = directory / 'annotations.json'
    state = json.loads(path.read_text()) if path.exists() else dict(schema_version=1,
        role='retrospective_human_rgb_annotation', manifest_sha256=hashlib.sha256((directory/'private_manifest.json').read_bytes()).hexdigest(), annotations={})
    if not path.exists():
        atomic(path, state)
    token = secrets.token_urlsafe(32)
    lock = threading.Lock()
    html = (Path(__file__).with_name('index.html')).read_text().replace('__TOKEN__', token)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, data, content_type='application/json; charset=utf-8', status=200):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == '/':
                return self.send(html.encode(), 'text/html; charset=utf-8')
            if self.path == '/api/state':
                with lock:
                    return self.send(dict(frames=[dict(id=f['id'], size=f['size']) for f in manifest['frames']],
                                          annotations=state['annotations']))
            if self.path == '/export':
                with lock:
                    return self.send(state)
            if self.path.startswith('/image/') and self.path[7:] in frames:
                return self.send(Path(frames[self.path[7:]]['path']).read_bytes(), 'image/png')
            return self.send({'error': 'Not found'}, status=404)

        def do_POST(self):
            if self.path != '/api/save' or self.headers.get('X-Annotation-Token') != token:
                return self.send({'error': 'Forbidden'}, status=403)
            try:
                n = int(self.headers.get('Content-Length', '0'))
                if not 0 < n <= 12000:
                    raise ValueError('Invalid request size')
                payload = json.loads(self.rfile.read(n))
                fid = payload['id']
                result = validate(payload['annotation'], frames[fid])
                with lock:
                    entry = dict(id=fid, annotation=result)
                    with (directory/'history.jsonl').open('a') as log:
                        log.write(json.dumps(entry, ensure_ascii=False)+'\n')
                        log.flush()
                        os.fsync(log.fileno())
                    state['annotations'][fid] = result
                    atomic(path, state)
                return self.send(dict(saved=True, annotation=result))
            except (ValueError, KeyError, TypeError) as e:
                return self.send({'error': str(e)}, status=400)
            except OSError:
                return self.send({'error': 'Disk save failed; please retry'}, status=500)

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, default=DEFAULT)
    parser.add_argument('--port', type=int, default=6173)
    args = parser.parse_args()
    # One server owns the annotation files. Never overwrite an existing review.
    import fcntl
    args.directory.mkdir(parents=True, exist_ok=True)
    with (args.directory/'server.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        server = make_server(args.directory, args.port)
        print(f'Annotation UI: http://127.0.0.1:{args.port}', flush=True)
        print(f'Saves: {args.directory / "annotations.json"}', flush=True)
        server.serve_forever()
