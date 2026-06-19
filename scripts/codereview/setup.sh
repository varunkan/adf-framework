#!/usr/bin/env bash
# Repair + verify the code-review-graph MCP server — the graph query tools the AI
# assistant uses (CLAUDE.md: "use the graph BEFORE Grep"). Root cause it fixes: the
# .venv-codereview had the FastMCP *client* but not *server* support, so
# `code-review-graph serve` crashed at startup and the MCP tools never attached —
# while the CLI hooks kept working, hiding the breakage.
#
# Run it yourself (it installs into a venv, which the assistant's sandbox blocks):
#   bash scripts/codereview/setup.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$REPO/.venv-codereview"
PIP="$VENV/bin/pip"

if [ ! -x "$PIP" ]; then
  echo "✘ no code-review-graph venv at $VENV"
  echo "  (re)create it, then re-run this script."
  exit 1
fi

echo "→ installing FastMCP server support into $VENV"
"$PIP" install -q -r "$REPO/scripts/codereview/requirements.txt"

echo "→ verifying the MCP server now handshakes + exposes its query tools"
if python3 "$REPO/scripts/codereview/crg_healthcheck.py"; then
  echo
  echo "✅ MCP server healthy. RESTART your session so Claude Code re-attaches it;"
  echo "   then query_graph / semantic_search_nodes / get_impact_radius / etc. are live."
else
  echo
  echo "✘ still unhealthy — see the error above."
  exit 1
fi
