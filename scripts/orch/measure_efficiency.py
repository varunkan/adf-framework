#!/usr/bin/env python3
"""ADF efficiency measurement harness (Task 5).

Reads the per-turn cost ledger (`cost.json` `runs[]`, written by CostMeter) for a
feature and reports the two honest axes — COST (tokens / $ / cache-hit) and
WALL-CLOCK (per-turn latency from `at` deltas) — over a window of turns.

Use for a controlled A/B: snapshot the turn-count before a config's run, run the
slice, then `--since <count>` to score just that config's turns.

    # baseline: note current turn count
    python3 scripts/orch/measure_efficiency.py --feature unit-converter --count
    # ...run the slice under a config..., then score the new turns:
    python3 scripts/orch/measure_efficiency.py --feature unit-converter --since 12 --label C1-resume

No external deps (stdlib only). $ figures are the API-equivalent the CLI reports;
the $0 subscription path still records them, so they are valid for RELATIVE A/B.
"""
import argparse, json, os, statistics, sys
from datetime import datetime

FW = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _runs(feature):
    p = os.path.join(FW, ".adf", "orchestration", "features", feature, "cost.json")
    if not os.path.exists(p):
        sys.exit(f"no cost.json for feature '{feature}' ({p})")
    return json.load(open(p)).get("runs", [])

def _ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def measure(runs, label):
    n = len(runs)
    g = lambda k: sum(int(r.get(k, 0) or 0) for r in runs)
    tin, tout = g("input_tokens"), g("output_tokens")
    ccreate, cread = g("cache_creation_input_tokens"), g("cache_read_input_tokens")
    usd = sum(float(r.get("usd", 0) or 0) for r in runs)
    denom = max(1, cread + ccreate + tin)
    # per-turn wall-clock from consecutive `at` deltas
    gaps = []
    times = [_ts(r.get("at", "")) for r in runs]
    for a, b in zip(times, times[1:]):
        if a and b:
            gaps.append((b - a).total_seconds())
    row = {
        "label": label, "turns": n,
        "usd_total": round(usd, 4), "usd_per_turn": round(usd / max(1, n), 4),
        "input_tokens": tin, "output_tokens": tout,
        "cache_creation": ccreate, "cache_read": cread,
        "cache_hit_rate": round(cread / denom, 4),
        "cache_create_per_turn": round(ccreate / max(1, n)),
        "median_turn_gap_s": round(statistics.median(gaps), 1) if gaps else None,
    }
    return row

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feature", default="ands-submission-portal")
    ap.add_argument("--since", type=int, default=0, help="score only runs[since:]")
    ap.add_argument("--label", default="window")
    ap.add_argument("--count", action="store_true", help="just print the turn count")
    a = ap.parse_args()
    runs = _runs(a.feature)
    if a.count:
        print(len(runs)); return
    row = measure(runs[a.since:], a.label)
    print(json.dumps(row, indent=2))

if __name__ == "__main__":
    main()
