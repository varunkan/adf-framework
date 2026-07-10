# Production split stack (Option B)

Vercel hosts the **Next.js UI**. The **FastAPI backend**, **Postgres**, **S3-compatible storage**, and **background worker** run on Railway, Fly.io, Render, or Docker — not on Vercel.

The monolith `server.py` remains for local dev and the 370-test suite. Production reuses the same stdlib **domain modules** (`domain.py`, `validation.py`, `transmission.py`, …).

## Architecture

```
┌─────────────────┐     HTTPS      ┌──────────────────────────────┐
│  Vercel         │ ─────────────► │  API (FastAPI + uvicorn)     │
│  Next.js UI     │   NEXT_PUBLIC  │  Railway / Fly / Render      │
└─────────────────┘   _API_URL     └───────────┬──────────────────┘
                                               │
                    ┌──────────────────────────┼──────────────────┐
                    ▼                          ▼                  ▼
              PostgreSQL                  MinIO/S3            Worker
              (submissions)               (eCTD packages)     (async jobs)
                                               │
                                               ▼ Phase 3
                                         FDA ESG NextGen (AS2)
                                               │
                                               ▼
                                         Health Canada (HC)
```

## Local development

**Recommended:** use Docker for the API (Python 3.12 + Postgres + MinIO). The host Python may be too new for `psycopg` binary wheels.

### 1. Backend stack (Docker)

```bash
cd adf-framework/apps/ands-submission-portal/production
cp .env.example .env
docker compose up --build
```

Services:

| Service  | URL |
|----------|-----|
| API      | http://localhost:8080 |
| Postgres | localhost:5432 |
| MinIO    | http://localhost:9000 (console :9001) |

Smoke test:

```bash
curl -s http://localhost:8080/api/health
curl -s -X POST http://localhost:8080/api/validate \
  -H 'Content-Type: application/json' \
  -d '{"applicant":"Acme","drug_product":"Metformin","dossier_id":"e123456","sequence":"0000","contact_email":"ra@acme.example"}'
```

### 2. Frontend (Next.js)

```bash
cd frontend
npm install
echo 'NEXT_PUBLIC_API_URL=http://localhost:8080' > .env.local
npm run dev
```

Open http://localhost:3000

## Deploy (production)

**End-to-end:** see **[DEPLOY.md](DEPLOY.md)** — Railway API + Vercel UI, or GitHub Actions CI.

Quick local script (requires `RAILWAY_TOKEN` + `vercel login`):

```bash
./scripts/deploy-e2e.sh
```

1. Create a Railway project with **Postgres** and **Redis** plugins.
2. Add a **MinIO** service or use AWS S3 (`S3_ENDPOINT` empty for real AWS).
3. Deploy from repo root with Dockerfile:
   - **Root directory:** `adf-framework/apps/ands-submission-portal`
   - **Dockerfile:** `production/backend/Dockerfile`
4. Set environment variables from `.env.example`:
   - `DATABASE_URL` — from Railway Postgres
   - `CORS_ORIGINS` — your Vercel URL(s)
   - `S3_*` — bucket credentials
   - `ESG_MODE=mock` until FDA ESG Test credentials exist
5. Deploy a second service for the worker using `production/backend/Dockerfile.worker`.

## Deploy frontend (Vercel)

1. Import the repo in Vercel.
2. Set **Root Directory** to `adf-framework/apps/ands-submission-portal/production/frontend`.
3. Add environment variable:
   - `NEXT_PUBLIC_API_URL` = `https://your-api.railway.app` (no trailing slash)
4. Deploy.

Add your Vercel preview/production URLs to the API `CORS_ORIGINS`.

## API surface (v1)

Core routes implemented; remaining monolith routes can be ported using the same pattern in `backend/app/routes/`.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness |
| POST | `/api/auth/signup` | Self-serve tenant registration (REQ-077) |
| POST | `/api/auth/login` | Tenant user login |
| POST | `/api/auth/logout` | End session |
| GET | `/api/tenant/dashboard` | READY/BLOCKED readiness dashboard (REQ-071) |
| GET/POST | `/api/tenant/submissions` | Tenant-scoped submission records |
| GET | `/api/tenant/nav` | Entitlement-filtered workspace nav |
| GET | `/api/openapi.json` | OpenAPI 3.1 schema (SAAS-REQ-011) |
| POST | `/api/validate` | Dry-run intake validation |
| GET/POST | `/api/submissions` | List / create |
| GET | `/api/submissions/{id}` | Fetch one |
| POST | `/api/packages/jobs` | Queue eCTD package job (worker) |
| GET | `/api/validation/rulesets` | HC ruleset versions |
| GET | `/api/transmission/account-types` | ESG account metadata |
| POST | `/api/transmission/configure` | ESG config validation |
| POST | `/api/transmission/test-round-trip` | Test gateway unlock |

## Health Canada connectivity (Phase 3)

Real submissions still go through **FDA ESG NextGen** with recipient **`HC`** — not a direct HC API.

1. Register as an FDA ESG Trading Partner (WebTrader and/or AS2).
2. Complete the **Test gateway** round-trip.
3. Implement `TestEsgAdapter` in `backend/app/integrations/esg.py` (AS2 client + cert handling).
4. Set `ESG_MODE=test`, then `production` after FDA approval.

See [CESG FAQ](https://www.canada.ca/en/health-canada/services/drugs-health-products/drug-products/applications-submissions/guidance-documents/common-electronic-submissions-gateway/frequently-asked-questions.html).

## Roadmap

| Phase | Status | Deliverable |
|-------|--------|-------------|
| 0 Foundation | **Done (this scaffold)** | FastAPI, Postgres, S3, worker, Next.js, Docker |
| 1 Artifacts | Planned | Version-pinned HC schemas, REP templates, rulesets |
| 2 Package engine | Planned | Full eCTD zip assembly → S3 |
| 3 ESG Test | Planned | Live FDA ESG Test AS2 adapter |
| 4 ESG Production | Planned | Production transmit + ack ingestion |
| 5 Enterprise | Planned | SSO, multi-tenant, audit export |

## Files

```
production/
├── docker-compose.yml
├── .env.example
├── README.md
├── backend/
│   ├── Dockerfile
│   ├── Dockerfile.worker
│   ├── requirements.txt
│   ├── app/           # FastAPI
│   └── worker/        # Background jobs
└── frontend/          # Next.js → Vercel
```
