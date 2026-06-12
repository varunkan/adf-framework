#!/usr/bin/env bash
# ADF comprehensive test suite: unit + coverage + API smoke + dashboard.
set -euo pipefail
ROOT="${ORCH_REPO_ROOT:-$(cd "$(dirname "$0")/../../.." && pwd)}"
API_PORT="${ORCH_PORT:-3847}"
# Coverage ratchet: floors live in coverage_floor.json and only move UP.
# Any drop fails the build; any gain raises the floor automatically.
# Target is 100% — the ratchet guarantees monotonic progress toward it.
FLOOR_FILE="$(cd "$(dirname "$0")" && pwd)/coverage_floor.json"
[ -f "$FLOOR_FILE" ] || echo '{"server": 38.0, "dashboard": 10.0}' > "$FLOOR_FILE"
MIN_SERVER_PCT="${MIN_SERVER_PCT:-$(python3 -c "import json;print(json.load(open('$FLOOR_FILE'))['server'])")}"
MIN_DASH_PCT="${MIN_DASH_PCT:-$(python3 -c "import json;print(json.load(open('$FLOOR_FILE'))['dashboard'])")}"
FAIL=0

ratchet_floor() {
  local key="$1" pct="$2"
  python3 - "$FLOOR_FILE" "$key" "$pct" << 'PY'
import json, sys
path, key, pct = sys.argv[1], sys.argv[2], float(sys.argv[3])
floors = json.load(open(path))
if pct > floors.get(key, 0):
    floors[key] = round(pct, 1)
    json.dump(floors, open(path, 'w'), indent=2)
    print(f"Ratchet: {key} coverage floor raised to {pct:.1f}%")
PY
}

echo "=== ADF Comprehensive Test Suite ==="
echo "Repo: $ROOT"
echo ""

run_server_tests() {
  echo "--- Orchestration server (dart test + coverage) ---"
  cd "$ROOT/adf-framework/tools/orchestration_server"
  rm -rf coverage
  dart test --coverage=coverage
  dart run coverage:format_coverage --lcov --in=coverage --out=coverage/lcov.info --report-on=lib
  python3 << 'PY'
import re
from pathlib import Path
lcov = Path('coverage/lcov.info').read_text()
lf = lh = 0
for line in lcov.splitlines():
    if line.startswith('LF:'): lf += int(line[3:])
    elif line.startswith('LH:'): lh += int(line[3:])
pct = 100*lh/lf if lf else 0
print(f"Server line coverage: {lh}/{lf} = {pct:.1f}%")
open('/tmp/adf_server_cov.txt','w').write(f"{pct:.1f}")
PY
  local pct
  pct=$(cat /tmp/adf_server_cov.txt)
  echo "Target: >= ${MIN_SERVER_PCT}%"
  python3 -c "import sys; sys.exit(0 if float('$pct')>=float('$MIN_SERVER_PCT') else 1)" || { echo "FAIL server coverage (ratchet floor: $MIN_SERVER_PCT%)"; FAIL=1; }
  [ "$FAIL" -eq 0 ] && ratchet_floor server "$pct"
}

run_dashboard_tests() {
  echo ""
  echo "--- Orchestration dashboard (flutter test + coverage) ---"
  cd "$ROOT/adf-framework/tools/orchestration_dashboard"
  flutter test --coverage
  if [ -f coverage/lcov.info ]; then
    python3 << 'PY'
from pathlib import Path
lcov = Path('coverage/lcov.info').read_text()
lf = lh = 0
for line in lcov.splitlines():
    if line.startswith('LF:'): lf += int(line[3:])
    elif line.startswith('LH:'): lh += int(line[3:])
pct = 100*lh/lf if lf else 0
print(f"Dashboard line coverage: {lh}/{lf} = {pct:.1f}%")
open('/tmp/adf_dash_cov.txt','w').write(f"{pct:.1f}")
PY
    local pct
    pct=$(cat /tmp/adf_dash_cov.txt)
    echo "Target: >= ${MIN_DASH_PCT}%"
    python3 -c "import sys; sys.exit(0 if float('$pct')>=float('$MIN_DASH_PCT') else 1)" || { echo "FAIL dashboard coverage (ratchet floor: $MIN_DASH_PCT%)"; FAIL=1; }
    [ "$FAIL" -eq 0 ] && ratchet_floor dashboard "$pct"
  fi
}

run_api_smoke() {
  echo ""
  echo "--- API functionality smoke (port $API_PORT) ---"
  if ! curl -sf "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1; then
    echo "Starting temporary API server..."
    ORCH_REPO_ROOT="$ROOT" ORCH_AUTO_RUNNER=false dart run \
      "$ROOT/adf-framework/tools/orchestration_server/bin/server.dart" >/tmp/adf-smoke-api.log 2>&1 &
    SMOKE_PID=$!
    for i in $(seq 1 15); do
      curl -sf "http://127.0.0.1:$API_PORT/health" >/dev/null && break
      sleep 1
    done
    trap "kill $SMOKE_PID 2>/dev/null || true" EXIT
  fi
  curl -sf "http://127.0.0.1:$API_PORT/health" | python3 -c "import sys,json;d=json.load(sys.stdin); assert d['status']=='ok'; print('health OK')"
  curl -sf "http://127.0.0.1:$API_PORT/features" | python3 -c "import sys,json;d=json.load(sys.stdin); assert 'features' in d; print('features OK', d.get('count',0))"
  curl -sf "http://127.0.0.1:$API_PORT/runner/health" | python3 -c "import sys,json;d=json.load(sys.stdin); print('runner ready:', d.get('ready'))"
  echo "API smoke passed"
}

run_server_tests
run_dashboard_tests
run_api_smoke

echo ""
if [ "$FAIL" -eq 0 ]; then
  echo "=== ALL COMPREHENSIVE TESTS PASSED ==="
else
  echo "=== SOME TESTS FAILED ==="
  exit 1
fi
