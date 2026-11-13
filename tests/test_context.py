import hashlib
import json
import unittest
from dataclasses import replace
from tracebot.context import ContextGraph
from tracebot.core import Evidence
from tracebot.providers.single_frame_vlm import Interpretation


def frame(eid='e1', t=0., visible='yes', posture='lying', limits=()):
    return (Evidence(eid,'ep','body',t,t,'fixture://'+eid),
            Interpretation(visible,posture,(),limits,False,(eid,)))

class ContextTests(unittest.TestCase):
    def test_expiry_reopens_dependents_without_erasing_history(self):
        g=ContextGraph('ep',max_age=5)
        g.observe(*frame(),0)
        old=g.snapshot()
        self.assertEqual(old['payload']['questions']['risk']['state'],'resolved')
        g.advance(5)
        new=g.snapshot()
        self.assertEqual(new['payload']['questions']['risk']['state'],'unresolved')
        self.assertTrue(any(x['question_id']=='risk' and x['reopened'] for x in new['payload']['history']))
        self.assertEqual(old['payload']['questions']['risk']['state'],'resolved')
        self.assertNotEqual(old['sha256'],new['sha256'])
    def test_conflict_and_revocation_propagate(self):
        g=ContextGraph('ep');g.observe(*frame(),0)
        g.observe(*frame('e2',1,posture='standing'),1)
        self.assertEqual(g.snapshot()['payload']['questions']['risk']['state'],'conflicted')
        g.revoke('e2',2)
        self.assertEqual(g.snapshot()['payload']['questions']['risk']['state'],'resolved')
        g.revoke('e1',3)
        self.assertEqual(g.snapshot()['payload']['questions']['risk']['state'],'unresolved')
    def test_non_detection_is_not_absence(self):
        g=ContextGraph('ep');g.observe(*frame(visible='no',posture='unknown'),0)
        self.assertEqual(g.snapshot()['payload']['questions']['presence']['state'],'unresolved')
    def test_absence_requires_trusted_coverage_and_no_occlusion(self):
        g=ContextGraph('ep');g.observe(*frame(visible='no',limits=('occluded',)),0,complete_coverage=True)
        self.assertEqual(g.snapshot()['payload']['questions']['presence']['state'],'unresolved')
        g.observe(*frame('e2',1,visible='no',posture='unknown'),1,complete_coverage=True)
        q=g.snapshot()['payload']['questions'];self.assertIs(q['presence']['value'],False)
        self.assertEqual(q['risk']['state'],'unresolved')
    def test_scope_episode_subject_and_reference_rejection(self):
        for change in ({'episode':'other'},{'subject':'other'},{'generation':1},{'received_time':9}):
            g=ContextGraph('ep');e,o=frame()
            self.assertFalse(g.observe(replace(e,**change),o,0))
        g=ContextGraph('ep');e,o=frame()
        self.assertFalse(g.observe(e,replace(o,evidence_ids=('other',)),0))
    def test_duplicate_cannot_refresh_expiry(self):
        g=ContextGraph('ep',max_age=5);g.observe(*frame(),0)
        self.assertFalse(g.observe(*frame(),4))
        g.advance(5);self.assertEqual(g.snapshot()['payload']['questions']['presence']['state'],'unresolved')
    def test_snapshot_digest_and_defensive_copy(self):
        g=ContextGraph('ep');g.observe(*frame(),0);s=g.snapshot()
        raw=json.dumps(s['payload'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        self.assertEqual(s['sha256'],hashlib.sha256(raw).hexdigest())
        s['payload']['questions'].clear();self.assertTrue(g.snapshot()['payload']['questions'])
    def test_bad_clock_and_unknown_question_rejected(self):
        g=ContextGraph('ep');g.advance(1)
        for t in (0,float('nan')):
            with self.assertRaises(ValueError):g.advance(t)
        with self.assertRaises(ValueError):g.bind(dict(question_id='invented'))
    def test_new_evidence_resolves_after_expiry(self):
        g=ContextGraph('ep',max_age=5);g.observe(*frame(),0);g.advance(5)
        g.observe(*frame('new',6),6)
        self.assertEqual(g.snapshot()['payload']['questions']['risk']['evidence_ids'],['new'])

class IntegratedContext(unittest.IsolatedAsyncioTestCase):
    async def test_harness_actions_and_results_link_to_questions(self):
        from tracebot.harness import Harness
        from tracebot.providers.harness_fixture import FixtureTools,FixturePlanner
        result=await Harness('ep',FixturePlanner(),FixtureTools(fail_first=True)).run()
        self.assertEqual(result['context_snapshot']['payload']['questions']['risk']['state'],'resolved')
        actions=[e['action'] for e in result['trace'] if e['kind']=='decision']
        self.assertTrue(all(a['question_id'] in ('presence','lying') for a in actions))
        self.assertTrue(any(e.get('question_id') for e in result['trace'] if e['kind']=='tool_result'))

    async def test_conflicting_posture_blocks_incident_danger_close(self):
        from tracebot.harness import Harness
        from tracebot.providers.harness_fixture import FixtureTools
        class Tools(FixtureTools):
            async def observe(self,camera,episode):
                self.current='east_inspection'
                e,o,r=await super().observe(camera,episode)
                if len(self.captures)==1:
                    o=replace(o,posture='standing',visible_risk_cues=())
                return e,o,r
        class Planner:
            def __init__(self):self.step=0
            async def choose(self,state):
                self.step+=1
                return dict(tool='observe' if self.step<3 else 'escalate',
                    target='body' if self.step<3 else '',reason='Check conflicting posture.',question_id='lying')
        r=await Harness('ep',Planner(),Tools()).run()
        self.assertEqual(r['state'],'escalated_unknown')
        self.assertEqual(r['context_snapshot']['payload']['questions']['risk']['state'],'conflicted')
