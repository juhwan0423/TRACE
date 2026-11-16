# Go2 live monitor — 2026-11-16

TRACE now includes a read-only Go2 monitor alongside its existing simulation workflow. This real-hardware addition was explicitly requested by the operator. The original simulation implementation guide remains unchanged.

![Go2 real-hardware presentation workspace](assets/go2-real-workspace.png)

## Verified on hardware

- Tailscale SSH connects Spark to the Jetson. The HTTP bridge health and authenticated state requests succeed.
- SportModeState arrives with approximately 1–3 ms age at the bridge.
- Jetson-attached RealSense RGB frames arrive at 640×480 over a persistent SSH connection, capped at 10 fps. This is not the Go2 built-in camera.
- The monitor refreshes telemetry once per second and displays stale/disconnected camera status.
- With operator confirmation of clearance, one `stand_up` request was sent. Reported body height rose from 0.076 m to 0.329 m and stayed there through eight one-second samples. No walking command was sent.
- `error_code` changed from 1001 to 1002; its firmware-specific meaning is unverified. `moving: false` is the bridge command bookkeeping field, not independent proof that the robot cannot move.

## Screen scope

The monitor receives live camera and telemetry. Qwen3-VL 8B now describes the latest received frame through local Ollama on port 11434, one request at a time. Optional repeat analysis waits until the previous request finishes; stale camera input is rejected. The UI identifies the analyzed frame time. Model descriptions are unverified observations, not navigation clearance, and no robot tools are executed.

CCTV supports selecting and looping local MicrosoftTeams-video MP4 files from the Downloads folder (including the Korean folder name). These are recorded files, not a connected CCTV feed.

The screenshot above is a **static presentation composition**: a saved RealSense RGB image, a rotated frame from a user-provided recording, and a historical Qwen response from a different observation. These sources are not synchronized. The UI shows a small mockup label and identifies historical Qwen output. Raw recordings are not included in the repository.

Local snapshot images and Qwen response logs were saved; the earlier live stream was not recorded as a continuous video. The standalone composition script `scripts/go2_presentation_mockup.py` uses local artifacts and recording paths; it is not a portable demo with bundled footage.

## Run

From the repository root, on the Spark desktop with system GTK installed:

```bash
/usr/bin/python3 scripts/monitor_go2_ui.py
# Optional: capture the app widget after 20 received frames
/usr/bin/python3 scripts/monitor_go2_ui.py --capture-mockup
```

The same component appears under **Go2 실시간** in `scripts/trace_desktop.py`. Click **스트림 연결** there. Run only one camera consumer at a time. Close the standalone monitor before connecting from the full app.

Read-only snapshot and state capture:

```bash
PYTHONPATH=src python3 -m tracebot.providers.go2_readonly
```

SSH must already be authenticated. The current deployment uses the Jetson project configuration at `/home/unitree/go2_bridge_project/config/bridge.env` and RealSense `/dev/video4`; adapt those deployment defaults for another robot. Tokens are read on Jetson and never copied into this repository or displayed. The bridge is accessed locally from Jetson through SSH; no new public camera port is opened.

## Validation and limits

Python compilation passed for the new monitor, snapshot provider, and modified main desktop module. Live streaming was observed beyond 123 frames. The standalone component was launched and captured; the entire simulation desktop was not relaunched or revalidated. Hardware timestamps, depth sensing, obstacle avoidance, automatic reconnect, and Qwen-to-Go2 motion integration remain future work. The displayed camera age measures time since local receipt, not sensor exposure time.

## November 16 follow-up validation

- Confirmed both snapshot and stream use RealSense `/dev/video4`, not a ROS camera topic. Enabled `exposure_auto_priority=1` for low-light adaptation; the lighting change also followed robot stand-up and changed framing, so a single cause was not established.
- Actual Qwen response received in approximately 7.5 seconds; subsequent responses recorded locally. No motion commands were generated or executed by Qwen.
- Captured the static presentation screenshot after correcting CCTV rotation 90 degrees counterclockwise. Existing simulation source and evaluation reports remain unchanged.
