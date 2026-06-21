#!/usr/bin/env bash
# ADF preflight — one green/red readout before you launch the studio.
# Checks toolchain, runner, ports, ollama, and all the filesystem/config bits
# that `adf doctor` + a real feature run depend on. Read-only; changes nothing.
#
# Usage:
#   ./adf-framework/scripts/preflight.sh            # auto-detect project root
#   ./adf-framework/scripts/preflight.sh -t /path   # explicit target
#   ./adf-framework/scripts/preflight.sh --runner ollama   # check a specific runner
set -uo pipefail

# ---- locate framework + project --------------------------------------------
FW="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${ORCH_REPO_ROOT:-}"
WANT_RUNNER=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -t|--target) TARGET="$2"; shift 2 ;;
    --runner)    WANT_RUNNER="$2"; shift 2 ;;
    -h|--help)   echo "Usage: $0 [-t TARGET] [--runner claude|ollama|custom]"; exit 0 ;;
    *) TARGET="$1"; shift ;;
  esac
done
# Default target: the dir that contains this framework (works for the in-repo copy).
[[ -z "$TARGET" ]] && TARGET="$(cd "$FW/.." && pwd)"
TARGET="$(cd "$TARGET" && pwd)"

# ---- pretty counters --------------------------------------------------------
PASS=0; WARN=0; FAILN=0
ok()   { printf '  \033[32mOK\033[0m   %s\n' "$1"; PASS=$((PASS+1)); }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$1"; WARN=$((WARN+1)); }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAILN=$((FAILN+1)); }
have() { command -v "$1" >/dev/null 2>&1; }

# Port check that works on macOS (lsof) or Linux (ss), best-effort.
port_busy() {
  local p="$1"
  if have lsof; then lsof -iTCP:"$p" -sTCP:LISTEN -n -P >/dev/null 2>&1; return $?; fi
  if have ss;   then ss -ltn 2>/dev/null | grep -q ":$p "; return $?; fi
  return 2  # unknown
}

echo "=== ADF preflight ==="
echo "Framework: $FW ($(cat "$FW/VERSION" 2>/dev/null || echo '?'))"
echo "Project:   $TARGET"

# ---- 1. toolchain -----------------------------------------------------------
echo ""
echo "[1] Toolchain"
have git    && ok "git: $(git --version | awk '{print $3}')" || bad "git missing"
if have dart; then ok "dart: $(dart --version 2>&1 | awk '{print $4}')"; else bad "dart missing — install Dart SDK (brew install dart-sdk) or via Flutter"; fi
if have flutter; then ok "flutter present"; else warn "flutter missing — needed for dashboard + coverage/lint gates (install: flutter.dev)"; fi
have python3 && ok "python3: $(python3 -V 2>&1 | awk '{print $2}')" || bad "python3 missing (CLI summaries + gates need it)"
have curl && ok "curl present" || warn "curl missing (adf health/feature verbs use it)"

# ---- 2. runner backend ------------------------------------------------------
echo ""
echo "[2] Runner"
RUNNER_SEL="$WANT_RUNNER"
if [[ -z "$RUNNER_SEL" && -f "$TARGET/.adf/runner.env" ]]; then
  RUNNER_SEL="$(grep -E '^ADF_RUNNER=' "$TARGET/.adf/runner.env" | head -1 | cut -d= -f2)"
fi
if [[ -f "$TARGET/.adf/runner.env" ]]; then
  ok ".adf/runner.env present (ADF_RUNNER=${RUNNER_SEL:-auto})"
else
  warn "no .adf/runner.env — run: $FW/install/write_runner_env.sh \"$TARGET\" ollama"
fi
case "${RUNNER_SEL:-auto}" in
  ollama)
    if have ollama; then
      ok "ollama installed"
      if ollama list 2>/dev/null | tail -n +2 | grep -q .; then
        ok "ollama has model(s): $(ollama list 2>/dev/null | awk 'NR>1{print $1}' | head -3 | paste -sd, -)"
      else
        warn "ollama has no models — pull one, e.g. ollama pull hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M"
      fi
    else
      bad "runner=ollama but 'ollama' not installed (brew install ollama)"
    fi ;;
  claude)  have claude && ok "claude (Claude Code) on PATH" || bad "runner=claude but 'claude' missing (npm i -g @anthropic-ai/claude-code)" ;;
  custom)  ok "runner=custom (ensure ADF_RUNNER_BIN points at your agent)" ;;
  auto|*)  warn "runner=auto — will probe custom→claude at start; install at least one" ;;
esac

# ---- 3. ports ---------------------------------------------------------------
echo ""
echo "[3] Ports"
for p in 3847 3848; do
  case "$(port_busy "$p"; echo $?)" in
    0) bad  "port $p in use — free it or set ORCH_PORT (3847=API, 3848=dashboard)" ;;
    1) ok   "port $p free" ;;
    *) warn "port $p — couldn't check (no lsof/ss); verify manually" ;;
  esac
done

# ---- 4. orchestration resolution -------------------------------------------
echo ""
echo "[4] Orchestration paths"
if [[ -f "$FW/lib/resolve_paths.sh" ]]; then
  # shellcheck source=/dev/null
  . "$FW/lib/resolve_paths.sh"
  ( cd "$TARGET"
    if ROOT="$(adf_resolve_repo_root 2>/dev/null)"; then
      printf '  \033[32mOK\033[0m   repo root: %s\n' "$ROOT"
      ORCH="$(adf_orchestration_dir "$ROOT")"
      if [[ -d "$ORCH" ]]; then printf '  \033[32mOK\033[0m   orchestration dir: %s\n' "$ORCH"
      else printf '  \033[33mWARN\033[0m orchestration dir missing: %s\n' "$ORCH"; fi
      [[ -f "$ROOT/.adf-install.json" ]] && printf '  \033[32mOK\033[0m   .adf-install.json present\n' \
        || printf '  \033[33mWARN\033[0m no .adf-install.json (fine if using .cursor/orchestration)\n'
    else
      printf '  \033[31mFAIL\033[0m no orchestration found — run: adf install -t "%s" -i cursor\n' "$TARGET"
    fi )
else
  bad "resolve_paths.sh missing from framework"
fi

# ---- 5. gate prerequisites (real feature run) ------------------------------
echo ""
echo "[5] Gate prerequisites"
[[ -f "$TARGET/pubspec.yaml" ]] && ok "pubspec.yaml ($(grep -m1 '^name:' "$TARGET/pubspec.yaml" | awk '{print $2}'))" || warn "no pubspec.yaml (not a Flutter/Dart project?)"
[[ -d "$TARGET/testcases" ]] && ok "testcases/ ($(find "$TARGET/testcases" -name '*.dart' 2>/dev/null | wc -l | tr -d ' ') files)" || warn "no testcases/ — coverage gate needs: flutter test testcases/ --coverage"
[[ -f "$TARGET/coverage/lcov.info" ]] && ok "coverage/lcov.info present" || warn "no coverage/lcov.info yet (generated on first 'adf test' — expected)"

# ---- 6. server / dashboard integrity ---------------------------------------
echo ""
echo "[6] Server & dashboard"
[[ -f "$FW/tools/orchestration_server/bin/server.dart" ]] && ok "server entrypoint present" || bad "missing tools/orchestration_server/bin/server.dart"
[[ -d "$FW/tools/orchestration_server/.dart_tool" ]] && ok "server deps fetched (.dart_tool)" || warn "run once: (cd $FW/tools/orchestration_server && dart pub get)"
[[ -d "$FW/tools/orchestration_dashboard" ]] && ok "dashboard project present" || warn "no dashboard project"

# ---- 7. secrets hygiene (light) --------------------------------------------
echo ""
echo "[7] Secrets hygiene"
if [[ -f "$FW/.env" ]]; then
  if git -C "$FW" ls-files --error-unmatch .env >/dev/null 2>&1; then
    bad ".env is TRACKED by git — it holds live keys; untrack: git rm --cached .env"
  else
    ok ".env present and git-ignored (not committed)"
  fi
else
  warn "no .env (free tiers still work; create from install/runner.env.example for keys)"
fi

# ---- summary ----------------------------------------------------------------
echo ""
echo "=== summary: $PASS ok, $WARN warn, $FAILN fail ==="
if [[ $FAILN -gt 0 ]]; then
  echo "→ Fix FAIL items before launching. Then: adf doctor && adf test && adf studio"
  exit 1
elif [[ $WARN -gt 0 ]]; then
  echo "→ Good to go; WARN items are first-run setup. Next: adf test && adf studio"
  exit 0
else
  echo "→ All green. Launch: adf studio"
  exit 0
fi
