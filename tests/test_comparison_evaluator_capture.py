"""Paired-capture truth validity and online/offline separation fixtures."""
import asyncio
import base64
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from comparison_evaluator_capture import (SCHEMA, evaluate_presence, paired_payload,
                                           save_evaluator_capture)
from real2sim_harness_tools import Real2SimTools
from tracebot.core import Evidence


def pair(mask=None, mapping=None, **kwargs):
    rgb = np.full((3, 4, 3), 100, dtype=np.uint8)
    if mask is None:
        mask = np.array([[0, 8, 8, 0], [0, 8, 8, 0], [0, 0, 0, 0]], dtype=np.uint32)
    if mapping is None:
        mapping = {'0': 'BACKGROUND', '8': '/World/Human/Body', '9': '/World/Machine'}
    return paired_payload(rgb, dict(data=mask, info={'idToLabels': mapping}),
                          clock_before=kwargs.get('before', 12),
                          clock_after=kwargs.get('after', 12), stage_root='/scene.usda',
                          target_prim='/World/Human', target_exists=kwargs.get('exists', True),
                          render_product='/Render/Camera')


def calibration():
    return dict(schema=SCHEMA, stage_root='/scene.usda', target_prim='/World/Human',
                cameras={'body': dict(positive_pixel_count=4, evidence_id='positive-frame',
                                      frame_sha256='a' * 64)})


class PairedEvaluatorTests(unittest.TestCase):
    def test_rgb_transport_retains_original_jpeg80_and_mask_has_exact_geometry(self):
        frame, metadata = pair()
        original = io.BytesIO()
        Image.fromarray(np.full((3, 4, 3), 100, np.uint8)).save(original, format='JPEG', quality=80)
        self.assertEqual(base64.b64decode(frame['image']), original.getvalue())
        self.assertEqual(metadata['visible_bbox_xyxy'], [1, 0, 3, 2])
        self.assertEqual(metadata['target_pixel_count'], 4)
        archive = np.load(io.BytesIO(base64.b64decode(metadata['mask_npz_base64'])), allow_pickle=False)
        self.assertEqual(archive['instance_ids'].dtype, np.uint32)
        self.assertEqual(evaluate_presence(metadata, None, 'body'), (True, 'mapped_target_pixels'))

    def test_no_target_ids_is_absence_only_with_positive_same_camera_calibration(self):
        _, metadata = pair(mask=np.full((3, 4), 9, np.uint32), mapping={'9': '/World/Machine'})
        self.assertTrue(metadata['mapping_valid'])
        self.assertEqual(metadata['target_ids'], [])
        self.assertIsNone(evaluate_presence(metadata, None, 'body')[0])
        self.assertFalse(evaluate_presence(metadata, calibration(), 'body')[0])
        self.assertIsNone(evaluate_presence(metadata, calibration(), 'fixed')[0])
        changed = calibration(); changed['stage_root'] = '/different.usda'
        self.assertIsNone(evaluate_presence(metadata, changed, 'body')[0])

    def test_missing_or_incomplete_mapping_never_becomes_absence(self):
        mask = np.full((3, 4), 9, np.uint32)
        for mapping in ({}, {'0': 'BACKGROUND'}, {'9': {'class': 'human'}}):
            _, metadata = pair(mask=mask, mapping=mapping)
            self.assertFalse(metadata['mapping_valid'])
            self.assertIsNone(evaluate_presence(metadata, calibration(), 'body')[0])

    def test_target_prefix_does_not_match_other_humans(self):
        _, metadata = pair(mask=np.full((3, 4), 8, np.uint32),
                           mapping={'8': '/World/Human2/Body'})
        self.assertEqual(metadata['target_pixel_count'], 0)

    def test_clock_changes_and_missing_prim_make_positive_unknown(self):
        for kwargs in ({'after': 13}, {'before': -1, 'after': -1}, {'exists': False}):
            _, metadata = pair(**kwargs)
            self.assertIsNone(evaluate_presence(metadata, calibration(), 'body')[0])

    def test_bad_mask_dimensions_cannot_score_visibility(self):
        _, metadata = pair(mask=np.zeros((5, 5), dtype=np.uint32))
        self.assertEqual(metadata['mapping_status'], 'invalid_segmentation')
        self.assertIsNone(evaluate_presence(metadata, calibration(), 'body')[0])

    def test_sidecar_binds_decoded_png_transport_mask_and_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); frame, metadata = pair()
            image = root / 'random-id.png'
            Image.open(io.BytesIO(base64.b64decode(frame['image']))).convert('RGB').save(image)
            evidence = Evidence('random-id', 'episode', 'body', 12, 13, str(image))
            save_evaluator_capture(root/'evaluation', evidence, metadata,
                                   rgb_transport=frame['image'], calibration=calibration())
            saved = json.loads((root/'evaluation/random-id.json').read_text())
            self.assertEqual(saved['frame_sha256'], hashlib.sha256(image.read_bytes()).hexdigest())
            self.assertTrue(saved['target_visible'])
            self.assertIsNone(saved['observable_posture'])
            self.assertNotIn('mask_npz_base64', saved)
            self.assertEqual(saved['mask_sha256'], hashlib.sha256(
                (root/'evaluation/random-id.npz').read_bytes()).hexdigest())
            metadata['rgb_transport_sha256'] = 'bad'
            save_evaluator_capture(root/'mismatch', evidence, metadata,
                                   rgb_transport=frame['image'], calibration=calibration())
            mismatch = json.loads((root/'mismatch/random-id.json').read_text())
            self.assertIsNone(mismatch['target_visible'])


class CaptureBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_adapter_only_sees_rgb_and_truth_never_enters_returned_record(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); frame, metadata = pair()
            async def requester(code, **args):
                if 'snapshot()' in code:
                    return {'now': 11}
                self.assertIn('comparison_evaluator_frames', code)
                return dict(frames={'body': frame}, evaluator={'body': metadata},
                            snapshot=dict(now=13, playing=True))
            adapter = AsyncMock(); adapter.infer.return_value = ('observation', {'status': 'ok'})
            tools = Real2SimTools(adapter, {}, root/'frames', requester,
                                 evaluator_output=root/'evaluator', evaluator_calibration=calibration())
            evidence, obs, record = await tools.observe('body', 'episode')
            self.assertEqual(list(adapter.infer.call_args.args), [evidence])
            self.assertEqual(tools.captured_evidence, [asdict(evidence)])
            self.assertEqual(set(record), {'status', 'capture_snapshot'})
            self.assertEqual(list((root/'frames').iterdir()), [Path(evidence.artifact)])
            self.assertTrue((root/'evaluator'/(evidence.id+'.json')).exists())
            self.assertNotIn('Human', evidence.artifact)

    async def test_qwen_failure_still_retains_captured_frame_and_mask(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); frame, metadata = pair()
            async def requester(code, **args):
                if 'snapshot()' in code:
                    return {'now': 11}
                return dict(frames={'body': frame}, evaluator={'body': metadata},
                            snapshot=dict(now=13, playing=True))
            adapter = AsyncMock(); adapter.infer.side_effect = RuntimeError('Qwen failed')
            tools = Real2SimTools(adapter, {}, root/'frames', requester,
                                 evaluator_output=root/'evaluator')
            with self.assertRaisesRegex(RuntimeError, 'Qwen failed'):
                await tools.observe('body', 'episode')
            self.assertEqual(len(tools.captured_evidence), 1)
            self.assertEqual(len(list((root/'evaluator').glob('*.json'))), 1)

    async def test_default_path_does_not_request_evaluator(self):
        with tempfile.TemporaryDirectory() as temp:
            frame, _ = pair()
            async def requester(code, **args):
                if 'snapshot()' in code:
                    return {'now': 11}
                self.assertIn('real2sim_monitor_frames', code)
                self.assertNotIn('evaluator', code)
                return dict(frames={'body': frame}, snapshot=dict(now=13, playing=True))
            adapter = AsyncMock(); adapter.infer.return_value = ('observation', {'status': 'ok'})
            tools = Real2SimTools(adapter, {}, temp, requester)
            await tools.observe('body', 'episode')

    async def test_broken_mask_is_unknown_but_does_not_control_the_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); frame, metadata = pair()
            metadata['mask_sha256'] = 'corrupt'
            async def requester(code, **args):
                if 'snapshot()' in code:
                    return {'now': 11}
                return dict(frames={'body': frame}, evaluator={'body': metadata},
                            snapshot=dict(now=13, playing=True))
            adapter = AsyncMock(); adapter.infer.return_value = ('observation', {'status': 'ok'})
            tools = Real2SimTools(adapter, {}, root/'frames', requester,
                                 evaluator_output=root/'evaluator')
            evidence, _, record = await tools.observe('body', 'episode')
            adapter.infer.assert_awaited_once()
            saved = json.loads((root/'evaluator'/(evidence.id+'.json')).read_text())
            self.assertIsNone(saved['target_visible'])
            self.assertNotIn('mask_file', saved)
            self.assertNotIn('binding_error', record)


if __name__ == '__main__':
    unittest.main()
