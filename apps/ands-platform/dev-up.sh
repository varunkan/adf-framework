#!/usr/bin/env bash
# ANDS Studio — idempotent local bring-up. Starts only the services that are
# DOWN, so it is safe to run repeatedly (login, cron, or by hand). Each service
# logs to .dev-logs/<name>.log. Run ./dev-down.sh to stop everything.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # apps/ands-platform
VENV="$ROOT/.venv/bin"
LIBS="$ROOT/libs"
LOGS="$ROOT/.dev-logs"
mkdir -p "$LOGS"

export ANDS_INTERNAL_TOKEN="${ANDS_INTERNAL_TOKEN:-ands-mesh-dev-7f3a91}"

up() {  # up <port>  -> 0 if already listening
  lsof -iTCP:"$1" -sTCP:LISTEN -P -n >/dev/null 2>&1
}

svc() {  # svc <name> <port> <reldir> <extra-env...>  -- python uvicorn service
  local name="$1" port="$2" dir="$3"; shift 3
  if up "$port"; then echo "  ✓ $name already up (:$port)"; return; fi
  echo "  ▸ starting $name (:$port)"
  ( cd "$ROOT/services/$dir" && env "$@" \
      ANDS_INTERNAL_TOKEN="$ANDS_INTERNAL_TOKEN" PYTHONPATH=".:$LIBS" \
      nohup "$VENV/uvicorn" app.main:app --port "$port" \
      >>"$LOGS/$name.log" 2>&1 & )
}

echo "ANDS Studio — bringing up the mesh…"
svc dossier      8010 dossier      GOVERNANCE_URL=http://127.0.0.1:8012
svc identity     8014 identity     ANDS_OWNER_EMAIL=owner@ands.local ANDS_OWNER_PASSWORD=ands-owner-dev
svc governance   8012 governance
svc transmission 8013 transmission
svc registry     8016 registry
svc lifecycle    8017 lifecycle
svc collaboration 8018 collaboration
svc journey      8011 journey      DOSSIER_URL=http://127.0.0.1:8010 GOVERNANCE_URL=http://127.0.0.1:8012 TRANSMISSION_URL=http://127.0.0.1:8013

# web (Next.js) last — it depends on the BFF URLs above
if up 3000; then
  echo "  ✓ web already up (:3000)"
else
  echo "  ▸ starting web (:3000)"
  ( cd "$ROOT/web" && env \
      ANDS_INTERNAL_TOKEN="$ANDS_INTERNAL_TOKEN" \
      JOURNEY_BFF_URL=http://127.0.0.1:8011 DOSSIER_BFF_URL=http://127.0.0.1:8010 \
      IDENTITY_BFF_URL=http://127.0.0.1:8014 GOVERNANCE_BFF_URL=http://127.0.0.1:8012 \
      REGISTRY_BFF_URL=http://127.0.0.1:8016 LIFECYCLE_BFF_URL=http://127.0.0.1:8017 \
      COLLAB_BFF_URL=http://127.0.0.1:8018 \
      nohup npm run dev >>"$LOGS/web.log" 2>&1 & )
fi

echo "ANDS Studio → http://localhost:3000  (logs: $LOGS)"
