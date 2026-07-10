#!/usr/bin/env bash
# End-to-end deploy: Railway (API + Postgres) + Vercel (Next.js UI)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORTAL="$(cd "$ROOT/.." && pwd)"
FRONTEND="$ROOT/frontend"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

info() { echo -e "${GREEN}==>${NC} $*"; }
err()  { echo -e "${RED}ERROR:${NC} $*" >&2; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "Missing $1"; exit 1; }
}

# --- Auth checks -----------------------------------------------------------
NEED_RAILWAY=0
NEED_VERCEL=0

if [ -z "${RAILWAY_TOKEN:-}" ]; then
  if npx --yes @railway/cli whoami >/dev/null 2>&1; then
    info "Railway: using CLI session"
  else
    info "Railway: not authenticated. Run: npx @railway/cli login"
    info "  Or: export RAILWAY_TOKEN=... from https://railway.com/account/tokens"
    NEED_RAILWAY=1
  fi
fi

if [ -z "${VERCEL_TOKEN:-}" ]; then
  if vercel whoami >/dev/null 2>&1; then
    info "Vercel: using CLI session"
    VERCEL_TOKEN=""
  else
    info "Vercel: not authenticated. Run: vercel login"
    info "  Or: export VERCEL_TOKEN=... from https://vercel.com/account/tokens"
    NEED_VERCEL=1
  fi
fi

if [ "$NEED_RAILWAY" = 1 ] || [ "$NEED_VERCEL" = 1 ]; then
  err "Complete login above, then re-run: $0"
  exit 1
fi

railway_cmd() {
  if [ -n "${RAILWAY_TOKEN:-}" ]; then
    RAILWAY_TOKEN="$RAILWAY_TOKEN" npx --yes @railway/cli "$@"
  else
    npx --yes @railway/cli "$@"
  fi
}

vercel_cmd() {
  if [ -n "${VERCEL_TOKEN:-}" ]; then
    npx vercel@50.22.1 "$@" --token="${VERCEL_TOKEN}"
  else
    npx vercel@50.22.1 "$@"
  fi
}

require_cmd npm

# --- Railway backend -------------------------------------------------------
info "Deploying API to Railway from $PORTAL"
cd "$PORTAL"

if [ ! -f .railway/project.json ] && [ -z "${RAILWAY_PROJECT_ID:-}" ]; then
  info "Linking new Railway project (ands-portal)..."
  railway_cmd init -n ands-portal -y
  info "Adding Postgres plugin..."
  railway_cmd add --database postgres -y || true
fi

railway_cmd up --detach -y

info "Waiting for deployment..."
sleep 15

API_URL="${ANDS_API_PUBLIC_URL:-}"
if [ -z "$API_URL" ]; then
  API_URL="$(railway_cmd domain 2>/dev/null | head -1 || true)"
  if [ -n "$API_URL" ] && [[ "$API_URL" != http* ]]; then
    API_URL="https://${API_URL}"
  fi
fi

if [ -z "$API_URL" ]; then
  err "Could not detect API URL. Set ANDS_API_PUBLIC_URL or run: railway domain"
  exit 1
fi

info "API URL: $API_URL"
curl -sf "${API_URL}/api/health" | head -c 200 || err "API health check failed"
echo ""

# Wire DATABASE_URL is automatic when Postgres plugin is linked on Railway.
railway_cmd variables set \
  "CORS_ALLOW_VERCEL_PREVIEWS=true" \
  "S3_ENABLED=false" \
  "ESG_MODE=mock" \
  -y >/dev/null 2>&1 || true

# --- Vercel frontend -------------------------------------------------------
info "Deploying frontend to Vercel"
cd "$FRONTEND"
export NEXT_PUBLIC_API_URL="$API_URL"

if [ ! -d .vercel ]; then
  vercel_cmd link --yes
fi

vercel_cmd deploy --prod --yes --env "NEXT_PUBLIC_API_URL=${API_URL}"

info "Done."
info "  API:  $API_URL"
info "  UI:   check Vercel output above for production URL"
info "Update Railway CORS_ORIGINS if you use a custom domain on Vercel."
