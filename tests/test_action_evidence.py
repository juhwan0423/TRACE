import unittest
from tracebot.harness import validate_action

class ActionEvidenceTests(unittest.TestCase):
    def check(self,refs,known=()):
        return validate_action(dict(tool='observe',target='body',reason='Seek another view.',evidence_ids=refs),
            [dict(tool='observe',target='body')],known)

    def test_initial_action_can_seek_evidence_without_claiming_a_reference(self):
        self.check([])

    def test_reference_must_exist_in_this_planning_context(self):
        with self.assertRaisesRegex(ValueError,'this context'):self.check(['previous-episode'])
        self.check(['current'],['current'])

    def test_duplicate_and_non_string_references_rejected(self):
        for refs in (['current','current'],[None],'current'):
            with self.assertRaises(ValueError):self.check(refs,['current'])
