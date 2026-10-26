"""Official Spot sample lifecycle with task commands and telemetry only."""
import json
import math
import time
from pathlib import Path
import numpy as np
import omni.usd
import omni.timeline
from isaacsim.core.simulation_manager import SimulationManager
from isaacsim.core.rendering_manager import ViewportManager
from isaacsim.robot.policy.examples import get_spot_spec, RobotPolicyRunner
from isaacsim.robot.policy.examples.interactive.quadruped.quadruped_example import QuadrupedExample
from isaacsim.robot.policy.examples.interactive.utils import snapshot_physics_simulation_state
from haiclaw.navigation import VelocityLease
from haiclaw.spot_commands import validation_command, WaypointFollower
from spot_scene import build_environment, attach_body_camera


class SpotDemo(QuadrupedExample):
    _spawn_position = (0., -3., .8)

    def __init__(self, workspace, occlusion=False):
        super().__init__()
        self.root = Path(workspace)
        self.config = json.loads((self.root/'configs/spot_acceptance.json').read_text())
        self.occlusion = occlusion
        self.mode = 'hold'
        self.velocity_lease = VelocityLease()
        self.elapsed = 0.
        self.records = []
        self.failure = None
        self.camera = None
        self.phase = 'hold'
        self.ticks = 0
        self.ready_count = 0
        self.run_id = str(time.time_ns())
        self.output = self.root/'artifacts/spot'/self.run_id
        self.output.mkdir(parents=True)

    def setup_scene(self):
        self._prev_physics_sim_device, self._prev_fabric_enabled = snapshot_physics_simulation_state()
        SimulationManager.set_backend('torch')
        SimulationManager.set_physics_sim_device('cuda')
        stage = omni.usd.get_context().get_stage()
        build_environment(stage, self.occlusion)
        self.spec = get_spot_spec()
        self._runner = RobotPolicyRunner(self.spec, prim_path=self._prim_path,
                                        position=self._spawn_position, training_engine='physx')
        self._runner.spawn()
        if abs(self._runner.physics_dt-self._physics_dt)>1e-9:
            raise RuntimeError('Export physics dt differs from official QuadrupedExample')
        self._world_settings['physics_dt'] = self._runner.physics_dt
        self._world_settings['rendering_dt'] = self._runner.physics_dt*self._runner.env_config.timing.render_interval
        self.body_path, self.camera = attach_body_camera(stage, self._prim_path)
        artifact = self.spec.engines['physx']
        self.manifest = dict(engine=self._runner.engine, usd=self.spec.usd_path,
                             model=artifact.model_path, env=artifact.env_config_path,
                             descriptor=artifact.descriptor_path, expected_sha256=artifact.model_sha256,
                             physics_dt=self._runner.physics_dt, decimation=self._runner.decimation,
                             rendering_dt=self._world_settings['rendering_dt'], body=self.body_path,
                             occlusion=self.occlusion, acceptance=self.config)
        self.save()

    async def setup_post_load(self):
        # Reuse official idempotent registration; no duplicate keyboard bindings.
        self._base_command.fill(0.)
        self._register_physics_callback()
        ViewportManager.set_camera_view(eye=[4, -7, 3], target=[0, -3, .6], camera='/OmniverseKit_Persp')

    def _on_timeline_stop(self, event):
        super()._on_timeline_stop(event)
        self._base_command.fill(0.)
        self.mode = 'hold'
        self.elapsed = 0.
        self.velocity_lease.reset()

    def start(self, mode='validation'):
        # Re-arm controller/actuator history after a long zero-command hold.
        # Public initialize() retains the measured pose; reset() would teleport.
        if mode in ('nav2', 'waypoints', 'validation') and self._physics_ready:
            self._runner.initialize()
        self.records = []
        self.elapsed = 0.
        self.ticks = 0
        self.failure = None
        self.mode = mode
        if mode == 'waypoints':
            self.follower = WaypointFollower([(3., -3.), (3., 1.)],
                                             self.config['waypoint_tolerance_m'], self.config['waypoint_timeout_seconds'])

    def hold(self):
        self.velocity_lease.reset()
        self.mode = 'hold'
        self._base_command.fill(0.)

    def state(self):
        art = self._runner.articulation
        p, q = art.get_world_poses()
        v, w = art.get_velocities()
        p, q, v, w = p.numpy()[0], q.numpy()[0], v.numpy()[0], w.numpy()[0]
        qw, qx, qy, qz = q
        yaw = math.atan2(2*(qw*qz+qx*qy), 1-2*(qy*qy+qz*qz))
        tilt = math.degrees(math.acos(float(np.clip(1-2*(qx*qx+qy*qy), -1, 1))))
        return p, q, v, w, yaw, tilt

    def on_physics_step(self, dt, context):
        try:
            if abs(dt-self._physics_dt)>1e-6:
                raise RuntimeError(f'Unexpected physics dt {dt}; expected {self._physics_dt}')
            if self.mode == 'validation':
                self.phase, cmd = validation_command(self.elapsed, self.config)
                self._base_command[:] = cmd
            elif self.mode == 'nav2':
                self.phase = 'nav2'
                self._base_command[:] = self.velocity_lease.sample(time.monotonic())
            elif self.mode == 'waypoints' and self._physics_ready:
                p, _, _, _, yaw, _ = self.state()
                self._base_command[:] = self.follower.command(p[0], p[1], yaw, self.elapsed)
                self.phase = self.follower.status
            else:
                self.phase = 'hold'
                self._base_command.fill(0.)
            was_ready = self._physics_ready
            super().on_physics_step(dt, context)  # Official restart/step/decimation/gains/binding.
            if self._policy_failed:
                raise RuntimeError('Official policy callback failed; see Kit log for deployment reason')
            if not self._physics_ready:
                return
            if not was_ready:
                self.ready_count += 1
                self.manifest['runtime_initialized'] = True
                self.manifest['joint_names'] = list(self._runner.articulation.dof_names)
                self.manifest['ready_count'] = self.ready_count
            self.elapsed += dt
            self.ticks += 1
            if self.ticks % 10 == 0:
                p, q, v, w, yaw, tilt = self.state()
                values = [*p, *q, *v, *w, tilt]
                if not np.isfinite(values).all():
                    raise RuntimeError('Nonfinite physics state')
                self.records.append(dict(t=self.elapsed, phase=self.phase, command=self._base_command.tolist(),
                                         position=p.tolist(), quaternion=q.tolist(), velocity=v.tolist(),
                                         angular_velocity=w.tolist(), yaw=yaw, tilt_deg=tilt,
                                         physics_ticks=self.ticks))
            if self.phase == 'done' and self.mode == 'validation':
                self.hold()
                self.save()
        except Exception as error:
            self.failure = str(error)
            self.hold()
            self._policy_failed = True
            self.save()
            omni.timeline.get_timeline_interface().pause()

    def save(self):
        (self.output/'manifest.json').write_text(json.dumps(getattr(self, 'manifest', {}), indent=2))
        (self.output/'telemetry.json').write_text(json.dumps(self.records))
        (self.output/'failure.json').write_text(json.dumps({'failure': self.failure}))

    def physics_cleanup(self):
        self.hold()
        self.save()
        self.camera = None
        super().physics_cleanup()
