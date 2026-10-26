#!/usr/bin/env bash
# Source this file in each TRACE terminal.
export WORKSPACE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ISAAC_LAB_DIR="$WORKSPACE_DIR" # Legacy launcher venv prefix; Isaac Lab is not required.
export ISAAC_SIM_DIR="$WORKSPACE_DIR/.venv/lib/python3.12/site-packages/isaacsim"
# EULA consent is operator-specific. Preserve an explicitly set environment value;
# sourcing a public repository script must not accept terms for a new operator.
export PATH="$WORKSPACE_DIR/.venv/bin:$WORKSPACE_DIR/artifacts/ollama/bin:$PATH"
export PYTHONPATH="$WORKSPACE_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
export LD_PRELOAD="/lib/aarch64-linux-gnu/libgomp.so.1${LD_PRELOAD:+:$LD_PRELOAD}"
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS="$WORKSPACE_DIR/artifacts/ollama/models"
export ROS_DOMAIN_ID=173 ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
