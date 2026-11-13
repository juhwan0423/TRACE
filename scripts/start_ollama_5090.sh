#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env_5090.sh"
export OLLAMA_NUM_PARALLEL=1 OLLAMA_CONTEXT_LENGTH=8192
exec "$WORKSPACE_DIR/artifacts/ollama/bin/ollama" serve
