#!/usr/bin/env python3
"""Verify an ADF Proof of Build — offline, no network, no key.

    python3 scripts/orch/verify_proof.py <app-dir>

Recomputes the Merkle seal from the files on disk and reports VERIFIED or
TAMPERED, naming any file that diverges from the sealed build. Exit 0 = VERIFIED.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proof_of_build as pob  # noqa: E402

_TICK, _CROSS = "✔", "✘"


def main(argv):
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    app_dir = argv[1]
    ok, r = pob.verify_proof(app_dir)
    if r.get("status") == "NO_PROOF":
        print(f"NO PROOF: {r['reason']}", file=sys.stderr)
        return 2

    print(f"\U0001F512 ADF Proof of Build — app '{r['feature_id']}' ({r['stack']})")
    print(f"   Seal: {r['seal']}   ({r['n_ok']}/{r['n_files']} files match)")
    for f in r["files"]:
        if f["status"] != "ok":
            extra = ""
            if f["status"] == "modified":
                extra = f" (sealed {f['sealed'][:8]}… now {f['actual'][:8]}…)"
            print(f"   {_CROSS} {f['path']}  {f['status'].upper()}{extra}")
    if not r["spec_ok"]:
        print(f"   {_CROSS} sealed spec (.adf-proof/spec.md) MODIFIED")
    if ok:
        print(f"   {_TICK} spec sealed   {_TICK} Merkle root matches")
        print("   ✅ VERIFIED — byte-for-byte what ADF built and proved. (offline)")
    else:
        print("   ❌ TAMPERED — this app diverges from its sealed build.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
