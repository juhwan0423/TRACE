"""Opt-in gate control for a FUTURE comparison cohort; not applied by importing.

Run inside the owned Real2Sim context only after the frozen cohort has ended::

    gate_control = ComparisonGateControl(door, real2sim_navigation)
    gate_control.apply_closed()
    # Let the existing simulation advance; poll verify_closed() until ready.
    # Use an external, finite timeout and retain any failed verification.
    gate_control.verify_closed()
    gate_control.restore()

The existing joint drive closes the gate without teleporting it. Readback MUST
use live physics tensors, never authored USD pose/velocity. Restore resumes the
original schedule at the CURRENT timeline phase; it does not rewind physics.
No stepping, timeline seek, navigation, file save, or automatic retry is done.
Local 6.2 API/source checked; live integration remains unverified.
"""
from pathlib import Path
import math


class ComparisonGateControl:
    def __init__(self, driver, navigation):
        import numpy as np
        import omni.timeline
        import omni.usd
        from isaacsim.core.experimental.prims import RigidPrim
        from isaacsim.core.experimental.utils import backend
        from isaacsim.core.simulation_manager import SimulationManager
        from pxr import Usd, UsdPhysics

        self.np, self.usd, self.backend = np, Usd, backend
        self.context, self.timeline = omni.usd.get_context(), omni.timeline.get_timeline_interface()
        self.clock, self.driver, self.navigation = SimulationManager, driver, navigation
        self.stage = navigation.stage
        self.scene_path = str(Path(navigation.root) / "lab_west/results/human_door/labwest_optb/human_in_scene.usda")
        self.active, self._stable_since, self._last_time, self._samples = False, None, None, 0
        self._guard(idle=True)
        if str(driver.door.GetPath()) != "/World/UAMDoor/Door" or driver.door.GetStage() != self.stage:
            raise RuntimeError("Unexpected door driver")
        joint = UsdPhysics.RevoluteJoint(self.stage.GetPrimAtPath("/World/UAMDoor/Hinge"))
        # This helper deliberately supports only the existing world-fixed hinge.
        if joint.GetBody0Rel().GetTargets() or list(map(str, joint.GetBody1Rel().GetTargets())) != ["/World/UAMDoor/Door"]:
            raise RuntimeError("Unsupported hinge bodies")
        if str(joint.GetAxisAttr().Get()) != "Z" or not np.allclose(joint.GetLocalPos1Attr().Get(), [0, 0, 0]):
            raise RuntimeError("Unsupported hinge frame")
        for attr in (joint.GetLocalRot0Attr(), joint.GetLocalRot1Attr()):
            q = attr.Get()
            if not np.allclose([q.GetReal(), *q.GetImaginary()], [1, 0, 0, 0]):
                raise RuntimeError("Unsupported hinge orientation")
        self.closed_position = np.asarray(joint.GetLocalPos0Attr().Get(), dtype=float)
        # Wrapping may ensure PhysxRigidBodyAPI in the SESSION layer. No source
        # asset or physical properties are intentionally changed by the wrapper.
        with Usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            self.body = RigidPrim("/World/UAMDoor/Door", reset_xform_op_properties=False)
        self._require_tensor()

    def _guard(self, *, idle=False):
        self.navigation.guard()
        if self.context.get_stage() is not self.stage or self.stage.GetRootLayer().realPath != self.scene_path:
            raise RuntimeError("Owned stage changed")
        if not self.timeline.is_playing():
            raise RuntimeError("Gate control requires the existing playing simulation")
        if idle and self.navigation.snapshot()["navigation"]["status"] not in ("idle", "arrived", "cancelled"):
            raise RuntimeError("Gate control requires inspected, stationary navigation")

    def _require_tensor(self):
        if not self.body.is_physics_tensor_entity_valid():
            raise RuntimeError("Live gate physics tensor unavailable; no USD fallback permitted")

    def snapshot(self):
        self._guard()
        self._require_tensor()
        with self.backend.use_backend("tensor", raise_on_unsupported=True, raise_on_fallback=True):
            p, q = self.body.get_world_poses()
            v, w = self.body.get_velocities()
        p, q, v, w = (x.numpy()[0].astype(float) for x in (p, q, v, w))
        if not all(self.np.isfinite(x).all() for x in (p, q, v, w)) or self.np.linalg.norm(q) < 1e-8:
            raise RuntimeError("Invalid gate physics readback")
        q /= self.np.linalg.norm(q)
        angle = math.degrees(2 * math.acos(float(self.np.clip(abs(q[0]), 0, 1))))
        return dict(active=self.active, simulation_time=self.clock.get_simulation_time(),
                    timeline_time=self.timeline.get_current_time(), readback="physics_tensor",
                    position_m=p.tolist(), orientation_wxyz=q.tolist(),
                    linear_velocity_m_s=v.tolist(), angular_velocity_rad_s=w.tolist(),
                    closed_orientation_error_deg=angle,
                    hinge_position_error_m=float(self.np.linalg.norm(p-self.closed_position)),
                    linear_speed_m_s=float(self.np.linalg.norm(v)), angular_speed_rad_s=float(self.np.linalg.norm(w)),
                    target_deg=float(self.driver.target.Get()))

    def apply_closed(self):
        """Between trials: override schedule, then require verified settling.

        The caller must first validate that closing the gate has clear space.
        Physical position/velocity are allowed to converge through the existing
        drive; an unsettled body is never reported ready just from target=0.
        """
        self._guard(idle=True)
        before = self.snapshot()
        owner = getattr(self.driver, "_trace_comparison_gate_owner", None)
        if owner is not None and owner is not self:
            raise RuntimeError("Another comparison controller owns the gate schedule")
        if not self.active:
            self._original_ts = self.driver.ts.copy()
            self._original_ds = self.driver.ds.copy()
            self.driver.ds = self.np.zeros_like(self.driver.ds)
            self.driver._trace_comparison_gate_owner = self
            self.active = True
        elif not self.np.array_equal(self.driver.ds, self.np.zeros_like(self._original_ds)):
            raise RuntimeError("Another caller changed the gate schedule")
        with self.usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            self.driver.update(self.timeline.get_current_time())
        self._stable_since, self._last_time, self._samples = None, None, 0
        return dict(operation="apply_closed", ready=False, before=before, after=self.snapshot())

    def verify_closed(self):
        """Require >=0.5 simulation seconds and >=3 distinct good samples."""
        s = self.snapshot()
        schedule_ok = (self.active and getattr(self.driver, "_trace_comparison_gate_owner", None) is self
                       and self.np.array_equal(self.driver.ts, self._original_ts)
                       and self.np.array_equal(self.driver.ds, self.np.zeros_like(self._original_ds)))
        within = (schedule_ok and abs(s["target_deg"]) <= .01
                  and s["closed_orientation_error_deg"] <= .5
                  and s["hinge_position_error_m"] <= .003
                  and s["linear_speed_m_s"] <= .005 and s["angular_speed_rad_s"] <= .01)
        now = s["simulation_time"]
        if self._last_time is not None and now < self._last_time:
            raise RuntimeError("Simulation clock rewound; reapply and requalify gate control")
        if not within:
            self._stable_since, self._samples = None, 0
        elif self._last_time is None or now > self._last_time:
            self._stable_since = now if self._stable_since is None else self._stable_since
            self._samples += 1
        self._last_time = now
        stable = 0 if self._stable_since is None else now-self._stable_since
        return dict(**s, within_tolerance=bool(within), stable_seconds=stable,
                    distinct_good_samples=self._samples, ready=bool(within and stable >= .5 and self._samples >= 3))

    def restore(self):
        """Resume the saved schedule now; never teleport to a past gate pose."""
        self._guard(idle=True)
        if not self.active:
            return dict(operation="restore", already_restored=True, after=self.snapshot())
        if (getattr(self.driver, "_trace_comparison_gate_owner", None) is not self
                or not self.np.array_equal(self.driver.ts, self._original_ts)
                or not self.np.array_equal(self.driver.ds, self.np.zeros_like(self._original_ds))):
            raise RuntimeError("Another caller changed the gate schedule; refusing to overwrite it")
        self.driver.ds = self._original_ds.copy()
        del self.driver._trace_comparison_gate_owner
        self.active = False
        with self.usd.EditContext(self.stage, self.stage.GetSessionLayer()):
            self.driver.update(self.timeline.get_current_time())
        self._stable_since, self._last_time, self._samples = None, None, 0
        return dict(operation="restore", restored_schedule=True, physical_state_rewound=False, after=self.snapshot())
