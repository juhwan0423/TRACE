"""Add a presentation-only observer camera to the owned TRACE stage."""
trace_guard()
if 'trace_overview_rgb' not in globals():
    from pxr import UsdGeom
    overview_path = '/World/TraceOverviewCamera'
    if stage.GetPrimAtPath(overview_path):
        raise RuntimeError('Unexpected existing overview camera; refusing replacement')
    overview_cam = UsdGeom.Camera.Define(stage, overview_path)
    overview_cam.CreateFocalLengthAttr(24.)
    overview_cam.CreateHorizontalApertureAttr(36.)
    overview_cam.CreateClippingRangeAttr((.1, 100.))
    aim(stage, overview_path, (7, 6, 6), (0, 0, .5))
    trace_overview_product = rep.create.render_product(overview_path, (1280, 720))
    trace_overview_rgb = rep.AnnotatorRegistry.get_annotator('rgb')
    trace_overview_rgb.attach([trace_overview_product])
    await app_utils.update_app_async(steps=30)
print(json.dumps({'ready': True, 'playing': omni.timeline.get_timeline_interface().is_playing()}))
