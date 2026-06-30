# Kubernetes manifests — ANDS platform

A reference deployment topology for the mesh. The full set is intentionally not
checked in verbatim for all 10 services (it's the same block ten times); instead
this provides the shared infra, the **gateway**, and **collaboration** as the
replicable per-service pattern.

## Apply

```bash
kubectl apply -f namespace.yaml
kubectl apply -f redis.yaml
kubectl apply -f collaboration.yaml
kubectl apply -f gateway.yaml
# … one manifest per remaining service (see below)
```

## Replicate for the other services

Copy `collaboration.yaml` and substitute, for each bounded context:

| Service | image | DB name / DSN |
|---------|-------|---------------|
| dossier, validation, identity, lifecycle, transmission, governance, readiness, registry | `ands-platform/<svc>:latest` | `<svc>` |
| **fees** | `ands-platform/fees:latest` | *(none — stateless)*; drop the `-db` Secret/Deployment/Service and the `ANDS_DB_BACKEND`/`ANDS_PG_DSN` env |

Every service image is built from `services/<svc>/Dockerfile` (build context =
`apps/ands-platform`). Push to your registry and update the `image:` fields.

## Notes

- **Persistence**: the DB blocks use `emptyDir` for demo clarity — swap for a
  `StatefulSet` + `PersistentVolumeClaim` (or a managed Postgres) in production.
- **Secrets**: DB creds are inline `stringData` for readability — source them
  from a real secret manager / sealed-secrets in production.
- **Probes**: every service exposes `/health` (liveness/readiness) and `/metrics`
  (Prometheus scrape target — add a `ServiceMonitor` if you run the Prometheus
  Operator).
- **Scale**: the app Deployments are stateless (state lives in Postgres/Redis),
  so `replicas` can be raised freely; the gateway and services are horizontally
  scalable.
