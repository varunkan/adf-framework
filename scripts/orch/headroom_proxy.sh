#!/usr/bin/env bash
# Start the headroom context-compression proxy from the local Python 3.13 venv.
#
# It is an Anthropic/OpenAI-compatible passthrough that compresses bulky context
# (tool outputs, long conversation history, RAG chunks) before forwarding to the
# provider — 60-95% fewer tokens on compressible content, same answers.
#
# Route ADF's billed Claude chat through it:
#   1) start this proxy:            scripts/orch/headroom_proxy.sh
#   2) start the API with:          ADF_HEADROOM=1 adf studio   (or run_server_local_llm.sh)
# which exports ANTHROPIC_BASE_URL=http://127.0.0.1:8787 for the server.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
FW="$(cd "$HERE/../.." && pwd)"
HB="$FW/.venv-headroom/bin/headroom"
PORT="${HEADROOM_PORT:-8787}"
if [[ ! -x "$HB" ]]; then
  echo "headroom not installed. Set it up once with:" >&2
  echo "  uv venv --python 3.13 $FW/.venv-headroom" >&2
  echo "  uv pip install --python $FW/.venv-headroom/bin/python 'git+https://github.com/chopratejas/headroom.git'" >&2
  exit 1
fi
echo "Headroom proxy → http://127.0.0.1:$PORT"
echo "Point ADF at it: ADF_HEADROOM=1 (sets ANTHROPIC_BASE_URL=http://127.0.0.1:$PORT)"
exec "$HB" proxy --host 127.0.0.1 --port "$PORT" "$@"
