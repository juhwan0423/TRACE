# TRACE held-out preflight — 2026-11-15

Geometry/render-only preparation for `reports/HELDOUT_CONFIRMATION_PROTOCOL_20261115.md`.
No Qwen or detector call was made on any condition in this folder.

- Phase A (`screen_geometry*.py`): authored poses applied in the owned port-8227 session;
  skin AABB vs permitted corridors (>= 0.4 m) and 3x5 vertical raycasts (floor hit at every
  point; no non-human hit inside the actor's height). Sparse screen, not a full collision
  certificate.
- Phase B (`capture_views*.py`): evaluator-only target pixel counts and RGB from the
  entrance, west and door Spot viewpoints plus the fixed camera.
- Selection: `select_conditions.py` -> `selection.json`; montage `heldout_useful_views.png`
  (assistant visual check: all 32 answerable useful views show the worker fully in frame
  except west lying feet; two west placements are partly occluded by the shelf, kept by rule).
- Calibration: `paired_calibration/` (fixed 13,464 target px, body 5,724 px, absent 0).

Incident, kept for the record: the first phase-A pass also applied failing candidate poses
next to Spot's west stance; a lying pose overlapped Spot and tipped it over ("Spot tilted
beyond 45 degrees"). The first west render pass therefore ran from the wrong position and
is kept as `INVALID_*`. Spot was recovered with the standard `reset_to_entrance()` (the same
call the runner makes before every trial), the closed-door control was re-applied and
verified, and all phase-B views were re-rendered. Later screens only applied poses far from
Spot. Superseded pixel-only selection v1 is kept as `superseded_*`.
