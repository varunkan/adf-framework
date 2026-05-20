---
name: orch-telemetry
description: >-
  OpenTelemetry agent observability for orchestration: captures agent reasoning
  (afterAgentThought), tool use, subagents, responses. Query traces, export OTLP.
  Use when debugging agent decisions or auditing a feature run.
---

# OpenTelemetry Telemetry Agent

## What is captured

| Hook event | Span name | Key attributes |
|------------|-----------|----------------|
| `afterAgentThought` | `agent.reasoning` | `agent.reasoning` (full thought text) |
| `afterAgentResponse` | `agent.response` | `agent.response` |
| `preToolUse` / `postToolUse` | `tool.<name>` | `tool.name`, `tool.input`, `tool.output` |
| `subagentStart` / `subagentStop` | `subagent.*` | subagent type, phase, feature |
| `sessionStart` / `sessionEnd` | `session.*` | session boundaries |

Traces are written to:

- `.cursor/orchestration/otel-traces.jsonl` (global)
- `.cursor/orchestration/features/<id>/otel-traces.jsonl` (per feature)

## Before orchestration run

Set session context so spans link to the feature and phase:

```bash
python3 tools/orchestration_telemetry/bin/set_session.py <feature-id> --phase 2 --new-trace
```

Orchestrator should call this at the start of each phase (or on `@orch-orchestrator start`).

## Query reasoning (complete detail)

```bash
# All reasoning spans for a feature
python3 tools/orchestration_telemetry/bin/query_traces.py -f <feature-id> --reasoning-only

# Phase 2 spec review reasoning
python3 tools/orchestration_telemetry/bin/query_traces.py -f <id> --phase 2 --event afterAgentThought

# JSON export
python3 tools/orchestration_telemetry/bin/query_traces.py -f <id> --format json --limit 200
```

## API (orchestration server)

```bash
GET http://127.0.0.1:3847/features/<id>/traces?limit=100&event=afterAgentThought
GET http://127.0.0.1:3847/features/<id>/traces?since=2026-05-17T12:00:00Z  # incremental poll
```

The **orchestration dashboard** feature detail screen polls this endpoint every 1s for live thought display.

## OTLP export (Jaeger / Grafana Tempo)

1. Install deps: `pip install -r tools/orchestration_telemetry/requirements.txt`
2. Start collector (optional Docker):

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
# docker run -p 4318:4318 -v $PWD/tools/orchestration_telemetry/otel-collector-config.yaml:/etc/otelcol/config.yaml otel/opentelemetry-collector:latest
```

3. Hooks auto-export when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.

## Hooks (project)

Configured in [`.cursor/hooks.json`](.cursor/hooks.json) → `.cursor/hooks/orch-otel-ingest.sh <event>`.

View live hook output: Cursor **Hooks** output channel.

## Correlation with orchestration

| Artifact | Purpose |
|----------|---------|
| `otel-traces.jsonl` | Full reasoning + tool timeline |
| `run-log.jsonl` | Raw hook payloads (legacy) |
| `judge-verdicts/` | BMAD review outcomes |
| `state.json` | Phase gates |

Use telemetry when you need **why** the agent chose an action, not just **what** it wrote.
