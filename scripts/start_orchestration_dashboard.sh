#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FW_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ -f "$FW_ROOT/../.adf-install.json" ]]; then ROOT="$(cd "$FW_ROOT/.." && pwd)"; else ROOT="${ORCH_REPO_ROOT:-$(pwd)}"; fi
export ORCH_REPO_ROOT="$ROOT"
export ORCH_AUTO_RUNNER="${ORCH_AUTO_RUNNER:-true}"
MODE="${1:-web}"
PORT="${ORCH_PORT:-3847}"
WEB_PORT="${ORCH_WEB_PORT:-3848}"
cd "$ROOT"
if ! lsof -i ":$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "Starting API on http://localhost:$PORT ..."
  dart run "$FW_ROOT/tools/orchestration_server/bin/server.dart" &
  sleep 2
fi
cd "$FW_ROOT/tools/orchestration_dashboard"
flutter pub get >/dev/null 2>&1 || true
if [[ "$MODE" == macos ]]; then
  flutter run -d macos --dart-define=ORCH_API_URL="http://127.0.0.1:$PORT"
else
  flutter run -d chrome --web-port="$WEB_PORT" --dart-define=ORCH_API_URL="http://localhost:$PORT"
fi
