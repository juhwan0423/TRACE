"""Bounded kinematic fixture motion, robot pose only; no ROS/device writes."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class MotionResult:
    status: str
    pose: tuple
    distance: float
    velocity: tuple


class WaypointMotion:
    def __init__(self, targets, speed=.5, angular_speed=1.):
        if speed <= 0 or angular_speed <= 0:
            raise ValueError('positive velocity bounds required')
        self.targets, self.speed, self.angular_speed = targets, speed, angular_speed
        self.pose = (0., -2., 0.)
        self.target = None
        self.status = 'cancelled'
        self.distance = 0.

    def inspect(self, target_id, now, timeout):
        self.target = self.targets.get(target_id)
        self.deadline = now + timeout
        self.status = 'moving' if self.target is not None else 'failed'
        return self.status

    def stop(self):
        self.status = 'cancelled'
        return MotionResult(self.status, self.pose, self.distance, (0., 0.))

    def step(self, now, dt):
        if dt <= 0 or not math.isfinite(dt):
            raise ValueError('positive finite dt required')
        v = w = 0.
        if self.status == 'moving':
            if now >= self.deadline:
                self.status = 'timed_out'
            else:
                x, y, yaw = self.pose
                dx, dy = self.target[0] - x, self.target[1] - y
                distance = math.hypot(dx, dy)
                if distance < .03:
                    self.status = 'arrived'
                else:
                    error = (math.atan2(dy, dx) - yaw + math.pi) % (2 * math.pi) - math.pi
                    w = max(-self.angular_speed, min(self.angular_speed, error / dt))
                    yaw += w * dt
                    if abs(error) < .15:
                        v = min(self.speed, distance / dt)
                        x += v * dt * math.cos(yaw)
                        y += v * dt * math.sin(yaw)
                        self.distance += v * dt
                    self.pose = (x, y, yaw)
        return MotionResult(self.status, self.pose, self.distance, (v, w))


class Nav2Motion:
    def __init__(self, **kwargs):
        raise RuntimeError('Nav2 blocked: validate map, localization, TF, footprint, costmap sensor and locomotion bridge before activation')
