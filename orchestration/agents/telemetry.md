# Agent: Telemetry (OpenTelemetry)

**Role:** Observability for agent reasoning, tool calls, and subagent workflows.

**Skill:** `orch-telemetry`

**Captures:** `afterAgentThought`, `afterAgentResponse`, `preToolUse`, `postToolUse`, `subagentStart`, `subagentStop`

**Outputs:** `otel-traces.jsonl` (OTEL-shaped spans with `agent.reasoning`, `tool.*` attributes)

**Query:**

```bash
python3 tools/orchestration_telemetry/bin/query_traces.py -f <feature-id> --reasoning-only
```

**Not a pipeline phase** — runs continuously via Cursor hooks during orchestration.
