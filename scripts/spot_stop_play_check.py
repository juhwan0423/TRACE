"""Explicit toolbar-equivalent Stop/Play check after waypoint motion."""
import json
import math
from isaacsim.core.simulation_manager import SimulationManager
ids = (demo._physics_callback_id, demo._timeline_stop_callback_id)
demo.hold()
omni.timeline.get_timeline_interface().stop()
await app_utils.update_app_async(steps=3)
omni.timeline.get_timeline_interface().play()
start_steps = SimulationManager.get_num_physics_steps()
start_ticks = demo.ticks
for _ in range(180):
    await app_utils.update_app_async(steps=1)
p, q, v, w, yaw, tilt = demo.state()
check = dict(command=demo._base_command.tolist(), position=p.tolist(), height=float(p[2]), tilt=tilt,
             callback_ids_unchanged=ids==(demo._physics_callback_id, demo._timeline_stop_callback_id),
             engine_steps=SimulationManager.get_num_physics_steps()-start_steps,
             callback_steps=demo.ticks-start_ticks, failure=demo.failure,
             reset_xy_error=math.dist(p[:2], demo._spawn_position[:2]))
check['passed'] = (check['callback_ids_unchanged'] and check['engine_steps']==check['callback_steps']
                   and check['command']==[0.,0.,0.] and check['reset_xy_error']<=demo.config['reset_pose_tolerance_m']
                   and demo.config['height_range_m'][0]<=p[2]<=demo.config['height_range_m'][1]
                   and tilt<=demo.config['max_tilt_degrees'] and not demo.failure)
(root/'artifacts/spot/stop_play.json').write_text(json.dumps(check,indent=2))
print(json.dumps(check,indent=2))
assert check['passed'], 'Stop/Play check failed'
demo.save()
