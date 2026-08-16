#!/usr/bin/env python3
"""Export a generated app as a portable, **self-verifying** zip: the full source
+ the sealed audit bundle + the Proof of Build (which already lives in the app as
`.adf-proof.json` / `PROOF.md`). The ownership half of the moat — your code, your
machine, and you can prove it elsewhere with no ADF and no network.

Heavy build dirs (node_modules, dist) and the live DB (data.db + WAL) are excluded
so the zip stays portable; `npm ci` reconstructs node_modules from the lockfile.

    python3 scripts/orch/export_app.py --app apps/<id> --out <dest.zip> \
        [--bundle audit-bundle.json] [--id <id>] [--json]
"""
import argparse
import json
import os
import sys
import zipfile

EXCLUDE_DIRS = {"node_modules", "dist", ".git", "__pycache__",
                ".adf-export", ".adf-exports"}
EXCLUDE_EXT = (".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3")

README = """# {id} — exported by ADF

A self-contained, **self-verifying** export of an app ADF generated. Your code,
your machine — verify and run it with no ADF and no network.

## Verify it (offline)
- `audit-bundle.json` — the sealed audit bundle: integrity chain + artifact hashes
  + the moat (Proof of Build seal, policy verdict, compaction). Verify with
  `verify_audit_bundle.py audit-bundle.json` (python3 stdlib only).
- `app/.adf-proof.json` + `app/PROOF.md` — the Proof of Build. Recompute the Merkle
  root over `app/`'s source and compare: VERIFIED or TAMPERED-naming-the-file.

## Run it
    cd app && npm ci && npm run build && PORT=8000 node server/index.mjs
"""


def collect(app_dir):
    """(abs_path, relpath) for every source file, minus heavy/build/live-DB files."""
    out = []
    for root, dirs, files in os.walk(app_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fn in sorted(files):
            if fn.endswith(EXCLUDE_EXT):
                continue
            fp = os.path.join(root, fn)
            out.append((fp, os.path.relpath(fp, app_dir)))
    return out


def export_app(app_dir, out_zip, audit_bundle=None, feature_id=None):
    files = collect(app_dir)
    parent = os.path.dirname(out_zip)
    if parent:
        os.makedirs(parent, exist_ok=True)
    n = 0
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for fp, rel in files:
            z.write(fp, arcname=os.path.join("app", rel))
            n += 1
        if audit_bundle is not None:
            z.writestr("audit-bundle.json", json.dumps(audit_bundle, indent=2))
            n += 1
        z.writestr("README.md",
                   README.format(id=feature_id or os.path.basename(app_dir)))
        n += 1
    return {"ok": True, "out": out_zip, "files": n,
            "bytes": os.path.getsize(out_zip)}


def _main(argv=None):
    ap = argparse.ArgumentParser(description="Export a generated app as a zip")
    ap.add_argument("--app", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bundle", help="path to an audit-bundle JSON to embed")
    ap.add_argument("--id")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    bundle = None
    if args.bundle and os.path.isfile(args.bundle):
        with open(args.bundle, encoding="utf-8") as f:
            bundle = json.load(f)

    if not os.path.isdir(args.app):
        report = {"ok": False, "error": f"no app at {args.app}"}
    else:
        report = export_app(args.app, args.out, bundle, args.id)

    if args.json:
        print(json.dumps(report))
    elif report["ok"]:
        print(f"exported {report['files']} entries -> {report['out']} "
              f"({report['bytes']} bytes)")
    else:
        print(report.get("error", "export failed"), file=sys.stderr)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(_main())
