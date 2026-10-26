"""Prepare owned live Isaac context without replacing an existing user stage."""
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
from run_closed_loop import remote, ROOT


def listening(port):
    with socket.socket() as s:
        s.settimeout(.3)
        return s.connect_ex(('127.0.0.1', port)) == 0


async def prepare():
    logs = ROOT / 'artifacts/logs'
    logs.mkdir(parents=True, exist_ok=True)
    started = False
    if not listening(8226):
        with (logs / 'closed-loop-server.log').open('a') as log:
            process = subprocess.Popen(['bash', str(ROOT / 'scripts/start_sim_server.sh')],
                                       cwd=ROOT, env=dict(os.environ, HAICLAW_ROS='1'),
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        (logs / 'closed-loop-server.pid').write_text(str(process.pid))
        started = True
        for _ in range(180):
            if process.poll() is not None:
                raise RuntimeError('Isaac exited; inspect closed-loop-server.log')
            if listening(8226):
                break
            await asyncio.sleep(1)
        else:
            raise TimeoutError('Isaac startup timeout; existing process preserved')
    state = await remote("import json, carb.settings, omni.usd; print(json.dumps(dict(owner=carb.settings.get_settings().get('/haiclaw/workspace'), demo='demo' in globals(), camera='trace_camera' in globals(), navigation='inspection' in globals() and 'ros_bridge' in globals())))")
    if state['owner'] != str(ROOT):
        raise RuntimeError('Port 8226 belongs to another workspace; refusing changes')
    if not state['demo'] and not started:
        raise RuntimeError('Existing stage has no TRACE demo; preserve it and inspect manually')
    if state['demo'] and not state['navigation']:
        raise RuntimeError('Existing Spot session lacks ROS/Nav2; preserve it and use a dedicated TRACE session')
    install = Path(os.environ['ISAAC_SIM_DIR'])
    health = await remote((install / 'skills/isaac-sim-remote/scripts/health_check.py').read_text(), raw=True)
    print(health)
    # Remote scripts require persistent globals, matching the official context protocol.
    if not state['demo']:
        (ROOT / 'artifacts/spot').mkdir(parents=True, exist_ok=True)
        for name in ('spot_preflight.py', 'spot_gui_setup.py', 'nav2_bridge_setup.py', 'nav2_gui_setup.py'):
            response = await remote("import ast, inspect\n_setup_result = eval(compile(source, filename, 'exec', flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT))\nif inspect.isawaitable(_setup_result):\n    await _setup_result",
                         raw=True, timeout=180.,
                         source=(ROOT/'scripts'/name).read_text(), filename=name,
                         workspace=str(ROOT), occlusion=True, replace_demo=False)
            print(response)
    containers = subprocess.check_output(['docker', 'ps', '--format', '{{.Names}}'], text=True).splitlines()
    if 'haiclaw-nav2' not in containers:
        with (logs / 'closed-loop-nav2.log').open('a') as log:
            process = subprocess.Popen(['bash', str(ROOT/'scripts/start_nav2.sh')], cwd=ROOT,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        (logs/'closed-loop-nav2.pid').write_text(str(process.pid))
    if not state['camera']:
        await remote("exec(compile(source, 'closed_loop_scene.py', 'exec'))", raw=True,
                     source=(ROOT/'scripts/closed_loop_scene.py').read_text())
    print('TRACE context ready. Run scripts/run_closed_loop.py.')


if __name__ == '__main__':
    asyncio.run(prepare())
