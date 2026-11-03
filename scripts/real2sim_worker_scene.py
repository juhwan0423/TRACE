"""Reversible, authored static worker poses in the existing Real2Sim session.

Execute in the owned ``real2sim`` Python-server context. This does not reset the
stage or simulate a physical fall. ``apply(position, rotation, frame=0)`` anchors
the rotated skinned mesh's XY bounding-box centre and lowest Z to ``position``.
``rotation`` is an XYZ Euler world-axis delta, in degrees, from the authored pose.
"""
import json
from pathlib import Path

import carb.settings
import numpy as np
import omni.timeline
import omni.usd
from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics, UsdSkel


class WorkerScenario:
    def __init__(self, stage, collider, navigation=None):
        self.stage, self.collider, self.navigation = stage, collider, navigation
        owner = carb.settings.get_settings().get('/real2sim/workspace')
        if not owner:
            raise RuntimeError('No owned Real2Sim workspace')
        self.expected_scene = str(Path(owner).resolve() /
                                  'lab_west/results/human_door/labwest_optb/human_in_scene.usda')
        self.layer = None
        self.applied = None
        self.cache = {}
        self.ends = [(a.copy(), b.copy()) for a, b in collider.ends]
        self.collisions = [bool(UsdPhysics.CollisionAPI(cap.GetPrim()).GetCollisionEnabledAttr().Get())
                           for cap, _, _ in collider.caps]
        self.guard()

    def guard(self, stationary=False):
        if omni.usd.get_context().get_stage() is not self.stage:
            raise RuntimeError('Real2Sim stage changed')
        if self.stage.GetRootLayer().realPath != self.expected_scene:
            raise RuntimeError('Unexpected Real2Sim root layer')
        if stationary and self.navigation and self.navigation.command.get('status') == 'moving':
            raise RuntimeError('Stop the active Spot goal before changing the worker')

    def _source_pose(self, frame):
        if frame in self.cache:
            return self.cache[frame]
        # Only mute this controller's layer, synchronously, to read original data.
        if self.layer:
            self.stage.MuteLayer(self.layer.identifier)
        try:
            human = self.stage.GetPrimAtPath('/World/Human')
            tc = Usd.TimeCode(frame)
            xfc = UsdGeom.XformCache(tc)
            prims = list(Usd.PrimRange(human, Usd.TraverseInstanceProxies()))
            skelroot = UsdSkel.Root(next(p for p in prims if p.IsA(UsdSkel.Root)))
            cache = UsdSkel.Cache()
            cache.Populate(skelroot, Usd.TraverseInstanceProxies())
            points = []
            for binding in cache.ComputeSkelBindings(skelroot, Usd.TraverseInstanceProxies()):
                query = cache.GetSkelQuery(binding.GetSkeleton())
                transforms = query.ComputeSkinningTransforms(tc)
                world = np.asarray(xfc.GetLocalToWorldTransform(binding.GetSkeleton().GetPrim()))
                for target in binding.GetSkinningTargets():
                    if not target.GetPrim().IsA(UsdGeom.Mesh):
                        continue
                    pts = UsdGeom.Mesh(target.GetPrim()).GetPointsAttr().Get(tc)
                    if pts and target.ComputeSkinnedPoints(transforms, pts, tc):
                        points.append(np.asarray(pts, dtype=float) @ world[:3, :3] + world[3, :3])
            if not points:
                raise RuntimeError('No skinned worker geometry available for grounding')
            motion = UsdSkel.Animation(self.stage.GetPrimAtPath('/World/HumanMotion'))
            values = {name: motion.GetPrim().GetAttribute(name).Get(tc)
                      for name in ('translations', 'rotations', 'scales')}
            if any(value is None for value in values.values()):
                raise RuntimeError('Worker animation is missing pose channels')
            data = (np.concatenate(points), values, xfc.GetLocalToWorldTransform(human),
                    xfc.GetLocalToWorldTransform(human.GetParent()))
            self.cache[frame] = data
            return data
        finally:
            if self.layer:
                self.stage.UnmuteLayer(self.layer.identifier)

    def apply(self, position, rotation=(0, 0, 0), frame=0):
        self.guard(stationary=True)
        position, rotation = np.asarray(position, float), np.asarray(rotation, float)
        if position.shape != (3,) or rotation.shape != (3,) or not np.isfinite([*position, *rotation, frame]).all():
            raise ValueError('Finite XYZ position, XYZ rotation and frame are required')
        if not self.stage.GetStartTimeCode() <= frame <= self.stage.GetEndTimeCode():
            raise ValueError('Frame lies outside the original animation')
        points, values, original_world, parent_world = self._source_pose(float(frame))
        # A temporary in-memory USD Xform supplies USD's documented XYZ ordering.
        scratch = Usd.Stage.CreateInMemory()
        rotation_op = UsdGeom.Xform.Define(scratch, '/Rotation').AddRotateXYZOp()
        rotation_op.Set(Gf.Vec3f(*rotation))
        rotate = rotation_op.GetOpTransform(Usd.TimeCode.Default())
        matrix = np.asarray(rotate)
        rotated = points @ matrix[:3, :3]
        low, high = rotated.min(axis=0), rotated.max(axis=0)
        anchor = np.array([(low[0] + high[0]) / 2, (low[1] + high[1]) / 2, low[2]])
        delta = rotate * Gf.Matrix4d().SetTranslate(Gf.Vec3d(*(position - anchor)))
        local = original_world * delta * parent_world.GetInverse()
        if self.layer is None:
            self.layer = Sdf.Layer.CreateAnonymous('trace-worker-scenario.usda')
            self.stage.GetSessionLayer().subLayerPaths.insert(0, self.layer.identifier)
        with Usd.EditContext(self.stage, self.layer):
            human = UsdGeom.Xformable(self.stage.GetPrimAtPath('/World/Human'))
            attr = human.GetPrim().GetAttribute('xformOp:transform:traceWorkerScenario')
            op = UsdGeom.XformOp(attr) if attr else human.AddTransformOp(opSuffix='traceWorkerScenario')
            op.Set(local)
            human.SetXformOpOrder([op])
            motion = self.stage.GetPrimAtPath('/World/HumanMotion')
            for name, value in values.items():
                motion.GetAttribute(name).Set(value)
        if not np.allclose(np.asarray(human.GetLocalTransformation()), np.asarray(local)):
            self.restore()
            raise RuntimeError('Stronger human transform opinion prevents scenario; restored')
        if any(motion.GetAttribute(name).GetTimeSamples() for name in values):
            self.restore()
            raise RuntimeError('Stronger animation opinion prevents static pose; restored')
        # The existing collider precomputes world endpoints. Freeze and transform
        # them too, preserving enabled collision state and every existing capsule.
        time_s = float(frame) / self.stage.GetTimeCodesPerSecond()
        md = np.asarray(delta)
        transformed = []
        for endpoints in self.ends:
            pair = []
            for array in endpoints:
                point = np.array([np.interp(time_s, self.collider.t, array[:, axis]) for axis in range(3)])
                point = point @ md[:3, :3] + md[3, :3]
                pair.append(np.repeat(point[None, :], len(array), axis=0))
            transformed.append(tuple(pair))
        self.collider.ends = transformed
        with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            self.collider.update(omni.timeline.get_timeline_interface().get_current_time())
        self.applied = dict(position=position.tolist(), rotation=rotation.tolist(), frame=float(frame),
                            anchor='skinned_bbox_xy_center_and_min_z',
                            bounds=[(low + position - anchor).tolist(), (high + position - anchor).tolist()])
        return self.state()

    def restore(self):
        self.guard(stationary=True)
        if self.layer:
            identifier = self.layer.identifier
            session = self.stage.GetSessionLayer()
            session.subLayerPaths = [p for p in session.subLayerPaths if p != identifier]
            self.layer = None
        self.collider.ends = [(a.copy(), b.copy()) for a, b in self.ends]
        with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            for (cap, _, _), was_enabled in zip(self.collider.caps, self.collisions):
                attr = UsdPhysics.CollisionAPI(cap.GetPrim()).GetCollisionEnabledAttr()
                if bool(attr.Get()) != was_enabled:
                    attr.Set(was_enabled)
            self.collider.update(omni.timeline.get_timeline_interface().get_current_time())
        self.applied = None
        return self.state()

    def state(self):
        self.guard()
        enabled = [bool(UsdPhysics.CollisionAPI(cap.GetPrim()).GetCollisionEnabledAttr().Get())
                   for cap, _, _ in self.collider.caps]
        return dict(active=self.layer is not None, layer=self.layer.identifier if self.layer else None,
                    pose=self.applied, collision_state_preserved=enabled == self.collisions,
                    verification='authored static skinned pose; not physical fall dynamics')


if not globals().get('real2sim_worker_scenario'):
    real2sim_worker_scenario = WorkerScenario(omni.usd.get_context().get_stage(), human_collider,
                                            globals().get('real2sim_navigation'))
else:
    if type(real2sim_worker_scenario).__name__ != 'WorkerScenario':
        raise RuntimeError('Unexpected existing worker scenario controller')
    # Remote scripts re-execute on each command. Retain the original backup and
    # anonymous layer while allowing fixes to the methods to take effect.
    real2sim_worker_scenario.__class__ = WorkerScenario
print(json.dumps(real2sim_worker_scenario.state()))
