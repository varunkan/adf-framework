# Operating ADF from a machine

Every ADF capability is reachable without a dashboard or IDE: the `adf` CLI
prints machine-readable JSON, the orchestration server speaks plain HTTP, and
an MCP server exposes the same operations to agent frameworks. This page is the
contract for scripts, CI jobs, and robots.

## CLI verbs

All verbs talk to the orchestration API at `${ORCH_API_URL:-http://127.0.0.1:3847}`
(start it with `adf start api`). Output rules:

- **Raw JSON to stdout** when `--json` is passed **or stdout is not a TTY** —
  piping into another program always yields the exact API payload.
- A brief human summary otherwise.
- Non-2xx responses and unreachable APIs exit `1`, print the error body (if
  any) to stderr, and hint `adf start api`.
- Override the per-request timeout with `ADF_API_TIMEOUT` (seconds; default 60,
  autopilot defaults to 900 because the crew runs synchronously server-side).

| Verb | What it does |
|------|--------------|
| `adf feature new "<requirement>" [--autopilot]` | `POST /features`; prints the new feature id (full payload in JSON mode). `--autopilot` starts the zero-token crew immediately. |
| `adf feature status <id>` | `GET /features/<id>` merged with `GET /features/<id>/pipeline` under a `pipeline` key. |
| `adf feature autopilot <id>` | `POST /features/<id>/autopilot`; blocks until the crew finishes. |
| `adf feature approve <id> [--phase N]` | `POST /features/<id>/approve`. Without `--phase` the pending approval phase (falling back to the current phase) is read from the feature first. |
| `adf feature cost <id>` | `GET /features/<id>/cost` — per-feature token/cost meter. |
| `adf feature audit <id> [-o FILE]` | `GET /features/<id>/audit-bundle`; with `-o` the raw bundle is written to FILE and a `{"ok": true, "path": …, "bundle_digest": …}` receipt is printed. |
| `adf health` | `GET /health` + `GET /runner/health`, merged as `{"api": …, "runner": …}`. |

Examples:

```bash
# Point every verb at a non-default server.
export ORCH_API_URL=http://127.0.0.1:3847

adf feature new "Add CSV export to the orders screen" --autopilot --json
adf feature status order-csv-export --json | python3 -m json.tool
adf feature approve order-csv-export            # approves the pending phase
adf feature approve order-csv-export --phase 3  # or an explicit phase
adf feature cost order-csv-export
adf feature audit order-csv-export -o audit.json
adf health --json
```

## HTTP API

The CLI is a thin curl wrapper — anything it does, you can do directly:

| Method | Route | Purpose |
|--------|-------|---------|
| `GET` | `/health` | API liveness (`{"status":"ok", …}`). |
| `GET` | `/runner/health` | Agent-runner readiness (`ready`, `runner_label`, `hint`). |
| `POST` | `/features` | Create a feature. Body: `{"requirement": "…", "autopilot": true\|false}` (optional `"id"`, `"track"`). Returns `201` with the detail payload including `id`. |
| `GET` | `/features/<id>` | Full feature detail (`summary`, `state`, `approvals`, `pipeline`, …). `404` if unknown. |
| `GET` | `/features/<id>/pipeline` | Pipeline plan: phases, steps, gate status. |
| `POST` | `/features/<id>/autopilot` | Run the zero-token ADF crew; responds when it completes. |
| `POST` | `/features/<id>/approve` | Body: `{"phase": N, "decision": "approved"\|"revise"\|"rejected", …}`. `409` when judge/artifact gates block (override with `judge_waiver` / `artifact_waiver`). |
| `GET` | `/features/<id>/cost` | Token/cost meter for one feature (`total_usd`, token counts). |
| `GET` | `/cost/summary` | Cost across all features (`total_usd`, `by_feature`). |
| `GET` | `/features/<id>/integrity` | Verify the feature's integrity chain; `?strict=true` forces a full raw-byte re-hash. |
| `GET` | `/features/<id>/audit-bundle` | Self-contained, hash-sealed audit export (below). |

### Audit bundle format (`adf-audit-bundle/1`)

```json
{
  "format": "adf-audit-bundle/1",
  "feature_id": "order-csv-export",
  "created_at": "2026-06-12T10:00:00.000Z",
  "runner": {"runner": "cursor", "runner_label": "Cursor"},
  "chain": { "…full integrity chain file…" },
  "artifacts": [{"path": "specs/…/spec.md", "sha256": "…", "bytes": 1234}],
  "gates": {"spec_approved": true},
  "cost": {"feature_id": "…", "total_usd": 0.42},
  "bundle_digest": "…sha256 hex…"
}
```

`bundle_digest` is the SHA-256 of the canonical JSON of the bundle without the
`bundle_digest` field, so any consumer can recompute and verify it offline.
`chain` is `null` (the digest is still computed) when the feature was never
sealed. Unknown features return `404`.

## MCP registration

ADF also ships an MCP server so Claude Code, Cursor, and other MCP clients can
drive the pipeline as native tools instead of shelling out to curl. See
[`tools/adf_mcp/README.md`](../tools/adf_mcp/README.md) for registration and
the tool catalogue.

## End-to-end robot script

Create a feature, run the crew, poll until the pipeline needs a human (or
finishes), verify the integrity chain, and export the sealed audit bundle:

```bash
#!/usr/bin/env bash
set -euo pipefail
API="${ORCH_API_URL:-http://127.0.0.1:3847}"
export ORCH_API_URL="$API"

# 1. Create (id comes back in the JSON payload — stdout is a pipe, so adf emits JSON).
ID="$(adf feature new "Add CSV export to the orders screen" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')"
echo "feature: $ID"

# 2. Run the zero-token crew end to end.
adf feature autopilot "$ID" > /dev/null

# 3. Poll status until the pipeline completes or waits on a human gate.
while true; do
  STATUS="$(adf feature status "$ID")"
  STATE="$(printf '%s' "$STATUS" | python3 -c \
    'import sys,json; s=json.load(sys.stdin)["summary"]; print(s["status"], s["awaiting_user"] is True)')"
  read -r PIPELINE_STATUS AWAITING <<< "$STATE"
  [[ "$PIPELINE_STATUS" == "completed" ]] && break
  if [[ "$AWAITING" == "True" ]]; then
    adf feature approve "$ID" > /dev/null   # robot approves the pending gate
    continue
  fi
  sleep 5
done

# 4. Verify the integrity chain (strict = full raw-byte re-hash).
curl -sS --fail-with-body "$API/features/$ID/integrity?strict=true" \
  | python3 -c 'import sys,json; r=json.load(sys.stdin); assert r.get("valid") is not False, r; print("integrity OK")'

# 5. Export the sealed audit bundle.
adf feature audit "$ID" -o "audit-$ID.json"
python3 -c "import json; b=json.load(open('audit-$ID.json')); print('digest:', b['bundle_digest'])"
```

Total spend across the run is one call away:

```bash
curl -sS "$API/cost/summary" | python3 -m json.tool
```
