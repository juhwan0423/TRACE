"""Execute via the official Python Server client (top-level await supported).

Injected arguments: workspace (absolute path). Run only in our dedicated session.
"""
import json
import sys
import time
from pathlib import Path
import numpy as np
from PIL import Image
from pxr import UsdGeom, Gf
import carb.settings
import omni.usd
import omni.timeline
import isaacsim.core.experimental.utils.app as app_utils
import isaacsim.core.experimental.utils.stage as stage_utils

root = Path(workspace).resolve()
output = root / 'artifacts' / 'occlusion'
output.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(root / 'scripts'))
from build_scene import build, aim

context = omni.usd.get_context()
stage = context.get_stage()
# Refuse to replace a user's scene. The dedicated launcher identifies ownership.
settings = carb.settings.get_settings()
if settings.get('/haiclaw/workspace') != str(root):
    raise RuntimeError('Not a HAI-CLAW-owned session: preserve the existing stage.')
if stage:
    backup = output / ('before_demo_' + str(time.time_ns()) + '.usda')
    if not stage.Export(str(backup)):
        raise RuntimeError('Backup failed; stage replacement refused')
await stage_utils.create_new_stage_async(template='empty')
stage = context.get_stage()
settings.set('/rtx/rendermode', 'RayTracedLighting')
settings.set('/rtx/post/tonemap/op', 4)
sensors = build(stage)
await app_utils.update_app_async(steps=120)
omni.timeline.get_timeline_interface().play()
await app_utils.update_app_async(steps=200)
records = []

async def capture(name, phase):
    start = time.perf_counter()
    for _ in range(120):
        await app_utils.update_app_async(steps=1)
        rgb, rgb_info = sensors[name].get_data('rgb')
        seg, seg_info = sensors[name].get_data('semantic_segmentation')
        if rgb is not None and seg is not None:
            break
    else:
        raise RuntimeError('Camera warm-up timeout: ' + name)
    rgb = rgb.numpy()
    seg = seg.numpy().squeeze()
    labels = seg_info.get('idToLabels', {})
    ids = [int(k) for k, v in labels.items() if 'person_proxy' in str(v)]
    count = int(np.isin(seg, ids).sum())
    path = output / f'{phase}_{name}.png'
    Image.fromarray(rgb).save(path, compress_level=0)
    record = dict(phase=phase, camera=name, person_proxy_pixels=count,
                  shape=list(rgb.shape), mean_rgb=float(rgb.mean()), std_rgb=float(rgb.std()),
                  file=str(path.relative_to(root)), bytes=path.stat().st_size,
                  sim_time_at_read=omni.timeline.get_timeline_interface().get_current_time(),
                  wall_capture_seconds=time.perf_counter()-start,
                  sensor_metadata=rgb_info, segmentation_labels=labels)
    records.append(record)
    assert record['mean_rgb'] > 30 and record['std_rgb'] > 5, record
    assert record['bytes'] >= 150_000, record
    return count

# Same target and two cameras. Fixed-camera entry is the positive control.
person_translate = UsdGeom.Xformable(stage.GetPrimAtPath('/World/PersonProxy')).GetOrderedXformOps()[0]
person_translate.Set(Gf.Vec3d(-2.2, 1.3, .9))
await app_utils.update_app_async(steps=60)
entry = await capture('FixedCamera', 'entry')
person_translate.Set(Gf.Vec3d(0, 1.3, .9))
await app_utils.update_app_async(steps=60)
hidden = await capture('FixedCamera', 'occluded')
front = await capture('MovingCamera', 'before_move')
# Authored camera translation along a clear side path. Not a walking controller.
for step in range(1, 61):
    fraction = step / 60
    aim(stage, '/World/MovingCamera', (3.5*fraction, -5+5*fraction, 1.5), (0, 1.3, .9))
    await app_utils.update_app_async(steps=1)
await app_utils.update_app_async(steps=60)
reacquired = await capture('MovingCamera', 'after_move')
still_hidden = await capture('FixedCamera', 'after_move')
omni.timeline.get_timeline_interface().pause()
stage.Export(str(output / 'scene.usda'))
summary = dict(verification_level='isaac-rendered-primitive-occlusion',
               motion='authored camera transform; no robot locomotion',
               perception='renderer semantic labels; no YOLO/VLM',
               seed=7, records=records,
               passed=entry>100 and hidden==0 and front==0 and reacquired>100 and still_hidden==0)
(output / 'results.json').write_text(json.dumps(summary, indent=2, default=str)+'\n')
print(json.dumps(summary, indent=2, default=str))
assert summary['passed'], 'Occlusion visibility contract failed; inspect captures'
