#!/usr/bin/env bash
# Write .adf/runner.env selecting the agent runner that drives the
# orchestration server. Source this file before `adf start`:
#   set -a; . .adf/runner.env; set +a
set -euo pipefail

TARGET="$1"
RUNNER="${2:-auto}"
mkdir -p "$TARGET/.adf"
ENV_FILE="$TARGET/.adf/runner.env"

case "$RUNNER" in
  cursor)
    cat > "$ENV_FILE" << 'ENV'
# ADF runner: Cursor CLI (cursor-agent)
ADF_RUNNER=cursor
# Optional unattended auth (else run: cursor-agent login)
# CURSOR_API_KEY=...
ENV
    ;;
  claude)
    cat > "$ENV_FILE" << 'ENV'
# ADF runner: Claude Code CLI (claude)
ADF_RUNNER=claude
# Optional unattended auth (else run: claude login)
# ANTHROPIC_API_KEY=...
# Override binary location if not on PATH:
# ADF_CLAUDE_PATH=/usr/local/bin/claude
ENV
    ;;
  ollama)
    # The Ollama wrapper ships with the framework; point ADF_RUNNER_BIN at it.
    FRAMEWORK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
    cat > "$ENV_FILE" << ENV
# ADF runner: local Ollama model (zero marginal cost, fully offline)
# Driven through the custom-runner contract via the bundled wrapper.
ADF_RUNNER=custom
ADF_RUNNER_BIN="$FRAMEWORK_ROOT/scripts/orch/ollama_runner.sh"
ADF_RUNNER_ARGS="{prompt} --workspace {workspace}"
ADF_RUNNER_KILL_PATTERN="ollama_runner.sh"
# Model and host (defaults shown). Pull the model once: ollama pull llama3.2
# ORCH_OLLAMA_MODEL=llama3.2
# OLLAMA_HOST=http://127.0.0.1:11434
ENV
    ;;
  custom)
    cat > "$ENV_FILE" << 'ENV'
# ADF runner: any agent CLI. Placeholders {prompt} and {workspace} are
# substituted at run time. {prompt} is always passed as a single argument.
ADF_RUNNER=custom
ADF_RUNNER_BIN="/path/to/your-agent"
ADF_RUNNER_ARGS="-p {prompt} --cwd {workspace}"
# ADF_RUNNER_API_KEY_ENV="YOUR_AGENT_API_KEY"
# ADF_RUNNER_KILL_PATTERN="your-agent"
ENV
    ;;
  auto|*)
    cat > "$ENV_FILE" << 'ENV'
# ADF runner: auto-detect (custom if configured, else cursor, else claude)
ADF_RUNNER=auto
ENV
    ;;
esac

echo "Wrote $ENV_FILE (ADF_RUNNER=$RUNNER)"
