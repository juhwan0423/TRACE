"""Launch an owned GUI and deploy the official Spot sample without touching other GUIs."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--scene', choices=['flat','occlusion'], default='flat')
parser.add_argument('--replace-demo', action='store_true', help='Save/replace only an existing HAI-CLAW Spot demo')
args = parser.parse_args()
install = Path(os.environ.get('ISAAC_SIM_DIR', str(root.parent/'IsaacLab/.venv/lib/python3.12/site-packages/isaacsim')))
client = install/'skills/isaac-sim-remote/scripts/isaacsim_send.py'

def listening():
    with socket.socket() as sock:
        sock.settimeout(.5)
        return sock.connect_ex(('127.0.0.1', 8226)) == 0

if not listening():
    env = dict(os.environ, HAICLAW_HEADLESS='0')
    log_dir = root/'artifacts/spot'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir/f'gui_{time.time_ns()}.log'
    with log_path.open('w') as log:
        process = subprocess.Popen(['bash', str(root/'scripts/start_sim_server.sh')], cwd=root,
                                   env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    print(f'GUI PID {process.pid}; log: {log_path}', flush=True)
    for _ in range(180):
        if process.poll() is not None:
            raise SystemExit(f'GUI exited ({process.returncode}); inspect {log_path}')
        if listening() and 'app ready' in log_path.read_text(errors='replace'):
            break
        time.sleep(1)
    else:
        raise SystemExit('GUI not ready. Preserve process; inspect log before retry.')

def send(arguments):
    subprocess.run([sys.executable, str(client), *arguments], check=True, cwd=root)

send(['--file',str(client.parent/'health_check.py')])
send(['--context','spot','--timeout','90','--args-json',json.dumps({'workspace':str(root)}),
      '--file',str(root/'scripts/spot_preflight.py')])
# Setup refuses non-owned sessions and refuses replacing an existing demo by default.
send(['--context','spot','--timeout','180','--args-json',json.dumps(dict(workspace=str(root), occlusion=args.scene=='occlusion', replace_demo=args.replace_demo)),
      '--file',str(root/'scripts/spot_gui_setup.py')])
print('GUI ready. Click Run / Reset validation. Zero velocity keeps the balancing policy active.')
