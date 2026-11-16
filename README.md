# TRACE

[![CPU contracts](https://github.com/juhwan0423/TRACE/actions/workflows/tests.yml/badge.svg)](https://github.com/juhwan0423/TRACE/actions/workflows/tests.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776ab)
![Isaac Sim 6.2](https://img.shields.io/badge/Isaac%20Sim-6.2-76b900)
![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)

**Task-Relevant Active Context and Evidence.** A robot inspection agent that has to show the camera frame behind each answer.

| | |
|---|---|
| Built | A Spot robot in a digital twin of our lab checks on a worker when an operator asks. A local vision-language model chooses where to look and when to move; the host validates every action and records the camera frame behind each answer. The same stack now streams live camera and telemetry from a real Unitree Go2. |
| Stack | Isaac Sim 6.2, Python `asyncio`, Qwen3-VL 8B on Ollama, YOLO11n, Unitree Go2 with Jetson and RealSense. Simulation on an RTX 5090 PC, model inference on a DGX Spark, linked over Tailscale. |
| Result | In a pre-registered test on 40 unseen conditions, a person-detector check cut answers not supported by their cited frame from 8 to 1 (p = 0.008), trading some coverage for reliability. |

https://github.com/user-attachments/assets/79563b4e-c37d-407b-aeb1-a65cc7d94959

*One four-minute simulated inspection, replayed from its records at 34.5 s. [Video file](docs/assets/trace_demo_monitor_en.mp4).*

## From simulation to a real robot

| **Simulation · Spot in Isaac Sim** | **Real robot · Unitree Go2 with Jetson** |
|---|---|
| Model-directed inspection with evidence checks in a digital twin of the lab | Live RealSense video, Go2 telemetry and Qwen3-VL scene descriptions |
| Evaluated in the results below | Observation pipeline running; motion control in progress |

![TRACE Go2 workspace: robot camera, CCTV view and Qwen3-VL panel](docs/assets/go2-real-workspace.png)

*Go2 workspace: the robot's RealSense view, a CCTV view of the lab and the Qwen3-VL description panel (composited for presentation). Setup and run commands: [Go2 live monitor](docs/go2-live-monitor.md).*

## System

![TRACE system overview](docs/assets/system-overview.svg)

The harness sits between the model and the robot. The model only sees camera frames and the questions still open, and it replies with one tool call. The harness checks that call against the allowed tools, named viewpoints and budgets before anything moves. Scene reconstruction comes from [HAI-Real2Sim](https://github.com/sayhee-kim/HAI-Real2Sim).

## How an inspection runs

An operator asks the robot to check a worker. The model can observe a camera, inspect a named viewpoint, wait, stop, or hand off a request it cannot resolve. Each observation carries its source, capture time and frame reference. The host rejects stale or unrelated evidence and enforces movement, tool-call and time budgets.

Presence and visible posture are separate questions, so finding a person does not make the workplace safe. The model cannot assign a safety verdict or send arbitrary coordinates to the robot.

```mermaid
flowchart LR
  Request[Operator request] --> Context[Questions and evidence]
  Context --> Planner[Local Qwen planner]
  Planner --> Guard[Validate tool and target]
  Guard --> Tools[Observe / inspect / wait / stop]
  Tools --> Sim[HAI-Real2Sim + Spot]
  Sim --> Context
  Context --> Host[Freshness, deadlines and resolution]
  Host --> Result[Inspection answer or unresolved handoff]
```

![Spot body-camera frame during a worker inspection](docs/assets/spot-inspection.png)

*Body-camera frame from a development run. Spot follows configured corridors with Isaac Sim's locomotion policy.*

## Results

All results below are from simulation in the reconstructed lab.

| What was checked | Result |
|---|---|
| Spot patrol in the reconstructed lab | 23/23 waypoints, with movement cancellation and entrance arrival exercised |
| Model-directed inspection, live Isaac + Qwen | Runs end in an inspection answer or an explicit unresolved handoff |
| Software contracts | 330 CPU tests, no GPU or model needed, CI on Python 3.11 and 3.12 |
| Person-detector gate OFF vs ON, 40 held-out conditions per arm | Tables below |

### Does the cited frame support the answer?

A posture label can be right while the cited frame does not show the worker. An answer therefore counts only if it is correct and its cited frame contains the target. Both arms use the same Qwen planner, prompts, tools and budgets. The ON arm adds a YOLO11n person-detector veto at confidence 0.60.

| November 15 held-out confirmation, 40 runs per arm | Gate OFF | Gate ON |
|---|---:|---:|
| Posture asserted with the target absent from the frame (primary outcome) | 8/40 | 1/40 |
| Correct and supported by the cited frame | 24/40 | 17/40 |
| Handoff in the eight unanswerable conditions | 6/8 | 6/8 |
| Mean wall time | 232 s | 344 s |

The 40 conditions are 20 worker placements that appear in no earlier run, each with a standing and a lying pose. The protocol, analysis script and condition lists were fixed and hashed before the first run, and the system was the frozen November 9 version.

- Unsupported posture claims fell from 8 to 1 (one-sided exact sign test, p = 0.0078).
- The gate is conservative. Correct, frame-backed answers went from 24 to 17 (p = 0.039), mostly where the detector missed the worker and the robot handed off instead of answering. Runs took about 112 s longer, from extra re-observation.
- Scope: one reconstructed lab, one synthetic worker, authored standing and lying poses.

### Reports

| Date | Topic | Document |
|---|---|---|
| Oct 27 | Integration runs and setup | [RTX 5090 setup](reports/RTX5090_SETUP.md), [work log](reports/WORKLOG.md) |
| Nov 7 | Pilot against fixed-order verification | [findings](reports/COMPARISON_FINDINGS_20261107.md), [protocol](reports/COMPARISON_PROTOCOL.md), [metrics](reports/COMPARISON_METRICS.md) |
| Nov 8 | Detector gate and human audit of 61 frames | [findings](reports/DETECTOR_GATE_FINDINGS_20261108.md), [human audit](reports/PERSON_DETECTOR_HUMAN_AUDIT_20261108.md), [protocol](reports/DETECTOR_GATE_PROTOCOL.md) |
| Nov 8 | First 40-run cohort | [pre-registered plan](reports/DETECTOR_GATE_COHORT_20261108.md) |
| Nov 9 | Host-rule fix and paired rerun | [rerun protocol](reports/SCOPED_LIMITATIONS_RERUN_20261109.md) |
| Nov 11 | Result figures and number sources | [presentation outline](reports/KSME_2026_SLIDE_CONTENTS_V2.md), [slide assets](artifacts/ksme_slide_package_20261111/) |
| Nov 15 | Held-out confirmation of the detector gate | [pre-registered protocol](reports/HELDOUT_CONFIRMATION_PROTOCOL_20261115.md), [results](reports/HELDOUT_CONFIRMATION_RESULTS_20261115.md), [analysis script and outputs](artifacts/heldout_confirmation_20261115/) |

Raw frames and per-run records stay local under `artifacts/comparisons/`. The runner is [run_real2sim_comparison.py](scripts/run_real2sim_comparison.py). It refuses to overwrite earlier runs or to continue a cohort after the source or model changes.

## Try the core without a simulator

```bash
git clone https://github.com/juhwan0423/TRACE.git
cd TRACE
PYTHONPATH=src python3 -B -m unittest discover -s tests -v
python3 scripts/run_harness.py --mode fixture --planner fixture --fail-first
python3 scripts/demo_context_resolution.py
```

The fixture exercises failure handling and context resolution without a GPU or model. It needs Python 3.11 or newer, and some tests need `numpy` and `pillow`.

## Run with Real2Sim

Scene assets, the Isaac Sim environment and the model endpoint are not in this repository. [RTX 5090 setup](reports/RTX5090_SETUP.md) describes them. The launch scripts target the development workstation, so check the paths before using another machine.

```bash
bash scripts/start_spark_tunnel.sh <Spark-Tailscale-IP>
bash scripts/start_trace_real2sim_5090.sh
```

The desktop monitor's **agent execution** tab starts and stops the harness. For a terminal run, after the monitor reports that Spot is ready:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_real2sim_harness.py --camera-policy body-only
```

Each run saves events, images, a result and a source/configuration snapshot under `artifacts/harness/`. A run can finish by handing off uncertainty, so `completed=true` alone does not mean a successful safety assessment.

For the **visible → occluded worker → Spot inspection** scenario, with the monitor and Spark tunnel already running:

```bash
PYTHONPATH=src .venv/bin/python scripts/demo_real2sim_occlusion.py
```

The scenario changes the scene through reversible runtime overrides. See the [scenario instructions and validation limits](reports/OCCLUDED_WORKER_SCENARIO.md).

## Code

The Python package is `tracebot`.

| Area | Entry point |
|---|---|
| Bounded execution and host decisions | [harness.py](src/tracebot/harness.py) |
| Questions and evidence lifecycle | [context.py](src/tracebot/context.py) |
| Local model planner | [harness_planner.py](src/tracebot/providers/harness_planner.py) |
| Real2Sim tool adapter | [real2sim_harness_tools.py](scripts/real2sim_harness_tools.py) |
| Corridor navigation | [real2sim_navigation.py](scripts/real2sim_navigation.py) |
| Repeated trials | [repeat_real2sim_trials.py](scripts/repeat_real2sim_trials.py) |
| Design decisions | [context method](reports/CONTEXT_METHOD_DECISIONS.md), [architecture notes](docs/architecture/README.md) |

## License

[MIT](LICENSE) for the code in this repository. Dependencies, model weights and scene assets keep their own terms. The optional person detector uses Ultralytics YOLO, which is AGPL-3.0.
