#!/usr/bin/env python3
"""Resumable panel driver — merges Workflow elicitation output to disk and
computes the still-missing (persona x flow x sample) cells, so a mid-run
credit-out never loses progress.

  python panel_driver.py missing <tag> [dir]     -> JSON of missing jobs
  python panel_driver.py merge   <tag> <output>  -> merge successes, print coverage
  python panel_driver.py cover   <tag>           -> coverage summary

A "job" is {persona_id, flow_key, sample}. The full grid is 12 personas x
8 flows x 2 samples = 192.
"""
from __future__ import annotations
import json
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from panel.personas import PERSONAS  # noqa: E402

FLOWS = ["onboarding", "journey", "catalog", "builder_forms",
         "ai_draft", "validate_export", "operations", "overall"]
PIDS = [p["id"] for p in PERSONAS]
SAMPLES = 2


def _path(tag: str) -> pathlib.Path:
    return HERE / "results" / f"{tag}_responses.json"


def _load(tag: str) -> list[dict]:
    p = _path(tag)
    return json.loads(p.read_text()) if p.exists() else []


def _key(r: dict) -> tuple:
    return (r["persona_id"], r["flow_key"], r["sample"])


def _extract(obj) -> list[dict]:
    """Pull the response list out of a workflow task-output wrapper or raw list."""
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        if "result" in obj:  # task-output wrapper
            res = obj["result"]
            res = json.loads(res) if isinstance(res, str) else res
            return _extract(res)
        for k in ("responses", "round4", "round3_opus", "jobs"):
            if k in obj and isinstance(obj[k], list):
                return obj[k]
    raise SystemExit(f"cannot find response list in {type(obj)}")


def missing(tag: str) -> None:
    done = {_key(r) for r in _load(tag)}
    jobs = [{"persona_id": p, "flow_key": f, "sample": s}
            for p in PIDS for f in FLOWS for s in range(SAMPLES)
            if (p, f, s) not in done]
    print(json.dumps(jobs))


def cover(tag: str) -> None:
    resp = _load(tag)
    done = {_key(r) for r in resp}
    total = len(PIDS) * len(FLOWS) * SAMPLES
    print(f"[{tag}] {len(done)}/{total} cells done")
    per = Counter(r["persona_id"] for r in resp)
    incomplete = [p for p in PIDS if per.get(p, 0) < len(FLOWS) * SAMPLES]
    if incomplete:
        print("  incomplete personas: " +
              ", ".join(f"{p}({per.get(p,0)}/{len(FLOWS)*SAMPLES})"
                        for p in incomplete))
    else:
        print("  all 12 personas complete")


def merge(tag: str, output: str) -> None:
    raw = json.loads(pathlib.Path(output).read_text())
    new = [r for r in _extract(raw) if r]
    cur = _load(tag)
    by = {_key(r): r for r in cur}
    added = 0
    for r in new:
        k = _key(r)
        if k not in by:
            by[k] = r
            added += 1
    merged = list(by.values())
    _path(tag).write_text(json.dumps(merged, indent=1))
    print(f"merged +{added} (had {len(cur)}, now {len(merged)})")
    cover(tag)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "missing":
        missing(sys.argv[2])
    elif cmd == "cover":
        cover(sys.argv[2])
    elif cmd == "merge":
        merge(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(f"unknown cmd {cmd}")
