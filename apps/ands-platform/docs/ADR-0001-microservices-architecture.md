# ADR-0001 — ANDS Platform: event-driven FastAPI microservices

**Status:** Accepted (2026-06-29) · **Supersedes:** the `apps/ands-submission-portal` stdlib monolith
**Decision owners:** product (user) + ADF
**Context docs:** [`VISION-GAP-REQUIREMENTS.md`](../../../docs/ands-portal/VISION-GAP-REQUIREMENTS.md), [`ANDS-PLATFORM-LAYERED-REQUIREMENTS.md`](../../../docs/ands-portal/ANDS-PLATFORM-LAYERED-REQUIREMENTS.md)

## Context

The ANDS submission portal exists today as a single stdlib-Python HTTP monolith
(`server.py` ~5.6k LOC + ~30 pure domain modules + SQLite, **675 tests green**). It is a
strong *regulatory rehearsal engine* but, per the vision gap doc (REQ-091), not a
production-grade multi-tenant SaaS: no horizontal scale, no async jobs, no per-service
isolation, ephemeral SQLite, and a single deploy blast-radius.

The product owner directed a **full rewrite** to a **microservice** architecture with a
**FastAPI + event-bus + API-gateway** stack.

## Decision

Rewrite the platform as an **event-driven microservice mesh**:

- **One service per bounded context**, each owning its data (Postgres-per-service).
- **FastAPI** for every service's HTTP surface; **Pydantic v2** request/response contracts.
- An **event bus** (Redis Streams in prod; in-memory in dev/test) carries domain events
  (`validation.failed`, `transmission.hc_ack`, `sequence.published`, `collab.task_assigned`, …)
  so services stay decoupled. This directly realizes the vision's webhook catalog (SAAS-REQ-011).
- An **API gateway / BFF** is the single external entry point: authN, routing, and
  cross-service aggregation (e.g. the readiness dashboard).
- **Hexagonal architecture (ports & adapters) + DDD** inside each service:
  `domain` (pure) → `service`/use-cases (pure) → `ports` → `adapters` (sqlite/in-mem for
  dev+test, postgres/redis for prod) → `api` (thin FastAPI). The pure, HC-verified domain
  logic is **ported from the monolith**, not re-derived — regulatory correctness is preserved.

### Why hexagonal is non-negotiable here

The build/CI sandbox runs Python 3.15-alpha with **no Docker, Postgres, or Redis**. The
ports/adapters seam lets the **domain + application + SQLite + in-memory-bus** layers run and
be **fully tested in-sandbox** (FastAPI `TestClient` = real ASGI boot), while the
**Postgres (`pg8000`) + Redis** adapters and `docker-compose`/k8s are the production deploy,
exercised in CI/cloud. Same code, swappable edges.

## Bounded contexts (services)

| Service | Owns (ported monolith modules) | Key events |
|---------|-------------------------------|-----------|
| **collaboration** *(first)* | comments, tasks, notifications (REQ-109) | consumes `validation.failed`, `transmission.hc_ack`; emits `collab.task_assigned` |
| **identity** | auth, tenancy, entitlements, rbac, privacy | `tenant.provisioned`, `user.invited` |
| **dossier** | domain, ectd, backbone, content_model, cv, content_plan (REQ-103), monograph (REQ-098/099), stf | `sequence.published` |
| **validation** | validation, report_ingest, profiles (REQ-102), live (REQ-104) | `validation.completed`, `validation.failed` |
| **lifecycle** | lifecycle, hc_calendar, response_builder | `lifecycle.transitioned` |
| **transmission** | transmission (ESG ride-along) | `transmission.sent`, `transmission.hc_ack` |
| **fees** | fees | `fee.paid` |
| **governance** | esign, retention, dr, audit | `audit.recorded` |
| **readiness (BFF)** | readiness — aggregates via events + gateway | — |
| **document** | object store, PDF remediation (REQ-090/108) — infra-gated | `document.remediated` |

## Consequences

- **+** Independent scale/deploy; clear ownership; event log doubles as a regulatory audit spine.
- **+** First-class fit for the vision's async jobs (validation, packaging, PDF remediation) and webhooks.
- **−** Operational complexity (N services, a bus, a gateway, per-service migrations).
- **−** Full end-to-end (Postgres/Redis/Docker) cannot run in the current sandbox; verified there via the SQLite + in-memory adapters and contract tests, and in CI/cloud via compose.
- The monolith stays as the **675-test oracle** to port from, and is decommissioned per service as each context is drained.

## Migration order

`collaboration` (pattern-defining, by hand) → then fan out `identity`, `dossier`,
`validation`, `lifecycle`, `transmission`, `fees`, `governance`, `readiness` — each: port
domain, add ports/adapters, FastAPI surface, tests (pytest + TestClient), Dockerfile,
compose entry, gateway route.
