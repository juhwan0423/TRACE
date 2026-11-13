"""Attach read-only camera feeds to the owned, already-running Real2Sim preview.

Execute in its `real2sim` Python-server context. Does not reset or advance the stage.
"""
import json
import io
import base64
from pathlib import Path
import carb.settings
import omni.usd
import omni.timeline
import omni.replicator.core as rep
from pxr import UsdGeom, Gf
from PIL import Image
from isaacsim.core.simulation_manager import SimulationManager

expected_root = str(Path(real2sim_root).resolve())
if carb.settings.get_settings().get('/real2sim/workspace') != expected_root:
    raise RuntimeError('Not the requested Real2Sim preview session')
monitor_stage = omni.usd.get_context().get_stage()
expected_scene = str(Path(expected_root)/'lab_west/results/human_door/labwest_optb/human_in_scene.usda')
if monitor_stage.GetRootLayer().realPath != expected_scene:
    raise RuntimeError('Real2Sim stage changed; refusing camera attachment')
monitor_stage.SetEditTarget(monitor_stage.GetSessionLayer())

if not globals().get('real2sim_monitor_sensors'):
    real2sim_monitor_sensors = {}
    views = {
        'overview': ((-.3, 3.4, 2.8), (-3.4, -1., 1.), 14., (1280,720)),
        'fixed': ((1.188, .404, 2.5), (-1.512, -1.246, .8), 11., (640,360)),
        'body': ((-2.712, .454, 2.4), (-1.012, -1.546, .8), 8., (640,360)),
    }
    for key, (eye, target, focal, resolution) in views.items():
        camera = UsdGeom.Camera.Define(monitor_stage, '/World/TraceReal2Sim/'+key)
        camera.CreateFocalLengthAttr(focal)
        camera.CreateClippingRangeAttr(Gf.Vec2f(.05,100))
        transform = UsdGeom.Xformable(camera)
        transform.ClearXformOpOrder()
        transform.AddTransformOp().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye),Gf.Vec3d(*target),Gf.Vec3d(0,0,1)).GetInverse())
        product = rep.create.render_product(str(camera.GetPath()), resolution)
        rgb = rep.AnnotatorRegistry.get_annotator('rgb')
        clock = rep.AnnotatorRegistry.get_annotator('IsaacReadSimulationTime')
        rgb.attach([product]); clock.attach([product])
        real2sim_monitor_sensors[key] = (product,rgb,clock)

def real2sim_monitor_frames():
    current = omni.usd.get_context().get_stage()
    if current is not monitor_stage or current.GetRootLayer().realPath != expected_scene:
        raise RuntimeError('Real2Sim stage changed')
    frames = {}
    for key, (_,rgb,clock) in real2sim_monitor_sensors.items():
        data = rgb.get_data()
        stamp = float(clock.get_data().get('simulationTime', -1))
        if not getattr(data,'size',0) or stamp < 0:
            raise RuntimeError('Real2Sim camera warming up: '+key)
        buffer = io.BytesIO()
        Image.fromarray(data[:,:,:3]).save(buffer,format='JPEG',quality=80)
        frames[key] = dict(image=base64.b64encode(buffer.getvalue()).decode(),
                           capture_time=stamp,width=data.shape[1],height=data.shape[0])
    snapshot = real2sim_navigation.snapshot() if globals().get('real2sim_navigation') else dict(
        now=SimulationManager.get_simulation_time(), playing=omni.timeline.get_timeline_interface().is_playing(),
        pose=None, navigation=None, scene='real2sim', spot_attached=False)
    return dict(frames=frames,snapshot=snapshot)


print(json.dumps({'scene':'real2sim','cameras':list(real2sim_monitor_sensors),'spot_attached':bool(globals().get('real2sim_navigation'))}))
