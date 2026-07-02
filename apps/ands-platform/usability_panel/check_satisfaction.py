#!/usr/bin/env python3
"""The 100%-satisfaction gate for a panel round.

    .venv-panel/bin/python check_satisfaction.py --tag before

Criterion (all must hold):
  1. every flow x construct cell mean >= 4.0
  2. bottom-2-box share <= 5% in every cell
  3. every persona individually: adoption >= 4.0 AND no flow-mean < 3.5
     ("100% of customers" = nobody left behind, not a good average)

Exit code 0 = satisfied, 1 = not yet (prints the ranked gap list).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent

CELL_MEAN_MIN = 4.0
BOTTOM2_MAX = 0.05
PERSONA_ADOPTION_MIN = 4.0
PERSONA_FLOW_MIN = 3.5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="before")
    args = ap.parse_args()
    data = json.loads((HERE / "results" / f"{args.tag}_scores.json").read_text())
    cells, rows = data["cells"], data["rows"]

    gaps: list[tuple[float, str]] = []   # (severity-sort-key, description)

    # 1+2 — survey cells
    for flow, cs in cells.items():
        for construct, agg in cs.items():
            if agg["mean"] < CELL_MEAN_MIN:
                gaps.append((agg["mean"],
                             f"cell {flow}/{construct}: mean {agg['mean']} "
                             f"< {CELL_MEAN_MIN}"))
            if agg["bottom2"] > BOTTOM2_MAX:
                gaps.append((4.0 - agg["bottom2"],
                             f"cell {flow}/{construct}: bottom-2 share "
                             f"{agg['bottom2']:.0%} > {BOTTOM2_MAX:.0%}"))

    # 3 — per-persona floors
    persona_flow: dict = defaultdict(lambda: defaultdict(list))
    persona_adoption: dict = defaultdict(list)
    for r in rows:
        persona_flow[r["persona_id"]][r["flow_key"]].append(r["mean"])
        if r["construct"] == "adoption":
            persona_adoption[r["persona_id"]].append(r["mean"])
    for pid, flows in persona_flow.items():
        for flow, means in flows.items():
            m = sum(means) / len(means)
            if m < PERSONA_FLOW_MIN:
                gaps.append((m, f"persona {pid} rates {flow} at {m:.2f} "
                                f"< {PERSONA_FLOW_MIN}"))
    for pid, means in persona_adoption.items():
        m = sum(means) / len(means)
        if m < PERSONA_ADOPTION_MIN:
            gaps.append((m, f"persona {pid} adoption {m:.2f} "
                            f"< {PERSONA_ADOPTION_MIN}"))

    if not gaps:
        print(f"[{args.tag}] SATISFIED — every cell >= {CELL_MEAN_MIN}, "
              f"bottom-2 <= {BOTTOM2_MAX:.0%}, every persona adoption >= "
              f"{PERSONA_ADOPTION_MIN} with no flow < {PERSONA_FLOW_MIN}.")
        return 0
    print(f"[{args.tag}] NOT SATISFIED — {len(gaps)} gap(s), worst first:")
    for _, g in sorted(gaps)[:40]:
        print(f"  - {g}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
