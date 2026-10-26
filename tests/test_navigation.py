import unittest
from haiclaw.navigation import InspectionRun, VelocityLease, ZERO


class NavigationSafety(unittest.TestCase):
    def run_goal(self):
        return InspectionRun('a', (3, 1, 3.14), 0, 100, timeout=20)

    def test_clamp_and_expire_at_boundary(self):
        lease = VelocityLease()
        self.assertTrue(lease.receive(2, 0, -4, 100))
        self.assertEqual(lease.sample(100.1), (.25, 0, -.3))
        self.assertEqual(lease.sample(100.25), ZERO)

    def test_invalid_unsupported_and_reset_stop(self):
        for command in [(-.1, 0, 0), (0, .1, 0), (float('nan'), 0, 0)]:
            lease = VelocityLease()
            lease.receive(.2, 0, 0, 1)
            self.assertFalse(lease.receive(*command, 2))
            self.assertEqual(lease.sample(2), ZERO)
        lease.receive(.2, 0, 0, 3)
        lease.reset()
        self.assertEqual(lease.sample(3), ZERO)

    def test_reordered_command_does_not_refresh_lease(self):
        lease = VelocityLease()
        lease.receive(.2, 0, 0, 10)
        self.assertFalse(lease.receive(.25, 0, .3, 9))
        self.assertEqual(lease.sample(10.25), ZERO)

    def test_wrong_orientation_is_not_arrival(self):
        run = self.run_goal()
        run.finish('a', 'arrived', 2, 102, (3, 1, 0), 5)
        self.assertEqual(run.status, 'failed')
        self.assertIsNone(run.arrived_at)

    def test_late_and_previous_goal_success_rejected(self):
        run = self.run_goal()
        self.assertFalse(run.finish('old', 'arrived', 1, 101, (3, 1, 3.14), 1))
        self.assertFalse(run.finish('a', 'arrived', 20, 120, (3, 1, 3.14), 2))
        self.assertEqual(run.status, 'timed_out')

    def test_wall_timeout_during_sim_pause(self):
        run = self.run_goal()
        self.assertEqual(run.tick(0, 120), 'timed_out')

    def test_terminal_results_and_stale_frames(self):
        for result in ('failed', 'cancelled'):
            run = self.run_goal()
            run.finish('a', result, 1, 101)
            self.assertFalse(run.finish('a', 'arrived', 2, 102, (3, 1, 3.14), 3))
            self.assertFalse(run.accept_frame('a', 4, 3, 3, 'image.png'))
            self.assertEqual(run.status, result)
        run = self.run_goal()
        run.finish('a', 'arrived', 2, 102, (3, 1, -3.14), 10)
        for args in [('old', 11, 3, 3), ('a', 10, 3, 3), ('a', 11, 2, 3), ('a', 11, 4, 3)]:
            self.assertFalse(run.accept_frame(*args, 'image.png'))
        self.assertTrue(run.accept_frame('a', 11, 3, 3.1, 'image.png'))
        self.assertFalse(run.accept_frame('a', 12, 4, 4.1, 'other.png'))


class ScanCadence(unittest.TestCase):
    def test_clock_reset_publishes_without_waiting_for_old_episode_time(self):
        from haiclaw.navigation import SimulationCadence
        cadence = SimulationCadence(.1)
        self.assertTrue(cadence.due(150.))
        self.assertFalse(cadence.due(150.05))
        self.assertTrue(cadence.due(0.))
        self.assertFalse(cadence.due(.05))
        self.assertTrue(cadence.due(.1))
