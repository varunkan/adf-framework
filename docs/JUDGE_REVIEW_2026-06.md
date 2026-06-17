# LLM-as-Judge Review — every ask, verified (2026-06)

Adversarial judge panel (9 asks): **5 fully delivered, 4 partial, 0 missing** (judges ran the cited tests).

Both confirmed: `autoCompactIfNeeded` has only its own definition (zero call sites — dead code), and the graph hook calls the bare `code-review-graph` command (not the absolute `.venv-codereview` path). The judges' two sharpest gaps hold up. Here's the report.

---

# ADF Session Verification Report
**Panel:** LLM-as-judge over 9 user asks · **Branch:** `v3.2.0-runner-backends-studio` · **Director's verdict:** ship-with-caveats

## 1. Scorecard

| # | Ask | Verdict | Evidence (one-liner) | Gap |
|---|-----|---------|----------------------|-----|
| 1 | `/compact` per task + auto-compact when needed (N11–N13) | **Partial** | Engine `compaction.py` 25/25, runner wiring 4/4, server surface + ContextChip 4/4 + 5/5; runner auto-compaction fires on edit/self-heal | Server "auto-compact at phase boundary" is **dead code** — `autoCompactIfNeeded` (compaction.dart:60) has zero callers; plan promises it twice (10X_BUILD.md:161,218) |
| 2 | 10x moat: audit-fold (N14), Data tab (N18), kill dead-air (N21), air-gapped build (N17) | **Full** | N14 14/14 + self-test; N18 8/8 + 2/2; N21 3/3+1/1; **N17 re-run live `--live` ok:true on real node v22.17.1** | Only stale commit test-counts; `data_tab_test.dart` path nuance — non-blocking |
| 3 | Agent-operable MCP loop + export-your-code (N16, N19) | **Full** | 13 MCP tools, mcp_server_test 10/10; export 4/4 + 2/2 + 1/1; endpoints live in server.dart | No single black-box e2e (per-layer + wiring instead); `adf_dashboard`→`orchestration_dashboard` label drift in the ask |
| 4 | Benchmark + honest scorecard + real capability number + built-in auth (N23–N27) | **Full** | bench 4/4, scorecard 8/8 (regenerates byte-for-byte), bench-build 3/3, auth 3/3, policy-gate 11/11; CI hard-gates all 5 | Real capability number is **cloud Opus (~$0.37)**, not the $0 local path (local 32B + free 70B timed out) — disclosed honestly, not the zero-cost headline |
| 5 | Fortune-5 audit: scan all + visual testing + "100% reliable/defect-free, address ALL" | **Partial** | Visual gate 5/5 (Chrome really executes bundle), SEC-1 CORS, GOV-2, `_asInt`, atomic `writeState`, scrubbed_env, regression test 6/6 — all P0 shipped | "ALL issues" = **P0-only**. Open: SEC-2 Dart path, SEC-4 auth secret, GOV-1 unvalidated seals, STATE-1 (3 of 4 files), all 3 DASH honesty fixes, Perf #1. No HTTP regression test for the CORS-403/GOV-400 fixes |
| 6 | Build 100% reliable — retry until it works (was stopping after 1 attempt) | **Full** | `resolve_feature_id` 26/26 (incl. phase-misparse), `childEnvFor` 6/6, internal heal 3 × outer heal 3, launcher `ORCH_MAX_HEAL_ATTEMPTS=3`; 2 real apps with offline-verifying proof seals | Stale docstring phase_runner.dart:28 ("launcher sets it to 1") — comment lies, code correct (task_bc178835) |
| 7 | Dashboard: stop the confirm/revise nag under auto-approve + browse artifacts every stage | **Full** | auto_flow 5/5 (single `autoApprove` resolver, every gate path respects it), stage_artifacts 3/3, full server suite 225/225, analyze clean; live: 13 features all `awaiting_user=False` | Verified at unit/widget level, no live click-through; most live features are `auto_approve=None` so the live snapshot doesn't exercise the suppression path (the two `=True` features do) |
| 8 | Self-contained reusable components via template+manifest; **a REAL build produced multiple components** (N, commit f4af007) | **Partial** | Mechanism real: prompt mandate, `component_manifest.py` 5/5, edit-reuse wiring, CI-gated; generator works on real code | **The load-bearing proof is absent.** No `.adf-components.json`/`COMPONENTS.md` anywhere in repo. The "8-component contact manager" exists only as commit-message prose. Only real app (`snake-ladder-games`) has **1 component + 157-line monolithic App.tsx** — built 7h *before* the commit. `find -newermt` after commit = empty |
| 9 | Codebase graph — create + keep integrating/referring | **Partial** | Graph current: 1778 nodes/246 files, built at f4af007; `.mcp.json` → absolute local binary, committed (82b8b24); new modules in graph; CLAUDE.md + SessionStart enforce "refer to it" | **Auto-update hook is broken.** `.claude/settings.json:9` calls bare `code-review-graph` (not the `.venv` absolute path); `which` = not found; `|| true` makes every Edit/Write a **silent no-op**. Graph already 1 commit behind HEAD — the documented "keep integrating" mechanism doesn't run |

**Tally:** 5 full · 4 partial · 0 not-delivered. The four partials each have one specific, closeable gap — none are foundational.

---

## 2. Concrete gaps to close (prioritized)

**P0 — honesty-of-claim defects (a stated promise does not execute at runtime):**

1. **Ask 8 — produce the real component artifact.** This is the only gap where the *evidence the ask explicitly demanded* is missing. Run one real React build through the post-f4af007 pipeline and commit the app dir **with** its generated `.adf-components.json` + `COMPONENTS.md` showing ≥3 props-driven components under `src/components/` + `ui/` primitives + a thin App.tsx. Until that artifact exists, the feature is asserted, not proven. *(Converts 8 → full.)*

2. **Ask 9 — fix the auto-update hook.** Point `.claude/settings.json:9` at the absolute binary `/Users/varunkumar/ai_pos_system/adf-framework/.venv-codereview/bin/code-review-graph` (matching `.mcp.json`), or put it on PATH. Then `update` once so graph head == HEAD, and commit. Confirmed broken by direct test — bare command is not resolvable. *(Converts 9 → full.)*

3. **Ask 1 — wire `autoCompactIfNeeded` into the phase path.** Confirmed dead (only its own definition repo-wide). Call it best-effort from `phase_runner.dart` (or the phase-advance handler near server.dart:452), honoring `ADF_AUTO_COMPACT`, + one integration test asserting it fires when over budget at a phase boundary. *(Converts 1 → full.)*

**P1 — security/integrity in Ask 5 (these are the audit's own P1/P2, still open in code):**

4. **SEC-4:** `auth.mjs:35` still ships world-known fallback `adf-dev-secret-set-ADF_AUTH_SECRET` (not fail-closed); `app_runner.dart` injects no per-app secret. Make fail-closed + inject a per-app secret.
5. **SEC-2 (Dart side):** `app_runner.dart:62` and `:155` still leak full `Platform.environment` (incl. API keys) into spawned preview apps. Only the Python runner was scrubbed — mirror `scrubbed_env` here.
6. **GOV-1:** `agent_crew.dart:200` validator still only checks phases {2,3,4}; phases 1/5/6 are `_advance()`-ed and `integrity.seal()`-ed unvalidated; phase-6 `tests_red` sealed without confirming executable failing tests. Refuse to seal 1/5/6 without validation.
7. **STATE-1 (finish the half):** `writeState` is atomic, but `writeRunStatus`/`appendApproval`/`writePhaseRequest` (~18 sites) still `writeAsStringSync` — a kill mid-write corrupts governance JSON. Route through `writeFileAtomic`.
8. **Missing regression test:** add `approve_gate_test.dart` driving the SEC-1 CORS-403 + GOV-2 invalid-decision-400 over HTTP. The fixes are real in code but **not regression-guarded** — exactly the silent-reintroduction class the audit warns about. §5 flagged this as the top missing test.

**P2 — honesty in the dashboard (Ask 5, all open):**
9. DASH-1: `_maybeAutoAutopilot` doesn't set `_autopilotRunning=true` and `catch(_){}` swallows failures. DASH-2: `_runAutopilot` renders celebratory "completed" on a `blocked` run; `summary['blockers']` read nowhere. DASH-3: edit-failure `catch(_)` lumps 409 with transient and falls through to chat with no status surfaced.

**P3 — cosmetic drift (non-defects, batch into one cleanup commit):** stale commit test-counts (N12/N14/N18); `phase_runner.dart:28` docstring (task_bc178835); 10X_BUILD.md planned-vs-shipped test filenames; two unclosed file handles in `test_component_manifest.py`.

---

## 3. Determinism action plan (more deterministic generation)

Today the model regenerates the highest-variance surfaces from scratch every build, and `fix_messages:856-860` enumerates the exact recurring failure modes (route prefixes, column names, status codes). Move that surface out of the LLM.

| Move | What it removes from the model | Mechanism | Effort |
|------|-------------------------------|-----------|--------|
| **Ship a checked-in, vitest-covered `src/components/ui/`** in the template; change prompt from "build primitives" → "import and compose the shipped primitives" | Button/Input/Card regeneration — identical every app, a recurring source of tsc errors that trigger full re-verify | Template already ships only App/main/index.css; add `ui/` and have `scaffold_app` copy it deterministically | Medium |
| **Deterministic feature-shape scaffolds** (CRUD list/form/dashboard) driven by the spec | schema.sql + Fastify GET/POST/PUT/DELETE routes (correct `/api` prefixes + 200/201/400/404) + typed `use<Feature>.ts` hook + vitest skeleton | Detect entity+fields from spec → template the deterministic parts; fall back to full LLM for non-CRUD. This is exactly where the model most often errs | Large |
| **Golden test for the modular layout** | Locks the "multiple components" claim (Ask 8) as gate-enforced, not synthetic-fixture-only | Feed a known multi-component generation through `extract_components`, assert `ui/` + ≥3 props-driven + thin App | Small |

**Sequencing:** primitives library first (small, immediate win + directly unblocks the Ask 8 artifact since a real build will now emit `ui/` deterministically), then CRUD scaffolds (the big variance reducer), golden test alongside.

---

## 4. Perf / token action plan (rough wins)

| Move | Win (rough) | Effort | Where |
|------|-------------|--------|-------|
| **Warm `node_modules` reuse** — `scaffold_app` hard-links/clonefiles the template's warm tree so the existing `if not isdir(node_modules)` guard makes `npm ci` a no-op | **10–50×** first-build / cold CI (cold `npm ci` 30–90s → ~0s); reclaims ~114 MB/app. This is the **audit's #1 perf win, still unfixed** | Small | agent_runner.py:147,366-389,776-779 |
| **Prompt caching (`cache_control`)** on the build/self-heal Anthropic calls | **~90%** input-token cost on the cached prefix across the up-to-3 self-heal turns (system+user are byte-identical each attempt). Note Opus 4.8 min cacheable prefix = 4096 tokens — fold CURRENT FILES into the cached span and verify via `usage.cache_read_input_tokens` | Small | agent_runner.py:471-494, 840-876 |
| **Incremental self-heal verify** — track the failed stage; on retry short-circuit instead of re-running build+vitest+boot+render from stage 1; persist `node_modules/.vite`; run headless render once after build+test pass | **2–4×** per self-heal attempt × up to 3 attempts | Medium | agent_runner.py:766-789, 1110 |
| **Trim ~950-token build prompt + lazy headroom import** — move the scaffold-contract prose (now encoded by the template) to a short reference; gate the headroom venv behind `ADF_HEADROOM` so the common small-prompt path doesn't pay transformers/torch import per spawn | Lower uncached first-build cost; removes multi-second per-spawn startup | Small | agent_runner.py:263-337, agent_runner_headroom.sh:9 |

**Highest leverage:** warm `node_modules` (one small change, 10–50×, already the audit's #1) and prompt caching (small change, ~90% on the cached prefix). Do both first.

---

## 5. Do-next (sequenced)

1. **Warm `node_modules` in `scaffold_app`** — biggest single win, small change, audit's #1. *(Perf)*
2. **Add `cache_control` to the Anthropic calls** — ~90% prefix-token cut, small change. *(Token)*
3. **Ship `src/components/ui/` in the template + flip the prompt to "compose"** — determinism + directly enables step 4. *(Determinism)*
4. **Run one real CRUD/contact-manager build through the post-f4af007 pipeline; commit the app + `.adf-components.json` + `COMPONENTS.md` (≥3 components)** — closes Ask 8's load-bearing gap. *(Honesty)*
5. **Fix `.claude/settings.json` hook → absolute binary; rebuild; commit** — closes Ask 9. *(Honesty)*
6. **Wire `autoCompactIfNeeded` into the phase boundary + integration test** — closes Ask 1. *(Honesty)*
7. **Security batch:** SEC-4 fail-closed auth secret → SEC-2 Dart env scrub → GOV-1 seal validation → finish STATE-1 atomic writes. *(Integrity — Ask 5 P1)*
8. **Add `approve_gate_test.dart`** (CORS-403 + GOV-400 over HTTP) so the shipped P0 fixes can't silently regress. *(Integrity)*
9. **Three DASH honesty fixes** + the cosmetic-drift cleanup commit (stale counts, docstrings, file handles). *(Polish)*
10. **Incremental self-heal verify + prompt trim** once the template encodes more deterministically. *(Perf/token)*

**Director's honest framing for stakeholders:** the P0 reliability+visual-testing spine, the MCP/export loop, the benchmark+auth proof, the retry-until-it-works fix, and the dashboard auto-flow are **genuinely shipped and test-backed**. Do **not** represent Ask 5 as "100% defect-free" — it is *P0 hardening + visual testing delivered; P1/P2 remediation outstanding.* Do **not** claim the component feature is proven until a real build's manifest is committed. Do **not** claim the graph "keeps integrating automatically" until the hook path is fixed. And the headline capability number is **cloud Opus at ~$0.37, not the $0 local path** — keep that caveat attached wherever the number appears.