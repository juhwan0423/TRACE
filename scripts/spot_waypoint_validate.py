"""After flat-floor success: exercise the same runner in the occlusion scene."""
import json
import time
import math
from PIL import Image
from isaacsim.core.simulation_manager import SimulationManager
assert all(r['passed'] for r in json.loads((root/'artifacts/spot/flat_summary.json').read_text()))
assert demo.occlusion
await replay('waypoints')
start = time.monotonic()
while demo.elapsed < demo.config['waypoint_timeout_seconds'] and not demo.failure:
    await app_utils.update_app_async(steps=1)
    if getattr(demo, 'follower', None) and demo.follower.status != 'moving':
        break
    if time.monotonic()-start > 240:
        demo.failure = 'Waypoint wall-clock timeout'
        break
status = demo.follower.status
# Stop residual uses same grace and limits as flat-floor validation.
demo.hold()
end = demo.elapsed + 4
while demo.elapsed < end and not demo.failure:
    await app_utils.update_app_async(steps=1)
demo.save()
records = demo.records
active = [r for r in records if r['t']>=3]
stop = [r for r in records if r['t']>=end-3]
residual = max(math.dist(stop[0]['position'][:2],r['position'][:2]) for r in stop) if stop else float('inf')
position = records[-1]['position'] if records else [0,0,0]
summary = dict(status=status, failure=demo.failure, final_position=position,
               final_distance=math.dist(position[:2], (3,1)), stop_residual=residual,
               height_min=min(r['position'][2] for r in active), height_max=max(r['position'][2] for r in active),
               tilt_max=max(r['tilt_deg'] for r in active), body=demo.body_path)
summary['passed'] = (status=='arrived' and not demo.failure and summary['final_distance']<=demo.config['waypoint_tolerance_m']
                     and residual<=demo.config['stop_residual_max_m']
                     and summary['height_min']>=demo.config['height_range_m'][0]
                     and summary['height_max']<=demo.config['height_range_m'][1]
                     and summary['tilt_max']<=demo.config['max_tilt_degrees'])
(root/'artifacts/spot/waypoint_summary.json').write_text(json.dumps(summary,indent=2))
(root/'artifacts/spot/waypoint_telemetry.json').write_text(json.dumps(records))
frame, info = demo.camera.get_data('rgb')
if frame is not None:
    Image.fromarray(frame.numpy()).save(root/'artifacts/spot/body_camera.png')
print(json.dumps(summary,indent=2))
assert summary['passed'], 'Waypoint validation failed; inspect telemetry'
