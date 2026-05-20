#!/usr/bin/env bash
# Reminds orchestrator sessions to sync state if approval pending (fail-open).
set +e

INPUT=$(cat)
FEATURE_DIR_ROOT=".cursor/orchestration/features"

MSG=""
if [[ -d "$FEATURE_DIR_ROOT" ]]; then
  for d in "$FEATURE_DIR_ROOT"/*/; do
    [[ -f "${d}state.json" ]] || continue
    id=$(basename "$d")
    [[ "$id" == _* ]] && continue
    if grep -q '"awaiting_user": true' "${d}state.json" 2>/dev/null; then
      MSG="Orchestration: feature '$id' awaits approval. Dashboard or @orch-orchestrator sync $id"
      break
    fi
  done
fi

if [[ -n "$MSG" ]]; then
  # Escape quotes for JSON string
  ESCAPED=$(echo "$MSG" | sed 's/\\/\\\\/g; s/"/\\"/g')
  echo "{\"followup_message\": \"$ESCAPED\"}"
else
  echo '{}'
fi
exit 0
