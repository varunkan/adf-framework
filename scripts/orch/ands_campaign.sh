#!/usr/bin/env bash
# Resilient campaign supervisor — the interruption-resilience feature, operational.
#
# Keeps the ANDS expansion driver ALIVE across crashes, kills, and session
# interruptions until every slice is green. All progress is checkpointed in the
# coverage ledger, so each relaunch RESUMES (skips done slices) rather than
# restarting. This is the "embrace failure and keep fighting" loop at the
# campaign level: a dead driver is simply restarted, not the end of the run.
set -uo pipefail
FW="$(cd "$(dirname "$0")/../.." && pwd)"
ID="${ANDS_FEATURE_ID:-ands-submission-portal}"
LEDGER="$FW/.adf/orchestration/features/$ID/coverage-ledger.json"
LOG="${ANDS_CAMPAIGN_LOG:-/tmp/ands-expand.log}"
TOTAL="${ANDS_TOTAL_SLICES:-12}"
MAX_RESTARTS="${MAX_RESTARTS:-60}"

done_count() {
  python3 -c "import json;print(len(json.load(open('$LEDGER')).get('done',[])))" 2>/dev/null || echo 0
}

echo "[campaign] start $(date) — driving $ID to $TOTAL slices green" >> "$LOG"
for r in $(seq 1 "$MAX_RESTARTS"); do
  d="$(done_count)"
  if [ "$d" -ge "$TOTAL" ]; then
    echo "[campaign] COMPLETE — $d/$TOTAL slices green $(date)" >> "$LOG"
    break
  fi
  echo "[campaign] launch driver (run $r, done=$d/$TOTAL) $(date)" >> "$LOG"
  python3 "$FW/scripts/orch/ands_expand_all.py" >> "$LOG" 2>&1
  rc=$?
  echo "[campaign] driver exited rc=$rc, done=$(done_count)/$TOTAL $(date)" >> "$LOG"
  sleep 10
done
echo "[campaign] supervisor end $(date) — done=$(done_count)/$TOTAL" >> "$LOG"
