#!/usr/bin/env bash
# Logs subagent starts to active feature run-log.jsonl (fail-open).
set +e

INPUT=$(cat)
FEATURE_DIR_ROOT=".cursor/orchestration/features"

# Best-effort: find feature with status active and awaiting work
FEATURE_ID=""
if [[ -d "$FEATURE_DIR_ROOT" ]]; then
  for d in "$FEATURE_DIR_ROOT"/*/; do
    [[ -f "${d}state.json" ]] || continue
    id=$(basename "$d")
    [[ "$id" == _* ]] && continue
    if grep -q '"status": "active"' "${d}state.json" 2>/dev/null; then
      FEATURE_ID="$id"
      break
    fi
  done
fi

if [[ -n "$FEATURE_ID" ]]; then
  LOG="${FEATURE_DIR_ROOT}/${FEATURE_ID}/run-log.jsonl"
  mkdir -p "$(dirname "$LOG")"
  printf '%s\n' "$INPUT" >> "$LOG"
fi

#region agent log
DEBUG_LOG="$(cd "$(dirname "$0")/../.." && pwd)/.cursor/debug-e6daa9.log"
printf '{"sessionId":"e6daa9","runId":"pre-fix","hypothesisId":"D","location":"orch-log-subagent.sh:exit","message":"subagent hook stdout","data":{"feature_id":"%s","response":"{\"permission\":\"allow\"}"},"timestamp":%s}\n' \
  "$FEATURE_ID" "$(python3 -c 'import time; print(int(time.time()*1000))' 2>/dev/null || date +%s000)" \
  >> "$DEBUG_LOG" 2>/dev/null || true
#endregion

printf '%s\n' '{"permission":"allow"}'
exit 0
