#!/usr/bin/env bash
# Verify ADF orchestration stack installation. Run from repo root.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
FAIL=0
ok() { echo "OK  $1"; }
fail() { echo "FAIL $1"; FAIL=1; }

echo "=== ADF setup verification ==="
echo "Repo: $ROOT"
echo ""

command -v dart >/dev/null && ok "dart" || fail "dart not found"
command -v flutter >/dev/null && ok "flutter" || fail "flutter not found"
command -v curl >/dev/null && ok "curl" || fail "curl not found"
[[ -x scripts/orch/seed_adf_artifacts.sh ]] && ok "scripts/orch executable" || fail "chmod +x scripts/orch/*.sh"

[[ -f .cursor/orchestration/framework-routing.yaml ]] && ok "framework-routing.yaml" || fail "missing routing"
[[ -f tools/orchestration_server/bin/server.dart ]] && ok "orchestration_server" || fail "missing server"
[[ -d tools/orchestration_dashboard/lib ]] && ok "orchestration_dashboard" || fail "missing dashboard"
[[ -f .cursor/skills/orch-orchestrator/SKILL.md ]] && ok "orch-orchestrator skill" || fail "missing orchestrator skill"

if [[ ! -d .agents/skills ]]; then
  echo "WARN .agents/skills missing — install BMAD for full reviewer automation"
fi

echo ""
echo "=== Optional: API (start server first) ==="
if curl -sf http://localhost:3847/health >/dev/null 2>&1; then
  ok "API http://localhost:3847/health"
  curl -sf http://localhost:3847/runner/health | head -c 120 || true
  echo ""
else
  echo "SKIP API not running — start with: ./scripts/start_orchestration_dashboard.sh web"
fi

if curl -sf -o /dev/null http://localhost:3848/ 2>&1; then
  ok "Dashboard http://localhost:3848"
else
  echo "SKIP Dashboard not running"
fi

echo ""
if [[ $FAIL -eq 0 ]]; then
  echo "=== Core checks passed ==="
else
  echo "=== Some checks failed ==="
  exit 1
fi
