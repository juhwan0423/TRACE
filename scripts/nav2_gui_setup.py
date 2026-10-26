import importlib
importlib.invalidate_caches()
import nav2_inspection
importlib.reload(nav2_inspection)
from nav2_inspection import Nav2Inspection
if 'inspection' in globals() and inspection.bridge is ros_bridge:
    inspection.close()
inspection = Nav2Inspection(ros_bridge, root)
inspection.update_subscription = omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(inspection.update, name='HAICLAW inspection')
if 'nav_window' in globals():
    nav_window.destroy()
nav_start_busy = False
nav_start_generation = 0

async def reset_and_navigate():
    global nav_start_busy
    if nav_start_busy or (inspection.run and inspection.run.status == 'moving'):
        return
    nav_start_busy = True
    generation = nav_start_generation
    target = (goal_x.model.as_float, goal_y.model.as_float, goal_yaw.model.as_float * 3.141592653589793 / 180.)
    try:
        await replay('hold')
        while demo.elapsed < 3.:
            await app_utils.update_app_async(steps=5)
        if generation == nav_start_generation:
            inspection.start(*target)
    finally:
        nav_start_busy = False


def cancel_navigation():
    global nav_start_generation
    nav_start_generation += 1
    inspection.cancel()

nav_window = ui.Window('HAI-CLAW | Nav2 inspection', width=430, height=260)
with nav_window.frame:
    with ui.VStack():
        ui.Label('Goal: map x, y (m), yaw (degrees)')
        with ui.HStack():
            goal_x = ui.FloatField(); goal_x.model.set_value(3.)
            goal_y = ui.FloatField(); goal_y.model.set_value(1.3)
            goal_yaw = ui.FloatField(); goal_yaw.model.set_value(180.)
        ui.Label('Ground-truth localization / PhysX planar scan')
        ui.Button('Reset Spot, navigate, capture', clicked_fn=lambda: asyncio.ensure_future(reset_and_navigate()))
        ui.Button('Cancel and stop', clicked_fn=cancel_navigation)
        ui.Label('Result + fresh RGB: artifacts/nav2/<run>/')
        nav_status_label = ui.Label('Idle')
print('Nav2 server ready:', inspection.client.server_is_ready(), 'bridge failure:', ros_bridge.failure)

if 'nav_status_subscription' in globals():
    nav_status_subscription = None

def refresh_nav_status(event):
    run = inspection.run
    if run is None:
        nav_status_label.text = 'Idle'
    else:
        detail = 'RGB saved' if run.evidence else (inspection.capture_failure or run.reason or '')
        nav_status_label.text = f'{run.status} {detail}'
nav_status_subscription = omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(refresh_nav_status, name='HAICLAW navigation status')
