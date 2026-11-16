#!/usr/bin/env bash
# Runs frozen cohort A then B with the unmodified runner; then the standard evaluate step.
cd /home/jude/Documents/ChatGPT/ROSCLAW/TRACE
source scripts/env_spark.sh; unset LD_PRELOAD
D=artifacts/heldout_confirmation_20261115
for T in A B; do
  echo "START $T $(date -Is)" >> $D/run_all.log
  PYTHONPATH=src .venv/bin/python -u scripts/run_real2sim_comparison.py run --output $D/cohort_$T > $D/cohort_$T/run.log 2>&1
  rc=$?; echo "END $T rc=$rc $(date -Is)" >> $D/run_all.log
  PYTHONPATH=src .venv/bin/python -u scripts/run_real2sim_comparison.py evaluate --output $D/cohort_$T >> $D/cohort_$T/evaluate.log 2>&1
  [ $rc -ne 0 ] && { echo "STOPPED after $T" >> $D/run_all.log; exit $rc; }
done
echo "ALL_DONE $(date -Is)" >> $D/run_all.log
