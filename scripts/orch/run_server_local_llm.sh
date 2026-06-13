#!/usr/bin/env bash
# Start the orchestration API with BOTH dashboard chat and the build runner
# driven by a local Ollama model — no cursor-agent, no cloud key, zero cost.
#
#   chat   -> OllamaBrain          (ORCH_CHAT_LLM=ollama, cursor chat disabled)
#   runner -> scripts/orch/ollama_runner.sh via ADF_RUNNER=custom
#
# Both read the same model from ORCH_OLLAMA_MODEL, so one variable controls the
# whole stack. If unset, we auto-detect the first model installed in Ollama and
# fall back to OllamaBrain's default Nemotron Nano.
set -euo pipefail
FRAMEWORK_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${ORCH_REPO_ROOT:-$(cd "$FRAMEWORK_ROOT/.." && pwd)}"
export ORCH_REPO_ROOT="$ROOT"

# --- Chat: local Ollama only, never cursor-agent --------------------------
export ORCH_CHAT_LLM=ollama
export ORCH_CHAT_USE_CURSOR=0
unset ORCH_CHAT_PREFER_CURSOR 2>/dev/null || true

# --- Runner: drive the 9-phase pipeline with the local Ollama adapter ------
export ADF_RUNNER=custom
export ADF_RUNNER_BIN="${ADF_RUNNER_BIN:-$FRAMEWORK_ROOT/scripts/orch/ollama_runner.sh}"
export ADF_RUNNER_ARGS="${ADF_RUNNER_ARGS:-{prompt} --workspace {workspace}}"

# --- Shared Ollama endpoint + model ---------------------------------------
DEFAULT_MODEL='hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M'
export OLLAMA_HOST="${OLLAMA_HOST:-${ORCH_OLLAMA_HOST:-http://127.0.0.1:11434}}"
export ORCH_OLLAMA_HOST="$OLLAMA_HOST"
if [[ -z "${ORCH_OLLAMA_MODEL:-}" ]]; then
  # 1) Persisted choice in $ROOT/.env (git-ignored, user-editable).
  PERSISTED=""
  if [[ -f "$ROOT/.env" ]]; then
    PERSISTED="$(grep -E '^[[:space:]]*ORCH_OLLAMA_MODEL=' "$ROOT/.env" 2>/dev/null \
      | tail -1 | cut -d= -f2- | sed -e 's/^[\"'\'' ]*//' -e 's/[\"'\'' ]*$//' -e 's/\r$//')"
  fi
  if [[ -n "$PERSISTED" ]]; then
    export ORCH_OLLAMA_MODEL="$PERSISTED"
  else
    # 2) Auto-detect installed models, preferring a coder model; 3) default.
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
fi

# Cloud keys would silently re-route chat off-local; keep this profile offline.
unset GROQ_API_KEY ORCH_LLM_API_KEY OPENAI_API_KEY 2>/dev/null || true

PORT="${ORCH_PORT:-3847}"
echo "Orchestration API (local Ollama chat + runner) on http://127.0.0.1:$PORT"
echo "Repo:   $ORCH_REPO_ROOT"
echo "Ollama: $OLLAMA_HOST"
echo "Model:  $ORCH_OLLAMA_MODEL"
echo "Runner: $ADF_RUNNER_BIN"

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
