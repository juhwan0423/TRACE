"""Contact scene and body camera authoring; no robot control."""
from pxr import Usd, UsdPhysics, UsdShade, UsdGeom, Gf
from build_scene import build


def build_environment(stage, occlusion=False):
    build(stage, physics_hz=500, create_sensors=False)
    if not occlusion:
        stage.RemovePrim('/World/Equipment')
        stage.RemovePrim('/World/PersonProxy')
    # Same contact coefficients as the official LocomotionPolicySample.
    mat = UsdShade.Material.Define(stage, '/World/GroundMaterial')
    physics = UsdPhysics.MaterialAPI.Apply(mat.GetPrim())
    physics.CreateStaticFrictionAttr(1.)
    physics.CreateDynamicFrictionAttr(1.)
    physics.CreateRestitutionAttr(0.)
    UsdShade.MaterialBindingAPI.Apply(stage.GetPrimAtPath('/World/Ground/Mesh')).Bind(mat, materialPurpose='physics')


def attach_body_camera(stage, robot_path):
    from isaacsim.sensors.experimental.rtx import RtxCamera, CameraSensor
    bodies = [p for p in Usd.PrimRange(stage.GetPrimAtPath(robot_path)) if p.HasAPI(UsdPhysics.RigidBodyAPI)]
    matches = [p for p in bodies if p.GetName() == 'body']
    if len(matches) != 1:
        raise RuntimeError('Expected exactly one Spot rigid body named body; found ' + str([str(p.GetPath()) for p in bodies]))
    body = str(matches[0].GetPath())
    path = body + '/HAIFrontCamera'
    cam = RtxCamera(path, tick_rate=30.)
    cam.camera.set_focal_lengths(24.)
    cam.camera.set_apertures(horizontal_apertures=36., vertical_apertures=20.25)
    cam.camera.set_clipping_ranges(.05, 100.)
    xf = UsdGeom.Xformable(stage.GetPrimAtPath(path))
    xf.ClearXformOpOrder()
    xf.AddTransformOp().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(.45, 0, .12), Gf.Vec3d(1.45, 0, .12), Gf.Vec3d(0, 0, 1)).GetInverse())
    return body, CameraSensor(cam, resolution=(360, 640), annotators=['rgb'])
