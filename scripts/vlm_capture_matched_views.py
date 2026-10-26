"""One actual Nav2 arrival, then three fresh matched-view evaluation frames."""
import importlib, json, time, uuid, math
importlib.invalidate_caches()
import vlm_people_scene
importlib.reload(vlm_people_scene)
from pxr import Usd, UsdGeom
from PIL import Image
from isaacsim.core.simulation_manager import SimulationManager
stage=omni.usd.get_context().get_stage()
if stage.GetRootLayer().identifier != spot_stage_id or stage.GetPrimAtPath(vlm_people_scene.ROOT):
    raise RuntimeError('Unexpected stage or existing temporary human root')
if inspection.run and inspection.run.status=='moving':
    raise RuntimeError('Existing navigation active')
output=root/'artifacts/vlm'
stage.Export(str(output/f'before_matched_views_{time.time_ns()}.usda'))
goal_x.model.set_value(3.); goal_y.model.set_value(1.3); goal_yaw.model.set_value(180.)
await reset_and_navigate()
while inspection.run.status=='moving':
    await app_utils.update_app_async(steps=5)
if inspection.run.status!='arrived':
    raise RuntimeError('Actual Nav2 arrival failed: '+str(inspection.run.reason))
# Use one actual movement request as the common capture position for all variants.
inspection.save()
nav=json.loads((inspection.output/'result.json').read_text())
proxy=UsdGeom.Imageable(stage.GetPrimAtPath('/World/PersonProxy'))
previous=proxy.GetVisibilityAttr().Get()
cases=[]
try:
    with Usd.EditContext(stage,stage.GetSessionLayer()): proxy.MakeInvisible()
    for scenario in ('normal_work','lying_on_floor','insufficient_view'):
        authored_at=SimulationManager.get_simulation_time()
        with Usd.EditContext(stage,stage.GetSessionLayer()):
            vlm_people_scene.build_case(stage,scenario)
        await app_utils.update_app_async(steps=10)
        stamp=float(inspection.clock.get_data().get('simulationTime',-1))
        data,_=demo.camera.get_data('rgb')
        if data is None or stamp<=max(authored_at,nav['arrived_at']):
            raise RuntimeError('No fresh rendered frame after scene change')
        p,_,_,_,yaw,_=demo.state()
        xy_error=math.dist(p[:2],(3.,1.3))
        yaw_error=abs(math.atan2(math.sin(yaw-math.pi),math.cos(yaw-math.pi)))
        if xy_error>.25 or yaw_error>.15:
            raise RuntimeError('Camera platform drifted outside arrival tolerance')
        folder=output/'captures'/str(uuid.uuid4())
        folder.mkdir(parents=True)
        image_path=folder/'rgb.png'
        Image.fromarray(data.numpy()).save(image_path)
        record=dict(nav)
        record['evidence']=dict(goal_id=nav['goal_id'],sequence=int(stamp*1e9),capture_time=stamp,
                                received_time=SimulationManager.get_simulation_time(),artifact=str(image_path))
        record['capture_validation']=dict(authored_at=authored_at,xy_error=xy_error,yaw_error=yaw_error,
                                          common_actual_arrival=True)
        (folder/'result.json').write_text(json.dumps(record,indent=2))
        stage.Export(str(output/(scenario+'.usda')))
        cases.append(dict(scenario=scenario,nav_result=str(folder/'result.json'),capture_verified=True,
                          asset_kind='locally authored stylized human mannequin'))
        (output/'cases.json').write_text(json.dumps(cases,indent=2))
        print(scenario,folder,stamp,flush=True)
finally:
    with Usd.EditContext(stage,stage.GetSessionLayer()):
        stage.RemovePrim(vlm_people_scene.ROOT)
        proxy.GetVisibilityAttr().Set(previous)
    (output/'scene_restored.json').write_text(json.dumps(dict(human_root_removed=not bool(stage.GetPrimAtPath(vlm_people_scene.ROOT)),
        proxy_visibility=proxy.GetVisibilityAttr().Get(),original_visibility=previous),indent=2))
