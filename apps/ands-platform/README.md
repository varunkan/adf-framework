# ANDS Platform — event-driven FastAPI microservices

The production rewrite of the ANDS submission portal: **one FastAPI service per
bounded context**, **Postgres-per-service**, a **Redis event bus**, and an **API
gateway / BFF** — hexagonal (ports & adapters) + DDD. See
[`docs/ADR-0001-microservices-architecture.md`](docs/ADR-0001-microservices-architecture.md).

> Replaces the former stdlib monolith (`apps/ands-submission-portal`), which
> served as the reference **oracle** during the rewrite and has now been fully
> decommissioned and removed — the domain logic lives in these services.

## Layout

```
libs/ands_shared/      shared kernel: event envelope + bus (in-mem/Redis),
                       SQLite base, problem+json, FastAPI app factory
services/<ctx>/app/    domain (pure) · ports · service (use-cases) ·
                       repository_sqlite (dev/test) · repository_postgres (prod) ·
                       api (FastAPI) · main (composition root)
services/<ctx>/tests/  pytest: domain + API (TestClient) + events
gateway/               API gateway / BFF (reverse proxy + health aggregation)
docker-compose.yml     local mesh (per-service Postgres, Redis, services, gateway)
verify.sh              run every suite with the platform venv
```

## The hexagonal seam (why it runs anywhere)

Each service depends on **ports**, not infrastructure. Two adapter sets:

| Edge | Dev / test (this repo) | Production (compose / cloud) |
|------|------------------------|------------------------------|
| Persistence | SQLite (`repository_sqlite`) | Postgres via `pg8000` (`repository_postgres`) |
| Event bus | `InMemoryEventBus` (synchronous) | `RedisEventBus` (Redis Streams) |

So the **domain + application + API** layers are fully tested in-sandbox over the
in-memory adapters (FastAPI `TestClient` = real ASGI), while Postgres/Redis are
exercised by `docker-compose` in CI/cloud. Same code, swapped edges — chosen by
env (`ANDS_DB_BACKEND`, `ANDS_BUS`).

## Run the tests

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements-dev.txt
./verify.sh
```

## Operations

- `make venv && make test` — create the venv and run every suite (`verify.sh`).
- CI: [`.github/workflows/ands-platform-ci.yml`](../../.github/workflows/ands-platform-ci.yml) runs the full suite + `docker compose build` on every platform change.
- Kubernetes: [`ops/k8s/`](ops/k8s/) — namespace, Redis, the gateway, and `collaboration` as the replicable per-service pattern.
- Observability: every service exposes `/health` and Prometheus `/metrics`; the gateway exposes `/gateway/health` and `/gateway/services`.

## Run the mesh locally (Docker)

```bash
docker compose up --build
curl localhost:8080/gateway/health
curl -X POST localhost:8080/api/collab/tasks \
  -H 'Content-Type: application/json' \
  -d '{"title":"Upload FR PM","assignee":"bob","due_date":"2026-08-01","dossier_id":"e123456"}'
curl 'localhost:8080/api/collab/inbox?user=bob'
```

## Run a single service (no Docker)

```bash
cd services/collaboration
PYTHONPATH=.:../../libs ../../.venv/bin/uvicorn app.main:app --port 8000
# defaults: ANDS_DB_BACKEND=sqlite, ANDS_BUS=memory
```

## Services

| Service | Status | Owns |
|---------|--------|------|
| **collaboration** | ✅ built (REQ-109) | comments, tasks, notifications; consumes `validation.failed` / `transmission.hc_ack`, emits `collab.task_assigned` |
| **dossier** | ✅ built (REQ-103/098/092/099/101/107/110) | content plans, bilingual PM, admin/corrective sequences, XML PM build/validate, PM cross-refs, eCTD assembly + Application Viewer (Files/Outline), submission archive/binder + share links; emits `content_plan.item_assigned`, `bilingual_pm.blocked` |
| **validation** | ✅ built (REQ-104) | versioned HC eCTD rule engine (run/inline/fix), persisted reports; emits `validation.completed` / `validation.failed` (→ collaboration notifies) |
| **identity** | ✅ built (REQ-077..084) | self-serve signup, login/sessions (PBKDF2), tenants, plans+overrides → effective entitlements, RBAC authorize; emits `identity.tenant_provisioned` |
| **lifecycle** | ✅ built (REQ-030/031/062) | DSTS state machine (Screening→Review→NOC/NOD/NON), statutory-holiday deadline calendar, 25% missed-service-standard credit; emits `lifecycle.transitioned`, `lifecycle.service_standard_missed` |
| **fees** | ✅ built (REQ-035/036/037) | stateless calculator: Schedule-1 fee + fiscal-year escalation, small-business remission/deferral, per-DIN Right-to-Sell |
| **transmission** | ✅ built (REQ-003/025/027/046) | FDA-ESG NextGen config + Test-gateway gate, 10 GB routing, one-at-a-time MDN→FDA→HC ack chain; emits `transmission.sent`, `transmission.hc_ack` (→ collaboration notifies) |
| **governance** | ✅ built (REQ-039/053/068/060) | tamper-evident e-signature gate (QA review + manifest) **and** the event-sourced audit trail — subscribes to `*` and records every domain event, append-only, with text export |
| **readiness (BFF)** | ✅ built (REQ-071) | event-driven projection — consumes validation/transmission/lifecycle/bilingual-PM events into a per-dossier READY/BLOCKED dashboard with drill-in blockers |
| **registry** | ✅ built (REQ-111) | marketed-product registration registry (product × country × dossier × DIN × status) with status state machine + post-NOC Right-to-Sell obligation; emits `registration.status_changed` |
| **webhooks** | ✅ built (SAAS-REQ-011) | tenants register endpoints (by event type/tenant); subscribes to the bus `*` and enqueues HMAC-signed deliveries to an append-only outbox |

Migration order and per-service recipe: see the ADR.
