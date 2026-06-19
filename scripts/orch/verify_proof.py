#!/usr/bin/env python3
"""Verify an ADF Proof of Build — offline, no network, no key.

    python3 scripts/orch/verify_proof.py <app-dir>
    python3 scripts/orch/verify_proof.py --json <app-dir>      # machine-readable
    python3 scripts/orch/verify_proof.py --trust <pubhex> <app-dir>   # check provenance
    python3 scripts/orch/verify_proof.py --trust <pubhex> --require-trusted <app-dir>
    python3 scripts/orch/verify_proof.py --require-signed <app-dir>   # fail if unsigned
    python3 scripts/orch/verify_proof.py --require-discipline tdd_followed <app-dir>
    python3 scripts/orch/verify_proof.py --keygen [dir]        # make a signing keypair

Recomputes the Merkle seal from the files on disk and reports VERIFIED or
TAMPERED, naming any file that diverges from the sealed build (INTEGRITY — needs
no key). If the proof also carries an optional Ed25519 PROVENANCE signature, the
signature status (and, with --trust, whether the signer is your trusted key) is
reported alongside. Exit 0 = VERIFIED.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proof_of_build as pob  # noqa: E402

_TICK, _CROSS = "✔", "✘"


def _keygen(argv):
    """Write a fresh Ed25519 keypair: <dir>/adf-signing.key (secret, 0600) +
    adf-signing.pub (publishable). Point ADF_SIGNING_KEY at the .key to sign builds."""
    out_dir = argv[0] if argv else ".adf-keys"
    seed_hex, pub_hex = pob.generate_keypair()
    if seed_hex is None:
        print("keygen needs the `cryptography` library (pip install cryptography)",
              file=sys.stderr)
        return 3
    os.makedirs(out_dir, exist_ok=True)
    key_path = os.path.join(out_dir, "adf-signing.key")
    pub_path = os.path.join(out_dir, "adf-signing.pub")
    # Create the SECRET seed with 0600 from the start (O_CREAT mode), so there is no
    # world-readable window between write and chmod.
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(seed_hex + "\n")
    os.chmod(key_path, 0o600)   # tighten too if the file pre-existed loosely
    with open(pub_path, "w", encoding="utf-8") as f:
        f.write(pub_hex + "\n")
    print(f"🔑 signing key  -> {key_path}  (SECRET — keep + git-ignore)")
    print(f"   public key   -> {pub_path}  (publish to pin provenance)")
    print(f"   public hex   :  {pub_hex}")
    print(f"\nSign builds:  export ADF_SIGNING_KEY={key_path}")
    print(f"Verify trust: python3 scripts/orch/verify_proof.py --trust {pub_hex} <app>")
    return 0


def main(argv):
    args = argv[1:]
    if args and args[0] == "--keygen":
        return _keygen(args[1:])
    as_json = require_signed = require_trusted = False
    trusted = None
    require_discipline = []
    rest = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            as_json = True
        elif a == "--require-signed":
            require_signed = True
        elif a == "--require-trusted":
            require_trusted = True
        elif a == "--trust" and i + 1 < len(args):
            trusted = [args[i + 1]]
            i += 1
        elif a == "--require-discipline" and i + 1 < len(args):
            # Repeatable, or comma-separated: --require-discipline tdd_followed,review_passed
            require_discipline += [d for d in args[i + 1].split(",") if d.strip()]
            i += 1
        else:
            rest.append(a)
        i += 1
    args = rest
    if len(args) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    app_dir = args[0]
    ok, r = pob.verify_proof(app_dir, trusted_pubkeys=trusted)
    # Opt-in provenance REQUIREMENTS: a buyer who treats the signature as mandatory
    # can fail the check when it is absent/invalid/untrusted (default stays lenient —
    # integrity-only — so the keyless path is unaffected).
    prov_ok = (not require_signed or r.get("signature") == "valid") and (
        not require_trusted or r.get("signer_trusted") is True)
    # Opt-in PROCESS requirement: a buyer can demand the build was made WITH a given
    # discipline (e.g. tdd_followed), failing the check when the sealed proof doesn't
    # attest it. Default empty => integrity-only, so the keyless path is unaffected.
    import process_facts
    disc_ok, disc_missing = process_facts.required_disciplines_met(
        {"process": r.get("process")}, require_discipline)

    if as_json:
        print(json.dumps({"ok": ok, "provenance_ok": prov_ok,
                          "discipline_ok": disc_ok, "discipline_missing": disc_missing,
                          **r}))
        if r.get("status") == "NO_PROOF":
            return 2
        return 0 if (ok and prov_ok and disc_ok) else 1
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

    # Provenance (optional, additive — never changes the VERIFIED/TAMPERED verdict).
    # A valid signature alone proves NOTHING about authorship unless YOU pin the key
    # with --trust (anyone can self-sign), so unpinned wording is cautionary.
    sig = r.get("signature")
    if sig == "valid":
        who = (f"{r['signer'][:16]}…" if r.get("signer") else "?")
        if r.get("signer_trusted") is True:
            print(f"   {_TICK} signed by TRUSTED key {who} — provenance confirmed")
        elif r.get("signer_trusted") is False:
            print(f"   {_CROSS} signed by UNTRUSTED key {who} — NOT your --trust key")
        else:
            print(f"   ⚠ signed by {who} but UNVERIFIED authorship — anyone can "
                  f"self-sign; pass --trust <pubhex> to confirm it is your key")
    elif sig == "invalid":
        print(f"   {_CROSS} provenance signature INVALID — do NOT trust the signer")
    elif sig == "unverifiable":
        print("   ⚠ signature present but COULD NOT be checked (cryptography lib "
              "missing) — provenance UNVERIFIED; integrity above is unaffected")
    # sig == 'unsigned' => keyless-only, nothing to print.
    if not prov_ok:
        need = "trusted-signed" if require_trusted else "signed"
        print(f"   {_CROSS} required provenance NOT met (--require: {need})")

    # Process discipline (additive — never changes the VERIFIED/TAMPERED verdict).
    # The sealed `process` block is inside the verdict, so it is already covered by
    # the Merkle integrity check above; this just surfaces it for a human auditor.
    disc_line = process_facts.process_summary_line({"process": r.get("process")})
    if disc_line:
        print("   " + disc_line.replace("**", ""))
    if not disc_ok:
        print(f"   {_CROSS} required discipline NOT attested: {', '.join(disc_missing)}")
    return 0 if (ok and prov_ok and disc_ok) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
