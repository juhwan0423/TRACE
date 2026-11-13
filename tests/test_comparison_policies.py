"""Policy/host contract tests with explicit fixtures; no Isaac, VLM or ROS claims."""
from copy import deepcopy
from dataclasses import replace
import unittest

from haiclaw.comparison_policies import CameraOnlyPlanner, FixedOrderVerificationPlanner
from haiclaw.harness import Harness, validate_action
from haiclaw.providers.harness_fixture import FixtureTools


VIEWS = ('east_inspection', 'southeast_inspection')


def public_context(**changes):
    result = dict(episode='ep', observations=[], current_viewpoint=None,
                  required_next_evidence=None, recent_events=[],
                  remaining_sim_seconds=180, remaining_wall_seconds=900,
                  available_tools=[dict(tool='observe', target='fixed'),
                                   dict(tool='observe', target='body'),
                                   *[dict(tool='inspect', target=v) for v in reversed(VIEWS)],
                                   dict(tool='escalate', target='')],
                  context_graph=dict(questions=[dict(id=q, state='unresolved')
                                                for q in ('presence', 'lying')]))
    result.update(changes)
    return result


class ComparisonPlannerTests(unittest.IsolatedAsyncioTestCase):
    async def test_predeclared_order_retry_budget_and_bounded_exhaustion(self):
        tools = FixtureTools(limited=True)
        planner = FixedOrderVerificationPlanner(VIEWS)
        result = await Harness('ep', planner, tools, max_steps=12, view_retry_budget=2).run()
        self.assertEqual(tools.moves, list(VIEWS))
        self.assertEqual(tools.captures, ['fixed', 'fixed', 'body', 'body', 'body', 'body'])
        self.assertEqual(result['state'], 'escalated_unknown')
        self.assertEqual(result['agent_decisions'], 9)
        self.assertFalse(any(e['kind'] == 'rejected' for e in result['trace']))
        for record in planner.records:
            self.assertGreaterEqual(record['latency_wall_seconds'], 0)
            self.assertEqual(record['raw_action'], record['action'])

    async def test_failed_viewpoint_skipped_then_fresh_observation(self):
        tools = FixtureTools(fail_first=True)
        planner = FixedOrderVerificationPlanner(VIEWS, initial_camera=None)
        result = await Harness('ep', planner, tools).run()
        self.assertEqual(tools.moves, list(VIEWS))
        self.assertEqual(tools.captures, ['body'])
        self.assertEqual(result['state'], 'danger_confirmed')
        starts = [e for e in result['trace'] if e['kind'] == 'tool_start']
        self.assertEqual([e['action']['tool'] for e in starts], ['inspect', 'inspect', 'observe'])

    async def test_invalid_postarrival_frames_do_not_authorize_next_move(self):
        class Stale(FixtureTools):
            async def observe(self, camera, episode):
                evidence, observation, record = await super().observe(camera, episode)
                return replace(evidence, episode='old'), observation, record
        tools = Stale()
        result = await Harness('ep', FixedOrderVerificationPlanner(VIEWS, initial_camera=None), tools).run()
        self.assertEqual(tools.moves, [VIEWS[0]])
        self.assertEqual(tools.captures, ['body', 'body'])
        self.assertEqual(result['observations'], [])
        self.assertEqual(result['state'], 'escalated_unknown')

    async def test_camera_errors_consume_bounded_attempts(self):
        class Broken(FixtureTools):
            async def observe(self, camera, episode):
                self.captures.append(camera)
                raise RuntimeError('fixture camera failed')
        tools = Broken()
        result = await Harness('ep', CameraOnlyPlanner(), tools).run()
        self.assertEqual(tools.captures, ['fixed', 'fixed'])
        self.assertEqual(tools.moves, [])
        self.assertEqual(result['state'], 'escalated_unknown')
        self.assertEqual(result['agent_decisions'], 3)

    async def test_host_question_completion_does_not_become_safe_verdict(self):
        class Standing(FixtureTools):
            async def observe(self, camera, episode):
                evidence, observation, record = await super().observe(camera, episode)
                return evidence, replace(observation, posture='standing', visible_risk_cues=()), record
        tools = Standing()
        result = await Harness('ep', FixedOrderVerificationPlanner(VIEWS, initial_camera=None), tools,
                               finish_on_inspection_answer=True).run()
        self.assertEqual(result['agent_decisions'], 2)
        self.assertFalse(result['inspection_answer']['lying']['value'])
        self.assertEqual(result['state'], 'escalated_unknown')
        self.assertEqual(tools.captures, ['body'])

    async def test_camera_only_does_not_move_or_use_disabled_camera(self):
        class BodyOnly(FixtureTools):
            cameras = ('body',)
        tools = BodyOnly()
        result = await Harness('ep', CameraOnlyPlanner('fixed'), tools).run()
        self.assertEqual(tools.captures, [])
        self.assertEqual(tools.moves, [])
        self.assertEqual(result['state'], 'escalated_unknown')

    async def test_initial_camera_disabled_skips_to_declared_view(self):
        class BodyOnly(FixtureTools):
            cameras = ('body',)
        tools = BodyOnly()
        result = await Harness('ep', FixedOrderVerificationPlanner(VIEWS), tools).run()
        self.assertEqual(tools.moves, [VIEWS[0]])
        self.assertEqual(tools.captures, ['body'])
        self.assertEqual(result['state'], 'danger_confirmed')

    async def test_public_catalog_order_and_irrelevant_truth_cannot_rank_views(self):
        a = public_context()
        b = deepcopy(a)
        b.update(scenario_truth='fallen', human_xyz=[1, 2, 3], artifact='/hidden/ground_truth')
        pa = FixedOrderVerificationPlanner(VIEWS, initial_camera=None)
        pb = FixedOrderVerificationPlanner(VIEWS, initial_camera=None)
        aa, ab = await pa.choose(a), await pb.choose(b)
        self.assertEqual(aa, ab)
        self.assertEqual(aa['target'], VIEWS[0])
        validate_action(aa, a['available_tools'])

    async def test_known_references_and_question_are_schema_compatible(self):
        context = public_context(observations=[dict(evidence_id='current')],
                                 context_graph=dict(questions=[dict(id='presence', state='resolved'),
                                                               dict(id='lying', state='unresolved')]))
        before = deepcopy(context)
        action = await CameraOnlyPlanner().choose(context)
        validate_action(action, context['available_tools'], ['current'])
        self.assertEqual(action['question_id'], 'lying')
        self.assertEqual(action['evidence_ids'], ['current'])
        self.assertEqual(context, before)

    async def test_episode_reset_and_duplicate_event_do_not_inflate_attempts(self):
        planner = CameraOnlyPlanner(max_observations_per_view=2)
        context = public_context()
        self.assertEqual((await planner.choose(context))['tool'], 'observe')
        event = dict(kind='tool_result', tool='observe', target='fixed', status='ok',
                     evidence_id='frame1', sim_time=1., wall_elapsed=1.)
        context['recent_events'] = [event, deepcopy(event)]
        self.assertEqual((await planner.choose(context))['tool'], 'observe')
        context['recent_events'].append(dict(event, evidence_id='frame2', sim_time=2., wall_elapsed=2.))
        self.assertEqual((await planner.choose(context))['tool'], 'escalate')
        self.assertEqual((await planner.choose(public_context(episode='next')))['tool'], 'observe')

    async def test_missing_completion_feedback_does_not_repeat_tool(self):
        planner = CameraOnlyPlanner()
        context = public_context()
        self.assertEqual((await planner.choose(context))['tool'], 'observe')
        self.assertEqual((await planner.choose(context))['tool'], 'escalate')

    async def test_host_budget_and_stricter_view_limit_are_respected(self):
        context = public_context(remaining_sim_seconds=0)
        self.assertEqual((await CameraOnlyPlanner().choose(context))['tool'], 'escalate')
        tools = FixtureTools(limited=True)
        result = await Harness('ep', FixedOrderVerificationPlanner(VIEWS), tools,
                               view_retry_budget=1, max_steps=12).run()
        self.assertEqual(tools.captures, ['fixed', 'body', 'body'])
        self.assertEqual(result['state'], 'escalated_unknown')

    def test_invalid_settings_rejected(self):
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                CameraOnlyPlanner(max_observations_per_view=value)
        for order in ('east', ['east', 'east'], ['']):
            with self.assertRaises(ValueError):
                FixedOrderVerificationPlanner(order)


if __name__ == '__main__':
    unittest.main()
