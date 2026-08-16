#!/usr/bin/env bash
# Run the ADF implement runner under the headroom venv (Python 3.13) so it can
# `import headroom` to compress bulky self-heal failure logs. Falls back to the
# system python3 (headroom simply unavailable -> compression skipped) when the
# venv is missing, so a fresh checkout still builds.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
FW="$(cd "$HERE/../.." && pwd)"
VENV_PY="$FW/.venv-headroom/bin/python"
if [[ -x "$VENV_PY" ]]; then
  exec "$VENV_PY" "$HERE/agent_runner.py" "$@"
fi
exec python3 "$HERE/agent_runner.py" "$@"
