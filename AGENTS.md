# HAI-CLAW workspace instructions

## Scope and requirements
- Read `implementation_guide.md` as the project requirements; preserve it intact.
- Simulation only. No real hardware, paid APIs, large downloads, other-project edits or global settings changes.
- Preserve existing GUI scenes and instances. Never reset an unsaved stage or terminate another instance.

## Installed official Isaac Sim skills
- Installation: `/home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim`
- Agent guide: `/home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/AGENTS.md`
- Routing index: `/home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills/SKILLS.md`
- Skills root: `/home/jude/isaac_ws_61/IsaacLab/.venv/lib/python3.12/site-packages/isaacsim/skills`
- Python: `/home/jude/isaac_ws_61/IsaacLab/.venv/bin/python`

Read the installed agent guide and routing index first. Select relevant skills by their description; read their `SKILL.md` and only the references/examples needed for the next step. Do not bulk-load all skills. Use local installed 6.2.0 API source/examples to validate calls. Do not change official skills or global Codex configuration.

This is a pip installation, not an Isaac Sim source build. Do not blindly apply `_build`, Repo/Premake, `python.sh` or source-tree launch commands. Resolve actual installed executables and dependencies first.

For the initial occlusion experiment, compose `isaac-sim-orchestrator`, `isaac-sim-assets`, `physics-simulation`, `isaac-sim-sensor`, and `isaac-camera` as needed. Before live GUI interaction read `isaac-sim-remote` and its Python Server documentation, check health, and inspect the current stage read-only. Coordinate any stage replacement with the user. Use `isaac-sim-validator` before delivering captures.

Record used skills, exact commands, failures, and verification levels in workspace reports/WORKLOG.md. Distinguish static review, Python fixture tests, USD inspection, real Isaac rendering, ROS transport, and locomotion verification. Never infer successful rendering or walking from installed packages alone.
