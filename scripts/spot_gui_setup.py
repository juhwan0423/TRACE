"""Official Python Server entry: workspace, occlusion (optional) arguments."""
import sys
from pathlib import Path
import carb.settings
import omni.usd
import omni.timeline
import omni.ui as ui
import asyncio
import isaacsim.core.experimental.utils.app as app_utils

root = Path(workspace).resolve()
if carb.settings.get_settings().get('/haiclaw/workspace') != str(root):
    raise RuntimeError('Refusing to replace an unowned GUI stage')
for folder in (root/'scripts', root/'src'):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
from spot_lifecycle import SpotDemo
stage = omni.usd.get_context().get_stage()
if 'demo' in globals():
    if not globals().get('replace_demo', False):
        raise RuntimeError('Demo already exists: reuse GUI controls or explicitly pass --replace-demo')
    if stage.GetRootLayer().identifier != globals().get('spot_stage_id'):
        raise RuntimeError('User changed the active stage; refusing replacement')
if stage:
    import time
    stage.Export(str(root/'artifacts/spot'/f'before_setup_{time.time_ns()}.usda'))
if 'demo' in globals():
    app_utils.stop()
    await app_utils.update_app_async(steps=2)
    demo.physics_cleanup()
    if 'window' in globals():
        window.destroy()
demo = SpotDemo(root, occlusion=bool(globals().get('occlusion', False)))
await demo.load_world_async()
spot_stage_id = omni.usd.get_context().get_stage().GetRootLayer().identifier
await app_utils.update_app_async(steps=10)

async def replay(mode):
    if globals().get('reset_busy', False):
        return
    globals()['reset_busy'] = True
    try:
        demo.hold()
        await demo.reset_async()
        demo.start(mode)
    finally:
        globals()['reset_busy'] = False

window = ui.Window('HAI-CLAW | Official Spot Policy', width=380, height=210)
with window.frame:
    with ui.VStack():
        ui.Label('PhysX Spot: 500 Hz physics / 50 Hz policy')
        ui.Label('Validation: hold > forward > turn > stop')
        ui.Button('Run / Reset validation', clicked_fn=lambda: asyncio.ensure_future(replay('validation')))
        ui.Button('Zero velocity (keep balance)', clicked_fn=demo.hold)
        ui.Button('Reset and hold', clicked_fn=lambda: asyncio.ensure_future(replay('hold')))
        if demo.occlusion:
            ui.Button('Reset and follow waypoints', clicked_fn=lambda: asyncio.ensure_future(replay('waypoints')))
        ui.Label('Toolbar Stop then Play: resets pose and holds')
print('Spot setup:', demo.output, 'failure:', demo.failure, 'body:', getattr(demo, 'body_path', None))
if demo.failure:
    raise RuntimeError(demo.failure)
