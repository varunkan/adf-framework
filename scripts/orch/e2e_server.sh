#!/usr/bin/env bash
# P5 — a REAL HTTP-server E2E: boot the actual orchestration server, drive the
# requirements create-with-sources path over HTTP, and assert it persists + reads
# back. Closes the audit's "E2E weak — no server test" gap. The crew's spec quality
# is proven separately by the live 577s run; this proves the SERVER path.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PORT="${ORCH_PORT:-3999}"
TMP="$(mktemp -d)"
LOG=/tmp/p5_server.log
FID="p5-e2e"
fail=0

cleanup() { kill "${SRV:-0}" 2>/dev/null; wait "${SRV:-0}" 2>/dev/null; rm -rf "$TMP"; }
trap cleanup EXIT

# Free the port of any stale listener (a prior run's server still shutting down).
lsof -ti "tcp:$PORT" 2>/dev/null | xargs kill -9 2>/dev/null; sleep 0.5

echo "[p5] booting the real server on :$PORT (repoRoot=$TMP)…"
( cd "$ROOT" && ORCH_PORT="$PORT" ORCH_REPO_ROOT="$TMP" \
    dart run tools/orchestration_server/bin/server.dart ) >"$LOG" 2>&1 &
SRV=$!

# wait for readiness (cold `dart run` compiles first)
ready=0
for _ in $(seq 1 120); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then ready=1; break; fi
  kill -0 "$SRV" 2>/dev/null || { echo "[p5] server died; log:"; tail -20 "$LOG"; exit 1; }
  sleep 0.5
done
[ "$ready" = 1 ] && echo "[p5] /health OK" || { echo "[p5] server never became ready"; tail -20 "$LOG"; exit 1; }

echo "[p5] POST /features (with reference-link source)…"
CREATE=$(curl -sf -X POST "http://127.0.0.1:$PORT/features" \
  -H 'Content-Type: application/json' \
  -d "{\"id\":\"$FID\",\"requirement\":\"Build a URL shortener\",\"track\":\"S\",\"stack\":\"stdlib\",\"sources\":[{\"url\":\"https://en.wikipedia.org/wiki/URL_shortening\"}]}") \
  || { echo "[p5] POST /features failed"; exit 1; }
echo "[p5] created id: $(echo "$CREATE" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("id"))')"

echo "[p5] GET /features/$FID (read it back over HTTP)…"
# curl -sf already 404s as failure; assert the detail is a non-trivial JSON object.
DETAIL=$(curl -sf "http://127.0.0.1:$PORT/features/$FID") || { echo "[p5] GET 404/failed"; exit 1; }
OK=$(echo "$DETAIL" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("ok" if isinstance(d,dict) and len(d)>=3 else "")')
[ "$OK" = ok ] && echo "[p5] feature readable over HTTP ✓" || { echo "[p5] detail not a valid payload"; fail=1; }

echo "[p5] sources persisted to disk where the crew reads them?"
# Prefix-agnostic: the orchestration root may resolve to .cursor/.claude/orchestration.
SRC="$(find "$TMP" -path "*/features/$FID/sources.json" 2>/dev/null | head -1)"
if [ -n "$SRC" ] && grep -q "URL_shortening" "$SRC"; then
  echo "[p5] sources.json persisted ✓ → $(cat "$SRC")"
else
  echo "[p5] sources.json MISSING/empty ✗"; fail=1
fi

echo "[p5] listed in GET /features?"
curl -sf "http://127.0.0.1:$PORT/features" | grep -q "$FID" && echo "[p5] listed ✓" || { echo "[p5] not listed ✗"; fail=1; }

[ "$fail" = 0 ] && echo "=== P5 SERVER E2E PASSED ===" || echo "=== P5 SERVER E2E FAILED ==="
exit $fail
