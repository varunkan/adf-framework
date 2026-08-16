#!/usr/bin/env bash
# One-shot installer: make `/adf` invokable in Claude Code from this repo.
#   - ensures .adf/secrets.env exists (from the committed example) WITHOUT clobbering real keys
#   - discovers the claude binary (no version pin)
#   - verifies the prebuilt server + dashboard, rebuilding them if the toolchain is present
#   - confirms the /adf skill and the detached launcher are in place
# Idempotent — safe to re-run.
set -uo pipefail
FW="$(cd "$(dirname "$0")/.." && pwd)"
cd "$FW"
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }

echo "ADF installer — wiring /adf for Claude Code"
echo "Framework root: $FW"
echo

# 1. Secrets (never overwrite an existing real file)
if [ -f .adf/secrets.env ]; then
  ok ".adf/secrets.env already present (left untouched)"
elif [ -f .adf/secrets.env.example ]; then
  mkdir -p .adf && cp .adf/secrets.env.example .adf/secrets.env
  ok "created .adf/secrets.env from template — edit it to add your keys"
else
  err ".adf/secrets.env.example missing — cannot seed secrets"
fi

# 2. claude binary (version-independent discovery — mirrors run_studio_capable.sh)
CB="${ADF_CLAUDE_PATH:-$(command -v claude 2>/dev/null || true)}"
[ -z "$CB" ] && CB="$(ls -t "$HOME/Library/Application Support/Claude/claude-code/"*/claude.app/Contents/MacOS/claude 2>/dev/null | head -1 || true)"
if [ -n "$CB" ] && [ -x "$CB" ]; then ok "claude binary: $CB"
else warn "claude binary not found — Claude runner unavailable (NVIDIA fallback still works)"; fi

# 3. Prebuilt artifacts (rebuild only if a toolchain is available)
SRV="tools/orchestration_server/build/server-fix"
WEB="tools/orchestration_dashboard/build/web/index.html"
if [ -x "$SRV" ]; then ok "server binary present: $SRV"
elif command -v dart >/dev/null 2>&1; then
  warn "server binary missing — building (dart compile exe)…"
  ( cd tools/orchestration_server && dart pub get >/dev/null 2>&1 && dart compile exe bin/server.dart -o build/server-fix >/dev/null 2>&1 ) \
    && ok "server built" || err "server build failed — run manually in tools/orchestration_server"
else err "$SRV missing and dart not installed — install Dart or drop in a prebuilt binary"; fi
if [ -f "$WEB" ]; then ok "dashboard web bundle present"
elif command -v flutter >/dev/null 2>&1; then
  warn "dashboard bundle missing — building (flutter build web)…"
  ( cd tools/orchestration_dashboard && flutter build web >/dev/null 2>&1 ) \
    && ok "dashboard built" || err "dashboard build failed — run flutter build web in tools/orchestration_dashboard"
else err "$WEB missing and flutter not installed"; fi

# 4. Fallback-runner venv
if [ -x .venv-headroom/bin/python ]; then ok "fallback-runner venv present (.venv-headroom)"
else warn ".venv-headroom missing — the NVIDIA fallback runner needs it; run the repo venv bootstrap if you plan to use it"; fi

# 5. Skill + launcher
[ -f .claude/skills/adf/skill.md ] && ok "/adf skill installed (.claude/skills/adf/skill.md)" || err ".claude/skills/adf/skill.md missing"
if [ -f scripts/orch/adf_studio_up.sh ]; then
  chmod +x scripts/orch/adf_studio_up.sh 2>/dev/null || true
  ok "detached launcher present (scripts/orch/adf_studio_up.sh)"
else err "scripts/orch/adf_studio_up.sh missing"; fi

echo
echo "Done. Open a NEW Claude Code session in this repo and type:  /adf"
echo "For the Claude-CLI runner ( \$0/token ), run 'claude setup-token' and put the"
echo "token in .adf/secrets.env as CLAUDE_CODE_OAUTH_TOKEN, then re-run /adf."
