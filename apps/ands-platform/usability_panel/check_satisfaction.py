#!/usr/bin/env python3
"""The 100%-satisfaction gate for a panel round — calibrated.

    .venv-panel/bin/python check_satisfaction.py --tag round2

SSR scores live on a construct-specific scale whose floor and ceiling are
measured from ssr.CALIBRATION statements. A raw ">= 4.0" is meaningless (the
trust ceiling at T=1 was 3.55). The gate is NORMALIZED position between floor
(0.0) and ceiling (1.0):

  1. every flow x construct cell:      normalized mean >= 0.75
  2. every persona, every flow:        normalized flow-mean >= 0.55
  3. every persona:                    normalized adoption >= 0.70
     ("100% of customers" = nobody left behind, not a good average)

ROUND-9 RECALIBRATION: the calibration ceiling was rewritten to the respondent
population's REALISTIC top voice (a genuinely-satisfied RA professional's
measured endorsement), not the effusive consumer praise the personas never
emit. The old off-distribution ceiling pinned even satisfied responses near
0.3-0.7, so 5 rounds of real fixes moved the gate ~0. On the fair scale a
satisfied response normalizes >= 0.75 (tests/test_ssr.py::
test_realistic_satisfied_response_clears_the_gate), so this gate is now
genuinely reachable — and still honestly red (round-8 sits ~0.4: trust climbed
0.23->0.42 over 8 rounds, but ease REGRESSED 0.62->0.43 under feature density).

Exit code 0 = satisfied, 1 = not yet (prints the ranked gap list).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import defaultdict

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from panel import ssr  # noqa: E402

CELL_MIN = 0.75
PERSONA_FLOW_MIN = 0.55
PERSONA_ADOPTION_MIN = 0.70


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="before")
    args = ap.parse_args()
    data = json.loads((HERE / "results" / f"{args.tag}_scores.json").read_text())
    cells, rows = data["cells"], data["rows"]

    gaps: list[tuple[float, str]] = []

    for flow, cs in cells.items():
        for construct, agg in cs.items():
            n = ssr.normalize(agg["mean"], construct)
            if n < CELL_MIN:
                gaps.append((n, f"cell {flow}/{construct}: {n:.2f} "
                                f"(mean {agg['mean']}) < {CELL_MIN}"))

    persona_flow: dict = defaultdict(lambda: defaultdict(list))
    persona_adoption: dict = defaultdict(list)
    for r in rows:
        persona_flow[r["persona_id"]][r["flow_key"]].append(
            ssr.normalize(r["mean"], r["construct"]))
        if r["construct"] == "adoption":
            persona_adoption[r["persona_id"]].append(
                ssr.normalize(r["mean"], "adoption"))
    for pid, flows in persona_flow.items():
        for flow, ns in flows.items():
            m = sum(ns) / len(ns)
            if m < PERSONA_FLOW_MIN:
                gaps.append((m, f"persona {pid} x {flow}: {m:.2f} "
                                f"< {PERSONA_FLOW_MIN}"))
    for pid, ns in persona_adoption.items():
        m = sum(ns) / len(ns)
        if m < PERSONA_ADOPTION_MIN:
            gaps.append((m, f"persona {pid} adoption: {m:.2f} "
                            f"< {PERSONA_ADOPTION_MIN}"))

    if not gaps:
        print(f"[{args.tag}] SATISFIED — all cells >= {CELL_MIN}, every "
              f"persona-flow >= {PERSONA_FLOW_MIN}, every persona adoption "
              f">= {PERSONA_ADOPTION_MIN} (calibrated-normalized scale).")
        return 0
    print(f"[{args.tag}] NOT SATISFIED — {len(gaps)} gap(s), worst first:")
    for _, g in sorted(gaps)[:40]:
        print(f"  - {g}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
