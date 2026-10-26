"""Run flat-floor validation and a reset replay through the owned GUI."""
import json
import time
from haiclaw.spot_validation import evaluate
from isaacsim.core.simulation_manager import SimulationManager
summaries = []
for replay_index in range(2):
    await replay('validation')
    ids = (demo._physics_callback_id, demo._timeline_stop_callback_id)
    demo._register_physics_callback()
    assert ids == (demo._physics_callback_id, demo._timeline_stop_callback_id), 'duplicate callback registration'
    step_start = SimulationManager.get_num_physics_steps()
    wall_start = time.monotonic()
    while demo.elapsed < 19 and not demo.failure:
        await app_utils.update_app_async(steps=1)
        if time.monotonic()-wall_start > 180:
            demo.failure = 'Validation wall-clock timeout'
            demo.hold()
            demo.save()
            raise RuntimeError(demo.failure)
    demo.hold()
    demo.save()
    result = evaluate(demo.records, demo.config, demo.failure)
    result['physics_ticks'] = demo.ticks
    result['engine_steps'] = SimulationManager.get_num_physics_steps()-step_start
    result['callback_ids_unchanged'] = ids == (demo._physics_callback_id, demo._timeline_stop_callback_id)
    result['records'] = len(demo.records)
    result['first_position'] = demo.records[0]['position'] if demo.records else None
    (root/'artifacts/spot'/f'flat_replay_{replay_index}.json').write_text(json.dumps(result,indent=2))
    (root/'artifacts/spot'/f'flat_telemetry_{replay_index}.json').write_text(json.dumps(demo.records))
    summaries.append(result)
    print('REPLAY', replay_index, json.dumps(result))
    if not result['passed']:
        break
(root/'artifacts/spot/flat_summary.json').write_text(json.dumps(summaries,indent=2))
assert len(summaries)==2 and all(r['passed'] for r in summaries), 'Flat validation failed; do not integrate occlusion scene'
import math
reset_error = math.dist(summaries[0]['first_position'], summaries[1]['first_position'])
lifecycle = dict(reset_pose_error_m=reset_error, reset_pass=reset_error<=demo.config['reset_pose_tolerance_m'],
                 callback_pass=all(r['physics_ticks']==r['engine_steps'] and r['callback_ids_unchanged'] for r in summaries))
(root/'artifacts/spot/lifecycle.json').write_text(json.dumps(lifecycle,indent=2))
assert lifecycle['reset_pass'] and lifecycle['callback_pass'], lifecycle
