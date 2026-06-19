#!/usr/bin/env python3
"""Health-check the code-review-graph MCP server — the thing that broke silently.

The knowledge graph has TWO surfaces: (1) the plain CLI (`code-review-graph update/
status/detect-changes`) which the editor hooks use, and (2) the **MCP server**
(`code-review-graph serve`) that exposes the query tools (query_graph,
semantic_search_nodes, get_impact_radius, ...) to an AI assistant. The CLI can be
perfectly healthy while the MCP server is DOWN — which is exactly what happened: the
venv had the FastMCP *client* but not *server* support, so `serve` crashed at startup
with `ImportError: FastMCP server support is not installed`, and the assistant lost
the graph without any loud signal.

This check actually STARTS the MCP server, performs the JSON-RPC handshake, and
asserts the core query tools are exposed — so the failure is caught at session start /
in CI instead of being discovered mid-task. Exit 0 = healthy, non-zero = broken (with
the exact fix printed).

    python3 scripts/codereview/crg_healthcheck.py [--repo <root>] [--bin <path>]
"""
import argparse
import json
import os
import subprocess
import sys

# The tools an AI assistant relies on (per CLAUDE.md "use the graph BEFORE Grep").
CORE_TOOLS = [
    "query_graph",
    "semantic_search_nodes",
    "get_impact_radius",
    "detect_changes",
    "get_review_context",
]
FIX_HINT = (
    "FIX: the code-review-graph MCP server needs FastMCP *server* support in its venv.\n"
    "     <venv>/bin/pip install 'fastmcp-slim[server]'   (or 'fastmcp')\n"
    "     then restart the session so Claude Code re-attaches the MCP server."
)


def _repo_root(start):
    # `.git` may be a DIR (normal clone) or a FILE (worktree / submodule — which is
    # the case for adf-framework), so test existence, not isdir, or we walk past it
    # into the parent repo and resolve the wrong venv.
    cur = os.path.dirname(os.path.abspath(start))
    while cur != os.path.dirname(cur):
        if os.path.exists(os.path.join(cur, ".git")):
            return cur
        cur = os.path.dirname(cur)
    return os.path.dirname(os.path.abspath(start))


def _default_bin(repo):
    p = os.path.join(repo, ".venv-codereview", "bin", "code-review-graph")
    return p if os.path.isfile(p) else "code-review-graph"


def handshake_tools(binary, repo, timeout=25):
    """Start `serve`, do the MCP initialize + tools/list handshake, return
    (tool_names, stderr). Raises on a startup crash / no response."""
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "crg-healthcheck", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    stdin = "".join(json.dumps(m) + "\n" for m in msgs)
    try:
        proc = subprocess.run(
            [binary, "serve", "--repo", repo],
            input=stdin, capture_output=True, text=True, timeout=timeout)
        out, err = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
    tools = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("id") == 2 and isinstance(m.get("result"), dict):
            tools = [t.get("name") for t in m["result"].get("tools", [])]
    return tools, err


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=None)
    ap.add_argument("--bin", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv[1:])

    repo = args.repo or _repo_root(__file__)
    binary = args.bin or _default_bin(repo)
    if not (os.path.isfile(binary) or binary == "code-review-graph"):
        print(f"✘ code-review-graph binary not found at {binary}", file=sys.stderr)
        return 2

    try:
        tools, err = handshake_tools(binary, repo)
    except Exception as e:  # noqa: BLE001 — health-check must never crash its caller
        print(f"✘ MCP server failed to start: {e}\n{FIX_HINT}", file=sys.stderr)
        return 1

    missing = [t for t in CORE_TOOLS if t not in tools]
    if not tools:
        tail = "\n".join(err.strip().splitlines()[-4:])
        print(f"✘ MCP server exposed NO tools (it likely crashed at startup).\n"
              f"  server stderr:\n  {tail}\n{FIX_HINT}", file=sys.stderr)
        return 1
    if missing:
        print(f"✘ MCP server is up but missing core tools: {missing}\n"
              f"  exposed: {sorted(tools)}", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"✔ code-review-graph MCP server healthy — {len(tools)} tools "
              f"(core present: {', '.join(CORE_TOOLS)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
