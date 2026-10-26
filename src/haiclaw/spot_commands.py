"""Velocity requests only. No robot pose writes or policy observation/action code."""
import math


def validation_command(t, config):
    end = 0.
    for phase, duration in config['phases_seconds'].items():
        end += duration
        if t < end:
            if phase == 'forward':
                return phase, [config['command_forward_mps'], 0., 0.]
            if phase == 'turn':
                return phase, [0., 0., config['command_turn_radps']]
            return phase, [0., 0., 0.]
    return 'done', [0., 0., 0.]


class WaypointFollower:
    def __init__(self, targets, tolerance=.25, timeout=45.):
        self.targets = list(targets)
        self.tolerance, self.timeout = tolerance, timeout
        self.index = 0
        self.status = 'moving'

    def command(self, x, y, yaw, elapsed):
        if self.status != 'moving':
            return [0., 0., 0.]
        if elapsed >= self.timeout:
            self.status = 'timed_out'
            return [0., 0., 0.]
        dx, dy = self.targets[self.index][0]-x, self.targets[self.index][1]-y
        if math.hypot(dx, dy) <= self.tolerance:
            self.index += 1
            if self.index == len(self.targets):
                self.status = 'arrived'
            return [0., 0., 0.]
        heading = (math.atan2(dy, dx)-yaw+math.pi) % (2*math.pi)-math.pi
        return [min(.25, math.hypot(dx, dy)) if abs(heading)<.35 else 0.,
                0., max(-.3, min(.3, heading))]
