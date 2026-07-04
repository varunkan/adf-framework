# Task-based evaluation — breaking the walkthrough ceiling

## Why (the round 5→8 plateau)

Eight rounds of the SSR **walkthrough** panel plateaued: mean normalized cell
0.404 → 0.396 → 0.397 (R5/R7/R8), 0/12 personas, and the 0.70 adoption bar was
never exceeded by any persona in any round (ceiling ~0.59). The mechanism is
structural, not a product defect:

1. **Honesty ↔ would-file trust.** The more honestly the tool states its limits
   (not the official eValidator, not certified, SSO on roadmap) — which personas
   *praise* — the more they withhold "I'd rely on this for a real filing" trust.
2. **Depth ↔ density.** Every content ask, once added, regresses clarity/ease
   elsewhere; adding content is ~zero-sum on the aggregate.
3. **A walkthrough can't earn "I'd adopt."** Adoption is an *experiential*
   judgment. Reading a description of a tool, a cautious professional will not say
   "I'd adopt" — they say "I'd have to try it and validate it myself." That is
   correct epistemics, and no amount of walkthrough polish overcomes it.

So the fix is not more walkthrough rounds — it is to let each synthetic persona
**actually perform a filing task** and rate the lived experience.

## The harness

**Faithful, in-process, no browser.** The mesh services expose real ASGI apps that
the test suite already drives with FastAPI `TestClient` (real routing + render,
SQLite + in-memory-bus adapters). We reuse that to run a REAL task and capture the
REAL request→response sequence — including real validation reports, real gates,
real error messages, real export blocks.

### 1. Trace generator (`usability_panel/task_eval/trace.py`)
Deterministically performs the canonical ANDS task end-to-end against the live
service apps and records each step as `{action, request, status, response_excerpt,
what_the_user_sees}`:

  signup/login → create dossier (placeholder ID) → open Module 1 → author/upload
  the required leaves → run eCTD validation (see the real report: rule IDs,
  pass/fail counts, criteria vX) → attempt export (see the real fail-closed block:
  placeholder-ID + any errors) → set the real Dossier ID → fix findings → re-validate
  → export the sequence → review/sign → simulated transmit (3-receipt chain).

The trace is the ground truth of *what actually happens when you do it* — the
antidote to a static description. Cached to `task_eval/traces/<task>.json`.

### 2. Task-eval panel (`task_eval/run_task_panel.js` Workflow)
Each of the 12 personas is given: their persona card, the TASK GOAL, and the real
interaction trace, and is asked to imagine performing it hands-on — narrate the
experience step by step (where they sailed through, where they hit friction, where
a real response reassured or worried them) — then rate **ease / clarity / trust /
adoption** on the lived experience, not a description. Same SSR scoring
(`panel/ssr.py`) so scores stay comparable in method, incomparable in tag.

### 3. Multiple tasks (coverage)
- T1 first-ANDS happy path (newcomer lens)
- T2 validation-fail → fix → export (the trust-critical loop)
- T3 multi-client CRO isolation (create two workspaces, prove no cross-read)
- T4 deficiency response + lifecycle sequence 0001 (expert lens)

## Gate re-examination (front #4)

The absolute bars (cell ≥ 0.55, adoption ≥ 0.70) were calibrated on the
walkthrough method. Two honest positions, to decide WITH the task-eval evidence:

- **Keep the bars, change the method.** If the bars are the right *destination*,
  the walkthrough was the wrong *vehicle* — a task-eval is the fair test of whether
  the product can reach them. Re-run the bars against task-eval scores.
- **Adoption needs a task-eval-native anchor set.** The current adoption anchors
  ("we are buying this", "I'd replace our tools immediately") are procurement
  verbs a single hands-on session can't trigger. A task-eval-appropriate adoption
  construct = "having done this, I would pilot/trial this on a real file" — a
  reachable, still-honest bar. Rebuild `panel/anchors.py` adoption anchors for the
  task context (NOT gaming — matching the anchor to what the method can measure).

Decision rule: run T1+T2 task-eval, compare adoption vs the walkthrough ceiling.
If task-eval adoption rises materially (personas who "did it" would trial it), the
walkthrough was the ceiling and we proceed on the task-eval. If it stays flat,
the gap is a real product/trust gap and we keep grinding the product.

## Honesty guardrail
The trace must be REAL (generated from the running code, never hand-authored to
flatter). If a step fails or blocks, the persona sees the real failure. The whole
point is to measure the true experience, not a marketing reel.
