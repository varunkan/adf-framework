#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FW_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ -f "$FW_ROOT/../.adf-install.json" ]]; then ROOT="$(cd "$FW_ROOT/.." && pwd)"; else ROOT="${ORCH_REPO_ROOT:-$(pwd)}"; fi
export ORCH_REPO_ROOT="$ROOT"
export ORCH_AUTO_RUNNER="${ORCH_AUTO_RUNNER:-true}"
PORT="${ORCH_PORT:-3847}"
cd "$ROOT"
if lsof -i ":$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "Already listening on http://localhost:$PORT"
else
  echo "Starting API on http://localhost:$PORT ..."
  exec dart run "$FW_ROOT/tools/orchestration_server/bin/server.dart"
fi
