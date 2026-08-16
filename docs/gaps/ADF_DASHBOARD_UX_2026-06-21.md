# ADF Dashboard UX — Diagnosis & Remediation Plan

**Date:** 2026-06-21
**Incident feature:** `regulatory-affairs-pharaceutical-industr`
**Author:** Lead (consolidated from 35 dimension-level findings)

---

## 1. Executive Summary

The user reported four felt problems: (a) streaming is **bursty, not smooth**; (b) the **conversation is glitchy**; (c) ADF **barreled past requirements** without presenting them; (d) it **ended blocked with no guidance**. These trace to **four root causes**, not four bugs.

### Root cause A — The live token stream is wired to the wrong runner.
The genuine, sub-second token feed that would produce a smooth "watch it think" experience is **only consumed on the cursor runner** (`ADF_RUNNER=cursor`). The deployed runner is the **Python `custom` runner**, which emits `runner.*` narration plus bare `{"type":"text"}` token events that the reasoning-buffer path **never reads** (`phase_runner.dart:1441-1453`). On top of that, even if those tokens were read, the only thing actually streaming token-by-token is **raw code**, which `isCodeDump` correctly suppresses (`phase_runner.dart:1163`) — leaving the live pane fed by coarse events spaced seconds apart. The transport compounds this: custom-runner spans are written **out-of-process** to `otel-traces.jsonl`, and the server's SSE only broadcasts spans appended *in-process*, so the client falls back to a 1.5–2s poll (`trace_writer.dart:19-21`, `server.dart:1720-1731`). The reveal layer then turns each poll batch into a dump-then-stall (`plain_thought_view.dart:50-55`, `typewriter_text.dart:69`). **Net: there is no continuous, per-token reasoning stream for the running build — by construction.**

### Root cause B — The conversation thread is built from the wrong source, with no IDs and no agent identity.
`buildChatView` treats `commands.jsonl` as a chat transcript and renders **internal control commands** (`crew`, `@orch-orchestrator resume …`) as fake **user bubbles** (`conversation_builder.dart:172-200`). The 6200 `agent.stream` reasoning spans are **never woven into the durable thread** — they flash live then vanish on the next `isRunning=false` poll (`agent_conversation_view.dart:72-75,108-115,213-219`). Ordering is non-deterministic (sort on a second-resolution string with tied keys, `conversation_builder.dart:202-206`) and client dedup keys on `role|text`, collapsing legitimately-repeated status lines (`feature_detail_screen.dart:273-290,491-511`). No span carries `agent.name`, so the stream can never say "Product Analyst is thinking…" (`phase_runner.dart:1164-1170`).

### Root cause C — The requirements gate is bypassed; the spec is garbage; nothing is ever presented.
`AgentCrew._advance` **hardcodes `awaiting_user=false`** for every phase 1-6 and never calls `autoApprove`, so the track-aware hold (designed so tracks M/L/XL *never* auto-flow) is **dead code** (`agent_crew.dart:410-422`, `feature_store.dart:700-713`). The track-M feature barreled to phase 7 unattended. Meanwhile `appendClientClarification` writes **every** user turn — including `@orch-orchestrator resume …` — verbatim into `requirement.md` (`feature_store.dart:247-264`), the deterministic engine turns that spam into EARS `SHALL` requirements (`deterministic_artifacts.dart:43-91`), and the result permanently fails the garbage-floor validator — but that validator **landed after the gate was already set true and cannot un-advance it** (`validate_adf_artifacts.sh:56-68`). There is **no "here are the verified requirements — confirm?" surface** on the deterministic path at all.

### Root cause D — Blocked state has no explanation surface, and success messages lie.
At `heal_attempts >= 3`, the runner writes a generic "Build stopped after 3 attempts" with **no causative reason** (`phase_runner.dart:1003-1023`, `status_banner.dart:81-88`). The crew's blocker message is formatted **identically to success** (`agent_crew.dart:433-455`). The runner emits "tests passed" even when `tests_green=false` (`phase_runner.dart:900-904`). And `GatesPanel` — which would show *which* gate failed — is **implemented but never rendered** by any screen (`feature_inspector.dart:86`).

---

## 2. Findings Table

| Dimension | Title | Sev | User symptom | Effort |
|---|---|---|---|---|
| streaming | Live token stream dead on custom runner (agent.stream is cursor-only) | critical | Abrupt; "waited then spat a lot" | M |
| streaming | Runner's real sub-second feed is raw code, correctly filtered out | high | Dark waits, sudden bursts | M |
| streaming | SSE can't carry out-of-process custom-runner spans; only file-backfill | high | "Live" chip but 1.5-2s batches | M |
| streaming | Web SSE depends on deprecated dart:html; else degrades to 1500ms poll | medium | Purely polled, no streaming | M |
| streaming | Typewriter types last-line-only → poll batch = dump-then-stall | medium | Jerky, non-homogeneous reveal | M |
| streaming | Technical event log pane has no SSE — pure 800ms poll | low | Raw log updates in chunks | S |
| conversation | Internal crew/orch commands leak in as fake user bubbles | critical | Glitchy/terse; no requirements shown | M |
| conversation | 6200 reasoning spans never woven into durable thread | critical | Thoughts burst then vanish | L |
| conversation | Sort on created_at string only; prompt+reply share timestamp | high | Reply precedes question | S |
| conversation | Client dedup keys on role+text → identical replies collide | high | Bubbles flicker/drop/reorder | M |
| conversation | Build-complete bubbles show truncated/garbled file lists | medium | Mangled half-paths | S |
| conversation | Crew/orch replies are 1-line stubs — no spec presented | high | Never said "here's what's done" | M |
| reasoning | Agent identity never attached to spans (all 6200 anonymous) | high | No "Analyst is reading…" labeling | M |
| reasoning | TypewriterText burst-then-stall: N-1 instant, only tail types | high | Abrupt, not step-by-step | M |
| reasoning | Zero reasoning spans during crew phases 1-6 (requirements) | high | Nothing to show during reqs phase | L |
| reasoning | isCodeDump guard landed after run — raw SQL/JS leaked live | medium | Raw code fragments in stream | S |
| reasoning | 6x duplicate crew phase labels across retries | medium | Same labels repeated, confusing | S |
| reasoning | Reasoning panel hidden in collapsed ExpansionTile | low | Panel may not be visible at all | M |
| reqs-gate | AgentCrew._advance bypasses track-M hold (hardcodes awaiting_user=false) | critical | Never paused; barreled to phase 7 | S |
| reqs-gate | requirement.md polluted with orch command spam | high | Garbage requirements | S |
| reqs-gate | Deterministic engine turns command spam into EARS SHALL reqs | high | "SHALL i need to create a app…" | M |
| reqs-gate | Garbage floor can't un-advance gates set before it shipped | high | Garbage spec yet gate=true | M |
| reqs-gate | No "verified requirements — confirm?" step on deterministic path | high | Never presented/confirmed | M |
| blocked-ux | Blocked state has no dedicated explanation surface | critical | No idea what failed or what to fix | M |
| blocked-ux | Spec-corruption blocker formatted identically to success | high | User didn't notice the block | S |
| blocked-ux | Runner says "tests passed" while tests_green=false | high | Contradictory: "passed" yet blocked | S |
| blocked-ux | GatesPanel implemented but never rendered | high | Can't see which gate failed | M |
| blocked-ux | Status bar body blank when running but step_id=null | medium | "Running \| Step: " empty | S |
| blocked-ux | No requirements-verified milestone when crew finishes 1-6 | medium | No "here's what's done" moment | M |
| incident | Duplicate crew fire at T+0 (two pipelines within 7s) | high | Glitchy from second one | S |
| incident | Phase-7 runner auto-restarts after every phase_complete | critical | No stable stopping point | M |
| incident | Persistent build failure; "attempt 4 of 3" counter bug | critical | Repeated "stopped", no root cause | M |
| incident | spec.md permanently contaminated → every crew run blocked | critical | Crew can never self-fix | S |
| incident | [REQ:clarify] infinite loop from local 4B Ollama nano-model | high | 8 user msgs, all → re-clarify | M |
| incident | 84s and 1018s dead silences in agent.stream | high | Bursts and stalls | S |
| incident | 600s build timeout consumes 10min with no visibility | medium | One invisible 10-min wait | S |
| incident | requirement.md accumulates all chat as clarifications verbatim | high | Nonsensical spec content | M |

---

## 3. Per-Finding Detail

### Streaming pipeline

**S1 — Live token stream dead on custom runner (critical).**
Root cause: `phase_runner.dart:1441-1453` buffers reasoning into `agent.stream` spans only on stdout `type=='assistant'||'message'` — its own comment says "LIVE only on the cursor-agent runner". The deployed runner is `custom` (Python), which emits `runner.*` + bare `{"type":"text"}` tokens, never `assistant`/`message`. The 6200 spans in `otel-traces.jsonl` are from an earlier cursor run.
Evidence: `phase_runner.dart:1441-1453`; `/tmp/orch-api.log` "Active runner: custom"; `run-log.jsonl` tail (`{"type":"text"}` tokens).
Fix: In the custom-runner stdout handler, feed `{"type":"text"}` token events into the **same** `_reasoningBuffers`/`_flushReasoningBuffer` path the cursor runner uses, so the Python runner's real token stream produces live `agent.stream` spans.

**S2 — Real sub-second feed is raw code, correctly filtered (high).**
Root cause: the only thing streaming token-by-token during generation is code (`<<<FILE:…`, SQL, `=>`), which `isCodeDump` rejects (`phase_runner.dart:1163,1179-1181`). Even with S1 fixed, the live pane gets only coarse `generating_progress` events; there is **no NL narration at token granularity**.
Evidence: `run-log.jsonl` code tokens every ~0.4-1.8s interleaved with `generating_progress` every ~6s; `phase_runner.dart:1163,1179-1181`.
Fix: Emit a sub-2s NL heartbeat span — "still generating `<file>` — N/M lines" — during code generation, so the pane has continuous human-readable motion while raw code stays hidden.

**S3 — SSE can't carry out-of-process spans (high).**
Root cause: `TraceWriter._events` is an in-process `StreamController.broadcast` (`trace_writer.dart:19-21`); `/events` tails it (`server.dart:1728-1731`). It only fires for spans appended by *this* server via `_traces.append`. The custom runner is a separate process writing `otel-traces.jsonl`; the server reads it once via backfill at connect (`server.dart:1722`) and never re-reads — so no new custom-runner span is ever pushed live.
Evidence: `trace_writer.dart:19-21,82-84`; `server.dart:1720-1731`.
Fix: Tail the per-feature `otel-traces.jsonl` on the server (file watcher) and push appended lines into `TraceWriter._events`, turning the 1500ms batch poll into a continuous push.

**S4 — Web SSE depends on deprecated dart:html (medium).**
Root cause: `agent_conversation_view.dart:9-10` selects `sse_connector_web.dart` only `if (dart.library.html)`; that connector uses deprecated `dart:html EventSource`. On any non-html target the stub drips a 1ms error to force degrade past `maxSseErrors=3` to the 1500ms poll (`sse_connector_stub.dart:15-17`, `live_trace_client.dart:138-151`).
Fix: Confirm the deployed build is the dart:html web target; migrate to `package:web`/`dart:js_interop` EventSource; verify in DevTools that `/events` stays open.

**S5 — Typewriter last-line-only = dump-then-stall (medium).**
Root cause: `PlainThoughtView` types only the final line (`plain_thought_view.dart:50-55`); earlier batch lines render instantly. `TypewriterText` fast-forwards when backlog>120 chars (`typewriter_text.dart:69`). Reveal cadence = poll-batch size, not token rate.
Fix: Once S1-S3 land, drive the typewriter from a steady token queue with a fixed drain rate (decouple ingest from reveal via a small buffer + steady timer).

**S6 — Technical event log has no SSE (low).**
Root cause: `AgentThoughtStream` uses a plain `Timer.periodic` 800ms poll, no SSE (`agent_thought_stream.dart:61-67,76-112`; `feature_inspector.dart:191-198`).
Fix: Route it through the same `LiveTraceClient`/SSE source, or explicitly label it as a polled raw-log view.

### Conversation rendering

**C1 — Internal commands leak as fake user bubbles (critical).**
Root cause: `buildChatView` renders every row with a non-empty `prompt` as a user bubble (`conversation_builder.dart:172-200`); `crew` and `@orch-orchestrator resume …` are machine triggers, not human input.
Fix: Add a `kind`/`origin` field (user/system/orchestrator) per command row; skip/transform internal ones into compact status chips ("Crew rebuilding spec…", "Resuming build…"). Only human prompts become "You" bubbles.

**C2 — Reasoning never woven into durable thread (critical).**
Root cause: `ConversationBuilder.build()`/`buildChatView()` read only run-log/commands; neither ingests `agent.stream` spans. The live panel is gated on `isRunning` and cleared on run reset (`agent_conversation_view.dart:72-75,108-115,213-219`), so thoughts vanish when the run stops.
Fix: Server-side, fold `agent.stream` reasoning into the chat model as collapsible "Agent thinking" entries keyed by step, ordered by span timestamp, so they persist post-run.

**C3 — Non-deterministic ordering (high).**
Root cause: user+assistant both stamped with `cmd['created_at']`, then sorted on the string (`conversation_builder.dart:180-206`); ties at second resolution reorder.
Fix: Composite sort key (timestamp, id, role-rank user<assistant). Command id is already a sortable epoch-ns integer. Apply same to `build()` 137-141.

**C4 — Dedup collides on role+text (high).**
Root cause: `_mergedConversation`/`_applyDetail` key dedup on `role|text` (`feature_detail_screen.dart:273-290,491-511`); ~12 byte-identical replies collapse and flicker across polls.
Fix: Have `buildChatView` emit a stable per-bubble id (command_id+role+index or span id); key all dedup on it.

**C5 — Garbled build-complete file lists (medium).**
Root cause: the runner-composed reply is itself corrupt ("`-affairs-pharaceutical-industr/…`", "`/useAnds.ts`"); `buildChatView` renders it verbatim as Markdown (`conversation_builder.dart:190-200`).
Fix: Fix the upstream file-list join (off-by-N strip on the `apps/<id>/` prefix); optionally normalize defensively on render.

**C6 — Crew replies are 1-line stubs (high).**
Root cause: only the terse `assistant_reply` is shown; nothing reads the built spec back into the conversation (`conversation_builder.dart:190-200`).
Fix: On crew/spec completion, compose a richer assistant turn summarizing captured requirements (from `spec.md`+`requirement.md`) + next steps, persisted as the reply or a dedicated presentation message.

### Reasoning presentation

**R1 — Spans are anonymous (high).** `agent.stream` spans carry no `agent.name`/`agent.wave` (`phase_runner.dart:1164-1170`, `trace_writer.dart:42-61`). Fix: add `agent.name`+`agent.wave` at `_flushReasoningBuffer`; `PlainThoughtFormatter` emits a header on agent transition ("Product Analyst is thinking…").

**R2 — Burst-then-stall (high).** Same mechanism as S5; measured max 27 spans in one 1.5s window. Fix: persistent display queue, enqueue lines with 300-600ms inter-line delay; raise typewriter step divisor 8→20+.

**R3 — Zero reasoning spans in crew phases 1-6 (high).** All 6200 spans are phase 7; the requirements pipeline emits only `crew.wave_start`/`agent_done` (`phase_runner.dart:1441-1445`). Fix: have crew agents emit `narrate()`/`agent.stream` reasoning, or at least a per-agent progress span every 5-10s per wave.

**R4 — Raw code leaked live (medium).** `isCodeDump` guard (`f5fb437`) shipped 10.5h after the run; client `ThoughtSanitizer._isNoise` misses mid-fragment strings like "CREMENT,\n…" (`thought_sanitizer.dart:45-50`). Server fix is in place. Fix: strengthen `_isNoise` to drop strings starting mid-word / >25% non-alpha; use content hash (not `body.hashCode`) for dedup.

**R5 — 6x duplicate crew labels (medium).** Dedup key uses timestamp, so 6 retry runs all pass (`agent_thought_stream.dart:94-96`); `_addLine` dedups consecutive only (`plain_thought_formatter.dart:93-100`). Fix: include run/session id in the key (show "Run 2:" or collapse "Wave 1 (3 attempts)"); content-dedup structural labels globally.

**R6 — Panel hidden in collapsed ExpansionTile (low).** `AgentThoughtStream` is inside a collapsed "Technical event log" tile (`feature_inspector.dart:186-199`); the primary panel only renders when `isRunning && _liveSpans.isNotEmpty` (`agent_conversation_view.dart:72-75,213-215`). Fix: promote to a permanently visible panel; after a run, one-shot fetch the last N reasoning spans for a post-run summary.

### Requirements gate flow

**G1 — Crew bypasses track-M hold (critical).** `AgentCrew._advance` sets `awaiting_user=false` for every phase 1-6, never calls `autoApprove`/reads `track` (`agent_crew.dart:410-422`); the track-aware guard (`feature_store.dart:700-713`) is dead. `Autopilot._advance` has the identical bug (`autopilot.dart:218-230`). Fix: route every advance through `autoApprove`: `if (!FeatureStore.autoApprove(state)) { state['awaiting_user']=true; pending_approval_phase=phase; }`.

**G2 — requirement.md polluted (high).** `appendClientClarification` writes every turn verbatim (`feature_store.dart:247-264`). Fix: drop/quarantine lines matching `^@orch-orchestrator`, `^# Builder:`, bare `resume <id>` before appending; keep them in `commands.jsonl`.

**G3 — Engine synthesizes EARS from spam (high).** `_readRequirement`/`extractRequirements`/`earsStatement` keep control-command bodies and wrap each fragment as "The system SHALL …" (`deterministic_artifacts.dart:43-91`). Fix: reuse the G2 filter in `_readRequirement`; reject fragments <3 meaningful tokens or starting with a control sigil; ideally require the real crew/human-confirmed spec on track M.

**G4 — Garbage floor can't revert set gates (high).** Floor (`validate_adf_artifacts.sh:56-68`) shipped after `requirements_complete=true` was set; the crew loop validates only on the way up and never re-checks passed gates (`agent_crew.dart:308-330`). Fix: on every crew/autopilot run, re-validate passed requirements gates (phases 2-4); on FAIL, revert the gate + reset `current_phase` + set `awaiting_user` (track-aware).

**G5 — No "confirm requirements?" step on deterministic path (high).** `requirements_open_questions` is populated only by the model-backed crew (`requirements_crew_runner.dart:94-96`); the deterministic path leaves it empty, so no elicitation gate renders. `_announce` only posts a terminal handoff (`agent_crew.dart:433-455`). Fix: add a hard requirements-presentation gate after phase 2 for M/L/XL — write a human-readable summary command into `commands.jsonl`, set `pending_approval_phase=2`+`awaiting_user=true`, stop; mirror `/approve` semantics (`approval_gate.dart`).

### Blocked & status UX

**B1 — No blocked explanation surface (critical).** `phase_runner.dart:1003-1023` writes a generic message; `status_banner.dart:81-88` renders a generic action prompt — no cause. Fix: add `blocked_reason` (error_code + first recovery_step) to run_status; surface it in the banner body; add a "Blocked" panel in `feature_detail_screen.dart` showing recovery_steps + "3/3 attempts exhausted".

**B2 — Blocker looks like success (high).** `_announce` formats blocked and success identically (`agent_crew.dart:433-455`); `run_status.error` stays null so the banner hits the Running branch, not blocked. Fix: prepend "BLOCKED — crew halted:" and set `run_status.error` to the blocker.

**B3 — "tests passed" while tests_green=false (high).** `phase_runner.dart:900-904` builds the outcome from exit code only, not `state.gates['tests_green']`. Fix: after `syncAfterRun` (line 876), read back `tests_green`; if false at phase 7, write "Build ran but tests are still failing — check run-log.jsonl".

**B4 — GatesPanel never rendered (high).** `FeatureInspector` (which renders `GatesPanel`, `feature_inspector.dart:86`) is never instantiated; `live_preview_panel.dart:220-295` shows only a progress bar. Fix: embed a gates breakdown in the Overview tab with per-gate human labels, conditional on phase>=7.

**B5 — Blank status body when step_id=null (medium).** `status_banner.dart:62-63` renders "Running | Step: " with empty stepLabel. Fix: phase-aware fallback body, e.g. "Building your app — writing code and running tests (phase 7 of 9)".

**B6 — No requirements-verified milestone (medium).** `_announce` posts a one-liner; `_checkMilestones` fires only an auto-dismissing snackbar (`feature_detail_screen.dart:241-243`). Fix: append a structured artifacts summary; add a persistent "Spec ready" milestone card at the phase-6 boundary with a deep-link to the Spec tab.

### Incident timeline

**I1 — Duplicate crew fire at T+0 (high).** Two crew runs 79ms/7s apart (`commands.jsonl:1-2`, two trace_ids). Fix: feature-level `crew_running` mutex in state.json checked before dispatch.

**I2 — Phase-7 auto-restart, no gate (critical).** `phase_complete`→`phase_start` within 0-60s, 7 times, chasing `tests_green`/`r100`; 7 sealed Proofs the user never sees. Fix: pause at a UI gate after `phase_complete`; make the completion_audit loop opt-in/visible.

**I3 — Persistent failure + "attempt 4 of 3" bug (critical).** Counter composed as `inner+outer` → "4 of 3" (`commands.jsonl:15-30`); `context_budget_warn` ~403/514 tokens means the model gets a stub context and regenerates failing code. Fix: correct the counter arithmetic; on `context_budget_warn`, abort self-heal and surface the root tsc error instead of burning 3 doomed attempts.

**I4 — Permanent spec contamination (critical).** 8 literal `@orch-orchestrator resume` strings in `spec.md` Problem statement; block fires on every subsequent run (`crew-log.jsonl:30,36`). Fix: strip `@orch-orchestrator .*` from `requirement.md` clarifications before writing `spec.md`; filter at ingestion (same as G2). Same root as I7.

**I5 — [REQ:clarify] infinite loop (high).** 4B Ollama nano-model (`hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B`) re-clarifies on every message including "yes"/"proceed"; eventually errors to fallback (`commands.jsonl:23-37`). Fix: detect imperative build/run intent and route to the orchestrator path, bypassing the clarification model; cap consecutive clarification depth at ~2, then execute or escalate to a cloud model.

**I6 — 84s/1018s dead silences (high).** 122 gaps >5s, 10 >30s; `generating_progress` heartbeats were absent from all Jun-20 runs (first one Jun-21 11:37). Fix: backfill the 6s heartbeat to all runner paths; emit a "run N of M started" event at each `feature_resolved`.

**I7 — requirement.md accumulates all chat verbatim (high).** 12 clarification blocks, 8 are orch commands; engine ingests wholesale (`state.json` `spec_source='deterministic'`). Fix: classify each input — pure affirmatives ("yes"/"proceed"/"ok") and routing commands update execution state only, never `requirement.md`; validate `requirement.md` before generating `spec.md`. (Converges with G2/G3/I4.)

---

## 4. Prioritized Fix Plan

The user's two deepest wants are: **(1) a SMOOTH, step-by-step reasoning stream**, and **(2) ADF actually presenting and confirming requirements before barreling on.** Everything below is ordered by **felt improvement per unit effort**, not by severity label.

### TIER 0 — Do FIRST. Small effort, enormous felt change. (~1-2 days)

These three S-effort fixes deliver the single biggest visible win: ADF stops barreling past requirements, stops lying, and the gate that *already exists* starts firing.

1. **G1 — Route crew/autopilot advance through `autoApprove`** (S, critical). One-line guard in `AgentCrew._advance` and `Autopilot._advance`. This **directly fixes "barreled past requirements"** — track-M now stops at the requirements gate. *Highest single-fix payoff.*
2. **G2 + I4/I7 — Filter orchestrator commands out of `requirement.md` at ingestion** (S, high). Prevents spec contamination at the source, which **un-blocks every future crew run** (this contamination is why the feature is permanently blocked).
3. **B2 + B3 — Make blocked look blocked, and stop the "tests passed" lie** (S, high). Set `run_status.error` to the blocker; cross-check `tests_green` before writing success. Kills the "glitchy / contradictory conversation" feeling immediately.

> After Tier 0: ADF pauses for requirements, the spec is clean, and the conversation stops contradicting itself. This is the bulk of complaints (c) and (d), and a chunk of (b).

### TIER 1 — Do NEXT. The smooth-stream backbone + presented requirements. (~1 week)

These M-effort fixes are the core of want (1) and the rest of want (c). **S1→S2→S3 must land together** — each alone is insufficient.

4. **S1 — Feed `{"type":"text"}` tokens into the reasoning buffer on the custom runner** (M). Without this there is *no* live stream on the deployed runner.
5. **S3 — Server-side tail of `otel-traces.jsonl` into `TraceWriter._events`** (M). Makes out-of-process spans actually flow over SSE — turns batch-poll into push.
6. **S2 — Sub-2s NL "still generating N/M lines" heartbeat** (M). Gives continuous human-readable motion while raw code stays hidden. (Pairs with I6's heartbeat backfill, S.)
7. **C1 — Classify command rows; render internal triggers as status chips, not user bubbles** (M). Removes the most jarring "glitchy conversation" symptom.
8. **G5 — Add the "here are the verified requirements — confirm?" gate on the deterministic path** (M). With G1 already holding, this is what the user actually *sees* at the hold. Mirror `/approve` semantics.
9. **C6 / B6 — Present a real "here's what's done, continuing" turn + persistent "Spec ready" milestone card** (M). The narrative moment the user explicitly asked for.

> After Tier 1: the live pane streams continuously, the conversation reads cleanly, and ADF presents requirements and waits. Wants (1), (a), (c), and most of (b) are addressed.

### TIER 2 — Polish the stream and harden the gate. (~1 week)

Quick wins (S) bundle naturally here:

- **C3** composite sort key; **R4** sanitizer + content-hash dedup; **R5** run-id in dedup key; **I1** crew mutex; **I3** attempt-counter fix + abort-on-context-warn; **I6** heartbeat backfill; **B5** phase-aware status body.

M-effort refinements:

- **S5 + R2** steady token-queue typewriter (the *final* smoothness layer — only meaningful once S1-S3 give a true token feed); **C4** stable per-bubble id for dedup; **R1** agent-identity headers ("Product Analyst is thinking…"); **B1** blocked explanation panel; **B4** render `GatesPanel`; **G3/G4** engine sanitization + gate re-validation; **I2** phase-7 pause gate; **I5** intent-aware chat routing.

### TIER 3 — Deeper structural work. (defer)

- **C2** persist distilled reasoning timeline into the durable thread (L).
- **R3** emit reasoning during crew phases 1-6 (L).
- **S4** migrate web SSE to `package:web` (M); **R6** promote reasoning panel out of the ExpansionTile (M); **S6** SSE the technical event log (S).

---

## Honest caveats

- **Tier 1 is sequenced, not parallel.** S1, S2, S3 are individually shippable but the user feels nothing until all three land — partial delivery will look unchanged. Set expectations accordingly.
- **S5/R2 (the typewriter) is the *last* smoothness lever, not the first.** Tuning it before S1-S3 polishes a poll-driven dump-then-stall; it cannot manufacture a token feed that the pipeline doesn't carry. Resist the temptation to start there because it's UI-visible.
- **The deterministic engine is the wrong long-term path for track M.** G2/G3/I4/I7 all stem from synthesizing requirements out of raw chat. The durable fix is to require the model-backed requirements crew (or a human-confirmed spec) on M/L/XL and treat the deterministic engine as a last-resort fallback — not the default that produced this incident.
- **The incident feature is in a corrupt terminal state** (`requirements_complete=true` over a garbage spec, phase 7, blocked). Even after these fixes it likely needs a manual reset/re-spec; the fixes prevent recurrence, they don't retroactively repair it.
