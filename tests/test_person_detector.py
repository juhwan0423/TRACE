"""RGB detector boundary fixtures; these do not establish detection accuracy."""
import asyncio
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tracebot.core import Evidence
from tracebot.providers.person_detector import LocalPersonDetector, _ultralytics_factory, DetectorUnavailable

try:
    from PIL import Image
except ImportError:
    Image = None


class Array:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


class Model:
    def __init__(self, boxes=(), names=None, error=None):
        self.names = {0: 'chair', 7: 'person'} if names is None else names
        self.boxes, self.calls, self.error = boxes, [], error

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return [SimpleNamespace(orig_shape=(64, 96), boxes=SimpleNamespace(
            xyxy=Array([b[0] for b in self.boxes]), conf=Array([b[1] for b in self.boxes]),
            cls=Array([b[2] for b in self.boxes])))]


@unittest.skipIf(Image is None, 'optional Pillow dependency unavailable')
class PersonDetectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.weights = self.root / 'local.pt'
        self.weights.write_bytes(b'local checkpoint fixture, not torch')
        self.frame = self.root / 'secret_truth_lying.png'
        Image.new('RGB', (96, 64), (13, 17, 23)).save(self.frame)
        self.evidence = Evidence('opaque', 'secret_episode', 'body', 2., 3., str(self.frame), generation=4)

    def detector(self, model=None, **kwargs):
        model = model or Model()
        self.loaded = []
        def factory(path):
            self.loaded.append(path)
            return model
        return LocalPersonDetector(self.weights, model_factory=factory, **kwargs), model

    def test_presence_uses_named_class_and_only_pixels_enter_backend(self):
        detector, model = self.detector(Model([((3, 4, 40, 60), .8, 7)]))
        self.assertEqual(self.loaded, [])
        result = detector.detect(self.evidence)
        self.assertEqual(result.status, 'detected')
        self.assertTrue(result.single_person)
        self.assertEqual(result.boxes[0].class_id, 7)
        call = model.calls[0]
        self.assertEqual(call['classes'], [7])
        self.assertEqual(call['source'].mode, 'RGB')
        self.assertEqual(call['source'].getpixel((0, 0)), (13, 17, 23))
        self.assertNotIn('secret', str({k: v for k, v in call.items() if k != 'source'}))
        self.assertFalse(getattr(call['source'], 'filename', None))
        self.assertEqual(result.frame_sha256, hashlib.sha256(self.frame.read_bytes()).hexdigest())
        self.assertEqual(result.model_sha256, hashlib.sha256(self.weights.read_bytes()).hexdigest())
        self.assertEqual((result.evidence_id, result.source, result.capture_time, result.generation),
                         ('opaque', 'body', 2., 4))
        self.assertEqual(result.frame_size, (96, 64))
        self.assertIn('posture unverified', result.reason)
        json.dumps(result.to_dict(), allow_nan=False)
        with self.assertRaises(FrozenInstanceError):
            result.status = 'not_detected'

    def test_no_detection_is_not_an_absence_claim(self):
        detector, _ = self.detector()
        result = detector.detect(self.evidence)
        self.assertEqual(result.status, 'not_detected')
        self.assertFalse(result.supports_person_presence)
        self.assertIn('not proof of absence', result.reason)

    def test_confidence_and_person_class_are_checked_again(self):
        detector, _ = self.detector(Model([((1, 1, 10, 10), .9, 0), ((1, 1, 10, 10), .24, 7)]))
        self.assertEqual(detector.detect(self.evidence).status, 'not_detected')

    def test_multiple_people_do_not_establish_target_identity(self):
        detector, _ = self.detector(Model([((1, 1, 10, 10), .5, 7), ((20, 1, 30, 10), .8, 7)]))
        result = detector.detect(self.evidence)
        self.assertEqual(result.status, 'multiple_people')
        self.assertTrue(result.supports_person_presence)
        self.assertFalse(result.single_person)
        self.assertIn('ambiguous', result.reason)
        self.assertEqual(result.boxes[0].confidence, .8)

    def test_low_floor_archives_candidates_but_only_decision_boxes_set_status(self):
        candidates = [((1, 1, 10, 10), .61, 7), ((20, 1, 30, 10), .3, 7),
                      ((40, 1, 50, 10), .049, 7), ((60, 1, 70, 10), .9, 0)]
        detector, model = self.detector(Model(candidates), confidence=.6,
                                       archive_confidence=.05, nms_iou=.7, max_det=300)
        result = detector.detect(self.evidence)
        self.assertEqual(result.status, 'detected')
        self.assertEqual([box.confidence for box in result.boxes], [.61])
        self.assertEqual([box.confidence for box in result.raw_boxes], [.61, .3])
        self.assertEqual(len(model.calls), 1)
        self.assertEqual((model.calls[0]['conf'], model.calls[0]['iou'], model.calls[0]['max_det']),
                         (.05, .7, 300))
        self.assertEqual((result.confidence_threshold, result.archive_confidence,
                          result.nms_iou, result.max_det), (.6, .05, .7, 300))
        self.assertEqual(result.raw_boxes_stage, 'post_nms_person_candidates')
        self.assertFalse(result.raw_boxes_at_capacity)
        payload = result.to_dict()
        self.assertEqual(payload['raw_boxes'][1]['confidence'], .3)
        json.dumps(payload, allow_nan=False)

    def test_decision_threshold_boundary_is_inclusive(self):
        detector, _ = self.detector(Model([((1, 1, 10, 10), .6, 7),
                                           ((20, 1, 30, 10), .599999, 7)]),
                                    confidence=.6, archive_confidence=.05)
        result = detector.detect(self.evidence)
        self.assertEqual(result.status, 'detected')
        self.assertEqual(len(result.raw_boxes), 2)
        self.assertEqual([box.confidence for box in result.boxes], [.6])

    def test_below_decision_threshold_does_not_become_presence(self):
        detector, _ = self.detector(Model([((1, 1, 10, 10), .59, 7)]),
                                    confidence=.6, archive_confidence=.05, max_det=1)
        result = detector.detect(self.evidence)
        self.assertEqual(result.status, 'not_detected')
        self.assertEqual(result.boxes, ())
        self.assertEqual(len(result.raw_boxes), 1)
        self.assertTrue(result.raw_boxes_at_capacity)
        self.assertFalse(result.supports_person_presence)

    def test_legacy_configuration_keeps_original_inference_floor(self):
        detector, model = self.detector(Model([((1, 1, 10, 10), .3, 7),
                                              ((20, 1, 30, 10), .2, 7)]))
        result = detector.detect(self.evidence)
        self.assertEqual(result.raw_boxes, result.boxes)
        self.assertEqual(model.calls[0]['conf'], .25)
        self.assertEqual(result.archive_confidence, .25)

    def test_missing_weights_fail_closed_without_loading_or_download(self):
        detector, _ = self.detector()
        self.weights.unlink()
        result = detector.detect(self.evidence)
        self.assertEqual(result.status, 'unavailable')
        self.assertEqual(self.loaded, [])
        self.assertEqual(result.boxes, ())

    def test_runtime_error_is_not_missed_detection(self):
        detector, _ = self.detector(Model(error=RuntimeError('bad native kernel')))
        result = detector.detect(self.evidence)
        self.assertEqual(result.status, 'error')
        self.assertFalse(result.single_person)

    def test_no_person_class_fails_closed(self):
        detector, _ = self.detector(Model(names={0: 'car'}))
        self.assertEqual(detector.detect(self.evidence).status, 'error')

    def test_changed_checkpoint_is_rejected(self):
        detector, model = self.detector()
        detector.detect(self.evidence)
        self.weights.write_bytes(b'replacement checkpoint')
        result = detector.detect(self.evidence)
        self.assertEqual(result.status, 'error')
        self.assertIn('changed after', result.reason)
        self.assertEqual(len(model.calls), 1)

    def test_checkpoint_loading_is_cached_but_frame_bytes_are_not(self):
        detector, model = self.detector()
        first = detector.detect(self.evidence)
        Image.new('RGB', (96, 64), (99, 88, 77)).save(self.frame)
        second = detector.detect(self.evidence)
        self.assertNotEqual(first.frame_sha256, second.frame_sha256)
        self.assertEqual(len(self.loaded), 1)
        self.assertEqual(model.calls[1]['source'].getpixel((0, 0)), (99, 88, 77))

    def test_bad_boxes_are_errors(self):
        for xyxy, confidence in [((0, 0, 100, 10), .8), ((4, 1, 3, 10), .8),
                                ((1, 1, 3, 10), float('nan'))]:
            with self.subTest(xyxy=xyxy, confidence=confidence):
                detector, _ = self.detector(Model([(xyxy, confidence, 7)]))
                self.assertEqual(detector.detect(self.evidence).status, 'error')

    def test_non_rgb_and_invalid_png_fail_before_model(self):
        for mode in ['L', 'RGBA']:
            Image.new(mode, (96, 64)).save(self.frame)
            detector, _ = self.detector()
            self.assertEqual(detector.detect(self.evidence).status, 'error')
            self.assertEqual(self.loaded, [])
        self.frame.write_bytes(b'not png')
        detector, _ = self.detector()
        self.assertEqual(detector.detect(self.evidence).status, 'error')
        self.assertEqual(self.loaded, [])

    def test_oversized_input_does_not_claim_partial_hash_is_frame_hash(self):
        detector, _ = self.detector(max_image_bytes=8)
        result = detector.detect(self.evidence)
        self.assertEqual(result.status, 'error')
        self.assertIsNone(result.frame_sha256)
        self.assertEqual(self.loaded, [])

    def test_async_wrapper_returns_same_schema(self):
        detector, _ = self.detector()
        result = asyncio.run(detector.infer(self.evidence))
        self.assertEqual(result.status, 'not_detected')


class DetectorConfigurationTests(unittest.TestCase):
    def test_bad_configuration_rejected_without_import(self):
        for path, kwargs in [('https://example.org/model.pt', {}), ('model.onnx', {}),
                             ('model.pt', {'confidence': 0}), ('model.pt', {'confidence': float('nan')}),
                             ('model.pt', {'image_size': 33}), ('model.pt', {'device': ''}),
                             ('model.pt', {'archive_confidence': .3}),
                             ('model.pt', {'archive_confidence': 0}),
                             ('model.pt', {'archive_confidence': float('nan')}),
                             ('model.pt', {'archive_confidence': True}),
                             ('model.pt', {'nms_iou': 0}), ('model.pt', {'nms_iou': 1.1}),
                             ('model.pt', {'nms_iou': float('nan')}), ('model.pt', {'nms_iou': True}),
                             ('model.pt', {'max_det': 0}), ('model.pt', {'max_det': True}),
                             ('model.pt', {'max_det': 300.0}), ('model.pt', {'max_det': 10001})]:
            with self.subTest(path=path, kwargs=kwargs), self.assertRaises(ValueError):
                LocalPersonDetector(path, **kwargs)

    def test_offline_environment_required_before_backend_import(self):
        with patch.dict(os.environ, {'YOLO_OFFLINE': 'false', 'YOLO_AUTOINSTALL': 'false'}):
            with self.assertRaises(DetectorUnavailable):
                _ultralytics_factory('/not/loadable.pt')


if __name__ == '__main__':
    unittest.main()
