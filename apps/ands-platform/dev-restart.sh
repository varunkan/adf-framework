#!/usr/bin/env bash
# Full FRESH restart of the ANDS Studio mesh — GUARANTEES running code == HEAD.
#
# Why this exists: dev-up.sh is idempotent (it skips a port that is already
# listening), so it will NOT replace a stale process started days ago — that is
# exactly how the mesh ends up serving old code. This force-stops everything,
# starts fresh, health-checks, and PROVES the fresh dossier serves the new forms
# before returning. It always brings :3000 back up (the "my ui is gone" guard).
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # apps/ands-platform
PORTS="3000 8010 8011 8012 8013 8014 8016 8017 8018"
TOKEN="${ANDS_INTERNAL_TOKEN:-ands-mesh-dev-7f3a91}"

echo "== 1/5  stopping the mesh =="
"$ROOT/dev-down.sh" || true

echo "== 2/5  force-freeing ports (SIGTERM is async; kill survivors + reloader children) =="
for port in $PORTS; do
  for _ in $(seq 1 20); do
    pids=$(lsof -tiTCP:"$port" -sTCP:LISTEN -P -n 2>/dev/null)
    [ -z "$pids" ] && break
    kill -9 $pids 2>/dev/null || true
    sleep 0.3
  done
  # belt-and-suspenders for uvicorn --reload (supervisor + worker child)
  pkill -9 -f "uvicorn app.main:app --port $port" 2>/dev/null || true
done
sleep 1   # let the OS release the sockets

echo "== 3/5  starting fresh =="
"$ROOT/dev-up.sh"

echo "== 4/5  waiting for backends to be healthy =="
allok=1
for port in 8010 8011 8012 8013 8014 8016 8017 8018; do
  ok=""
  for _ in $(seq 1 40); do
    code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$port/health" 2>/dev/null)
    [ "$code" = "200" ] && { ok=1; break; }
    sleep 0.5
  done
  if [ -n "$ok" ]; then echo "  ✓ :$port healthy"; else echo "  ✗ :$port NOT healthy — tail $ROOT/.dev-logs"; allok=0; fi
done

echo "== 5/5  PROOF the FRESH dossier serves the new forms (§1.3.1 Product Monograph) =="
proof=$(curl -s -H "X-Internal-Auth: $TOKEN" \
  "http://127.0.0.1:8010/api/dossier/section-form-schema/1.3.1" 2>/dev/null)
echo "$proof" | "$ROOT/.venv/bin/python" -c "import json,sys
try:
    s=(json.load(sys.stdin).get('schema') or {})
    n=len(s.get('fields') or [])
    print(f\"  PM title: {s.get('title')} | generator: {s.get('generator')} | fields: {n}\")
    sys.exit(0 if (s.get('generator')=='pm_xml' and n>=17) else 3)
except Exception as e:
    print('  PROOF FAILED to parse response:', repr(e)); sys.exit(3)" 2>&1
proofrc=${PIPESTATUS[1]:-$?}

# the 'my ui is gone' guardrail — never finish with the web down
webok=""
for _ in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:3000/login" 2>/dev/null)
  [ "$code" = "200" ] && { webok=1; break; }
  sleep 1
done
[ -n "$webok" ] && echo "  ✓ web :3000 up (HTTP 200 /login)" || echo "  ✗ web :3000 NOT up — tail $ROOT/.dev-logs/web.log"

echo "== DONE.  Owner login: owner@ands.local / ands-owner-dev  (logs: $ROOT/.dev-logs) =="
{ [ "$allok" = 1 ] && [ "$proofrc" = 0 ] && [ -n "$webok" ]; } && exit 0 || exit 1
