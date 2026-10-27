# RTX 5090 local setup

This checkout runs on `jude-X870E-AORUS-PRO`, not DGX Spark.

Start the desktop monitor with its simulation dependencies:

```bash
cd /home/jude/Documents/ChatGPT/ROSCLAW/TRACE
bash scripts/start_trace_5090.sh
```

The default environment is HAI-Real2Sim (Isaac Python server 8227). The desktop
shows its cameras and sends frame inference to Spark. Spot navigation is connected through the desktop buttons and command interface below.
The native operator-triggered inspection harness is connected (see below); the legacy live harness refuses
to silently use the old demo. Fixture mode remains available for software checks.

The local `.venv` symlink reuses the existing Isaac Sim 6.2 environment at
`/home/jude/isaac_ws_61/IsaacLab/.venv`. Ollama and its model files live in
`artifacts/ollama`. Graphviz is extracted under `artifacts/graphviz`; no system
package or global environment change is needed. Use `env_5090.sh`, since
`env_spark.sh` contains an ARM-specific library preload.

The previous HAICLAW checkout remains at `/home/jude/isaac_ws_61/haiclaw_ws`.
Active endpoints are localhost 8227 (Real2Sim) and 11435 (SSH tunnel to Spark Ollama).

Execution evidence and current limitations are recorded in `WORKLOG.md`.

## Real2Sim monitor and Spark Qwen

Latest upstream applied: e80f30a. Run:

```bash
bash scripts/start_trace_real2sim_5090.sh
```

This uses the already-running Real2Sim scene at localhost 8227, or starts its
6.2 preview if that port is free. It displays three real camera feeds. The cage-side
camera now follows Spot. Manual navigation is connected; the native inspection harness is available; autonomous incident detection is not implemented. The original TRACE demo is retired from the default launcher.

The configured model endpoint is now Spark via localhost 11435. After both machines
are signed into the same Tailscale account, keep this command running:

```bash
bash scripts/start_spark_tunnel.sh <Spark-Tailscale-IP>
curl http://127.0.0.1:11435/api/tags
```

SSH user defaults to juhwan (`TRACE_SPARK_USER` overrides it). Host-key verification
and SSH authentication use normal OpenSSH prompts; no credentials are saved by the
launcher. The desktop frame-analysis button requires the tunnel. Local Ollama is
not started automatically and is not a fallback. Logs for this monitor are separated
under artifacts/live_real2sim.

Current verified Spark address: `100.73.59.16`. The tunnel launcher defaults to this address; run `bash scripts/start_spark_tunnel.sh` in a terminal to reconnect. An existing tunnel occupies port 11435, so do not start duplicates. Initial Real2Sim frame inference passed on Spark in 96.23 seconds.

## Real2Sim Spot commands

The default monitor attaches the 6.2 Spot runner to the owned labwest preview and
provides patrol, west, cage, entrance, and stop buttons. The body-camera feed moves
with Spot and can be selected for the existing Spark Qwen frame analysis. Worker
animation and colliders stay visible during navigation.

```bash
python3 scripts/real2sim_control.py state
python3 scripts/real2sim_control.py go patrol
python3 scripts/real2sim_control.py go west
python3 scripts/real2sim_control.py go cage
python3 scripts/real2sim_control.py go entrance
python3 scripts/real2sim_control.py stop
# Only after stopping: explicitly teleport the simulation robot back to its spawn.
python3 scripts/real2sim_control.py reset
```

Goals follow the repository's saved A* corridor; arbitrary straight-line targets
are not accepted. Start a full patrol at the entrance. Stop an active goal before
replacing it. Lack of progress, excessive tilt, and goal deadlines produce a failure;
controller exceptions pause the owned simulation. Faults require inspection; the explicit entrance-reset button resets only Spot.
Live navigation uses 0.45 m/s maximum speed and a 0.15 m waypoint tolerance.
This is simulator waypoint navigation, not Nav2 or autonomous Qwen decision making.
Commands and snapshots are recorded under `artifacts/live_real2sim/navigation.jsonl`.

Live validation: TRACE-issued full patrol completed 23/23 target waypoints in
65.726 simulation seconds with worker/door animation preserved. Movement,
cancellation, and entrance arrival were also verified. The first faster run
failed the tilt guard; the successful run used the conservative limits above.
See `artifacts/live_real2sim/navigation-validation.json` for the final snapshot.

## Native harness baseline (no LangGraph)

```bash
PYTHONPATH=src .venv/bin/python scripts/run_real2sim_harness.py
# Short live validation with an explicit three-decision budget:
PYTHONPATH=src .venv/bin/python scripts/run_real2sim_harness.py --max-steps 3
```

The Real2Sim monitor's agent tab runs this entry point. It starts an operator-requested
worker inspection on the current scene; it does not inject a disappearance, move the
worker, or assert a detected incident. The Qwen planner selects observe/inspect/wait/
stop/escalate through the existing native asyncio Harness. The framework-independent
Planner and InspectionTools protocols isolate orchestration from model and tools.

Real2Sim inspection moves have request IDs and final view headings. Arrival timestamps
use the same SimulationManager clock as image capture. Cancellation is scoped to the
harness's action ID; replaced goals are never accepted as its own arrival. Fresh image
files, decisions, tool results, config/model settings and code hashes are saved in each
artifacts/harness/<episode> directory. Do not compare a completed unresolved handoff
with a successful diagnosis: the terminal state must be reported separately.

For a later LangGraph comparison, hold the model configuration, tool implementation,
scenarios, evidence/closure rules, decision budgets and starting conditions constant.
Compare success/unknown rates, stale-evidence rejection, latency, model/tool calls,
and interruption recovery. Current inspection baseline has no durable crash-resume
or autonomous incident detector; those are explicit future comparison dimensions.
