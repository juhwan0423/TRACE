# Independent RGB person gate: implementation and development findings

Date: 2026-11-08 (Asia/Seoul). This completes the detector-gate implementation and saved-image integration stage. It does **not** report a new robot-policy comparison or a demonstrated TRACE advantage.

## Implemented behavior

- Both arms run the same original Qwen request on the entire RGB frame. The gate does not skip Qwen calls or change its prompt.
- The enabled gate runs a separate local YOLO11n detector on those same image bytes. Exactly one person candidate, bound to the same frame hash and evidence provenance, permits the original interpretation to continue. It never upgrades an uncertain or limited Qwen answer.
- Zero or multiple candidates, detector failure, mismatched evidence or timeout produce an effective unknown posture requiring another observation or handoff. Original Qwen output and effective interpretation are both saved. Existing standing-answer and lying-danger paths consume the effective interpretation.
- A rejected post-arrival observation releases the observation requirement, allowing another viewpoint. Planner feedback contains the gate status and reason, not model paths, image hashes or simulator truth.
- A detector-positive is not identity, posture or safety verification. Single false positives can pass; real people accompanied by false candidates can be rejected.

Code: [detector](../src/haiclaw/providers/person_detector.py), [gate](../src/haiclaw/providers/person_gate.py), [comparison runner](../scripts/run_real2sim_comparison.py), [offline evaluator](../src/haiclaw/detector_gate_metrics.py).

## Fixed development configuration

YOLO11n, confidence 0.25, image size 640, CPU, 10 s detector result timeout. Configuration was chosen before these detector outputs; it was not tuned to the five historical assertions. Ultralytics 8.3.221 and ultralytics-thop 2.0.18 were installed only in TRACE's existing `.venv`, without dependency upgrades. The 5,613,764-byte checkpoint came from [the official asset release](https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt).

Checkpoint SHA256: `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`.

Config: [person_gate_yolo11n.json](../configs/person_gate_yolo11n.json). Local artifact `artifacts/person_detector/models/provenance.json` records checkpoint provenance. Model/settings paths are project-local. No automatic model download or global settings write occurs during detection.

## Actual checks

| Check | Result | Interpretation |
| --- | --- | --- |
| All 61 unique archived RGB frames | 31 single candidate, 13 multiple candidates, 17 no candidate; zero execution errors | Detector operation on saved development images; no per-frame accuracy estimate |
| Detector wall time over those frames | First call approximately 0.699 s; subsequent-call median approximately 0.0252 s | CPU detector time only, not whole-agent latency |
| Five historical asserted-answer frames | Previously supported two each have one candidate; previously unsupported three each have multiple candidates | Prior labels are an unblinded assistant audit, not independent ground truth |
| Saved Qwen responses replayed through final gate | Two posture answers retained; three standing answers changed to unknown; five actual detector calls | No new Qwen calls or closed-loop actions; all frame hashes matched |
| Two fresh Spark Qwen calls on saved frames | Standing answer retained on first; second already returned uncertain/unknown and remained unknown | Actual model integration; the second call does not demonstrate a newly prevented hallucination |
| Full regression suite | 265 tests passed | Software, fixture and installed-USD checks; not perception performance |

**A person-positive rule alone would have passed all three old unsupported assertions.** The single-candidate rule rejects their multiple candidates, but this is ambiguity rejection, not correct recognition that the worker is absent. Inspection of the box overlay shows laboratory equipment receiving person detections. Do not turn this five-image development coincidence into a claim of 100% hallucination removal.

Saved outputs:

- `artifacts/person_detector/20261108_legacy_all_frames/results.json` and `runtime_provenance.json` — all 61 detections, source/config/model hashes and package versions.
- `artifacts/person_detector/20261108_legacy_assertions/results.json` and `detector_boxes.png` — five selected assertion frames and box overlay.
- `artifacts/person_detector/20261108_saved_qwen_gate_replay/results.json` and `run_replay.py` — final gate applied to the five stored Qwen interpretations, with source/frame/config hashes and replay limitations.
- `artifacts/person_detector/20261108_fresh_qwen_smoke/protocol.json` and `results.json` — two fresh calls, raw/effective interpretations and per-call cost. Qwen times were approximately 16.0 s and 50.9 s. Later wrapper timeout/malformed-response defenses were checked by regression tests, not a repeat of these fresh calls.

Original November 7 trial/image files were preserved. No new simulator rendering, robot movement, door modification or real hardware operation occurred in this implementation step.

## Run and compare

The normal harness remains gate-off unless explicitly enabled. With the usual simulator and Spark setup already ready:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_real2sim_harness.py \
  --camera-policy body-only --person-gate-config configs/person_gate_yolo11n.json
```

For a new cohort, use exactly `agent_gate_off` and `agent_gate_on` in the manifest and pass `--person-gate-config configs/person_gate_yolo11n.json` to `run_real2sim_comparison.py freeze`. Freeze records detector configuration, checkpoint hash and package versions. Live execution refuses changed dependencies or weights. Both arms keep the same planner and existing host rules; this estimates the additional gate's effect, not all of TRACE's effect.

The offline evaluator receives `support_annotations.json` separately, after execution. It distinguishes target presence from readable posture, retains unknown/failure in the denominator, and reports missing-annotation bounds rather than filling in success or zero error. Model request attempts and detector calls are counted separately. See the [protocol](DETECTOR_GATE_PROTOCOL.md) for exact metric definitions.

## Remaining work before quantitative claims

The proposed 20-condition/40-execution comparison has not been frozen or run. It still needs paired initial-state checks, a fixed door state, RGB-synchronous evaluator-only segmentation and independent image-based posture review. Existing scene preparation is not yet a demonstrated complete scene reset. Neither segmentation annotations nor a detector output may substitute for independent posture readability labels.

The native detector thread cannot be forcibly cancelled by an asyncio timeout. Late results are denied and further detector calls on that adapter are disabled, but a stuck native backend can delay process shutdown. Do not describe the timeout as a hard process-termination guarantee.

Validation command: `PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -q`. Gate tests include both answer/incident closure paths, unknown preservation, original-response preservation, evidence mismatches, malformed detector responses, cancellation/deadlines and moving after a veto.
