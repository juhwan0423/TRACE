"""Nav2 action lifecycle and fresh body-camera capture, simulation only."""
import json
import math
import time
import uuid
from pathlib import Path
from PIL import Image
from rclpy.action import ActionClient
from nav2_msgs.action import NavigateToPose
from isaacsim.core.simulation_manager import SimulationManager
import omni.replicator.core as rep
import omni.timeline
from haiclaw.navigation import InspectionRun


class Nav2Inspection:
    def __init__(self, bridge, root):
        self.bridge, self.demo, self.root = bridge, bridge.demo, Path(root)
        self.client = ActionClient(bridge, NavigateToPose, '/navigate_to_pose')
        self.clock = rep.AnnotatorRegistry.get_annotator('IsaacReadSimulationTime')
        self.clock.attach([str(self.demo.camera.render_product.GetPath())])
        self.run = None
        self.handle = None
        self.last_frame = -1
        self.capture_failure = None
        self.arrived_wall = None
        self.output = self.root/'artifacts/nav2'

    def start(self, x=3., y=1.3, yaw=math.pi):
        if self.run and self.run.status == 'moving':
            raise RuntimeError('Cancel active goal before starting another')
        if not self.client.server_is_ready():
            raise RuntimeError('Nav2 action server not ready')
        if not omni.timeline.get_timeline_interface().is_playing() or self.bridge.failure:
            raise RuntimeError('Simulation/bridge not ready')
        self.output = self.root/'artifacts/nav2'/str(time.time_ns())
        self.output.mkdir(parents=True)
        for filename in ('params.yaml', 'inspect.xml'):
            (self.output/filename).write_text((self.root/'ros2/nav2'/filename).read_text())
        now = SimulationManager.get_simulation_time()
        self.run = InspectionRun(str(uuid.uuid4()), (x,y,yaw), now, time.monotonic(), timeout=180.)
        # Wall budget includes rendering slowdown, fixed before executing any trial.
        self.run.wall_deadline = time.monotonic()+600.
        self.handle, self.capture_failure = None, None
        self.demo.start('nav2')
        self.demo.velocity_lease.reset()
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp.sec = int(now)
        goal.pose.header.stamp.nanosec = int((now-int(now))*1e9)
        goal.pose.pose.position.x, goal.pose.pose.position.y = float(x), float(y)
        goal.pose.pose.orientation.z, goal.pose.pose.orientation.w = math.sin(yaw/2), math.cos(yaw/2)
        goal_id = self.run.goal_id
        future = self.client.send_goal_async(goal)
        future.add_done_callback(lambda f: self.accepted(f, goal_id))
        self.save()

    def accepted(self, future, goal_id):
        handle = future.result()
        if self.run.goal_id != goal_id or self.run.status != 'moving':
            if handle.accepted:
                handle.cancel_goal_async()
            return
        if not handle.accepted:
            self.result(goal_id, 'failed')
            return
        self.handle = handle
        handle.get_result_async().add_done_callback(lambda f: self.result(goal_id, {4:'arrived',5:'cancelled'}.get(f.result().status,'failed')))

    def result(self, goal_id, result):
        pose, sequence = None, None
        if result == 'arrived':
            p, _, _, _, yaw, _ = self.demo.state()
            pose = (float(p[0]), float(p[1]), yaw)
            stamp = float(self.clock.get_data().get('simulationTime', -1))
            sequence = max(0, int(stamp*1e9))
        accepted = self.run.finish(goal_id, result, SimulationManager.get_simulation_time(), time.monotonic(), pose, sequence)
        if accepted:
            if self.run.status == 'arrived':
                self.arrived_wall = time.monotonic()
            self.demo.hold()
            self.demo.save()
            (self.output/'telemetry.json').write_text(json.dumps(self.demo.records))
            if result == 'failed' and self.run.reason is None:
                self.run.reason = 'Nav2 action aborted; see bringup log'
            self.save()

    def cancel(self):
        self.demo.hold()
        if self.run and self.run.status == 'moving':
            self.result(self.run.goal_id, 'cancelled')
            if self.handle:
                self.handle.cancel_goal_async()

    def update(self, event):
        if not self.run:
            return
        now = SimulationManager.get_simulation_time()
        if self.run.status == 'moving':
            if self.demo.mode != 'nav2' or not omni.timeline.get_timeline_interface().is_playing():
                self.cancel()
            elif self.run.tick(now, time.monotonic()) == 'timed_out':
                self.demo.hold()
                if self.handle:
                    self.handle.cancel_goal_async()
                self.save()
            elif self.bridge.failure or self.demo.failure:
                self.result(self.run.goal_id, 'failed')
        elif self.run.status == 'arrived' and self.run.evidence is None and not self.capture_failure:
            if not omni.timeline.get_timeline_interface().is_playing() or now < self.run.arrived_at:
                self.capture_failure = 'timeline interrupted before fresh capture'
                self.save()
                return
            if time.monotonic()-self.arrived_wall > 30.:
                self.capture_failure = 'fresh camera frame timeout'
                self.save()
                return
            if now - self.run.arrived_at < 1.:
                return
            try:
                stamp = float(self.clock.get_data().get('simulationTime', -1))
                if stamp <= self.run.arrived_at:
                    return
                data, _ = self.demo.camera.get_data('rgb')
                if data is None:
                    return
                image = data.numpy()
                path = self.output/'body_camera.png'
                Image.fromarray(image).save(path)
                if not self.run.accept_frame(self.run.goal_id, int(stamp*1e9), stamp, now, path):
                    raise RuntimeError('Camera timestamp rejected')
                self.save()
            except Exception as error:
                self.capture_failure = str(error)
                self.save()

    def save(self):
        state = vars(self.run).copy()
        state.update(planned_path=self.bridge.plan, scan_messages=self.bridge.scan_messages, capture_failure=self.capture_failure, localization='simulation ground-truth',
                     obstacle_sensor='PhysX planar collision rays, 0.65 m height',
                     timestamp_source='IsaacReadSimulationTime attached to body camera render product',
                     thresholds=dict(position_m=.25,yaw_rad=.15,sim_timeout_s=180,wall_timeout_s=600))
        (self.output/'result.json').write_text(json.dumps(state, indent=2))

    def close(self):
        self.cancel()
        self.update_subscription = None
        self.clock.detach([str(self.demo.camera.render_product.GetPath())])
        self.client.destroy()
