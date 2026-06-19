# code-review-graph (the knowledge graph) — how it's wired

A persistent, incremental knowledge graph of THIS repo's source (1399 nodes / 13k
edges / 250 files across dart, python, ts/tsx, sql, bash). It is a **developer-
productivity layer for building ADF** — it is deliberately **not** part of the
product's prompt→app build pipeline (which stays $0/offline/self-contained). The
runner/crew/server never call it.

## Two surfaces (this distinction is why it broke silently)

| Surface | Command | Used by | Needs |
|---|---|---|---|
| **CLI** | `code-review-graph update / status / detect-changes` | the editor **hooks** | FastMCP client only |
| **MCP server** | `code-review-graph serve` (stdio) | the **AI assistant** (query tools) | FastMCP **server** support |

The CLI can be perfectly healthy while the MCP server is down — so the assistant can
lose `query_graph` / `semantic_search_nodes` / `get_impact_radius` / `detect_changes`
/ `get_review_context` with no loud signal.

## Wired at each step

- **Per edit** — `.claude/settings.json` `PostToolUse` (Edit|Write|Bash) runs
  `code-review-graph update --skip-flows` → the graph re-indexes after every change.
- **Per session start** — `SessionStart` runs `code-review-graph status`.
- **MCP query tools** — `.mcp.json` registers `code-review-graph serve` (stdio); Claude
  Code attaches it at session start and exposes the query tools. CLAUDE.md mandates
  using them BEFORE Grep/Glob.
- **Review** — `code-review-graph detect-changes` gives risk-scored change analysis
  (changed functions, test gaps) — works from the CLI, no MCP needed.

## The failure (2026-06-19) and the fix

`code-review-graph serve` crashed at startup —
`ImportError: FastMCP server support is not installed` — because the venv had the
FastMCP *client* but not *server* support. The MCP tools never attached this session.

```bash
bash scripts/codereview/setup.sh     # installs the server extra + verifies, then RESTART
```

## Verify (anytime, no MCP needed to run the check)

```bash
python3 scripts/codereview/crg_healthcheck.py   # exit 0 = MCP server healthy, 1 = broken
```

It starts `serve`, performs the MCP handshake, and asserts the core query tools are
exposed — so a broken graph surfaces immediately instead of mid-task. Recommended:
add it to the `SessionStart` hook (after `status`) so the breakage can never be silent
again:

```jsonc
// .claude/settings.json → hooks.SessionStart[0].hooks, append:
{ "type": "command",
  "command": "python3 scripts/codereview/crg_healthcheck.py --quiet || echo 'code-review-graph MCP DOWN — run scripts/codereview/setup.sh'",
  "timeout": 30 }
```
