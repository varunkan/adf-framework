# Orchestration OpenTelemetry

Captures **complete agent reasoning** via Cursor hooks into OTEL-shaped JSONL spans.

## Quick start

Hooks are enabled in [`.cursor/hooks.json`](../../.cursor/hooks.json). Restart Cursor after changes.

```bash
# Start feature trace
python3 tools/orchestration_telemetry/bin/set_session.py my-feature --phase 1 --new-trace

# After agent work — query reasoning
python3 tools/orchestration_telemetry/bin/query_traces.py -f my-feature --reasoning-only

# API (with orchestration server running)
curl 'http://127.0.0.1:3847/features/my-feature/traces?reasoning_only=true&limit=50'
```

## What you get

Each `afterAgentThought` hook produces a span with attribute `agent.reasoning` containing the model's thought text. Tool calls include `tool.name`, `tool.input`, `tool.output`.

## OTLP (optional)

```bash
pip install -r tools/orchestration_telemetry/requirements.txt
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
```

Use [otel-collector-config.yaml](otel-collector-config.yaml) with Docker OpenTelemetry Collector for Jaeger/Grafana.

## Skill

`@orch-telemetry` — see [`.cursor/skills/orch-telemetry/SKILL.md`](../../.cursor/skills/orch-telemetry/SKILL.md)
