#!/usr/bin/env bash
# System gate for DAG node N2 (and the react-vite-sqlite stack): the checked-in
# template MUST install, typecheck, build, and boot — serving the SPA at / and a
# health endpoint at /api/health. Exit 0 only if every step passes.
set -uo pipefail
ROOT="${ORCH_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
TPL="$ROOT/templates/react-vite-sqlite"

fail() { echo "GATE FAIL: $*" >&2; exit 1; }

[[ -d "$TPL" ]] || fail "template dir missing: $TPL"
cd "$TPL" || fail "cannot cd $TPL"

echo "== npm ci ==" ; npm ci --no-audit --no-fund >/tmp/tpl-ci.log 2>&1 || { tail -30 /tmp/tpl-ci.log; fail "npm ci"; }
echo "== npm run build (tsc + vite) ==" ; npm run build >/tmp/tpl-build.log 2>&1 || { tail -40 /tmp/tpl-build.log; fail "npm run build"; }
echo "== npm test (vitest) ==" ; npm test >/tmp/tpl-test.log 2>&1 || { tail -40 /tmp/tpl-test.log; fail "npm test"; }

# pick a free port
PORT=$(node -e 'const n=require("net");const s=n.createServer();s.listen(0,()=>{console.log(s.address().port);s.close()})')
echo "== boot on :$PORT ==" ; PORT="$PORT" node server/index.mjs >/tmp/tpl-boot.log 2>&1 &
BOOT_PID=$!
trap 'kill $BOOT_PID 2>/dev/null' EXIT

ok=0
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/" 2>/dev/null || true)
  hcode=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/health" 2>/dev/null || true)
  if [[ "$code" == "200" && "$hcode" == "200" ]]; then ok=1; break; fi
  sleep 0.5
done
[[ "$ok" == "1" ]] || { tail -30 /tmp/tpl-boot.log; fail "server did not serve / (200) and /api/health (200)"; }

echo "GATE PASS: template installs, builds, tests, and boots (/=200, /api/health=200) on :$PORT"
