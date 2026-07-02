# ANDS Studio → 100% synthetic-customer satisfaction plan

Goal (user mandate): every synthetic customer satisfied; one-stop shop for
Canadian ANDS regulatory submissions; the most advanced, error-free
submission system available.

## The measurement loop (how "100%" is defined and proven)

Panel: `usability_panel/` — SSR method (arXiv:2510.08338), 12 regulatory
personas × 8 grounded UI-flow stimuli × 2 samples, constructs
ease / clarity / trust / adoption.

**Satisfaction criterion (all must hold):**
1. Every flow × construct cell mean ≥ 4.0/5
2. Bottom-2-box share ≤ 5% in every cell
3. Every individual persona: adoption ≥ 4.0 and no flow rated < 3.5
   ("100% of customers" = nobody left behind, not a good average)

Loop: run panel → rank findings → fix → re-transcribe changed flows →
re-run → compare tagged rounds (`before`, `round2`, …) until criterion holds.

## Layer 1 — Known friction (already visible in the grounded stimuli)

These are facts of the current UI, surfaced while transcribing it; the
panel will rank them, but they are near-certain complaints:

- **F1 Dossier ID burden**: users must already know the `e123456` format and
  hold a real ID. Fix: explain how a Dossier ID is obtained (REP), offer
  "I don't have one yet" path that files the request and uses a draft ID.
- **F2 Account recovery absent**: no forgot-password, no email verification,
  no stated password rules. Fix: add password rules + reset flow (dev-mode
  email simulation) + say so on the screen.
- **F3 Company ID prerequisite**: 5-digit HC Company ID needed mid-journey
  with only a mention of OSIP. Fix: inline "how to get one" guidance +
  accept "pending" state.
- **F4 Novice terminology wall**: personas with no RA background (founder,
  nutraceutical director) face ANDS/eCTD/REP/DIN jargon. Term tooltips
  exist but coverage is partial. Fix: complete Term coverage + a
  plain-language glossary panel + "what am I looking at" intro per module.
- **F5 AI trust provenance**: AI-drafted sections give no sources. The
  skeptic personas (30-yr veteran, QA manager, ex-HC reviewer) will not
  trust unattributed AI text. Fix: every generated/drafted document carries
  "how this was produced" + the HC guidance citations it followed + the
  new content-review findings panel run automatically.
- **F6 Audit/Part-11 visibility**: audit trail exists but its guarantees
  (who/when/what, immutability) aren't surfaced where QA looks. Fix: audit
  chip on every document + exportable audit report per dossier.
- **F7 Validation-rule identity**: publisher persona judges tools by HC
  validation-rule coverage. Fix: label every finding with its HC v5.3-style
  rule ID + link, show the rule catalogue, state coverage explicitly.
- **F8 Bilingual/PM reality**: labelling persona lives in EN+FR and XML PM.
  Fix: surface bilingual state per document, PM XML build/validate flow
  from the section UI (exists — make it discoverable + French toggle).
- **F9 PM visibility**: project-manager persona needs status: per-dossier
  % ready, blockers, deadlines, client-facing export. Portfolio exists —
  add deadline/NOA clocks + a printable client status report.
- **F10 Multi-client cost/isolation**: CDMO persona: tenant isolation is
  real but silent. Fix: state the isolation model in-product; per-client
  workspace switcher affordance.

## Layer 2 — One-stop completeness (regulatory scope)

Built already (keep hardening): guided journey, dossier/eCTD engine 3.2.2 +
CA M1 2.2, sample-prefilled forms + HC content review with canada.ca
citations, LLM drafting, validation, fees incl. small-business, review +
e-sign, simulated CESG transmission with receipts, export with checksums,
sequences 0001+, Form V + NOA register, registry/DIN + annual notification +
Right-to-Sell, post-NOC changes, correspondence hub, portfolio, audit,
multi-tenant auth.

Remaining for "one-stop" honesty and depth:
- **S1** Pre-submission phase: pre-ANDS meeting request package + minutes
  capture; reference-product selection rationale (CRP) helper.
- **S2** REP end-to-end surface: CO/DossierID/RT XML as first-class
  artifacts with their own screen (they exist inside export today).
- **S3** Post-filing lifecycle depth: SDN/NOD/Clarifax response builder UX
  from the correspondence hub (wired to response sequences).
- **S4** Post-NOC obligations calendar: annual notification, Right-to-Sell,
  shortage tiers, PSUR-C on request — one deadlines calendar feeding
  portfolio.
- **S5** Real-gateway honesty: document the CESG/WebTrader step and produce
  the exact transmissible package; never claim fake connectivity.
- **S6** Knowledge base: in-app HC guidance library (the links the review
  engine already cites) + contextual "read the rule" everywhere.

## Layer 3 — Error-free discipline

- **E1** Every service suite green on every commit (current: 263 dossier +
  520+ platform tests).
- **E2** tsc clean; zero browser console errors on every flow (verified via
  automated UI sweep).
- **E3** Panel regression: re-run affected flows each round; a fix that
  lowers any cell is reverted/reworked.
- **E4** Durability: all state in per-service SQLite/Postgres (restart-proof,
  proven); dev-up idempotent bring-up; backup script.

## Execution order

Round 1 (now): panel baseline → rank Layer-1 items by measured pain →
implement the top items wholesale → re-run → publish before/after.
Round 2+: repeat; fold in Layer-2 items as personas demand them (their
feedback texts tell us); stop only at the criterion above.
