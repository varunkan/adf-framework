#!/usr/bin/env python3
"""Standalone verifier for ADF audit bundles (adf-audit-bundle/1).

One machine proves to another what was built: the orchestration server
exports a bundle from GET /features/<id>/audit-bundle and this script checks
it anywhere python3 exists — no server, no Dart, stdlib only.

Checks performed:
  1. bundle_digest — recomputed by replicating the Dart server's canonical
     JSON encoding (IntegrityChain.canonical: top-level keys sorted, compact
     separators, Dart-VM number/string formatting) byte-for-byte.
  2. chain integrity — every block's block_hash, prev_hash linkage back to
     "genesis", and manifest_root are recomputed from the contained blocks.
  3. artifacts — the bundle's artifact list must equal the chain's sealed
     manifest; with --repo, each artifact is re-hashed against a checkout.

Exit codes: 0 valid, 1 tampered/invalid, 2 usage error.

Usage:
  verify_audit_bundle.py [--json] [--repo PATH] BUNDLE.json
  verify_audit_bundle.py --self-test
"""

import argparse
import hashlib
import json
import math
import os
import sys

FORMAT = "adf-audit-bundle/1"

REQUIRED_KEYS = (
    "format",
    "feature_id",
    "created_at",
    "runner",
    "chain",
    "artifacts",
    "gates",
    "cost",
    "bundle_digest",
)


# ---------------------------------------------------------------------------
# Canonical JSON encoding — byte-for-byte replica of Dart's
# IntegrityChain.canonical (sorted top-level keys + dart:convert jsonEncode).
# ---------------------------------------------------------------------------

def dart_double_repr(value):
    """Render a float exactly as Dart-VM jsonEncode does.

    The Dart VM follows the ECMAScript Number-to-String algorithm (shortest
    round-trip digits, decimal notation for exponents in (-7, 21), bare
    exponents like 1e-7 / 1e+21) and additionally appends ".0" to integral
    values rendered in decimal notation. Python's repr() also produces the
    shortest round-trip digits but pads exponents (1e-07) and switches to
    exponential notation at different thresholds, so the digits are re-laid
    out here per the ECMAScript rules.
    """
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError("non-finite numbers are not valid JSON")
    if value == 0.0:
        return "-0.0" if math.copysign(1.0, value) < 0 else "0.0"
    sign = "-" if value < 0 else ""
    text = repr(abs(value))
    if "e" in text:
        mantissa, _, exp_text = text.partition("e")
        exponent = int(exp_text)
    else:
        mantissa, exponent = text, 0
    int_part, _, frac_part = mantissa.partition(".")
    digits = int_part + frac_part
    point = len(int_part) + exponent  # value == 0.digits * 10**point
    stripped = digits.lstrip("0")
    point -= len(digits) - len(stripped)
    digits = stripped.rstrip("0")
    n, k = point, len(digits)
    if k <= n <= 21:
        body = digits + "0" * (n - k) + ".0"  # integral decimal gets ".0"
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        head = digits[0] + ("." + digits[1:] if k > 1 else "")
        body = "%se%s%d" % (head, "+" if e >= 0 else "-", abs(e))
    return sign + body


_SHORT_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def _encode_string(s):
    """Dart jsonEncode string rules: short escapes, \\u00xx for other
    control characters, everything else (including non-ASCII) literal."""
    out = ['"']
    for ch in s:
        esc = _SHORT_ESCAPES.get(ch)
        if esc is not None:
            out.append(esc)
        elif ord(ch) < 0x20:
            out.append("\\u%04x" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _encode_value(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, str):
        return _encode_string(v)
    if isinstance(v, int):  # bool already handled above
        return str(v)
    if isinstance(v, float):
        return dart_double_repr(v)
    if isinstance(v, dict):
        return "{" + ",".join(
            _encode_string(k) + ":" + _encode_value(val) for k, val in v.items()
        ) + "}"
    if isinstance(v, list):
        return "[" + ",".join(_encode_value(item) for item in v) + "]"
    raise TypeError("unencodable value of type %s" % type(v).__name__)


def canonical(obj):
    """Replica of IntegrityChain.canonical: only the TOP-LEVEL keys are
    sorted; nested maps keep their document order (json.load preserves it,
    matching the insertion order Dart hashed). Dart sorts by UTF-16 code
    units; all contract keys are ASCII, where that equals Python's sort."""
    if not isinstance(obj, dict):
        raise TypeError("canonical() takes a JSON object")
    return _encode_value(dict(sorted(obj.items(), key=lambda kv: kv[0])))


def sha256_hex_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_hex_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_bundle(bundle, repo=None):
    """Returns (valid, checks) where checks is a list of
    {"check": str, "ok": bool, "detail": str}."""
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return ok

    if not isinstance(bundle, dict):
        add("structure", False, "bundle is not a JSON object")
        return False, checks
    missing = [k for k in REQUIRED_KEYS if k not in bundle]
    if not add(
        "structure",
        not missing,
        "all %d contract fields present" % len(REQUIRED_KEYS)
        if not missing
        else "missing fields: %s" % ", ".join(missing),
    ):
        return False, checks

    add(
        "format",
        bundle["format"] == FORMAT,
        "format is %r" % bundle["format"],
    )

    body = {k: v for k, v in bundle.items() if k != "bundle_digest"}
    try:
        recomputed = sha256_hex_text(canonical(body))
        add(
            "bundle_digest",
            recomputed == bundle["bundle_digest"],
            "recomputed %s, bundle says %s"
            % (recomputed[:12], str(bundle["bundle_digest"])[:12]),
        )
    except (TypeError, ValueError) as e:
        add("bundle_digest", False, "cannot canonicalize bundle: %s" % e)

    chain = bundle["chain"]
    artifacts = bundle["artifacts"] if isinstance(bundle["artifacts"], list) else None
    if artifacts is None:
        add("artifacts", False, "artifacts is not a list")
    if chain is None:
        add("chain_links", True, "feature was never sealed (chain: null)")
        if artifacts is not None:
            add(
                "artifacts_match_manifest",
                artifacts == [],
                "no sealed manifest, so the artifact list must be empty"
                if artifacts == []
                else "%d artifacts listed without a sealed manifest" % len(artifacts),
            )
    elif not isinstance(chain, list) or not chain:
        add("chain_links", False, "chain must be null or a non-empty block list")
    else:
        problems = []
        prev_hash = "genesis"
        for i, block in enumerate(chain):
            if not isinstance(block, dict):
                problems.append("block %d is not an object" % i)
                break
            block_body = {k: v for k, v in block.items() if k != "block_hash"}
            try:
                if sha256_hex_text(canonical(block_body)) != block.get("block_hash"):
                    problems.append("block %d: block_hash mismatch (rewritten)" % i)
                manifest = block.get("manifest")
                if not isinstance(manifest, dict):
                    problems.append("block %d: manifest missing" % i)
                elif sha256_hex_text(canonical(manifest)) != block.get("manifest_root"):
                    problems.append("block %d: manifest_root mismatch" % i)
            except (TypeError, ValueError) as e:
                problems.append("block %d: cannot canonicalize: %s" % (i, e))
            if block.get("prev_hash") != prev_hash:
                problems.append("block %d: prev_hash linkage broken" % i)
            prev_hash = block.get("block_hash")
        add(
            "chain_links",
            not problems,
            "%d blocks hash-linked back to genesis" % len(chain)
            if not problems
            else "; ".join(problems),
        )

        if artifacts is not None:
            last = chain[-1] if isinstance(chain[-1], dict) else {}
            manifest = last.get("manifest")
            sealed = sorted(manifest.items()) if isinstance(manifest, dict) else []
            listed = sorted(
                (a.get("path"), a.get("sha256"))
                for a in artifacts
                if isinstance(a, dict)
            )
            add(
                "artifacts_match_manifest",
                listed == sealed and len(listed) == len(artifacts),
                "%d artifacts equal the sealed manifest" % len(sealed)
                if listed == sealed and len(listed) == len(artifacts)
                else "artifact list disagrees with the sealed manifest",
            )

    if repo is not None and artifacts is not None:
        bad = []
        for a in artifacts:
            if not isinstance(a, dict):
                bad.append("malformed artifact entry")
                continue
            path = os.path.join(repo, a.get("path", ""))
            if not os.path.isfile(path):
                bad.append("%s: missing from checkout" % a.get("path"))
            elif sha256_hex_file(path) != a.get("sha256"):
                bad.append("%s: content drifted from sealed hash" % a.get("path"))
        add(
            "repo_artifacts",
            not bad,
            "%d artifacts re-hashed against %s" % (len(artifacts), repo)
            if not bad
            else "; ".join(bad),
        )

    # The moat, attested in the same sealed document (added 2026-06): Proof of
    # Build seal + policy verdict + compaction summary. Already digest-covered;
    # this adds a semantic sanity check. Absent/null is fine (older bundles, or a
    # feature that was never built into an app).
    moat = bundle.get("moat")
    if moat in (None, {}):
        add("moat_attested", True, "no per-app moat (feature not built into an app)")
    elif not isinstance(moat, dict):
        add("moat_attested", False, "moat is present but not an object")
    else:
        problems = []
        proof = moat.get("proof")
        if proof is not None:
            seal = proof.get("seal")
            if not (isinstance(seal, str) and seal.startswith("adf1:")):
                problems.append("proof seal malformed (%r)" % seal)
            # 'root' key populated by audit_bundle.dart from proof['merkle_root']
            # per proof_of_build.py:238 (SSOT). When present and non-null it
            # binds the full 256-bit Merkle root: it must be 64 lowercase hex
            # chars AND seal == 'adf1:' + root[:12] (seal derivation per
            # proof_of_build.py:239). Absent/null root is a soft pass (legacy
            # bundles exported before this binding landed).
            root = proof.get("root")
            if root is not None:
                if not (isinstance(root, str) and len(root) == 64
                        and all(c in "0123456789abcdef" for c in root)):
                    problems.append("proof root malformed (%r)" % root)
                elif seal != "adf1:" + root[:12]:
                    problems.append(
                        "proof seal/root mismatch: seal=%r root_prefix=%r"
                        % (seal, root[:12])
                    )
        policy = moat.get("policy")
        if policy is not None and not isinstance(policy.get("ok"), bool):
            problems.append("policy verdict is not a boolean")
        parts = []
        if proof is not None:
            parts.append("proof %s" % proof.get("seal"))
        if policy is not None:
            parts.append(
                "policy %s" % ("compliant" if policy.get("ok") else "VIOLATIONS"))
        if moat.get("context") is not None:
            parts.append("%s compaction card(s)" % moat["context"].get("cards"))
        add("moat_attested", not problems,
            ("; ".join(problems)) if problems
            else ("attested: " + ", ".join(parts) if parts else "moat present"))

    return all(c["ok"] for c in checks), checks


# ---------------------------------------------------------------------------
# Self-test — fixtures generated by the Dart server's own encoder, so the
# canonical replication is pinned byte-for-byte.
# ---------------------------------------------------------------------------

# Output of Dart-VM jsonEncode for each double (verified against dart 3.x).
_DART_DOUBLE_FIXTURES = [
    (1.0, "1.0"),
    (6.0, "6.0"),
    (0.0, "0.0"),
    (-0.0, "-0.0"),
    (0.1, "0.1"),
    (0.04, "0.04"),
    (-0.5, "-0.5"),
    (0.0001, "0.0001"),
    (1e-05, "0.00001"),
    (2.3e-05, "0.000023"),
    (1e-06, "0.000001"),
    (1e-07, "1e-7"),
    (-1e-07, "-1e-7"),
    (1.5e-07, "1.5e-7"),
    (3.141592653589793, "3.141592653589793"),
    (123456789012345.0, "123456789012345.0"),
    (1e20, "100000000000000000000.0"),
    (1e21, "1e+21"),
    (2e22, "2e+22"),
]

# Produced by IntegrityChain.canonical / hashString on the Dart VM for the
# fixture object below — the ground truth this script must reproduce.
_DART_CANONICAL_FIXTURE = (
    '{"alpha":{"unsorted_z":1.0,"unsorted_a":[true,null,"café €\\n",'
    "0.000001,1e-7,1e+21,100000000000000000000.0,-0.5,0.000023,6.0,42]},"
    '"mid":"a\\"b\\\\c\\td","zeta":1}'
)
_DART_CANONICAL_SHA256 = (
    "ca7f68784e8937c59528260c388e45b0acf5c10f1dee5095360c907fe10cc34d"
)


def _self_test_bundle():
    """Builds a synthetic, internally consistent bundle the same way the
    Dart server does, so end-to-end verification can be exercised offline."""
    manifest = {"specs/x/spec.md": hashlib.sha256(b"spec").hexdigest()}
    gates = {"tests_green": True, "review_approved": False}
    prev_hash = "genesis"
    chain = []
    for index in range(2):
        body = {
            "index": index,
            "ts": "2026-06-12T00:00:0%d.000Z" % index,
            "feature": "x",
            "phase": index + 1,
            "actor": "adf",
            "manifest": manifest,
            "manifest_root": sha256_hex_text(canonical(manifest)),
            "gates_hash": sha256_hex_text(canonical(gates)),
            "prev_hash": prev_hash,
        }
        block = dict(body, block_hash=sha256_hex_text(canonical(body)))
        chain.append(block)
        prev_hash = block["block_hash"]
    bundle = {
        "format": FORMAT,
        "feature_id": "x",
        "created_at": "2026-06-12T00:00:02.000Z",
        "runner": {"runner": "cursor", "runner_label": "Cursor CLI (cursor-agent)"},
        "chain": chain,
        "artifacts": [
            {"path": "specs/x/spec.md", "sha256": manifest["specs/x/spec.md"], "bytes": 4},
        ],
        "gates": gates,
        "cost": {"feature_id": "x", "total_usd": 0.042, "runs": []},
    }
    bundle["bundle_digest"] = sha256_hex_text(canonical(bundle))
    return bundle


def self_test():
    failures = []

    def check(name, actual, expected):
        if actual != expected:
            failures.append("%s: got %r, want %r" % (name, actual, expected))

    for value, expected in _DART_DOUBLE_FIXTURES:
        check("dart_double_repr(%r)" % value, dart_double_repr(value), expected)

    fixture = {
        "zeta": 1,
        "alpha": {
            "unsorted_z": 1.0,
            "unsorted_a": [
                True, None, "café €\n", 1e-06, 1e-07, 1e21, 1e20, -0.5,
                2.3e-05, 6.0, 42,
            ],
        },
        "mid": 'a"b\\c\td',
    }
    check("canonical(fixture)", canonical(fixture), _DART_CANONICAL_FIXTURE)
    check(
        "sha256(canonical(fixture))",
        sha256_hex_text(canonical(fixture)),
        _DART_CANONICAL_SHA256,
    )

    # Round-trip: a serialized-then-parsed bundle must keep its digest.
    bundle = _self_test_bundle()
    reparsed = json.loads(json.dumps(bundle))
    valid, checks = verify_bundle(reparsed)
    check("synthetic bundle verifies", valid, True)

    tampered = json.loads(json.dumps(bundle))
    tampered["gates"]["review_approved"] = True  # one-byte flip
    valid, checks = verify_bundle(tampered)
    check("tampered gates detected", valid, False)
    check(
        "tampered gates failing check",
        [c["check"] for c in checks if not c["ok"]],
        ["bundle_digest"],
    )

    forged = json.loads(json.dumps(bundle))
    forged["chain"][0]["actor"] = "attacker"
    forged_body = {k: v for k, v in forged.items() if k != "bundle_digest"}
    forged["bundle_digest"] = sha256_hex_text(canonical(forged_body))
    valid, checks = verify_bundle(forged)  # digest fixed up, links must fail
    check("rewritten chain block detected", valid, False)
    check(
        "rewritten chain failing check",
        [c["check"] for c in checks if not c["ok"]],
        ["chain_links"],
    )

    unsealed = {
        k: (None if k in ("chain", "cost") else v) for k, v in bundle.items()
    }
    unsealed["artifacts"] = []
    body = {k: v for k, v in unsealed.items() if k != "bundle_digest"}
    unsealed["bundle_digest"] = sha256_hex_text(canonical(body))
    valid, _ = verify_bundle(json.loads(json.dumps(unsealed)))
    check("unsealed bundle (chain: null) verifies", valid, True)

    if failures:
        for f in failures:
            print("FAIL %s" % f, file=sys.stderr)
        print("self-test: %d failure(s)" % len(failures), file=sys.stderr)
        return 1
    print("self-test: all checks passed")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Verify an ADF audit bundle (adf-audit-bundle/1) offline.",
    )
    parser.add_argument("bundle", nargs="?", help="path to the bundle JSON file")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--repo", metavar="PATH", help="re-hash artifacts against this checkout")
    parser.add_argument("--self-test", action="store_true", help="run the built-in encoder/verifier tests")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.bundle:
        parser.error("a bundle file is required (or use --self-test)")
    if args.repo and not os.path.isdir(args.repo):
        parser.error("--repo path is not a directory: %s" % args.repo)

    try:
        with open(args.bundle, encoding="utf-8") as f:
            raw = f.read()
    except OSError as e:
        parser.error("cannot read bundle: %s" % e)

    try:
        bundle = json.loads(raw)
    except ValueError as e:
        if args.json:
            print(json.dumps({"valid": False, "error": "not JSON: %s" % e}))
        else:
            print("TAMPERED: bundle is not valid JSON: %s" % e, file=sys.stderr)
        return 1

    valid, checks = verify_bundle(bundle, repo=args.repo)

    if args.json:
        print(json.dumps({
            "valid": valid,
            "bundle": args.bundle,
            "feature_id": bundle.get("feature_id") if isinstance(bundle, dict) else None,
            "bundle_digest": bundle.get("bundle_digest") if isinstance(bundle, dict) else None,
            "moat": bundle.get("moat") if isinstance(bundle, dict) else None,
            "checks": checks,
        }))
    else:
        if isinstance(bundle, dict):
            print("audit bundle: %s" % args.bundle)
            print("feature: %s  created: %s  runner: %s" % (
                bundle.get("feature_id"),
                bundle.get("created_at"),
                (bundle.get("runner") or {}).get("runner_label")
                if isinstance(bundle.get("runner"), dict) else None,
            ))
        for c in checks:
            print("  [%s] %s: %s" % ("ok" if c["ok"] else "FAIL", c["check"], c["detail"]))
        print("VALID" if valid else "TAMPERED")
    return 0 if valid else 1


if __name__ == "__main__":
    sys.exit(main())
