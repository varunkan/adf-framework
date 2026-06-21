#!/usr/bin/env bash
# Start the orchestration API with dashboard chat and the build runner
# driven by a local Ollama model, with optional hybrid routing to the
# Claude API for complex queries.
#
# Default (ORCH_CHAT_LLM=ollama in .env or unset):
#   chat   -> OllamaBrain only, zero cost
#   runner -> scripts/orch/ollama_runner.sh via ADF_RUNNER=custom
#
# Hybrid  (ORCH_CHAT_LLM=auto + ANTHROPIC_API_KEY set in .env):
#   chat   -> simple queries stay on local Ollama ($0),
#             complex queries route to Claude API (billed)
#   runner -> still local by default; set ADF_RUNNER=claude for Claude Code CLI
#
# All settings are read from $FRAMEWORK_ROOT/.env (git-ignored).
set -euo pipefail
FRAMEWORK_ROOT="${ORCH_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
# The repo root IS the framework dir: the feature store (.cursor/orchestration),
# specs/, and apps/ all live under adf-framework. Defaulting to its PARENT made a
# plain restart point at a stale, unrelated feature set — the user's features
# "vanished". An explicit ORCH_REPO_ROOT still overrides this.
ROOT="${ORCH_REPO_ROOT:-$FRAMEWORK_ROOT}"
export ORCH_REPO_ROOT="$ROOT"

# --- Load persisted config from .env (does not override existing env) ------
_load_env_key() {
  local key="$1"
  [[ -n "${!key:-}" ]] && return 0
  local val=""
  for _ef in "$ROOT/.env" "$FRAMEWORK_ROOT/.env"; do
    [[ -f "$_ef" ]] || continue
    # `|| true`: a key absent from this file makes grep exit 1, which under
    # `set -euo pipefail` would otherwise abort the launcher.
    val="$(grep -E "^[[:space:]]*${key}=" "$_ef" 2>/dev/null \
      | tail -1 | cut -d= -f2- | sed -e 's/^[\"'\'' ]*//' -e 's/[\"'\'' ]*$//' -e 's/\r$//' || true)"
    [[ -n "$val" ]] && break
  done
  # Use if/fi (not `&&`): a trailing `[[ ]] && export` returns 1 when the key
  # is absent, which under `set -e` would abort the launcher at the call site.
  if [[ -n "$val" ]]; then export "$key=$val"; fi
  return 0
}
_load_env_key ORCH_CHAT_LLM
_load_env_key ADF_RUNNER
_load_env_key ANTHROPIC_API_KEY
_load_env_key NVIDIA_API_KEY

# --- Chat: default local Ollama, no cursor-agent --------------------------
export ORCH_CHAT_LLM="${ORCH_CHAT_LLM:-ollama}"
export ORCH_CHAT_USE_CURSOR=0
unset ORCH_CHAT_PREFER_CURSOR 2>/dev/null || true

# --- Headroom-first by default: compress context before every LLM call ------
# Default ON when the venv is present. The build runner (agent_runner.py)
# applies headroom in-process before EVERY backend (NVIDIA/Claude/Ollama). For
# chat, the billed Claude tier is routed through the local headroom proxy —
# auto-started here if not already up, and only used when reachable so Claude
# never breaks if it's down. Disable everything with ADF_HEADROOM=0.
_HB="$FRAMEWORK_ROOT/.venv-headroom/bin/headroom"
_HEADROOM_DEFAULT=0; [[ -x "$_HB" ]] && _HEADROOM_DEFAULT=1
export ADF_HEADROOM="${ADF_HEADROOM:-$_HEADROOM_DEFAULT}"
if [[ "$ADF_HEADROOM" == "1" || "$ADF_HEADROOM" == "true" ]]; then
  _HR_PORT="${HEADROOM_PORT:-8787}"
  _HR_URL="${HEADROOM_PROXY_URL:-http://127.0.0.1:$_HR_PORT}"
  if ! curl -sf --max-time 2 "$_HR_URL/livez" >/dev/null 2>&1 && [[ -x "$_HB" ]]; then
    echo "Headroom: starting compression proxy on :$_HR_PORT"
    ( "$_HB" proxy --host 127.0.0.1 --port "$_HR_PORT" >/tmp/headroom-proxy.log 2>&1 & )
    for _i in $(seq 1 12); do curl -sf --max-time 1 "$_HR_URL/livez" >/dev/null 2>&1 && break; sleep 1; done
  fi
  if curl -sf --max-time 2 "$_HR_URL/livez" >/dev/null 2>&1; then
    export ANTHROPIC_BASE_URL="$_HR_URL"
    echo "Headroom: ON — runner in-process + Claude chat via $_HR_URL"
  else
    echo "Headroom: ON for runner (in-process); Claude proxy unavailable — Claude chat direct"
  fi
fi

# --- Runner: file-writing agent that actually implements code --------------
# agent_runner.py loads the crew's spec, asks a capable model (free NVIDIA NIM
# by default, Claude/Ollama fallback) for a complete app, writes the files, and
# self-heals: it runs the generated tests and feeds failures back until they
# pass. ollama_runner.sh (text-only, no file writes) remains for chat-style use.
export ADF_RUNNER="${ADF_RUNNER:-custom}"
# Use the headroom wrapper (runs the runner under the .venv-headroom Python 3.13
# so it can compress self-heal failure logs); it falls back to system python3
# when the venv is absent. Set ADF_RUNNER_BIN to agent_runner.py to bypass.
export ADF_RUNNER_BIN="${ADF_RUNNER_BIN:-$FRAMEWORK_ROOT/scripts/orch/agent_runner_headroom.sh}"
# NOTE: do not write `${ADF_RUNNER_ARGS:-{prompt} ...}` — the `}` in `{prompt}`
# closes the `${...}` early, yielding the broken `{prompt --workspace ...`.
# Set the default in a separate, single-quoted assignment instead.
if [[ -z "${ADF_RUNNER_ARGS:-}" ]]; then
  ADF_RUNNER_ARGS='{prompt} --workspace {workspace}'
fi
export ADF_RUNNER_ARGS
# The self-heal loop runs several model calls + test runs; give it room (the
# server's per-run budget defaults to 30s, which would kill it mid-build).
export ORCH_RUNNER_TIMEOUT_SEC="${ORCH_RUNNER_TIMEOUT_SEC:-600}"
# The file-writing runner self-heals INTERNALLY (ADF_RUNNER_FIX_ITERS, default 3).
# The Dart layer also re-spawns it after a hard failure; 3 outer attempts means a
# transient failure (a flaky model turn, a cold npm cache) keeps retrying instead
# of giving up after one — what the "build stopped after 1 attempt" report hit.
export ORCH_MAX_HEAL_ATTEMPTS="${ORCH_MAX_HEAL_ATTEMPTS:-3}"

# Track-aware approval (see FeatureStore.autoApprove): with the default `true`, only
# track-S MICRO-FIXES (≤1 file) auto-flow straight to a finished app; tracks M/L/XL
# (net-new / cross-cutting work) HOLD for human confirmation of the spec — so ADF can
# never barrel to implementation on unconfirmed requirements. `=all` forces auto for
# every track (power user); `=false` requires a human on every track. Per-feature
# `auto_approve` overrides this. Proof/policy/audit artifacts are produced regardless.
export ORCH_AUTO_APPROVE="${ORCH_AUTO_APPROVE:-true}"

# New features build the real React+Vite+Tailwind+SQLite app by default (not the
# single-file stdlib fallback). Override per-feature in the dashboard or with
# ADF_DEFAULT_STACK=stdlib.
export ADF_DEFAULT_STACK="${ADF_DEFAULT_STACK:-react-vite-sqlite}"

# --- Requirements crew: the DEFAULT spec engine (CREW-1) ----------------------
# ADF researches the prompt + any reference links and drafts REAL EARS requirements
# via the multi-agent crew (free NVIDIA NIM by default; Claude/Ollama fallback),
# instead of the zero-token deterministic template engine that produced garbage
# "SHALL <verbatim prompt>" specs. ON by default for net-new / cross-cutting tracks
# (M/L/XL), OFF for a track-S micro-fix; when no model is reachable the run falls
# back to the deterministic engine (DISCLOSED via spec_source, never silent).
# Override (else the server resolves the track-aware default):
#   ADF_REQUIREMENTS_CREW=0  → force the deterministic engine (no model calls)
#   ADF_REQUIREMENTS_CREW=1  → force the crew on EVERY track (including S)
if [[ -n "${ADF_REQUIREMENTS_CREW:-}" ]]; then export ADF_REQUIREMENTS_CREW; fi

# --- Shared Ollama endpoint + model ---------------------------------------
DEFAULT_MODEL='hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M'
export OLLAMA_HOST="${OLLAMA_HOST:-${ORCH_OLLAMA_HOST:-http://127.0.0.1:11434}}"
export ORCH_OLLAMA_HOST="$OLLAMA_HOST"
_load_env_key ORCH_OLLAMA_MODEL
if [[ -z "${ORCH_OLLAMA_MODEL:-}" ]]; then
  # Auto-detect installed models, preferring a coder model; fall back to default.
  DETECTED="$(curl -sf "${OLLAMA_HOST%/}/api/tags" 2>/dev/null \
    | python3 -c 'import sys,json
try:
    names=[m["name"] for m in (json.load(sys.stdin).get("models") or [])]
except Exception:
    names=[]
coder=[n for n in names if "coder" in n.lower() or "code" in n.lower()]
print((coder or names or [""])[0])' 2>/dev/null || true)"
  export ORCH_OLLAMA_MODEL="${DETECTED:-$DEFAULT_MODEL}"
fi

# Non-Anthropic cloud keys would silently re-route the HTTP-LLM chat path
# off-local; clear them. ANTHROPIC_API_KEY is kept — the model router uses it
# only when ORCH_CHAT_LLM=auto, and degrades to local-only when it is empty.
unset GROQ_API_KEY ORCH_LLM_API_KEY OPENAI_API_KEY 2>/dev/null || true

PORT="${ORCH_PORT:-3847}"
CHAT_LABEL="local Ollama"
if [[ "$ORCH_CHAT_LLM" == "auto" ]]; then
  CLOUDS=()
  [[ -n "${NVIDIA_API_KEY:-}" ]] && CLOUDS+=("NVIDIA NIM (free)")
  [[ -n "${ANTHROPIC_API_KEY:-}" ]] && CLOUDS+=("Claude")
  if [[ ${#CLOUDS[@]} -gt 0 ]]; then
    CHAT_LABEL="hybrid (Ollama + $(IFS=' + '; echo "${CLOUDS[*]}"))"
  else
    CHAT_LABEL="auto (local-only — set NVIDIA_API_KEY (free) or ANTHROPIC_API_KEY)"
  fi
fi
echo "Orchestration API on http://127.0.0.1:$PORT"
echo "Repo:   $ORCH_REPO_ROOT"
echo "Chat:   $CHAT_LABEL"
echo "Ollama: $OLLAMA_HOST"
echo "Model:  $ORCH_OLLAMA_MODEL"
echo "Runner: ${ADF_RUNNER} (${ADF_RUNNER_BIN##*/})"

if ! curl -sf "${OLLAMA_HOST%/}/api/tags" >/dev/null 2>&1; then
  echo "WARN: Ollama not reachable at $OLLAMA_HOST — start it with 'ollama serve'" >&2
  echo "      and pull a model once, e.g. 'ollama pull $ORCH_OLLAMA_MODEL'." >&2
fi

# AOT-compile the server once per source change: ~15s JIT startup -> <1s.
SRV="$FRAMEWORK_ROOT/tools/orchestration_server"
HASH=$(find "$SRV/bin" "$SRV/lib" "$SRV/pubspec.yaml" -name '*.dart' -o -name 'pubspec.yaml' 2>/dev/null | sort | xargs shasum 2>/dev/null | shasum | cut -c1-12)
EXE="$SRV/build/server-$HASH"
if [[ ! -x "$EXE" ]]; then
  echo "Compiling server (one-time for this source version)..."
  mkdir -p "$SRV/build"
  rm -f "$SRV"/build/server-* 2>/dev/null || true
  (cd "$SRV" && dart compile exe bin/server.dart -o "$EXE" >/dev/null)
fi
echo "Starting AOT server: $EXE"
exec "$EXE"
