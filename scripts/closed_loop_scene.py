"""Install live camera helpers into the owned Spot context; scenario truth stays here."""
import json
import time
import uuid
from pathlib import Path
from PIL import Image
from pxr import UsdGeom, Gf
import omni.replicator.core as rep
from isaacsim.core.simulation_manager import SimulationManager
from isaacsim.sensors.experimental.rtx import RtxCamera, CameraSensor
from build_scene import aim
from vlm_people_scene import build_case, ROOT as PEOPLE_ROOT

stage = omni.usd.get_context().get_stage()
if stage.GetRootLayer().identifier != spot_stage_id:
    raise RuntimeError('Stage changed; refusing edits')
if inspection.run and inspection.run.status == 'moving':
    raise RuntimeError('Navigation active; wait or cancel first')
if 'trace_camera' in globals():
    raise RuntimeError('Closed-loop sensors already installed; reuse existing helpers')
trace_output = root / 'artifacts/closed_loop'
trace_output.mkdir(parents=True, exist_ok=True)
stage.Export(str(trace_output / f'before_{time.time_ns()}.usda'))
UsdGeom.Imageable(stage.GetPrimAtPath('/World/PersonProxy')).MakeInvisible()
camera = RtxCamera('/World/TraceFixedCamera', tick_rate=30.)
camera.camera.set_focal_lengths(24.)
camera.camera.set_apertures(horizontal_apertures=36., vertical_apertures=20.25)
camera.camera.set_clipping_ranges(.05, 100.)
aim(stage, '/World/TraceFixedCamera', (0, -5, 2), (0, 1.3, 1.))
trace_camera = CameraSensor(camera, resolution=(720, 1280), annotators=['rgb'])
trace_clock = rep.AnnotatorRegistry.get_annotator('IsaacReadSimulationTime')
trace_clock.attach([str(trace_camera.render_product.GetPath())])


def trace_guard():
    current = omni.usd.get_context().get_stage()
    if current is not stage or current.GetRootLayer().identifier != spot_stage_id:
        raise RuntimeError('Active stage changed')
    if demo.failure or ros_bridge.failure:
        raise RuntimeError(str(demo.failure or ros_bridge.failure))


async def trace_present():
    trace_guard()
    inspection.cancel()
    app_utils.stop()
    build_case(stage, 'normal_work')
    human = UsdGeom.Xformable(stage.GetPrimAtPath(PEOPLE_ROOT + '/Human'))
    human.GetOrderedXformOps()[0].Set(Gf.Vec3d(0, -1.5, 0))
    human.AddRotateXOp().Set(0.)
    # All topology/collision authoring precedes physics reset and policy binding.
    await replay('hold')
    while demo.elapsed < 3.:
        await app_utils.update_app_async(steps=5)
    await app_utils.update_app_async(steps=30)


async def trace_occlude(case):
    trace_guard()
    if case not in ('normal_work', 'lying_on_floor', 'insufficient_view'):
        raise ValueError('unknown scenario')
    human = UsdGeom.Xformable(stage.GetPrimAtPath(PEOPLE_ROOT + '/Human'))
    ops = human.GetOrderedXformOps()
    ops[0].Set(Gf.Vec3d(0, 2.55, .17) if case == 'lying_on_floor' else Gf.Vec3d(0, 1.7, 0))
    ops[1].Set(90. if case == 'lying_on_floor' else 0.)
    if case == 'insufficient_view':
        # Put the mannequin behind the existing opaque equipment for both cameras.
        ops[0].Set(Gf.Vec3d(0, 0, 0))
    await app_utils.update_app_async(steps=30)


async def trace_capture(after=-1.):
    trace_guard()
    end = time.monotonic() + 30.
    while time.monotonic() < end:
        stamp = float(trace_clock.get_data().get('simulationTime', -1))
        if stamp > after:
            data, _ = trace_camera.get_data('rgb')
            if data is not None:
                image = data.numpy()
                if image.size and image[:, :, :3].mean() > 20:
                    path = trace_output / (str(uuid.uuid4()) + '.png')
                    Image.fromarray(image).save(path)
                    return dict(artifact=str(path), capture_time=stamp,
                                received_time=SimulationManager.get_simulation_time())
        await app_utils.update_app_async(steps=5)
    raise RuntimeError('No fresh nonblack fixed-camera frame')


def trace_snapshot():
    trace_guard()
    return dict(now=SimulationManager.get_simulation_time(),
                playing=omni.timeline.get_timeline_interface().is_playing(),
                navigation=vars(inspection.run) if inspection.run else None,
                capture_failure=inspection.capture_failure,
                nav_ready=inspection.client.server_is_ready(),
                pose=demo.state()[0].tolist())


print('TRACE camera helpers ready')
