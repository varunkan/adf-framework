#!/usr/bin/env bash
# Launch ADF Studio with CAPABLE models:
#   - HIGH / deep-tier tasks + the implement runner -> Claude Opus 4.8 (ultra:
#     adaptive thinking is auto-enabled for claude-opus models)
#   - fast / balanced brain tiers + runner fallback -> NVIDIA Nemotron Ultra (253B, free NIM)
# Keys are read from .adf/secrets.env (gitignored). Fill it in first.
set -euo pipefail
FW="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$FW"

[ -f .adf/secrets.env ] && source .adf/secrets.env
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "ERROR: ANTHROPIC_API_KEY is empty. Fill .adf/secrets.env, then re-run." >&2
  exit 1
fi

# Nemotron Ultra 253B is NOT served on the free NIM account (404). The strongest
# free, working NIM model is Nemotron Super 49B v1.5 (a reasoning model). Opus 4.8
# needs Anthropic API credits — set ADF_USE_OPUS=1 once the account has credit.
NEMOTRON="nvidia/llama-3.3-nemotron-super-49b-v1.5"
USE_OPUS="${ADF_USE_OPUS:-0}"

export ORCH_BRAIN=auto                       # high complexity -> deep, else fast/balanced
export ORCH_PROVIDER_FAST=nvidia
export ORCH_PROVIDER_BALANCED=nvidia
export ORCH_NVIDIA_MODEL_FAST="$NEMOTRON"
export ORCH_NVIDIA_MODEL_BALANCED="$NEMOTRON"

# BOTH auth paths wired; auto-pick the MOST EFFICIENT available runner:
#   1. Claude Code SUBSCRIPTION (CLAUDE_CODE_OAUTH_TOKEN via `claude setup-token`)
#      -> claude backend: Opus quality at ZERO per-token cost. PREFERRED.
#   2. else the custom runner (agent_runner.py): Anthropic API Opus when ADF_USE_OPUS=1
#      + credits, otherwise the free NVIDIA Nemotron Super 49B.
# Override the auto-pick with ADF_RUNNER_PREF=claude|custom.
CLAUDE_BIN="$HOME/Library/Application Support/Claude/claude-code/2.1.181/claude.app/Contents/MacOS/claude"
PREF="${ADF_RUNNER_PREF:-auto}"
if { [ "$PREF" = auto ] && [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -x "$CLAUDE_BIN" ]; } \
   || [ "$PREF" = claude ]; then
  export ADF_RUNNER=claude
  export ADF_CLAUDE_PATH="$CLAUDE_BIN"
  RUNNER_DESC="Claude Code subscription (Opus, \$0/token) — most efficient"
else
  export ADF_RUNNER=custom
  export ADF_RUNNER_BIN="$FW/scripts/orch/agent_runner_headroom.sh"
  export ADF_RUNNER_ARGS='{prompt} --workspace {workspace}'
  export ADF_RUNNER_MODEL="$NEMOTRON"
  if [ -n "${ANTHROPIC_API_KEY:-}" ] && [ "${ADF_USE_OPUS:-0}" = 1 ]; then
    RUNNER_DESC="custom: Anthropic API Opus 4.8 (paid)"
  else
    RUNNER_DESC="custom: NVIDIA Nemotron Super 49B (free)"
  fi
fi
echo "  (runner = $RUNNER_DESC)"

# A Claude Code build is an agent doing many steps — give it real time.
export ORCH_RUNNER_TIMEOUT_SEC="${ORCH_RUNNER_TIMEOUT_SEC:-1800}"
export ADF_NVIDIA_TIMEOUT_SEC="${ADF_NVIDIA_TIMEOUT_SEC:-480}"
export ADF_RUNNER_MAX_TOKENS="${ADF_RUNNER_MAX_TOKENS:-12000}"

if [ "$USE_OPUS" = "1" ] && [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  # Opus available (credits present): deep tier + implement runner lead with Opus 4.8 (ultra thinking)
  export ORCH_PROVIDER_DEEP=anthropic
  export ORCH_MODEL_DEEP=claude-opus-4-8
  export ADF_RUNNER_CLAUDE_MODEL=claude-opus-4-8
  echo "  (Opus 4.8 ENABLED for deep tier + implement)"
else
  # No Opus credits: Nemotron Super 49B everywhere; drop Anthropic so the runner
  # doesn't waste an attempt 400ing on every call.
  unset ANTHROPIC_API_KEY
  export ORCH_PROVIDER_DEEP=nvidia
  export ORCH_NVIDIA_MODEL_DEEP="$NEMOTRON"
fi

# --- Chat LLM: capable too (clarifications/announcements) --------------------
export ORCH_CHAT_LLM=claude

# --- Studio server -----------------------------------------------------------
export ORCH_REPO_ROOT="$FW"
export ORCH_PORT="${ORCH_PORT:-3847}"
export ORCH_AUTO_APPROVE=false               # track M holds at every gate (you watch + approve)

echo "ADF Studio: workhorse=$NEMOTRON | deep=$([ "$USE_OPUS" = 1 ] && echo 'Opus-4.8(ultra)' || echo "$NEMOTRON") | port $ORCH_PORT"
exec "$FW/tools/orchestration_server/build/server-fix"
