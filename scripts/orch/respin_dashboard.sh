#!/usr/bin/env bash
set -euo pipefail
FRAMEWORK_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${ORCH_REPO_ROOT:-$(cd "$FRAMEWORK_ROOT/.." && pwd)}"
export ORCH_REPO_ROOT="$ROOT"
API_PORT="${ORCH_PORT:-3847}"
WEB_PORT="${ORCH_WEB_PORT:-3848}"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  ADF Studio — proof-governed agentic development         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "Project: $ROOT"
echo ""

echo "Stopping old API/dashboard..."
lsof -ti:"$API_PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti:"$WEB_PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
pkill -f "orchestration_server/bin/server" 2>/dev/null || true
pkill -f "orchestration_dashboard" 2>/dev/null || true
sleep 2

echo "Starting API (Cursor CLI chat + zero-token crew)..."
"$FRAMEWORK_ROOT/scripts/orch/run_server_cursor_cli.sh" > /tmp/orch-api.log 2>&1 &
for i in $(seq 1 45); do
  if curl -sf "http://127.0.0.1:$API_PORT/health" >/dev/null; then break; fi
  sleep 1
done
if ! curl -sf "http://127.0.0.1:$API_PORT/health" >/dev/null; then
  echo "API failed — see /tmp/orch-api.log"
  exit 1
fi
echo "✓ API healthy at http://127.0.0.1:$API_PORT"
echo ""

DASH="$FRAMEWORK_ROOT/tools/orchestration_dashboard"
if [[ "${1:-}" == "--dev" ]]; then
  echo "Starting dashboard (dev/hot-reload)..."
  cd "$DASH"
  flutter run -d chrome --web-port="$WEB_PORT" > /tmp/orch-dashboard.log 2>&1 &
else
  DHASH=$(find "$DASH/lib" "$DASH/web" "$DASH/pubspec.yaml" -type f 2>/dev/null | sort | xargs shasum 2>/dev/null | shasum | cut -c1-12)
  STAMP="$DASH/build/web/.adf-build-hash"
  if [[ ! -f "$STAMP" || "$(cat "$STAMP" 2>/dev/null)" != "$DHASH" ]]; then
    echo "Building dashboard web bundle (one-time for this source version)..."
    (cd "$DASH" && flutter build web --release > /tmp/orch-dashboard-build.log 2>&1)
    echo "$DHASH" > "$STAMP"
  fi
  echo "Serving static dashboard..."
  (cd "$DASH/build/web" && exec python3 -m http.server "$WEB_PORT" --bind 127.0.0.1) > /tmp/orch-dashboard.log 2>&1 &
  disown || true
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ADF Studio is ready"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Dashboard:  http://localhost:$WEB_PORT"
echo "  API:        http://127.0.0.1:$API_PORT"
echo ""
echo "  Paste your prompt at:"
echo "    → http://localhost:$WEB_PORT"
echo ""
echo "  Try: \"Add a loyalty points screen to checkout\""
echo "       Crew runs instantly (zero tokens) · integrity chain seals artifacts"
echo ""
echo "  Logs: /tmp/orch-api.log · /tmp/orch-dashboard.log"
echo "  Dev mode (hot reload): adf studio --dev"
echo ""
