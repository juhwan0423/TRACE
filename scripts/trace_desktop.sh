#!/usr/bin/env bash
set -euo pipefail
TRACE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec /usr/bin/python3 "$TRACE_ROOT/scripts/trace_desktop.py"
