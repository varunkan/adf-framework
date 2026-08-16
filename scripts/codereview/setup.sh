#!/usr/bin/env bash
# Build/repair + verify the code-review-graph MCP server's venv (.venv-codereview) —
# the graph query tools the AI assistant uses (CLAUDE.md: "use the graph BEFORE Grep").
#
# ROOT CAUSE this fixes (2026-06-19): the venv ran Python 3.15, too new for a deep
# dependency — beartype imports `typing.no_type_check_decorator`, REMOVED in 3.15 — so
# `code-review-graph serve` crashed at startup under a misleading "FastMCP server
# support is not installed" message and the assistant silently lost the graph. The CLI
# (update/status/detect-changes doesn't touch beartype) kept working, hiding it.
# Fix: build the venv on a Python the stack supports (3.13/3.12/3.11). The graph DATA
# lives in .code-review-graph/ (outside the venv), so a rebuild preserves it.
#
# Run it yourself (venv installs are sandbox-blocked for the assistant):
#   bash scripts/codereview/setup.sh   # then RESTART the session
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$REPO/.venv-codereview"

# Pick a SUPPORTED Python (avoid 3.15+ until the deps catch up).
PYBIN=""
for cand in python3.13 python3.12 python3.11; do
  if command -v "$cand" >/dev/null 2>&1; then PYBIN="$(command -v "$cand")"; break; fi
done
[ -n "$PYBIN" ] || { echo "✘ need python3.13/3.12/3.11 on PATH (graph deps don't support 3.15 yet)"; exit 1; }
echo "→ using $("$PYBIN" --version 2>&1) at $PYBIN"

# Recreate the venv when missing or on an unsupported Python.
recreate=1
if [ -x "$VENV/bin/python3" ]; then
  pv="$("$VENV/bin/python3" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo '?')"
  case "$pv" in 3.11|3.12|3.13) recreate=0 ;; esac
  [ "$recreate" = 1 ] && echo "→ existing venv is Python $pv (unsupported) — rebuilding"
fi
if [ "$recreate" = 1 ]; then
  rm -rf "$VENV"
  "$PYBIN" -m venv "$VENV"
fi

echo "→ installing code-review-graph (graph engine + MCP server) into the venv"
"$VENV/bin/pip" install -q -U pip
"$VENV/bin/pip" install -q -r "$REPO/scripts/codereview/requirements.txt"

echo "→ verifying the MCP server handshakes + exposes its query tools"
if python3 "$REPO/scripts/codereview/crg_healthcheck.py"; then
  echo
  echo "✅ MCP server healthy. RESTART your session so Claude Code re-attaches it;"
  echo "   then query_graph / semantic_search_nodes / get_impact_radius / etc. are live."
else
  echo
  echo "✘ still unhealthy — see the error above."
  exit 1
fi
