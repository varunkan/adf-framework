## Working principles (standing directives — apply to EVERY task)

**NEVER start a dev/preview/web server that could displace the user's running
app.** Do NOT run `preview_start`, `npm run dev`, `next dev/start`, `uvicorn`, or
any server that binds a port the user's app may already use (esp. `:3000` and the
mesh service ports 8010–8018). Starting a competing server on `:3000` will kill
the user's working web and break their UI — this happened once (2026-07-05) and
must never recur. To verify UI: interact READ-ONLY with the user's ALREADY-RUNNING
server (its serverId), or verify from source + `tsc`/`next lint`/`next build` +
the content checks. If a fresh server is genuinely required, ASK first and use a
non-conflicting port. This overrides "always run autonomously" and the
preview-tools guidance.

**Always run autonomously.** Execute the work end to end without pausing for
approval or check-ins. Make the reasonable call yourself from the goal, the
evidence, and sensible defaults, and proceed. Do NOT use AskUserQuestion for
choices you can resolve — reserve it only for a genuinely blocking external
dependency, and even then prefer picking the best option and moving on. Keep
committing verified units and reporting progress; never request permission to
continue. When a task is large, decompose it and drive it to completion via
workflows/subagents rather than stopping to confirm.

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

**Treat user/customer feedback as literal acceptance criteria — implement ALL of
it, don't guess.** When real feedback exists (users, reviewers, evaluation
personas), enumerate EVERY concrete ask and implement the full set faithfully, the
way they asked — do not cherry-pick a few top themes, silently drop, or
de-prioritize comments away. Never guess at fixes when explicit asks are on the
table. Re-measure/re-review only AFTER the whole backlog is built and verified —
evaluation cycles are expensive; spend them confirming completed work, not
re-discovering asks you already hold. Keep a written backlog and check off each
item against a code change + test so nothing is ignored.

**Plan every fix with all data points possible before executing it.** Before
writing any fix, gather the full evidence for THAT fix — the current source of
every file it touches, the type/contract it must honor, the callers and tests,
the failing signal, and the user/persona ask it answers — then state the approach,
then implement. No fix starts from assumption; ground each one in the real code.

**Root-cause before any fix; never blind-regenerate.** When a build/test/gate/
review fails, read the error and trace the actual cause before changing code. No
shotgun edits, no regenerating a whole file to dodge a diagnosis.

**Test-first (TDD).** For any code change, write the test first, prove it RED,
then implement to GREEN. Let the tests, not vibes, define done.

**Verify against the running system.** "Done" = tests green AND observed working
in the real running app AND self-reviewed AND committed — never claimed from
assumptions. Report outcomes faithfully (failures with output, skipped steps as
skipped).

**Adversarially self-review before every commit.** Do a pass that actively tries
to REFUTE your own change — security holes, edge cases, unfaithful claims, broken
invariants. This cheap pass repeatedly catches real defects pre-ship.

**Ground every claim in current source (file:line); never assert from memory.**
Recalled facts and this file may be stale — verify a symbol/flag/behavior still
exists in the code before relying on it.

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

### RULE: update the knowledge graph after every commit

**After every `git commit`, update the knowledge graph so it reflects the new
HEAD** — call `mcp__code-review-graph__build_or_update_graph_tool` (incremental;
it re-parses only what changed). Do this once per commit, right after committing.
This keeps `detect_changes`, `query_graph`, `get_impact_radius`, and semantic
search accurate for the next task; a stale graph gives wrong callers/dependents/
coverage. When a batch of commits lands together, one update after the last is
fine. (The auto-update hook is best-effort — this rule guarantees it.)
