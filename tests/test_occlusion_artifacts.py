"""Validate saved real-render evidence; this test does not run Isaac Sim."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CaptureEvidence(unittest.TestCase):
    def test_real_capture_contract(self):
        result_path = ROOT / 'artifacts/occlusion/results.json'
        self.assertTrue(result_path.is_file(), 'Run scripts/run_occlusion.py first')
        result = json.loads(result_path.read_text())
        self.assertEqual(result['verification_level'], 'isaac-rendered-primitive-occlusion')
        records = {(r['phase'], r['camera']): r for r in result['records']}
        self.assertGreater(records['entry', 'FixedCamera']['person_proxy_pixels'], 100)
        self.assertEqual(records['occluded', 'FixedCamera']['person_proxy_pixels'], 0)
        self.assertEqual(records['before_move', 'MovingCamera']['person_proxy_pixels'], 0)
        self.assertGreater(records['after_move', 'MovingCamera']['person_proxy_pixels'], 100)
        self.assertEqual(records['after_move', 'FixedCamera']['person_proxy_pixels'], 0)
        for record in records.values():
            self.assertEqual(record['shape'], [720, 1280, 3])
            path = ROOT / record['file']
            self.assertEqual(path.stat().st_size, record['bytes'])
            self.assertEqual(path.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
            self.assertGreater(record['mean_rgb'], 30)
            self.assertGreater(record['std_rgb'], 5)
        self.assertTrue(result['passed'])
