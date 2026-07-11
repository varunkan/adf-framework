# ANDS Submission Portal

A single-file-runnable portal for preparing **ANDS (Abbreviated New Drug
Submission)** regulatory transactions for Health Canada — with a real
Health-Canada-style eCTD validation engine, REP enrolment, eCTD packaging,
CESG/FDA-ESG transmission modelling, submission lifecycle/clarifax tracking,
fees, and governance.

Python 3 **standard library only** — no pip installs, no network calls. Storage
is sqlite.

> **Built by ADF.** This portal started as a 30-test intake MVP and was grown by
> the Agentic Development Framework's requirements crew + relentless self-heal
> loop into the **18-module, 370-test** build documented here. The requirements
> corpus and the live-Health-Canada verification trail live in
> [`docs/ands-portal/`](../../docs/ands-portal/) and
> [`specs/ands-submission-portal/`](../../specs/ands-submission-portal/).

## Run

```bash
cd apps/ands-submission-portal
python3 server.py
```

Open <http://127.0.0.1:8000/>. Fill the form and click **Validate** (dry-run,
shows pass/fail per rule) or **Submit** (validates and stores). The sqlite file
`submissions.db` is created next to the script. Stop with `Ctrl-C`.

## Test

```bash
cd apps/ands-submission-portal
python3 -m unittest        # 370 tests
```

**370 tests, all passing** (~53s). Each test spins up a real HTTP server on an
ephemeral port and exercises the domain modules and the JSON API end-to-end.
No third-party test runner — plain `unittest`.

## What it does

| Capability | Module(s) | Highlights |
| ---------- | --------- | ---------- |
| **Intake & identifiers** | `domain`, `rep` | Dossier ID = `e` + 6/7 digits (drugs; `m` is the medical-device convention); 4-digit sequences; Company ID as an HC-assigned alphanumeric token; required-field + email checks. |
| **eCTD validation engine** | `validation` | Versioned ruleset (default **v5.3**, eff 2025-05-31), categories A–I, two-tier **Error/Warning** model, per-rule fixes, consistency + packaging gates, emitted-report ingest. |
| **eCTD assembly & backbone** | `ectd`, `backbone`, `content_model` | `dossier-id/NNNN/{m1/ca,m2..m5,util}` tree, ICH `index.xml` + `index-md5.txt`, CA `ca-regional.xml`, MD5 leaf checksums; ICH DTD **3.2.2** / CA Module 1 Schema **v2.2** pinned. |
| **ANDS content / bioequivalence** | `bioequivalence`, `qos` | CS-BE builder (electronic copy in **Module 1.6**, pivotal reports in 5.3.1.2, 2.4–2.7 suppressed), Cmax rule versioned across ICH **M13A** (eff 2025-12-27), QOS-CE (2.3) template + gate. |
| **REP & templates** | `rep` | CO/RT/PI template versions, immutable filenames, `ca-regional.xml` generation, portal-owned cover letter (HC supplies the placement slot, not a fillable template). |
| **Transmission (CESG/FDA-ESG)** | `transmission` | FDA-ESG NextGen ride-along (no direct HC endpoint), WebTrader/AS2, MDN→ACK1→HC-ACK chain, Core-ID correlation, 10 GB ceiling → physical-media fallback. |
| **Lifecycle & calendar** | `lifecycle`, `hc_calendar` | Screening (45d) → review (ANDS 180d) → decision (NOC/NON/NOD), clarifax clock-stops, Inactive-45/90, service standards + on-time KPIs, HC holiday calendar. |
| **Fees** | `fees` | Per-fiscal-year schedule (current 2025-26/2026-27 amounts), per-grouping CPI vs ministerial-2% escalation basis, right-to-sell fees, 25% fee credit. |
| **Study tagging** | `stf` | Dedicated STF leaf builder/validator for Module 5 BE studies. |
| **Governance** | `rbac`, `esign`, `retention`, `dr`, `report_ingest` | Role-based portfolio access, audit log + export, HPFB e-signature policy, retention/disposition, in-Canada residency as an opt-in value-add control, validation-report ingest. |

A submission is **accepted only when every rule passes**; otherwise it is
rejected, **not stored**, and the response lists *every* failing rule.

## JSON API

The server exposes 70+ JSON endpoints across intake, validation, packaging,
transmission, lifecycle, and governance. Core surface:

| Group | Endpoints |
| ----- | --------- |
| Intake | `POST /api/validate`, `POST /api/submissions`, `GET /api/submissions[/<id>]`, `POST /api/identifiers/validate` |
| Validation | `GET /api/validation/{rulesets,ruleset,services}`, `POST /api/validation/{run,inline,fix,report,consistency,package}` |
| eCTD | `GET /api/ectd/placement`, `GET\|POST /api/ectd/dossiers`, `POST /api/transactions/assemble`, `POST /api/backbone/generate` |
| Bioequivalence | `GET /api/be/rulesets`, `POST /api/be/{resolve,evaluate}`, `POST /api/cs-be/build`, `GET /api/crp/fields`, `POST /api/crp/validate` |
| QOS / STF | `GET /api/qos/template`, `POST /api/qos/{build,gate}`, `POST /api/stf/{generate,validate}` |
| Transmission | `POST /api/transmission/{configure,test-round-trip,route,submit,ack,monitor,resend}`, `POST /api/transmission/media/{build,ship,receive}` |
| Lifecycle | `GET /api/lifecycle/dossiers`, `POST /api/lifecycle/{start,transition,service-standard}`, `POST /api/calendar/deadline` |
| Governance | `GET /api/rbac/roles`, `GET /api/audit`, `GET /api/retention/policy`, `GET /api/esign/policy`, `GET /api/fees/reference` |
| Workspace | `GET /api/tenant/{nav,entitlements,submissions}`, `GET /api/tenant/dashboard` (REQ-071 submission-readiness aggregation: per-submission lifecycle / validation / Module-1 X-of-Y / fees / e-sign / transmission / next-deadline tiles + READY\|BLOCKED + drill-in to blocking items), `GET /api/journey/{id}` (JRNY-REQ-001 guided-journey spine: the gated 11-stage walk — stages done/current/locked + plain-language reason — + Resume position + folded-in readiness card) |

Each intake error is `{"rule": "<id>", "message": "<human-readable>"}`; the
validation engine's findings additionally carry a `severity` (`Error` /
`Warning`).

### Example

```bash
curl -X POST http://127.0.0.1:8000/api/submissions \
  -H 'Content-Type: application/json' \
  -d '{"applicant":"Acme Generics Inc.","drug_product":"Metformin HCl 500 mg tablets",
       "dossier_id":"e123456","submission_type":"ANDS","sequence":"0000",
       "contact_email":"ra@acme.example"}'
```

## Provenance & honest scope

The requirements corpus (70 functional + 21 non-functional) was discovered by an
ADF multi-agent research crew against live canada.ca sources, then adversarially
verified by a second crew that re-fetched Health Canada docs on 2026-06-21
(verdict + corrections in [`docs/ands-portal/`](../../docs/ands-portal/)). A
2026-06-24 reconciliation of all 68 known deltas against this code found roughly
half fully closed-with-tests and the remainder partial or open.

**Known limitations (by design or still open):**

- Ships **stand-in** reference artifacts for the CA Module 1 XSD, REP XSL
  stylesheets, and controlled vocabularies — not the real HC binary schema files
  (a consequence of the zero-dependency, stdlib-only constraint).
- No dossier-ID **request** workflow: the portal validates and uses an existing
  Dossier ID; it does not model the HC request round-trip.
- No 8-week pre-filing lead-time gate, and privacy is PIPEDA-baseline only (no
  provincial-privacy overlay) yet.

## Files

- `server.py` — HTTP shell: sqlite store, 70+-route JSON API, single-page UI at `/`.
- `test_app.py` — 370-test `unittest` suite.
- 20 dependency-free domain modules: `validation`, `lifecycle`, `transmission`,
  `ectd`, `rep`, `bioequivalence`, `esign`, `content_model`, `rbac`, `fees`,
  `backbone`, `report_ingest`, `hc_calendar`, `stf`, `dr`, `retention`, `qos`,
  `readiness` (REQ-071 submission-readiness aggregation),
  `journey` (REQ-073 guided-journey spine), `domain`.
