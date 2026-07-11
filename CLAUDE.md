## ⛔ MUST #0 — Headroom is mandatory (verify BEFORE any model token exchange)

**ALWAYS run through Headroom. Before ANY token exchange with a model — your own
turns, `Workflow`/`Task`/`Agent` subagents, persona/SSR elicitation, ANY model
call — FIRST confirm the Headroom compression proxy is running AND in the request
path:**

1. Proxy is up: `curl -s http://127.0.0.1:8787/health` responds.
2. Routing is active: `ANTHROPIC_BASE_URL` == `http://127.0.0.1:8787` (NOT
   `https://api.anthropic.com`).

**SELF-HEAL (deterministic) — run `headroom_patch` whenever routing is missing.**
The durable routing state (proxy up + Claude Desktop binary shim applied +
re-patch agent loaded) is guaranteed by ONE idempotent utility:

    /Users/varunkumar/.claude/headroom-desktop-shim/headroom_patch ensure

It runs automatically at SessionStart (hook in `~/.claude/settings.json`), and
**you MUST run it whenever the two checks above fail** (or run `headroom_patch
status` to diagnose), then re-verify. It rebuilds the compiled arm64 trampoline,
(re)wraps every desktop `claude.app`, starts the proxy, and loads the launchd
agent — all idempotent and race-safe. See
`~/.claude/headroom-desktop-shim/README.md` and memory [[headroom-desktop-shim]].

**Hard reality — a running session's route is fixed at launch.** `headroom_patch`
makes routing correct for the NEXT spawn; it CANNOT reroute the already-running
session. So:
- **Terminal**: if unrouted, relaunch (`headroom wrap claude`, or plain `claude`
  since `settings.json` sets the base URL). Do not burn uncompressed tokens —
  wait for relaunch.
- **Desktop app**: the shim makes every NEW session route automatically. If the
  current session shows `ANTHROPIC_BASE_URL=https://api.anthropic.com`, run
  `headroom_patch ensure` (fixes the durable state) and tell the user to open a
  new session / reopen the app to pick it up — this specific session stays direct.

Start the proxy with `headroom proxy` (background) and verify with `headroom
doctor`. This gate precedes every other directive below.

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

**Graph-first — consult the knowledge graph BEFORE proposing, changing,
validating, or reviewing ANY code.** This is a hard, standing gate on every code
task, not a suggestion. Before you PROPOSE a change: query the code-review-graph
MCP tools (`semantic_search_nodes`, `query_graph` for callers/callees/imports/
tests, `get_impact_radius`, `get_review_context`, `get_architecture_overview`) to
establish the real structure, callers, dependents, and test coverage — so you act
on the actual graph of the code, not an assumption. Before you VALIDATE or REVIEW
a change: use `detect_changes` + `get_impact_radius` + `get_affected_flows` +
`query_graph pattern=tests_for` to see the full blast radius and what must be
re-checked. Only fall back to Grep/Glob/Read for what the graph genuinely does not
cover (e.g. non-indexed TSX/asset details) — and say so. Then: gather full context
via the graph → form the plan → make the change → validate the change against the
graph's impact set. After every commit, update the graph
(`build_or_update_graph_tool`) so the next task's context is accurate. A change
proposed or reviewed without first consulting the graph is incomplete work.

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

**ALWAYS self-heal every stopper or failed process — to completion.** When ANY
process stalls, blocks, or fails (build, test, gate, server, workflow, agent
run, pipeline step, tool call), never abandon it, retry it blindly, or route
around it. Run the full self-heal loop every time:
1. **Find the root cause with deep analysis** — read the actual error/logs/
   state, trace the failing path in the code, reproduce it minimally, and
   cross-check every data point (process state, env, config, recent changes,
   git history) before concluding anything.
2. **Design a real solution** that addresses that root cause — not a symptom
   patch, not a workaround that leaves the defect in place.
3. **Implement it.**
4. **Test it** — prove the original failure is gone (re-run the exact failed
   process) plus the relevant test suite so nothing regressed.
5. **Ensure the expected outcome is achieved** — the originally-intended
   result must now be observed end-to-end in the real running system, not
   inferred. A stopper counts as resolved ONLY when the original process
   completes successfully and its intended outcome is verified.
Then log the root cause + fix (activity log) so it never has to be
re-diagnosed. This loop applies recursively: if the fix itself fails, self-heal
that failure the same way.

**Test-first (TDD).** For any code change, write the test first, prove it RED,
then implement to GREEN. Let the tests, not vibes, define done.

**Verify against the running system.** "Done" = tests green AND observed working
in the real running app AND self-reviewed AND committed — never claimed from
assumptions. Report outcomes faithfully (failures with output, skipped steps as
skipped).

**Visually test the UI after EVERY change, whenever a UI is available.** If the
change touches any rendered surface (a page, component, style, layout, copy,
route, or the data a view renders), you are not done until you have VISUALLY
verified it in the running UI — do not stop at tests/`tsc`/`build`. Drive the
app's ALREADY-RUNNING server READ-ONLY (never start a competing one — see the
first directive): load the affected view, take a screenshot, and check the DOM
(`read_page`), console, and network for errors; confirm the change renders as
intended AND that nothing adjacent regressed. Check the states that matter for
the change — the relevant routes, empty/error/loading states, and (when layout
or theming moved) responsive breakpoints and light/dark. Share the visual proof
(screenshot / observed values), never "looks fine" from assumption. If the app
isn't running and a UI check is genuinely required, ASK before starting a server
(non-conflicting port). SKIP only when the change has no rendered surface at all
(pure backend/CLI/lib/test/tooling) — and say that you skipped and why.

**Adversarially self-review before every commit.** Do a pass that actively tries
to REFUTE your own change — security holes, edge cases, unfaithful claims, broken
invariants. This cheap pass repeatedly catches real defects pre-ship.

**Ground every claim in current source (file:line); never assert from memory.**
Recalled facts and this file may be stale — verify a symbol/flag/behavior still
exists in the code before relying on it.

**Maintain an activity log — one entry per activity, updated after EVERY commit.**
Keep a running log document at `docs/activity-log/ACTIVITY_LOG.md` (newest entry
first) that records EVERY activity: the date, what was analyzed, what changed and
why, the requirement/persona/gap it traces to, the commit hash(es), and the
verification result (tests run + outcome). Append an entry immediately after each
commit — and for any substantive analysis, decision, or test round even when no
commit results. Before starting new work, READ the latest log entries to
understand what was done last and continue from there: the log is the durable,
human-readable memory of the build (complementary to the knowledge graph and
auto-memory). No activity is complete until it is logged. For a long
multi-round campaign, also keep a per-campaign log (e.g.
`docs/activity-log/<campaign>-log.md`) and link it from the main log.

**Check ALL current code and state BEFORE every commit — a prior step may have
half-landed.** A network error, interrupted tool call, timeout, or crash can
leave the working tree partially changed or a commit partially made. So before
every `git add`/`git commit`: re-run `git status` + `git diff --stat` +
`git log --oneline -3`, re-read (or diff) the exact files you intend to commit,
and re-run the relevant tests — confirm the ACTUAL current state matches what you
intend, that no earlier change was lost or double-applied, and that nothing
unrelated is being swept in. Never commit blind on the assumption a previous step
completed; verify it did, then commit.

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
