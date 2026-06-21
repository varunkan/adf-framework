# ADF Validation — Multi-Agent Judge Gap Report (2026-06-21)

## 1. Executive Summary

**What was validated.** Three artifacts were put under adversarial review in a single sweep: (a) the **requirements-crew PLAN** (`~/.claude/plans/i-would-like-to-cheerful-iverson.md`); (b) the **ADF implementation** that landed against that plan (the Python orchestration crew under `scripts/orch/`, the Dart orchestration server under `tools/orchestration_server/`, the proof-of-build sealing, and the model router); and (c) **ADF-vs-north-star** — whether the shipped product advances the stated goal of generating credible apps and sealing an honest Proof of Build.

**Method.** Fourteen decomposers expanded the three artifacts into **85 atomic verification tasks**. Each atomic task was handed to **3-persona diverse-caliber judge panels** that read the *real* source (not summaries), then every raised finding was put through an **adversarial 2-verifier confirmation** pass. Findings only survived if at least one verifier could confirm the defect against cited `file:line` evidence; severities below are the verifiers' *corrected* assessments, not the panels' self-assigned ones. Several originally-"high" claims were downgraded once blast radius was traced, and a number of claims were dropped outright as false-mechanism or fabricated-premise.

**Top-line verdict (honest).** The sealing mechanics, model routing, and TDD predicates are largely sound and well-reasoned; most "high" accusations did not survive verification. But the sweep is **lopsided**: it deeply interrogated four subsystems (requirements-crew, governance-proof, model-science, security/policy) while the north-star's *primary* moat axis — **does the free path actually generate a working, multi-file app?** — and the entire verify→preview→edit runtime path went essentially unexamined. The single most consequential confirmed finding is not a crypto break but an **honesty gap**: the "scorecard" publishes only the paid run that succeeded and omits that the free/local path built **0 working apps**. The highest-severity *structural* gaps are a verdict-path writer/reader contract break and a set of seal-completeness holes (Merkle root dropped from the bundle; mobile APK facts never sealed). No CRITICAL and no HIGH-that-bypasses-tamper-detection survived; the governance seal still catches file tampering.

## 2. Severity Tally

| Severity | Count |
| --- | --- |
| Critical | 0 |
| High | 9 |
| Medium | 22 |
| Low | 4 |
| **Total confirmed** | **35** |

*(35 confirmed of 48 findings raised; 13 dropped as false-mechanism, fabricated-premise, or duplicate.)*

## 3. Top Gaps

| Rank | Title | Area | Severity |
| --- | --- | --- | --- |
| 1 | Verdict-path contract mismatch between Python crew and Dart orchestrator | Architecture Integration | High |
| 2 | Policy gate is fail-OPEN on exceptions | Security | Medium |
| 3 | Merkle root silently dropped from the audit bundle (key-name mismatch) | Governance-Proof | Medium |
| 4 | Mobile (APK) deliverable facts not folded into the sealed Merkle root | Governance-Proof | Medium |
| 5 | Concurrent crew runs corrupt the integrity ledger (no single-flight lock) | Governance-Proof | Medium |
| 6 | Crew failure silently falls back to a deterministic template spec | Governance-Proof | Medium |
| 7 | Open-questions elicitation is wired but dead end-to-end | Requirements Crew | Medium |
| 8 | NVIDIA swarm timeout is silently 120s, not the intended 240s | Requirements Crew | Medium |
| 9 | Audio (ASR) and existing-repo ingest sources are unbuilt and unwired | Requirements Crew | Medium |
| 10 | `agent_runner.generate()` has no per-call `model=`; app-gen can't route | Architecture Integration | Medium |
| 11 | Static `models` field fakes per-agent attribution; no test covers it | TDD & Coverage | Medium |
| 12 | `_tdd_red_baseline` deps-absent guard has zero direct test coverage | TDD & Coverage | Medium |
| 13 | Requirements verdict content not validated; garbage verdict can pass | Governance-Proof | Low–Medium |
| 14 | "Honest scorecard" omits that free/local builds produced 0 working apps | Honesty / Bench | Low |

## 4. Detailed Findings (by severity)

### 4.1 Architecture Integration

#### Verdict-path contract mismatch between Python crew and Dart orchestrator — HIGH

- **What's wrong:** The requirements-crew handoff has a writer/reader disagreement on the verdict file location. `requirements_crew.py` unconditionally writes the judge verdict to a hardcoded `.cursor/orchestration/...` path, while the Dart side resolves the path dynamically. The two only agree by coincidence under the default `.cursor` layout.
- **Evidence:** `scripts/orch/requirements_crew.py:359-361` (hardcoded `repo_root/.cursor/orchestration/features/{fid}/judge-verdicts`); the file reads only `ORCH_REPO_ROOT` at `:344` and never reads `ORCH_ORCHESTRATION_DIR` (nor the `.adf-install.json`/package/`.adf` layouts). Reader: `tools/orchestration_server/lib/orchestration_paths.dart:43-64` resolves the root from `ORCH_ORCHESTRATION_DIR` → `.adf-install.json` `orchestration_dir` → dir-probe of `.cursor`/`adf-framework`/`.adf`. Gate: `tools/orchestration_server/lib/requirements_crew_runner.dart:34-35` (`verdictPath` via `featureRel`) and `:62` (`existsSync()` success check). Test blind spot: `tools/orchestration_server/test/requirements_crew_runner_test.dart:119-120` writes the verdict to the Dart-resolved path under the default layout, masking the divergence.
- **Why it matters:** Whenever the resolved orchestration root is anything but legacy `.cursor/orchestration` — `ORCH_ORCHESTRATION_DIR` set, an install manifest pointing elsewhere, or the package (`adf-framework/orchestration`) / generic (`.adf/orchestration`) layouts — Python writes to `.cursor/...` while Dart reads elsewhere. The `existsSync()` gate then fails on a fully successful crew run: a phantom approval-gate failure. The trigger surface is broader than an env var alone, and the test suite cannot catch it because it only exercises the coincidentally-aligned default layout. (Note: the panel's framing that the runner "fails to pass `ORCH_ORCHESTRATION_DIR` to the subprocess" is slightly off — `Process.run` inherits the parent env, so the var does reach Python; the actual cause is that Python ignores it and all other resolution sources.)
- **Recommended fix + effort:** Make Python honor the same resolution order as Dart — read `ORCH_ORCHESTRATION_DIR`, then `.adf-install.json` `orchestration_dir`, then probe — and share/centralize the path logic so writer and reader cannot drift. Add a runner test that exercises a non-`.cursor` layout. **Effort: M.**

#### `agent_runner.generate()` has no per-call `model=`; app-generation path can't route models — MEDIUM

- **What's wrong:** The plan scoped a per-call `model=` override on `agent_runner.generate()` as "the single seam through which every subagent gets the right model." It was implemented on the backend functions and wired through `model_router`, but `generate()` itself was never updated — so only the requirements-crew path got per-call routing; the app/build-generation path remains env-var-only.
- **Evidence:** `scripts/orch/agent_runner.py:1242` (`def generate(messages, timeout):` — no `model` param); `:1264` (`call_with_retry(backend, messages, timeout)` — model not threaded); `:1253-1260` (env-var-only backend dispatch). Backends do accept it: `:1074`/`:1137`/`:1198` (`model=None`). Crew path threads it: `scripts/orch/model_router.py:109-110` (`lambda m, t: fn(m, t, model=model)`); `requirements_crew.py:31-34` uses `model_router.complete`, not `generate`. App-gen call sites bypass routing: `agent_runner.py:2078` (`_crew_generate`) and `:2625` (monolithic). Plan: `i-would-like-to-cheerful-iverson.md:70` and `:125` explicitly name `generate` for the override.
- **Why it matters:** Dynamic per-subagent/per-task model assignment (e.g. head agent on Opus, slices on NIM) is unavailable for app builds despite full backend support. This is a missing capability / incomplete design goal, not a runtime defect — app generation still works via env-default/reliability-first ordering, and the build crew's BuildAgents don't yet carry per-agent models, so there is currently no driver consuming the seam. It becomes user-relevant the moment per-agent model assignment is wired into the build side.
- **Recommended fix + effort:** Add an optional `model=None` parameter to `generate()` and thread it through `call_with_retry` to the backend, matching the `model_router` pattern; default behavior unchanged when omitted. **Effort: S.**

### 4.2 Security

#### Policy gate is fail-OPEN on exceptions — a sealed proof can falsely attest "passed security rules" — MEDIUM

- **What's wrong:** The policy gate is a true hard gate on the happy path (a real `sk-` secret is detected, `policy_blocked` is set, `seal_app` is skipped via `_PolicyBlocked`, and the runner exits 6). But the entire gate block is wrapped in a broad `try/except Exception` that only logs `"policy gate skipped"` and leaves `policy_blocked = None`. Any exception in the gate path (import error, file-read `OSError`, regex pathology) silently bypasses it: `build_ok = verified and not policy_blocked` becomes `True`, `seal_app` runs, and `sys.exit(0)` fires — even with real secrets in source.
- **Evidence:** `scripts/orch/agent_runner.py:2748` (`policy_blocked = None` init); `:2769` (`try:` wraps the whole gate including `import policy_gate`, `check_policy`, `blocking_violations`); `:2797-2798` (`except Exception as e: log("policy gate skipped: ...")` — no re-raise, no fail-closed); `:2887` (`build_ok = verified and not policy_blocked` → `True`); `:2939` (`sys.exit(0 if build_ok else 6)`). Contrast the adjacent PROCESS gate at `:2830-2835`, which deliberately fails **closed** on its own exception — proving the fail-closed pattern was known and the policy gate's omission is an inconsistency, not intent.
- **Why it matters:** The hard-gate guarantee ("a sealed Proof of Build means it passed the enforced security rules") is the security contract. Under fail-open, the failure is silent and total — a sealed proof would falsely attest compliance — and it's the security-critical gate that lacks the fail-closed handling the process gate already has. No test exercises the agent_runner exit-6 path end-to-end or the fail-open bypass (`scripts/orch/test_policy_gate.py:244-267` validates the module in isolation only).
- **Recommended fix + effort:** Mirror the process gate — on gate exception under enforced policy, set `policy_blocked = ["policy_gate_error"]` so the build fails closed; add an end-to-end test that drives agent_runner to exit 6 and one that asserts an injected gate exception blocks the seal. **Effort: S.**

#### `process_facts` nonce binding degrades to a no-op when `ADF_BUILD_NONCE` is unset — LOW

- **What's wrong:** `_current_nonce()` returns `''` when `ADF_BUILD_NONCE` is unset; `_write` stamps `''` and `_read` accepts when `obj.get("_nonce","") == _current_nonce(env)`. So under an unset nonce, a planted dict with no `_nonce` key passes the equality and is read as current-build evidence. (Note: the claim's "common non-CI case / high severity / security regression" framing is **not** supported.)
- **Evidence:** `scripts/orch/process_facts.py:89` (`return (env.get("ADF_BUILD_NONCE") or "").strip()`), `:101` (stamps `_nonce`), `:125` (equality check; empty-vs-empty passes). Test gap: `scripts/orch/test_process_hardening.py:30-60` only uses non-empty nonces; lines 67-76 plant non-dicts rejected by `isinstance`, not the nonce path.
- **Why it matters:** Defense-in-depth / test-coverage, not an exploitable hole. The only sealing path, `agent_runner.main`, unconditionally `shutil.rmtree`s `.adf-process/` (`agent_runner.py:2524`) **and** sets a fresh UUID nonce (`:2525`) before any recorder or read runs, so every real attestation has a clean dir and a unique non-empty nonce. The risk is latent: a future refactor that dropped the wipe would have only the now-no-op nonce left, with no test to catch the regression. The docstring (`:84-87`) already documents the no-op as intentional.
- **Recommended fix + effort:** Add a regression test asserting a planted `_nonce=""` dict is rejected under the production (wiped + UUID-nonce) path; optionally make `_read` reject artifacts lacking a `_nonce` key outright. **Effort: S.**

#### `web_scraper` fallback has no robots.txt awareness — LOW

- **What's wrong:** The raw urllib fallback fetches URLs with no robots.txt compliance (no `Disallow`/crawl-delay/allow logic). The claim's framing as a **plan-vs-implementation breach** is **false** — the cited "robots-aware" plan text does not exist anywhere in the repo or git history — so this is a missing-feature/hardening gap, not a contract violation.
- **Evidence:** `scripts/orch/web_scraper.py:24-25` (imports only `urllib.parse`/`urllib.request`, no `robotparser`); `:52-60` (`_http_get` does a direct `urlopen` with only a `User-Agent: ADF-Research/1.0` header); `:104` (the only "robot" token is a CAPTCHA-detection regex); `:192-214` (`gather` fetches up to `max_pages=8`). `git log --all -S 'robots-aware'` returns no commits.
- **Why it matters:** A research run can fetch pages a site's robots.txt disallows. Impact is low: a User-Agent is set, primary traffic routes through Jina/Firecrawl (which manage their own compliance), the fallback is a single GET per URL (no recursion, no rate loop, no auth/secret exposure), capped at ~8 pages/run. Real ToS-politeness gap, not a security exploit.
- **Recommended fix + effort:** In the urllib fallback, parse the target's `/robots.txt` via `urllib.robotparser.RobotFileParser` and skip disallowed URLs; honor crawl-delay; add a test. **Effort: M.**

### 4.3 Governance-Proof

The following gaps were each adversarially verified. Severities reflect *corrected* assessments — several were downgraded from the original "high" once the actual blast radius was traced, and one finding's asserted mechanism was found false and is reported as the smaller real residual. **No CRITICAL or HIGH survives verification** — every original "high" was either correctly downgraded (truncated seal still binds the root; auto-approve is track-gated; tamper detection still fires) or partially false in its asserted mechanism.

#### Merkle root is silently dropped from the audit bundle (key-name mismatch) — MEDIUM

- **What's wrong:** The Dart audit bundler reads `proof['root']`, but the Python sealer writes the Merkle root under `merkle_root`. Against every real `.adf-proof.json`, `proof['root']` resolves to `null`, so `moat.proof.root` is null in every shipped bundle — and that null is folded into the sealed `bundle_digest`.
- **Evidence:** `tools/orchestration_server/lib/audit_bundle.dart:121` (`'root': proof['root']`) vs `scripts/orch/proof_of_build.py:238` (`"merkle_root": root`); digest coverage at `audit_bundle.dart:75,79-80`. Confirmed against all 12 `apps/*/.adf-proof.json` (all have `merkle_root`, none have `root`). The unit-test fixture masks it: `tools/orchestration_server/test/audit_bundle_test.dart:135` hard-codes the wrong key `'root'` to match the buggy reader, and the moat assertions (`:160-165`) never check `moat.proof.root`. The standalone verifier never reads either key (`scripts/orch/verify_audit_bundle.py:300-304` checks only `seal`).
- **Why it matters:** The Merkle root is the core integrity claim of the Proof of Build. The bundle's moat summary advertises and digests `root: null` instead of the real root — a misleading, incomplete attestation in every shipped governance bundle. Not a full tamper bypass: `seal = "adf1:" + root[:12]` (`proof_of_build.py:239`) is read correctly and is digest-covered, so a 48-bit prefix of the real root is still bound — but the full 256-bit root is not independently bound by the moat summary.
- **Recommended fix + effort:** Read `proof['merkle_root']` (with a fallback to `root` for legacy proofs) in `audit_bundle.dart`; fix the test fixture to use `merkle_root`; add an assertion that `moat.proof.root` equals a real `seal_app()` output; add a `root`/`merkle_root` presence+match check to `verify_audit_bundle.py`. **Effort: S.** *(Merges two separately-filed findings — "reads wrong key" and "fixture masks the mismatch" — which share one root cause.)*

#### Mobile (APK) deliverable facts are not folded into the sealed Merkle root — MEDIUM

- **What's wrong:** `_verdict_bytes()` seals `stack`, `verified`, `verify_summary`, and conditional `policy`/`render`/`process` — but has no branch for `mobile`. The `mobile_facts` dict (APK sha256, package id, size, emulator preview) passed into `seal_app()` is dropped from both the Merkle root *and* the recorded proof metadata. The `.adf-mobile/` artifacts are also excluded from the file leaves by the dot-dir filter in the source walker.
- **Evidence:** `scripts/orch/proof_of_build.py:62-84` (no `mobile` branch; metadata block `:228-234` also omits it; `grep "mobile"` → zero matches). `scripts/orch/agent_runner.py:2869` passes `"mobile": mobile_facts`; the comment at `:2851` ("its hash sealed below so the downloadable binary is attested") is **false**. File walker excludes `.adf-mobile/` at `agent_runner.py:2148-2152` (write site `:1779`). Reproduced empirically: two `compute_proof` calls differing only in `build['mobile']['sha256']` ('deadbeef' vs 'CHANGED__') produce a byte-identical `merkle_root`.
- **Why it matters:** A swapped/tampered APK or forged emulator preview recomputes to VERIFIED — `verify_proof` cannot detect it. The documented contract ("prove the downloaded APK is the one ADF built") is broken, and the in-code comment actively asserts a guarantee that does not hold. Scoped: only affects `expo-rn` builds where native delivery actually ran; web builds and all file/spec/policy/render/process attestations remain sound.
- **Recommended fix + effort:** Add a `mobile` branch to `_verdict_bytes()` (fold in `apk_sha256` + key preview facts), or seal `.adf-mobile/facts.json` as a leaf; record `mobile` in proof metadata; correct the false comment; add a test mutating the APK sha and asserting the root changes. **Effort: S.**

#### Concurrent crew runs corrupt the integrity ledger (no single-flight lock) — MEDIUM

- **What's wrong:** Nothing guards `runCrewForFeature` per `featureId`. `kickAutopilotBackground` fires it unawaited on feature-create; `POST /features/<id>/autopilot` calls it directly. Both build a fresh `AgentCrew` sharing the same top-level `IntegrityChain` and on-disk ledger. With `await` suspension points inside the per-phase seal loop, two concurrent runs interleave: duplicated/interleaved phase blocks in the ledger, last-write-wins on `state.json`, and racing artifact writes to `specs/$id`.
- **Evidence:** `tools/orchestration_server/bin/server.dart:219-225` (no in-flight check), `:479-490` (unawaited spawn), `:954` (fired on create), `:1285-1298` (direct call). Suspension points: `agent_crew.dart:229,262`. Unsynchronized state RMW: `agent_crew.dart:361-373`. Append seal: `integrity_chain.dart:209-232`. A repo-wide grep for mutex/inflight/single-flight over the crew path returns no relevant guard (the `phase_runner.dart` `_active` set guards a different subsystem).
- **Why it matters:** The proof-of-build ledger can accumulate duplicate phase seals and reflect race-corrupted artifacts. **Correction to the original claim:** this is NOT a cryptographic "fork." `seal()` is fully synchronous and re-reads `prevHash` fresh on each call, so hash linkage stays valid and `verify()` reports no `chain_broken` — the failure mode is a *duplicated/race-corrupted single chain*, not two parallel forks. Requires a second concurrent trigger within the run window; not the default single-run path.
- **Recommended fix + effort:** Add a per-`featureId` in-flight guard (a `Set<String>` or `Mutex`) checked in `runCrewForFeature`; reject or coalesce a second trigger while one is active. **Effort: S–M.**

#### Crew failure silently falls back to a deterministic template spec — MEDIUM

- **What's wrong:** When `RequirementsCrewRunner.run()` returns false (process crash, exit ≠ 0, or missing verdict file), `_specPhase` drops straight to `engine.generatePhase(id, 2)` with no log, no state flag, no warning, and no thrown exception. The fallback returns normally, so `_runWithBudget` stamps the spec-writer agent `status: 'ok'` — indistinguishable from a real crew success — and the template spec is sealed via `integrity.seal(..., actor: 'adf-crew')`.
- **Evidence:** `tools/orchestration_server/lib/agent_crew.dart:106-112` (silent fallthrough), `:327-334` (stamped `ok`), `:279` (sealed as `adf-crew`). Silent failure modes in `requirements_crew_runner.dart:59-64`. The garbage floor (`scripts/orch/validate_adf_artifacts.sh:61-69`) only catches `@orch-orchestrator` spam and 1–2-word SHALL fragments — a well-formed deterministic spec passes cleanly.
- **Why it matters:** A crashed requirements crew advances the pipeline and cryptographically seals a template spec as if requirements were researched, with zero audit trail — directly undermining the governance guarantee that a sealed spec was research-grounded. **Scope correction:** the claim's "on crew failure" overstates — *timeout* failures DO produce explicit `timed_out`/`blocked` entries and halt. Only the *non-timeout* failure path is genuinely silent. No correctness impact on the artifact's structural validity.
- **Recommended fix + effort:** On `run()==false`, write a `crew-log.jsonl` entry and a `state` flag (e.g. `spec_source: 'deterministic_fallback'`), surface it in the UI, and either seal under a distinct actor or block advancement pending user acknowledgement. **Effort: S–M.**

#### Requirements verdict content is not validated; a garbage/empty verdict can pass the gate — LOW–MEDIUM

- **What's wrong:** `RequirementsCrewRunner.run()` decides success from `exitCode == 0 && File(verdictPath).existsSync()` — file *existence* only, never content. An empty or garbled verdict file satisfies the gate, contradicting the docstring's promise that "a crashed/empty crew run can NEVER fake a pass." The "NEVER fakes a pass" test covers exit≠0 and exit==0+no-file, but not exit==0+empty/garbage-content. Separately, `requirements_crew.py main()` returns `0` unconditionally regardless of `po_pass`.
- **Evidence:** `requirements_crew_runner.dart:62` (existence-only); docstrings `:14-15,42-43`. Test gap: `requirements_crew_runner_test.dart:102-115`. Self-demonstrating: the P4 test at `:84` creates an empty verdict file and `run()` still proceeds. No downstream content floor: `run_post_sync.dart:101` advances on bare `existsSync()`. `requirements_crew.py:369` (`return 0`), though the verdict PASS/REVISE content IS written (`:231`) and parsed in Dart (`run_post_sync.dart:50`).
- **Why it matters:** A partial-failure crew (exits 0, writes empty/corrupt verdict) can advance the requirements-approval gate. **Important scope:** this is *not* a default-path governance bypass. The verdict content IS enforced at the `/approve` gate (`approval_gate.dart:42`, `decision=='approved' && verdict!='pass'` → HTTP 409), and tracks M/L/XL never auto-flow (`feature_store.dart:710-712`) — so a REVISE on typical (net-new) requirements still pauses for a human. The silent pass-through requires auto-approve explicitly enabled AND an empty/garbage verdict. Blast radius is the advisory spec stage, not production deploy.
- **Recommended fix + effort:** Parse the verdict file in `run()` and require a recognizable PASS/REVISE token (reject empty/garbage); add the missing negative test; optionally have `main()` exit non-zero on REVISE. **Effort: S.** *(Merges the "exit-code-unconditional-0" finding with the "missing garbage-verdict test" finding.)*

#### `backend`/`model` Merkle-exclusion is implementation-true but test-unproven — LOW

- **What's wrong:** `compute_proof()` correctly excludes `created_at`, `backend`, and `model` from the Merkle leaves (they appear only in the returned proof dict). But the test suite has a named exclusion test for `created_at` only; no test mutates `backend` or `model` and asserts the root is unchanged.
- **Evidence:** `scripts/orch/proof_of_build.py:62-84` (`_verdict_bytes` omits all three), `:227-230` (recorded in dict, not leaves). `scripts/orch/test_proof_of_build.py:53-57` (only `created_at` tested); BUILD fixture `:15-16` pins `backend`/`model` and never varies them.
- **Why it matters:** Code is correct — this is purely a gap in the evidentiary record. Under a regulatory/audit lens where every attested property needs a matching test, two of three exclusion claims are unproven by the suite.
- **Recommended fix + effort:** Add two 3-line tests mirroring `test_created_at_is_metadata_not_in_the_root` for `backend` and `model`. **Effort: S.**

#### Audit-bundle proof endpoint shows only the LIVE policy verdict, never the sealed one — LOW

- **What's wrong:** **The claim's stated mechanism is false** and is dropped: `verify_proof.py --json` emits no `policy` key, so `proof_check.dart` does not *replace* a sealed verdict — it *adds* a live `checkPolicy()` result. The real residual gap: the sealed `verdict.policy` from `.adf-proof.json` is never surfaced in `GET /features/<id>/proof` at all. The response shows only the live `policy_gate.py` result, with no sealed-vs-live comparison and no staleness flag.
- **Evidence:** `proof_check.dart:41` (`{...report, 'policy': await checkPolicy(id)}`); `proof_of_build.py:430-446` surfaces only `verdict.get("process")`, not `policy`; `verify_proof.py` has zero `policy` references. Sealed `verdict.policy` present but unused, e.g. `apps/url-shortener-web-page/.adf-proof.json`.
- **Why it matters:** A minor transparency/auditability shortfall — no dual-verdict display. It is **not** an exploitable bypass: editing any sealed file flips file hashes → `status: TAMPERED`, `root_ok: false` (`proof_of_build.py:388-393,413,431`), and the live policy run also flips to VIOLATED — both signals agree, so the asserted "shows compliant while sealed says otherwise" contradiction cannot arise.
- **Recommended fix + effort:** Surface the sealed `verdict.policy` alongside the live result (`sealed_policy_ok` vs `live_policy_ok`) and flag any divergence. **Effort: S.**

### 4.4 Requirements Crew

Six confirmed gaps, deduplicated and ranked by adversarially-verified severity (not the original claim's self-assigned severity). All are plan-vs-implementation or logic defects; none are fabricated, though one (web_scraper pipeline) was disputed by a verifier and survives only on the strength of the plan text, and one (open-questions) survives with a corrected root cause.

#### Open-questions elicitation is wired but dead end-to-end — MEDIUM

- **What's wrong:** The P3 "interactive requirements confirmation" feature appears complete but renders nothing in production. The crew produces `requirements_open_questions`, the server serializes them, and a dedicated `RequirementsQuestionsPanel` exists — but a key-path mismatch means the panel always reads an empty value and short-circuits to `SizedBox.shrink()`. (Note: the original claim's diagnosis — "no presenter exists / key never read" — is wrong; a presenter exists and the key *is* serialized. The corrected, verified root cause is a payload-shape mismatch.)
- **Evidence:** Server nests the key under `summary`: `feature_store.dart:847` (inside `featureSummary()`), surfaced as `detail['summary']` at `feature_store.dart:931`; `server.dart` (buildDetailPayload/featureDetailPayload, ~`397-432`) never lifts it to top level. Panel reads it at the *top* level: `requirements_questions_panel.dart:14` (`detail?['requirements_open_questions']`), short-circuits empty at `:20`. Screen passes the full payload: `feature_detail_screen.dart:1271`. The only test feeds a synthetic top-level map (`requirements_questions_panel_test.dart:30-31`), so it never exercises the real nested shape.
- **Why it matters:** The flagship interactive elicitation loop is silently non-functional — questions are generated and shipped to the client but never shown, and no test catches it. Highest user-facing impact of the set.
- **Recommended fix + effort:** Either change `fromDetail` to read `detail?['summary']?['requirements_open_questions']`, or lift the key to the top-level detail payload in `server.dart`. Add a screen/integration test that feeds the real nested server shape. **Effort: S.**

#### NVIDIA swarm timeout is silently 120s, not the intended 240s — MEDIUM

- **What's wrong:** `clarify_swarm.py:154` does `os.environ.setdefault("ADF_NVIDIA_TIMEOUT_SEC", "240")` intending 240s worker timeouts, but the value is combined via `min()`, so it can only *lower* the effective timeout, never raise it. The swarm's `_complete()` wrapper never passes a timeout, so `model_router.complete`'s hardcoded `timeout=120` wins: `min(120, 240) = 120`. The 240 setdefault is dead intent.
- **Evidence:** `clarify_swarm.py:38` (`complete(prompt, role, system=system)` — no timeout) and `:154` (the setdefault); `model_router.py:113` (`def complete(..., timeout=120, ...)`) forwarded unchanged at `:124`; `agent_runner.py:1084` (`nv_timeout = min(timeout, int(os.environ.get("ADF_NVIDIA_TIMEOUT_SEC", "75")))`).
- **Why it matters:** Slow free-tier NIM responses needing 120–240s are cut off early despite config attempting to allow them, then fall through to the next provider. Nothing crashes, but configured intent is silently defeated and the code carries a misleading dead knob.
- **Recommended fix + effort:** Have `_complete()` pass `timeout=int(os.environ.get("ADF_NVIDIA_TIMEOUT_SEC", "240"))`, or make `model_router.complete`'s default read the env var. **Effort: S.**

#### Audio (NIM ASR) and existing-repo ingest sources are unbuilt and unwired — MEDIUM

- **What's wrong:** The approved plan lists 8 first-class Wave-1 multimodal sources; 2 of them — voice/audio (`audio_ingest.py`, NIM ASR) and existing-repo analysis (`repo_analyst.py`, reusing the code-review-graph MCP) — are named NEW deliverables but neither file exists nor is wired. The crew's `_load_sources` handles only url/link passthrough and path→doc_ingest; there is no audio or repo branch.
- **Evidence:** `find` (repo-wide, excl. node_modules) returns neither `audio_ingest.py` nor `repo_analyst.py`. `requirements_crew.py:312-332` (`_load_sources`) branches only on url/link and path; grep for `audio|asr|repo_analyst|whisper|transcribe|code-review-graph|repo_path` → no matches. Plan `i-would-like-to-cheerful-iverson.md:50,58-59,125-126`. Self-acknowledged in memory `adf-requirements-crew.md:20,37` ("STILL TODO").
- **Why it matters:** A genuine plan-vs-impl overstatement — 2 of 8 advertised sources don't ship. Bounded: the other 6 (web, docs, url/link, data, mockup-via-doc, figma) are built and E2E-verified, and the gap is self-documented as remaining work, not a silent regression.
- **Recommended fix + effort:** Implement `audio_ingest.py` (ASR → transcript → extract) and `repo_analyst.py` (wrap code-review-graph MCP), add corresponding branches to `_load_sources`, with tests. Or, if deferring, downgrade the plan/docs to stop advertising them as shipped Wave-1 sources. **Effort: M** (build) / **S** (descope docs).

#### Dart `POST /features` parses only `sources:[{url}|{path}]`; multimodal intake fields and uploads absent — LOW

- **What's wrong:** The plan's Dart intake spec lists `attachments[]`, `mockups[]`, `figma_url`, `reference_sites[]`, `audio[]`, `repo_path`, `data_files[]`. The handler parses only `body['sources']` and reads the body as a single JSON string, so multipart file uploads cannot be handled at all. (The Figma path that exists only sniffs a URL out of requirement *text* — not an explicit `figma_url` field.)
- **Evidence:** `server.dart:889-981` (handler); `:891-892` reads body as one JSON string (no multipart); `:924-927` parses only `sources` → `store.writeSources`. Grep of `tools/orchestration_server/` for `mockup|figma_url|repo_path|data_files|reference_sites|attachments|audio|multipart|MultipartRequest|/upload` → zero hits. Memory `adf-requirements-crew.md:35,37` marks this STILL TODO. (Caveat: verifier could not find the cited plan "line 126" as checked-in markdown; the implementation gap itself is unambiguous.)
- **Why it matters:** Server-side counterpart to the missing Python modules above — the intake API can't accept uploads/audio/repo paths. Low because it's an intentional phased deferral: the link/path path works end-to-end and is server-E2E tested (P5), and the Python `doc_ingest` backend already handles PDF/DOCX/etc.
- **Recommended fix + effort:** Add multipart parsing and the additional intake fields to the handler, wired to `doc_ingest`/the new ingest modules. **Effort: M.**

#### `gather()` silently drops user URLs beyond `max_pages=8` — LOW

- **What's wrong:** `gather()` truncates the combined target list with `targets[:max_pages]` (default 8). User-named ("authoritative") URLs are prepended first, so priority is honored *within* the 8-URL window — but if a user supplies >8 URLs, the excess are dropped with no log, warning, or record. The cap is undocumented in the docstring; both real callers invoke `gather()` without overriding `max_pages`.
- **Evidence:** `web_scraper.py:193` (`max_pages=8`), `:199-208` (user URLs prepended), `:210` (`targets[:max_pages]` truncation), `:194-195` (docstring omits cap). Callers: `requirements_crew.py:144`, `clarify_swarm.py:45`. Test gap: `test_web_scraper.py:108` (1 user URL), `:115` (disabled) — no >8 case.
- **Why it matters:** Narrow edge case — only bites when a user names more than 8 authoritative URLs, in which case later ones are silently discarded. Degrades gracefully (still returns a corpus). The original claim that this "contradicts authoritative-first priority" is overstated; the real issue is silent data loss + missing warning at the >8 boundary.
- **Recommended fix + effort:** Log/surface a warning when targets are truncated; document the cap; consider keeping all user URLs and only capping search-derived results. Add a >8-URL test. **Effort: S.**

#### `web_scraper.scrape()` is hard-truncate + single LLM extract, not the plan's chunk → rank → cite pipeline — LOW

- **What's wrong:** The plan promises "query-expand → fetch → de-boilerplate → chunk → relevance-rank → summarize-with-citations." The implementation hard-slices `body = page["markdown"][:12000]`, passes the whole truncated body to one `complete(...)` extract call, and returns `citations: [url]` (the source URL echoed, not citations bound to ranked passages). No chunking, ranking, per-chunk scoring, or query-expansion exists.
- **Evidence:** `web_scraper.py:179` (`[:12000]`), `:181-186` (single extract), `:189` (`citations: [url]`). Grep `chunk|rank|score|segment|relevance|summariz` → no pipeline code. Plan `i-would-like-to-cheerful-iverson.md:76-77` (verbatim pipeline text). (One verifier ruled this NOT REAL on the basis that the code's own *docstring* makes no such promise; it survives because the approved *plan* does, confirmed verbatim. Also: memory `adf-requirements-crew.md:37` claims commit 55ac935 left "no `[:N]` literals" — `:179` violates that stated invariant.)
- **Why it matters:** Quality ceiling, not a break. Source content past 12k chars is silently dropped (long regulatory/FDA pages get cut), and relevance is delegated entirely to one prompt instead of a retrieval stage. Degrades gracefully and still yields a focused, source-attributed note.
- **Recommended fix + effort:** Either implement chunk→rank→cite, or route the slice through the canonical `compaction.clip` and downgrade the plan wording to match reality. **Effort: M** (real pipeline) / **S** (descope + use compaction).

### 4.5 Plan Soundness & Research-Synthesis

#### Wave 1 `research-synth` (Qwen per-domain-slice summarization) is unimplemented — LOW

- **What's wrong:** The design specifies a dedicated Wave-1 `research-synth` agent, one per domain slice, using Qwen long-context to produce `{slice, facts[], citations[]}`. No such layer exists: the implementation calls `gather()` and passes the corpus straight to Wave 2. The planned Qwen long-context model assignment is unused, and there is no per-domain-slice aggregation granularity.
- **Evidence:** Plan `/Users/varunkumar/.claude/plans/i-would-like-to-cheerful-iverson.md:39` (`research-synth (one per domain slice) … {slice, facts[], citations[]} … Qwen long-context`; roster `:28`). Impl `scripts/orch/requirements_crew.py:143-145` (`gather()` → `_corpus_text()`, fed directly to Wave 2 at `:153`) — no `BuildAgent`/Qwen invocation between gather and drafting. `web_scraper.py:172-214` `gather()`/`scrape()` only do per-URL extraction.
- **Why it matters:** Limited. A functional substitute is already in place: `web_scraper.scrape()` runs a per-page Llama-70B extraction (`web_scraper.py:181-189`, `role='extract'`) returning `{facts, citations:[url]}`, and `_corpus_text()` (`requirements_crew.py:101-107`) assembles those cited facts with head+tail `compaction.clip` (not blind truncation). So Wave 2 receives per-page LLM-filtered, cited facts — the panel's "unfiltered raw text forcing agents to filter themselves" is false. What is genuinely missing is slice-level aggregation and the Qwen long-context assignment; no correctness or safety impact.
- **Recommended fix + effort:** Either implement the per-domain-slice Qwen synth pass between `gather()` and Wave 2, or formally retire `research-synth` from the design and document the per-URL extract step as the accepted substitute. **Effort: M** (build) / **S** (reconcile the plan).

#### Re-run cost claim is unimplemented: every invocation runs the full wave DAG — LOW

- **What's wrong:** The plan promises "Re-runs touch only affected agents + the head (cheap)," but `requirements_crew.run()` executes all five waves unconditionally on every call. There is no cache-file read, no content-hash/fingerprint check, no affected-agent or dirty/stale tracking, and no conditional wave/early-exit skip anywhere in the function. A re-run of the same requirement with the same sources re-executes the entire multi-LLM pipeline at full cost.
- **Evidence:** Plan claim `/Users/varunkumar/.claude/plans/i-would-like-to-cheerful-iverson.md:80` ("Re-runs touch only affected agents + the head (cheap)"); `:119` describes a unit test for this that was never written. Unconditional waves in `scripts/orch/requirements_crew.py` (`run()`, lines 118-214): Wave 0 plan `complete()` @137; Wave 1 `gather()` @144; Wave 2 `build_crew.run_crew(draft_agents)` @157; Wave 3a po `@172`; Wave 3b questions @181; Wave 4 synthesis @188 and cross-check @195 — all top-to-bottom with zero conditionals. `grep -niE 'cache|skip|affected|incremental|dirty|stale|rerun|fingerprint|hash|reuse|memoiz'` returns only an unrelated docstring "reuse" and the closure names `run_draft`/`run_po`; the `prior` parameter is never referenced.
- **Why it matters:** A cost/efficiency promise the system does not deliver, so re-runs are full-price rather than cheap. No correctness, security, or trust impact — outputs remain correct. Practical exposure is modest because requirements runs are per-feature and rarely re-invoked on identical inputs in a tight loop. The risk is mainly that the plan documents a guarantee (and a test) that does not exist.
- **Recommended fix + effort:** Either (a) implement the claimed incrementality — persist per-wave outputs keyed by a content hash of requirement + sources + agent config, skip waves whose inputs are unchanged; or (b) correct the plan to drop the "cheap re-run" claim and remove the unwritten test. **Effort: L** (real caching) / **S** (correct the plan wording).

### 4.6 Model Science (Labels)

All four originally-filed "plan-vs-impl" model findings are the same defect class (stale "Nemotron Ultra"/"DeepSeek R1" labels vs. actual Qwen/Super/v4-pro routing); every verifier downgraded each to LOW with no functional/user impact. Merged into one gap.

#### Stale model-science labels: docstrings/comments/one user-facing artifact cite Nemotron Ultra and DeepSeek R1, but the router runs Qwen, Nemotron Super, and DeepSeek v4-pro — LOW

- **What's wrong:** Across the requirements crew and router, prose, inline comments, and one user-facing artifact name models that the router never selects on the default (free) path. The verifiers confirmed the *routing itself is correct and deliberate*; only the labels lie. Specifically:
  - `plan` role is labeled "Nemotron Ultra" but routes to Nemotron Super 49B (DeepSeek fallback); Ultra is never eligible for `plan` under any env.
  - The PO `verify`/`cross_check` role is labeled "DeepSeek R1" but runs `deepseek-ai/deepseek-v4-pro` (R1 404s on NIM).
  - Free-path `synthesis`/`questions` heads are documented as falling to "Nemotron Ultra" but default to Qwen; Ultra only prepends under `ADF_QUALITY=max`.
  - The `judge` role is documented as "Nemotron Ultra" but defaults to Qwen; Ultra only swaps in under `ADF_QUALITY=max`.
- **Evidence:** `scripts/orch/model_router.py:43` (`"plan": [("nvidia", _M["super"]), ("nvidia", _M["deepseek"])]`); `_HEAD_ROLES` at `:65` excludes `plan`; max-swap at `:90-91` guarded by `if role in _HEAD_ROLES`. `requirements_crew.py:7,136` (`# Wave 0 — plan (Nemotron Ultra)` — wrong). `model_router.py:24` (`"deepseek": "deepseek-ai/deepseek-v4-pro"`; substitution disclosed `:20-22`). Stale "DeepSeek R1" labels: `model_router.py:10`; `requirements_crew.py:10,12`. `model_router.py:57` (synthesis Qwen-first NVIDIA, free-path strip `:92-93`). `model_router.py:46` (`"judge": [("nvidia", _M["qwen"])]`; Ultra prepend only `:90-91`). **User-facing artifact (worst of the set):** `requirements_crew.py:239` — printed PO verdict `_(perspective-diverse: DeepSeek R1 ∥ Nemotron Ultra)_`, written into the gate output, names two models that did not run on the default path; inline comment `:162` likewise stale. Misleading test docstring: `test_model_router.py:60` claims "synthesis head falls to NVIDIA (Nemotron Ultra)" while the assertion at `:42` correctly asserts the head is *not* Ultra.
- **Why it matters:** No runtime, behavioral, or capability impact — the routing is internally consistent and the lineage-independence invariant (generator≠verifier; verify=DeepSeek ∥ judge=Qwen, different pretraining families) holds and is test-covered (`test_model_router.py:25-33, 41, 44-46`). The cost is twofold: (1) the `:239` string ships a *user/gate-facing* claim about which models verified the PRD that is factually false on the default path, undermining trust in the proof artifact; (2) the design-rationale prose is anchored to R1's "RL-trained o1-class long-CoT" property, which is not established for v4-pro — misleading a developer reading the comments to understand the diversity guarantee.
- **Recommended fix + effort:** Sweep the five label sites to reflect actual default-path models; make the `:239` string dynamic (emit the model ids the router actually returned for `verify`/`judge`, showing Ultra/R1 only when `ADF_QUALITY=max`); update the test docstring at `:60`; optionally soften the "RL-trained long-CoT" rationale where it now describes v4-pro. Pure documentation/label change, no routing edits. **Effort: S.**
- **Soft science note (not a separate gap):** on the *default free path* the PO pair is reasoner ∥ long-context (DeepSeek v4-pro ∥ Qwen) rather than the plan's intended reasoner ∥ reasoner (R1 ∥ Ultra). Perspective diversity survives; the "both rigorous self-verifiers" property is only recovered at `ADF_QUALITY=max`. This is an intentional, documented availability trade-off (planned models 404 on the free NIM endpoint), belonging in the fix's rationale comment, not as a defect.
- **Dropped:** the framing of all four original claims (the alleged routing/architecture break, the "silent" substitution, the fabricated "Ultra 253B" judge target, and the non-existent committed "Wave 0 / Wave 3 plan table") — every verifier found these parts false or unsubstantiated.

### 4.7 TDD & Test Coverage

#### `_tdd_red_baseline` deps-absent guard has zero direct test coverage — MEDIUM

- **What's wrong:** The branch that prevents an un-`npm install`ed app from producing a fake GREEN (returns INCONCLUSIVE `{red: False, vacuous: False}` when `node_modules` is missing) is never exercised by any test. The function is referenced only by its definition and its single production call site.
- **Evidence:** `scripts/orch/agent_runner.py:2043-2045` (the guard); only other reference is `agent_runner.py:2026` (def) and `:2675` (call). `grep -rn "_tdd_red_baseline" scripts/orch/test_*.py` → zero hits. `test_tdd_loop.py:43-68` tests only the pure `tdd_loop.red_baseline`; `test_agent_runner.py` `node_modules` tests target `warm_node_modules`/`_ensure_template_node_modules` only.
- **Why it matters:** A trust-bearing honesty seam. A regression that removes or inverts the `node_modules` check would let a missing-deps failure be scored as a real RED (→ spurious GREEN) and pass the suite silently.
- **Recommended fix + effort:** Add one test that calls `_tdd_red_baseline` against an app dir with no `node_modules` and asserts `red is False, vacuous is False` plus the "deps absent" reason. **Effort: S.** *(One verifier downgraded to low — trivial 3-line `isdir` check, low intrinsic regression risk, covered transitively in integration. Held at medium for what it guards.)*

#### Static `models` field fakes per-agent attribution the plan requires; no test covers it — MEDIUM

- **What's wrong:** `requirements_crew.py` records `"models": "free NVIDIA bulk + Opus head"` — a hardcoded literal copied from the plan's example parenthetical, not actual per-agent attribution. The routing layer knows which model served each role but never surfaces it: `_complete` discards the model identity, and the phase-2.md writer emits an equally static `_(perspective-diverse: DeepSeek R1 ∥ Nemotron Ultra)_` line. No test validates per-agent attribution.
- **Evidence:** `requirements_crew.py:210` (static literal); `:34` (`_complete` returns text only); `model_router.py:122-128` (`complete()` returns served `(text, usage)` but not model identity); `requirements_crew.py:237-240` (static phase-2 line). Plan item: `i-would-like-to-cheerful-iverson.md:121` ("log which model each agent used"). The pharma test (`test_requirements_crew.py:27-42`) is fully mock-injected; `e2e_server.sh` exercises a URL-shortener — neither validates attribution.
- **Why it matters:** A plan verification item satisfied in name only. The recorded attribution is cosmetic and would not detect a routing change. Impact is observability/metadata, not the produced PRD — hence not higher than medium.
- **Recommended fix + effort:** Have `model_router.complete()` return the served `(prov, model)` and have the crew collect a per-role map into the `models` field; assert it in a routing-aware test. **Effort: M.** *(One verdict marked this "not real" claiming no such plan item exists — factually wrong; the plan line is at `:121`.)*

#### Red-without-green path doesn't assert the persisted `status='skipped'` — LOW

- **What's wrong:** `test_red_without_green_is_not_proven` asserts only `fact["proven"] is False`; it never calls `read_process_facts` to confirm the artifact persists `status="skipped"`. The implementation is correct, but this path's end-to-end seal is unverified.
- **Evidence:** `test_tdd_loop.py:88-91` (no `read_process_facts` call) vs. the vacuous-path test at `:82-86` which does assert the persisted status. `tdd_loop.py:76` and `process_facts.py:201-207` are both correct.
- **Why it matters:** Low — the same `else` branch is exercised transitively by the vacuous test; only the direct red-without-green→persisted-status chain lacks an assertion. Pure test-hygiene.
- **Recommended fix + effort:** Add `read_process_facts` + `assertEqual(status, "skipped")` to the existing test. **Effort: S.**

#### Written `requirements-draft.json` `sources` traceability is never asserted on disk — LOW

- **What's wrong:** `test_writes_spec_artifacts` loads the written `requirements-draft.json` and asserts only `feature_id == "pharma-demo"`; it never asserts `draft["sources"]` is present/non-empty. The traceability list is tested in-memory but not on the serialized artifact.
- **Evidence:** `test_requirements_crew.py:79-80` (single assertion) vs. in-memory coverage at `:59-63`. `requirements_crew.py:205` (`"sources"` is a sibling key) and `:219-221` (single `json.dump`) confirm sources is written.
- **Why it matters:** Low — sources and feature_id are sibling keys serialized in one `json.dump`; no realistic path drops sources while keeping feature_id. Blind spot is the serialization round-trip only.
- **Recommended fix + effort:** Add `assertTrue(draft["sources"])` to the existing on-disk test. **Effort: S.**

### 4.8 Performance

Both gaps below were confirmed but corrected down to **low**: the code is functionally correct on the primary (macOS) host; the real defects are documentation accuracy, telemetry labeling, and missing test coverage. Neither is a correctness or runtime regression.

#### Swarm parallelism is pool-bounded at 8, and no test proves concurrent execution — LOW

- **What's wrong:** The swarm can *generate* hundreds-to-thousands of tasks, but executes them through a `ThreadPoolExecutor` capped at `ADF_SWARM_PARALLELISM` (default 8). At ~900-1020 tasks (tracks L/XL), at most 8 workers run at any instant. The "massively parallel 100s-1000s workers" framing describes task count, not concurrent execution. Separately, no test ever proves two workers ran simultaneously.
- **Evidence:** `scripts/orch/build_crew.py:130-131` (`ThreadPoolExecutor(max_workers=max(1, parallelism))`); `scripts/orch/clarify_swarm.py:160` (default 8), `:4-5` ("the massive parallel muscle"), `:185` ("spinning {len(tasks)} worker agents"); `test_clarify_swarm.py:47-53` asserts only call counts; no wall-clock timing, `threading.active_count()`, thread-ID diversity, or barrier anywhere.
- **Why it matters:** The pool cap is a deliberate, correct design choice (rate-limit resilience). But the "massive parallel" wording overstates the runtime concurrency ceiling, and the missing test means a future regression that silently serializes the pool (`parallelism=1`) would pass CI. `test_scales_with_grid` even comments it "proves it scales to 100s-1000s" while only asserting task-*generation* counts.
- **Recommended fix + effort:** Soften the docstring/log to "up to N concurrent workers (default 8) over 100s-1000s of tasks," and add one test that uses a barrier or `threading.active_count()` to assert ≥2 workers run concurrently and the count never exceeds `parallelism`. **Effort: S.**

#### `warm_node_modules` "APFS clonefile" fast path is macOS-only and mislabels Linux copies as clones — LOW

- **What's wrong:** `warm_node_modules` tries `cp -c -R` (BSD/macOS clonefile(2)) first, then `cp -al`. On GNU/Linux, `cp -c` is *not* clonefile and *not* `--no-clobber` — it's an ignored no-op compat flag, so `cp -c -R src dst` to a fresh destination succeeds as a plain deep recursive copy with return code 0. That short-circuits the `cp -al` hardlink and `shutil.copytree` fallbacks, and the success branch narrates `method="clone"` unconditionally. On Linux the result is a full deep copy reported in telemetry as a zero-disk clone. (The original claim's mechanism — "`cp -c` means `--no-clobber`, falls through to hardlinks" — is wrong on both counts.)
- **Evidence:** `scripts/orch/agent_runner.py:791` (`for cmd in (["cp","-c","-R",src,dst], ["cp","-al",src,dst]):`), `:793-797` (returns `True` with `narrate("deps_warm", method="clone")`), docstring `:778-783`. `.github/workflows/ci.yml` runs on `ubuntu-latest`. macOS `man cp`: `-c` = clonefile(2); GNU coreutils CoW clone is `--reflink`.
- **Why it matters:** Functionally harmless — the deep copy produces a usable `node_modules` and still skips `npm ci`. But on Linux it silently forfeits the advertised "instant + zero extra disk" benefit (slow full copy, double disk) and pollutes telemetry by labeling that copy `method="clone"`, misleading anyone diagnosing warm-up perf on the CI host.
- **Recommended fix + effort:** Detect platform / use `cp --reflink=auto` on Linux for real CoW, and report the actual method per branch (`clone`/`hardlink`/`copy`). Correct the docstring to mark clonefile as macOS-only. **Effort: S.**

### 4.9 Web-Research

#### Missing test: cross-provider fallback when a provider exhausts retries and returns `None` — LOW

- **What's wrong:** No test injects the `None` return value (the exhaustion signal from `call_with_retry`) and asserts that `complete()` advances to the next provider candidate. The existing fallback test (`test_falls_through_on_empty`) exercises an empty-string tuple `("", {})`, and the 429 retry test uses a single-candidate role, so neither covers the literal `None` → next-provider path.
- **Evidence:** `scripts/orch/model_router.py:122-130` (the `complete()` candidate loop; success guard at `:127`: `if res and res[0] and res[0].strip()`). `scripts/orch/agent_runner.py:906-927` (`call_with_retry` returns `None` on exhaustion/non-retryable at `:922,927`). `test_model_router.py:81-92` (`test_falls_through_on_empty` returns `""`, not `None`) and `:106-124` (single-candidate role).
- **Why it matters:** A test-coverage gap, not a live bug. `complete()` handles `None` correctly today: `if res and res[0]` short-circuits on `None` exactly as it falls through on `("", {})`. The only untested nuance is the literal `None` value and the resulting `last=None` terminal return — exposed to a future refactor of the `:127` guard.
- **Recommended fix + effort:** Add one test using a multi-candidate role where the first stubbed provider returns `None`; assert the second is invoked. A one-line variant of `test_falls_through_on_empty` swapping `("", {})` for `None`. **Effort: S.**

### 4.10 Honesty / Bench

#### Dart `nonInteractiveEnv` falsely claims parity with Python's `NON_INTERACTIVE_ENV` — LOW

- **What's wrong:** The Dart `nonInteractiveEnv` map carries a doc comment stating it "Mirrors the Python runner's NON_INTERACTIVE_ENV," but it defines only 15 of Python's 21 keys. Six are missing: `TERM=dumb`, `PIP_DISABLE_PIP_VERSION_CHECK=1`, `PIP_PROGRESS_BAR=off`, `npm_config_update_notifier=false`, `ADBLOCK=1`, `HOMEBREW_NO_AUTO_UPDATE=1`. The parity claim is objectively false.
- **Evidence:** `tools/orchestration_server/lib/phase_runner.dart:73-92` (comment at 73-74; 15-key map) vs. `scripts/orch/agent_runner.py:1396-1418` (21-key map). Mismatch introduced in commit `a68700c`.
- **Why it matters:** Dart-spawned children are less hardened than Python-spawned ones. Practical impact is bounded: the Dart map includes `CI=1` and `NO_COLOR=1`, already suppressing most interactive/ANSI behavior. The residual effect is extra stdout noise (pip nags, progress bars, npm/brew chatter) — not a hard hang. Primarily an honesty/parity problem: the comment overstates what the code does.
- **Recommended fix + effort:** Add the six missing keys to make it a true mirror, or downgrade the comment to "subset." Best to add the keys and derive both maps from a single shared source to prevent drift. **Effort: S.**

#### "Honest scorecard" omits that every free/local build run produced 0 working apps — LOW

- **What's wrong:** Not the accusation as originally framed. The doc does **not** pass the paid build off as free — `docs/ADF_VS_LOVABLE.md:12` explicitly attributes the result to `claude-opus-4-8 (cloud)` and `~$0.37 total`, and the line-28 "$0 / local-model crew" checkmark is a distinct (accurate) claim about the zero-token spec crew, not codegen. The real defect is selective reporting by omission: a page branded "the honest scorecard" publishes only the cherry-picked paid run (3/3 built, $0.37) and never surfaces that the measured free/offline build runs failed — NVIDIA built 0/3 and local Ollama built 0/1.
- **Evidence:** `scripts/bench/results/build-nvidia.json` (all 3 apps `built:false`, `in_tokens/out_tokens:0`, `governed:false`); `scripts/bench/results/build-latest.json` (Ollama `built:false`, 600.3s timeout, 0 tokens); `scripts/bench/results/scorecard-input.json:16-18` (`backend: claude-opus-4-8 (cloud)`, `local:false`, the only file rendered into the doc); `docs/ADF_VS_LOVABLE.md:12,28`; `scripts/bench/scorecard.py:111-126` (honest 0/N fallback prose that never renders because the doc was built from the paid input).
- **Why it matters:** For a page that sells "$0-crew" and offline capability as the wedge, silently reporting only the paid path that succeeded — while the actual $0/offline path built nothing — creates a misleading impression of local-model parity. The numbers shown are internally accurate and honestly attributed; the dishonesty is in what is left out.
- **Recommended fix + effort:** Surface the free/local results in the doc — render the bench's existing 0/N fallback (the prose already exists in `scorecard.py:111-126`), or add an explicit row/footnote disclosing NVIDIA 0/3 and Ollama 0/1 with the 600s latency note. **Effort: S.**

## 5. Coverage & Meta-Gaps

The 85-task sweep is dense but lopsided. It exhaustively interrogates four subsystems — **requirements-crew**, **governance-proof (seal mechanics)**, **model-science routing**, and **security/policy** — while the north-star's *primary* moat axis (generate credible multi-file apps) and the entire **app runtime path** (verify → preview → edit-loop) went almost completely unexamined.

### 5.1 Important areas NOT validated / under-covered

- **App-output quality (north-star move #1).** Zero claims test whether the `react-vite-sqlite` / `expo-rn` generators actually produce a working, multi-file app. The only generation claims touch *templates' security* — never *functional correctness*, schema→api→component wiring, or that a generated app boots. This is half the entire bet and it is unaudited.
- **Deterministic phases 1, 3-6 content quality.** The crew only replaces phase 2; phases 1/3-6 stay templated, and phases 1/5/6 are sealed with zero machine validation. Nothing validates whether the templated plan / task-DAG / test-strategy / test-cases the pipeline ships are coherent — the original "hollow CRUD" failure mode could still live here, now hidden behind a crew-grounded phase 2.
- **The verify / boot / preview runtime.** `app_runner.dart`, `preview_service.dart`, `runner_health.dart`, `artifact_validator.dart` — none appear in the validated set. No claim checks that AppRunner spawns on PORT, that the iframe preview reflects real app state, or that `artifact_validator.check()` gates anything beyond the garbage regex.
- **The edit-loop (memory's perf-critical surface).** Compaction wiring into `assemble_edit()` is validated, but the *behavioral* edit loop — one-box edit → re-gen → re-verify warm path the memory pegs at 7s — has no correctness or latency claim.
- **TDD enforcement end-to-end.** Individual `tdd_loop` predicates are well-covered, but no claim verifies the gate *blocks a real build* when `tdd_followed=skipped` flows through to the proof seal.
- **Concurrency/data-integrity beyond two spots.** TOCTOU on FeatureStore and the autopilot single-flight are flagged, but the file-backed store's atomicity is otherwise unprobed across the full wave fan-out.

### 5.2 Meta-gaps (whole subsystems / E2E paths nobody checked)

- **No full create→autopilot→crew→gate→generate→verify→preview HTTP E2E.** The single biggest blind spot. The sweep validated the crew *in isolation* and the proof seal *in isolation* but never the spine connecting them through a running server to a previewable app.
- **The "8-axis ADF vs Lovable" scorecard is asserted, not measured.** The honesty claims confirm the `$0.37 / 3-of-3` numbers omit the free-path failures, but no claim independently *re-measures* performance, deploy, or capability parity. The scorecard's denominator (what Lovable actually does) is untested.
- **Deploy = literally zero.** `grep deploy` over the server lib returns nothing. The north-star and honesty axis both name "ZERO deploy capability" — correctly — meaning an entire promised axis has no implementation *and* no test.
- **Multimodal intake is half-built and that half is untested for function.** `audio_ingest.py` / `repo_analyst.py` don't exist and `server.dart` only parses link sources. But `doc_ingest.py` (PDF/DOCX/CSV→requirements, shipped per memory) has *no* validation claim at all — the one multimodal path that supposedly works is unchecked.
- **Provenance/signing trust chain partially checked.** Ed25519 verifier internals are validated, but key *management* (where the signing key lives, fresh-install behavior, rotation) is untouched — a signed-but-untrusted-key build's behavior is unspecified.

### 5.3 The single most important thing to validate next

**Run one real end-to-end build of a non-trivial app on the free NVIDIA path and confirm the generated app actually boots, serves, and passes its own tests — then verify the sealed proof reflects that reality.**

Highest-leverage because it simultaneously exercises the *only* untested spine (crew → phases 1/3-6 → generate → verify → preview), directly tests north-star move #1 (credible app output), and re-grounds the dishonest scorecard. Every validated claim so far proves a *component* behaves; none proves the *product builds a working app*. Given the confirmed `0/3 built on free path` honesty gap, the most likely catastrophic finding is that the free-path pipeline still produces a non-booting or hollow app — which would invalidate the entire moat regardless of how rigorous the seal mechanics are.

Relevant unaudited files: `tools/orchestration_server/lib/app_runner.dart`, `tools/orchestration_server/lib/artifact_validator.dart`, `tools/orchestration_server/lib/deterministic_artifacts.dart` (phases 1,3-6), `scripts/orch/doc_ingest.py`, and the `react-vite-sqlite` / `expo-rn` templates under `templates/`.

## 6. Prioritized Remediation Roadmap

Fix-first order, grouped by effort. Within each group, ordered by severity/leverage.

### Fix first — small effort, high leverage (S)

1. **Policy gate fail-closed** (Security, MEDIUM) — mirror the process gate: on gate exception under enforced policy, set `policy_blocked = ["policy_gate_error"]`. Add an exit-6 E2E test. *(`agent_runner.py:2748-2798`)*
2. **Merkle root key fix** (Gov, MEDIUM) — read `proof['merkle_root']` (legacy `root` fallback) in `audit_bundle.dart`; fix fixture; add moat-root assertion; add presence/match check to `verify_audit_bundle.py`.
3. **Seal mobile APK facts** (Gov, MEDIUM) — add a `mobile` branch to `_verdict_bytes()`; record in metadata; correct the false comment at `agent_runner.py:2851`; add a mutate-sha test.
4. **Open-questions payload-path fix** (Req, MEDIUM) — read `detail['summary']['requirements_open_questions']` (or lift to top level); add a real-shape screen test.
5. **NVIDIA timeout** (Req, MEDIUM) — `_complete()` passes `timeout` from `ADF_NVIDIA_TIMEOUT_SEC` (default 240).
6. **Verdict content validation** (Gov, LOW–MED) — parse verdict for a PASS/REVISE token; `main()` exits non-zero on REVISE; add the negative test.
7. **`generate()` `model=` seam** (Arch, MEDIUM) — add optional `model=None`, thread through `call_with_retry`.
8. **Stale model labels sweep** (Model-Science, LOW) — fix five label sites, make the `:239` string dynamic, fix the test docstring.
9. **Test/hygiene cluster** (LOW): `_tdd_red_baseline` deps-absent test; `backend`/`model` exclusion tests; red-without-green persisted-status assert; `sources` on-disk assert; `None`-fallthrough router test; swarm-concurrency barrier test; nonce-rejection regression test.
10. **Dart env parity** (Honesty, LOW) — add the six missing keys (or shared source); soften comment.
11. **Scorecard honesty** (Bench, LOW) — render the existing 0/N fallback / disclose NVIDIA 0/3, Ollama 0/1.
12. **`gather()` >8-URL warning** (Req, LOW) — log truncation; document the cap; add the >8 test.
13. **Surface sealed policy verdict** (Gov, LOW) — show `sealed_policy_ok` vs `live_policy_ok`.
14. **Plan-doc reconciliation** (LOW) — drop the "cheap re-run" claim and remove the unwritten test; document the per-URL extract as the accepted `research-synth` substitute.

### Medium effort (M)

15. **Verdict-path contract unification** (Arch, **HIGH — top structural priority**) — make Python honor Dart's resolution order; centralize path logic; add a non-`.cursor` runner test.
16. **Single-flight crew lock** (Gov, MEDIUM) — per-`featureId` in-flight guard in `runCrewForFeature` (S–M).
17. **Silent deterministic-fallback signal** (Gov, MEDIUM) — `crew-log.jsonl` + `spec_source` state flag + UI surfacing or block-on-fallback (S–M).
18. **Per-agent model attribution** (TDD, MEDIUM) — `complete()` returns served `(prov, model)`; collect per-role map; routing-aware test.
19. **`warm_node_modules` Linux CoW** (Perf, LOW) — `cp --reflink=auto` on Linux; report the real method per branch.
20. **robots.txt awareness** (Security, LOW) — `RobotFileParser` in the urllib fallback.
21. **Multimodal intake (Dart side)** (Req, LOW) — multipart parsing + extra intake fields; pairs with #22.
22. **Audio + repo ingest modules** (Req, MEDIUM) — build `audio_ingest.py` and `repo_analyst.py` + `_load_sources` branches (or descope docs at S).
23. **web_scraper chunk→rank→cite** (Req, LOW) — real retrieval stage, or route through `compaction.clip` + descope plan (S).
24. **research-synth Qwen slice pass** (Plan, LOW) — implement the per-slice synth layer, or formally retire it (S).

### Large effort (L)

25. **Re-run incrementality** (Plan, LOW) — persist per-wave outputs keyed by content hash; skip unchanged waves. (Or drop the claim at S — see #14.)
26. **The validation gap, not a code fix:** the highest-value *next action* is not in this list but in §5.3 — a real free-path E2E build that proves the generated app boots and the seal reflects it.
