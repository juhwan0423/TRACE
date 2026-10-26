import json, math
import numpy as np
from PIL import Image
if inspection.run.status != 'arrived' or inspection.run.evidence is None:
    raise RuntimeError('No successful arrival/fresh frame to validate')
arrival_t = inspection.run.arrived_at - (inspection.run.sim_deadline-180.)
while demo.elapsed < arrival_t+4.:
    await app_utils.update_app_async(steps=5)
records = list(demo.records)
post = [r for r in records if arrival_t+1. <= r['t'] <= arrival_t+4.]
arrival = min(records, key=lambda r:abs(r['t']-arrival_t))
frame_t = inspection.run.evidence['capture_time']-(inspection.run.sim_deadline-180.)
frame = min(records, key=lambda r:abs(r['t']-frame_t))
image_path = inspection.run.evidence['artifact']
image = np.asarray(Image.open(image_path).convert('RGB'))
travel = [r for r in records if 0 <= r['t'] <= arrival_t+4]
xy_error = math.dist(arrival['position'][:2], inspection.run.target[:2])
yaw_error = abs(math.atan2(math.sin(arrival['yaw']-inspection.run.target[2]), math.cos(arrival['yaw']-inspection.run.target[2])))
residual = max(math.dist(r['position'][:2],post[0]['position'][:2]) for r in post)
final_speed = np.mean([math.hypot(*r['velocity'][:2]) for r in post[-25:]])
checks = dict(arrived=inspection.run.status=='arrived', xy=xy_error<=.25, yaw=yaw_error<=.15,
              fresh=inspection.run.evidence['capture_time']>inspection.run.arrived_at,
              height=all(.35<=r['position'][2]<=.85 for r in travel),
              tilt=all(r['tilt_deg']<=25 for r in travel), residual=residual<=.15, stop_speed=final_speed<=.08)
checks = {k: bool(v) for k,v in checks.items()}
summary = dict(passed=all(checks.values()), checks=checks, position_error_m=xy_error, yaw_error_rad=yaw_error,
               stop_residual_m=residual, stop_final_speed_mps=float(final_speed),
               frame_pose=frame['position'], frame_yaw=frame['yaw'], arrival_pose=arrival['position'],
               rgb_mean=float(image.mean()), rgb_std=float(image.std()), image_bytes=Path(image_path).stat().st_size,
               resolution=list(image.shape), scan_messages=ros_bridge.scan_messages,
               scan_age=SimulationManager.get_simulation_time()-ros_bridge.last_scan)
(inspection.output/'verification.json').write_text(json.dumps(summary,indent=2))
(inspection.output/'telemetry.json').write_text(json.dumps(travel))
inspection.save()
print(json.dumps(summary,indent=2))
