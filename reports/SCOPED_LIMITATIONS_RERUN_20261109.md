# TRACE scoped-limitations correction and paired rerun

Frozen before new policy inference, 2026-11-09.

The original rule rejected every nonempty observation_limitations list. Version
trace-context/2-scoped-limitations permits only whole clauses describing an
unseen face, rear-facing view, or low-angle view, when the model explicitly says
person_visible=yes, a known posture, and needs_more_observation=false. Unknown
or mixed caveats (including body/head occlusion, cropping, blur, multiple people)
still block. All original caveats remain in memory and audit records. This is a
conservative English phrase rule, not a learned verifier or proof of visibility.

The same helper governs ContextGraph claims, harness clear-subject status and
incident posture conversion. Report normalization uses the snapshot rule version;
legacy snapshots retain the original limitation behavior. Freshness, identity
binding, quality, conflict/revocation, detector veto, and absence coverage rules
remain in force. Standing never establishes overall safety.

## Execution

- Same 20 authored conditions, same paired order/seed, 40 trials, gate OFF/ON.
- Both arms get the host-rule correction; same Qwen checkpoint, prompt, detector
  threshold 0.60, camera catalog, motion and time/call budgets.
- Baseline artifacts: artifacts/comparisons/20261108_gate060_01, preserved.
- New output: artifacts/comparisons/20261109_scoped_limitations_01.
- Manifest: configs/comparison_scoped_limitations_20261109.json.
- Existing running simulation stage is retained, using the existing trial reset
  and capture/integrity controls. No hardware commands or scene replacement.
- This is a development rerun after diagnosing these conditions, not held-out
  confirmation. Report original and corrected results separately. Do not convert
  single-frame replay improvements into live success counts.

## Outcomes (unchanged definitions)

Grounded correct within budget; target-presence-unsupported posture assertions;
unknown handoffs/timeouts; wall time, distance and model calls. All 20 attempts
per arm remain in the denominator, including errors. Keep standing/lying and
answerable/unanswerable strata. Exact cited-frame posture labels are required
for positive-target assertions; previous frame labels cannot be copied onto new
images. Pending labels remain explicitly pending; segmentation is evaluator-only.

Stop on persistent integrity or cleanup failures. No mid-cohort tuning. Both
improvements and regressions will be reported. No performance conclusion yet.
