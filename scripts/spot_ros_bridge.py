"""Simulation-only rclpy adapter on the installed official ROS bridge runtime.

Ground-truth planar localization and a PhysX collision-ray planar scanner.
No AMCL, SLAM, real LiDAR, or real robot transport is claimed.
"""
import math
import time
import rclpy
from haiclaw.navigation import SimulationCadence
from rclpy.node import Node
from geometry_msgs.msg import Twist, TransformStamped
from nav_msgs.msg import Odometry, Path as NavPath
from sensor_msgs.msg import LaserScan
from rosgraph_msgs.msg import Clock
from tf2_msgs.msg import TFMessage
from rclpy.qos import QoSProfile, DurabilityPolicy
import omni.physx
import omni.timeline
from isaacsim.core.simulation_manager import SimulationManager


class SpotROS(Node):
    def __init__(self, demo):
        if not rclpy.ok():
            rclpy.init()
        super().__init__('haiclaw_spot_bridge')
        self.demo = demo
        self.commands = 0
        self.plan = []
        self.plan_subscription = self.create_subscription(NavPath, '/plan', self.receive_plan, 10)
        self.last_scan = -1.
        self.scan_cadence = SimulationCadence(.1)
        self.odom = self.create_publisher(Odometry, '/odom', 10)
        self.tf = self.create_publisher(TFMessage, '/tf', 10)
        self.clock = self.create_publisher(Clock, '/clock', 10)
        self.scan_messages = 0
        self.scan = self.create_publisher(LaserScan, '/scan', 10)
        self.static = self.create_publisher(TFMessage, '/tf_static', QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.subscription = self.create_subscription(Twist, '/cmd_vel', self.receive, 1)
        transform = TransformStamped()
        transform.header.frame_id, transform.child_frame_id = 'map', 'odom'
        transform.transform.rotation.w = 1.
        self.static_transform = transform

        self.failure = None

    def receive_plan(self, msg):
        self.plan = [[p.pose.position.x, p.pose.position.y] for p in msg.poses]

    def receive(self, msg):
        if self.demo.mode == 'nav2':
            self.demo.velocity_lease.receive(msg.linear.x, msg.linear.y, msg.angular.z, time.monotonic())
            self.commands += 1

    def update(self, event):
        try:
            rclpy.spin_once(self, timeout_sec=0.)
            if not omni.timeline.get_timeline_interface().is_playing() or not self.demo._physics_ready:
                self.demo.velocity_lease.reset()
                return
            t = SimulationManager.get_simulation_time()
            stamp = Clock().clock
            stamp.sec, stamp.nanosec = int(t), int((t-int(t))*1e9)
            self.clock.publish(Clock(clock=stamp))
            p, q, v, w, yaw, tilt = self.demo.state()
            msg = Odometry()
            msg.header.stamp, msg.header.frame_id, msg.child_frame_id = stamp, 'odom', 'base_link'
            msg.pose.pose.position.x, msg.pose.pose.position.y = float(p[0]), float(p[1])
            msg.pose.pose.orientation.z, msg.pose.pose.orientation.w = math.sin(yaw/2), math.cos(yaw/2)
            msg.twist.twist.linear.x = float(v[0]*math.cos(yaw)+v[1]*math.sin(yaw))
            msg.twist.twist.linear.y = float(-v[0]*math.sin(yaw)+v[1]*math.cos(yaw))
            msg.twist.twist.angular.z = float(w[2])
            self.odom.publish(msg)
            transform = TransformStamped()
            transform.header, transform.child_frame_id = msg.header, 'base_link'
            transform.transform.translation.x, transform.transform.translation.y = float(p[0]), float(p[1])
            transform.transform.rotation = msg.pose.pose.orientation
            self.static_transform.header.stamp = stamp
            self.tf.publish(TFMessage(transforms=[self.static_transform, transform]))
            if not self.scan_cadence.due(t):
                return
            self.last_scan = t

            scan = LaserScan()
            scan.header.stamp, scan.header.frame_id = stamp, 'base_link'
            scan.angle_min, scan.angle_max, scan.angle_increment = -math.pi, math.pi-math.pi/180, math.pi/180
            scan.range_min, scan.range_max, scan.scan_time = .05, 10., .1
            query = omni.physx.get_physx_scene_query_interface()
            ranges = []
            for i in range(360):
                hits = []
                def report(hit):
                    if not hit.rigid_body.startswith('/World/Spot'):
                        hits.append(hit.distance)
                    return True
                angle = yaw + scan.angle_min + i*scan.angle_increment
                query.raycast_all((float(p[0]), float(p[1]), .65), (math.cos(angle), math.sin(angle), 0.), 10., report)
                ranges.append(float(min(hits)) if hits else float('inf'))
            scan.ranges = ranges
            self.scan.publish(scan)
            self.scan_messages += 1
        except Exception as error:
            self.failure = str(error)
            self.demo.hold()
            self.get_logger().error(self.failure)
            self.update_subscription = None

    def close(self):
        self.demo.hold()
        self.update_subscription = None
        self.destroy_node()
