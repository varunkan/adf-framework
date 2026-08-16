# ADF Gap Remediation Plan (2026-06-21)

Source: [ADF_JUDGE_GAPS_2026-06-21.md](../ADF_JUDGE_GAPS_2026-06-21.md) · Registry: [ADF_GAP_REGISTRY.json](ADF_GAP_REGISTRY.json)
Scope: the 30 canonical confirmed gaps (0 critical, 1 high, ~12 medium, rest low). Method for execution: spec (BMAD architect) → design → TDD test plan → implement test-first → adversarial review + self-heal.

## Principles
- **Test-first, always.** Every gap gets a RED test that reproduces it before the fix; GREEN proves the fix; full regression proves no break.
- **Single source of truth.** Python engines own logic; Dart shells the CLIs. Fix the engine, not a copy.
- **Steelman first.** Several findings carry verifier corrections (the original accusation was partly wrong). Honor the *corrected* root cause, not the raw claim. Prefer additive fixes.
- **Commit per gap (or per tight cluster).** Each commit = one RED→GREEN→regression unit.
- **Descope honestly where the roadmap says so.** Some "gaps" are plan-overreach; the cheapest correct fix is to align the doc/plan to reality (and say so), not to build the unbuilt feature now.

## Severity-honest priority (verifier-corrected)
1. **HIGH (1):** G01 verdict-path contract mismatch — the only real structural high.
2. **MEDIUM (12):** G02 policy fail-open · G03 merkle-root key · G04 mobile seal · G05 single-flight · G06 silent fallback · G07 open-questions dead · G08 NVIDIA timeout · G09 audio/repo ingest · G10 generate() model seam · G11 attribution · G12 tdd-baseline test · G13 verdict content.
3. **LOW (17):** the rest — test-hygiene, doc/label honesty, and phased deferrals.

## Workstreams (batched by FILE OWNERSHIP — this is what enables safe parallel implementation)
Gaps that touch the same file MUST be implemented in the same batch (sequential within batch) to avoid edit conflicts. Batches with disjoint file sets can run in parallel worktrees.

| Batch | Owns (files) | Gaps | Architect lead |
| --- | --- | --- | --- |
| **B1 · agent_runner.py (Python core)** | `scripts/orch/agent_runner.py` (+ its tests) | G02, G04(py side), G10, G12, G27 | security + technical + performance |
| **B2 · proof/seal (Python)** | `scripts/orch/proof_of_build.py`, `verify_audit_bundle.py`, `test_proof_of_build.py` | G04(seal branch), G14 | security |
| **B3 · model_router + clarify_swarm (Python)** | `scripts/orch/model_router.py`, `clarify_swarm.py`, `test_model_router.py` | G08, G23, G28, G26(swarm side) | performance + technical |
| **B4 · requirements_crew (Python)** | `scripts/orch/requirements_crew.py`, `test_requirements_crew.py` | G11, G13(py side), G21, G22, G23(crew labels), G25 | technical |
| **B5 · web_scraper (Python)** | `scripts/orch/web_scraper.py`, `test_web_scraper.py` | G17, G19, G20 | security + technical |
| **B6 · ingest modules (Python, NEW)** | `scripts/orch/audio_ingest.py`, `repo_analyst.py` (new) + `requirements_crew._load_sources` | G09 | technical |
| **B7 · tdd_loop/process_facts tests (Python)** | `test_tdd_loop.py`, `test_process_hardening.py`, `build_crew.py` | G16, G24, G26(build_crew) | security + technical |
| **B8 · audit_bundle + proof_check (Dart)** | `tools/orchestration_server/lib/audit_bundle.dart`, `proof_check.dart` (+ tests) | G03, G15 | security + technical |
| **B9 · crew runner + agent_crew (Dart)** | `requirements_crew_runner.dart`, `agent_crew.dart`, `orchestration_paths.dart` (+ tests) | G01, G06, G13(dart side) | technical |
| **B10 · server + concurrency (Dart)** | `bin/server.dart`, `feature_store.dart`, `phase_runner.dart`, widgets | G05, G07, G18, G29 | security + technical |
| **B11 · docs/bench (honesty)** | `docs/ADF_VS_LOVABLE.md`, `scripts/bench/scorecard.py`, plan reconciliation | G30, G22(descope), G21(descope), G20(descope), plan wording | technical |

Cross-batch dependencies: **G18→G09** (server intake needs the modules); **G11→G23** (attribution builds on the router returning model identity). Sequence B6 before B10's G18; B3 before B4's attribution.

## Phased execution (steps 4–7)
- **Step 4a — Specs (BMAD architects).** Per gap: an EARS-style spec authored by its assigned architect persona (security / performance / technical). Depth scales to effort: substantive gaps get full requirements + acceptance criteria; trivial doc/test gaps get a tight one-paragraph spec. Cross-reviewed by a second architect.
- **Step 4b — Design.** Per spec: components touched, contracts, data flow, edge cases, single-source-of-truth placement, backward-compatibility notes.
- **Step 5 — TDD test plan + cases.** Per spec: the exact RED test(s) that reproduce the gap, the GREEN assertion, and the regression set. Prove RED first.
- **Step 6 — Implement.** Batch by the table above. Within a batch: write RED test → confirm RED → implement → GREEN → batch regression. Commit per gap/cluster.
- **Step 7 — Review + self-heal.** Adversarial review each fix (does it actually close the *verifier-corrected* gap? any regression? new attack surface?), heal until green, full python+dart regression, then re-verify against the original finding.

## Out of scope this cycle (logged)
- **Free-path E2E validation (report §5.3 / roadmap #26):** the highest-value *next action*, but it's a validation run (needs free-tier NIM/Ollama availability + a real generation), not a code fix. Tracked separately; surfacing the honest 0/N numbers (G30) is the in-scope down-payment.
- **G22 real re-run caching (L):** descope to a plan-wording correction this cycle (the cheap, honest fix); real incremental caching is a future enhancement.
