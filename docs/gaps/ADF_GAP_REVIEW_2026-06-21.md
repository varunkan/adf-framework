# ADF Gap Fix Re-Review — 2026-06-21

Adversarial re-review of 30 committed gap fixes (commit `a58d56e`). Each fix was checked for whether it actually closes the gap, whether its tests have teeth (proven via mutation), regression/new-surface risk, and the severity if left unfixed.

## Verdict Table

| Gap | Verdict | fix_closes_gap | test_has_teeth | regression_risk | severity_if_unfixed |
| --- | ------- | -------------- | -------------- | --------------- | ------------------- |
| G01 | solid | yes | yes | no | none |
| G02 | solid | yes | yes | no | none |
| G03 | incomplete | no | yes | no | low |
| G04 | solid | yes | yes | no | none |
| G05 | incomplete | yes | no | no | low |
| G06 | solid | yes | yes | no | none |
| G07 | incomplete | no | yes | no | medium |
| G08 | incomplete | yes | yes | no | low |
| G09 | incomplete | yes | yes | no | low |
| G10 | solid | yes | yes | no | none |
| G11 | solid | yes | yes | no | none |
| G12 | solid | yes | yes | no | none |
| G13 | solid | yes | yes | no | none |
| G14 | solid | yes | yes | no | low |
| G15 | incomplete | yes | yes | no | low |
| G16 | solid | yes | yes | no | low |
| G17 | solid | yes | yes | no | low |
| G18 | incomplete | no | no | no | low |
| G19 | solid | yes | yes | no | low |
| G20 | solid | yes | yes | no | low |
| G21 | solid | yes | yes | no | low |
| G22 | incomplete | no | yes | no | low |
| G23 | solid | yes | yes | no | low |
| G24 | solid | yes | yes | no | low |
| G25 | solid | yes | yes | no | none |
| G26 | solid | yes | yes | no | low |
| G27 | solid | yes | yes | no | low |
| G28 | solid | yes | yes | no | low |
| G29 | solid | yes | yes | no | low |
| G30 | solid | yes | yes | no | low |

## Heal List

The following 7 gaps are not solid and require remediation.

### G03 — Merkle root binding not enforced in verifier (severity: low; fix_closes_gap: NO)

**Issues:**
- **Verifier-side fix never landed (AC4 / R3).** The spec required `scripts/orch/verify_audit_bundle.py`'s `moat_attested` branch to read `proof.get('root')` and, when present, require `len==64` lowercase-hex AND `seal == 'adf1:' + root[:12]`. Commit `a58d56e` did not touch `verify_audit_bundle.py` at all — only `audit_bundle.dart` and `audit_bundle_test.dart`. Code at `verify_audit_bundle.py:300-318` still only checks `seal.startswith('adf1:')` and never reads `root`/`merkle_root`.
- **Missing RED-2 / AC5(b) teeth-test.** No test mutates `moat.proof.root` to a different 64-hex value with the seal left valid and the bundle_digest fixed up, asserting `moat_attested` fails. The only verifier tamper test (`audit_bundle_test.dart:331-351`) mutates the *seal* string, which the pre-existing `startswith('adf1:')` check already caught — it exercises nothing new and would pass with zero verifier changes.
- **Residual root cause open.** Because the verifier never reads `root`, an attacker who edits `moat.proof.root` and recomputes the bundle_digest passes `verify_audit_bundle.py`. Only the 48-bit seal prefix is bound. The display/honesty goal (root no longer null) is met; the verification-binding goal is not.

**Change needed:** Implement the root presence/format/seal-consistency check in `verify_audit_bundle.py:300-318` exactly as specified at `G03.md:72-86`, and add the AC5(b) Dart test (set `moat.proof.root` to a different 64-hex, keep a valid seal, fix up `digestOf()`, assert `exitCode==1` and `failing==['moat_attested']`).

### G05 — Crew concurrency guard tests don't exercise production seam (severity: low; test_has_teeth: NO)

**Issues:**
- **AC-1/AC-2 test re-implements the wiring.** `agent_crew_concurrency_test.dart:101-110` defines a local `guardedRun()` closure that calls `CrewGate.tryAcquire/release` instead of the production `runCrewForFeature` (`server.dart:301`). Deleting `crewGate.tryAcquire(id)` from the real `runCrewForFeature` (`server.dart:304`) would still pass all 5 tests — they prove the primitive works, not that the seam uses it.
- **AC-6 untested.** No `server_autopilot_guard_test.dart` exists; grep over `test/` for `/autopilot`, `409`, `crew already in flight` finds nothing. The 409 wiring (`server.dart:1405-1410`) is completely unverified.
- **AC-7 untested.** `kickAutopilotBackground`'s no-op on a skipped result (`server.dart:583-584`) has no test asserting `autoEnqueueImplement` is not called on a skipped run.
- **AC-2 claimed but unasserted.** The test comment claims state.json coherence coverage, but the test only parses the integrity ledger and never reads `state.json`/`completed_builders`.

**Change needed:** Add an integration test that drives the actual server seam (launch the server, fire two concurrent `POST /features/<id>/autopilot`, assert the second returns HTTP 409 with body `{'error':'crew already in flight','feature_id':id}`), a guard test that the skipped path does not enqueue implement, and either assert on `state.json` or drop the AC-2 claim from the comment.

### G07 — Open-questions panel fix never committed (severity: medium; fix_closes_gap: NO)

**Issues:**
- **Fix absent from HEAD — false attestation.** The commit message attests "G07 open-questions panel reads the real nested payload shape," but `a58d56e --stat` lists zero files under `tools/orchestration_dashboard/`. The fix and its tests exist only as uncommitted working-tree changes (`git status` shows `M` on both files).
- **Committed panel still buggy.** At `a58d56e`, `requirements_questions_panel.dart:14` still reads top-level-only `detail?['requirements_open_questions']` — identical to the buggy `e590e2a` state. A clean checkout (CI, fresh clone, another machine) ships the dead-E2E panel and the gap remains live.
- **Registry has wrong paths.** `docs/gaps/ADF_GAP_REGISTRY.json` lists nonexistent `tools/orchestration_server/lib/widgets/...` paths for G07.

**Change needed:** Commit the working-tree modifications to `requirements_questions_panel.dart` and `requirements_questions_panel_test.dart` (content is correct and ready) so the fix is sealed under the commit that claims it. Update the registry `files` entries to `tools/orchestration_dashboard/...`.

### G08 — NVIDIA timeout end-to-end chain untested (severity: low; fix_closes_gap: yes)

**Issues:**
- **AC4 missing.** No test drives the full chain `clarify_swarm._complete → model_router.complete(env=None) → fake capture` with `ADF_NVIDIA_TIMEOUT_SEC=240` in `os.environ`. The behavior is correct (manually verified: `complete` with `env=None` reads `os.environ` and forwards 240), but the spec's AC4 (mandatory) is unfulfilled; the TDD set wrongly marked it "Optional." This is the only unresolved AC.

**Change needed:** Add one test to `test_clarify_swarm.py` that sets `os.environ['ADF_NVIDIA_TIMEOUT_SEC']='240'`, calls `clarify_swarm._complete` directly with a fake injected into `model_router.complete`, and asserts the captured timeout equals 240.

### G09 — Path guard rejects `..` but not absolute-outside-subtree (severity: low; fix_closes_gap: yes)

**Issues:**
- **R8 subtree-confinement under-delivered.** `audio_ingest.py:38-44` and `repo_analyst.py:41-46` `_path_rejected` only rejects literal `..` components. R8 (corrected) requires rejecting both `..` AND an absolute path resolving outside the allowed subtree. Demonstrated empirically: `repo_analyst.ingest('/etc')` walks `/etc` and folds the listing (passwd, ssh config, etc.) into `raw`/`requirements`, then sends it to the LLM. `audio_ingest.ingest('/etc/passwd')` also passes the guard. Note: this is under-delivery, not a regression — the sibling `doc_ingest.ingest` has no traversal guard at all, and the acceptance gate AC8 only requires the `..` case (which passes).
- **Minor:** dispatch test leaks an unclosed file handle (pre-existing `_load_sources` pattern, cosmetic).

**Change needed:** Confine to an allowed root — thread `repo_root` from `_load_sources` into the engines and reject when `os.path.realpath(path)` is not under `os.path.realpath(allowed_root)` (via `os.path.commonpath`). Add an AC/test for an absolute-path-outside-subtree (e.g. `/etc`) rejection.

### G15 — Python-side sealed_policy tests never written (severity: low; fix_closes_gap: yes)

**Issues:**
- **AC9/RED-1/RED-2 absent.** The spec mandated two Python tests in `SealAndVerify`: `test_verify_proof_includes_sealed_policy` and `test_verify_proof_sealed_policy_null_when_no_policy_in_proof`. Neither exists. Reverting `proof_of_build.py:477` would leave all 28 Python tests green — the Python suite has zero direct coverage of the `sealed_policy` contract. (The implementation is correct, and the Dart side RED-3/RED-4 do carry teeth, so the gap is functionally closed; only the mandated Python coverage is missing.)

**Change needed:** Add the two `SealAndVerify` tests per `G15.md:181-211` — assert `sealed_policy['ok'] is True` and `sealed_policy == policy_block` for a policy-bearing proof, and `sealed_policy is None` when no policy key is present.

### G18 — Multimodal upload endpoint unverified end-to-end (severity: low; fix_closes_gap: NO)

**Issues:**
- **False E2E comment.** `multimodal_intake_test.dart:6-7` claims the upload routes are exercised by `scripts/orch/e2e_server.sh`, but that script has zero references to `/upload`, `figma_url`, `reference_sites`, or multipart.
- **RED-2 / RED-3 missing.** The mandated HTTP-layer tests (POST multipart to `/features/<id>/upload` → 200, file saved, sources.json updated; POST `application/json` → 400) do not exist. The 8 present tests cover only the pure helpers `normalizeIntakeSources` and `sanitizeUploadFilename`.
- **AC-3..AC-6 unverified.** File-saved/200, non-multipart 400, zero-file-parts 400, unknown-id 404 — none covered. Path-traversal rejection is tested only at the pure-helper level, not at the HTTP route.
- **RFC 5987 filenames silently rejected.** `server.dart:1456-1457` matches only the RFC 2183 quoted `filename="..."` form; `filename*=UTF-8''...` extended-value parts are drained as non-file fields, yielding a spurious 400. Untested and deviates from AC-3.

**Change needed:** Add the HTTP-layer integration tests (RED-2/RED-3 and AC-3..AC-6) inside `multimodal_intake_test.dart` driving the real upload route; either wire `/upload` into the E2E script or correct the false comment; and handle (or explicitly document as out-of-scope) RFC 5987 `filename*=` parsing in `server.dart:1456-1457`.

### G22 — Honesty-gap plan-file edits not made (severity: low; fix_closes_gap: NO)

**Issues:**
- **AC-1/AC-2/AC-3 unsatisfied.** The three misleading "incremental cheapness" claims in `~/.claude/plans/i-would-like-to-cheerful-iverson.md` remain: line 80 ("Re-runs touch only affected agents + the head (cheap)."), line 86 ("re-run affected subagents + head"), line 119 ("re-run touches only affected agents" as a test item). The repo-tracked deliverables (AC-4..AC-7) are solid — the docstring and the `FullDag` teeth-test (8 `complete()` calls on both runs) are correct — but the primary honesty edits to the plan file were not made. The spec's Risk-1 mitigation does not waive AC-1/AC-2/AC-3.

**Change needed:** Edit the plan file: remove the line-80 sentence, replace line-86 wording with cost-neutral phrasing (e.g. "re-run the crew + head"), and remove the line-119 test item.

## Bottom Line

**23 of 30 solid; 7 need healing.**

Most fixes are genuinely solid with mutation-proven teeth and no regression surface. The 7 that need work fall into three buckets:

1. **One fix was never committed (G07)** — the highest-severity item (medium). The commit message attests a fix that lives only in the working tree, so a clean checkout still ships the bug. This is a false attestation and should be fixed first.
2. **Two fixes are materially incomplete (G03, G18)** — they do not close their gaps. G03 left the entire verifier-side binding unimplemented (the security-relevant half), and G18 left the upload endpoint's HTTP contract completely unverified.
3. **Four are functionally correct but under-tested or under-delivered against spec (G05, G08, G09, G15, G22)** — G05 has tests that exercise a primitive instead of the production seam; G08 and G15 are missing mandated tests for behavior that is otherwise correct; G09 under-delivers R8's subtree confinement (a real, demonstrated path-disclosure surface, though not a regression); G22 left the plan-file honesty edits undone.

No fix introduced a regression or new attack surface. Recommend prioritizing G07 (commit it), then G03 and G09 (the two with real security implications), then the remaining test/doc completeness items.
