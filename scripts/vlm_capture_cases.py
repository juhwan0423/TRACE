"""Owned GUI only: reversible session-layer human scenes and real Nav2 captures."""
import importlib, json, time
importlib.invalidate_caches()
from pxr import Usd, UsdGeom
import vlm_people_scene
importlib.reload(vlm_people_scene)
from vlm_people_scene import build_case, ROOT as PEOPLE_ROOT
stage=omni.usd.get_context().get_stage()
if stage.GetRootLayer().identifier != spot_stage_id:
    raise RuntimeError('User changed stage; refusing scene edits')
if inspection.run and inspection.run.status=='moving':
    raise RuntimeError('Navigation is active; refusing scene edits')
if stage.GetPrimAtPath(PEOPLE_ROOT):
    raise RuntimeError('Temporary human root already exists; inspect before replacing')
output=root/'artifacts/vlm'
output.mkdir(parents=True,exist_ok=True)
stage.Export(str(output/f'before_people_{time.time_ns()}.usda'))
proxy=UsdGeom.Imageable(stage.GetPrimAtPath('/World/PersonProxy'))
previous_visibility=proxy.GetVisibilityAttr().Get()
cases=[]
try:
    with Usd.EditContext(stage,stage.GetSessionLayer()):
        proxy.MakeInvisible()
    for case in ('normal_work','lying_on_floor','insufficient_view'):
        if omni.usd.get_context().get_stage() is not stage:
            raise RuntimeError('Stage changed during capture')
        with Usd.EditContext(stage,stage.GetSessionLayer()):
            build_case(stage,case)
        await app_utils.update_app_async(steps=10)
        goal_x.model.set_value(3.); goal_y.model.set_value(1.3); goal_yaw.model.set_value(180.)
        await reset_and_navigate()
        while inspection.run.status=='moving':
            await app_utils.update_app_async(steps=5)
        wall_end=time.monotonic()+30
        while inspection.run.status=='arrived' and not inspection.run.evidence and not inspection.capture_failure and time.monotonic()<wall_end:
            await app_utils.update_app_async(steps=5)
        inspection.save()
        stage.Export(str(output/(case+'.usda')))
        cases.append(dict(scenario=case,nav_result=str(inspection.output/'result.json'),
                          capture_verified=bool(inspection.run.evidence),
                          asset_kind='locally authored stylized human mannequin'))
        (output/'cases.json').write_text(json.dumps(cases,indent=2))
        print(case,inspection.run.status,inspection.output,flush=True)
finally:
    inspection.cancel()
    with Usd.EditContext(stage,stage.GetSessionLayer()):
        stage.RemovePrim(PEOPLE_ROOT)
        proxy.GetVisibilityAttr().Set(previous_visibility)
    (output/'scene_restored.json').write_text(json.dumps(dict(
        human_root_removed=not bool(stage.GetPrimAtPath(PEOPLE_ROOT)),
        proxy_visibility=proxy.GetVisibilityAttr().Get(),
        original_visibility=previous_visibility),indent=2))
