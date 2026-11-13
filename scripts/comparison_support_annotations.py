"""Join evaluator-only instance masks to the exact frames cited by a claim.

This derives target presence only. RGB-readable posture remains unannotated.
Human support_annotations.json is neither read nor changed by this module.
"""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from comparison_evaluator_capture import SCHEMA, _mapping_info, evaluate_presence


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identity(value):
    return (value.get('id', value.get('evidence_id')), value.get('episode'),
            value.get('generation', 0), value.get('source'),
            value.get('capture_time'), value.get('received_time'))


def _valid_name(value):
    return isinstance(value, str) and value not in ('', '.', '..') and Path(value).name == value


def _frame_support(trial, evidence_id, evidence, report):
    result = dict(evidence_id=evidence_id, target_present=None, issues=[])
    try:
        if not _valid_name(evidence_id):
            raise ValueError('invalid evidence reference')
        if evidence is None:
            raise ValueError('claimed frame absent from captured evidence')
        if evidence.get('episode') != report.get('episode'):
            raise ValueError('captured evidence belongs to another episode')
        sidecar_path = trial/'evaluator'/(evidence_id+'.json')
        sidecar = json.loads(sidecar_path.read_text())
        if sidecar.get('schema') != SCHEMA or _identity(sidecar) != _identity(evidence):
            raise ValueError('sidecar/evidence identity mismatch')
        frame = Path(evidence['artifact']).resolve()
        if frame.parent != (trial/'frames').resolve() or not frame.is_file():
            raise ValueError('claimed RGB is outside the trial frame directory or missing')
        if frame.name != sidecar.get('frame_file') or _sha(frame) != sidecar.get('frame_sha256'):
            raise ValueError('RGB frame hash or filename mismatch')
        mask_name = sidecar.get('mask_file')
        if not _valid_name(mask_name):
            raise ValueError('missing or invalid mask filename')
        mask_path = trial/'evaluator'/mask_name
        if mask_path.resolve().parent != (trial/'evaluator').resolve():
            raise ValueError('mask is outside evaluator directory')
        if _sha(mask_path) != sidecar.get('mask_sha256'):
            raise ValueError('instance mask hash mismatch')
        with np.load(mask_path, allow_pickle=False) as archive:
            mask = archive['instance_ids']
        with Image.open(frame) as image:
            width, height = image.size
        if (mask.shape != (height, width) or mask.dtype != np.uint32
                or (sidecar.get('width'), sidecar.get('height')) != (width, height)):
            raise ValueError('RGB/mask shape or dtype mismatch')
        target = sidecar.get('target_prim')
        if not isinstance(target, str) or not target.startswith('/'):
            raise ValueError('invalid target prim')
        _, ids, valid_mapping, status = _mapping_info(sidecar.get('id_to_labels'), mask, target)
        if not valid_mapping or not sidecar.get('mapping_valid'):
            raise ValueError('invalid instance mapping: '+status)
        count = int(np.isin(mask, ids).sum()) if ids else 0
        if count != sidecar.get('target_pixel_count') or set(ids) != set(sidecar.get('target_ids', [])):
            raise ValueError('stored target pixel summary disagrees with mask mapping')
        before, after = sidecar.get('clock_before'), sidecar.get('clock_after')
        if (type(before) not in (int, float) or type(after) not in (int, float)
                or not math.isfinite(before) or before < 0 or before != after
                or after != evidence.get('capture_time')):
            raise ValueError('unverified RGB/mask clock binding')
        visible, reason = evaluate_presence(sidecar, sidecar.get('calibration'), evidence['source'])
        if visible is not sidecar.get('target_visible'):
            raise ValueError('stored target visibility disagrees with recomputation')
        result.update(target_present=visible, presence_status=reason,
                      frame_sha256=sidecar['frame_sha256'], mask_sha256=sidecar['mask_sha256'],
                      target_pixel_count=count)
        if visible is None:
            result['issues'].append(reason)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result['issues'].append(str(exc))
    return result


def build_support(out, records):
    """Return per-trial presence annotations; no files or online state mutated."""
    out = Path(out)
    annotations = {}
    for row in records:
        trial_id = row.get('trial_id')
        if not _valid_name(trial_id) or trial_id in annotations:
            raise ValueError('invalid or duplicate trial_id')
        refs = row.get('normalization', {}).get('answer_evidence_ids', [])
        if not isinstance(refs, list) or len(set(refs)) != len(refs):
            raise ValueError('invalid or duplicate claimed evidence references')
        annotation = dict(evidence_ids=list(refs), claim_target_present=None,
                          claim_observed_posture=None, source='paired_simulator_segmentation',
                          frame_results=[], issues=[],
                          limitation='Presence is simulator target visibility; posture needs independent RGB review')
        annotations[trial_id] = annotation
        trial = out/'trials'/trial_id
        try:
            report = json.loads((trial/'result.json').read_text())
        except (OSError, ValueError) as exc:
            annotation['issues'].append('Missing/unreadable trial report: '+str(exc))
            continue
        evidence_by_id = {}
        conflicts = set()
        all_evidence = list(report.get('captured_evidence', []))
        all_evidence += [entry.get('evidence', {}) for entry in report.get('evidence_records', [])]
        for evidence in all_evidence:
            eid = evidence.get('id')
            if eid in evidence_by_id and evidence_by_id[eid] != evidence:
                conflicts.add(eid)
            evidence_by_id[eid] = evidence
        for ref in refs:
            if ref in conflicts:
                frame = dict(evidence_id=ref, target_present=None,
                             issues=['conflicting captured evidence records'])
            else:
                frame = _frame_support(trial, ref, evidence_by_id.get(ref), report)
            annotation['frame_results'].append(frame)
            annotation['issues'].extend(ref+': '+issue for issue in frame['issues'])
        values = [frame['target_present'] for frame in annotation['frame_results']]
        if any(value is True for value in values):
            annotation['claim_target_present'] = True
        elif values and all(value is False for value in values):
            annotation['claim_target_present'] = False
        elif not refs:
            annotation['issues'].append('No cited frames; no segmentation annotation assigned')
    return annotations
