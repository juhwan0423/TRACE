# TRACE detector gate: held-out confirmation protocol

Pre-registered 2026-11-15 (Asia/Seoul), before any policy, Qwen or detector inference on
the conditions below. This file's SHA-256 is embedded in both frozen manifests. Nothing in
this file, the system, the thresholds or the analysis script may change after the first
held-out trial starts. Any later deviation is reported as a deviation, not folded in.

## 1. Why this run exists

The 2026-11-09 comparison (`artifacts/comparisons/20261109_scoped_limitations_01`) reused
the 20 conditions that had been used to diagnose and fix the system, so it is development
evidence. Its numbers (presence-unsupported posture claims OFF 3/20 vs ON 0/20; grounded
correct OFF 11/20 vs ON 13/20; mean wall time +38.5 s with the gate) are the hypotheses
this run tests on conditions the system has never seen.

## 2. System under test (frozen, unchanged)

- Code: the 2026-11-09 frozen source. The only differences in the current tree are the
  package rename `haiclaw` -> `tracebot` (2026-11-13) and one docstring line; verified by
  a file-by-file diff before freezing.
- Host rule `trace-context/2-scoped-limitations`; Qwen3-VL 8B, Ollama digest
  `9cf69da2b16d097f7def535917c4b55a95d6c7ee5700eb69ab86b01b3cfca487`; YOLO11n person gate
  `configs/person_gate_yolo11n_confirmatory060.json` (decision confidence 0.60, archive
  0.05, NMS 0.70, max_det 300).
- Runtime `configs/comparison_heldout_runtime_20261115.json`: byte-for-byte the same
  budgets, viewpoints, initial pose and retry rules as the 2026-11-08/09 runtime (300 s
  sim, 900 s wall, 12 actions, 45 s evidence age, view retry 2). Only the evaluator-only
  segmentation calibration was re-measured in the current simulator session.
- Arms: `agent_gate_off` vs `agent_gate_on`, the same matched pair as before.

## 3. Held-out conditions

- 20 new worker placements in the same reconstructed lab: 8 west, 8 entrance, 4
  off-catalog (no camera can see the worker). Each placement has a standing and a lying
  pose, giving 40 conditions, run as two frozen cohorts of 20
  (`configs/comparison_heldout_20261115_A.json`, `..._B.json`) because the frozen runner
  only accepts 20-condition confirmatory cohorts.
- Every placement is at least 0.2 m from every position used in the 2026-11-07
  development pilot, the 2026-11-08 cohort, the 2026-11-09 rerun and the demos. Standing
  body headings are new (90, 180 or -90 degrees; previous cohorts used only 0). Lying
  headings include three new ones (0, 90, 180); the previous heading (-90) is reused at
  new positions.
- New schedule seeds: 20261115 (A), 20261116 (B). Arm order is balanced by the frozen
  scheduler.
- Selection used only geometry and evaluator-only rendering, with the deterministic rule in
  `artifacts/heldout_preflight_20261115/select_conditions.py`: route clearance >= 0.4 m and
  sparse floor/collision rays; useful-view target pixels >= 5000, fixed-camera < 1000,
  other views < 1000; target mask not touching any image border (west lying may touch the
  bottom edge, the same cropped-feet allowance as 2026-11-08); off-catalog placements show
  zero target pixels in all three Spot views and the fixed camera; farthest-point spread
  from prior positions. A first pixel-only version was superseded after a visual check
  showed head-cropped close placements; this happened before any inference and is kept in
  the preflight folder.
- Limitation stated up front: same lab, same three viewpoints and camera catalog, one
  synthetic worker asset. This tests generalisation to unseen placements and headings, not
  to new environments.

## 4. Sample size and run

80 trials (40 conditions x 2 arms). At the 2026-11-09 pace (about 4.8 min per trial)
this is roughly 6.5 hours of simulation. If the OFF arm's unsupported-claim rate stays near
15% and the gate removes them, about 6 discordant pairs are expected, enough for the
primary one-sided test to reach p = 0.016. A smaller effect may not be detectable; that
will be reported as such.

Runs use the existing frozen runner (`scripts/run_real2sim_comparison.py freeze/run/
evaluate`). No trial is rerun silently. If infrastructure stops a cohort, the runner's
existing resume path continues the same frozen schedule and the stop is reported. No
outcome-based exclusion.

## 5. Outcomes and analysis (fixed)

All attempted trials stay in every denominator. Definitions are the existing
`src/tracebot/detector_gate_metrics.py` ones. The pooled analysis is
`artifacts/heldout_confirmation_20261115/analysis.py` (its SHA-256 is recorded in
`artifacts/heldout_confirmation_20261115/PREREGISTRATION_HASHES.json`); it was dry-run on
the 2026-11-09 development data only to check that it reproduces the published numbers.

- P1, primary: presence-unsupported posture assertion (a standing/lying answer whose cited
  frames contain zero verified target pixels). H1: ON < OFF. Exact one-sided sign test on
  discordant condition pairs across both cohorts, alpha 0.05. Sensitivity: the same test
  on placement clusters (sum over the two postures). P1 needs only segmentation, so it is
  final when the runs finish.
- S1: grounded correct within budget (right posture, cited frame contains the target and
  a blinded human rater reads the same posture, within sim and wall budgets). Two-sided
  exact McNemar; ON - OFF difference with a placement-cluster bootstrap 95% CI (10,000
  resamples, seed 20261115). Non-inferiority margin -0.10, declared here.
- S2: wall time per trial, paired ON - OFF mean with the same bootstrap; detector calls and
  latency, model calls and distance reported descriptively.
- Descriptive: unresolved, timeouts, errors, correct unknown handoff on the 8 unanswerable
  conditions, strata by posture and spatial family, per cohort and pooled.

Interpretation fixed in advance: P1 is "confirmed on held-out conditions" only if the
one-sided p < 0.05. Otherwise the gate's effect on unsupported claims is "not confirmed"
and the observed counts are reported. S1 improvement is claimed only if the CI excludes 0;
non-inferiority only if the CI lower bound is above -0.10; otherwise it is inconclusive.

## 6. Human annotation

Every cited frame with a target-present posture assertion gets one blinded label
(standing / lying / unreadable) from the same single rater as before, through
`tools/posture_annotation/server.py`, with policy, answer and truth hidden. Labels are not
inferred or copied from earlier frames. Until labelling finishes, S1 is reported as an
identification range, not a point estimate.

## 7. Verification levels

Live Isaac Sim 6.2 rendering + local Qwen3-VL + YOLO11n, closed loop in simulation. Not
real hardware, not physical falls (authored static poses), not ROS transport.
