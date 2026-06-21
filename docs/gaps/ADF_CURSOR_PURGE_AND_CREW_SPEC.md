# SPEC — Purge Cursor + Wire the Requirements Crew (controlled, eval-gated)

**Date:** 2026-06-21 · **Owner:** controlled TDD program · **North star:** the best app-generation platform in the world — ADF runs on its OWN governed runner (Python custom + free NVIDIA / Claude / Ollama), and every M/L/XL build produces a *researched, confirmed* spec, not template garbage.

## 1. Goals
- **G-CURSOR:** remove cursor-the-tool entirely from the active product. ADF must not depend on, default to, or reference `cursor-agent` / a "cursor" runner / cursor command strings. The Python **custom** runner is the default and only first-class CLI runner (Claude Code optional).
- **G-CREW:** the model-backed **requirements crew** is the default spec engine for tracks M/L/XL — it researches the user's links + the web, drafts real EARS requirements, PO-validates, and presents them. The zero-token **deterministic engine is a last-resort fallback** (only when no model is reachable), and that fallback is always disclosed (never silent).

## 2. Scope
**In scope**
- `runner_backend.dart`: drop `RunnerKind.cursor` + `CursorBackend`; default auto-select → custom (if configured) → claude → **custom** (never cursor).
- Delete cursor scripts: `scripts/orch/run_server_cursor_cli.sh`, `scripts/orch/setup_cursor_runner.sh`, `install/adapters/cursor.sh`.
- `respin_dashboard.sh`: remove the `--cursor` / `ADF_STUDIO_BACKEND=cursor` backend; local is the only backend.
- `pipeline_planner.dart`: the `cursorCommand`/`cursor_command` field generates `@orch-orchestrator resume …` strings (the same spam class that poisoned requirement.md). Rename to a neutral `runHint`/drop, with no `@orch-orchestrator` literal.
- Dashboard (`runner_setup_card.dart`, `new_feature_screen.dart`, `feature_detail_screen.dart`, `api_client.dart`): remove cursor as a selectable/displayed runner.
- Server/runner glue (`phase_runner.dart`, `orchestrator_chat.dart`, `agent_chat_runner.dart`, `adf_brain.dart`, `run_post_sync.dart`, `runner_health.dart`, `feature_store.dart`, `agent_runner.py`, `preflight.sh`, `write_runner_env.sh`): remove cursor branches/hints; keep custom/claude/ollama.
- `RequirementsCrewRunner.isEnabled`: default **ON** for M/L/XL (opt-out via `ADF_REQUIREMENTS_CREW=0`); launchers export the default; graceful + DISCLOSED fallback to deterministic when no model is reachable.
- A runnable eval harness `scripts/eval/platform_eval.sh` (before/after, the guardrail).

**Out of scope (this program)**
- Renaming the `.cursor/orchestration` **data directory** (feature store path). It is a layout name, not the tool; renaming is a separate, risky migration. *Decision needed — see §7.* Until then, it stays.
- The smooth-streaming backbone (S1/S3/S2) — separate Tier-1 program. NOTE: purging cursor makes the cursor-only live-stream path dead code; wiring the custom-runner token stream (S1) is the immediate follow-on, tracked separately.
- Historical docs/memory referencing cursor (left as record; not active code).

## 3. Success Criteria (measurable; eval enforces)
| ID | Criterion | BEFORE | TARGET |
|---|---|---|---|
| C1 | cursor-the-tool refs in active code (lib/bin/scripts/dashboard, excl tests/docs/.cursor-data) | 97 | **0** |
| C2 | cursor tool scripts/adapters on disk | 3 | **0** |
| C3 | default runner with nothing configured ≠ cursor | cursor | **custom** |
| C4 | `RequirementsCrewRunner.isEnabled()` default (M/L/XL) | false | **true** |
| C5 | crew enabled in the launcher | no | **yes** (opt-out documented) |
| C6 | a fresh M-track build's spec provenance | deterministic | **crew** (when a model is reachable) |
| C7 | generated spec quality: no "SHALL <verbatim prompt>", no `@orch-orchestrator`, ≥1 cited source when research ran | garbage | **clean + cited** |
| C8 | no `@orch-orchestrator` literal emitted by pipeline_planner | present | **0** |
| C9 | full regression (dart server / dashboard / python) | 325/7/481 | **≥ baseline, all green** |
| C10 | graceful + DISCLOSED deterministic fallback when no model | n/a | spec banner says "fallback", run not silent |

## 4. Evaluation Checklist (run BEFORE and AFTER via `scripts/eval/platform_eval.sh`)
1. C1 grep count == 0 (allowlist file for any intentional residual, with reason).
2. C2 scripts absent.
3. C3 a Dart unit test resolves default backend == custom (no cursor in `RunnerKind`).
4. C4 a Dart unit test: `isEnabled()` with empty env + track M == true; `ADF_REQUIREMENTS_CREW=0` == false.
5. C8 a Dart unit test: pipeline_planner emits no `@orch-orchestrator`.
6. C9 run all three suites; assert pass counts ≥ baseline.
7. C6/C7/C10 LIVE E2E: create a fresh M-track feature with a clean requirement + a reference link; assert spec provenance == crew, EARS are real, no `@orch`, sources cited; then simulate no-model and assert disclosed deterministic fallback.

## 5. Guardrails
- **TDD:** every change RED→GREEN; no edit without a failing test first (or a mutation-proven guard for pure-removal).
- **Regression gate:** all suites green after every commit; counts never drop.
- **One change at a time, committed:** cursor purge and crew wiring are separate, independently-reverting commits; within cursor purge, batched by safe unit (backend → scripts → planner → dashboard → glue) each green before the next.
- **No silent behavior change:** the deterministic fallback is always disclosed (ties to B2/B3 already shipped).
- **Eval before & after:** `platform_eval.sh` is run and recorded at the start (baseline) and end (proof), and wired into CI.
- **Reversibility:** cursor removal is staged so any batch can be reverted without breaking the build.

## 6. Execution order (controlled)
1. **EVAL-0** — build `scripts/eval/platform_eval.sh`; record BEFORE (this doc's §3 BEFORE column).
2. **CREW-1** — `isEnabled` default-on (M/L/XL) + opt-out + tests (TDD). *(Low blast radius, immediate value: real specs.)*
3. **CREW-2** — launcher exports the default; graceful+disclosed fallback verified; LIVE E2E (C6/C7/C10).
4. **CURSOR-1** — `runner_backend.dart`: drop cursor enum/backend; default→custom; tests (TDD).
5. **CURSOR-2** — delete cursor scripts + `respin --cursor`; preflight/write_runner_env cleanup.
6. **CURSOR-3** — `pipeline_planner` cursorCommand→runHint, kill `@orch-orchestrator` literal; tests.
7. **CURSOR-4** — dashboard cursor removal (runner_setup_card/new_feature/api_client); rebuild + E2E.
8. **CURSOR-5** — server/runner glue cleanup (phase_runner/orchestrator_chat/etc.).
9. **EVAL-1** — re-run `platform_eval.sh`; record AFTER; assert all C1–C10 met; commit the proof.

## 7. Open decision for the user
- **`.cursor/orchestration` data-dir rename** (e.g. → `.adf/orchestration`)? It's the feature-store path, branded "cursor" but unrelated to the tool. Renaming touches `orchestration_paths.dart` resolution + every existing feature on disk (a migration). **Recommend: defer** (keep the path; purge only the tool). Confirm or request the rename.

## 8. Risks & mitigations
- **Missed cursor ref breaks build** → eval C1==0 + full analyze/test gate after each batch; staged commits.
- **Crew-by-default slows builds / needs a key** → free NVIDIA NIM is the default crew path ($0); disclosed fallback to deterministic when no model; opt-out flag.
- **Crew produces a worse spec than expected** → C7 quality gate + the requirements-presentation hold (G1, shipped) lets the user reject/revise before implementation.
