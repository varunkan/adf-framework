#!/usr/bin/env bash
# Adapt a local Ollama model to ADF's custom-runner contract (zero marginal cost).
# The orchestration server (CustomBackend, ADF_RUNNER=custom) invokes this as:
#   ollama_runner.sh "<prompt>" --workspace <repo-or-worktree>
# per ADF_RUNNER_ARGS="{prompt} --workspace {workspace}".
#
# It POSTs the prompt to the local Ollama HTTP API and emits the single
# stream-json line the server's phase runner parses from stdout:
#   {"type":"result","result":"<model response>"}
#
# Environment:
#   OLLAMA_HOST         Ollama base URL (default http://127.0.0.1:11434)
#   ORCH_OLLAMA_MODEL   model name (default llama3.2; run `ollama pull` first)
#   ORCH_OLLAMA_TIMEOUT_SEC  request timeout in seconds (default 600)
set -euo pipefail

command -v curl >/dev/null 2>&1 || {
  echo "ollama_runner.sh: curl not found on PATH" >&2
  exit 1
}
command -v python3 >/dev/null 2>&1 || {
  echo "ollama_runner.sh: python3 not found on PATH (required for JSON encoding)" >&2
  exit 1
}

PROMPT="${1:-}"
[[ $# -gt 0 ]] && shift
WORKSPACE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      # Accepted for contract compatibility: Ollama is a plain text model with
      # no filesystem or tool access, so the path is context only.
      WORKSPACE="${2:-}"
      shift 2
      ;;
    *) shift ;;
  esac
done

if [[ -z "$PROMPT" ]]; then
  echo "ollama_runner.sh: empty prompt (expected argv template: {prompt} --workspace {workspace})" >&2
  exit 2
fi

HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
case "$HOST" in
  http://*|https://*) ;;
  *) HOST="http://$HOST" ;;
esac
HOST="${HOST%/}"
MODEL="${ORCH_OLLAMA_MODEL:-llama3.2}"

# Build the request body with python3 so the prompt is JSON-escaped correctly.
BODY="$(python3 - "$MODEL" "$PROMPT" "$WORKSPACE" << 'PY'
import json, sys
model, prompt, workspace = sys.argv[1], sys.argv[2], sys.argv[3]
if workspace:
    prompt = f"Workspace (for reference; you have no file access): {workspace}\n\n{prompt}"
print(json.dumps({"model": model, "prompt": prompt, "stream": False}))
PY
)"

RESPONSE_FILE="$(mktemp)"
trap 'rm -f "$RESPONSE_FILE"' EXIT

HTTP_CODE="$(curl -sS -o "$RESPONSE_FILE" -w '%{http_code}' \
  --max-time "${ORCH_OLLAMA_TIMEOUT_SEC:-600}" \
  -H 'Content-Type: application/json' \
  -X POST -d "$BODY" "$HOST/api/generate")" || {
  echo "ollama_runner.sh: cannot reach Ollama at $HOST — start it with 'ollama serve' (and 'ollama pull $MODEL' once)" >&2
  exit 1
}

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "ollama_runner.sh: Ollama at $HOST returned HTTP $HTTP_CODE: $(cat "$RESPONSE_FILE")" >&2
  echo "ollama_runner.sh: hint — is model '$MODEL' pulled? Run: ollama pull $MODEL" >&2
  exit 1
fi

# Extract .response and emit the one-line result event the server parses.
python3 - "$RESPONSE_FILE" << 'PY'
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
except (OSError, ValueError) as exc:
    print(f"ollama_runner.sh: invalid JSON from Ollama: {exc}", file=sys.stderr)
    sys.exit(1)
text = data.get("response")
if not isinstance(text, str) or not text.strip():
    err = data.get("error") or "empty response from Ollama"
    print(f"ollama_runner.sh: {err}", file=sys.stderr)
    sys.exit(1)
print(json.dumps({"type": "result", "result": text}))
PY
