#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env_5090.sh"
export REAL2SIM_ROOT="${REAL2SIM_ROOT:-$(dirname "$WORKSPACE_DIR")/HAI-Real2Sim}"
export TRACE_SCENE=real2sim TRACE_ISAAC_PORT=8227
cd "$WORKSPACE_DIR"
if ! python - <<'PY'
import socket
with socket.socket() as s:
    s.settimeout(.5)
    raise SystemExit(s.connect_ex(('127.0.0.1',8227)) != 0)
PY
then
    python "$REAL2SIM_ROOT/lab_west/reproduce/preview_isaacsim620.py" --python "$ISAAC_LAB_DIR/.venv/bin/python"
fi
python - <<'PY'
import urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:11435/api/tags',timeout=3).close()
except OSError:
    print('Spark Qwen tunnel is not connected. Camera monitoring remains available; inference will wait for connection.')
PY
exec bash scripts/trace_desktop_5090.sh
