#!/usr/bin/env python3
"""Set orchestration OTEL session context (feature id, phase, optional new trace)."""
from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".cursor" / "orchestration").is_dir():
            return parent
    return Path.cwd()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("feature_id")
    p.add_argument("--phase", type=int, default=None)
    p.add_argument("--new-trace", action="store_true")
    args = p.parse_args()

    root = repo_root()
    path = root / ".cursor" / "orchestration" / "otel-session.json"
    session: dict = {}
    if path.is_file():
        try:
            session = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    if args.new_trace or not session.get("trace_id"):
        session["trace_id"] = uuid.uuid4().hex
    session["feature_id"] = args.feature_id
    if args.phase is not None:
        session["current_phase"] = args.phase

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(session, indent=2))


if __name__ == "__main__":
    main()
