## Working principles (standing directives — apply to EVERY task)

**Plan before executing.** Before acting on any non-trivial instruction, gather
and weigh all data points that bear on it (code, tests, git history, memory,
prior results, live process/env/config state), form an explicit plan, then
execute. Never blind-fire, and never re-derive facts already established.

**Look at all data points that can influence the decision.** Base every call on
the full evidence, not the first signal found. Cross-check independent sources
before asserting a conclusion — e.g. a claim about a running tool is verified via
process + env var + config + health endpoint together, not any one alone.

**Frugal on tokens, never on quality.** Quality, correctness and thoroughness are
non-negotiable and come first — never trade them to save tokens. Within that,
minimize token WASTE: no redundant reads, no re-running finished work, no
re-explaining settled points, no bloated output. Frugality cuts waste, not the
work that produces a correct, complete result. Prefer the graph / token-efficient
tools below; delegate wide searches to subagents and keep only the conclusions.

**Use headroom (token-compression proxy).** Run Claude Code through headroom so
its compression proxy (`127.0.0.1:8787`, ~50% context savings) sits in the
request path — launch from a terminal with `headroom wrap claude`. This is a
LAUNCH-TIME choice: a session already started (e.g. from the Claude desktop app,
which routes straight to `api.anthropic.com`) cannot switch it on mid-run.
Confirm it is active by checking `ANTHROPIC_BASE_URL = http://127.0.0.1:8787` and
that the proxy `/health` responds.

**Compact context every ~1M tokens.** Over a long session, trigger context
compaction at roughly every 1,000,000 tokens of cumulative usage so the working
context stays lean and cheap — don't let it bloat unbounded. Compact proactively
at those boundaries (and at natural phase breaks), and rely on the harness's
auto-compaction as the window fills. (Hard enforcement is a harness/hook concern,
not something the model can self-trigger reliably — so treat the 1M-token mark as
a standing checkpoint to compact.)

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
