#!/usr/bin/env bash
set -euo pipefail
TRACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$TRACE_ROOT/artifacts/ssh"
SPARK_TARGET="${1:-${TRACE_SPARK_HOST:-100.73.59.16}}"
if [[ -z "$SPARK_TARGET" ]]; then
    echo "Usage: bash scripts/start_spark_tunnel.sh <Spark Tailscale IP or hostname>" >&2
    exit 2
fi
exec ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=accept-new \
    -o "UserKnownHostsFile=$TRACE_ROOT/artifacts/ssh/known_hosts" \
    -L 127.0.0.1:11435:127.0.0.1:11434 "${TRACE_SPARK_USER:-juhwan}@$SPARK_TARGET"
