# ANDS / ADF — Activity Log

Durable, human-readable record of **every** activity on this repo: analysis,
decisions, code changes, test rounds. **Newest entry first.** Each entry traces
to a requirement/persona/gap, names the commit(s), and states the verification
outcome. Mandated by CLAUDE.md ("Maintain an activity log"). Read the top entries
before starting new work to understand what was done last.

Per-campaign logs (linked from entries):
- Regulatory persona + dosage-form swarm: [`persona-dosage-swarm-log.md`](persona-dosage-swarm-log.md)

---

## 2026-07-10 — Session: process directives + journey traceability + next swarm round

### Entry 6 — Commit `da1d564` — JRNY-REQ-001: journey spine as GET /api/journey/{id}
- **What:** Closed the "journey.py gap". `journey.py` is now a tracked, tested
  domain module (was untracked scratch). `server.py`: new `GET /api/journey/{id}`
  (tenant session + 'dashboard' gate; returns stages done/current/locked+reason +
  Resume position + folded-in REQ-071 readiness card; 404 for unknown/non-numeric/
  cross-tenant ids; `?today=` anchors the countdown). `_handle_tenant_submission`
  now carries company_id/sequence/applicant/oriented/reviews so the journey can
  advance past orientation. README: +endpoint row, modules 19→20.
- **Why:** JRNY-REQ-001 (MUST) — the gated journey must be served by the BFF, not
  buried in a module. User asked to test current code, confirm the requirement,
  and TDD it.
- **Verification (TDD):** 11 `journey.py` domain tests + 8 endpoint tests. Proved
  RED (endpoint 404) → implemented → GREEN. **Full suite 693 passed** (was 675).
  Adversarial review: route ordering, id-parse crash-safety, tenant isolation,
  backward-compat of the POST change — all checked.

### Entry 5 — CLAUDE.md: activity-log + pre-commit-recheck directives
- **What:** Added two standing directives to `CLAUDE.md`: (1) maintain this
  activity log, one entry per activity, updated after every commit; (2) always
  re-check the full current code/state (`git status`/`diff`/`log` + re-read files
  + re-run tests) before every commit, since a network error can leave a prior
  step half-landed. Verified both landed (CLAUDE.md L108, L121) after the user
  re-sent the pre-commit directive — the check confirmed the edit was already in
  place, so no double-apply. Committed with this log update.
- **Why:** User instruction (2026-07-10), flagged "very important".
- **Verification:** grep-confirmed in CLAUDE.md before commit.

### Entry 4 — Requirement traceability for journey.py → found JRNY-REQ-001 gap
- **What:** Traced the recently-touched portal code to requirements in
  [`docs/ands-portal/ANDS-PLATFORM-LAYERED-REQUIREMENTS.md`](../ands-portal/ANDS-PLATFORM-LAYERED-REQUIREMENTS.md).
  Findings: `readiness.py`=REQ-071 (shipped, tested); REQ-075 rules R06/B07b
  (shipped this session, tested); **`journey.py`=REQ-073 / JRNY-REQ-001 (MUST) is
  a GAP** — the doc itself tags it "journey.py gap": the gated 11-stage journey
  spine exists as a pure module but is NOT served as `GET /api/journey/{id}`
  (stages+position+readiness), and has **zero tests**.
- **Why:** User asked to test current code, find why it was written, confirm a
  requirement existed, and TDD it.
- **Decision:** TDD the journey spine — (1) characterize `journey.py` with domain
  tests, (2) implement `GET /api/journey/{id}` (RED→GREEN), (3) carry
  company_id/oriented/sequence/applicant/reviews through the submission POST so
  the journey can actually progress. Tasks #1–#3.
- **Verification:** Analysis only; implementation tracked below / in tasks.

### Entry 3 — Commit `fee959e` — gitignore portal artifacts
- **What:** `apps/ands-submission-portal/.gitignore` now ignores `data/`,
  `.coverage`, `__pycache__`.
- **Verification:** `git status` clean of the artifacts afterward.

### Entry 2 — Commit `8f25601` — production deploy scaffold + 0.0.0.0 host binding
- **What:** Railway (`railway.toml`→`production/Dockerfile.monolith`, ships the
  stdlib `server.py` monolith) + Render (`production/render.yaml`, FastAPI backend
  rewrite + worker + Postgres) + Next.js frontend scaffold; `server.py __main__`
  honours `HOST` (default 127.0.0.1) for container `0.0.0.0:PORT` binding.
- **Why:** Make the ANDS portal cloud-deployable (was uncommitted Jul-6 work).
- **Verification:** 39 source files; `node_modules`/`.next` excluded via nested
  `.gitignore`; `.env.example` placeholders only (no secrets); full suite 675
  passed. Knowledge graph updated to HEAD.

### Entry 1 — Commits `8141d22` (REQ-075) + `ee394a3` (README)
- **What:** REQ-075 referential integrity — two ICH-backbone validation rules
  (min_version 5.3, Error): `R06` (orphaned file: stored file no backbone leaf
  references) and `B07b` (leaf recorded MD5 ≠ actual bytes hash). README doc
  catch-up for the already-shipped REQ-071 readiness module + Workspace API.
- **Why:** Complete + green uncommitted portal work found at session start (on top
  of committed swarm round-11 `b0581a3`).
- **Verification:** Dedicated tests (orphan-blocking, checksum mismatch,
  dir/artifact exemption, 5.2-vs-5.3 gating); full suite **675 passed**. Graph
  updated.
