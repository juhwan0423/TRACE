"""Send the camera experiment to an already-running, owned Python Server."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--timeout', type=int, default=300)
args = parser.parse_args()
install = Path(os.environ.get('ISAAC_SIM_DIR', str(root.parent / 'IsaacLab/.venv/lib/python3.12/site-packages/isaacsim')))
client = install / 'skills/isaac-sim-remote/scripts/isaacsim_send.py'
import json
health = subprocess.run([sys.executable, str(client), '--timeout', '30', '--file',
                         str(client.parent / 'health_check.py')], check=False)
if health.returncode:
    raise SystemExit(health.returncode)
command = [sys.executable, str(client), '--context', 'haiclaw', '--timeout', str(args.timeout),
           '--execution-timeout', str(args.timeout-10), '--args-json', json.dumps({'workspace': str(root)}),
           '--file', str(root/'scripts/occlusion_demo.py')]
raise SystemExit(subprocess.call(command))
