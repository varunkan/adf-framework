# ADF runner efficiency — benchmark (Task 5)

**As of:** 2026-06-26 · **Path:** $0 Claude Code subscription (Opus/Sonnet) · **Reproduce:**
`python3 scripts/orch/measure_efficiency.py --feature <id> [--since N] [--label X]`

> Honesty rules: two SEPARATE axes (cost-× and wall-clock-×) — never one fused "100×". `$` figures
> are the API-equivalent the CLI reports (actual subscription spend is $0); valid for RELATIVE A/B.
> "Measured" = a clean controlled/deterministic measurement; "Observed" = real but confounded
> (mixed phases/levers); "Pending" = needs the controlled A/B below.

## Headline (what's earned so far)
- **Verify gate ~3.4× faster** (deterministic, clean): the headless-Chrome layer 21s → ~6s.
- **Warm session ~9× cheaper on a resumed turn** (controlled 2-turn spike, clean).
- **93.4% cache-hit rate observed** across 25 real build turns (warm reuse working; partly confounded
  by the CLI's own system-prompt caching — clean per-lever split is Pending).
- **Reliability**: the infinite phantom-defect loop and the premature-idle stall are fixed; the build
  now runs until the real gate passes (see `[[adf-orphan-resume-churn-fix]]`, `[[adf-heal-stale-server-falsepos]]`).

## Clean measurements
| Lever | Metric | Before | After | Factor | Method |
|---|---|---|---|---|---|
| Gate-settle perf | `visual_verify.mjs` wall-clock | 17.1s | 4.8s | ~3.6× | timed on the ANDS app (fresh boot), deterministic |
| Gate-settle perf | `accessibility.mjs` wall-clock | 2.7s | 1.3s | ~2.1× | same |
| Gate-settle perf | whole deterministic gate | ~21s | ~6s | **~3.4×** | sum of agents, identical coverage (5 views, 0 defects) |
| Warm session | resumed-turn $ (2-turn spike) | $0.094 | $0.011 | **~9×** | `--session-id` then `--resume`, sonnet, same workload |
| Warm session | resumed-turn cache_creation | 13,275 | 30 | ~440× less re-created | same spike (turn-2 read 30,220 from cache) |

## Observed (real, but confounded — needs A/B to attribute)
From 25 recorded ANDS build turns (`measure_efficiency.py --feature ands-submission-portal`):
- cache_hit_rate **0.934**; cache_read 10.5M vs cache_creation 715K (strong warm reuse signal).
- $/turn **~$0.65** avg (API-equiv); median per-turn wall-clock **~10 min** (model-dominated — the
  non-model harness is a small slice of a turn, which is exactly why "100× single-build latency"
  is not achievable without changing the model).

## Incremental-verify (lever #3): now ACTIVATABLE via one knob (was dormant)
The gate's deep LLM agents — `e2e`, `integration`, `black-box`, `white-box` — ship
**`enabled: false`** in `scripts/orch/test_agents/registry.json`, so by default the live gate is
**all deterministic** (ui-visual, accessibility, dup, security, functional ≈ ~6s post-settle) and
the incremental lever has nothing to defer (**0× when off** — the prior, quota-safe default).
`_apply_deep_agent_gate` (run_test_agents.py, commit 76cefaa) wires those agents' `enabled` to the
single **`ADF_DEEP_AGENTS`** knob: set it to `1` and the deep agents run — deferred by
`ADF_VERIFY_INCREMENTAL` while the cheap deterministic tier is dirty, then run once it is clean (the
natural completion milestone). That is when the lever does real work (deferring a multi-minute
4-agent Opus sweep on every deterministically-failing cycle). $0 holds: `llm_agent.py` drives
`claude -p --model opus` via `CLAUDE_CODE_OAUTH_TOKEN`, never the API. Covered by 5 unit tests
(`test_deep_agent_gate.py`). To quantify the saving, run a C-incremental A/B with `ADF_DEEP_AGENTS=1`.

## Parallelism (lever #4): cap-2 now UNBLOCKED + isolation proven (deterministic)
`ADF_BUILD_PARALLELISM>1` gives each concurrent feature its own app port. The remaining blocker —
apps hardcoding `:8000` — is closed (commit 76cefaa): `childEnvFor` sets both `ADF_SMOKE_PORT` and
`PORT`, and every app's `__main__` honors `ADF_SMOKE_PORT or PORT or 8000` (new apps inherit it from
the build prompt). **Proven without LLM quota:** two apps booted on `:8011`+`:8012` simultaneously
(one via `ADF_SMOKE_PORT`, one via `PORT`) — both HTTP 200, nothing on shared `:8000`. Allocator +
cap logic covered by `phase_runner_parallelism_test.dart`. The live two-feature throughput A/B
(builds/hr at cap 1 vs cap 2) is the only piece still needing a real quota'd run; do it on two SMALL
throwaway features (not the live ANDS build) and watch for `rate_limit_event`.

## Controlled A/B — assessed NOT worth the quota (and why)
A 5-config × N=3 LLM build campaign was planned for clean per-lever attribution, but inspection shows
low marginal value: warm-session is already cleanly spiked (~9×), incremental-verify is dormant
(above), and model-tiering's $ benefit is the known Sonnet/Opus price ratio. The campaign (~15 LLM
builds + restarts) would mostly re-confirm warm-session while consuming the shared weekly rate budget
the ANDS build needs. **Decision: skip it; the clean measurements + this finding suffice.** If the
deep agents are later enabled, re-run a C-incremental A/B to quantify lever #3.

## Honest caveats
- **Single-build latency is NOT 100×** and won't be without changing the model — the model turn (~10
  min) dwarfs the non-model harness (~6s gate). The wins are in *cost/turn*, *gate time*, and
  *eliminated wasted turns* (the biggest reliability win), plus *throughput* via bounded concurrency.
- **Aggregate throughput** is capped by the $0 subscription weekly/5h rate limit, not the architecture.
- LLM non-determinism → the A/B reports medians/ranges over N, not single points.
- The observed 93% cache-hit blends the CLI's baseline system-prompt caching with the `--resume`
  lever; only the C0-vs-C1 A/B isolates the lever's marginal contribution.

## How to reproduce
1. `python3 scripts/orch/measure_efficiency.py --feature <id> --count` → note turn count.
2. Run the slice under a config (set `ADF_RUNNER_RESUME`/`ADF_TIER_BUILD`/`ADF_VERIFY_INCREMENTAL`,
   restart server-fix, build).
3. `... --since <count> --label <config>` → that config's metrics row.
4. Repeat per config; compare rows.
