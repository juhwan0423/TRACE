"""CPU-only USD verification of reversible worker poses; never starts Isaac.

Run: .venv/bin/python -m unittest discover -s tests -p test_real2sim_worker_scene.py -v
Requires optional numpy/usd-core and the existing local character/motion assets.
Set REAL2SIM_ROOT to their repository (defaults to TRACE's HAI-Real2Sim sibling).
Missing dependencies/assets skip these tests; they are not rendering evidence.
"""
import ast
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

try:
    import numpy as np
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, UsdSkel
except ImportError:
    np = None

TRACE = Path(__file__).resolve().parents[1]
REAL2SIM = Path(os.environ.get('REAL2SIM_ROOT', str(TRACE.parent / 'HAI-Real2Sim'))).resolve()
CHARACTER = REAL2SIM / 'pipeline/assets/human/actorcore_normalwalk/walk_normal_m.usd'
MOTION = REAL2SIM / 'lab_uam/results/human_motion/IMG_4630/retarget_scene.usda'
COLLIDER = REAL2SIM / 'pipeline/tools/sim/human_collider.py'


@unittest.skipIf(np is None, 'Optional numpy/usd-core are unavailable')
@unittest.skipUnless(all(p.is_file() for p in (CHARACTER, MOTION, COLLIDER)),
                     'Local Real2Sim character/motion assets are unavailable')
class WorkerSceneUSDTests(unittest.TestCase):
    def setUp(self):
        stage = self.stage = Usd.Stage.CreateInMemory()
        stage.SetStartTimeCode(0)
        stage.SetEndTimeCode(1384)
        stage.SetTimeCodesPerSecond(30)
        human = UsdGeom.Xform.Define(stage, '/World/Human')
        human.AddTranslateOp().Set(Gf.Vec3d(-1.058, -.447, .034))
        human.AddRotateZOp().Set(132.15317)
        human.AddScaleOp().Set(Gf.Vec3f(.009466894))
        stage.DefinePrim('/World/Human/char').GetReferences().AddReference(str(CHARACTER))
        stage.DefinePrim('/World/HumanMotion').GetReferences().AddReference(
            str(MOTION), '/World/RetargetedAnims/actorcore/Motion')
        for prim in Usd.PrimRange(human.GetPrim()):
            if prim.IsA(UsdSkel.Root) or prim.IsA(UsdSkel.Skeleton):
                UsdSkel.BindingAPI.Apply(prim).CreateAnimationSourceRel().SetTargets(['/World/HumanMotion'])
        stage.SetEditTarget(stage.GetSessionLayer())
        spec = importlib.util.spec_from_file_location('worker_test_human_collider', COLLIDER)
        self.collider_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.collider_module)
        self.collider = self.collider_module.HumanCollider(stage)
        self.context = dict(stage=stage)
        namespace = dict(np=np, Gf=Gf, Sdf=Sdf, Usd=Usd, UsdGeom=UsdGeom,
                         UsdPhysics=UsdPhysics, UsdSkel=UsdSkel, Path=Path,
                         omni=SimpleNamespace(
                             usd=SimpleNamespace(get_context=lambda: SimpleNamespace(
                                 get_stage=lambda: self.context['stage'])),
                             timeline=SimpleNamespace(get_timeline_interface=lambda: SimpleNamespace(
                                 get_current_time=lambda: 0.0))))
        # Extract the actual class without executing the live-context bootstrap.
        path = TRACE / 'scripts/real2sim_worker_scene.py'
        definition = next(n for n in ast.parse(path.read_text()).body
                          if isinstance(n, ast.ClassDef) and n.name == 'WorkerScenario')
        exec(compile(ast.Module(body=[definition], type_ignores=[]), str(path), 'exec'), namespace)
        self.worker = worker = namespace['WorkerScenario'].__new__(namespace['WorkerScenario'])
        # Anonymous test stages have no scene filepath. Supply the corresponding
        # baseline metadata; all guard, pose and restore methods remain unchanged.
        worker.stage, worker.collider = stage, self.collider
        worker.navigation = SimpleNamespace(command=dict(status='idle'))
        worker.expected_scene = stage.GetRootLayer().realPath
        worker.layer, worker.applied, worker.cache = None, None, {}
        worker.ends = [(a.copy(), b.copy()) for a, b in self.collider.ends]
        worker.collisions = [bool(UsdPhysics.CollisionAPI(cap.GetPrim()).GetCollisionEnabledAttr().Get())
                             for cap, _, _ in self.collider.caps]
        self.root_before = stage.GetRootLayer().ExportToString()
        self.session_before = stage.GetSessionLayer().ExportToString()

    def composed_geometry(self, timecode):
        """Independently evaluate USD's composed skinned mesh and joint transforms."""
        prims = list(Usd.PrimRange(self.stage.GetPrimAtPath('/World/Human')))
        root = UsdSkel.Root(next(p for p in prims if p.IsA(UsdSkel.Root)))
        cache = UsdSkel.Cache()
        cache.Populate(root, Usd.TraverseInstanceProxies())
        tc, points = Usd.TimeCode(timecode), []
        xforms = UsdGeom.XformCache(tc)
        for binding in cache.ComputeSkelBindings(root, Usd.TraverseInstanceProxies()):
            query = cache.GetSkelQuery(binding.GetSkeleton())
            skinning = query.ComputeSkinningTransforms(tc)
            world = np.asarray(xforms.GetLocalToWorldTransform(binding.GetSkeleton().GetPrim()))
            for target in binding.GetSkinningTargets():
                if not target.GetPrim().IsA(UsdGeom.Mesh):
                    continue
                pts = UsdGeom.Mesh(target.GetPrim()).GetPointsAttr().Get(tc)
                if pts and target.ComputeSkinnedPoints(skinning, pts, tc):
                    points.append(np.asarray(pts) @ world[:3, :3] + world[3, :3])
        skeleton = UsdSkel.Skeleton(next(p for p in prims if p.IsA(UsdSkel.Skeleton)))
        query = cache.GetSkelQuery(skeleton)
        names = [str(j).split('/')[-1] for j in query.GetJointOrder()]
        joints = dict(zip(names, [np.array(m.ExtractTranslation())
                                 for m in query.ComputeJointWorldTransforms(xforms)]))
        return np.concatenate(points), joints

    def test_actual_skin_grounding_colliders_and_exact_restore(self):
        motion = self.stage.GetPrimAtPath('/World/HumanMotion')
        original_samples = {n: motion.GetAttribute(n).GetTimeSamples()
                            for n in ('translations', 'rotations', 'scales')}
        self.assertTrue(all(len(v) > 1 for v in original_samples.values()))
        for frame, rotation in ((0, [0, 90, 0]), (20, [90, 0, 45]), (0, [0, 0, 0])):
            with self.subTest(frame=frame, rotation=rotation):
                state = self.worker.apply([-4.3, -.9, .03], rotation, frame)
                self.assertTrue(state['collision_state_preserved'])
                points, joints = self.composed_geometry(900)
                bounds = np.array([points.min(0), points.max(0)])
                np.testing.assert_allclose(bounds, state['pose']['bounds'], atol=1e-5)
                np.testing.assert_allclose((bounds[0, :2] + bounds[1, :2]) / 2, [-4.3, -.9])
                self.assertAlmostEqual(bounds[0, 2], .03)
                for name in original_samples:
                    self.assertEqual(motion.GetAttribute(name).GetTimeSamples(), [])
                for (a, b), (joint_a, joint_b, _) in zip(self.collider.ends, self.collider_module.SEGMENTS):
                    np.testing.assert_allclose(a, np.repeat(a[:1], len(a), axis=0))
                    np.testing.assert_allclose(b, np.repeat(b[:1], len(b), axis=0))
                    np.testing.assert_allclose(a[0], joints[joint_a], atol=1e-5)
                    if not joint_b.endswith('+up'):
                        np.testing.assert_allclose(b[0], joints[joint_b], atol=1e-5)
                self.assertEqual(self.stage.GetRootLayer().ExportToString(), self.root_before)
        self.worker.restore()
        for name, samples in original_samples.items():
            self.assertEqual(motion.GetAttribute(name).GetTimeSamples(), samples)
        for (a, b), (original_a, original_b) in zip(self.collider.ends, self.worker.ends):
            np.testing.assert_array_equal(a, original_a)
            np.testing.assert_array_equal(b, original_b)
        self.assertEqual(self.stage.GetSessionLayer().ExportToString(), self.session_before)
        self.assertEqual(self.stage.GetRootLayer().ExportToString(), self.root_before)

    def test_state_during_motion_allowed_but_pose_changes_refused(self):
        self.worker.apply([-4.3, -.9, .03], [0, 90, 0])
        active_session = self.stage.GetSessionLayer().ExportToString()
        self.worker.navigation.command['status'] = 'moving'
        self.assertTrue(self.worker.state()['active'])
        with self.assertRaisesRegex(RuntimeError, 'Stop the active Spot goal'):
            self.worker.apply([-4.3, -.9, .03])
        with self.assertRaisesRegex(RuntimeError, 'Stop the active Spot goal'):
            self.worker.restore()
        self.assertEqual(self.stage.GetSessionLayer().ExportToString(), active_session)
        self.worker.navigation.command['status'] = 'idle'
        self.worker.restore()
        self.context['stage'] = Usd.Stage.CreateInMemory()
        with self.assertRaisesRegex(RuntimeError, 'stage changed'):
            self.worker.state()

    def test_restore_collision_state_preserves_root_with_different_edit_target(self):
        self.worker.apply([-4.3, -.9, .03], [0, 90, 0])
        attr = UsdPhysics.CollisionAPI(self.collider.caps[0][0].GetPrim()).GetCollisionEnabledAttr()
        attr.Set(False)
        self.stage.SetEditTarget(self.stage.GetRootLayer())
        self.worker.restore()
        self.assertTrue(attr.Get())
        self.assertEqual(self.stage.GetRootLayer().ExportToString(), self.root_before)


if __name__ == '__main__':
    unittest.main()
