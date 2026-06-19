#!/usr/bin/env python3
"""ADF Proof of Build — a tamper-evident certificate shipped INSIDE every
generated app.

The wedge no prompt-to-app competitor serves: an app you can *prove*. After ADF
generates an app and verification passes (build + tests + boot), it seals the app
into a **Merkle root** over (every source file) + (the spec it was built from) +
(the build verdict). The seal, the file hashes, and the provenance (prompt, model,
backend, stack, time) are written to the app as `.adf-proof.json` + a human-readable
`PROOF.md`, with a sealed copy of the spec under `.adf-proof/spec.md`.

Anyone — with no network, no trust in ADF, no secret key — can recompute the seal
from the files on disk and confirm the app is byte-for-byte what ADF built and
proved, or see exactly which file diverged. Pure SHA-256. Offline. Forever.

  compute_proof(...)        -> proof dict (pure; the Merkle math)
  seal_app(app_dir, ...)    -> writes .adf-proof.json + PROOF.md + .adf-proof/spec.md
  verify_proof(app_dir)     -> (ok, report) by recomputing from disk, offline
"""
import hashlib
import json
import os

PROOF_SCHEMA = "adf-proof/1"
PROOF_JSON = ".adf-proof.json"
PROOF_MD = "PROOF.md"
PROOF_DIR = ".adf-proof"
SPEC_LEAF = "@spec"
BUILD_LEAF = "@build"
# Domain separator for the OPTIONAL provenance signature (so an ADF signature can
# never be replayed as a signature over a different protocol's message).
SIG_DOMAIN = "adf-proof-v1:"


def _h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _leaf(path: str, content: bytes) -> str:
    # Domain-separated so a file's bytes can't be confused with a tree node and
    # so path+content are bound together (renaming a file breaks the seal too).
    return _h(b"adf-leaf\x00" + path.encode("utf-8") + b"\x00" + content)


def _merkle_root(leaves) -> str:
    """An order-independent Merkle root over leaf digests. Leaves are sorted (so
    file order never affects the root), paired, and hashed up to a single root.
    The odd leaf at a level is promoted by self-pairing."""
    if not leaves:
        return _h(b"adf-empty")
    level = sorted(leaves)
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            a = level[i]
            b = level[i + 1] if i + 1 < len(level) else level[i]
            nxt.append(_h(b"adf-node\x00" + bytes.fromhex(a) + bytes.fromhex(b)))
        level = nxt
    return level[0]


def _verdict_bytes(stack: str, build: dict) -> bytes:
    """The canonical, sealed subset of the build verdict — the claim being made:
    this stack, verified, with this summary, and (when present) the governance
    policy outcome. Serialized deterministically so it re-seals identically."""
    verdict = {
        "stack": stack,
        "verified": bool(build.get("verified")),
        "verify_summary": build.get("verify_summary", ""),
    }
    if build.get("policy") is not None:
        verdict["policy"] = build["policy"]
    # MM11: seal WHAT render-verified — the platforms the app actually rendered on
    # (web and/or a real iOS device), the proven flag, and the JS bundle size — so
    # "renders on iOS" becomes a cryptographically attested, tamper-evident property.
    if build.get("render") is not None:
        verdict["render"] = build["render"]
    # The engineering DISCIPLINE the app was built with (verify gates, and — when
    # enabled — TDD RED→GREEN, root-cause, review): sealed so "built WITH discipline
    # X" is a recomputable attestation, not a prose claim. Conditional, so any older
    # build (no `process`) re-seals to the byte-identical root.
    if build.get("process") is not None:
        verdict["process"] = build["process"]
    return json.dumps(verdict, sort_keys=True, separators=(",", ":")).encode("utf-8")


# --- OPTIONAL provenance signing (additive; the keyless seal is unchanged) -------
# The keyless Merkle root proves INTEGRITY (these bytes => this root), recomputable
# by anyone offline with no key. An optional detached Ed25519 signature over that
# root adds PROVENANCE (a specific key-holder vouches "I produced this"), for the
# regulated buyer who needs authenticity too. Signing is OFF by default (no key =>
# the pure keyless seal) and degrades gracefully where the crypto lib is absent.

def _ed25519():
    """Lazy, optional. Returns (ed25519_module, serialization) or (None, None) when
    the vetted `cryptography` lib is unavailable — signing then no-ops (keyless
    still works). We use a vetted library, never homemade crypto."""
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives import serialization
        return ed25519, serialization
    except Exception:
        return None, None


def signing_available():
    return _ed25519()[0] is not None


def resolve_signing_seed(env=None):
    """The Ed25519 signing seed (32 bytes) from the environment, or None (keyless,
    the default). ADF_SIGNING_KEY = 64-hex seed, OR a path to a file holding it.
    Signing is OPT-IN — absence keeps the pure keyless seal."""
    env = env if env is not None else os.environ
    val = (env.get("ADF_SIGNING_KEY") or "").strip()
    if not val:
        return None
    if os.path.isfile(val):
        try:
            with open(val, encoding="utf-8") as f:
                val = f.read().strip()
        except (OSError, ValueError):
            # OSError (unreadable) or UnicodeDecodeError (binary/corrupt key file):
            # degrade to keyless rather than aborting the whole seal with a traceback.
            return None
    try:
        seed = bytes.fromhex(val)
    except ValueError:
        return None
    return seed if len(seed) == 32 else None


def generate_keypair():
    """A fresh Ed25519 keypair as (seed_hex, public_hex), or (None, None) if the
    crypto lib is absent. The seed is the 32-byte private key (keep secret); the
    public hex is publishable and pins provenance."""
    ed25519, serialization = _ed25519()
    if ed25519 is None:
        return None, None
    priv = ed25519.Ed25519PrivateKey.generate()
    seed = priv.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption())
    pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return seed.hex(), pub.hex()


def _seed_bytes(seed):
    """Normalize a seed given as 32 raw bytes OR 64 hex chars to bytes, else None."""
    if not seed:
        return None
    if isinstance(seed, str):
        try:
            seed = bytes.fromhex(seed.strip())
        except ValueError:
            return None
    return seed if isinstance(seed, (bytes, bytearray)) and len(seed) == 32 else None


def sign_root(merkle_root, seed):
    """Detached, deterministic (RFC 8032) Ed25519 signature over the Merkle root.
    `seed` may be 32 raw bytes or 64 hex chars. Returns the signature dict, or None
    when there is no usable seed / no crypto lib (so a re-seal stays byte-identical
    and the keyless path is never disturbed)."""
    seed = _seed_bytes(seed)
    if not seed:
        return None
    ed25519, serialization = _ed25519()
    if ed25519 is None:
        return None
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    pub = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    sig = priv.sign((SIG_DOMAIN + merkle_root).encode())
    return {"alg": "ed25519", "domain": SIG_DOMAIN, "signed": "merkle_root",
            "public_key": pub.hex(), "sig": sig.hex()}


def verify_signature(signature, merkle_root):
    """Verify a proof's detached signature over its Merkle root. Returns one of:
    'unsigned' (no signature) | 'valid' | 'invalid' | 'unverifiable' (lib absent)."""
    if not signature:
        return "unsigned"
    ed25519, _ = _ed25519()
    if ed25519 is None:
        return "unverifiable"
    try:
        # PIN the domain to our constant — never trust the proof-supplied `domain`,
        # or an Ed25519 signature made under a foreign protocol's domain could be
        # replayed as ADF provenance. The carried field is documentation only.
        if signature.get("domain", SIG_DOMAIN) != SIG_DOMAIN:
            return "invalid"
        pub = ed25519.Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(signature["public_key"]))
        msg = (SIG_DOMAIN + merkle_root).encode()
        pub.verify(bytes.fromhex(signature["sig"]), msg)
        return "valid"
    except Exception:
        return "invalid"


def compute_proof(feature_id, stack, files, spec_text, build, created_at=None,
                  signing_seed=None):
    """Pure: compute the proof dict from in-memory inputs.

    files: iterable of (relpath, content) where content is str or bytes.
    The Merkle root covers the files + the spec + the build verdict. `created_at`
    and the richer `build` provenance are METADATA — recorded, not in the root —
    so the same app re-seals to the same root regardless of clock or backend."""
    file_entries, leaves = [], []
    for path, content in sorted(files, key=lambda fc: fc[0]):
        cb = content.encode("utf-8") if isinstance(content, str) else content
        file_entries.append({"path": path, "sha256": _h(cb), "bytes": len(cb)})
        leaves.append(_leaf(path, cb))

    spec_b = (spec_text or "").encode("utf-8")
    leaves.append(_leaf(SPEC_LEAF, spec_b))
    verdict_b = _verdict_bytes(stack, build)
    leaves.append(_leaf(BUILD_LEAF, verdict_b))

    root = _merkle_root(leaves)
    proof = {
        "schema": PROOF_SCHEMA,
        "feature_id": feature_id,
        "stack": stack,
        "created_at": created_at,
        "build": {
            "backend": build.get("backend"),
            "model": build.get("model"),
            "verified": bool(build.get("verified")),
            "verify_summary": build.get("verify_summary", ""),
            "prompt": build.get("prompt"),
        },
        "spec_sha256": _h(spec_b),
        "verdict": json.loads(verdict_b),
        "files": file_entries,
        "merkle_root": root,
        "seal": "adf1:" + root[:12],
    }
    # OPTIONAL provenance: a detached signature over the root (NOT folded into the
    # root — it signs it). Absent => the unchanged keyless proof.
    sig = sign_root(root, signing_seed)
    if sig:
        proof["signature"] = sig
    return proof


def _walk_source(app_dir):
    """The app's source surface to seal: reuse the runner's editable-file walker
    (skips deps, build output, caches, lockfiles, dotfiles — so `.adf-proof/` is
    excluded and sealed explicitly instead). Lazy import avoids a load-time cycle."""
    import agent_runner
    return agent_runner.current_app_files(app_dir)


def _render_line(proof):
    """The human line attesting which platforms render-verified (MM11), or ''."""
    render = (proof.get("verdict") or {}).get("render")
    if not (render and render.get("platforms")):
        return ""
    plats = ", ".join(render["platforms"])
    kb = (render.get("js_bytes") or 0) // 1024
    extra = f"  ·  **JS bundle:** {kb} KB" if kb else ""
    return f"**Render-proven on:** {plats}{extra}  "


def _process_line(proof):
    """The human line attesting the disciplines a build was made with (verify gates,
    TDD, root-cause, review), or ''. Lazy import keeps proof_of_build self-contained
    and avoids any load-time cycle (process_facts imports only stdlib)."""
    try:
        import process_facts
        return process_facts.process_summary_line(proof.get("verdict") or {})
    except Exception:
        return ""


def _signature_line(proof):
    """The human line attesting an optional provenance signature, or ''."""
    sig = proof.get("signature")
    if not sig:
        return ""
    return (f"**Signed (provenance):** Ed25519 by `{sig.get('public_key', '')[:16]}…` "
            f"— verify with `--trust <pubkey>`  ")


def render_proof_md(proof):
    b = proof["build"]
    lines = [
        "# 🔏 ADF Proof of Build",
        "",
        f"**Seal:** `{proof['seal']}`  ",
        f"**Merkle root:** `{proof['merkle_root']}`  ",
        f"**App:** `{proof['feature_id']}`  ·  **Stack:** `{proof['stack']}`  ",
        f"**Built:** {proof.get('created_at') or 'n/a'}  ·  "
        f"**Backend:** {b.get('backend') or 'n/a'}  ·  "
        f"**Model:** {b.get('model') or 'n/a'}  ",
        f"**Verified:** {'✅ ' + (b.get('verify_summary') or 'yes') if b.get('verified') else '❌ no'}",
        *([_render_line(proof)] if _render_line(proof) else []),
        *([_process_line(proof)] if _process_line(proof) else []),
        *([_signature_line(proof)] if _signature_line(proof) else []),
        "",
        "This app ships a tamper-evident certificate. The Merkle root above seals "
        "every source file below, the spec it was built from "
        "(`.adf-proof/spec.md`), and the build verdict. Recompute it offline — no "
        "network, no trust in ADF, no key required:",
        "",
        "```",
        "python3 scripts/orch/verify_proof.py <this-app-dir>",
        "```",
        "",
        f"If every byte matches, you get **VERIFIED**. Change one byte of any file "
        f"and the seal turns **TAMPERED** and names the file.",
        "",
        f"## Sealed files ({len(proof['files'])})",
        "",
        "| file | sha256 | bytes |",
        "| --- | --- | --- |",
    ]
    for f in proof["files"]:
        lines.append(f"| `{f['path']}` | `{f['sha256'][:16]}…` | {f['bytes']} |")
    lines += [
        "",
        f"Spec sha256: `{proof['spec_sha256']}`",
        "",
        "_Generated by ADF. Provenance you own — verifiable forever._",
        "",
    ]
    return "\n".join(lines)


def seal_app(app_dir, feature_id, stack, spec_text, build,
             created_at=None, files=None, signing_seed=None):
    """Seal a built app: walk its source, compute the proof, and write
    `.adf-proof.json` + `PROOF.md` + a sealed copy of the spec under
    `.adf-proof/spec.md`. Returns the proof dict. If a signing seed is configured
    (param or ADF_SIGNING_KEY), an Ed25519 provenance signature rides along."""
    if files is None:
        files = _walk_source(app_dir)
    if signing_seed is None:
        signing_seed = resolve_signing_seed()
    proof = compute_proof(feature_id, stack, files, spec_text, build, created_at,
                          signing_seed=signing_seed)

    pdir = os.path.join(app_dir, PROOF_DIR)
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, "spec.md"), "w", encoding="utf-8") as f:
        f.write(spec_text or "")
    with open(os.path.join(app_dir, PROOF_JSON), "w", encoding="utf-8") as f:
        json.dump(proof, f, indent=2, sort_keys=True)
        f.write("\n")
    with open(os.path.join(app_dir, PROOF_MD), "w", encoding="utf-8") as f:
        f.write(render_proof_md(proof))
    return proof


def verify_proof(app_dir, trusted_pubkeys=None):
    """Recompute the seal from the files on disk and compare to the recorded
    proof — fully offline. Returns (ok, report) where report names every file's
    status (ok | modified | missing) and whether the sealed spec and Merkle root
    still hold.

    INTEGRITY (the keyless tamper-evidence) is `ok` and unchanged. PROVENANCE is
    additive + optional: if the proof carries a signature, the report adds
    `signature` (unsigned|valid|invalid|unverifiable), `signer` (public key), and —
    when `trusted_pubkeys` is given — `signer_trusted`. `ok` stays purely about
    integrity so an unsigned proof still VERIFIES; provenance is reported alongside,
    not conflated."""
    pj = os.path.join(app_dir, PROOF_JSON)
    if not os.path.isfile(pj):
        return False, {"status": "NO_PROOF",
                       "reason": f"{PROOF_JSON} not found in {app_dir}"}
    with open(pj, encoding="utf-8") as f:
        proof = json.load(f)

    file_reports, leaves, all_ok = [], [], True
    for entry in proof.get("files", []):
        path = entry["path"]
        disk = os.path.join(app_dir, path)
        if not os.path.isfile(disk):
            file_reports.append({"path": path, "status": "missing"})
            all_ok = False
            continue
        with open(disk, "rb") as fh:
            cb = fh.read()
        actual = _h(cb)
        if actual == entry["sha256"]:
            file_reports.append({"path": path, "status": "ok"})
        else:
            file_reports.append({"path": path, "status": "modified",
                                 "sealed": entry["sha256"], "actual": actual})
            all_ok = False
        leaves.append(_leaf(path, cb))

    # Sealed spec copy (provenance that travels with the app).
    spec_path = os.path.join(app_dir, PROOF_DIR, "spec.md")
    spec_b = b""
    spec_ok = True
    if os.path.isfile(spec_path):
        with open(spec_path, "rb") as fh:
            spec_b = fh.read()
    spec_ok = _h(spec_b) == proof.get("spec_sha256")
    leaves.append(_leaf(SPEC_LEAF, spec_b))

    # Verdict leaf reconstructed from the recorded (and displayed) verdict.
    verdict = proof.get("verdict") or {}
    verdict_b = json.dumps(verdict, sort_keys=True, separators=(",", ":")).encode()
    leaves.append(_leaf(BUILD_LEAF, verdict_b))

    root = _merkle_root(leaves)
    root_ok = root == proof.get("merkle_root")
    ok = all_ok and spec_ok and root_ok

    # Provenance (additive, optional). Verify the signature against the RECOMPUTED
    # root (not the recorded one) so a programmatic caller keying off provenance
    # alone can never trust bytes no longer on disk — a tampered file flips the
    # signature to 'invalid' too.
    sig = proof.get("signature")
    sig_status = verify_signature(sig, root)
    signer = sig.get("public_key") if sig else None
    signer_trusted = None
    # Trust requires a CRYPTOGRAPHICALLY VALID signature: the trusted pubkey is
    # public (it's published to pin provenance), so membership ALONE — without a
    # valid signature over the recomputed root — must never read as trusted.
    if sig_status == "valid" and signer and trusted_pubkeys is not None:
        signer_trusted = (signer.strip().lower()
                          in {k.strip().lower() for k in trusted_pubkeys})

    return ok, {
        "status": "VERIFIED" if ok else "TAMPERED",
        "seal": proof.get("seal"),
        "feature_id": proof.get("feature_id"),
        "stack": proof.get("stack"),
        "expected_root": proof.get("merkle_root"),
        "recomputed_root": root,
        "root_ok": root_ok,
        "spec_ok": spec_ok,
        "files": file_reports,
        "n_files": len(file_reports),
        "n_ok": sum(1 for f in file_reports if f["status"] == "ok"),
        "signature": sig_status,        # unsigned | valid | invalid | unverifiable
        "signer": signer,               # the signing public key (hex), or None
        "signer_trusted": signer_trusted,  # True/False when trusted_pubkeys given
        "process": verdict.get("process"),  # sealed process-discipline facts, or None
    }
