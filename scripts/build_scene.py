"""USD scene authoring for the isolated camera experiment (inside Kit only)."""
from pxr import Gf, UsdGeom, UsdLux, UsdPhysics, UsdShade, Sdf, PhysxSchema
from isaacsim.sensors.experimental.rtx import RtxCamera, CameraSensor
from isaacsim.core.experimental.utils import semantics


def material(stage, path, color):
    mat = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, path + '/Shader')
    shader.CreateIdAttr('UsdPreviewSurface')
    shader.CreateInput('diffuseColor', Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
    shader.CreateInput('roughness', Sdf.ValueTypeNames.Float).Set(.7)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), 'surface')
    return mat


def cube(stage, path, pos, size, mat):
    root = UsdGeom.Xform.Define(stage, path)
    root.AddTranslateOp().Set(Gf.Vec3d(*pos))
    mesh = UsdGeom.Cube.Define(stage, path + '/Mesh')
    mesh.CreateSizeAttr(1.)
    mesh.AddScaleOp().Set(Gf.Vec3f(*size))
    UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(mat)
    UsdPhysics.CollisionAPI.Apply(mesh.GetPrim())
    return root


def aim(stage, path, eye, target):
    camera = UsdGeom.Xformable(stage.GetPrimAtPath(path))
    camera.ClearXformOpOrder()
    matrix = Gf.Matrix4d().SetLookAt(Gf.Vec3d(*eye), Gf.Vec3d(*target), Gf.Vec3d(0, 0, 1)).GetInverse()
    camera.AddTransformOp().Set(matrix)


def build(stage, *, physics_hz=60, create_sensors=True):
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.)
    stage.SetTimeCodesPerSecond(physics_hz)
    world = UsdGeom.Xform.Define(stage, '/World')
    stage.SetDefaultPrim(world.GetPrim())
    physics = UsdPhysics.Scene.Define(stage, '/World/PhysicsScene')
    physics.CreateGravityDirectionAttr(Gf.Vec3f(0, 0, -1))
    physics.CreateGravityMagnitudeAttr(9.81)
    px = PhysxSchema.PhysxSceneAPI.Apply(physics.GetPrim())
    px.CreateTimeStepsPerSecondAttr(physics_hz)
    px.CreateSolverTypeAttr('TGS')
    grey = material(stage, '/World/Materials/Floor', (.35, .38, .42))
    blue = material(stage, '/World/Materials/Equipment', (.05, .22, .45))
    pink = material(stage, '/World/Materials/Proxy', (.95, .05, .4))
    cube(stage, '/World/Ground', (0, 0, -.05), (12, 12, .1), grey)
    cube(stage, '/World/Equipment', (0, 0, 1.2), (2.4, 1.2, 2.4), blue)
    person = UsdGeom.Capsule.Define(stage, '/World/PersonProxy')
    person.CreateAxisAttr('Z')
    person.CreateRadiusAttr(.23)
    person.CreateHeightAttr(1.2)
    person.AddTranslateOp().Set(Gf.Vec3d(0, 1.3, .9))
    UsdShade.MaterialBindingAPI.Apply(person.GetPrim()).Bind(pink)
    semantics.add_labels('/World/PersonProxy', labels='person_proxy', taxonomy='class')
    # Static authored proxy, intentionally no body dynamics / detector claim.
    dome = UsdLux.DomeLight.Define(stage, '/World/DomeLight')
    dome.CreateIntensityAttr(1000.)
    sun = UsdLux.DistantLight.Define(stage, '/World/DistantLight')
    sun.CreateIntensityAttr(1000.)
    sun.AddRotateXYZOp().Set(Gf.Vec3f(-35, -25, 0))
    sensors = {}
    if not create_sensors:
        return sensors
    for name in ('FixedCamera', 'MovingCamera'):
        path = '/World/' + name
        cam = RtxCamera(path, tick_rate=30.)
        cam.camera.set_focal_lengths(24.)
        cam.camera.set_apertures(horizontal_apertures=36., vertical_apertures=20.25)
        cam.camera.set_clipping_ranges(.05, 100.)
        aim(stage, path, (0, -5, 1.5), (0, 1.3, .9))
        sensors[name] = CameraSensor(cam, resolution=(720, 1280), annotators=['rgb', 'semantic_segmentation'])
    return sensors
