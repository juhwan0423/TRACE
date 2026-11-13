import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('annotation_score',Path(__file__).resolve().parents[1]/'tools/person_annotation/score.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def row(presence='visible', boxes=None, status='detected'):
    return dict(id='F001',trial_id='trial',evidence_id='frame',annotation=dict(presence=presence,
        posture='lying' if presence=='visible' else None,box=[0,0,10,10] if presence=='visible' else None,
        prior_exposure=False),detector=dict(status=status,boxes=boxes or [],source='body'))

def box(xyxy,confidence=.9):return dict(xyxy=xyxy,confidence=confidence)

class AnnotationScoreTests(unittest.TestCase):
    def test_inclusive_overlap_boundary(self):
        r=m.score([row(boxes=[box([0,0,5,10])])])
        self.assertEqual(r['recall']['numerator'],1)
        self.assertEqual(r['per_frame'][0]['best_iou'],.5)

    def test_background_singleton_is_not_target_match(self):
        r=m.score([row(boxes=[box([20,20,30,30])])])
        self.assertEqual(r['recall']['numerator'],0)
        self.assertEqual(r['visible_singleton_below_iou'],1)
        self.assertEqual(r['readable_gate_rejection']['numerator'],0)

    def test_duplicate_candidates_only_one_true_positive_and_gate_rejected(self):
        r=m.score([row(boxes=[box([0,0,10,10]),box([1,1,10,10])],status='multiple_people')])
        self.assertEqual(r['recall']['value'],1)
        self.assertEqual(r['object_precision']['value'],.5)
        self.assertEqual(r['unmatched_boxes'],1)
        self.assertEqual(r['readable_gate_rejection']['value'],1)

    def test_detector_failure_not_counted_as_true_negative(self):
        r=m.score([row('absent',status='error')])
        self.assertEqual(r['detector_errors'],1)
        self.assertIsNone(r['absent_any_false_positive']['value'])

    def test_unknown_annotation_not_counted_as_absent(self):
        r=m.score([row('uncertain',boxes=[box([0,0,10,10])])])
        self.assertEqual(r['uncertain'],1)
        self.assertEqual(r['absent'],0)
        self.assertIsNone(r['object_precision']['value'])

    def test_higher_threshold_can_turn_ambiguous_false_positive_into_gate_pass(self):
        rows=[row('absent',[box([0,0,10,10],.7),box([20,20,30,30],.4)],'multiple_people')]
        self.assertEqual(m.score(rows,.25)['absent_singleton_gate_pass']['value'],0)
        self.assertEqual(m.score(rows,.6)['absent_singleton_gate_pass']['value'],1)

if __name__=='__main__':unittest.main()
