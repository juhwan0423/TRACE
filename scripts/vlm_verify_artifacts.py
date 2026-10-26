"""Offline syntax/PNG/arrival-metadata/dry-run-view verification; no API calls."""
import ast
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import struct

root = Path(__file__).resolve().parents[1]
files = list((root/'scripts').glob('vlm_*.py')) + [root/p for p in (
    'src/haiclaw/providers/single_frame_vlm.py', 'src/haiclaw/providers/gemini.py',
    'tests/test_single_frame_vlm.py')]
for path in files:
    compile(path.read_text(), str(path), 'exec', flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
rows = []
for case in json.loads((root/'artifacts/vlm/cases.json').read_text()):
    record = json.loads(Path(case['nav_result']).read_text())
    evidence, check = record['evidence'], record['capture_validation']
    data = Path(evidence['artifact']).read_bytes()
    assert data.startswith(b'\x89PNG\r\n\x1a\n')
    width, height = struct.unpack('>II', data[16:24])
    assert record['status'] == 'arrived'
    assert evidence['capture_time'] > max(record['arrived_at'], check['authored_at'])
    assert evidence['received_time'] >= evidence['capture_time']
    assert check['xy_error'] <= .25 and check['yaw_error'] <= .15
    assert (width, height) == (640, 360)
    rows.append(dict(scenario=case['scenario'], image=evidence['artifact'], width=width,
                     height=height, bytes=len(data), arrival=record['arrived_at'],
                     capture=evidence['capture_time'], **check))
viewer = Path((root/'artifacts/vlm/three_case_dry_run.log').read_text().strip())
results = json.loads(viewer.with_name('results.json').read_text())
assert len(results) == 3
assert all(r['mode'] == 'dry_run_no_inference' and r['raw_response'] is None
           and r['final_incident_state'] is None for r in results)
assert viewer.read_text().count('<img ') == 3
HTMLParser().feed(viewer.read_text())
guide_hash = hashlib.sha256((root/'implementation_guide.md').read_bytes()).hexdigest()
assert guide_hash == '09adb11f375e5b03dff4b0f4713e9eff925ba7253c9d6f67bbaf76c42ac66403'
output = dict(syntax_files=len(files), captures=rows, dry_run_viewer=str(viewer),
              actual_api_calls=0, guide_sha256=guide_hash)
(root/'artifacts/vlm/verification.json').write_text(json.dumps(output, indent=2))
print('PASS: syntax, 3 capture contracts, dry-run HTML/JSON, unchanged guide')
