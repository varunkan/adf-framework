#!/usr/bin/env python3
"""Per-persona satisfaction scorecard — proves (or disproves) the "100% of
personas satisfied" mandate for a round, persona by persona.

    .venv-panel/bin/python persona_scorecard.py --tag round4

For each of the 12 personas it prints their normalized flow means, adoption,
and a PASS/FAIL against the same calibrated gate thresholds as
check_satisfaction.py (cell>=0.75 is a per-cell check; here we roll up per
persona: every flow >=0.55 and adoption >=0.70). A persona is SATISFIED only
if none of their flows and their adoption fall short.
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
from panel.personas import PERSONAS  # noqa: E402

PERSONA_FLOW_MIN = 0.55
PERSONA_ADOPTION_MIN = 0.70
FLOWS = ["onboarding", "journey", "catalog", "builder_forms",
         "ai_draft", "validate_export", "operations", "overall"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="round4")
    args = ap.parse_args()
    rows = json.loads((HERE / "results" / f"{args.tag}_scores.json")
                      .read_text())["rows"]

    pf: dict = defaultdict(lambda: defaultdict(list))
    pa: dict = defaultdict(list)
    for r in rows:
        pf[r["persona_id"]][r["flow_key"]].append(
            ssr.normalize(r["mean"], r["construct"]))
        if r["construct"] == "adoption":
            pa[r["persona_id"]].append(ssr.normalize(r["mean"], "adoption"))

    order = [p["id"] for p in PERSONAS]
    hdr = f"{'persona':26}" + "".join(f"{f[:4]:>5}" for f in FLOWS) + \
        f"{'adopt':>7}  verdict"
    print(f"[{args.tag}] per-persona calibrated satisfaction "
          f"(flow>= {PERSONA_FLOW_MIN}, adoption>= {PERSONA_ADOPTION_MIN})")
    print(hdr)
    print("-" * len(hdr))
    satisfied = 0
    for pid in order:
        flows = pf.get(pid, {})
        cells = []
        ok = True
        for f in FLOWS:
            ns = flows.get(f)
            if not ns:
                cells.append(f"{'--':>5}")
                continue
            m = sum(ns) / len(ns)
            if m < PERSONA_FLOW_MIN:
                ok = False
            cells.append(f"{m:5.2f}")
        adopt = sum(pa[pid]) / len(pa[pid]) if pa.get(pid) else 0.0
        if adopt < PERSONA_ADOPTION_MIN:
            ok = False
        satisfied += ok
        mark = "SATISFIED" if ok else "fail"
        print(f"{pid:26}" + "".join(cells) + f"{adopt:7.2f}  {mark}")
    print("-" * len(hdr))
    print(f"SATISFIED PERSONAS: {satisfied}/{len(order)} "
          f"({100*satisfied//len(order)}%)")
    return 0 if satisfied == len(order) else 1


if __name__ == "__main__":
    sys.exit(main())
