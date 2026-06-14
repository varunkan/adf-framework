#!/usr/bin/env bash
# OpenTelemetry ingest for Cursor agent hooks (reasoning, tools, subagents). Fail-open.
# Stdout MUST be exactly one JSON object — Cursor blocks tools on invalid hook output.
set +e

EVENT="${1:-unknown}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export OTEL_HOOK_EVENT="$EVENT"
export ORCH_REPO_ROOT="$ROOT"

INPUT=$(cat)
SCRIPT="$ROOT/tools/orchestration_telemetry/bin/ingest_event.py"

if [[ -f "$SCRIPT" ]]; then
  # Telemetry is a side effect (writes trace files). Its stdout must NOT reach
  # the hook's stdout — Cursor requires exactly one JSON object, emitted below.
  printf '%s' "$INPUT" | python3 "$SCRIPT" >/dev/null 2>&1
else
  LOG="$ROOT/.cursor/orchestration/otel-traces.jsonl"
  mkdir -p "$(dirname "$LOG")"
  printf '{"hook":"%s","ts":"%s","payload":%s}\n' \
    "$EVENT" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${INPUT:-{}}" >> "$LOG" 2>/dev/null || true
fi

# Authorization is OFF by default: this is a telemetry hook, so it must not
# silently approve shell/MCP execution on the user's behalf. Returning {} lets
# Cursor fall back to its normal per-action approval prompt.
#
# For unattended/autopilot runs, opt in by exporting ADF_HOOK_AUTO_APPROVE=1
# (e.g. in .adf/runner.env). Only then do the gating events auto-allow.
RESPONSE='{}'
case "${ADF_HOOK_AUTO_APPROVE:-0}" in
  1|true|yes|on)
    case "$EVENT" in
      preToolUse|subagentStart|beforeShellExecution|beforeMCPExecution)
        RESPONSE='{"permission":"allow"}'
        ;;
    esac
    ;;
esac

printf '%s\n' "$RESPONSE"
exit 0
