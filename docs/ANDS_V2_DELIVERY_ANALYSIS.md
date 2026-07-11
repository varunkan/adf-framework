# ANDS v2 delivery — root-cause analysis, design & solution (2026-06-27)

After several build attempts the v2 UI made **zero durable progress** (tests still 599,
`nav=0 router=0`, no v2 slice in the ledger) while consuming quota and tripping rate limits.
This is the thorough analysis of why, and the engineered fix.

## Symptoms observed
- Repeated seven-day `rate_limit_event: rejected` (overage allowed) within ~10 min of each campaign start.
- The app home page never changed — no shell/router/Prism — despite the campaign "running".
- Partial, uncommitted edits left in `apps/ands-submission-portal/*.py` after each stop.
- The campaign driver sat in `wait_idle` while the server's auto-runner built a stale scope.

## Issues — root-caused

| # | Issue | Root cause |
|---|-------|-----------|
| **I1** | **Quota exhaustion is the binding constraint** | All 3 paths are capped: $0 subscription hit its **seven-day** cap; the claude.ai **monthly spend limit** tripped; the paid `ANTHROPIC_API_KEY` has **no credit**. Only NVIDIA-Nemotron is free, and it's too weak for regulated UI work. |
| **I2** | **Deep agents are a 4× quota accelerant** | `ADF_DEEP_AGENTS=1` runs 4 extra Opus-judged agents (e2e/integration/black-box/white-box) on **every clean gate cycle**. On a build that cycles the gate many times, this multiplies Opus turns ~5× — and it's what burned the weekly cap each time. The deterministic gate already enforces the UI/accessibility bar, so deep agents add little during *iteration*. |
| **I3** | **Slices are far too big to land** | A single slice (e.g. U1 = the *entire* multi-page shell + router + Prism design system) cannot be completed in one rate-limited/interruptible build turn. The agent never reaches a green, committable state, so nothing lands. |
| **I4** | **Work is lost on every interruption** | Build-agent edits sit **uncommitted**; a throttle/kill mid-turn discards in-flight work. There is no per-turn checkpoint, so each restart starts over → net-zero progress under throttling. |
| **I5** | **Two orchestrators contend** | The campaign driver (`ands_expand_all.py`) AND the server auto-runner both drive the same feature. `wait_idle` stalls the driver while the auto-runner builds whatever is in `mvp-scope.md` (a stale pre-render once thrashed the sequence). Net: out-of-order, non-deterministic builds. |
| **I6** | **Completion gates never flip in the basic loop** | ANDS is defect-clean but `review_approved`/`all_quality_gates_pass` stay false; only the **review-harden** stage sets them. The plain heal loop circles "idle but not complete" and burns heal attempts to the cap. |
| **I7** | **Monitoring couldn't notify** | Watchers launched `nohup`-detached aren't harness-tracked, so they can't ping on an event. |
| **I8** | (lower) **13 demo apps blocked with REAL defects** | Re-verify proved they're not phantom (favicon-404, a11y labels, dup-code, static security). Separate track; needs build turns = quota. |

**The binding root cause = I1×I2×I3×I4 compounding:** too-big slices can't finish inside a quota
window that the 4× deep-agent multiplier exhausts fast, and interruptions lose the partial work — so
spend goes up while durable output stays at zero.

## Design — the solution

### S1. Stop the accelerant: deterministic-gate-first
`ADF_DEEP_AGENTS=0` for the *build/iteration* loop. The deterministic gate (ui-visual, accessibility,
dup, security, functional ≈ 6s, no LLM) carries iteration. Run the deep Opus agents **only once**, in
the final review-harden milestone per feature. → ~5× more useful build turns per quota budget.

### S2. Right-size slices so each lands in 1–2 turns
Decompose the 5 big v2 slices into small, independently-greenable increments, e.g. U1 becomes:
- **U1a** router + nav skeleton (routes change the URL, one view renders) — no styling.
- **U1b** design tokens + self-contained Prism CSS (one `<style>` block).
- **U1c…** ONE page per slice (Dashboard → Submissions → Content/eCTD tree → Validation → …).
Small slices finish before a throttle hits and survive interruptions.

### S3. Checkpoint every green slice (kill-safe)
After each slice greens, **commit** the app (ADF seal / `git commit`) so a throttle/kill never loses
it. Verify ADF already commits per slice; if not, add a commit step to the driver. No more net-zero.

### S4. One orchestrator, no pre-render
Run a SINGLE sequencer. Never write `mvp-scope.md` outside the driver (that caused the thrash). Either
(a) keep `ands_expand_all.py` as the sole driver with the auto-runner only *executing* its kicks, or
(b) drive slices with a thin sequential loop. Fix `wait_idle` so a non-settling heal loop can't block it.

### S5. Wire completion + tracked monitoring
Run review-harden after the slices to flip the quality/review gates. Use harness-tracked monitors.

## Billing decision (USER'S CALL — gates everything else)
Building needs Opus turns, and all paid paths are capped. With **S1+S2+S3** the weekly $0 budget goes
~5× further, so incremental v2 delivery becomes feasible *within* the cap. Pick one:
1. **Wait for the weekly reset (~Jun 29–30)** then build with S1–S5 — $0, no overage.
2. **Add API credit** (console.anthropic.com → Billing) → switch to the paid runner, build now.
3. **Build trivial parts on NVIDIA** ($0) — not suitable for the regulated UI; only stopgap.

## Execution order (once billing is chosen)
1. `ADF_DEEP_AGENTS=0`, `ADF_BUILD_PARALLELISM=1` (S1).
2. Replace the 5 big v2 slices with the small-increment slice list (S2) in `ands_expand_all.py`.
3. Confirm/Add per-slice commit (S3); single-driver + remove any pre-render (S4).
4. Launch the campaign (tracked monitor) → it lands U1a, U1b, U1c… one by one, committing each.
5. review-harden milestone (deep agents on for that one pass) → gates flip → done (S5).
