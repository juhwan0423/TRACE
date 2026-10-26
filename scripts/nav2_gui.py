"""Launch the owned Spot GUI with Jazzy bridge, then attach Nav2 controls."""
import os
import argparse
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--attach', action='store_true', help='Reattach to the existing owned Spot stage without replacing it')
args = parser.parse_args()
env = dict(os.environ, HAICLAW_ROS='1')
if not args.attach:
    subprocess.run([sys.executable, str(root/'scripts/spot_gui.py'), '--scene', 'occlusion'], env=env, check=True)
install = Path(os.environ.get('ISAAC_SIM_DIR', str(root.parent/'IsaacLab/.venv/lib/python3.12/site-packages/isaacsim')))
client = install/'skills/isaac-sim-remote/scripts/isaacsim_send.py'
for script in ('nav2_bridge_setup.py', 'nav2_gui_setup.py'):
    subprocess.run([sys.executable, str(client), '--context', 'spot', '--file', str(root/'scripts'/script)], check=True)
