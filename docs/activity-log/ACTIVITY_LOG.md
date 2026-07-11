# ANDS / ADF — Activity Log

Durable, human-readable record of **every** activity on this repo: analysis,
decisions, code changes, test rounds. **Newest entry first.** Each entry traces
to a requirement/persona/gap, names the commit(s), and states the verification
outcome. Mandated by CLAUDE.md ("Maintain an activity log"). Read the top entries
before starting new work to understand what was done last.

Per-campaign logs (linked from entries):
- Regulatory persona + dosage-form swarm: [`persona-dosage-swarm-log.md`](persona-dosage-swarm-log.md)

---

## 2026-07-11 — Commit the v3.2.0 working tree (fleet rebuild + Proof-of-Build) + self-heal directive

**Trace:** user asks "commit the working tree changes with a sensible message"
and (earlier) the self-heal standing directive.

**Commits:**
- `e4a9b51` docs(claude): NEW standing self-heal directive (root-cause deep
  analysis → solution → implement → test → verify outcome, recursive) + the
  headroom_patch MUST-#0 rewrite that was uncommitted WIP on disk. (First cut
  `dd3eef7` swept the WIP in with a message that under-described it; caught via
  insertion-count mismatch and amended — commit was unpushed.)
- `5dfd96a` feat(v3.2.0): 210 files, +72,471/−1,451 — regenerated 10 sample
  apps, 5 NEW apps (countdown-2 Node/Vite, tip-calculator-2 Vite/TS,
  mobile-habit-tracker Expo, snake-ladder-games, url1), per-app Proof-of-Build
  artifacts (PROOF.md, .adf-proof*, .adf-policy-report, .adf-stack, .adf-process),
  Stop-hook mesh auto-heal REPOINTED to ~/ands-platform (old in-repo path was
  deleted at extraction; dev-up.sh verified idempotent — never kills), .gitignore
  runtime-junk classes (root *.db, err/srv logs, .coverage, app state JSONs).

**Verification:** staged-junk sweep clean (no .db/.log/.coverage/node_modules/
runtime JSONs staged); junk classes proven ignored via git check-ignore; tree
clean post-commit. App test suites not re-run here (committing existing WIP
as-is; the fleet's own PROOF artifacts record their build-time verification).


## 2026-07-10 — Session: process directives + journey traceability + next swarm round

### Entry 9 — Extract ANDS to its own repo `/Users/varunkumar/ands-platform`
- **What:** Moved `apps/ands-platform` OUT of the adf-framework monorepo into a
  standalone repo at `~/ands-platform` (sibling of `ai_pos_system`). Fresh git repo
  (user chose: fresh, not history-preserving). adf-framework commit **4a3521f** removed
  `apps/ands-platform` (693 files) + the 9 `ands-*` launch configs; new repo initial
  commit **e6f5b97** (+ launch.json 9e75a9a).
- **Why:** User: "remove all ands-platform code from ai_pos_system and put under a
  separate folder ands-platform parallel to ai_pos_system." ANDS is a distinct product
  from ADF Studio (the builder) — clean separation.
- **Safety:** Copied via `git archive` (tracked files only, excludes .venv/node_modules/
  .next), **byte-verified** (checksum + 693=693 tracked-file parity) and committed at the
  new location BEFORE deleting here. Source also retained in adf-framework git history.
  Running mesh processes (:3000 + 8010-8018) left untouched per user — they restart from
  the new location. NOTE: this session stays rooted in adf-framework; ANDS work should now
  happen in a session rooted at `~/ands-platform`.
- **Verification:** new repo 694 tracked files, tree clean; adf-framework `apps/` has no
  `ands-*`; adf launch.json keeps only `adf-dashboard`; graph updated (742 files, 0 errors).

### Entry 8 — Re-target: swarm moves to the mesh (Entries 1,6 were on the wrong app)
- **What:** The regulatory work must run against the mesh, not the monolith. Re-running
  the persona + dosage-form swarm against `apps/ands-platform/services/*`
  (dossier/journey/validation/fees/readiness). Round-12's monolith probe is discarded.
- **Correction:** Entries 1 (REQ-075) and 6 (JRNY-REQ-001) were built into the now-deleted
  monolith — REQ-075 must be re-checked against the mesh's `ectd_validation.py` and added
  there only if genuinely missing; the journey endpoint was already a first-class mesh
  service (:8011), so no port needed. Memory `ands-microservices-rewrite` corrected.

### Entry 7 — Commit `73cce82` — REMOVE the stdlib monolith (apps/ands-submission-portal)
- **What:** Deleted `apps/ands-submission-portal/` (73 files), dropped the `ands-app`
  launch config, fixed two live references (ands-platform README dead link + dossier
  `pm_xml.py` comment). The mesh `apps/ands-platform` is the sole product.
- **Why:** User flagged that this session's changes went into the WRONG app (the
  monolith), which they had asked to remove (documented in memory 2026-07-01). Verified:
  monolith was NOT a runtime dependency of the mesh (only doc/comment refs).
- **Verification:** launch.json valid + `ands-app` gone; **:3000 mesh app still serving**;
  **mesh dossier suite still 719 passed** (unchanged before/after). Graph updated.
- **Remaining monolith footprint (flagged to user, NOT yet removed):** `specs/ands-submission-portal/`,
  `.adf/orchestration/features/ands-submission-portal/`, and orch scripts
  (`ands_expand_all.py`, `measure_efficiency.py`, `ands_campaign.sh`) that name it.

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
