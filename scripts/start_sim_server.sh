#!/usr/bin/env bash
set -euo pipefail
WORKSPACE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ISAAC_LAB_DIR="${ISAAC_LAB_DIR:-$(dirname "$WORKSPACE_DIR")/IsaacLab}"
ISAAC_SIM_DIR="${ISAAC_SIM_DIR:-$ISAAC_LAB_DIR/.venv/lib/python3.12/site-packages/isaacsim}"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
export ROS_DOMAIN_ID=173 ROS_LOCALHOST_ONLY=1 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export XDG_CACHE_HOME="$WORKSPACE_DIR/artifacts/runtime/cache"
export XDG_CONFIG_HOME="$WORKSPACE_DIR/artifacts/runtime/config"
export XDG_DATA_HOME="$WORKSPACE_DIR/artifacts/runtime/data"
export CUDA_CACHE_PATH="$WORKSPACE_DIR/artifacts/runtime/cuda"
mkdir -p "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$CUDA_CACHE_PATH"
python3 - <<'PY'
import socket
with socket.socket() as s:
    if s.connect_ex(('127.0.0.1', 8226)) == 0:
        raise SystemExit('Port 8226 occupied: preserve the existing instance; inspect it first.')
PY
ros_args=(--/isaac/startup/ros_bridge_extension=)
if [[ "${HAICLAW_ROS:-0}" == "1" ]]; then
    export ROS_DISTRO=jazzy RMW_IMPLEMENTATION=rmw_fastrtps_cpp
    export FASTRTPS_DEFAULT_PROFILES_FILE="$WORKSPACE_DIR/ros2/nav2/fastdds_local.xml"
    export ROS_LOG_DIR="$WORKSPACE_DIR/artifacts/nav2/roslogs"
    export LD_LIBRARY_PATH="$ISAAC_SIM_DIR/exts/isaacsim.ros2.core/jazzy/lib:${LD_LIBRARY_PATH:-}"
    ros_args=(--enable isaacsim.ros2.bridge)
fi
window_args=()
if [[ "${HAICLAW_HEADLESS:-1}" == "1" ]]; then window_args+=(--no-window); fi
exec "$ISAAC_LAB_DIR/.venv/bin/python" -B -c \
 'import charset_normalizer, charset_normalizer.md, charset_normalizer.cd; from isaacsim import main; main()' \
 "${window_args[@]}" --enable isaacsim.code_editor.python_server \
 "${ros_args[@]}" --/isaac/startup/ros_sim_control_extension= \
 --/exts/isaacsim.code_editor.python_server/host=127.0.0.1 \
 --/app/settings/persistent=false --/haiclaw/workspace="$WORKSPACE_DIR" \
 --/app/userConfigPath="$WORKSPACE_DIR/artifacts/runtime/user.config.json" \
 --/app/userCachePath="$XDG_CACHE_HOME" --/app/userDataPath="$XDG_DATA_HOME" \
 --/log/file="$WORKSPACE_DIR/artifacts/logs/kit.log" \
 --/exts/isaacsim.physics.newton/auto_switch_on_startup=false \
 --/exts/isaacsim.core.simulation_manager/default_engine=physx \
 --/renderer/multiGpu/enabled=false --/app/window/width=1280 --/app/window/height=720 \
 --/rtx/rendermode=RayTracedLighting "$@"
