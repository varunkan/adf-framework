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

# Telemetry hook: do not auto-approve subagent execution unless the user has
# opted into unattended mode (see orch-otel-ingest.sh). Default {} = let Cursor
# prompt as usual.
RESPONSE='{}'
case "${ADF_HOOK_AUTO_APPROVE:-0}" in
  1|true|yes|on) RESPONSE='{"permission":"allow"}' ;;
esac

printf '%s\n' "$RESPONSE"
exit 0
