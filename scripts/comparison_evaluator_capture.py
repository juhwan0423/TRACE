"""Evaluator-only paired RGB / instance-mask capture for the owned live stage.

This file may be imported by offline tools or executed in the ``real2sim``
server namespace. It never supplies segmentation to an online model. Existing
monitor products and JPEG quality are retained; no scene transform is changed.
"""
import base64
import hashlib
import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image


SCHEMA = 'trace-paired-evaluator/1'


def _mapping_info(mapping, mask, target_prim):
    """Resolve IDs from this frame's mapping, never from remembered numeric IDs."""
    if not isinstance(mapping, dict) or not mapping:
        return {}, [], False, 'missing_id_to_labels'
    normalized = {}
    try:
        for key, value in mapping.items():
            index = int(key)
            if index < 0 or not isinstance(value, str) or not value:
                raise ValueError('Invalid instance mapping')
            normalized[str(index)] = value
    except (TypeError, ValueError):
        return {}, [], False, 'malformed_id_to_labels'
    # Background ID 0 can be omitted by the renderer; other image IDs must
    # resolve explicitly, otherwise absence cannot be established.
    missing = set(int(x) for x in np.unique(mask)) - {int(x) for x in normalized} - {0}
    target_ids = [int(k) for k, value in normalized.items()
                  if value == target_prim or value.startswith(target_prim + '/')]
    return normalized, target_ids, not missing, ('unmapped_image_ids' if missing else 'complete')


def paired_payload(rgb, segmentation, *, clock_before, clock_after, stage_root,
                   target_prim, target_exists, render_product):
    """Pure array encoding, used by the live synchronous callback and fixtures."""
    rgb = np.array(rgb, copy=True)
    if rgb.ndim != 3 or rgb.shape[2] < 3 or not rgb.size:
        raise RuntimeError('RGB camera is warming up')
    encoded = io.BytesIO()
    Image.fromarray(rgb[:, :, :3]).save(encoded, format='JPEG', quality=80)
    image = encoded.getvalue()
    metadata = dict(schema=SCHEMA, stage_root=stage_root, target_prim=target_prim,
                    target_exists=bool(target_exists), render_product=str(render_product),
                    clock_before=float(clock_before), clock_after=float(clock_after),
                    synchronized=bool(math.isfinite(clock_before) and clock_before >= 0
                                      and clock_before == clock_after),
                    capture_method='same render product; synchronous copied buffers; clock bracket',
                    rgb_transport_sha256=hashlib.sha256(image).hexdigest(),
                    width=int(rgb.shape[1]), height=int(rgb.shape[0]))
    try:
        mask = np.array(segmentation['data'], copy=True)
        if mask.shape != rgb.shape[:2] or mask.dtype.kind not in 'ui':
            raise ValueError('Instance mask shape or dtype does not match RGB')
        if mask.size and (int(mask.min()) < 0 or int(mask.max()) > 2**32 - 1):
            raise ValueError('Instance IDs exceed uint32 range')
        mask = mask.astype(np.uint32, copy=False)
        mapping, ids, valid, reason = _mapping_info(
            segmentation.get('info', {}).get('idToLabels'), mask, target_prim)
        buffer = io.BytesIO()
        np.savez_compressed(buffer, instance_ids=mask)
        mask_bytes = buffer.getvalue()
        target_mask = np.isin(mask, ids) if ids else np.zeros(mask.shape, dtype=bool)
        ys, xs = np.nonzero(target_mask)
        metadata.update(id_to_labels=mapping, target_ids=ids, mapping_valid=valid,
                        mapping_status=reason, target_pixel_count=int(target_mask.sum()),
                        visible_bbox_xyxy=([int(xs.min()), int(ys.min()), int(xs.max()) + 1,
                                            int(ys.max()) + 1] if len(xs) else None),
                        mask_sha256=hashlib.sha256(mask_bytes).hexdigest(),
                        mask_npz_base64=base64.b64encode(mask_bytes).decode())
    except (KeyError, TypeError, ValueError) as exc:
        metadata.update(mapping_valid=False, mapping_status='invalid_segmentation',
                        segmentation_error=str(exc), target_pixel_count=None,
                        target_ids=[], id_to_labels={}, visible_bbox_xyxy=None)
    frame = dict(image=base64.b64encode(image).decode(), capture_time=float(clock_after),
                 width=int(rgb.shape[1]), height=int(rgb.shape[0]))
    return frame, metadata


def evaluate_presence(metadata, calibration, camera):
    """Segmentation confirms visibility only, never readable posture or identity."""
    if (metadata.get('schema') != SCHEMA or not metadata.get('synchronized')
            or not metadata.get('mapping_valid') or not metadata.get('target_exists')):
        return None, 'invalid_pair_or_mapping'
    pixels = metadata.get('target_pixel_count')
    if not isinstance(pixels, int) or pixels < 0:
        return None, 'invalid_pixel_count'
    if pixels:
        return True, 'mapped_target_pixels'
    calibration = calibration if isinstance(calibration, dict) else {}
    entry = calibration.get('cameras', {}).get(camera, {})
    if (calibration.get('schema') == SCHEMA
            and calibration.get('stage_root') == metadata.get('stage_root')
            and calibration.get('target_prim') == metadata.get('target_prim')
            and isinstance(entry.get('positive_pixel_count'), int)
            and entry['positive_pixel_count'] > 0
            and entry.get('frame_sha256') and entry.get('evidence_id')):
        return False, 'zero_target_pixels_after_positive_camera_calibration'
    return None, 'zero_pixels_without_positive_camera_calibration'


def save_evaluator_capture(output, evidence, metadata, *, rgb_transport, calibration=None):
    """Write a separate evaluator sidecar; return nothing to inference/planning."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    record = dict(metadata) if isinstance(metadata, dict) else dict(schema=SCHEMA,
        synchronized=False, mapping_valid=False, mapping_status='missing_evaluator_payload')
    payload = record.pop('mask_npz_base64', None)
    raw = base64.b64decode(rgb_transport, validate=True)
    if record.get('rgb_transport_sha256') != hashlib.sha256(raw).hexdigest():
        record.update(synchronized=False, binding_error='RGB transport hash mismatch')
    if record.get('clock_after') != evidence.capture_time:
        record.update(synchronized=False, binding_error='Capture clock mismatch')
    if payload is not None:
        try:
            mask_bytes = base64.b64decode(payload, validate=True)
            if hashlib.sha256(mask_bytes).hexdigest() != record.get('mask_sha256'):
                raise ValueError('Evaluator mask hash mismatch')
        except (TypeError, ValueError) as exc:
            # An unusable evaluator label must not change online behavior.
            # Disk errors still propagate because the requested audit cannot
            # be saved, but malformed truth is recorded as unknown.
            record.update(mapping_valid=False, binding_error=str(exc))
        else:
            path = output / (evidence.id + '.npz')
            path.write_bytes(mask_bytes)
            record['mask_file'] = path.name
    else:
        record.update(mapping_valid=False, binding_error='Missing evaluator mask')
    present, reason = evaluate_presence(record, calibration, evidence.source)
    record.update(evidence_id=evidence.id, episode=evidence.episode,
                  generation=evidence.generation, source=evidence.source,
                  capture_time=evidence.capture_time, received_time=evidence.received_time,
                  frame_sha256=hashlib.sha256(Path(evidence.artifact).read_bytes()).hexdigest(),
                  frame_file=Path(evidence.artifact).name,
                  target_visible=present, presence_status=reason,
                  observable_posture=None,
                  posture_note='Requires independent RGB annotation; not inferred from simulation pose',
                  calibration=calibration)
    (output / (evidence.id + '.json')).write_text(json.dumps(record, indent=2) + '\n')


def install_comparison_evaluator_capture(namespace, *, target_prim='/World/Human'):
    """Attach once to existing render products, without replacing the monitor."""
    import omni.usd
    import omni.replicator.core as rep
    stage = omni.usd.get_context().get_stage()
    if stage is not namespace.get('monitor_stage'):
        raise RuntimeError('Evaluator requires the owned monitor stage')
    namespace['real2sim_navigation'].guard()
    sensors = namespace['real2sim_monitor_sensors']
    state = namespace.get('_comparison_evaluator_state')
    signature = (id(stage), target_prim, tuple((k, id(v[0])) for k, v in sensors.items()))
    if state and state['signature'] != signature:
        raise RuntimeError('Evaluator stage/product changed; revalidation required')
    if not state:
        annotators = {}
        for key, (product, _, _) in sensors.items():
            annotator = rep.AnnotatorRegistry.get_annotator(
                'instance_id_segmentation', init_params={'colorize': False})
            annotator.attach([product])
            annotators[key] = annotator
        state = dict(signature=signature, stage=stage, annotators=annotators)
        namespace['_comparison_evaluator_state'] = state

    def capture():
        if omni.usd.get_context().get_stage() is not stage:
            raise RuntimeError('Evaluator stage changed')
        namespace['real2sim_navigation'].guard()
        frames, evaluator = {}, {}
        # No await, update, timeline step or yield is permitted between these
        # reads. Copies prevent subsequent renderer updates changing the data.
        for key, (product, rgb, clock) in sensors.items():
            before = float(clock.get_data().get('simulationTime', -1))
            rgb_data = np.array(rgb.get_data(), copy=True)
            seg_data = state['annotators'][key].get_data()
            if isinstance(seg_data, dict):
                seg_data = dict(seg_data)
                seg_data['data'] = np.array(seg_data.get('data'), copy=True)
            after = float(clock.get_data().get('simulationTime', -1))
            frames[key], evaluator[key] = paired_payload(
                rgb_data, seg_data, clock_before=before, clock_after=after,
                stage_root=stage.GetRootLayer().realPath, target_prim=target_prim,
                target_exists=bool(stage.GetPrimAtPath(target_prim).IsValid()),
                render_product=getattr(product, 'path', str(product)))
        return dict(frames=frames, evaluator=evaluator,
                    snapshot=namespace['real2sim_navigation'].snapshot())

    namespace['comparison_evaluator_frames'] = capture
    return dict(schema=SCHEMA, cameras=list(sensors), target_prim=target_prim,
                stage_root=stage.GetRootLayer().realPath, installed=True)
