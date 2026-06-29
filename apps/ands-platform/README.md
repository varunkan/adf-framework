# ANDS Platform — event-driven FastAPI microservices

The production rewrite of the ANDS submission portal: **one FastAPI service per
bounded context**, **Postgres-per-service**, a **Redis event bus**, and an **API
gateway / BFF** — hexagonal (ports & adapters) + DDD. See
[`docs/ADR-0001-microservices-architecture.md`](docs/ADR-0001-microservices-architecture.md).

> Replaces the stdlib monolith at [`apps/ands-submission-portal`](../ands-submission-portal),
> which is retained as the 675-test **oracle** to port domain logic from, and
> decommissioned per context as each service drains it.

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
| **dossier** | ✅ built (REQ-103, REQ-098) | eCTD Module-1 placement, submission content plans, bilingual Product Monograph; emits `dossier.content_plan.item_assigned`, `dossier.bilingual_pm.blocked` |
| **validation** | ✅ built (REQ-104) | versioned HC eCTD rule engine (run/inline/fix), persisted reports; emits `validation.completed` / `validation.failed` (→ collaboration notifies) |
| identity | ⏳ | auth, tenancy, entitlements, rbac, privacy |
| lifecycle | ⏳ | DSTS lifecycle, HC calendar |
| transmission | ⏳ | FDA-ESG ride-along |
| fees | ⏳ | fee schedule |
| governance | ⏳ | e-sign, retention, DR, audit |
| readiness (BFF) | ⏳ | event-driven dashboard aggregation |

Migration order and per-service recipe: see the ADR.
