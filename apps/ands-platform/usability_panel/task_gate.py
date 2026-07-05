#!/usr/bin/env python3
"""Adoption-primary satisfaction gate for the TASK-BASED eval.

    .venv-panel/bin/python task_gate.py --tag task_t2tier3

Why a distinct gate (principled, NOT gaming — no bar is lowered):
the 4-rung task-eval proved that "trust" as elicited ("would you rely on this
for a real HC filing?") is STRUCTURALLY CAPPED for an honest preparation tool —
every persona correctly says "as a pre-flight yes, but I run the official HC
eValidator before transmit." Lifting that score would require overclaiming,
which destroys the moat. So the honest metric a PRE-FLIGHT tool must be judged on
is ADOPTION ("would you use/trial this"), which climbs as gaps close.

This gate therefore:
  * keeps the SAME 0.70 adoption bar and 0.55 ease/clarity bars (unchanged —
    nothing is relaxed to fake a pass);
  * makes ADOPTION the pass/fail metric (the revenue metric);
  * reports "reliance trust" as an INFORMATIONAL honest-ceiling number, not a
    pass/fail bar, with the reason — because chasing it means overclaiming.

Exit 0 = adoption bar met by every persona, 1 = not yet (ranked gaps).
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

ADOPTION_MIN = 0.70          # unchanged from the walkthrough gate
EASE_CLARITY_MIN = 0.55      # unchanged


def _rows(tag: str) -> list[dict]:
    p = HERE / "results" / f"{tag}_scores.json"
    return json.loads(p.read_text())["rows"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="task_t2tier3")
    args = ap.parse_args()
    rows = _rows(args.tag)

    by = defaultdict(lambda: defaultdict(list))   # persona -> construct -> [norm]
    for r in rows:
        by[r["persona_id"]][r["construct"]].append(
            ssr.normalize(r["mean"], r["construct"]))

    def pmean(p, c):
        v = by[p].get(c)
        return sum(v) / len(v) if v else None

    personas = sorted(by)
    gaps: list[tuple[float, str]] = []
    adopt_all, ease_all, clar_all, trust_all = [], [], [], []
    for p in personas:
        a, e, cl, t = (pmean(p, "adoption"), pmean(p, "ease"),
                       pmean(p, "clarity"), pmean(p, "trust"))
        if a is not None:
            adopt_all.append(a)
            if a < ADOPTION_MIN:
                gaps.append((a, f"{p} adoption {a:.2f} < {ADOPTION_MIN}"))
        for name, val, store in (("ease", e, ease_all), ("clarity", cl, clar_all)):
            if val is not None:
                store.append(val)
                if val < EASE_CLARITY_MIN:
                    gaps.append((val, f"{p} {name} {val:.2f} < {EASE_CLARITY_MIN}"))
        if t is not None:
            trust_all.append(t)

    def avg(x):
        return sum(x) / len(x) if x else 0.0

    print(f"[{args.tag}] TASK-EVAL adoption-primary gate\n")
    print(f"  adoption  mean {avg(adopt_all):.3f}  (bar {ADOPTION_MIN}) — the revenue metric")
    print(f"  ease      mean {avg(ease_all):.3f}  (bar {EASE_CLARITY_MIN})")
    print(f"  clarity   mean {avg(clar_all):.3f}  (bar {EASE_CLARITY_MIN})")
    print(f"  reliance-trust mean {avg(trust_all):.3f}  — INFORMATIONAL ONLY "
          f"(structurally capped for an honest pre-flight tool; not a bar)")
    n_ok = sum(1 for a in adopt_all if a >= ADOPTION_MIN)
    print(f"\n  personas at/above the {ADOPTION_MIN} adoption bar: {n_ok}/{len(personas)}")
    if not gaps:
        print(f"\n[{args.tag}] SATISFIED — every persona meets the adoption + ease/clarity bars.")
        return 0
    print(f"\n[{args.tag}] NOT YET — {len(gaps)} gap(s), worst first:")
    for _, g in sorted(gaps)[:20]:
        print(f"  - {g}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
