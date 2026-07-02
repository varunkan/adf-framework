#!/usr/bin/env python3
"""Run the synthetic usability panel end to end.

    .venv-panel/bin/python run_panel.py [--flows f1,f2] [--samples 2] [--tag before]

Raw elicitations are cached per tag in results/<tag>_responses.json so
re-analysis (or SSR-parameter tweaks) never re-pays the LLM calls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from panel import report  # noqa: E402
from panel.elicit import elicit_all  # noqa: E402
from panel.personas import PERSONAS  # noqa: E402


def load_stimuli(only: list[str] | None) -> list[dict]:
    stimuli = []
    for f in sorted((HERE / "stimuli").glob("*.json")):
        s = json.loads(f.read_text())
        if only and s["flow_key"] not in only:
            continue
        stimuli.append(s)
    if not stimuli:
        raise SystemExit("no stimuli found in stimuli/")
    return stimuli


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flows", default="", help="comma-separated flow_keys (default all)")
    ap.add_argument("--samples", type=int, default=2)
    ap.add_argument("--tag", default="before", help="results file prefix")
    ap.add_argument("--reuse", action="store_true",
                    help="skip elicitation, reuse cached responses for this tag")
    args = ap.parse_args()

    only = [f.strip() for f in args.flows.split(",") if f.strip()] or None
    stimuli = load_stimuli(only)
    results_dir = HERE / "results"
    results_dir.mkdir(exist_ok=True)
    raw_path = results_dir / f"{args.tag}_responses.json"

    if args.reuse and raw_path.exists():
        responses = json.loads(raw_path.read_text())
        if only:
            responses = [r for r in responses if r["flow_key"] in only]
        print(f"reusing {len(responses)} cached responses from {raw_path.name}")
    else:
        total = len(PERSONAS) * len(stimuli) * args.samples
        print(f"eliciting {total} responses "
              f"({len(PERSONAS)} personas x {len(stimuli)} flows x {args.samples})...")

        def prog(done: int, all_: int) -> None:
            if done % 10 == 0 or done == all_:
                print(f"  {done}/{all_}", flush=True)

        ckpt = results_dir / f"{args.tag}_checkpoint.json"
        prior = json.loads(ckpt.read_text()) if ckpt.exists() else []
        if prior:
            prior = [r for r in prior if any(
                r["flow_key"] == s["flow_key"] for s in stimuli)]
            print(f"resuming from checkpoint: {len(prior)} already done")
        responses = asyncio.run(elicit_all(
            PERSONAS, stimuli, args.samples, prog,
            checkpoint_path=ckpt, done=prior))
        ckpt.unlink(missing_ok=True)
        # merge into cache so partial runs (--flows) accumulate
        cache = json.loads(raw_path.read_text()) if raw_path.exists() else []
        keep = [r for r in cache
                if not any(r["flow_key"] == s["flow_key"] for s in stimuli)]
        raw_path.write_text(json.dumps(keep + responses, indent=1))

    print("SSR-scoring...")
    rows = report.score_responses(responses)
    cells = report.aggregate_cells(rows)
    print("mining themes...")
    themes = asyncio.run(report.mine_themes(responses))

    (results_dir / f"{args.tag}_scores.json").write_text(json.dumps(
        {"cells": cells, "rows": rows}, indent=1))
    md = report.render_markdown(cells, themes, stimuli, len(responses))
    out = results_dir / f"{args.tag}_report.md"
    out.write_text(md)
    print(f"\nwrote {out}")
    for flow, cs in cells.items():
        print(f"  {flow:16s} " + "  ".join(
            f"{c}={a['mean']}" for c, a in cs.items()))


if __name__ == "__main__":
    main()
