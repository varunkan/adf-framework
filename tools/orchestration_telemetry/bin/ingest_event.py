#!/usr/bin/env python3
"""
Ingest Cursor hook JSON → OpenTelemetry spans + JSONL trace log.

Environment:
  OTEL_HOOK_EVENT   — hook name (afterAgentThought, postToolUse, …)
  ORCH_REPO_ROOT    — repo root (optional; auto-detected)
  OTEL_EXPORTER_OTLP_ENDPOINT — if set, also export spans via OTLP HTTP

Stdout: always {} for hook compatibility.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOOK_EVENT = os.environ.get("OTEL_HOOK_EVENT", "unknown")


def repo_root() -> Path:
    env = os.environ.get("ORCH_REPO_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".cursor" / "orchestration").is_dir():
            return parent
    return Path.cwd()


def load_session(root: Path) -> dict[str, Any]:
    path = root / ".cursor" / "orchestration" / "otel-session.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {
        "trace_id": uuid.uuid4().hex,
        "feature_id": None,
        "current_phase": None,
        "spans": {},
    }


def save_session(root: Path, session: dict[str, Any]) -> None:
    path = root / ".cursor" / "orchestration" / "otel-session.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")


def active_feature_id(root: Path) -> str | None:
    features = root / ".cursor" / "orchestration" / "features"
    if not features.is_dir():
        return None
    for d in sorted(features.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        state_file = d / "state.json"
        if not state_file.is_file():
            continue
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            if state.get("status") == "active":
                return d.name
        except json.JSONDecodeError:
            continue
    return None


def extract_reasoning(payload: dict[str, Any]) -> str | None:
    for key in (
        "thought",
        "thinking",
        "reasoning",
        "content",
        "text",
        "message",
        "agent_message",
    ):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # Nested
    for key in ("data", "payload", "body"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            r = extract_reasoning(nested)
            if r:
                return r
    return None


def extract_tool_info(payload: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    name = payload.get("tool_name") or payload.get("toolName") or payload.get("name")
    if not name and isinstance(payload.get("tool"), dict):
        name = payload["tool"].get("name")
    inp = payload.get("tool_input") or payload.get("toolInput") or payload.get("input") or {}
    out = payload.get("tool_output") or payload.get("toolOutput") or payload.get("output")
    extra: dict[str, Any] = {}
    if isinstance(inp, dict):
        extra["tool.input"] = json.dumps(inp, default=str)[:8000]
    if out is not None:
        extra["tool.output"] = json.dumps(out, default=str)[:8000]
    return (str(name) if name else None, extra)


def span_name(event: str, payload: dict[str, Any]) -> str:
    if event == "afterAgentThought":
        return "agent.reasoning"
    if event == "afterAgentResponse":
        return "agent.response"
    if event in ("preToolUse", "postToolUse", "postToolUseFailure"):
        tool, _ = extract_tool_info(payload)
        return f"tool.{tool or 'unknown'}"
    if event in ("subagentStart", "subagentStop"):
        t = payload.get("subagent_type") or payload.get("subagentType") or "subagent"
        return f"subagent.{t}.{event}"
    if event == "sessionStart":
        return "session.start"
    if event == "sessionEnd":
        return "session.end"
    return f"hook.{event}"


def build_attributes(
    event: str,
    payload: dict[str, Any],
    feature_id: str | None,
    phase: Any,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "hook.event": event,
        "cursor.hook": True,
    }
    if feature_id:
        attrs["orch.feature_id"] = feature_id
    if phase is not None:
        attrs["orch.phase"] = phase

    reasoning = extract_reasoning(payload)
    if reasoning:
        attrs["agent.reasoning"] = reasoning[:32000]

    response = payload.get("response") or payload.get("assistant_message")
    if isinstance(response, str) and response.strip():
        attrs["agent.response"] = response.strip()[:32000]

    tool_name, tool_extra = extract_tool_info(payload)
    if tool_name:
        attrs["tool.name"] = tool_name
    attrs.update(tool_extra)

    for k in ("subagent_type", "subagentType", "model", "command", "status"):
        if k in payload and payload[k] is not None:
            attrs[f"cursor.{k}"] = str(payload[k])[:2000]

    return attrs


def write_jsonl(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def maybe_otlp_export(record: dict[str, Any]) -> None:
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            resource = Resource.create(
                {"service.name": "ai-pos-orchestration", "cursor.agent": True}
            )
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)

        tracer = trace.get_tracer("orch-telemetry")
        attrs = record.get("attributes", {})
        with tracer.start_as_current_span(record.get("name", "hook.event")) as span:
            for k, v in attrs.items():
                span.set_attribute(k, v)
    except ImportError:
        pass
    except Exception:
        pass


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {"_raw": raw}

    root = repo_root()
    session = load_session(root)
    feature_id = session.get("feature_id") or active_feature_id(root)
    phase = session.get("current_phase")

    span_id = uuid.uuid4().hex[:16]
    parent = session.get("active_span_id")
    now = datetime.now(timezone.utc).isoformat()

    attrs = build_attributes(HOOK_EVENT, payload, feature_id, phase)
    record = {
        "timestamp": now,
        "trace_id": session.get("trace_id"),
        "span_id": span_id,
        "parent_span_id": parent,
        "name": span_name(HOOK_EVENT, payload),
        "kind": "INTERNAL",
        "status": "ERROR" if HOOK_EVENT == "postToolUseFailure" else "OK",
        "attributes": attrs,
        "hook_payload": payload,
    }

    # Global orchestration trace log
    global_log = root / ".cursor" / "orchestration" / "otel-traces.jsonl"
    write_jsonl(record, global_log)

    # Per-feature trace log
    if feature_id:
        feat_log = (
            root
            / ".cursor"
            / "orchestration"
            / "features"
            / feature_id
            / "otel-traces.jsonl"
        )
        write_jsonl(record, feat_log)

    # Keep subagent spans as parent for nested tool calls
    if HOOK_EVENT == "subagentStart":
        session["active_span_id"] = span_id
    elif HOOK_EVENT == "subagentStop":
        session["active_span_id"] = session.get("parent_span_id")

    save_session(root, session)
    maybe_otlp_export(record)

    print("{}")


if __name__ == "__main__":
    main()
