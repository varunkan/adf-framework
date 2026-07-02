#!/usr/bin/env python3
"""Before/after comparison of two panel rounds.

    .venv-panel/bin/python compare_rounds.py --a before --b round2

Prints the flow x construct delta table (mean shifts), distribution moves
(bottom-2 / top-2), and per-persona adoption movement — the proof that a fix
round actually moved the synthetic customers.
"""

from __future__ import annotations

import argparse
import json
import pathlib
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent


def _load(tag: str) -> dict:
    return json.loads((HERE / "results" / f"{tag}_scores.json").read_text())


def _persona_adoption(rows: list[dict]) -> dict[str, float]:
    acc: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r["construct"] == "adoption":
            acc[r["persona_id"]].append(r["mean"])
    return {p: sum(v) / len(v) for p, v in acc.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="before")
    ap.add_argument("--b", default="round2")
    args = ap.parse_args()
    A, B = _load(args.a), _load(args.b)

    print(f"=== {args.a} -> {args.b}: flow x construct mean deltas ===")
    print(f"{'flow':16s} {'construct':9s} {args.a:>7s} {args.b:>7s} {'delta':>7s}")
    worse = 0
    for flow, cs in sorted(B["cells"].items()):
        for construct, agg in cs.items():
            old = (A["cells"].get(flow) or {}).get(construct)
            if not old:
                print(f"{flow:16s} {construct:9s} {'new':>7s} {agg['mean']:7.2f}")
                continue
            d = agg["mean"] - old["mean"]
            mark = " ▲" if d > 0.05 else (" ▼ REGRESSION" if d < -0.05 else "")
            if d < -0.05:
                worse += 1
            print(f"{flow:16s} {construct:9s} {old['mean']:7.2f} "
                  f"{agg['mean']:7.2f} {d:+7.2f}{mark}")

    print("\n=== bottom-2 share (dissatisfied mass) ===")
    for flow, cs in sorted(B["cells"].items()):
        for construct, agg in cs.items():
            old = (A["cells"].get(flow) or {}).get(construct)
            if old:
                print(f"{flow:16s} {construct:9s} "
                      f"{old['bottom2']:6.1%} -> {agg['bottom2']:6.1%}")

    print("\n=== per-persona adoption movement ===")
    pa, pb = _persona_adoption(A["rows"]), _persona_adoption(B["rows"])
    for pid in sorted(set(pa) | set(pb)):
        a, b = pa.get(pid), pb.get(pid)
        if a is not None and b is not None:
            print(f"{pid:28s} {a:5.2f} -> {b:5.2f} ({b - a:+.2f})")

    print(f"\n{worse} regressed cell(s)" if worse
          else "\nno regressed cells")


if __name__ == "__main__":
    main()
