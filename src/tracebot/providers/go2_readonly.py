"""Read-only Go2 telemetry and Jetson RealSense snapshots over Tailscale SSH.

Run: PYTHONPATH=src python3 -m tracebot.providers.go2_readonly
No credentials leave Jetson; no robot motion endpoints are exposed.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import time

REMOTE = r'''
import base64, json, pathlib, shlex, time, urllib.request
cfg = {}
for line in pathlib.Path('/home/unitree/go2_bridge_project/config/bridge.env').read_text().splitlines():
    fields = shlex.split(line, comments=True)
    if fields and fields[0] == 'export': fields = fields[1:]
    if fields and '=' in fields[0]:
        k, v = fields[0].split('=', 1); cfg[k] = v
url = 'http://%s:%s' % (cfg.get('BRIDGE_HOST', '127.0.0.1'), cfg.get('BRIDGE_PORT', '8765'))
result = {'source': 'go2-jetson', 'camera_source': 'Jetson RealSense /dev/video4'}
for endpoint in ('health', 'state'):
    request = urllib.request.Request(url + '/' + endpoint, headers={'X-Bridge-Token': cfg['BRIDGE_TOKEN']})
    with urllib.request.urlopen(request, timeout=5) as response:
        result[endpoint] = json.load(response)
import cv2
cap = cv2.VideoCapture(4, cv2.CAP_V4L2)
try:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    cap.set(cv2.CAP_PROP_FPS, 30)
    for _ in range(15):
        ok, frame = cap.read()
        if not ok: raise RuntimeError('RealSense frame unavailable')
    result['frame_received_unix_s'] = time.time()
    ok, encoded = cv2.imencode('.jpg', frame)
    if not ok: raise RuntimeError('JPEG encoding failed')
    result['jpeg_base64'] = base64.b64encode(encoded).decode()
except Exception as exc:
    result['camera_error'] = str(exc)
finally:
    cap.release()
print(json.dumps(result))
'''

class Go2ReadOnly:
    def __init__(self, host='unitree@100.114.58.53'):
        self.host = host

    def capture(self, output):
        proc = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                               self.host, 'python3 -'], input=REMOTE, text=True,
                              capture_output=True, timeout=40, check=True)
        result = json.loads(proc.stdout)
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        encoded = result.pop('jpeg_base64', None)
        if encoded:
            frame = output / 'frame.jpg'
            frame.write_bytes(base64.b64decode(encoded, validate=True))
            result['frame_path'] = str(frame.resolve())
        result['received_unix_s'] = time.time()
        (output / 'state.json').write_text(json.dumps(result, indent=2) + '\n')
        return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='artifacts/go2/' + time.strftime('%Y%m%d-%H%M%S'))
    args = parser.parse_args()
    print(json.dumps(Go2ReadOnly().capture(args.output), indent=2))
