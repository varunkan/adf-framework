#!/usr/bin/env bash
# OpenTelemetry ingest for Cursor agent hooks (reasoning, tools, subagents). Fail-open.
# Stdout MUST be exactly one JSON object — Cursor blocks tools on invalid hook output.
set +e

EVENT="${1:-unknown}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export OTEL_HOOK_EVENT="$EVENT"
export ORCH_REPO_ROOT="$ROOT"
DEBUG_LOG="$ROOT/.cursor/debug-e6daa9.log"

#region agent log
_agent_log() {
  local hyp="$1" loc="$2" msg="$3" data="$4"
  printf '{"sessionId":"e6daa9","runId":"pre-fix","hypothesisId":"%s","location":"%s","message":"%s","data":%s,"timestamp":%s}\n' \
    "$hyp" "$loc" "$msg" "$data" "$(python3 -c 'import time; print(int(time.time()*1000))' 2>/dev/null || date +%s000)" \
    >> "$DEBUG_LOG" 2>/dev/null || true
}
#endregion

INPUT=$(cat)
INPUT_LEN=${#INPUT}
SCRIPT="$ROOT/tools/orchestration_telemetry/bin/ingest_event.py"
PY_EXIT=0
PY_OUT=""

#region agent log
_agent_log "C" "orch-otel-ingest.sh:entry" "hook invoked" "{\"event\":\"$EVENT\",\"root\":\"$ROOT\",\"script_exists\":$([ -f "$SCRIPT" ] && echo true || echo false),\"input_len\":$INPUT_LEN,\"pwd\":\"$(pwd)\"}"
#endregion

if [[ -f "$SCRIPT" ]]; then
  PY_OUT=$(printf '%s' "$INPUT" | python3 "$SCRIPT" 2>/dev/null)
  PY_EXIT=$?
  if [[ $PY_EXIT -ne 0 ]]; then
    PY_OUT=""
  fi
else
  LOG="$ROOT/.cursor/orchestration/otel-traces.jsonl"
  mkdir -p "$(dirname "$LOG")"
  printf '{"hook":"%s","ts":"%s","payload":%s}\n' \
    "$EVENT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${INPUT:-{}}" >> "$LOG" 2>/dev/null || true
fi

# Cursor gating hooks require explicit permission (empty {} may be rejected).
RESPONSE='{}'
case "$EVENT" in
  preToolUse|subagentStart|beforeShellExecution|beforeMCPExecution)
    RESPONSE='{"permission":"allow"}'
    ;;
esac

#region agent log
PY_LINES=$(printf '%s' "$PY_OUT" | wc -l | tr -d ' ')
PY_BYTES=${#PY_OUT}
_agent_log "A" "orch-otel-ingest.sh:pre-emit" "python capture + response choice" "{\"event\":\"$EVENT\",\"py_exit\":$PY_EXIT,\"py_bytes\":$PY_BYTES,\"py_lines\":$PY_LINES,\"py_out_preview\":\"$(printf '%s' "$PY_OUT" | head -c 120 | sed 's/\\/\\\\/g; s/"/\\"/g')\",\"response\":\"$RESPONSE\"}"
#endregion

printf '%s\n' "$RESPONSE"

#region agent log
_agent_log "B" "orch-otel-ingest.sh:exit" "hook stdout emitted" "{\"event\":\"$EVENT\",\"response\":\"$RESPONSE\",\"exit\":0}"
#endregion

exit 0
