import json
from pathlib import Path
import unittest
from tracebot.spot_commands import validation_command, WaypointFollower
from tracebot.spot_validation import evaluate


class SpotCommands(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((Path(__file__).resolve().parents[1]/'configs/spot_acceptance.json').read_text())

    def test_end_of_sequence_requests_zero(self):
        self.assertEqual(validation_command(100, self.config), ('done', [0.,0.,0.]))

    def test_waypoint_behind_requires_turn_without_forward_motion(self):
        follower = WaypointFollower([(-2.,0.)])
        cmd = follower.command(0.,0.,0.,0.)
        self.assertEqual(cmd[0], 0.)
        self.assertLessEqual(abs(cmd[2]), .3)

    def test_timeout_and_arrival_hold_zero(self):
        follower = WaypointFollower([(1.,0.)], timeout=1.)
        self.assertEqual(follower.command(0,0,0,1.), [0.,0.,0.])
        self.assertEqual(follower.status, 'timed_out')
        other = WaypointFollower([(1.,0.)])
        self.assertEqual(other.command(1,0,0,0.), [0.,0.,0.])
        self.assertEqual(other.status, 'arrived')
        self.assertEqual(other.command(0,0,0,1.), [0.,0.,0.])

    def test_missing_or_failed_telemetry_never_passes(self):
        self.assertFalse(evaluate([], self.config)['passed'])
        self.assertFalse(evaluate([], self.config, 'policy failed')['passed'])
