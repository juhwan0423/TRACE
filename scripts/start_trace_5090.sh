#!/usr/bin/env bash
# The primary 5090 environment is Real2Sim.
set -euo pipefail
exec bash "$(dirname "${BASH_SOURCE[0]}")/start_trace_real2sim_5090.sh"
