"""Transport-independent navigation safety contracts; no ROS or pose writes.

A ROS adapter must supply fresh receipt times, action IDs, measured poses and
sensor-origin timestamps. Passing these tests does not validate ROS transport.
"""
import math

ZERO = (0., 0., 0.)


class VelocityLease:
    """Conservative demo envelope, NOT a claim about all trained policy limits.

    Monotonic wall time expires commands even when simulation time is paused.
    Rearward/lateral commands are disabled until gait validation covers them.
    """
    def __init__(self, ttl=.25):
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError('positive finite ttl required')
        self.ttl = ttl
        self.reset()

    def reset(self):
        self.command = ZERO
        self.received_at = None

    def receive(self, vx, vy, wz, now):
        values = (vx, vy, wz, now)
        if not all(math.isfinite(v) for v in values):
            self.reset()
            return False
        if self.received_at is not None and now <= self.received_at:
            return False
        # Unsupported degrees of freedom stop rather than silently misexecute.
        if vx < 0 or abs(vy) > 1e-6:
            self.command = ZERO
            self.received_at = now
            return False
        self.command = (min(vx, .25), 0., max(-.3, min(wz, .3)))
        self.received_at = now
        return True

    def sample(self, now):
        if (not math.isfinite(now) or self.received_at is None
                or not 0 <= now - self.received_at < self.ttl):
            self.reset()
            return ZERO
        return self.command


class InspectionRun:
    """One goal lifetime: action success AND measured pose gate arrival.

    Camera frame sequence and capture time must both advance after arrival.
    Times are simulation seconds; wall deadline is separately enforced by tick.
    Terminal callbacks from previous goals cannot alter this run.
    """
    def __init__(self, goal_id, target, sim_now, wall_now, timeout=120.):
        if (len(target) != 3 or not all(math.isfinite(v) for v in
                (*target, sim_now, wall_now, timeout)) or timeout <= 0):
            raise ValueError('finite pose/times and positive timeout required')
        self.goal_id, self.target = goal_id, tuple(target)
        self.sim_deadline, self.wall_deadline = sim_now + timeout, wall_now + timeout
        self.status, self.reason = 'moving', None
        self.arrived_at = self.arrival_frame = self.evidence = None

    def tick(self, sim_now, wall_now):
        if self.status == 'moving' and (sim_now >= self.sim_deadline or wall_now >= self.wall_deadline):
            self.status, self.reason = 'timed_out', 'navigation deadline'
        return self.status

    def finish(self, goal_id, result, sim_now, wall_now, pose=None, frame_sequence=None):
        self.tick(sim_now, wall_now)
        if goal_id != self.goal_id or self.status != 'moving':
            return False
        if result not in ('arrived', 'failed', 'cancelled'):
            raise ValueError('unknown result')
        if result == 'arrived':
            if (pose is None or len(pose) != 3 or not all(math.isfinite(v) for v in pose)
                    or not isinstance(frame_sequence, int) or frame_sequence < 0):
                result, self.reason = 'failed', 'missing measured pose/frame sequence'
            else:
                distance = math.hypot(pose[0]-self.target[0], pose[1]-self.target[1])
                yaw_error = abs(math.atan2(math.sin(pose[2]-self.target[2]), math.cos(pose[2]-self.target[2])))
                if distance > .25 or yaw_error > .15:
                    result, self.reason = 'failed', 'goal position/orientation outside tolerance'
                else:
                    self.arrived_at, self.arrival_frame = sim_now, frame_sequence
        self.status = result
        return True

    def accept_frame(self, goal_id, sequence, capture_time, received_time, artifact):
        if (goal_id != self.goal_id or self.status != 'arrived' or self.evidence is not None
                or not isinstance(sequence, int) or sequence <= self.arrival_frame
                or not all(math.isfinite(v) for v in (capture_time, received_time))
                or not self.arrived_at < capture_time <= received_time or not artifact):
            return False
        self.evidence = dict(goal_id=goal_id, sequence=sequence, capture_time=capture_time,
                             received_time=received_time, artifact=str(artifact))
        return True


class SimulationCadence:
    """Periodic publishing which resumes immediately after a timeline reset."""
    def __init__(self, period):
        if not math.isfinite(period) or period <= 0:
            raise ValueError('positive finite period required')
        self.period, self.last = period, None

    def due(self, now):
        if not math.isfinite(now):
            return False
        if self.last is None or now < self.last or now-self.last >= self.period:
            self.last = now
            return True
        return False
