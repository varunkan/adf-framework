#!/usr/bin/env python3
"""Run the benchmark: evaluate built apps on the capability + governance axes and
write a results JSON the scorecard reads.

By default it scores whatever apps already exist under <repo>/apps/. With --build
it drives the full ADF pipeline for each suite prompt first (slow; needs a model
backend + npm) — that's how the capability axes (builds, tests-pass, time) are
measured for real. The governance axes are always real and offline.

    python3 scripts/bench/run_bench.py [--repo R] [--app DIR ...] [--out F] [--json]
    python3 scripts/bench/run_bench.py --build        # full pipeline (slow)
"""
import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import evaluate  # noqa: E402


def _app_dirs(repo, explicit):
    if explicit:
        return [os.path.abspath(d) for d in explicit]
    return sorted(d for d in glob.glob(os.path.join(repo, "apps", "*"))
                  if os.path.isdir(d))


def run(repo, app_dirs):
    results = [evaluate.evaluate_app(repo, d) for d in app_dirs]
    return {"results": results, "summary": evaluate.summarize(results)}


def _main(argv=None):
    ap = argparse.ArgumentParser(description="ADF benchmark runner")
    ap.add_argument("--repo", default=ROOT)
    ap.add_argument("--app", action="append", dest="apps",
                    help="evaluate a specific app dir (repeatable)")
    ap.add_argument("--out", help="write the results JSON here")
    ap.add_argument("--build", action="store_true",
                    help="build the full suite via the pipeline first (slow)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.build:
        print("--build drives the full ADF pipeline per prompt (model + npm); "
              "run it where a backend is configured. Scoring existing apps now.",
              file=sys.stderr)

    dirs = _app_dirs(args.repo, args.apps)
    report = run(args.repo, dirs)

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    if args.json:
        print(json.dumps(report))
    else:
        s = report["summary"]
        print(f"apps scored: {s['apps']}")
        print(f"  governed (proven+compliant+offline): {s['governed']}/{s['apps']}")
        print(f"  proven:    {s['proven']}/{s['apps']}")
        print(f"  compliant: {s['compliant']}/{s['apps']}")
        print(f"  offline:   {s['offline']}/{s['apps']}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
