# ADF vs oh-my-pi — comparison & adoption roadmap

> **Provenance.** Compared ADF (this repo) against [can1357/oh-my-pi](https://github.com/can1357/oh-my-pi)
> @ `8eeb707` (cloned 2026-06-17). Method: a 21-agent comparison workflow — 10 dimensions,
> each independently compared then **adversarially verified** against oh-my-pi's actual source
> (the verifier corrected several first-pass errors, noted inline). Evidence paths under
> `packages/…` / `crates/…` refer to the oh-my-pi tree; `scripts/…` / `tools/…` refer to this repo.
> oh-my-pi is a *terminal coding agent* (TS+Rust); ADF is a *governed prompt-to-app builder*
> (Python engines + Dart orchestrator + Flutter UI) — different categories, so the value is the
> **adoptable algorithms**, not a single overall winner.

# oh-my-pi vs ADF: Per-Dimension Comparison & Adoption Report

## 1. TL;DR

**ADF** (`/Users/varunkumar/ai_pos_system/adf-framework`) is a *governed prompt-to-app builder* — it generates whole React/Vite/SQLite or stdlib-Python apps test-first, then seals a Merkle "Proof of Build" + policy gate + offline/$0 verification (Python engines + Dart orchestrator + Flutter UI). **oh-my-pi** (`/tmp/ohmypie`) is a *terminal coding agent harness* — a Claude-Code/Aider peer that edits existing repos through a hardened tool loop, with LSP/DAP code intel, swarm subagents, and 40+ providers (TS + Rust monorepo). They are different categories: ADF proves the *artifact*, oh-my-pi drives the *session*.

The single most important thing ADF should take is **oh-my-pi's hashline edit-apply algorithm** (`/tmp/ohmypie/packages/hashline/`): a hash-anchored line-patch format that makes edit cost proportional to *change size* instead of *file size*. ADF's one-box `editApp` loop currently re-emits every changed file in full on every edit and self-heal iteration — a large, avoidable token/latency tax plus an undetected-overwrite risk. The cheaper near-term wins are a **non-interactive env-hardening table**, a **content-hash staleness gate**, a **structured-section compaction summary**, and **closing ADF's already-collected-but-never-read `knownBlockers` learning loop**.

## 2. Scorecard

| Dimension | oh-my-pi | ADF | Winner | One-line why |
|---|---|---|---|---|
| Edit / diff application | Hash-anchored line patches (hashline), cost ∝ change | Whole-file re-emit, cost ∝ file size | **oh-my-pi** | hashline gates on a content hash + edits only changed lines; benchmark `avg_tok_out` 268–2285 vs O(file) |
| Tool harness & execution | Streaming bounded output + minimizer + env hardening + cancel | Ad-hoc fully-buffered `subprocess.run` + blind tail-slice | **oh-my-pi** | one hardened executor vs duplicated plumbing with a real Dart drain-deadlock hazard |
| Code intel & build verification | LSP writethrough (per-file diagnostics) + DAP | Cold full `tsc+vite+vitest` + **headless render gate** + Merkle seal | **n/a-different** | oh-my-pi owns the fast inner loop; ADF owns the authoritative, provable verdict |
| Agent / subagent orchestration | Resumable parked-session revive, async fan-out, declarative DAG | Governed 9-phase gate DAG + Merkle seal + approval gate | **n/a-different** | oh-my-pi wins resume/async/data-driven; ADF wins enforcement/audit/$0 |
| Context management & compaction | 5 strategies (structured summary, bitmap, handoff, prune) | Deterministic $0 file-relevance fold + auditable context card | **n/a-different** | oh-my-pi deeper on conversation; ADF stronger on auditability/$0-determinism |
| Model providers, routing & cost | ~60 providers, auth rotation, rate-limit classification | 3 backends, complexity ladder, prompt-cache accounting | **n/a-different** | oh-my-pi owns breadth+resilience; ADF appropriately scoped + cost-deliberate, but has a real 529-downgrade gap |
| Memory & learning | Closed cross-session loops (autolearn, MEMORY.md, hindsight) | Collects `learnings.jsonl` but **never reads it back** (`knownBlockers` is dead code) | **oh-my-pi** | ADF has the signal but no recall loop wired |
| Architecture & extensibility | Capability/provider registry, plugins, MCP client, SDK | StackProfile contract + Python single-source-of-truth | **n/a-different** | oh-my-pi wins ecosystem breadth; ADF wins clarity + offline determinism |
| Governance, determinism & verifiability | Host/credential safety (approval tiers, secret obfuscation) | Merkle Proof-of-Build + policy gate + integrity ledger + audit bundle | **ADF** | ADF ships keyless offline artifact tamper-evidence; oh-my-pi has nothing comparable |
| Prompt-to-app generation & determinism | Plan/goal/advisor steering of a free-form edit agent | `feature_shapes` skeleton contract + scaffold-then-diff + sealed verify | **n/a-different** | ADF wins structural determinism; oh-my-pi wins outcome/completion discipline |

## 3. Where ADF Is Stronger

- **Artifact verifiability is the product, not a session feature.** Offline, keyless tamper-evidence over the *generated app*: domain-separated leaves + order-independent SHA-256 Merkle root binding files + spec + policy verdict, recomputable forever with stdlib Python (`scripts/orch/proof_of_build.py`, `verify_proof.py`). oh-my-pi has *nothing* comparable — its only hashing is AES-GCM collab frames, a 16-bit xxHash32 patch anchor, and a git conversation checkpoint.
- **Governance is a sealed verdict, not advice.** The 5-rule `policy_gate.py` outcome is folded into the Merkle root; flipping a result or editing a file flips the seal to TAMPERED and names the file. A second pipeline `IntegrityChain` (`tools/orchestration_server/lib/integrity_chain.dart`) catches six breach classes incl. injection and gate-forgery, with an adversarial strict re-hash mode.
- **Authoritative whole-project + render verification.** A green means `tsc --noEmit && vite build` *and* vitest *and* server boot *and* a headless-Chrome `#root`-mount render all passed (`scripts/orch/visual_verify.py` `assess_dom`) — catching white-screen/runtime-crash defects that LSP/tsc/vitest/HTTP-200 all miss. oh-my-pi's per-file LSP pass is not a whole-project guarantee.
- **Structural determinism oh-my-pi doesn't attempt.** `scripts/orch/feature_shapes.py` is a pure/total/testable classifier that pins exact schema, route verbs+status codes, hook signature, and test cases per shape; scaffold-then-diff (`scaffold_app`) means the model only diffs the feature surface, never rederiving build wiring.
- **Zero-cost, offline by default.** The shape classifier, complexity router, and compaction engine add no model calls; `cost_meter.dart` has an explicit `sourceZero` $0 mode and `offline_build.py` gives a live network-blocked air-gap proof.
- **Single-source-of-truth discipline.** Integrity-critical verify/proof/export/compaction logic lives once in Python; the Dart shells are thin wrappers (`compaction.dart→compaction.py`, `proof_check.dart→verify_proof.py`), so UI and engine physically cannot drift.

## 4. Where oh-my-pi Is Stronger

- **Edit-apply efficiency & safety** (`packages/hashline/`): edit cost ∝ change size, a content-hash staleness gate (`MismatchError`), a `seenLines` provenance guard, and snapshot-replay drift recovery — backed by a reproducible cross-model benchmark.
- **Tool harness mechanics** (`packages/coding-agent/src/exec/`, `crates/pi-shell/`): one hardened executor with streaming bounded output + lossless artifact spill, a deterministic exit-code-gated command-output minimizer, a ~40-key non-interactive env table, and cooperative `CancelToken` process-group teardown.
- **Incremental code intel** (`packages/coding-agent/src/lsp/`): per-file diagnostics in the *same tool result* as the edit, with genuinely correct version-aware staleness handling, deferred late-diagnostics re-injection, and a dedup ledger; plus DAP runtime debugging.
- **Cross-session learning** (`packages/coding-agent/src/{autolearn,memories,hindsight}/`): multiple *working* closed loops that distill lessons and re-inject them into future sessions — exactly the loop ADF collects signal for but never closes.
- **Provider resilience** (`packages/ai/src/`): rate-limit error classification + per-reason backoff, retry-same-model-before-failover, multi-credential auth rotation, replay-safe streaming retry.
- **Open extensibility** (`packages/coding-agent/src/capability/`): one capability/provider registry under tools/skills/MCP/hooks/rules, filesystem-discovered plugins, a full MCP *client*, and an embeddable SDK.

## 5. Algorithms ADF Should Adopt

Only verifier-confirmed (`claim_holds=true`, `recommend ∈ {adopt-now, adopt-later}`) items, sorted by impact then effort.

---

### 5.1 Hash-anchored line-patch applier for the one-box `editApp` loop — **HEADLINE** *(impact: high, effort: large, adopt-later)*

**What it is.** Replace whole-file re-emission in EDIT mode with a hashline-style patch. A line-numbered read mints a short content-hash *tag* over the whole normalized file; the model echoes that tag in a section header `[path#TAG]` and emits hunks that name *original* line numbers (`SWAP A.=B:` replace, `DEL A`, `INS.PRE/POST/HEAD/TAIL`); a pure applier verifies the live file still hashes to the tag before applying, then applies hunks bottom-up so ranges always index the original and never shift.

**The upgrade for ADF, in detail.** Today ADF re-emits whole files everywhere via the `<<<FILE: path>>>...<<<END>>>` protocol. `build_edit_messages` (`scripts/orch/agent_runner.py:1005`) instructs the model to "re-emit the COMPLETE content of every file you change," and `current_app_files` (`:982`) loads *all* editable source (up to 60 files / 200KB) into the prompt. A one-word tweak to a 400-line component costs ~400 lines of *output* tokens (plus latency and $) every iteration — `O(file size)`. Worse, whole-file retyping invites silent collateral damage (the model "helpfully" reformats or drops a comment in an untouched function) and there is **no staleness detection at all**: if the on-disk file changed between read and emit, `write_files` (`:660`) blindly overwrites it.

A hashline patch flips the cost to `O(change)` and eliminates both risks: the model can only touch lines it names, and the hash gate rejects edits authored against a stale view.

**Benchmark numbers** (`/tmp/ohmypie/packages/typescript-edit-benchmark/all_models_results.json`, verified): on real TS source doing surgical single-token edits, `avg_tok_out` ranges **268–2285** (median ~1331 — the comparison's "~900" was a confirmed error) and `tool_input_chars` **3583–9883**, with `edit_success_pct` **74.1–100%** (model-dependent). The headline — cost proportional to change, not file — is firmly supported by the `tool_input_chars` band and the bottom-up original-line applier verified at `apply.ts:939-984`.

**Evidence in oh-my-pi.** `format.ts:110` (`computeFileHash` — note: `Bun.hash.xxHash32`, a Bun builtin, *not* a portable lib; a Python port must supply its own hash); `patcher.ts:387` (`liveMatches` hash gate), `:353` (`#assertSeenLines`), `:192-216` (all-or-nothing preflight + mid-batch landed reporting); `apply.ts:939-941` (bottom-up application), `:595` (`repairReplacementBoundaries` off-by-one repair); `prompt.md` + `grammar.lark` (formal spec).

**Adoption plan (Python).** Fully language-agnostic; nothing depends on TS/Rust.
1. Add `normalize(text)` (strip trailing ws/CR per line), `file_tag(text) = hashlib.blake2s(normalize(text)).hexdigest()[:4]` (substituting blake2s for the Bun-specific xxHash32 changes tag *values*, not the design), and `format_numbered(text)`.
2. In `build_edit_messages`, present each file as `[path#TAG]` + `N:line` rows and teach the SWAP/DEL/INS grammar (port `prompt.md`).
3. Write a ~150-LOC pure `apply_hunks(text, hunks)` mirroring `apply.ts`'s bottom-up original-line model.
4. Before applying, recompute the tag from the on-disk file and reject on mismatch (port the `MismatchError` message).
5. Keep whole-file emission as the BUILD-mode/new-file path — exactly as hashline does (it only *edits* existing files). **Drop block ops** (`block.ts` `SWAP.BLK`) — they require a per-language tree-sitter resolver ADF has no analog for (`block.ts:107-112` throws `BLOCK_RESOLVER_UNAVAILABLE` without one).

The test + smoke-boot + self-heal loop stays as the correctness backstop on top. *(~4600 LOC in the original package — this is why it is adopt-later and edit-mode-only; it is philosophically at odds with ADF's deliberate single uniform whole-file generate/edit path, chosen for weak-local-model robustness + direct Merkle-seal auditability.)*

---

### 5.2 Centralized non-interactive env-hardening table *(impact: high, effort: small, adopt-now)*

**What it is.** A single ~40-key constant (`PAGER/GIT_PAGER/MANPAGER=cat`, `CI=1`, `GIT_TERMINAL_PROMPT=0`, `GIT_EDITOR=true`, `npm_config_yes/fund/audit/progress`, `PYTHONUNBUFFERED=1`, `NO_COLOR=1`, `DEBIAN_FRONTEND=noninteractive`, `PIP_NO_INPUT`, …) merged into every child env, on top of secret scrubbing.

**Why it beats ADF's current approach.** ADF's `scrubbed_env` (`agent_runner.py:755-762`) only *removes* secrets; it sets none of these, so an npm/git/pip step can hang on a pager or interactive prompt and only die at the timeout.

**Evidence.** `non-interactive-env.ts` (`NON_INTERACTIVE_ENV` + `buildNonInteractiveEnv`), wired at `bash-executor.ts:187`.

**Adoption plan.** Add a `NON_INTERACTIVE_ENV` dict in `agent_runner.py`; have `scrubbed_env(**extra)` merge scrubbed-base → table → extra. Mirror the same dict into `phase_runner.dart` `childEnvFor`. Pure data, zero native deps — highest impact-per-effort item in the whole report.

---

### 5.3 Status-aware in-backend retry + rate-limit classification *(impact: high, effort: small+medium, adopt-now — as a pair)*

**What it is.** (a) A pure function classifying a provider error into `QUOTA_EXHAUSTED / RATE_LIMIT_EXCEEDED / MODEL_CAPACITY_EXHAUSTED / SERVER_ERROR / UNKNOWN` with a per-reason backoff (capacity errors get jitter — verified as **45–75s one-sided**, `BASE 45s + random*30s`, not the symmetric "±15s" the source comment claims). (b) A bounded retry loop that retries the *same* model on a retryable status (429/503/529) before failing over to a different backend.

**Why it beats ADF's current approach.** ADF's `generate()` (`agent_runner.py:615-638`) catches `OSError/ValueError/KeyError` generically and falls through to the *next, weaker* backend; both Dart brains do `if (statusCode != 200) return null` (`claude_api_brain.dart:176`, `openai_compat_brain.dart:127`). So a transient 529-overloaded *silently demotes a Claude build to free NVIDIA mid-run* instead of waiting ~1s and retrying the same model. ADF cannot distinguish "wait 30min (quota)" from "retry in 30s (rate limit)" from "overloaded, retry now with jitter."

**Evidence.** `rate-limit-utils.ts:30-101` (`parseRateLimitReason`, `calculateRateLimitBackoffMs`, `isUsageLimitError`). *Note:* the comparison cited `auth-retry.ts:103-142` (`withAuth`) for the retry loop, but that is an **auth-rotation** loop (401/usage-limit → refresh-same → rotate-sibling), *not* a 529 retry loop — oh-my-pi handles transient-status retry separately (rate-limit-utils backoff + AgentSession message-level retry, per `docs/provider-streaming-internals.md`). The *pattern* ADF wants is sound; the cited code does a different (auth) job.

**Adoption plan.** Port the ~70-line classifier to Python (`agent_runner.py`) and mirror in a small Dart `rate_limit.dart`. Surface the HTTP status from `http_post_json`, wrap each `call_*` in `retry(attempts=3)` keyed on the classified reason (inner loop), keeping the existing backend-fallback list as the *outer* loop (only after retries exhaust). Give the Dart brains a `statusCode`-keyed retry around `_post` instead of blanket `return null`. Pure control-flow, no new deps.

---

### 5.4 Wire the learned-blocker recall loop into the build prompt *(impact: high, effort: small, adopt-now)*

**What it is.** Before generating/healing phase N, look up the top-K most-frequent prior failure blockers for that phase (and their recorded fixes) and splice a compact "Past failures here + the fix that healed them — avoid repeating" block into the prompt, wrapped as background guidance.

**Why it beats ADF's current approach.** ADF *already* records every outcome with `(phase, blockers, fix)` and *already* ranks them via `knownBlockers(phase)` (`learning_store.dart:50`) — but **nothing consumes it**: `knownBlockers` is referenced only by its own unit test; only `stats()` is read (for dashboards, `server.dart:999/1005`). No blocker text ever reaches a build or heal prompt (verified: grep empty). The store's own docstring promising "future runs consult it to pre-empt repeat failures" is aspirational. This is the lowest-risk, highest-leverage learning win because the signal is already being collected.

**Evidence.** oh-my-pi's `<memories>` recall+inject pattern: `hindsight/state.ts:262-283` (`recallForContext`), `mnemopi/backend.ts:102-110` (`buildDeveloperInstructions` splices `lastRecallSnippet`), `mental-models.ts:246-250` (anti-feedback "background knowledge, not instructions" preamble).

**Adoption plan.** In `agent_runner.py`, before building/healing a phase, read the top 3–5 `knownBlockers(phase)` (port the ~15-line JSONL scan to Python, or expose it via the existing orchestration descriptor endpoint that already calls `stats()`), format blockers + recorded fixes as a bounded text block wrapped in an anti-feedback preamble, and add it to the message. No model call for the recall itself — it's a deterministic frequency rank ADF already computes. $0-compatible.

---

### 5.5 Structured-section compaction summary + iterative update prompt *(impact: high, effort: small, adopt-now)*

**What it is.** Replace ADF's shallow first-line digest with a fixed-section summary (`Goal / Constraints / Progress[Done|In Progress|Blocked] / Key Decisions / Next Steps / Critical Context`), plus a *separate* update path that folds the prior summary forward losslessly (preserve all prior info, only move items In Progress→Done) instead of re-digesting from scratch.

**Why it beats ADF's current approach.** ADF's offline `_digest_messages` (`compaction.py:118-132`) truncates each turn to ~70 chars / 600 total and re-digests from scratch every fold, so task state (done/next/decisions) is lost and never compounds. Directly upgrades the `.adf-context` audit artifact too.

**Evidence.** `compaction-summary.md` (the exact template) + `compaction-update-summary.md` ("MUST preserve all information from the previous summary," "move items from In Progress to Done").

**Adoption plan.** Pure prompt + control-flow. Add two template string constants in `compaction.py`; when an optional summarizer is supplied, pass the structured template (and on re-fold, pass the previous `[compacted ...]` summary under `<previous-summary>` with the update template). Keep the offline path as fallback but emit the section skeleton even offline (derive Next Steps from the last user turn). Fully Python-portable, $0-compatible.

---

### 5.6 Bounded head+tail `OutputSink` with lossless artifact spill *(impact: high, effort: medium, adopt-now)*

**What it is.** Replace `capture_output=True` + `out[-3000:]` with a streaming sink that keeps a head window + rolling tail, applies a per-line column cap, spills the complete raw stream to a file, and returns structured truncation metadata + the log path.

**Why it beats ADF's current approach.** `_react_verify` (`agent_runner.py:857-863`) buffers the whole build log then keeps only the last 3000 bytes — **discarding the head where the first real error usually is**, with no recoverable full log. *(Note: the comparison claimed `_node_smoke_boot` already uses an incremental readline loop — it does not; it polls and does a single `proc.stdout.read()` on early exit at `:805-808`, so the incremental loop must be built fresh.)*

**Evidence.** `streaming-output.ts` (`OutputSink`: `#head` window + rolling tail `#buffer` + middle-elision marker + lossless artifact spill; structured `OutputSummary`).

**Adoption plan.** A ~60-line Python sink: `Popen` + readline loop, head deque (first N KB) + tail deque (last M KB), full stream to a temp `.adf-log` under the feature dir, return `head + "…[elided X bytes]…" + tail` plus the log path. Surface the path through the existing self-heal failure text instead of `out[-3000:]`. Zero native deps; largely subsumes the token-waste problem the minimizer targets.

---

### 5.7 `seenLines` provenance guard — reject edits to regions the model never saw *(impact: medium, effort: small, adopt-now)*

**What it is.** Track which lines a read/outline actually *displayed*, and refuse an edit that targets a file region only outlined/elided rather than shown in full.

**Why it beats ADF's current approach.** `compact_files` (`compaction.py:198`) replaces over-budget files with a one-line OUTLINE, then asks the model to edit. If the model emits a `<<<FILE: p>>>` for an outlined-only path, it is editing blind — it has the path and symbol names but not the body, and can hallucinate it. ADF has no guard.

**Evidence.** `snapshots.ts:47` (`seenLines`), `patcher.ts:353` (`#assertSeenLines`).

**Adoption plan.** Reuses data ADF already computes: `compaction.py:230` already records `summarized_paths`. In the edit apply path, if the model emits a file for a path that was only in `summarized_paths`, reject it and re-run `assemble_edit` forcing that file to be kept whole. No hashline adoption required.

---

### 5.8 Content-hash staleness gate (`MismatchError`) *(impact: medium, effort: small, adopt-now)*

**What it is.** Stamp each file ADF reads in edit mode with a cheap content hash; before `write_files` overwrites, recompute the live hash and refuse (or re-read) if it changed since the model saw it.

**Why it beats ADF's current approach.** `write_files` (`agent_runner.py:660`) overwrites with zero staleness check. If a file changed between `current_app_files` reading it and the model emitting (concurrent edit, prior self-heal iteration, out-of-band change), ADF silently clobbers it.

**Evidence.** `patcher.ts:387` (`liveMatches` gate) + `mismatch.ts` (distinguishes "changed since read" vs "not from this session").

**Adoption plan.** In `current_app_files`, stash `{path: blake2s(content)[:8]}`; before `write_files` persists a model-emitted file, re-read on-disk, recompute, and on mismatch either re-run `assemble_edit` with fresh content or surface a clear conflict. ADF already uses `hashlib.sha256` in `proof_of_build.py:33`, so this is a few stdlib lines. *(Standalone — does not require the full patch format; a precursor to 5.1.)*

---

### 5.9 Completion-audit gate before sealing *(impact: high, effort: medium, adopt-now)*

**What it is.** Before sealing the Proof of Build, run a structured audit mapping each concrete deliverable to current-state evidence, refusing to declare success when verification scope is narrower than claim scope (thin/wrong tests, missing artifacts).

**Why it beats ADF's current approach.** The self-heal loop seals the moment `verify_app` passes (`agent_runner.py:1191-1242`) — but `verify_app` only runs whatever tests the model wrote. A vacuous test (asserts 200, never checks the body) passes the gate and ADF seals a wrong app. *(Notably, ADF's deterministic port would be **stronger** than oh-my-pi's own version: oh-my-pi's audit is a soft model self-steer in `goal-continuation.md`, not a mechanical check — `completeGoalFromTool` at `goals/runtime.ts:461-484` enforces nothing.)*

**Evidence.** `prompts/goals/goal-continuation.md` (6-step audit: restate deliverables → map to authoritative evidence → re-inspect → match verification scope to claim scope → uncertainty = not-done → budget-exhaustion ≠ completion).

**Adoption plan.** After `verify_app` passes and before `seal_app`: for the shaped path, derive the deliverable checklist *deterministically* from `feature_shapes.skeleton_contract` (it already enumerates exact routes/status-codes/test-cases) and grep the generated test for each route+status assertion — block the seal (or trigger one more heal iteration) when a required deliverable has no assertion. For the generic shape, fall back to one cheap model call scoring coverage-vs-spec. Pure-Python for the shaped path; reuses the contract ADF already computes.

---

### 5.10 Declarative agent DAG (`waits_for`/`reports_to`) with Kahn cycle detection *(impact: medium, effort: small, adopt-now)*

**What it is.** Move the crew roster + dependency edges out of hardcoded Dart into a declarative definition parsed into a deps map, with topological wave-building and explicit cycle detection.

**Why it beats ADF's current approach.** ADF's crew waves work but the roster and `needs` are compiled into `buildCrew()` (`agent_crew.dart:98-132`); cycle detection is only an implicit `StateError` on an empty wave. You can't add a `security-analyst` agent or re-wire deps without editing Dart.

**Evidence.** `swarm/dag.ts` (`buildDependencyGraph`, Kahn `detectCycles`, `buildExecutionWaves`) + `swarm/schema.ts` (`validateSwarmDefinition` self-dep/unknown-dep checks).

**Adoption plan.** Add a crew-def file (the 6 agents + needs already exist as data) loaded by `FeatureStore`; port the ~80-line algorithm to Dart. Keep `engine.generatePhase` as the run body.

---

### Adopt-later (gated on a prerequisite)

These are confirmed real and portable but only pay off after a prerequisite lands; do them in sequence, not now.

| Item | Evidence | Gate / why later |
|---|---|---|
| **Process-group spawn for Python boot helpers** | `crates/pi-shell/src/shell.rs` `NewProcessGroup` + `process.rs` `killTree` | `smoke_boot`/`_node_smoke_boot` use `Popen` without `start_new_session`, orphaning node/vite grandchildren. Small stdlib fix (`start_new_session=True` + `os.killpg`) — **borderline adopt-now**, low frequency |
| **Concurrent stdout/stderr drain in `phase_runner.dart`** | `shell.rs:2331-2340` (single shared pipe; the comparison's "two streams" framing was corrected) | Genuine deadlock: `phase_runner.dart:732-750` drains stdout fully *then* stderr; >~64KB to stderr blocks until the budget timer. Small Dart fix |
| **Deterministic command-output minimizer (tiny per-command dict)** | `pipeline.rs` + `detect.rs` (~900 LOC full; ADF needs only a small dict since it knows the command) | Second priority behind the OutputSink, which subsumes most of the raw-token problem |
| **LSP-driven pre-build diagnostic pre-filter (pyright/tsc-LSP)** | `lsp/index.ts:686/496` + `defaults.json` (53 servers, not 48) | High-impact but a from-scratch JSON-RPC-over-stdio client; land the ledger first, then pyright for the default stdlib stack |
| **Version-aware diagnostic staleness** | `lsp/index.ts:507-521,642` | Pure ~30-line algorithm but *useless* without the LSP prefilter — rides on it |
| **DiagnosticsLedger dedup** | `diagnostics-ledger.ts:4-41` | ~20 lines, works on raw tsc/vitest text today; near-zero-risk standalone — **could be adopt-now**, modest impact since ADF caps at 3 iters |
| **Per-subagent resume via persisted run-contract** | `task/persisted-revive.ts`, `registry/agent-lifecycle.ts` | Gain only materializes once crew agents bill tokens via `AgentEscalation`; on the $0 deterministic brain (regenerate in ms) it saves nothing |
| **Bounded-concurrency worker pool + abort** | `task/parallel.ts` (`mapWithConcurrencyLimit`, `Semaphore`) | Nothing to overwhelm with 6 ms-scale agents (max wave width 2); pair with the resume item once agents are LLM-backed |
| **Superseded/useless tool-result pruning** | `pruning.ts` (`MIN_PRUNE_TOKENS=50`, etc.) | Presupposes a structured per-turn tool-result session log ADF's whole-file runner lacks; only after `compact_messages` is wired |
| **Adaptive keep-recent via measured usage ratio** | `compaction.ts:889-897` | Backends do return usage, but the ratio only sharpens `compact_messages`, which isn't wired into the runner |
| **Tiny-model difficulty classifier for routing** | `auto-thinking/classifier.ts` (3-class > 4-class on sub-2B is in the *file header*, not `local-models.md`) | Better than `_complexity`'s lexical heuristic, hostable on ADF's local Nemotron tier, but adds a model call — gate behind `ORCH_ROUTER=auto` |
| **Role/usage-based provider health resolution** | `model-resolver.ts:382-415` (`pickPreferredModel`) | Small in-memory provider-health map, but only pays off once the rate-limit classifier (5.3) feeds it failure reasons |
| **Pre-send secret obfuscation of the LLM transcript** | `secrets/obfuscator.ts`, `secrets/index.ts` | Real exfiltration gap (a secret in a prompt/read file reaches the provider); reuse `policy_gate._SECRET_PATTERNS` + env-name matching. **Borderline adopt-now** |
| **Critical-pattern denylist over generated `package.json` scripts** | `bash.ts:51-90` (`CRITICAL_BASH_PATTERNS`) | `offline_build.py` already denylists *network* tools over declared stack commands; extend with destructive-shape regexes applied to generated npm scripts — the one real model→exec path. **Borderline adopt-now** |
| **End-of-build reflective fix-recipe capture** | `autolearn/controller.ts:83-138` | The LLM-nudge mechanism doesn't port; the deterministic `{signature, phase, fix}` distillation does — but only pays off after 5.4 exists to consume it |
| **Fail-closed pre/post tool hooks** | `hooks/tool-wrapper.ts:52-88` | Programmable org guardrails ADF can't express today; fewer interception points given whole-file protocol — after secret obfuscation |
| **Curated builder-domain "mental models" (cached, budget-capped)** | `hindsight/seeds.json`, `mental-models.ts:215-324` | Render/inject scaffolding ports; content-generation engine does not — needs cross-app consolidation ADF doesn't yet collect |
| **Capability/provider registry + layered SKILL.md discovery** | `capability/index.ts`, `extensibility/skills.ts` | Premature: ADF has 2 stacks + 3 runners and an existing `CustomBackend` env escape hatch; revisit when a 3rd-party ecosystem is a real goal |
| **MCP *client* (consume external servers)** | `mcp/manager.ts` + transports + `config.ts` | Real missing direction, but cuts against ADF's $0/offline-determinism identity (network nondeterminism into a proof-sealed pipeline); large pure-Dart build — only with a concrete in-pipeline tool need |
| **Model-based difficulty classifier (prompt-to-app variant)** | `auto-thinking/classifier.ts` | Same as routing classifier — adds a model call for marginal tier gain; gate behind `ORCH_ROUTER=auto` |
| **Orthogonal advisor/watchdog reviewer** | `advisor/runtime.ts`, `watchdog.ts:11-83` | A real channel ADF lacks; the live async loop doesn't map onto ADF's batch generate→verify→seal flow, so a single post-gen review call is a weaker analog — after the completion-audit gate |

## 6. Explicitly NOT Worth Adopting

- **Snapshot-replay 3-way-merge recovery** (`recovery.ts`) — verified correct, but needs a pre-edit snapshot ADF doesn't keep + a diff lib ADF doesn't import; only pays off *after* the full patch format lands, and ADF's real drift backstop is re-read + the self-heal loop. *Skip until/unless 5.1 ships.*
- **DAP runtime-debug loop (debugpy)** (`tools/debug.ts`) — building a DAP client (socket + framing + breakpoint-at-traceback parsing + locals capture) is large; ADF's generated apps are small fresh scaffolds where a vitest/unittest traceback is usually enough. *Revisit only if logic-bug convergence is a measured bottleneck.*
- **Detached async subagents with yield-based delivery** (`task/index.ts`) — depends on `AsyncJobManager` + yield-tool + session lifecycle ADF has no equivalent of; ADF already gets non-blocking kick from `unawaited(kickAutopilotBackground)` + `TraceWriter`. *Large effort, marginal benefit over the existing seam.*
- **Resume-safe output-id allocation** (`task/output-manager.ts`) — ADF already seals every attempt's artifact hashes into the IntegrityChain, so the audit trail is preserved cryptographically even when the file is overwritten. *Keeping `plan-2.md` files is a marginal nicety.*
- **Cross-session handoff document pipeline** (`docs/handoff-generation-pipeline.md`) — genuine in oh-my-pi, but its core pain (unbounded interactive multi-turn context) barely exists in ADF's bounded 9-phase governed DAG; needs session-tree plumbing the Dart orchestrator lacks + a non-$0 LLM call.
- **Replay-safe streaming retry** (`stream.ts:368-482`) — elegantly correct, but ADF's whole-file protocol is inherently non-streaming and nothing in ADF streams today (`call_ollama` sets `stream:false`); adopting requires first building a streaming path. *Defer indefinitely.*
- **Embeddable SDK surface** (`sdk.ts:1100`) — ADF already has a clean process boundary (HTTP API + outbound MCP) that external agents use; no evidenced demand for in-process Dart embedding. *Lowest ROI of the architecture items.*
- **Full read/write/exec tier approval state machine** (`docs/approval-mode.md`) — ADF's generation agent has **no free-form shell or file tool** (it only emits whole files via the `<<<FILE:>>>` protocol; every command ADF runs is fixed by its own code), so there is no per-tool-call surface to gate. The only real exec risk (generated npm scripts) is better closed by the small critical-pattern denylist. *Over-engineered for ADF.*
- **Plan-as-protected-artifact / compaction protection for the spec** (`plan-protection.ts`) — **solves a problem ADF doesn't have**: the Dart crew re-reads `requirement.md` fresh from disk per phase (`deterministic_artifacts.dart:23-46`) and `compact_files` is wired *only* to the EDIT-mode app-file payload (`agent_runner.py:1064`), never the spec; `build_messages` injects spec/plan verbatim (`:178-182`). There is no paraphrase or spec-compaction drift to protect against.

## 7. Recommended Next 3 Moves

1. **Ship the two zero-risk resilience + hygiene fixes in one pass (5.2 + 5.3 + 5.8).** Add `NON_INTERACTIVE_ENV` to `scrubbed_env` and mirror into `phase_runner.dart childEnvFor`; surface HTTP status from `http_post_json` and wrap each `call_*` in a reason-classified `retry(3)` (inner) before backend failover (outer), giving the Dart brains the same status-keyed retry; and stamp `current_app_files` reads with a content hash, re-checking before `write_files` overwrites. *All pure stdlib, no native deps; closes the pager-hang risk, the silent 529→weaker-backend downgrade, and the blind-overwrite hole — the three highest impact-per-effort items.*

2. **Close the learning loop and harden the seal (5.4 + 5.9).** Wire `knownBlockers(phase)` into the build/heal prompt (the signal is already collected — only the read half is missing), and add a deterministic completion-audit before `seal_app` that derives the deliverable checklist from `feature_shapes.skeleton_contract` and rejects sealing when a required route+status has no test assertion. *Together these stop ADF from re-deriving the same failures and from sealing passing-but-vacuously-tested apps — the two biggest correctness gaps in the build pipeline.*

3. **Cut edit-mode token cost with a hashline-style patch applier (5.1), preceded by the cheap OutputSink (5.6).** First replace `out[-3000:]` with a head+tail+artifact-spill `OutputSink` so self-heal sees the *first* error, not just the tail. Then, edit-mode-only, replace whole-file re-emission with a `[path#TAG]` + line-hunk format: `normalize`/`file_tag` (blake2s), a numbered-read presentation in `build_edit_messages`, a ~150-LOC bottom-up `apply_hunks`, and a pre-apply hash gate — keeping whole-file emission for BUILD/new-file and dropping tree-sitter block ops. *This is the headline structural win for the one-box `editApp` loop (cost `O(change)` not `O(file)`, plus collateral-damage and staleness safety), staged behind the smaller wins because it is ~large and touches the generate/edit protocol.*