from dataclasses import replace
import unittest
from tracebot.harness import Harness
from tracebot.providers.harness_fixture import FixtureTools, FixturePlanner


class StandingTools(FixtureTools):
    async def observe(self,*args):
        evidence,observation,record=await super().observe(*args)
        return evidence,replace(observation,posture='standing',visible_risk_cues=()),record


class InspectionCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_clear_inspection_answers_end_request_without_safe_verdict(self):
        tools=StandingTools()
        result=await Harness('ep',FixturePlanner(),tools,finish_on_inspection_answer=True).run()
        self.assertEqual(result['agent_decisions'],2)
        self.assertTrue(result['inspection_answer']['presence']['value'])
        self.assertFalse(result['inspection_answer']['lying']['value'])
        self.assertEqual(result['state'],'escalated_unknown')
        self.assertTrue(result['completed'])

    async def test_limited_evidence_does_not_satisfy_request(self):
        result=await Harness('ep',FixturePlanner(),StandingTools(limited=True),
            finish_on_inspection_answer=True,max_steps=2).run()
        self.assertIsNone(result['inspection_answer'])
        self.assertEqual(result['state'],'escalated_unknown')

    async def test_visible_danger_is_not_downgraded_by_request_completion(self):
        result=await Harness('ep',FixturePlanner(),FixtureTools(),finish_on_inspection_answer=True).run()
        self.assertEqual(result['state'],'danger_confirmed')

    async def test_ablation_preserves_non_autocompleting_baseline(self):
        result=await Harness('ep',FixturePlanner(),StandingTools(),max_steps=3).run()
        self.assertIsNone(result['inspection_answer'])
        self.assertEqual(result['agent_decisions'],3)
