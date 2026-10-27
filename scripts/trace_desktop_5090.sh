#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env_5090.sh"
export PATH="$WORKSPACE_DIR/artifacts/graphviz/root/usr/bin:$PATH"
export LD_LIBRARY_PATH="$WORKSPACE_DIR/artifacts/graphviz/root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export GVBINDIR="$WORKSPACE_DIR/artifacts/graphviz/root/usr/lib/x86_64-linux-gnu/graphviz"
mkdir -p "$WORKSPACE_DIR/artifacts/logs"
exec bash "$WORKSPACE_DIR/scripts/trace_desktop.sh"
