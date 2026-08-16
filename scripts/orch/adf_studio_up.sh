#!/usr/bin/env bash
# Bring ADF Studio up DETACHED, wait for it, and open the dashboard.
#
# Invoked by the /adf skill. The orchestration server is long-lived, so it MUST
# outlive the (short) `claude -p` turn that launches it. A plain foreground (or
# even backgrounded-but-same-session) process gets reaped seconds after the turn
# ends, so we detach into a new session via setsid (Linux) or nohup (macOS).
set -uo pipefail
FW="$(cd "$(dirname "$0")/../.." && pwd)"
PORT="${ORCH_PORT:-3847}"
LOG="${ADF_STUDIO_LOG:-/tmp/adf-studio.log}"
URL="http://127.0.0.1:${PORT}"
LAUNCHER="$FW/scripts/orch/run_studio_capable.sh"

up() { curl -sf -m 2 "$URL/health" >/dev/null 2>&1; }

if up; then
  echo "ADF Studio already running at $URL"
else
  echo "Starting ADF Studio (detached) — log: $LOG"
  if command -v setsid >/dev/null 2>&1; then
    setsid bash "$LAUNCHER" >"$LOG" 2>&1 </dev/null &
  else
    nohup bash "$LAUNCHER" >"$LOG" 2>&1 </dev/null &
    disown 2>/dev/null || true
  fi
  # First boot warms a local chat model, so allow ~40s.
  for _ in $(seq 1 80); do up && break; sleep 0.5; done
fi

if up; then
  echo "ADF Studio is up: $URL"
  # Surface which runner the launcher selected (Claude CLI vs fallback).
  grep -m1 '(runner =' "$LOG" 2>/dev/null || true
  command -v open >/dev/null 2>&1 && open "$URL" || true
  exit 0
else
  echo "ADF Studio did not come up within the timeout." >&2
  echo "Tail the log to see why:  tail -n 40 $LOG" >&2
  exit 1
fi
