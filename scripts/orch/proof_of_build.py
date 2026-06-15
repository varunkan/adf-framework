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
    return json.dumps(verdict, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_proof(feature_id, stack, files, spec_text, build, created_at=None):
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
    return {
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


def _walk_source(app_dir):
    """The app's source surface to seal: reuse the runner's editable-file walker
    (skips deps, build output, caches, lockfiles, dotfiles — so `.adf-proof/` is
    excluded and sealed explicitly instead). Lazy import avoids a load-time cycle."""
    import agent_runner
    return agent_runner.current_app_files(app_dir)


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
             created_at=None, files=None):
    """Seal a built app: walk its source, compute the proof, and write
    `.adf-proof.json` + `PROOF.md` + a sealed copy of the spec under
    `.adf-proof/spec.md`. Returns the proof dict."""
    if files is None:
        files = _walk_source(app_dir)
    proof = compute_proof(feature_id, stack, files, spec_text, build, created_at)

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


def verify_proof(app_dir):
    """Recompute the seal from the files on disk and compare to the recorded
    proof — fully offline. Returns (ok, report) where report names every file's
    status (ok | modified | missing) and whether the sealed spec and Merkle root
    still hold."""
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
    }
