import base64
from dataclasses import asdict
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from comparison_evaluator_capture import SCHEMA, paired_payload, save_evaluator_capture
from comparison_support_annotations import build_support
from tracebot.core import Evidence


class SupportAnnotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.trial = self.out/'trials'/'t1'
        (self.trial/'frames').mkdir(parents=True)
        self.evidence = []
        self.rows = [dict(trial_id='t1', normalization=dict(answer_evidence_ids=[]))]

    def add(self, eid, visible=True, calibrated=True):
        mask = np.full((3, 4), 8 if visible else 9, np.uint32)
        frame, metadata = paired_payload(np.full((3, 4, 3), 100, np.uint8),
            dict(data=mask, info={'idToLabels': {'8': '/World/Human/Body', '9': '/World/Machine'}}),
            clock_before=12, clock_after=12, stage_root='/scene.usda',
            target_prim='/World/Human', target_exists=True, render_product='/Render/Camera')
        path = self.trial/'frames'/(eid+'.png')
        Image.open(io.BytesIO(base64.b64decode(frame['image']))).convert('RGB').save(path)
        evidence = Evidence(eid, 'episode', 'body', 12, 13, str(path))
        cal = dict(schema=SCHEMA, stage_root='/scene.usda', target_prim='/World/Human',
                   cameras={'body': dict(positive_pixel_count=3, evidence_id='cal', frame_sha256='a'*64)})
        save_evaluator_capture(self.trial/'evaluator', evidence, metadata,
                               rgb_transport=frame['image'], calibration=cal if calibrated else None)
        self.evidence.append(asdict(evidence))
        self.rows[0]['normalization']['answer_evidence_ids'].append(eid)
        (self.trial/'result.json').write_text(json.dumps(dict(episode='episode',
            captured_evidence=self.evidence, evidence_records=[dict(evidence=e) for e in self.evidence])))

    def label(self):
        return build_support(self.out, self.rows)['t1']

    def edit_sidecar(self, eid, **changes):
        path = self.trial/'evaluator'/(eid+'.json')
        data = json.loads(path.read_text()); data.update(changes); path.write_text(json.dumps(data))

    def test_positive_presence_never_supplies_posture(self):
        self.add('f1')
        human = self.out/'support_annotations.json'; human.write_text('{"unmodified": true}')
        row = self.label()
        self.assertTrue(row['claim_target_present'])
        self.assertIsNone(row['claim_observed_posture'])
        self.assertEqual(row['issues'], [])
        self.assertEqual(human.read_text(), '{"unmodified": true}')

    def test_negative_requires_calibration(self):
        self.add('f1', False, False)
        self.assertIsNone(self.label()['claim_target_present'])
        self.edit_sidecar('f1', target_visible=False)
        self.assertIsNone(self.label()['claim_target_present'])

    def test_all_valid_negative_refs_establish_absence(self):
        self.add('f1', False); self.add('f2', False)
        self.assertFalse(self.label()['claim_target_present'])

    def test_missing_ref_is_unknown_unless_another_valid_ref_is_positive(self):
        self.add('f1', False)
        self.rows[0]['normalization']['answer_evidence_ids'].append('missing')
        self.assertIsNone(self.label()['claim_target_present'])
        self.add('f2', True)
        self.assertTrue(self.label()['claim_target_present'])
        self.assertTrue(self.label()['issues'])

    def test_mask_tampering_and_summary_tampering_fail_closed(self):
        self.add('f1')
        self.edit_sidecar('f1', target_pixel_count=0, target_visible=False)
        self.assertIsNone(self.label()['claim_target_present'])
        self.assertIn('disagrees', self.label()['issues'][0])
        self.edit_sidecar('f1', target_pixel_count=12, target_visible=True)
        (self.trial/'evaluator'/'f1.npz').write_bytes(b'corrupt')
        self.assertIsNone(self.label()['claim_target_present'])
        self.assertIn('hash mismatch', self.label()['issues'][0])

    def test_rgb_hash_episode_and_clock_bindings_are_required(self):
        self.add('f1')
        for changes in (dict(frame_sha256='bad'), dict(episode='other'), dict(clock_before=11)):
            path = self.trial/'evaluator'/'f1.json'; old = path.read_text()
            self.edit_sidecar('f1', **changes)
            self.assertIsNone(self.label()['claim_target_present'])
            path.write_text(old)

    def test_claim_cannot_borrow_mask_from_uncited_frame(self):
        self.add('visible'); self.add('absent', False)
        self.rows[0]['normalization']['answer_evidence_ids'] = ['absent']
        self.assertFalse(self.label()['claim_target_present'])

    def test_report_identity_mismatch_and_no_refs_stay_unknown(self):
        self.add('f1')
        path = self.trial/'result.json'; report = json.loads(path.read_text())
        report['episode'] = 'other'; path.write_text(json.dumps(report))
        self.assertIsNone(self.label()['claim_target_present'])
        self.rows[0]['normalization']['answer_evidence_ids'] = []
        self.assertIsNone(self.label()['claim_target_present'])


if __name__ == '__main__':
    unittest.main()
