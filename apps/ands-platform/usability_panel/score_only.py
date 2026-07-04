#!/usr/bin/env python3
"""Score a cached responses file (from a Workflow elicitation) into
results/<tag>_scores.json, WITHOUT re-eliciting.

Decoupled from run_panel.py because elicitation now happens via a Workflow
(Opus respondents), not the in-process Groq client. Sanitizes two things the
gate cares about:

  * spurious `adoption` answers on non-'overall' flows — the adoption construct
    is only asked on 'overall'; some respondent models volunteer it anyway,
    which would pollute the per-persona adoption gate;
  * FILE_UNREADABLE sentinels — a respondent that could not read its stimulus
    file returns the literal string; those cells are dropped (and reported so
    they can be re-run) rather than scored as real dissatisfaction.

    .venv-panel/bin/python score_only.py --tag round7
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from panel import report  # noqa: E402

CONSTRUCTS = ("ease", "clarity", "trust", "adoption")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="round7")
    args = ap.parse_args()

    rp = HERE / "results" / f"{args.tag}_responses.json"
    responses = json.loads(rp.read_text())

    stripped = 0
    unreadable = []
    clean = []
    for r in responses:
        if not r:
            continue
        ans = r.get("answers", {})
        # drop FILE_UNREADABLE cells (any construct carrying the sentinel)
        if any(isinstance(v, str) and "FILE_UNREADABLE" in v
               for k, v in ans.items() if k in CONSTRUCTS):
            unreadable.append((r["persona_id"], r["flow_key"], r["sample"]))
            continue
        # adoption only valid on 'overall'
        if r.get("flow_key") != "overall" and "adoption" in ans:
            del ans["adoption"]
            stripped += 1
        clean.append(r)

    print(f"loaded {len(responses)} responses -> {len(clean)} scorable")
    print(f"stripped {stripped} spurious adoption answers on non-overall flows")
    if unreadable:
        print(f"WARNING: {len(unreadable)} FILE_UNREADABLE cells dropped (re-run these):")
        for u in unreadable:
            print(f"  - {u[0]}/{u[1]}#{u[2]}")

    rows = report.score_responses(clean)
    cells = report.aggregate_cells(rows)
    outp = HERE / "results" / f"{args.tag}_scores.json"
    outp.write_text(json.dumps({"cells": cells, "rows": rows}, indent=1))
    print(f"\nwrote {outp.name} — {len(rows)} construct-rows, {len(cells)} flows")
    for flow, cs in cells.items():
        print(f"  {flow:16s} " + "  ".join(
            f"{c}={a['mean']}" for c, a in cs.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
