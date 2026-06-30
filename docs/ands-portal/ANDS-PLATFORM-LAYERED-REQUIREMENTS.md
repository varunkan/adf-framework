# ANDS Platform — Layered Requirements Specification

**Document:** `ANDS-PLATFORM-LAYERED-REQUIREMENTS.md`  
**Version:** 1.0  
**Date:** 2026-06-27  
**Status:** Authoritative product spec (engineering + UX + security)  
**Supersedes depth:** Extends [`VISION-GAP-REQUIREMENTS.md`](VISION-GAP-REQUIREMENTS.md) v2.0 and [`COMPETITIVE-REQUIREMENTS-INVENTORY.md`](COMPETITIVE-REQUIREMENTS-INVENTORY.md)  
**Spec Kit implementation spec:** [`specs/ands-submission-platform/spec.md`](../../../specs/ands-submission-platform/spec.md)

---

## 0. Purpose and reading guide

This document decomposes **every competitive and regulatory requirement** into implementable layers:

| Layer | ID prefix | Count (target) |
|-------|-----------|----------------|
| UI / UX | `UI-REQ-*` | 65 |
| REST / async API | `API-REQ-*` | 55 |
| Database & persistence | `DB-REQ-*` | 40 |
| Document management | `DM-REQ-*` | 45 |
| Performance & scale | `PERF-REQ-*` | 25 |
| Security & compliance | `SEC-REQ-*` | 35 |
| UI ↔ API integration | `INT-REQ-*` | 30 |
| World-best / state-of-art | `BEST-REQ-*` | 20 |

**Requirement record format:**

```
ID | Priority (MUST/SHOULD/COULD) | Statement | Acceptance criteria | Vendor benchmark | Traces (REQ/COMP)
```

**Design north star:** *Super easy for a first-time ANDS filer; state-of-art for a 50-person RA org — same product, progressive disclosure.*

---

## 1. Vendor re-review by architectural layer

Second-pass loop: map **what each leader actually ships** at UI, API, data, docs, perf, security layers.

| Vendor | UI strength | API / integration | Data model | Doc mgmt | Perf | Security |
|--------|-------------|-------------------|------------|----------|------|----------|
| **LORENZ docuBridge** | TOC editor, Application Viewer, Node Content Pane | Automator hooks; limited public REST | Project/sequence store; local or cloud | Import eCTD; multi-format publish | Batch validate server | Part 11; on-prem option |
| **LORENZ eValidator FIVE** | webAccess browser UI | Batch job API (enterprise) | Validation job store | PDF reports | Server-side batch | Agency-trusted profiles |
| **Veeva Vault RIM** | Content plans, continuous publish UI, Archive viewer | **Vault REST** (OAuth, VQL, eCTD mapping API) | Unified RIM object model | Vault Docs + staging import | Cloud scale | Enterprise SSO, SOC |
| **Certara GlobalSubmit** | Live validation gutter, CrossCheck QC | eDMS connectors | Central submission workspace | PDF auto-process | Live validation perf | Part 11 + CSV packs |
| **EXTEDO eCTDmanager** | Visual assembly, no-XML UX | DMS connectors (SharePoint, Vault, Documentum) | Dossier DB | Incremental publish | Parallel builds | 35+ agency validator |
| **Ennov / eCTD 247** | Metadata nav, drag-drop EDM | Cloud API (limited public) | DIA EDM model + dossier | Built-in EDMS Premium | Cloud elastic | Part 11, ISO 9001 |
| **Phlexglobal** | CRO client portal | ML intake pipeline | Multi-sponsor | PhlexNeuron structuring | Automation throughput | Secure share |
| **Assyro AI** | Decision-tree validation UI, co-author | Regulatory change feeds | Validation graph store | AI-assisted authoring | Real-time validate | Explainable audit |
| **Freyr SUBMIT PRO** | Pro dashboard, clone workflows | DMS integrations | Submission metadata | Built-in viewer/validator | Dashboard analytics | Audit-ready tracking |
| **FDA ESG NextGen USP** | Guided transmit wizard, ack tracker | **API credentials** in USP | Submission status store | Secure upload | 10 GB guidance | **MFA required** |
| **HC (regulatory)** | N/A | CESG via ESG only | DSTS lifecycle | eCTD + non-eCTD | 10 GB ceiling | No sponsor residency mandate |

**Layer coverage gap (us vs world-class today):**

| Layer | Industry MUST count | Us today | Target Ph 3 |
|-------|---------------------|----------|-------------|
| UI | 42 | 12 partial | 38 |
| API | 28 | 8 partial | 26 |
| DB | 22 | 5 partial | 20 |
| DM | 30 | 6 partial | 28 |
| PERF | 18 | 2 partial | 16 |
| SEC | 24 | 7 partial | 22 |
| INT | 20 | 4 partial | 18 |

---

## 2. UI / UX requirements (`UI-REQ`)

*Benchmark: Veeva content plans, LORENZ TOC editor, Certara live gutter, ESG USP guided transmit, NDIR guided lifecycle UX.*

### 2.1 Onboarding & shell

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| UI-REQ-001 | MUST | **Single workspace shell** — one left nav, breadcrumbs, no module hopping | All REQ-085 routes render in one shell without full page reload to legacy `/` | Veeva unified RIM |
| UI-REQ-002 | MUST | **First-run wizard** — company → dossier ID → first sequence in ≤5 screens | New user completes wizard without docs; skip paths for reuse dossier | ESG USP guided |
| UI-REQ-003 | MUST | **Role-based home** — RA Author, QC, Publisher, Approver, Admin see tailored dashboards | Role switch changes visible widgets and actions | Ennov dashboards |
| UI-REQ-004 | SHOULD | **Sandbox mode** banner — clear “Training / not for Production transmit” | Sandbox tenant UI distinct color + no Production transmit button | SaaS best practice |
| UI-REQ-005 | MUST | **WCAG 2.1 AA** — keyboard nav, focus order, contrast, aria labels on tree and stepper | Automated axe scan zero critical on core flows | SEC/accessibility |
| UI-REQ-006 | SHOULD | **Responsive status views** — transmission/lifecycle readable on tablet/phone | Authoring desktop-only; status pages responsive | Mobile-safe status |

### 2.2 Guided ANDS journey (super easy)

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| UI-REQ-010 | MUST | **Persistent stepper** on `/submit` — Enrolment → Dossier → Validate → Fees → Review → Transmit → Lifecycle | Each step shows complete/locked/blocked with one-line reason | Our REQ-073 |
| UI-REQ-011 | MUST | **One primary CTA per screen** — “Do this next” button always visible above fold | No screen with >3 equal-weight primary buttons | NDIR guided UX |
| UI-REQ-012 | MUST | **Plain-language labels** — HC jargon expandable via “What is this?” tooltips | Every form field links to HC source tooltip | Compliance UX |
| UI-REQ-013 | MUST | **READY / BLOCKED dashboard** — traffic-light cards + drill-in to blocking items | Matches readiness.py tiles; zero placeholder pages | BEST differentiator |
| UI-REQ-014 | MUST | **Empty states with recipes** — “Start ANDS” loads template checklist not blank tree | First dossier offers ANDS content model preset | Freyr templates |
| UI-REQ-015 | SHOULD | **Progress %** on content plan and Module 1 checklist | Derived from leaf fill ratio + validation pass | Veeva SCP |

### 2.3 eCTD tree & authoring

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| UI-REQ-020 | MUST | **Split-pane TOC editor** — tree left, preview/properties right | Drag-drop upload to selected leaf | LORENZ, DnXT Publisher |
| UI-REQ-021 | MUST | **Inline validation gutter** on selected leaf — errors/warnings with fix links | Updates within 3s of change (see PERF) | Certara live |
| UI-REQ-022 | MUST | **Lifecycle operation picker** — new/replace/delete/append with HC semantics | Illegal ops disabled with explanation | docuBridge |
| UI-REQ-023 | SHOULD | **Current view vs sequence view** toggle | Shows cumulative dossier state | eCTD standard |
| UI-REQ-024 | SHOULD | **Deep-linkable leaves** — URL opens tree focused on leaf | Share link opens same node for QC | Collaboration |
| UI-REQ-025 | MUST | **Module 1 placement hints** — ghost nodes for required-but-empty HC sections | Placement table drives ghosts | HC table |
| UI-REQ-026 | SHOULD | **Bulk upload** — multi-file drop with auto-suggest leaf from filename/metadata | User confirms mapping table | Ennov AI classify |
| UI-REQ-027 | SHOULD | **CrossCheck mode** — split PDF viewer + hyperlink destination preview | Side-by-side panes sync scroll | Certara CrossCheck |
| UI-REQ-028 | MUST | **Application Viewer** post-publish — Files + Outline tabs | Read-only; export PDF report | LORENZ v25 |

### 2.4 Canada ANDS-specific UI

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| UI-REQ-030 | MUST | **Bilingual PM panel** — EN + FR side-by-side with sync scroll optional | Missing FR blocks READY | HC PM guidance |
| UI-REQ-031 | MUST | **Forms wizard** — Certification + ANDS Attestation + SANDS as step forms | PDF/XML output to correct leaves | COMP-CA |
| UI-REQ-032 | SHOULD | **CRP builder UI** — structured fields + foreign CRP path | Live equivalence check messages | REQ-007 |
| UI-REQ-033 | SHOULD | **CS-BE / QOS-CE builders** — sectioned forms not raw XML | Draft banner on CS-BE | REQ-008/061 |
| UI-REQ-034 | SHOULD | **Fee calculator widget** — shows amount, remission, 25% credit eligibility | Links to REQ-035–037 | Ennov/Freyr |
| UI-REQ-035 | SHOULD | **XML PM preview** — render + rule violations list | When XML PM required | REQ-099 |

### 2.5 Collaboration & workflow UI

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| UI-REQ-040 | MUST | **Comments thread** per leaf and per validation finding | @mention notifies assignee | Veeva |
| UI-REQ-041 | MUST | **Task inbox** — My Tasks, Needs Attention, Pending Approval | Dashboard Tasks tab like DnXT | DnXT Publisher |
| UI-REQ-042 | MUST | **Approval queue** — diff summary before e-sign | Four-eyes on transmit | REQ-076 |
| UI-REQ-043 | SHOULD | **Activity feed** — dossier timeline (upload, validate, publish, transmit, ack) | Filter by user/action | Audit UX |
| UI-REQ-044 | SHOULD | **Client portal view** (CRO) — sponsor read-only + comment | Scoped to one sponsor | Phlexglobal |
| UI-REQ-045 | SHOULD | **Notifications center** — in-app + email prefs | User configures channels | SaaS standard |

### 2.6 Transmission & lifecycle UI

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| UI-REQ-050 | MUST | **Transmission console** — state diagram MDN → FDA Ack → HC Ack | Core ID prominent | REQ-028 |
| UI-REQ-051 | MUST | **Test vs Production** toggle with visual guardrails | Production requires MFA + entitlement | ESG USP |
| UI-REQ-052 | MUST | **One-at-a-time queue** per dossier — next sequence locked until HC ack | Shows queued sequences | REQ-027 |
| UI-REQ-053 | SHOULD | **Physical media wizard** — USB/HDD package + shipping checklist | >10 GB path | REQ-058 |
| UI-REQ-054 | SHOULD | **Lifecycle timeline** — screening/review/clarifax/NOC | Clock-stop events editable per HC guidance | REQ-030 |
| UI-REQ-055 | SHOULD | **Rejection ingest UI** — upload HC validation PDF → mapped defects on tree | Core ID lookup | REQ-029 |

### 2.7 Admin, owner & billing UI

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| UI-REQ-060 | MUST | **Owner console** — tenants, plans, entitlements, suspend | REQ-077–084 | Our code |
| UI-REQ-061 | MUST | **Billing self-serve** — plan, usage, invoices, upgrade | Stripe customer portal embed | eCTD 247 |
| UI-REQ-062 | MUST | **ESG credentials UI** — upload cert, test connection, never show private key again | Masked thumbprint only | ESG USP |
| UI-REQ-063 | SHOULD | **Team admin** — invite users, assign roles, MFA enforce | SSO config for Enterprise | Veeva |
| UI-REQ-064 | SHOULD | **Usage meters** — sequences published, storage GB, validation minutes | Visible on billing page | SaaS transparency |

### 2.8 Analytics & intelligence UI

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| UI-REQ-070 | SHOULD | **Intelligence tab** — portfolio cycle time, screening pass rate, backlog | DnXT Intelligence tab | DnXT |
| UI-REQ-071 | SHOULD | **Validator parity score** — % match vs golden eValidator run | Shown per dossier pre-transmit | G-P3-01 |
| UI-REQ-072 | COULD | **Regulatory change feed** — HC notices affecting active dossiers | Dismiss/snooze/link | Assyro |

### 2.9 Guided story experience & Prism-3D spatial UI (`JRNY-REQ`)

> The "never-before, next-level" guided filing experience (approved plan
> `fizzy-bouncing-rose`): a story-driven, Prism-3D-spatial walk that lets even a
> **non-regulatory** person file a real ANDS and make informed decisions. Grounded
> in live Health Canada research (eCTD/Module-1, screening→review→NOC/NOD/NON,
> ANDS/bioequivalence & the Canadian Reference Product, the Fees Order, and
> CESG-rides-on-FDA-ESG). Backed by the **journey BFF** service (`/api/journey/*`).

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| JRNY-REQ-001 | MUST | **Journey spine as an API** — the gated 11-stage journey is served by the BFF, not buried in a module | `GET /api/journey/{id}` returns stages (done/current/locked+reason) + position + readiness | journey.py gap |
| JRNY-REQ-002 | MUST | **"Tell me about your drug" intake** — a branching conversation captures submission type + generic/reference picture and routes the pathway | `POST /api/journey/intake` returns route + advisories; a new-indication ANDS is steered to NDS/SNDS | route_submission_type |
| JRNY-REQ-003 | MUST | **Branch early & honestly** — pharmaceutical-equivalence + ICH-M13A/legacy bioequivalence pre-checks run up front | Non-equivalent generic / failed BE flagged before content build; `eligible_ands=false` | REQ-007/008/063 |
| JRNY-REQ-004 | MUST | **Story over form** — every step leads with a plain-language "what this is & why" before any field | Each step renders purpose/teaches copy above inputs | HC research |
| JRNY-REQ-005 | MUST | **Spatial submission view** — the eCTD shown as a Module 1–5 "tower"; placing a document is a visible spatial act, slots light green/amber/red | WebGL tower reacts to readiness tiles; whole tower glows READY when nothing blocks | Plan centerpiece |
| JRNY-REQ-006 | MUST | **Reduced-motion / no-WebGL fallback** — the spatial view degrades to a 2D Prism version | `prefers-reduced-motion` and WebGL-absent both render an accessible 2D tower; axe zero-critical | UI-REQ-005 |
| JRNY-REQ-007 | MUST | **Persistent READY/BLOCKED card** — plain-language blocking items + one-click Resume to the current step | Card matches readiness_card tiles; Resume deep-links the current stage | UI-REQ-013 |
| JRNY-REQ-008 | MUST | **One primary CTA + "Next: <step>"** — a single advancing action per step with a visible next-pointer | Advancing a step returns the next stage label/route | UI-REQ-011 |
| JRNY-REQ-009 | MUST | **Save & resume** — a guided session persists; the user returns to exactly where they were | Session reload restores position + collected answers | Plan decision 4 |
| JRNY-REQ-010 | MUST | **Dossier-ID guidance** — `e123456` format check + the 8-week MAX lead time as a warn-only (never a gate) | `POST /api/journey/dossier-id/assess` returns format_ok + lead_time.too_early (warn only) | REQ-002 |
| JRNY-REQ-011 | MUST | **Advisories warn, prerequisites gate, fees never hard-coded** — only true prerequisites block; fee figures render the current fiscal year | 8-week lead & fee currency are warn-only; the live fee is shown, not a static number | HC Fees Order |
| JRNY-REQ-012 | MUST | **CESG-rides-on-FDA-ESG teaching** — the transmit step teaches FDA-ESG registration, certificate/lead-time failure modes, WebTrader vs AS2, "select HC" | Transmit step surfaces the gateway-redirect explanation + cert-expiry branch | HC research gap |
| JRNY-REQ-013 | MUST | **Three-receipt chain explicit** — FDA-MDN → FDA-ACK → **HC-ACK (Core ID)**; only the HC ACK proves receipt | Transmit/track UI shows the 3-receipt chain and "don't stop at the FDA ACK" | HC research gap |
| JRNY-REQ-014 | SHOULD | **Size & sequencing branches** — >10 GB → physical media; 5–10 GB → after-4:30-PM-EST; one transaction at a time (await ACK) | Transmit step branches on size; holds the next send until the prior ACK | HC research gap |
| JRNY-REQ-015 | MUST | **Small-business status BEFORE filing** — capture whether status is granted; warn that filing first forfeits the remission/first-submission waiver (affiliate threshold) | Fees step asks "granted yet?" and warns if not | Fees Order SOR/2019-124 |
| JRNY-REQ-016 | MUST | **Bilingual PM completeness gate** — English + French PM with Grade 6–8 Patient Medication Information tied to the checklist | Content step gates on a bilingual-PM completeness signal | REQ-099/100 |
| JRNY-REQ-017 | SHOULD | **Foreign-CRP justification branch** — when the CRP can't be bought in Canada, collect the justification + bridging data | Intake branches to a justification record when `foreign` CRP | REQ-007 (c) |
| JRNY-REQ-018 | SHOULD | **ANDS Sponsor Attestation Checklist flag** — requested from HC by email, not on the public forms page | Review/sign step flags it so it isn't discovered missing at screening | HC research gap |
| JRNY-REQ-019 | SHOULD | **Calm the timeline** — track shows that target review days count only HC's time & pause while they wait on you; every response deadline is a visible timer (+ pause-the-clock) | Track step renders SDN/clarifax/NOD/NON timers + the 2-day screening clarification / SRL teaching | REQ-030/031/062 |
| JRNY-REQ-020 | COULD | **Pre-submission meeting step** — an optional early "de-risk the filing" branch (recommended 3+ months ahead) | Orient/your-drug offers an optional pre-submission-meeting checkpoint | HC research gap |

---

## 3. API requirements (`API-REQ`)

*Benchmark: Veeva Vault REST, OpenAPI-first SaaS, ESG API credentials, webhook-driven automation.*

### 3.1 Platform API foundation

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| API-REQ-001 | MUST | **OpenAPI 3.1** spec published at `/api/openapi.json` + Redoc/Swagger UI | Versioned; breaking changes bump major | Modern SaaS |
| API-REQ-002 | MUST | **API versioning** — `/api/v1/` prefix; deprecation headers | 12-month deprecation window | Stripe-style |
| API-REQ-003 | MUST | **Tenant scoping** — every resource under `/api/v1/tenants/{tenant_id}/...` or JWT tenant claim | Cross-tenant calls impossible | Multi-tenant |
| API-REQ-004 | MUST | **Idempotency-Key** header on POST mutate (publish, transmit, pay) | Replay returns same result | SaaS best practice |
| API-REQ-005 | MUST | **Cursor pagination** — `?cursor=&limit=` on all lists | Stable sort by created_at,id | Performance |
| API-REQ-006 | MUST | **Problem Details (RFC 9457)** error format with `rule_id` for validation errors | Client maps to UI gutter | Developer UX |
| API-REQ-007 | MUST | **Rate limits** — 429 + Retry-After; tier-based quotas | Documented per plan | SEC |
| API-REQ-008 | SHOULD | **Bulk operations** — batch validate, batch export | Async job IDs returned | eValidator batch |

### 3.2 Auth API

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| API-REQ-010 | MUST | `POST /auth/signup`, `/login`, `/logout`, `/refresh` | Cookie + Bearer modes | REQ-077 |
| API-REQ-011 | MUST | `POST /auth/mfa/enroll`, `/mfa/verify` — TOTP/WebAuthn | Required before Production transmit | ESG USP |
| API-REQ-012 | SHOULD | **OIDC/SAML SSO** — Enterprise tenant config | Okta/Azure AD tested | Veeva |
| API-REQ-013 | MUST | **API keys** — service accounts with scoped permissions | Rotate without downtime | SaaS |
| API-REQ-014 | SHOULD | **OAuth2 client credentials** for CRO integrations | Machine-to-machine | Vault pattern |

### 3.3 Domain resource APIs (core)

| ID | Pri | Requirement | Acceptance | Traces |
|----|-----|-------------|------------|--------|
| API-REQ-020 | MUST | **Dossiers CRUD** + nested sequences | OpenAPI documented | ectd |
| API-REQ-021 | MUST | **Leaves** — add/replace/delete, upload URL presign | Multipart or S3 presign | DM |
| API-REQ-022 | MUST | **Validation** — `POST .../validate` (inline), `.../validate/report` | Returns errors+warnings+fixes | REQ-022–024 |
| API-REQ-023 | MUST | **Publish** — `POST .../publish` → async job | Job status poll | REQ-090 |
| API-REQ-024 | MUST | **Package download** — signed URL for eCTD zip | Checksum in response | REQ-090 |
| API-REQ-025 | MUST | **Transmission** — configure, test-round-trip, submit, ack poll | ESG adapter behind | REQ-087 |
| API-REQ-026 | MUST | **Readiness** — `GET .../dashboard` aggregates tiles | Matches UI-REQ-013 | REQ-071 |
| API-REQ-027 | MUST | **Intake** — validate + create submission | REQ-001 domain | domain |
| API-REQ-028 | MUST | **REP** — CO/RT/PI generate, identifier validate | Immutable filenames | REQ-001/006 |
| API-REQ-029 | MUST | **Content plans** — CRUD tasks, checklist items | Links to leaves | REQ-103 |
| API-REQ-030 | SHOULD | **Import eCTD** — `POST .../import` multipart zip | Reconstruct tree | REQ-106 |
| API-REQ-031 | SHOULD | **Correspondence** — upload HC notice, link lifecycle | REQ-112 | lifecycle |
| API-REQ-032 | SHOULD | **Registrations** — product×country×DIN | REQ-111 | RIM |
| API-REQ-033 | MUST | **Audit** — `GET .../audit?from=&to=` export CSV/JSON | Append-only | REQ-060 |
| API-REQ-034 | SHOULD | **Comments/tasks** — CRUD with assignee | REQ-109 | collaboration |
| API-REQ-035 | MUST | **Owner** — tenants, plans, entitlements | REQ-080–082 | auth |

### 3.4 Async jobs API

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| API-REQ-040 | MUST | `POST /jobs` types: `publish`, `validate_batch`, `pdf_remediate`, `package_transmit`, `import_ectd` | Returns `job_id` | Worker pattern |
| API-REQ-041 | MUST | `GET /jobs/{id}` — status, progress %, result, error | WebSocket optional upgrade | SaaS |
| API-REQ-042 | SHOULD | `DELETE /jobs/{id}` — cancel in-flight | Graceful worker cancel | UX |
| API-REQ-043 | MUST | Job events include **checksum** of outputs | Verify on download | Integrity |

### 3.5 Webhooks & events

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| API-REQ-050 | MUST | **Webhooks** — register URL + secret; HMAC-SHA256 signature | Retry 3x exponential backoff | Stripe |
| API-REQ-051 | MUST | Events: `sequence.published`, `validation.completed`, `transmission.sent`, `transmission.hc_ack`, `task.assigned`, `tenant.plan_changed` | Documented payload schemas | SAAS-REQ-011 |
| API-REQ-052 | SHOULD | **Event log API** — replay for integrators | 30-day retention | Enterprise |

### 3.6 Integrator APIs (external systems)

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| API-REQ-060 | SHOULD | **DMS sync** — `POST /connectors/{type}/sync` SharePoint, Documentum, Vault | Maps to content plan items | EXTEDO |
| API-REQ-061 | SHOULD | **Metadata mapping API** — like Vault `ectdmapping` | XML leaf ↔ product objects | Veeva API |
| API-REQ-062 | COULD | **Outbound to LORENZ/EXTEDO** export format | Hybrid customer path | COMP-INT-007 |
| API-REQ-063 | MUST | **Billing webhooks** — Stripe → entitlements | SAAS-REQ-002 | Stripe |

### 3.7 ESG adapter internal API (service boundary)

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| API-REQ-070 | MUST | Internal `EsgService.submit(package_id, env)` | Isolated network egress | ESG NextGen |
| API-REQ-071 | MUST | Internal `AckIngestion.poll()` + `AckIngestion.ingest(payload)` | Idempotent Core ID | REQ-088 |
| API-REQ-072 | MUST | Secrets from vault only — never env plaintext in prod | KMS envelope | SEC |

---

## 4. Database requirements (`DB-REQ`)

*Benchmark: Veeva unified object model, tenant isolation, audit immutability, job queue durability.*

### 4.1 Architecture

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| DB-REQ-001 | MUST | **PostgreSQL 15+** primary store production; SQLite dev-only | REQ-091 | Production stack |
| DB-REQ-002 | MUST | **Control plane DB** separate from **tenant data** (schema or database) | Platform owner data isolated | REQ-078 |
| DB-REQ-003 | MUST | **Row-level tenant_id** on every tenant table + enforced in repository layer | Zero cross-tenant queries in tests | NFR-015 |
| DB-REQ-004 | MUST | **Migrations** — Alembic/Flyway; backward-compatible expand-only in prod | Rollback plan documented | SaaS |
| DB-REQ-005 | SHOULD | **Read replicas** for reporting/analytics | Lag <30s acceptable | Scale |

### 4.2 Core entities (logical model)

| Entity | Key fields | Traces |
|--------|------------|--------|
| `tenants` | id, plan_id, status, residency_region | REQ-077 |
| `users` | id, tenant_id, role, mfa_enabled | REQ-038 |
| `dossiers` | id, tenant_id, dossier_id, product_name, activity_type | REQ-002 |
| `sequences` | id, dossier_id, number, lifecycle_state, published_at | REQ-016 |
| `leaves` | id, sequence_id, leaf_id, path, checksum, operation | REQ-017 |
| `documents` | id, leaf_id, s3_key, version, mime, size_bytes | DM |
| `validation_runs` | id, sequence_id, ruleset_version, blocking, report_json | REQ-022 |
| `publish_jobs` | id, sequence_id, status, artifact_s3_key | REQ-090 |
| `transmissions` | id, sequence_id, core_id, message_id, state, env | REQ-028 |
| `content_plans` | id, dossier_id, template_type, progress | REQ-103 |
| `tasks` | id, assignee_id, due_at, status, ref_type, ref_id | REQ-109 |
| `comments` | id, thread_id, body, author_id | UI-REQ-040 |
| `audit_events` | id, actor, action, before, after, immutable | REQ-060 |
| `registrations` | id, product_id, country, din, status | REQ-111 |
| `correspondence` | id, dossier_id, notice_type, received_at | REQ-112 |
| `artifact_registry` | id, type, version, sha256, effective_date | REQ-089 |

### 4.3 Database non-functional

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| DB-REQ-010 | MUST | **Optimistic locking** — `version` column on dossier/sequence/leaf | REQ-057 conflict 409 | Veeva |
| DB-REQ-011 | MUST | **Sequence number assignment** — DB serial or advisory lock per dossier | No duplicate seq nums | REQ-057 |
| DB-REQ-012 | MUST | **Append-only audit** — no UPDATE/DELETE on audit_events | REQ-060 | Part 11 |
| DB-REQ-013 | MUST | **Soft delete** dossiers with retention hold flag | REQ-054 | Retention |
| DB-REQ-014 | SHOULD | **Full-text search** on leaf titles, comments, task titles (PG tsvector) | UI-REQ metadata nav | Ennov |
| DB-REQ-015 | MUST | **Encrypted columns** for ESG secrets metadata (not cert PEM — that's vault) | SEC | KMS |
| DB-REQ-016 | SHOULD | **Partitioning** audit_events by month | Query perf at scale | Enterprise |
| DB-REQ-017 | MUST | **Foreign keys + ON DELETE RESTRICT** on regulatory graph | No orphan sequences | Integrity |
| DB-REQ-018 | SHOULD | **Point-in-time recovery** — PITR enabled Postgres | RPO ≤1h | SAAS-NFR-005 |

### 4.4 Caching & queue data

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| DB-REQ-020 | MUST | **Redis** for sessions, rate limits, job queue (Celery/RQ) | HA Redis prod | Worker stack |
| DB-REQ-021 | SHOULD | Cache **artifact registry** rulesets in Redis with version key | Invalidate on registry update | PERF |
| DB-REQ-022 | MUST | Job queue **at-least-once** delivery + idempotent workers | No duplicate publishes | REL |

---

## 5. Document management requirements (`DM-REQ`)

*Benchmark: Veeva Vault Docs, Ennov EDMS, EXTEDO incremental publish, S3 object store.*

### 5.1 Storage architecture

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| DM-REQ-001 | MUST | **S3-compatible object store** — tenant-prefixed keys `s3://{tenant}/{dossier}/{seq}/...` | REQ-090 | Cloud SaaS |
| DM-REQ-002 | MUST | **Presigned upload URLs** — client uploads direct to S3; API records metadata after | Reduces API load | PERF |
| DM-REQ-003 | MUST | **Content-addressable storage option** — dedupe by SHA256 per tenant | Same file two leaves → one blob | Efficiency |
| DM-REQ-004 | MUST | **Version immutability** — published blob never overwritten; new version new key | Part 11 | Audit |
| DM-REQ-005 | MUST | **Server-side encryption** SSE-KMS on bucket | SEC | AWS best practice |
| DM-REQ-006 | SHOULD | **Canada region bucket** option per tenant | NFR-001 | Residency |

### 5.2 Document lifecycle

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| DM-REQ-010 | MUST | States: `draft` → `ready_for_qc` → `approved` → `published` → `transmitted` → `archived` | Only approved in publish | MasterControl |
| DM-REQ-011 | MUST | **WORM retention** option on transmitted packages | Legal hold blocks delete | REQ-054 |
| DM-REQ-012 | MUST | **MD5 leaf checksum** stored at upload; verified pre-publish | REQ-015 | eCTD |
| DM-REQ-013 | SHOULD | **Virus scan** on upload (ClamAV or cloud AV) | Block infected | SEC |
| DM-REQ-014 | MUST | **PDF remediation pipeline** — worker transforms PDF; stores before/after | REQ-108 | EXTEDO services |
| DM-REQ-015 | SHOULD | **Word source tracking** — optional DOCX source linked to PDF leaf | Fix Word then re-render | Ennov |

### 5.3 eCTD package artifacts

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| DM-REQ-020 | MUST | Store **published eCTD zip** + manifest JSON per sequence | Downloadable 7 years | Archive |
| DM-REQ-021 | MUST | Store **backbone XMLs** separately for diff/republish | index.xml, ca-regional.xml | Publishing |
| DM-REQ-022 | MUST | Store **validation report** JSON + optional PDF per run | Attached to sequence | Veeva archival |
| DM-REQ-023 | SHOULD | Store **ack artifacts** raw (MDN, FDA ack, HC ack) | Core ID index | REQ-088 |
| DM-REQ-024 | SHOULD | **Import package** staging area for external eCTD zip | REQ-106 | LORENZ import |

### 5.4 Document metadata & search

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| DM-REQ-030 | MUST | Metadata: title, leaf_id, module, hc_section, language, author, version | DIA EDM alignment | Ennov |
| DM-REQ-031 | SHOULD | **Auto-classification** suggest leaf from content (AI tier) | User confirms | Ennov AI |
| DM-REQ-032 | MUST | **Full-text index** optional on PDF text layer post-OCR | Search finds content | RIM |
| DM-REQ-033 | SHOULD | **Where-submitted** tag at document level | Veeva roadmap pattern | Veeva blog |

### 5.5 Integrations (document sources)

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| DM-REQ-040 | SHOULD | **SharePoint connector** — sync approved PDFs into content plan | API-REQ-060 | EXTEDO |
| DM-REQ-041 | SHOULD | **Veeva Vault outbound** — pull finalized docs via Vault REST | API-REQ-060 | Veeva Connections |
| DM-REQ-042 | COULD | **Email ingest** — forward HC notices to tenant inbox | REQ-112 | Correspondence |
| DM-REQ-043 | MUST | **Export all tenant data** — eCTD zips + JSON + audit on exit | SAAS-REQ-004 | Portability |

---

## 6. Performance requirements (`PERF-REQ`)

*Benchmark: Certara live validation, Veeva cloud scale, HC 10 GB packages, ESG timeouts.*

| ID | Pri | Requirement | Target | Benchmark |
|----|-----|-------------|--------|-----------|
| PERF-REQ-001 | MUST | API read P95 latency (non-job) | <500ms at 100 RPS/tenant | SAAS-NFR-002 |
| PERF-REQ-002 | MUST | **Inline validation** P95 after leaf change | <3s for typical sequence (<500 leaves) | Certara live |
| PERF-REQ-003 | MUST | **Publish job** 2 GB sequence | <15 min wall time on standard worker | Industry |
| PERF-REQ-004 | MUST | **Publish job** 10 GB sequence | Complete without timeout; progress reporting | HC CESG |
| PERF-REQ-005 | MUST | **Concurrent users** same dossier | 25 users; locking prevents corruption | REQ-057 |
| PERF-REQ-006 | MUST | **Checksum compute** | ≥50 MB/s per worker on PDF stream | Large dossiers |
| PERF-REQ-007 | SHOULD | **Batch validate** 10 sequences | Queue completes <60 min | eValidator FIVE |
| PERF-REQ-008 | MUST | **Dashboard load** | <2s including readiness aggregation | UI-REQ-013 |
| PERF-REQ-009 | MUST | **Presigned upload** | Supports 5 GB single file upload | Large PDFs |
| PERF-REQ-010 | SHOULD | **CDN** for static UI assets | TTFB <200ms global | SaaS |
| PERF-REQ-011 | MUST | **ESG submit timeout** handling | Retry with same idempotency key | REQ-087 |
| PERF-REQ-012 | MUST | **DB connection pool** sizing documented per 1000 tenants | No connection exhaustion | Ops |
| PERF-REQ-013 | SHOULD | **Horizontal worker scale** — add workers linearly throughput | Auto-scale on queue depth | Cloud |
| PERF-REQ-014 | MUST | **Cold start** API pod | <10s ready probe pass | K8s |
| PERF-REQ-015 | SHOULD | **Search** metadata query P95 | <1s | Ennov |

### 6.1 SLOs (production)

| Tier | Availability | Publish success | Validation availability |
|------|--------------|-----------------|-------------------------|
| Starter | 99.5% | 99% | 99.5% |
| Team | 99.9% | 99.5% | 99.9% |
| Enterprise | 99.95% | 99.9% | 99.95% |

---

## 7. Security requirements (`SEC-REQ`)

*Benchmark: ESG MFA, Veeva enterprise, Part 11, PIPEDA, tenant isolation.*

### 7.1 Identity & access

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| SEC-REQ-001 | MUST | **Password policy** — min length, breach list check (HIBP) | REQ-083 | SaaS |
| SEC-REQ-002 | MUST | **MFA** required for Production transmit + owner console | ESG USP | FDA |
| SEC-REQ-003 | MUST | **RBAC** — least privilege; dossier-scoped roles | REQ-038 | HC |
| SEC-REQ-004 | MUST | **SSO SAML/OIDC** Enterprise tier | REQ-038 | Veeva |
| SEC-REQ-005 | MUST | **Session fixation** protection; rotate on login | OWASP | Standard |
| SEC-REQ-006 | MUST | **API key rotation** without service interruption | Dual-key window | SaaS |
| SEC-REQ-007 | SHOULD | **IP allowlist** Enterprise optional | CRO security | Enterprise |

### 7.2 Data protection

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| SEC-REQ-010 | MUST | **TLS 1.2+** everywhere; HSTS preload | Scan A+ | Baseline |
| SEC-REQ-011 | MUST | **Encryption at rest** AES-256 DB + S3 KMS | SAAS-NFR-004 | Cloud |
| SEC-REQ-012 | MUST | **Tenant isolation** — IAM policies on S3 prefix | Pen test proof | NFR-015 |
| SEC-REQ-013 | MUST | **Secrets vault** — HashiCorp Vault or cloud KMS; no secrets in git | SEC | Ops |
| SEC-REQ-014 | MUST | **PII minimization** — collect only necessary profile fields | PIPEDA | REQ-067 |
| SEC-REQ-015 | SHOULD | **Field-level encryption** for correspondence containing PHI | Provincial | NFR-005 |
| SEC-REQ-016 | MUST | **Secure delete** crypto-shred keys on tenant offboarding after export window | SAAS-REQ-004 | GDPR pattern |

### 7.3 Application security

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| SEC-REQ-020 | MUST | **OWASP ASVS L2** on API; annual pen test | Report remediated | Enterprise sales |
| SEC-REQ-021 | MUST | **CSRF** protection on cookie auth | Token double-submit | Web |
| SEC-REQ-022 | MUST | **Input validation** — size limits, MIME allowlist pdf/xml/docx | Reject polyglots | Upload safety |
| SEC-REQ-023 | MUST | **Audit all auth failures** + lockout after N attempts | SOC | Standard |
| SEC-REQ-024 | SHOULD | **CSP** strict on workspace UI | No inline script unsafe | XSS |
| SEC-REQ-025 | MUST | **Dependency scanning** in CI — block critical CVEs | SCA gate | DevSecOps |
| SEC-REQ-026 | MUST | **Signed webhooks** HMAC | API-REQ-050 | Integrators |

### 7.4 Regulatory & compliance security

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| SEC-REQ-030 | MUST | **Part 11 feature map** — audit trail, e-sign, authority checks | REQ-118 CSV pack | Certara |
| SEC-REQ-031 | MUST | **Tamper-evident audit** — hash chain optional on audit export | REQ-053 | e-sign |
| SEC-REQ-032 | SHOULD | **SOC 2 Type II** track | SAAS-NFR-009 | Enterprise |
| SEC-REQ-033 | SHOULD | **Canadian residency** deploy — ca-central-1 only option | SAAS-NFR-008 | Value-add |
| SEC-REQ-034 | MUST | **Subprocessor list** published; DPA with customers | Trust center | SAAS-REQ-005 |
| SEC-REQ-035 | MUST | **Basis tagging** on security controls (HC vs value-add) | REQ-067 | Verification |

---

## 8. UI ↔ API integration requirements (`INT-REQ`)

*How the frontend and backend must behave together — realtime, optimistic UX, offline resilience.*

| ID | Pri | Requirement | Acceptance | Benchmark |
|----|-----|-------------|------------|-----------|
| INT-REQ-001 | MUST | **Design system tokens** — single source for status colors (READY/BLOCKED/warn) | UI matches API severity enums | Prism UI-4 |
| INT-REQ-002 | MUST | **Optimistic UI** on leaf upload with rollback on 4xx/5xx | Toast + revert tree state | Modern SaaS |
| INT-REQ-003 | MUST | **Polling fallback** for jobs — 2s interval; WebSocket optional upgrade | Progress bar accurate ±5% | Jobs |
| INT-REQ-004 | MUST | **Stale-while-revalidate** on dashboard — show cached readiness, refresh background | No blank flash | UX perf |
| INT-REQ-005 | MUST | **Validation gutter** driven solely by `POST /validate/inline` — no client-side rules | Single source of truth | Architecture |
| INT-REQ-006 | MUST | **Error mapping** — RFC9457 `rule_id` → gutter fix action deep link | One-click fix works | REQ-023 |
| INT-REQ-007 | MUST | **Concurrent edit detection** — 409 shows merge UI not silent overwrite | REQ-057 | Google Docs pattern |
| INT-REQ-008 | MUST | **Transmit button** disabled unless API `GET /readiness` returns `ready=true` | No client bypass | Safety |
| INT-REQ-009 | MUST | **File upload** uses presigned URL flow; UI shows bytes uploaded | DM-REQ-002 | S3 pattern |
| INT-REQ-010 | SHOULD | **SSE or WebSocket** for ack state changes on transmission console | Live ack without poll | ESG USP |
| INT-REQ-011 | MUST | **Session refresh** silent before expiry; redirect login on 401 | No data loss mid-form | Auth |
| INT-REQ-012 | MUST | **Feature flags** from entitlements API — hide nav client-side AND server 403 | REQ-082 | Security |
| INT-REQ-013 | SHOULD | **Offline banner** when API unreachable; queue comments locally optional COULD | Resilience | PWA |
| INT-REQ-014 | MUST | **i18n hook** — UI strings externalized; FR UI labels for bilingual orgs | Future FR UI | HC bilingual |
| INT-REQ-015 | MUST | **Deep links** — `/dossiers/{id}/tree?leaf=` loads via API then focuses node | UI-REQ-024 | Collaboration |
| INT-REQ-016 | SHOULD | **BFF layer** optional — Next.js server aggregates dashboard calls to 1 round trip | PERF dashboard | Vercel |
| INT-REQ-017 | MUST | **E2E contract tests** — Playwright UI actions match OpenAPI schemas | CI gate | Quality |
| INT-REQ-018 | MUST | **Version pin** — UI displays `ruleset_version` + `artifact_registry_version` from API | Trust | REQ-089 |
| INT-REQ-019 | SHOULD | **Embedded Stripe** billing portal iframe/postMessage secure | UI-REQ-061 | Stripe |
| INT-REQ-020 | MUST | **CORS** — only allowed origins; credentials mode documented | SEC | Web |

---

## 9. World-best / state-of-art requirements (`BEST-REQ`)

*Exceed LORENZ/Veeva/Certara — “super easy” + “best ANDS system in the world”.*

| ID | Pri | Requirement | Why world-best | Acceptance |
|----|-----|-------------|----------------|------------|
| BEST-REQ-001 | MUST | **“5-day first ANDS” guarantee path** — wizard + templates + concierge tier | Beats 6-month legacy onboarding | Median new tenant publishes seq 0000 mock ≤5 business days |
| BEST-REQ-002 | MUST | **Zero-surprise transmit** — pre-flight shows exact HC validator output diff vs last run | Trust | User confirms diff modal before send |
| BEST-REQ-003 | MUST | **Plain-language everywhere** — Grade 10 reading level default; jargon expandable | Super easy | UX content audit |
| BEST-REQ-004 | MUST | **One-click “Fix all safe fixes”** — auto-apply validation fixes that cannot break content | Speed | REQ-023 batch fix |
| BEST-REQ-005 | SHOULD | **“What HC will see” preview** — REP stylesheet + PM render matched to registry | HC-aligned preview | REQ-065 |
| BEST-REQ-006 | SHOULD | **ANDS copilot** — chat answers “where does X go?” citing placement table section | Super easy | RAG on HC docs |
| BEST-REQ-007 | SHOULD | **Smart sequence suggest** — proposes next sequence number + operation types from lifecycle | Reduces errors | AI/rules hybrid |
| BEST-REQ-008 | MUST | **Price transparency** — in-app TCO vs docuBridge/GlobalSubmit calculator | Disrupts license model | SAAS-REQ-007 |
| BEST-REQ-009 | SHOULD | **Community template marketplace** — anonymized ANDS checklists shared | Network effect | COULD phase 4 |
| BEST-REQ-010 | MUST | **Validator parity badge** — “98% match LORENZ CA eCTD on golden set” public score | Trust moat | Published metric |
| BEST-REQ-011 | SHOULD | **Same-day publish** after last doc approved — continuous publish like Veeva | Speed | <1h publish job |
| BEST-REQ-012 | SHOULD | **Cross-module brain** — flags CMC table ≠ QOS narrative conflicts | Assyro-class | REQ-120 |
| BEST-REQ-013 | COULD | **Regulatory twin** — digital twin simulates screening deficiency risk score | State of art | ML on historical |
| BEST-REQ-014 | MUST | **Instant sandbox** — `<60s` tenant provision with sample dossier | Super easy signup | SAAS-REQ-008 |
| BEST-REQ-015 | SHOULD | **Universal undo** — 24h undo publish metadata (not transmitted) | Safety | UX |
| BEST-REQ-016 | SHOULD | **HC change autopilot** — when ruleset updates, auto-run impact + suggested fixes | Assyro-class | REQ-119 |
| BEST-REQ-017 | MUST | **Accessibility-first tree** — screen reader can navigate full eCTD tree | Inclusive best | WCAG |
| BEST-REQ-018 | SHOULD | **Voice of RA advisory panel** — in-app feedback loop on UX friction | Continuous UX | Product ops |
| BEST-REQ-019 | MUST | **No vendor lock-in pledge** — full export anytime; open eCTD zip standard | Trust + EU style | DM-REQ-043 |
| BEST-REQ-020 | MUST | **Happiness metric** — in-app CES survey post-first-transmit; target CES >50 | Super easy proof | Product KPI |

---

## 10. Master comparison matrix (layered)

| Capability | LORENZ | Veeva | Certara | Ennov | **Target us** |
|------------|--------|-------|---------|-------|---------------|
| **UI: Guided ANDS** | ○ | ● | ○ | ● | **●●** BEST-REQ |
| **UI: Live gutter** | ● | ● | **●●** | ● | **●●** |
| **UI: CrossCheck** | ○ | ○ | **●●** | ○ | **●●** |
| **UI: Bilingual PM** | ○ | ● | ○ | ○ | **●●** |
| **API: Public REST** | ○ | **●●** | ○ | ○ | **●●** |
| **API: Webhooks** | ○ | ○ | ○ | ○ | **●●** |
| **DB: Unified RIM** | ○ | **●●** | ● | **●●** | **●** (ANDS-focused) |
| **DM: Built-in EDMS** | ○ | **●●** | ○ | **●●** | **●** content plan |
| **PERF: Live validate** | ● | ● | **●●** | ● | **●●** |
| **SEC: MFA transmit** | ○ | ● | ○ | ○ | **●●** ESG-aligned |
| **INT: Presigned upload** | ○ | ● | ● | ● | **●●** |
| **BEST: Super easy** | ○ | ○ | ○ | ● | **●●** north star |
| **BEST: Affordable SaaS** | ● pay/seq | ○ | ○ | ● | **●●** |

Legend: ○ weak · ● adequate · ●● target leadership

---

## 11. Traceability index (layer → functional)

| Layer ID range | Maps to |
|----------------|---------|
| UI-REQ-* | REQ-071–076, 085, 098–110, COMP-WF, COMP-CA |
| API-REQ-* | REQ-087–088, 090–091, SAAS-REQ-011, all `/api/*` |
| DB-REQ-* | REQ-057, 077–078, 060, NFR-015, NFR-019 |
| DM-REQ-* | REQ-009–015, 090, 108, REQ-106 |
| PERF-REQ-* | NFR-008, NFR-009, SAAS-NFR-002 |
| SEC-REQ-* | NFR-007, NFR-015, REQ-038, SAAS-NFR-003–004 |
| INT-REQ-* | Production frontend + OpenAPI contract |
| BEST-REQ-* | Vision differentiation + COMP-DIFF |

---

## 12. Implementation priority (layer sprints)

| Sprint | Focus | IDs |
|--------|-------|-----|
| **S1 Foundation** | OpenAPI, Postgres schema, S3 presign, auth+MFA | API-001–007, DB-001–004, DM-001–002, SEC-001–013 |
| **S2 Super easy UI** | Wizard, stepper, READY dashboard, TOC editor | UI-001–015, UI-020–025, INT-001–008 |
| **S3 Validation UX** | Live gutter, CrossCheck, fix-all | UI-021, UI-027, API-022, PERF-002, BEST-004 |
| **S4 Canada ANDS** | Bilingual PM, forms, CS-BE/QOS UI | UI-030–035, REQ-098–101 |
| **S5 Transmit** | ESG adapter, ack SSE, transmission UI | UI-050–052, API-025, API-070–071, INT-010 |
| **S6 Enterprise** | SSO, webhooks, DMS connector, CSV pack | API-050–060, SEC-004, SEC-030, DM-040 |
| **S7 World-best** | Copilot, parity badge, TCO calculator, CES | BEST-001–020 |

---

## 13. Related documents

| Document | Role |
|----------|------|
| [`VISION-GAP-REQUIREMENTS.md`](VISION-GAP-REQUIREMENTS.md) | Gap + REQ-087–122 functional roadmap |
| [`COMPETITIVE-REQUIREMENTS-INVENTORY.md`](COMPETITIVE-REQUIREMENTS-INVENTORY.md) | 127 COMP-* vendor requirements |
| [`requirements-corrected.json`](requirements-corrected.json) | HC regulatory corpus |
| [`../../apps/ands-submission-portal/production/README.md`](../../apps/ands-submission-portal/production/README.md) | Target deployment stack |

---

*This specification is the engineering-facing decomposition of “best ANDS submission platform in the world — super easy, state of the art, multi-tenant SaaS.”*
