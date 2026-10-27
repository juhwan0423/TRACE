#!/usr/bin/env bash
# Source on jude's RTX 5090 workstation; reuses the installed Isaac Sim 6.2.
export WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ISAAC_LAB_DIR=/home/jude/isaac_ws_61/IsaacLab
export ISAAC_SIM_DIR="$ISAAC_LAB_DIR/.venv/lib/python3.12/site-packages/isaacsim"
export PATH="$WORKSPACE_DIR/.venv/bin:$WORKSPACE_DIR/artifacts/ollama/bin:$PATH"
export PYTHONPATH="$WORKSPACE_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
export OLLAMA_HOST=127.0.0.1:11434
export TRACE_SPARK_HOST=100.73.59.16
export TRACE_SCENE="${TRACE_SCENE:-real2sim}"
export TRACE_ISAAC_PORT="${TRACE_ISAAC_PORT:-8227}"
export OLLAMA_MODELS="$WORKSPACE_DIR/artifacts/ollama/models"
export ROS_DOMAIN_ID=173 ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
