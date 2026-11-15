# TRACE held-out confirmation: final results

Protocol: `reports/HELDOUT_CONFIRMATION_PROTOCOL_20261115.md` (unchanged). Runs 2026-11-15
15:50–22:35 KST, 80/80 trials recorded, no integrity markers, gate cleanup saved for both
cohorts. Analysis: `artifacts/heldout_confirmation_20261115/analysis.py` (hash unchanged) →
`results_P1_preannotation.json`.

## P1 (primary): presence-unsupported posture claims — CONFIRMED

| | gate OFF | gate ON |
|---|---|---|
| unsupported claims / attempted trials | 8/40 (20%) | 1/40 (2.5%) |

Discordant pairs OFF-only 7, ON-only 0, both 1. Exact one-sided sign test p = 0.0078
(pre-registered alpha 0.05). Placement-cluster sensitivity: 6 of 20 placements worse with
OFF, 0 worse with ON, p = 0.016. One unsupported ON claim remains.

## S2: cost

Mean wall time per trial OFF 232 s vs ON 344 s; paired ON−OFF +112 s, placement-cluster
bootstrap 95% CI [52, 171] s. Model calls 10.3 vs 14.7; distance 6.4 vs 10.4 m; detector
6.3 calls and 0.2 s per ON trial. The cost is mostly extra re-observation, not detector time.
This is larger than the development estimate (+38.5 s).

## Descriptive (not tests)

Posture assertions OFF 32 vs ON 18; unresolved answers 8 vs 22; timeouts 1 vs 4; errors
1 vs 0. Unanswerable conditions: correct unknown handoff 6/8 in both arms; inappropriate
posture assertion on unanswerable 1/8 vs 0/8. The gate answers less often, so S1 may go
either way.

## S1 (grounded correct): gate is WORSE — non-inferiority fails

Blinded labels: 41/41 cited frames labelled by the user (A 19, B 22; 28 standing, 13 lying,
0 unreadable, 0 prior exposure), frozen under `cohort_*/human_posture_review_20261115/
finalized_v1`. Every target-present posture claim in both arms matched the human reading.

| | gate OFF | gate ON |
|---|---|---|
| grounded correct within budget | 24/40 (60%) | 17/40 (42.5%) |

Pairs: OFF-only 8, ON-only 1, both 16, neither 15. Two-sided exact McNemar p = 0.039.
ON − OFF = −0.175, placement-cluster bootstrap 95% CI [−0.325, −0.05]. The pre-registered
non-inferiority margin (−0.10) is not met; the CI excludes 0 on the harmful side.

Descriptive (post hoc, not pre-registered): in the 8 pairs where only OFF was correct, ON
ended with an unknown answer every time; 6 of the 8 are entrance placements. Across those
ON trials the detector refused corroboration 68 times (64 `not_detected`, 4
`multiple_people`). The gate mostly costs answers by missing the real worker, not by
slowing the detector.

## Overall reading

On held-out placements the gate does what it was designed for (unsupported claims 8 → 1,
confirmed) but it also blocks valid evidence: grounded correct answers drop by 7 and each
trial takes about 112 s longer. The November 9 development hint (11 → 13) did not
replicate. The fair thesis claim is a confirmed safety/coverage trade-off, not an overall
improvement. Same lab, one synthetic worker, single human rater.
