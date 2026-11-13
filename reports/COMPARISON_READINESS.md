# TRACE comparison readiness — 2026-11-07

Read-only readiness inspection at approximately 19:08 KST. No simulator, model server, tunnel, navigation, worker-pose change, package installation, or download was started. The pre-existing user modification in `scripts/run_real2sim_harness.py` was preserved.

## Current execution status

- Local ports 8226/8227 and 11434/11435 were closed. No Isaac/Real2Sim/Ollama/tunnel process was found, so there was no live stage to inspect or preserve remotely.
- `curl --max-time 5 http://127.0.0.1:11435/api/tags` failed with connection refused.
- Tailscale was Running and this PC online, but `spark-0a58` / `100.73.59.16` was offline, last seen `2026-11-07T08:10:00.1Z`. Read-only SSH with BatchMode, existing host-key verification, and a five-second timeout also timed out.
- RTX 5090: 32,607 MiB total, 30,015 MiB free at inspection. No compute process was listed. This is pre-launch capacity, not proof that simultaneous rendering and model inference will fit.
- The existing Isaac Python environment, Real2Sim preview launcher, scene, patrol plan, and all 12 required NAS-manifest files exist. No asset download is currently indicated.
- A local x86-64 Ollama binary and Qwen3-VL 8B model are already cached. All six referenced blobs exist with the manifest-specified sizes (6,190,972,820 total bytes). Manifest SHA256: `7281ceccb1fb1cc8d83aa98aed0887d87de1e9b886527b0763edc060fbd075b0`. This verifies cache presence and sizes, not inference success or full blob hashes.

Machine-readable checks: `artifacts/trace_comparison_readiness/initial_status.json` and `local_model_cache.json`.

## Existing scene and observation candidates

The existing A* corridor defines these targets. Candidate coordinates are not arbitrary straight-line goals.

| Target | Corridor index | XY metres | Final yaw used by agent | Evidence status |
|---|---:|---|---:|---|
| entrance | 0 | (-1.12, 3.32) | -1.570796 | Existing arrival/standing observation and occluded-worker starting view |
| west | 7 | (-5.62, 1.62) | -1.570796 | Existing actual locomotion and visible-lying confirmation |
| door | 21 | (-0.92, 1.52) | -2.0 | Existing actual locomotion and original standing-worker observation |
| cage | 18 | (-1.32, -0.63) | legacy | Excluded from agent catalog after prior stance/visibility failure; do not reintroduce without calibration |

Historical rendered geometry evidence, not newly executed checks:

- Standing worker at bounding-box anchor `[-1.05,-0.45,0.03]`, rotation `[0,0,0]`: fixed camera 6,136 human pixels and entrance body camera 2,644 pixels (`artifacts/worker_scenario/visible/capture.json`).
- Lying worker at anchor `[-5.5,-0.3,0.03]`, rotation `[0,90,90]`: fixed and entrance body cameras both zero human pixels (`end-to-end-hidden/capture.json`); west body camera 6,860 pixels (`end-to-end-west/capture.json`). Skin pose and colliders were transformed together. This is an authored static pose, not physical falling.
- The same hidden anchor with standing rotation is implemented as a demo option but does not yet have equivalent geometric/live-validation evidence. Its greater height could change fixed-camera visibility. A second hidden-worker layout and an unresolvable condition also remain calibration tasks; no unsupported coverage claim is made here.

## Safe APIs and exact next commands

After root coordinates exclusive stage/GPU ownership, the established local scene launcher is:

```bash
cd /home/jude/Documents/ChatGPT/ROSCLAW/TRACE
bash scripts/start_trace_real2sim_5090.sh
```

It refuses/reuses an occupied 8227 rather than silently replacing another stage. The preview checks `/real2sim/workspace` and the exact root layer. Monitor/navigation attachment creates runtime session-layer state and starts the robot; it is a mutation and was **not** executed during this inspection.

Use `scripts/env_5090.sh` on this x86-64 PC. `scripts/env_spark.sh` contains an ARM-specific preload and is not the correct local launch environment.

For the original inference deployment, once Spark is online:

```bash
bash scripts/start_spark_tunnel.sh
curl --max-time 5 http://127.0.0.1:11435/api/tags
```

Alternatively, root may explicitly choose the already-cached local model for the entire new comparison:

```bash
bash scripts/start_ollama_5090.sh
curl --max-time 5 http://127.0.0.1:11434/api/tags
```

The existing VLM config targets port 11435; a separate comparison config would need port 11434. Preserve the old config, freeze the chosen deployment before comparisons, and do not compare local wall latency directly with historical Spark runs. A real image/schema inference and simultaneous GPU-memory check remain necessary.

Read-only live requests, once the server is ready, use `real2sim_control.request` in the `real2sim` context:

- `real2sim_navigation.snapshot()` for pose/status/time and `real2sim_navigation.guard()` for stage ownership.
- `real2sim_monitor_frames()` reads the existing three RGB annotators and capture timestamps. It does not issue navigation or explicit timeline steps.
- The installed remote skill's `health_check.py` checks version, stage and timeline without resetting them.

After separately coordinated scene calibration, `real2sim_navigation.navigate(target, request_id, final_yaw)` executes only validated corridor targets; `stop(request_id=...)` cancels only the caller's motion. Worker `apply(...)`/`restore()` use a removable session layer and reject changes while Spot is moving. `scripts/real2sim_worker.py capture --measure` attaches evaluator-only segmentation and waits for fresh frames; it must not be described as a purely passive read, and segmentation/worker truth must never enter planner inputs.

## Validation scope and applied instructions

Read project `AGENTS.md` and `implementation_guide.md`; installed Isaac `AGENTS.md` and `skills/SKILLS.md`; `isaac-sim-remote` plus Python-server workflows, `isaac-sim-sensor`, `isaac-camera`, and `isaac-sim-validator`. This inspection is filesystem/process/network readiness plus review of historical rendered evidence. No fresh Isaac rendering, locomotion, model inference, geometry calibration, or comparative performance was validated.


## Authorized live launch and calibration update

Root subsequently authorized a new owned local Real2Sim process. The earlier read-only status above is historical. Spark port **11435** was restored and its `/api/tags` response lists `qwen3-vl:8b`. Root explicitly chose Spark only; the local-cache alternative above was **not used**. No VLM inference or comparison-policy call was made by this readiness task.

- Owned Isaac PID: **3461047**; Python server: `127.0.0.1:8227`, context `real2sim`; version 6.2. Existing preview launcher, scene, 12 cached assets and corridor were reused. No packages or assets downloaded; no TRACE desktop app launched.
- Exact launcher: after `source scripts/env_5090.sh`, `python ../HAI-Real2Sim/lab_west/reproduce/preview_isaacsim620.py --python "$ISAAC_LAB_DIR/.venv/bin/python"`. Logs are `artifacts/trace_comparison_readiness/launch.log` and the sibling HAI-Real2Sim `artifacts/preview_isaacsim620_8227/{server.log,kit.log,server.pid}`.
- Attached the existing `scripts/real2sim_monitor_scene.py` and `scripts/real2sim_navigation.py` through the installed `isaacsim_send.py --port 8227 --context real2sim`. Robot ready, playing, and actual corridor navigation to west/door/entrance succeeded. Navigation remains closed-loop locomotion; camera poses follow measured robot pose.
- `artifacts/trace_comparison_readiness/runtime_provenance.json` records loaded-source hashes, stage/patrol paths and hashes, all 12 asset hashes, camera settings, runtime revision and attachment times. Matching remote global: `trace_comparison_runtime_provenance`. Navigation, monitor, worker source and original root USD hashes still match the prelaunch snapshot. No robot/source reload was performed.
- Runtime revision: `corridor-stance-wide-view/2`. Fixed camera remains 640×360/focal11; body camera 640×360/focal8. The proposed comparison door endpoint uses commanded yaw **2.9 radians**, which differs from historical door yaw−2. All comparison policies must share one frozen catalog; this calibration does not silently change the existing harness catalog.

Calibration uses only a removable worker scenario layer and authored static skinned poses with corresponding capsules. These are not physically simulated falls. Captures include evaluator-only human segmentation; those pixels and worker truth must never enter the agent's observation or decision inputs. Presence counts demonstrate visibility, not VLM answerability.

Initial west and north lying candidates had possible equipment intrusion near their extremities, revealed by downward physics rays, and were rejected for this comparison. Final adjusted anchors use the same floor/scene, with a 5×5 ray grid over each lying footprint returning the floor at z=0. This is a sampled geometric sanity check, not exhaustive mesh nonpenetration certification. Original and rejected captures remain preserved.


### Retained calibration failure

The adjusted north lying footprint intersects the existing north corridor. An entrance→west traversal failed at approximately `[-2.373,2.207]` with `No progress or goal deadline exceeded`; see `navigation_west_a3d4fcab.json`. This is a real navigation/scene condition, not a successful arrival. A following shell command continued after that failure; its `west_adjusted_lying_reversed` capture was therefore taken from the wrong location, is marked `INVALID.json`, and is excluded from geometry evidence. The failure and capture are preserved. The actor was already moved off the corridor before an explicitly logged Spot-only reset to entrance (`explicit_reset_after_route_obstruction.json`); no stage/controller reload or silent retry was used. The north-lying case must be labeled as a possible route-obstruction control, or excluded from a clean-view comparison. Its entrance body image contains only a clipped head/vest at the right edge; a segmentation count alone cannot establish answerability.


### Final bounded calibration and handoff

Five development scenarios were accepted before any Qwen policy call; exact requested schema is in `artifacts/trace_comparison_readiness/accepted_scenarios.json`. They form **three independent spatial groups**, not five independent scenes. All captures and measured poses are in `geometry_manifest.json`.

| Scenario | Anchor metres | Rotation degrees | Fixed human pixels | Entrance body | West body | Door body | Scope |
|---|---|---|---:|---:|---:|---:|---|
| west_lying | [-5.3, 0.2, 0.03] | [0, 90, -90] | 0 | 0 | 8649 | 0 | development visible posture |
| west_standing | [-5.3, 0.2, 0.03] | [0, 0, 0] | 185 | 0 | 25216 | 0 | development visible posture |
| north_standing | [-3, 2.1, 0.03] | [0, 0, 0] | 0 | 0 | 0 | 9257 | development visible posture |
| offcatalog_lying | [3, 1.5, 0.03] | [0, 90, 90] | 0 | 0 | 0 | 0 | coverage-limited unknown |
| offcatalog_standing | [3, 1.5, 0.03] | [0, 0, 0] | 0 | 0 | 0 | 0 | coverage-limited unknown |

The valid west-lying capture is `west_adjusted_lying_reversed_valid/body.png`, obtained after actual arrived-west navigation. Root independently reviewed its near-horizontal legs/trunk/vest and accepted it as development-answerable with cropped-feet/no-face limitations. The prior wrong-location capture remains excluded. North lying is excluded entirely from the clean comparison because it obstructed the route and the entrance view was heavily clipped. Both off-catalog postures were rendered at all three actual robot viewpoints, with zero human pixels in every allowed camera. These are coverage-limited unknown controls, not a disappearance detector evaluation.

Handoff preserves the live process, playing at door (commanded yaw2.9), with the actor standing at `[3,1.5,0.03]`. `handoff.json` records actual pose and runtime. Root may now own sequential scene/policy operations. No Qwen inference, shared navigation/monitor/harness edit, physical hardware action, stage reload, asset change or local-model fallback was performed by this task.


## Frozen-pilot door-phase review

A later read-only source audit during the development pilot found an uncontrolled dynamic background: `/World/UAMDoor/Door` is the UAM cage gate, not the navigation target named `door`. Its hinge is at `[-1.772,-1.336,0.2]`, width1.05m and height1.85m. `door_driver.py:18–33` interpolates and writes its angular drive target on each preview update. The authored schedule opens from0° at21.3s to95° at23.5s, staysopen until36.6s, and closes by38.4s. The preview loops over1384frames/30fps≈46.133s (`labwest_preview_isaacsim620.py:34–57`; sceneUSD:19–34). Physical gate angle can lag the target.

`run_real2sim_comparison.py:212–242` resets Spot, settles6simulationseconds and applies staticworkerframe0; it does not reset timeline phase or physical door pose/velocity. Thus fixed-CCTV/entrance-body backgrounds are not pair-matched across policies. Randomized order does not by itself remove this small-pilot nuisance. Its effect on decisions has not been measured, so no measured advantage/disadvantage is claimed.

The gate does not geometrically block the nominal allowed entrance/west/door shortest routes: those centerlines stay at least2.980m from the hinge, or1.880m beyond a conservative1.1m sweepdisk. This bound excludes forbidden cage/fullpatrol routes and arbitrary robot drift. Fixed CCTV and entrance body view the cage; doorbodyyaw2.9 points away. This finding is therefore a background/state-repeatability limitation, not evidence that the allowed route is invalid.

Keep the running pilot and its frozen settings unchanged, report it as development, and do not claim fullscene-reset equivalence. For the next cohort, the simplest control is a predefined staticclosed gate with explicit target/actualpose/angularvelocity reset and verified settling. Alternatively predeclare balanced initial phases and reset/log actual hinge state at trialstart and every capture. A timeline seek alone does not reset a driven rigid body. Do not infer phase from `SimulationManager.now %46.133` without proving those clocks coincide. Detailed evidence and scope: `artifacts/trace_comparison_readiness/door_phase_review.json`.


## North-standing route qualification after frozen pilot t0000

The prior calibration arrival is verified: northstanding was applied/captured atsim282.386, west→door navigation began282.420 and arrived315.100, with the identical worker pose still present in the door capture at320.586. However, its trajectory already hesitated around `[-3.48,1.89]` for approximately6simulationseconds, then passed farther south at y≈1.65. Therefore a single arrival was insufficient to establish robust route reachability.

Frozen development trialt0000 subsequently failed at essentially the same hotspot (`[-3.47418,1.87045]`, no-progress). The nominal route y=1.82 is only0.0195m below the worker's visual bbox ymin1.8395; this point-path gap does not provide Spot-body clearance. The human has enabled kinematic capsule colliders and no Spot filter (`human_collider.py:16–20,63–69,86–91`; `real2sim_worker_scene.py:119–133`). These facts support probable worker/path interference, but there are no contact-pair/force records, so the exact counterpart is not proven and controller/contact sensitivity remains unresolved.

Keep every frozen-v1 trial and its denominator. Treat northstanding as a development condition confounded by reachability, not an observer-only comparison; do not retrospectively remove its failed run or change its pose. Before a new cohort, test full-body swept clearance and repeated traversal in both directions, with recorded contact/reset state, independently of Qwen outcomes. Details: `artifacts/trace_comparison_readiness/north_standing_route_review.json`. No running scene or frozen experimental file was changed for this audit.


## Prepared next-cohort gate control — not applied to v1

New file `scripts/comparison_gate_control.py` defines `ComparisonGateControl` without applying it on import/exec. The installed 6.2 `physics-simulation` skill and local experimental `RigidPrim`/backend source were checked. Actual readback uses `use_backend("tensor", raise_on_unsupported=True, raise_on_fallback=True)`, `get_world_poses()` and `get_velocities()`. This deliberately avoids using `DoorDriver.angle_deg()` or authored USD velocities as proof of physical settling.

After the current cohort ends, and only in a stationary owned scene with a clear gate sweep, the explicit remote-context sequence is:

```python
exec(gate_source)  # exact contents of scripts/comparison_gate_control.py
trace_gate_control = ComparisonGateControl(door, real2sim_navigation)
trace_gate_control.apply_closed()
# Let the existing simulation advance and poll with a finite external timeout:
trace_gate_control.verify_closed()
# Before resuming the original animated scene:
trace_gate_control.restore()
```

`apply_closed()` saves and zeros only the in-memory DoorDriver schedule and asks the existing joint drive to close. It does not teleport or force zero velocities; physical state must converge. `verify_closed()` requires orientation error≤0.5°, hinge-position error≤3mm, linear speed≤0.005m/s, angular speed≤0.01rad/s and target≤0.01°, continuously for≥0.5simulationseconds across≥3 distinct samples. These are new-cohort proposed tolerances, not measured success. Duplicate timestamps cannot establish readiness. Invalid tensors, rewound clocks, changed stages or competing schedule owners fail explicitly.

`restore()` reinstates the saved schedule at the current timeline phase. It restores the driving behavior, not a past physical state. The helper neither steps nor seeks the timeline, saves assets, changes navigation, or retries automatically. Constructing the wrapper can ensure PhysxRigidBodyAPI in the session layer; this and the actual tensor binding still require a bounded live integration test after v1. Python syntax plus eight fixture checks passed (`gate_control_static_checks.json`); **no live Isaac call or current-v1 mutation was performed**.

Original north-standing candidate `[-3,2.5,0.03]`, rotation`[0,0,0]`: door camera has9,516human pixels, fixed0; original entrance body0. Evidence: `door_north2_standing/capture.json` and `entrance_north2_standing/capture.json`. There is no west-body capture or reliable route proof with this pose retained. It remains a candidate requiring full-body/capsule clearance and repeated bidirectional traversal before acceptance; it is not added to frozen v1. Details: `next_cohort_north_candidate.json`.


## Post-v1 live gate diagnostic: physical closure failed

After all10 frozen trials completed and root released the stage, `gate_validation_v1/run.py` acquired the same runner lock. Cleanup had restored the original animated worker near the gate, so the first clearance check failed. Root then explicitly authorized temporary off-catalog standing placement `[3,1.5,0.03]` for this diagnostic only. The controller/session backup was saved first; the rechecked human-capsule clearance to the conservative gate sweep was4.160m. Spot remained arrived and stationary at entrance; no navigation or cohort was started.

The new helper bound successfully to live physics tensors. `apply_closed()` kept target0, but none of172 samples across28.684simulationseconds passed the unchanged tolerance gate before the60wallsecond deadline. Actual orientation error stayed45.404–45.490° and hinge-origin error0.134–0.138m. This is a substantial physical closure failure, not a threshold issue. The pre-binding `session_before.usda` already contains a similarly displaced gate and large physical velocity values, so no new helper API fault was demonstrated; the underlying physical cause is not isolated.

Original schedule arrays were restored exactly. Across a further bounded60wallseconds, targets ranged0–90.333° and matched the original schedule at sampled phases within0.0000026°. Physical orientation changed only≈0.086°, so normal opening motion was **not** verified. Do not treat this helper as a validated physical scene fix or infer that the source schedule implies large actual motion in v1.

Finally, the original actor animation was restored; the scenario layer is inactive, original session sublayers are unchanged, gate ownership is released, and the helper instance was discarded. The wrapper's sole added `PhysxRigidBodyAPI` session metadata was explicitly removed, returning the effective door schemas to their saved state. Frozen source/asset hashes remain identical. All failures are retained in `gate_validation_v1/`; `summary.json` records measurements and `final_handoff.json` records restored ownership/state. The scene remains live, playing, with Spot arrived at entrance; the runner lock is released. No frozen-v1 files, source gate assets, constraints or tolerances were changed.
