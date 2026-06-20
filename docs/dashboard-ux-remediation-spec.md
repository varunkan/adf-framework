# Dashboard UX Remediation — Specification

**Status: COMPLETE** — all 12 tasks (T1–T12) landed via TDD, one commit each. Both blockers
(D2 generation blackout, D7 ingest coverage) and the root-cause D3→D8 classifier chain are fixed;
the two adjudicated-false lens claims were dropped. Suites green: dashboard, server
narration/heuristics/ingest, python agent_runner.

Scope: defects in commits `35d1641..HEAD` (the NL-narration / phase-artifacts / approve-revise
overhaul), found by a 4-lens adversarial review + architect adjudication (`needs-fixes-before-ship`)
and independently fact-checked against the code.

**Runner reality (grounded).** `agent_runner.py` (the DEFAULT runner) emits only: `narrate()`
(×43 typed events), `file_write`, `result`, and `text` (the per-token stream). It emits NO
`assistant`/`message`/`tool_call`/`tool_result`/`thinking`. Therefore each defect is tagged
**[LIVE]** (fires on the default runner) or **[LATENT]** (only on the cursor-agent runner,
`ADF_RUNNER=cursor`). Latent ≠ invented — the cursor runner is supported — but it sets priority.

**Method.** TDD: each fix gets a failing test first (red), the smallest change to green, then the
full package suite stays green. One commit per task. No batching.

---

## Defects (grounded)

### D2 — Generation phase goes dark [BLOCKER] [LIVE]
`phase_runner.dart` suppresses `type:'text'`; that token stream is the ONLY signal between
`narrate('generating')` and the post-generation `file_write`s (`agent_runner.py` `_stream_delta`
974-980; file writes happen after generate()). Net: up to ~180s of silence in the longest phase.
**Spec:** the runner emits a coarse, throttled `generating_progress` narrate() event (byte/sec
threshold) carrying a COUNT only (never code), so the feed never goes dark. `cardKind` maps it →
`STEP`. **Test:** (py) N `_stream_delta` calls past the threshold ⇒ ≥1 `generating_progress`
event, containing no `<<<FILE`/code; (dart) `cardKind('generating_progress')=='STEP'`.

### D7 — Zero integration coverage for the suppression dispatch [BLOCKER] [LIVE]
`isCodeDump` is unit-tested in isolation; nothing proves `_ingestAgentLine` actually drops the
`type:'text'` stream and summarizes `result`. A mis-merge deleting the `return;` ships silently.
**Spec/Test:** server test feeds a recorded `text`/`file_write`/`result` line sequence into the
ingest path and asserts: zero spans for the `text` line; a `runner.build_summary` for a
`<<<FILE>>>` result; a kept prose span for a plain result.

### D8 — Code-classifier FALSE POSITIVES drop ordinary English [MAJOR] [LIVE via result; more on cursor]
`isCodeDump`/`ThoughtSanitizer` keyword regexes (`UPDATE\s`,`SELECT\s`, `_codeStart` with
return/from/static/etc., `caseSensitive:false`, anchored `^`) match prose: "Update the spec…",
"Select the format…", "Return the ID…", "From the spec…", "Static analysis shows…", "Flutter
rebuilds…" → flagged as code → dropped/rewritten. Reachable via the `result` prose branch (LIVE)
and `thinking`/`assistant` (cursor). **Spec:** keyword starters require a code discriminator
(e.g. `UPDATE \w+ SET`, `SELECT … FROM`, trailing `;`, NOT followed by an article the/a/this), and
the prose-colliding shell/code words are gated on extra code signal. **Test:** a sentence starting
with each colliding word is classified prose; real `UPDATE users SET x=1`, `SELECT * FROM t`,
`const x = 1;` still flagged.

### D3 — Two divergent "is this code?" implementations, no SSOT [MAJOR] [design]
`PhaseRunner.isCodeDump` (server, ratio 0.10, >40 guard) vs `ThoughtSanitizer._isMostlyCode`
(client, ratio 0.12, no guard): same concept, different thresholds → guaranteed drift, and is the
root cause of the D8 family. **Spec:** one canonical predicate. Server and dashboard are separate
Dart packages; lacking a shared package, define ONE `CodeHeuristics.isCodeLike` per package from an
identical, documented spec + a SHARED golden test vector (same inputs → same booleans), so drift is
caught by CI. Both call-sites delegate. **Test:** a golden table asserted identical in both packages.

### D1 — `rawBody` is dead code; tool detail silently lost [MAJOR] [LATENT consumer]
`trace_span.dart:161` `rawBody` has no consumer; commit `689c907` claimed an "opt-in expander"
that doesn't exist. The old UI showed tool Input/Output; now it's unreachable. **Spec:** add a
"Details" disclosure in `ActivityCard` rendering `rawBody` when present. **Test:** a tool span
renders the NL title and, expanded, the raw Input/Output; a non-tool span shows no disclosure.

### D9 — `ToolNarration._key` never matches production tool input [MAJOR] [LATENT, cursor]
`phase_runner.dart:1305` stores `'$input'` = Dart `Map.toString()` → `{file_path: x}` (no quotes);
the client regex `"key":"value"` never matches ⇒ every tool degrades to "Reading a file". Tests fed
pre-serialized JSON production never sends. **Spec:** server serializes tool.input with
`jsonEncode`; `_key` parses structurally (jsonDecode with try/catch) instead of regex-on-quotes.
**Test:** `humanize('read_file', jsonEncode({'file_path':'lib/db.dart'}))` AND the Map.toString form
both → "Reading lib/db.dart"; a bash command with embedded quotes isn't truncated.

### D5 — Banner "Request changes" discards typed notes + bypasses confirm [MAJOR] [LIVE]
`feature_detail_screen.dart` banner: `onRevise: _clarifyAndRedo('', clientConfirmed:true)` — drops
anything typed in the ApprovalActionBar notes field and makes the `!clientConfirmed` guard dead for
this path. **Spec:** the banner action focuses/scrolls the ApprovalActionBar (where notes + confirm
live) rather than submitting blind; OR shares the notes source. We choose **focus-the-bar** (single
source of the revise decision). **Test:** tapping banner "Request changes" does NOT call the revise
API; it scrolls/focuses the approval bar.

### D6 — `_phaseClicked` never resets; selection pinned, dot sticky, re-tap no-op [MAJOR] [LIVE]
Set once (`:1283`), never cleared; `LivePreviewPanel.didUpdateWidget` only animates on a CHANGED
`selectedPhase`, so re-tapping the same phase does nothing. **Spec:** use a monotonic "selection
nonce" so an identical re-tap still focuses; clear selection (and the dot) when the live phase
advances past the viewed phase or on build completion. **Test:** re-tapping the same phase
re-triggers focus; advancing the live phase clears the dot.

### D10 — `_approve` has no in-flight guard → double-submit [MAJOR] [LIVE]
Two Approve surfaces (banner + bar); `_approve`/`_clarifyAndRedo` on the screen have no `_busy`
guard, so a fast double-tap (or banner+bar) double-submits. **Spec:** a screen-level
`_approvalInFlight` gate disables both surfaces during a request. **Test:** while a submit is
in-flight, a second invocation is a no-op.

### D11 — Reasoning-buffer (`assistant`/`message`) branch is dead on the default runner [MAJOR] [LATENT]
`agent_runner.py` never emits `assistant`/`message`; with `text` now suppressed, `_flushReasoningBuffer`
is never fed on the Python runner, and `plain_thought_formatter_test`'s REASONING cases imply a path
that doesn't run in production. **Spec:** keep the branch (it IS live on cursor), but DOCUMENT it as
cursor-only and add a server test that the Python-runner event set produces narration WITHOUT relying
on the buffer. (No deletion — it's real for cursor; the fix is honesty + coverage.)

### D4 — `_humanStepLabel` keyword order mislabels `test-plan` [MINOR] [LIVE]
`:447 contains('plan')` precedes `:449 contains('test')` ⇒ `test-plan` → "Planning". **Spec:** check
`test` before `plan`. **Test:** `humanStepLabel('build-test-plan')=='Writing tests'`,
`'create-plan'=='Planning'`. Extract to a pure top-level fn.

### D12 — Tab indices are magic literals; pre-existing Spec off-by-one [MINOR] [LIVE]
`animateTo(5)`/`animateTo(2)` literals; the Spec quick-action `:318 animateTo(2)` opens **Data**
(Spec is index 3). **Spec:** named tab constants; fix the Spec action to the Spec index. **Test:**
tapping the Spec quick-action selects the Spec tab.

### D14 — `result` prose silently truncated 8000→2000 [MINOR] [LIVE]
Long genuine prose answers now cut at 2000 (was 8000); rationale ("code persists elsewhere") doesn't
apply to prose. **Spec:** restore a higher prose limit (e.g. 8000) for non-`<<<FILE>>>` results; pin
with a test.

### D15 — `_autoUnstuck` one-shot never reset [MINOR] [LIVE]
Set once per State lifetime; a second genuinely-stuck run is never auto-recovered. **Spec:** reset on
a new run start. **Test:** after a run completes and a new run starts, the valve re-arms.

### D16 — Approval race guard decays via `started_at` [MINOR] [LIVE]
`recentlyActive` falls back to `started_at`, which ages normally, so a >30s phase can still auto-
unstick a fresh gate. **Spec:** anchor to the `awaiting_user`/`finished_at` transition, not the
slow-moving start. **Test:** a 45s phase that just set awaiting_user is NOT auto-unstuck.

### D13 — `_focusSelected` bare catch + deprecated controller [NIT]
`catch(_){}` hides failures; `ExpansionTileController` is deprecated behind `// ignore`. **Spec:**
`debugPrint` in the catch; leave the controller (the supported `controller:` param still requires it)
but track the deprecation. (Lowest priority.)

### Dropped (panel adjudicated false / not worth gating)
- Two-banner phase MISMATCH: **false** — both resolve from `pending_approval_phase` first.
- `ToolNarration` "Writing a test" unreachable branch: nit, not a defect.

---

## DAG

```
Leaves (independent, smallest, do first):
  D4  humanStepLabel order        (pure fn)
  D14 result prose limit          (1 const + test)
  D12 tab constants + Spec fix    (rename + 1 fix)
  D15 autoUnstuck reset           (1 flag)
  D16 race-guard anchor           (1 expr)
  D13 focusSelected debugPrint    (nit)

Core chain:
  D3 CodeHeuristics SSOT  ──►  D8 false-positive discriminators  ──►  (both classifiers delegate)
  D2 generating_progress heartbeat (server+trace_span)  ── independent of D3, but after D8 lands the
                                                            shared classifier so progress text is clean
  D7 ingest-dispatch integration test  ── after D2 (covers suppress + summary + heartbeat together)

Dashboard interaction:
  D1 rawBody ActivityCard expander
  D5 banner focuses approval bar
  D6 selection nonce + reset
  D10 approval in-flight guard      (pairs with D5/D6 — same screen)
  D11 document + cover cursor-only branch
```
Critical path: **D3 → D8 → D7**. Everything else parallelizes.

## Tasks (one commit each; red→green→full-suite)

| T  | Defect | Package | Deliverable |
|----|--------|---------|-------------|
| T1 | D4  | dashboard | extract `humanStepLabel`; order test |
| T2 | D14 | server | restore 8000 prose limit; boundary test |
| T3 | D12 | dashboard | tab-index constants + Spec off-by-one fix; tab test |
| T4 | D15+D16 | dashboard | per-run `_autoUnstuck` reset + race-guard anchor; tests |
| T5 | D3  | both | `CodeHeuristics.isCodeLike` SSOT + shared golden vector |
| T6 | D8  | both | discriminators kill prose false-positives; collision tests |
| T7 | D2  | server | `generating_progress` heartbeat + `cardKind` map; py+dart tests |
| T8 | D7  | server | `_ingestAgentLine` sequence integration test |
| T9 | D1  | dashboard | `ActivityCard` rawBody disclosure; widget test |
| T10| D9  | both | jsonEncode tool.input + structural `_key`; tests (Map+JSON) |
| T11| D5+D6+D10 | dashboard | banner→focus bar, selection nonce+reset, in-flight guard; widget tests |
| T12| D11+D13 | both | document cursor-only path + Python-runner narration test; debugPrint |

Each task: failing test first, minimal fix, run task test + full package suite, commit.

---

# ROUND 2 — fixing the remediation's own holes (post second adversarial review)

A second 4-lens review of T1–T12 (`123cabe..HEAD`) returned `needs-fixes-before-ship`. Findings
fact-checked by running the actual classifier + reading the code. **Honesty correction:** the
Round-1 "COMPLETE" status was premature — D2/D8/D1/D5/D6 were not delivered as specified.

## Defects (grounded)

### E1 — D2 blackout STILL live on the default runner [BLOCKER]
The T7 heartbeat sits in `_stream_delta`, only called when `ADF_RUNNER_STREAM=1` (opt-in, default
OFF — `agent_runner.py:937-943`). The default `generate()` is a single blocking `http_post_json`
emitting nothing between `generating` and `generated`. **Spec:** start a watchdog timer thread
BEFORE the blocking call that `narrate('generating_progress', …)` every ~6s, cancelled on return,
so the feed never goes dark regardless of streaming. **Test:** a watchdog unit test (fake clock /
short interval) asserts ≥1 heartbeat over a simulated slow call, none after cancel.

### E2 — classifier eats prose containing `=>` / `::` / `word();` [MAJOR]
`_callOrArrow` is unanchored → fires anywhere. VERIFIED: `"The request => response cycle now
works."`, `"See ci.example.com::8080 …"`, `"verify(); confirm the output …"` → `isCodeLike=true`
→ dropped at `phase_runner.dart:1381` (also defeats D14). **Spec:** drop bare `=>`/`::`; keep only
line-anchored statement shapes (`[;{]\s*$`, `^\s*\w+\s*=>`, a bare-call line
`^\s*[\w.]+\([^)]*\)\s*[;{]?\s*$`). **Test:** golden cases for prose arrows/URLs/method-refs = false;
real `db.save(url);` / `obj.foo()` = true.

### E3 — SQL false-positives: `select…from`+comma, prose `delete from` [MAJOR]
VERIFIED: `"Select the rows from the cache, limit to 10."` and `"delete from your mind any
assumption…"` → code. **Spec:** SELECT…FROM only when SELECT is NOT followed by an article
(the/a/all/each/…); `delete from`/`insert into` only when followed by a non-possessive identifier
(not your/the/my/…); drop bare `,`/`=` from the SQL signal. **Test:** those exact sentences =
false; `SELECT * FROM t`, `SELECT id, name FROM t`, `DELETE FROM sessions` = true.

### E4 — D1 deviated from spec (deleted vs disclosure) [MAJOR → re-scope]
T9 deleted `rawBody`; the spec deliverable was an ActivityCard disclosure. Hiding raw tool JSON is
consistent with the user's "less machine detail" intent, so **re-classify D1 as DEFERRED** (dead
code removed; a power-user disclosure is a future opt-in) — and correct the Round-1 "landed" claim.
No code change; spec + honesty fix.

### E5 — D6 half-implemented [MAJOR]
(1) Deselect clears `_phaseClicked` but the rail dot binds to `_viewPhase` (`feature_detail_screen
.dart:1321`) so it stays lit. (2) No auto-clear when the live phase advances/ completes. **Spec:**
bind the rail's selected highlight to `_phaseClicked`; in the detail-apply path, clear
`_phaseClicked`/`_viewPhase` when the live phase advances past the viewed one or the build completes.
**Test:** widget tests for deselect-unlights and advance-clears (currently zero D6 tests).

### E6 — D5 dialog ratification + real test [MAJOR]
The dialog is a reasonable design (captures fresh notes, never blind-submits) but deviates from the
specced "focus-the-bar" and is only callback-tested. **Spec:** RATIFY the dialog (single capture
surface for the banner path; the bar stays for the in-chat path) AND add a screen-level test that
opens the dialog, submits a note, and asserts `_clarifyAndRedo` received it. Fold in E9 (dispose the
controller) + E10 (treat empty == cancelled).

### E7 — make the T8 suppression test non-vacuous [MAJOR]
Deleting the `return;` in the `type:'text'` branch still yields zero spans (text falls through to
no-match). **Spec:** the test must feed `text` THEN a known span-producing event on the same run and
assert ONLY the latter survives in order — so removing the guard (which would then buffer/emit the
text) fails the test.

### E8 — remove the dead `selectionNonce` [MINOR]
Deselect-toggle always changes `selectedPhase`, so the nonce clause never independently fires. Remove
the param + plumbing.

### E11 — ratify `generating_progress` → GENERATE + add the test [NIT]
GENERATE (active tone) is better UX than the spec's STEP. Update the spec to GENERATE and add the
missing `cardKind('generating_progress')` test.

## DAG
```
U1 (E1 watchdog)            ─ python, isolated
U2 (E2+E3 classifier)       ─ both pkgs + golden; isolated, highest correctness value
U3 (E7 non-vacuous test)    ─ server test only
U4 (E5 deselect/auto-clear) ─ dashboard screen + rail
U5 (E6+E9+E10 dialog)       ─ dashboard screen + test
U6 (E4 re-scope D1)         ─ spec only (honesty)
U7 (E8 remove nonce)        ─ dashboard
U8 (E11 cardKind)           ─ dashboard + test
```
All leaves are independent. Order by severity: U1 → U2 → U3 → U4 → U5 → U6 → U7 → U8.
Each: failing test first, minimal fix, full suite, one commit.
