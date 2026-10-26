"""Locally authored, stylized human mannequin; no downloaded assets or truth API."""
from pxr import Gf, UsdGeom, UsdShade
from build_scene import material, cube
ROOT='/World/HAIVLM'


def sphere(stage, path, point, radius, mat):
    prim=UsdGeom.Sphere.Define(stage,path)
    prim.CreateRadiusAttr(radius)
    prim.AddTranslateOp().Set(Gf.Vec3d(*point))
    UsdShade.MaterialBindingAPI.Apply(prim.GetPrim()).Bind(mat)


def limb(stage,path,start,end,radius,mat):
    a,b=Gf.Vec3d(*start),Gf.Vec3d(*end)
    direction=b-a
    prim=UsdGeom.Capsule.Define(stage,path)
    prim.CreateAxisAttr('Z'); prim.CreateRadiusAttr(radius)
    prim.CreateHeightAttr(max(.01,direction.GetLength()-2*radius))
    prim.AddTranslateOp().Set((a+b)/2)
    prim.AddOrientOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Rotation(Gf.Vec3d(0,0,1),direction.GetNormalized()).GetQuat())
    UsdShade.MaterialBindingAPI.Apply(prim.GetPrim()).Bind(mat)


def build_case(stage, case):
    if case not in ('normal_work','lying_on_floor','insufficient_view'):
        raise ValueError('unknown evaluation case')
    stage.RemovePrim(ROOT)
    UsdGeom.Xform.Define(stage,ROOT)
    skin=material(stage,ROOT+'/Skin',(.63,.39,.24))
    shirt=material(stage,ROOT+'/Shirt',(.85,.34,.03))
    trousers=material(stage,ROOT+'/Trousers',(.035,.06,.11))
    dark=material(stage,ROOT+'/Dark',(.015,.015,.02))
    yellow=material(stage,ROOT+'/Helmet',(.95,.77,.06))
    bench=material(stage,ROOT+'/BenchMaterial',(.32,.33,.35))
    human=UsdGeom.Xform.Define(stage,ROOT+'/Human')
    human.AddTranslateOp().Set(Gf.Vec3d(0,2.55,.17) if case=='lying_on_floor' else Gf.Vec3d(0,1.7,0))
    if case=='lying_on_floor': human.AddRotateXOp().Set(90.)
    base=ROOT+'/Human'
    # Geometry has no human dynamics/medical ground truth; it is a posed mannequin.
    for side,x in [('L',-.10),('R',.10)]:
        limb(stage,base+'/'+side+'Thigh',(x,0,.86),(x,0,.49),.085,trousers)
        limb(stage,base+'/'+side+'Shin',(x,0,.49),(x,.01,.12),.065,trousers)
        sphere(stage,base+'/'+side+'Knee',(x,0,.49),.078,trousers)
        foot=UsdGeom.Sphere.Define(stage,base+'/'+side+'Boot')
        foot.CreateRadiusAttr(1.)
        foot.AddTranslateOp().Set(Gf.Vec3d(x,.06,.08)); foot.AddScaleOp().Set(Gf.Vec3f(.09,.16,.07))
        UsdShade.MaterialBindingAPI.Apply(foot.GetPrim()).Bind(dark)
    limb(stage,base+'/Torso',(0,0,.90),(0,0,1.40),.20,shirt)
    limb(stage,base+'/Neck',(0,0,1.40),(0,0,1.53),.07,skin)
    sphere(stage,base+'/Head',(0,0,1.61),.13,skin)
    sphere(stage,base+'/Helmet',(0,-.015,1.72),.145,yellow)
    for x in (-.045,.045): sphere(stage,base+('/EyeL' if x<0 else '/EyeR'),(x,.119,1.63),.015,dark)
    for side,sign in [('L',-1),('R',1)]:
        shoulder=(sign*.22,0,1.37)
        elbow=(sign*.27,0,1.10) if case=='lying_on_floor' else (sign*.26,.23,1.18)
        hand=(sign*.27,0,.86) if case=='lying_on_floor' else (sign*.17,.43,1.00)
        limb(stage,base+'/'+side+'UpperArm',shoulder,elbow,.065,shirt)
        limb(stage,base+'/'+side+'Forearm',elbow,hand,.05,skin)
        sphere(stage,base+'/'+side+'Hand',hand,.06,skin)
    # Workbench pose provides context only; a still image cannot prove work/activity.
    cube(stage,ROOT+'/BenchTop',(0,2.35,.95),(.85,.50,.08),bench)
    for x in (-.33,.33):
        for y in (2.18,2.52): cube(stage,ROOT+f'/Leg{int((x+1)*100)}_{int(y*100)}',(x,y,.46),(.06,.06,.92),bench)
    if case=='insufficient_view':
        cube(stage,ROOT+'/Screen',(1.25,1.7,.95),(.08,1.6,1.9),bench)
