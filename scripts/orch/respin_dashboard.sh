#!/usr/bin/env bash
set -euo pipefail
FRAMEWORK_ROOT="${ORCH_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
# Repo root defaults to the framework dir (where the feature store, specs/, and
# apps/ live), NOT its parent — otherwise a plain restart points at a stale,
# unrelated feature set and the user's features appear to vanish. Explicit
# ORCH_REPO_ROOT still overrides.
ROOT="${ORCH_REPO_ROOT:-$FRAMEWORK_ROOT}"
export ORCH_REPO_ROOT="$ROOT"
API_PORT="${ORCH_PORT:-3847}"
WEB_PORT="${ORCH_WEB_PORT:-3848}"

# Backend selection. Default: local Ollama (chat + runner).
BACKEND=local
DEV=0
for arg in "$@"; do
  case "$arg" in
    --local)  BACKEND=local ;;
    --dev)    DEV=1 ;;
  esac
done
API_LAUNCHER="run_server_local_llm.sh"
BACKEND_LABEL="local Ollama chat + runner"

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

echo "Starting API ($BACKEND_LABEL)..."
"$FRAMEWORK_ROOT/scripts/orch/$API_LAUNCHER" > /tmp/orch-api.log 2>&1 &
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
if [[ "$DEV" == "1" ]]; then
  echo "Starting dashboard (dev/hot-reload)..."
  cd "$DASH"
  flutter run -d chrome --web-port="$WEB_PORT" > /tmp/orch-dashboard.log 2>&1 &
else
  DHASH=$(find "$DASH/lib" "$DASH/web" "$DASH/pubspec.yaml" -type f 2>/dev/null | sort | xargs shasum 2>/dev/null | shasum | cut -c1-12)
  STAMP="$DASH/build/web/.adf-build-hash"
  if [[ ! -f "$STAMP" || "$(cat "$STAMP" 2>/dev/null)" != "$DHASH" ]]; then
    echo "Building dashboard web bundle (one-time for this source version)..."
    # --pwa-strategy=none: do NOT ship a service worker. Flutter's SW caches the
    # whole app and serves a STALE build after every rebuild — users then see the
    # "same old (broken) dashboard" no matter what changed. No SW = every refresh
    # is the live build. Also drop any SW left over from an older build.
    (cd "$DASH" && flutter build web --release --pwa-strategy=none > /tmp/orch-dashboard-build.log 2>&1)
    rm -f "$DASH/build/web/flutter_service_worker.js"
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
echo "  Backend: $BACKEND_LABEL"
echo "  Dev mode (hot reload): adf studio --dev"
echo ""
