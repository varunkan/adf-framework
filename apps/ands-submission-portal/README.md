# ANDS Submission Portal (MVP)

A single-file runnable portal for **ANDS (Abbreviated New Drug Submission)**
intake with real Health-Canada-style eCTD validation: Dossier-ID format,
4-digit sequence numbers, and per-dossier sequence-lifecycle enforcement.

Python 3 **standard library only** — no pip installs, no network. Storage is
sqlite.

## Run

```bash
cd apps/ands-submission-portal
python3 server.py
```

Then open <http://127.0.0.1:8000/>. Fill the form and click **Validate**
(dry-run, shows pass/fail per rule) or **Submit** (validates and stores).
Stop with `Ctrl-C`. The sqlite file `submissions.db` is created next to the
script.

## Test

```bash
cd apps/ands-submission-portal
python3 -m unittest -v
```

30 tests, all passing — covering the domain rules and the JSON API end-to-end.

## Validation rules (the real value)

These are implemented for real in `domain.validate_intake`:

| Rule | Behaviour |
| ---- | --------- |
| **Dossier ID** | Lowercase `e` + 6 or 7 digits (`e123456`, `e1234567`). Anything else rejected. |
| **Sequence number** | Exactly 4 digits (`0000`–`9999`). |
| **Sequence lifecycle** | The first accepted sequence for a dossier must be `0000`; each later one exactly previous + 1 (no gaps, no duplicates). Rejections name the expected next sequence. |
| **Required fields** | Applicant, drug product, dossier ID, sequence, contact email — all non-empty; email must look like an email. |
| **Submission type** | Must equal `ANDS`. |

A submission is **accepted only when every rule passes**; otherwise it is
rejected, **not stored**, and the response lists *every* failing rule.

## JSON API

| Method & path | Purpose |
| ------------- | ------- |
| `POST /api/validate` | Dry-run. Returns `{"valid": bool, "errors": [...]}`; never stores. |
| `POST /api/submissions` | Validate + store if valid. `201` with the stored record, or `422` with the validation errors. |
| `GET /api/submissions` | List accepted submissions. |
| `GET /api/submissions/<id>` | One submission, or `404` if missing. |

Each error is `{"rule": "<id>", "message": "<human-readable>"}`.

### Example

```bash
curl -X POST http://127.0.0.1:8000/api/submissions \
  -H 'Content-Type: application/json' \
  -d '{"applicant":"Acme Generics Inc.","drug_product":"Metformin HCl 500 mg tablets",
       "dossier_id":"e123456","submission_type":"ANDS","sequence":"0000",
       "contact_email":"ra@acme.example"}'
```

## Files

- `domain.py` — pure, dependency-free domain logic. The MVP intake rules live in
  `validate_intake` / `next_expected_sequence`.
- `server.py` — thin HTTP shell: sqlite `SubmissionStore`, JSON API, and the
  single-page UI served at `/`.
- `test_app.py` — `unittest` suite for the domain rules and the API.

## Scope

This is the bounded MVP: submission intake + the four validation rules +
sqlite persistence + JSON API + UI. Full eCTD packaging, REP/backbone XML
generation, transmission/ACK tracking, fees, and RBAC are out of scope for this
build (see `specs/ands-submission-portal/mvp-scope.md`).
