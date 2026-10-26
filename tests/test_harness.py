import asyncio
from dataclasses import replace
import unittest
from haiclaw.harness import Harness,validate_action
from haiclaw.providers.harness_fixture import FixtureTools,FixturePlanner

class SequencePlanner:
    def __init__(self,actions):self.actions=list(actions);self.states=[]
    async def choose(self,state):
        self.states.append(state)
        return self.actions.pop(0)

def action(tool,target=''):return dict(tool=tool,target=target,reason='Test choice based on available evidence.')

class HarnessTests(unittest.IsolatedAsyncioTestCase):
    async def test_motion_failure_replans_to_different_view(self):
        tools=FixtureTools(fail_first=True)
        result=await Harness('ep',FixturePlanner(),tools).run()
        self.assertEqual(tools.moves,['east_inspection','southeast_inspection'])
        self.assertEqual(tools.captures,['body'])
        self.assertEqual(result['state'],'danger_confirmed')
        self.assertTrue(result['completed']);self.assertGreater(tools.stopped,0)
    async def test_limited_evidence_selects_another_view_then_unknown(self):
        tools=FixtureTools(limited=True)
        # Prevent endless alternating through the two viewpoints via explicit choices.
        planner=SequencePlanner([action('inspect','east_inspection'),action('observe','body'),
            action('inspect','southeast_inspection'),action('observe','body'),action('escalate')])
        result=await Harness('ep',planner,tools).run()
        self.assertEqual(result['state'],'escalated_unknown')
        self.assertEqual(len(tools.moves),2)
        self.assertIn('pixelated texture',str(planner.states[2]['observations']))
    async def test_no_model_safe_tool_or_arbitrary_target_executes(self):
        tools=FixtureTools();planner=SequencePlanner([action('safe'),action('inspect','/tmp/arbitrary'),action('escalate')])
        result=await Harness('ep',planner,tools).run()
        self.assertEqual(tools.moves,[]);self.assertEqual(result['state'],'escalated_unknown')
        self.assertEqual(len([e for e in result['trace'] if e['kind']=='rejected']),2)
    async def test_deadline_during_planning(self):
        class Slow:
            async def choose(self,state):await asyncio.sleep(20);return action('inspect','east_inspection')
        tools=FixtureTools();result=await Harness('ep',Slow(),tools,budget=.05).run()
        self.assertEqual(result['state'],'escalated_unknown');self.assertEqual(tools.moves,[])
    async def test_wall_timeout_with_frozen_clock(self):
        class Frozen(FixtureTools):
            async def snapshot(self):return dict(now=1.,playing=True)
        class Slow:
            async def choose(self,state):await asyncio.sleep(10)
        tools=Frozen();result=await Harness('ep',Slow(),tools,wall_budget=.05).run()
        self.assertEqual(result['state'],'escalated_unknown');self.assertTrue(result['completed'])
    async def test_old_episode_observation_never_accepted(self):
        class Old(FixtureTools):
            async def observe(self,camera,episode):
                e,o,r=await super().observe(camera,episode)
                return replace(e,episode='previous'),o,r
        tools=Old();planner=SequencePlanner([action('inspect','east_inspection'),action('observe','body'),action('escalate')])
        result=await Harness('ep',planner,tools).run()
        self.assertEqual(result['state'],'escalated_unknown');self.assertEqual(result['observations'],[])
    async def test_stopped_simulation_aborts(self):
        class Paused(FixtureTools):
            async def snapshot(self):return dict(now=1.,playing=False)
        tools=Paused();result=await Harness('ep',FixturePlanner(),tools).run()
        self.assertFalse(result['completed']);self.assertIn('stopped',result['error']);self.assertEqual(tools.stopped,1)
    async def test_reset_clock_aborts_without_safe_close(self):
        class Reset(FixtureTools):
            def __init__(self):super().__init__();self.n=0
            async def snapshot(self):self.n+=1;return dict(now=10. if self.n<3 else 1.,playing=True)
        result=await Harness('ep',FixturePlanner(),Reset()).run()
        self.assertFalse(result['completed']);self.assertEqual(result['state'],'escalated_unknown')
    async def test_step_limit_bounds_indecisive_agent(self):
        result=await Harness('ep',SequencePlanner([action('stop')]),FixtureTools(),max_steps=1).run()
        self.assertEqual(result['state'],'escalated_unknown')
    async def test_transport_error_is_recorded_and_stops(self):
        class Error:
            async def choose(self,state):raise ConnectionError('offline')
        tools=FixtureTools();r=await Harness('ep',Error(),tools).run()
        self.assertFalse(r['completed']);self.assertIn('offline',r['error']);self.assertEqual(tools.stopped,1)
    async def test_cancellation_stops_robot(self):
        class Slow:
            async def choose(self,state):await asyncio.sleep(10)
        tools=FixtureTools();h=Harness('ep',Slow(),tools);task=asyncio.create_task(h.run())
        await asyncio.sleep(.02);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertGreater(tools.stopped,0);self.assertFalse(h.completed)
    async def test_context_has_no_fixture_truth_or_files(self):
        planner=SequencePlanner([action('escalate')]);await Harness('ep',planner,FixtureTools()).run()
        state=str(planner.states)
        for token in ('limited','fail_first','lying_on_floor','artifact','/home/'):
            self.assertNotIn(token,state)
    def test_invalid_limits(self):
        for budget in (float('nan'),float('inf'),0,-1):
            with self.assertRaises(ValueError):Harness('ep',None,None,budget=budget)

    async def test_deadline_discards_late_tool_result(self):
        class Late(FixtureTools):
            async def observe(self,camera,episode):
                try:await asyncio.sleep(1)
                except asyncio.CancelledError:await asyncio.sleep(.01)
                self.current='east_inspection'
                return await super().observe(camera,episode)
        h=Harness('ep',SequencePlanner([action('observe','body')]),Late(),budget=.03)
        result=await h.run();await asyncio.sleep(.05)
        self.assertEqual(result['state'],'escalated_unknown')
        self.assertEqual(h.memory,[])
    async def test_observation_file_paths_never_enter_model_context(self):
        tools=FixtureTools(limited=True);planner=SequencePlanner([action('observe','fixed'),action('escalate')])
        h=Harness('ep',planner,tools);r=await h.run()
        self.assertTrue(r['evidence_records'])
        self.assertNotIn('fixture://',str(planner.states))
    async def test_observation_timeout_is_not_safe(self):
        class Slow(FixtureTools):
            async def observe(self,camera,episode):await asyncio.sleep(10)
        r=await Harness('ep',SequencePlanner([action('observe','fixed')]),Slow(),operation_timeout=.02).run()
        self.assertEqual(r['state'],'escalated_unknown')

    async def test_motion_timeout_replans_with_remaining_budget(self):
        class SlowFirst(FixtureTools):
            async def inspect(self,target):
                if target=='east_inspection':await asyncio.sleep(10)
                return await super().inspect(target)
        tools=SlowFirst();r=await Harness('ep',FixturePlanner(),tools,operation_timeout=.05,motion_timeout=.05).run()
        self.assertEqual(tools.moves,['southeast_inspection'])
        self.assertEqual(r['state'],'danger_confirmed')
        self.assertTrue(any(e.get('status')=='timeout' for e in r['trace']))

    async def test_arrival_requires_fresh_body_before_next_move(self):
        tools=FixtureTools(limited=True)
        planner=SequencePlanner([action('inspect','east_inspection'),
            action('inspect','southeast_inspection'),action('observe','body'),
            action('inspect','southeast_inspection'),action('escalate')])
        r=await Harness('ep',planner,tools).run()
        self.assertEqual(tools.moves,['east_inspection','southeast_inspection'])
        self.assertFalse(any(t['tool']=='inspect' for t in planner.states[1]['available_tools']))
        self.assertTrue(any(t['tool']=='inspect' for t in planner.states[3]['available_tools']))
        self.assertEqual(len([e for e in r['trace'] if e['kind']=='rejected']),1)

    async def test_failed_move_does_not_claim_previous_viewpoint(self):
        class FailSecond(FixtureTools):
            async def inspect(self,target):
                if target=='southeast_inspection':return dict(status='failed')
                return await super().inspect(target)
        planner=SequencePlanner([action('inspect','east_inspection'),action('observe','body'),
            action('inspect','southeast_inspection'),action('escalate')])
        r=await Harness('ep',planner,FailSecond(limited=True)).run()
        self.assertIsNone(planner.states[3]['current_viewpoint'])
        self.assertEqual(r['state'],'escalated_unknown')
