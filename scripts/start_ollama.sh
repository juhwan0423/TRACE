#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/env_spark.sh"
export OLLAMA_CONTEXT_LENGTH=8192 OLLAMA_NUM_PARALLEL=1
exec "$WORKSPACE_DIR/artifacts/ollama/bin/ollama" serve
