#!/usr/bin/env bash
# Start orchestration API with dashboard chat powered by Cursor CLI (cursor-agent).
set -euo pipefail
FRAMEWORK_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT="${ORCH_REPO_ROOT:-$(cd "$FRAMEWORK_ROOT/.." && pwd)}"
export ORCH_REPO_ROOT="$ROOT"
export ORCH_CHAT_USE_CURSOR=1
export ORCH_CHAT_PREFER_CURSOR=1
export ORCH_CHAT_ASYNC=1
export ORCH_CHAT_TIMEOUT_SEC=90
export ORCH_HEADLESS_ASSUME_READY=1
export CURSOR_AGENT_PATH="${CURSOR_AGENT_PATH:-$HOME/.local/bin/cursor-agent}"
unset GROQ_API_KEY ORCH_LLM_API_KEY OPENAI_API_KEY 2>/dev/null || true
PORT="${ORCH_PORT:-3847}"
echo "Orchestration API (Cursor CLI chat) on http://127.0.0.1:$PORT"
echo "Repo: $ORCH_REPO_ROOT"
echo "Agent: $CURSOR_AGENT_PATH"

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
