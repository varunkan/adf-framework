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

# SLEEP RESILIENCE: re-exec the whole campaign under caffeinate so the Mac never
# idle-sleeps mid-run (idle sleep suspended builds and burned the watchdog's
# resume budget). One-shot guard so we don't fork caffeinate repeatedly.
if [ "${ADF_NO_CAFFEINATE:-0}" != "1" ] && [ -z "${ANDS_CAFFEINATED:-}" ] && command -v caffeinate >/dev/null 2>&1; then
  export ANDS_CAFFEINATED=1
  exec caffeinate -i -d -m -s bash "$0" "$@"
fi

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
