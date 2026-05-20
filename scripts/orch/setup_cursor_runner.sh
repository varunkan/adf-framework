#!/usr/bin/env bash
# One-time setup for orchestration dashboard headless runner.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
AGENT="${CURSOR_AGENT_PATH:-$HOME/.local/bin/cursor-agent}"
ENV_FILE="$HOME/.cursor/agent.env"
PORT="${ORCH_PORT:-3847}"

echo "=== Cursor orchestration runner setup ==="
echo ""

if [[ ! -x "$AGENT" ]]; then
  echo "cursor-agent not found. Installing..."
  curl -fsSL https://cursor.com/install | bash
  AGENT="$HOME/.local/bin/cursor-agent"
fi

echo "Agent: $AGENT"
echo ""

# Option A: API key (no browser) — paste from https://cursor.com/dashboard → API Keys
if [[ -f "$ENV_FILE" ]] && grep -q CURSOR_API_KEY "$ENV_FILE" 2>/dev/null; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
  echo "Loaded $ENV_FILE"
fi

if [[ -z "${CURSOR_API_KEY:-}" ]]; then
  echo "Choose one:"
  echo "  1) Browser login (recommended): cursor-agent login"
  echo "  2) API key: add to ~/.cursor/agent.env:"
  echo "       CURSOR_API_KEY=cursor_xxxxxxxx"
  echo ""
  read -r -p "Run browser login now? [Y/n] " ans
  if [[ "${ans:-Y}" =~ ^[Yy]$ ]]; then
    "$AGENT" login
  fi
else
  echo "CURSOR_API_KEY is set."
fi

echo ""
echo "Verifying..."
if "$AGENT" status 2>&1 | grep -qi "logged in\|authenticated"; then
  echo "OK: cursor-agent authenticated"
elif [[ -n "${CURSOR_API_KEY:-}" ]]; then
  echo "OK: using CURSOR_API_KEY"
else
  echo "Still not authenticated. Run: cursor-agent login"
  exit 1
fi

if ! grep -q CURSOR_API_KEY "$ENV_FILE" 2>/dev/null && [[ -n "${CURSOR_API_KEY:-}" ]]; then
  mkdir -p "$(dirname "$ENV_FILE")"
  echo "CURSOR_API_KEY=$CURSOR_API_KEY" >> "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi

echo ""
echo "Restart orchestration API if it is running, then open dashboard:"
echo "  ORCH_REPO_ROOT=$ROOT dart run tools/orchestration_server/bin/server.dart"
echo "  http://localhost:3848"
echo ""
if curl -sf "http://localhost:$PORT/runner/health" >/dev/null 2>&1; then
  curl -sf "http://localhost:$PORT/runner/health" | python3 -m json.tool 2>/dev/null || curl -sf "http://localhost:$PORT/runner/health"
fi
