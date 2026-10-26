#!/usr/bin/env bash
set -euo pipefail
WORKSPACE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
exec docker run --rm --pull never --name haiclaw-nav2 --network host --ipc host \
  --user "$(id -u):$(id -g)" --read-only --tmpfs /tmp -e ROS_LOG_DIR=/tmp/roslogs -e FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/ros2/nav2/fastdds_local.xml \
  -e ROS_DOMAIN_ID=173 -e ROS_LOCALHOST_ONLY=1 -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
  -v "$WORKSPACE_DIR:/workspace:ro" --entrypoint bash haiclaw-nav2:jazzy \
  -c 'source /opt/ros/jazzy/setup.bash; exec ros2 launch /workspace/ros2/nav2/bringup.launch.py'
