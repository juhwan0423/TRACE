import unittest
from dataclasses import replace
from tracebot.observation_rules import posture_limitations_block, RULE_VERSION
from tracebot.context import ContextGraph
from tracebot.providers.single_frame_vlm import incident_decision, Interpretation
from tracebot.core import Evidence
from test_comparison_records import report, normalize


class ScopedLimitationsTests(unittest.TestCase):
    def observation(self, limits, **kw):
        return replace(Interpretation('yes','lying',(),tuple(limits),False,('e',)), **kw)

    def test_question_irrelevant_caveats_allow_posture(self):
        for limits in (["person's face not visible", 'view from behind'],
                       ['person viewed from behind, face not visible'],
                       ['low-angle view'], ['rear view']):
            with self.subTest(limits=limits):
                o = self.observation(limits)
                g = ContextGraph('ep')
                self.assertTrue(g.observe(Evidence('e','ep','body',0,0,'fixture://e'),o,0))
                self.assertTrue(g.supports_danger())
                self.assertFalse(incident_decision(o).insufficient_evidence)
                self.assertEqual(g.snapshot()['payload']['evidence']['e']['interpretation']['limitations'],limits)

    def test_unknown_or_mixed_limitations_remain_blocked(self):
        for text in ('occluded', 'blurred', 'upper body obscured', 'head not visible',
                     'face not visible, legs obscured', 'low angle makes posture uncertain',
                     'rear view and multiple people', 'face not visible but body cropped',
                     'not a person, face not visible', ''):
            with self.subTest(text=text):
                self.assertTrue(posture_limitations_block([text]))
                o = self.observation([text])
                g = ContextGraph('ep')
                g.observe(Evidence('e','ep','body',0,0,'fixture://e'),o,0)
                self.assertFalse(g.supports_danger())
                self.assertTrue(incident_decision(o).insufficient_evidence)

    def test_explicit_uncertainty_quality_and_expiry_still_block(self):
        for fields in ({'needs_more_observation':True}, {'posture':'unknown'},
                       {'person_visible':'uncertain'}):
            o = self.observation(['face not visible'], **fields)
            self.assertTrue(incident_decision(o).insufficient_evidence)
        for fields in ({'quality':.2}, {'reason':'occluded'}, {'capture_time':-50,'received_time':-50}):
            e=replace(Evidence('e','ep','body',0,0,'fixture://e'),**fields)
            g=ContextGraph('ep');g.observe(e,self.observation(['face not visible']),0)
            self.assertFalse(g.supports_danger())

    def test_absence_is_not_relaxed(self):
        g=ContextGraph('ep')
        g.observe(Evidence('e','ep','body',0,0,'fixture://e'),
                  self.observation(['rear view'],person_visible='no',posture='unknown'),0,
                  complete_coverage=True)
        self.assertEqual(g.snapshot()['payload']['questions']['presence']['state'],'unresolved')

    def test_normalization_preserves_legacy_rules(self):
        r=report();p=r['context_snapshot']['payload']
        p['evidence']['e1']['interpretation']['limitations']=['face not visible']
        self.assertEqual(normalize(r)['inspection_question_answer'],'unknown')
        p['rule_version']=RULE_VERSION
        self.assertEqual(normalize(r)['inspection_question_answer'],'standing')
        p['evidence']['e1']['interpretation']['limitations'].append('body obscured')
        self.assertEqual(normalize(r)['inspection_question_answer'],'unknown')
