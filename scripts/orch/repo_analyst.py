#!/usr/bin/env python3
"""ADF existing-repo analyst — turn a pointer to an EXISTING local repository into a
compact domain/feature/convention summary for the crew's Wave-1 ingestion. When a user
asks to extend or rebuild an app they already have, the existing code is an authoritative
requirement source, so (like an uploaded doc) it is weighted above web research.

Dependency-light + graceful-degrade discipline, mirroring `doc_ingest.py`: an
unavailable analysis backend yields a NOTE, never a crash.

Analysis backends are tried in order:
  1. `code-review-graph` binary, probed in this order (all OPTIONAL):
       a. `ADF_CODE_REVIEW_GRAPH_BIN` env var (explicit override)
       b. `<repo_root>/.venv-codereview/bin/code-review-graph` (this project's venv)
       c. `shutil.which('code-review-graph')` (PATH lookup)
     Invoked with a bounded timeout (<=30s), `shell=False`, path as a positional arg.
  2. stdlib `os.walk` fallback (ALWAYS available; the PRIMARY path in CI): top-level
     dirs/files + a tally of file extensions. This is the path the tests exercise.

Public API (structurally identical to `doc_ingest`'s surface):
  analyze(path)            -> {kind, text, note}            (text='' + note on degrade)
  ingest(path, complete)   -> {source, kind, requirements, raw, note}

SECURITY: paths are validated for `..` traversal BEFORE any file-read or subprocess
call; the code-review-graph binary is invoked with `shell=False` and the repo path as a
pre-split list element — never interpolated into a shell string.
"""
import os
import shutil
import subprocess
from collections import Counter

_CRG_TIMEOUT = 30  # seconds, bounded per spec R4.
_WALK_MAX_DEPTH = 2
_MAX_ENTRIES = 200  # cap how many names we collect, to keep the summary compact.


def _path_rejected(path):
    """Return a rejection reason string if the path is unsafe, else None. Rejects
    traversal (`..` components) before any file/subprocess access (R8)."""
    if not path or not isinstance(path, str):
        return "rejected: empty or non-string path"
    parts = path.replace("\\", "/").split("/")
    if ".." in parts:
        return "rejected: path traversal ('..') component not allowed"
    return None


def _find_crg_binary():
    """Locate the code-review-graph binary by the spec's probe order, or None."""
    env_bin = os.environ.get("ADF_CODE_REVIEW_GRAPH_BIN")
    if env_bin:
        return env_bin if os.path.isfile(env_bin) else None
    # repo_root is two levels up from this file: scripts/orch/repo_analyst.py
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    venv_bin = os.path.join(repo_root, ".venv-codereview", "bin", "code-review-graph")
    if os.path.isfile(venv_bin):
        return venv_bin
    return shutil.which("code-review-graph")


def _crg_analyze(path):
    """Opportunistically run code-review-graph for a richer summary. Returns (text, note).
    Any failure/timeout returns ('', note) so the caller falls through to the walk."""
    binary = _find_crg_binary()
    if not binary:
        return "", ""
    try:
        proc = subprocess.run(
            [binary, "status", path],
            capture_output=True, text=True, timeout=_CRG_TIMEOUT, shell=False)
        out = (proc.stdout or "").strip()
        if out:
            return out, ""
        return "", "code-review-graph produced no output"
    except Exception as e:  # noqa: BLE001
        return "", f"code-review-graph unavailable: {e}"


def _walk_summary(path):
    """Dependency-light filesystem summary: top-level dirs/files + extension tallies,
    limited to depth 2. Returns (text, note). The PRIMARY path in CI."""
    top = sorted(os.listdir(path))
    top_dirs = [n for n in top if os.path.isdir(os.path.join(path, n))]
    top_files = [n for n in top if os.path.isfile(os.path.join(path, n))]

    ext_counts = Counter()
    file_names = []
    base_depth = path.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(path):
        depth = root.rstrip(os.sep).count(os.sep) - base_depth
        if depth >= _WALK_MAX_DEPTH:
            dirs[:] = []  # prune deeper traversal
        for fn in files:
            ext = os.path.splitext(fn)[1].lower() or "(noext)"
            ext_counts[ext] += 1
            if len(file_names) < _MAX_ENTRIES:
                rel = os.path.relpath(os.path.join(root, fn), path)
                file_names.append(rel)

    lines = [f"Repo: {os.path.basename(path.rstrip(os.sep)) or path}"]
    if top_dirs:
        lines.append("Top-level directories: " + ", ".join(top_dirs))
    if top_files:
        lines.append("Top-level files: " + ", ".join(top_files))
    if ext_counts:
        tally = ", ".join(f"{ext}:{n}" for ext, n in ext_counts.most_common())
        lines.append("File-extension counts: " + tally)
    if file_names:
        lines.append("Files (sample):")
        lines.extend("  " + n for n in file_names)
    return "\n".join(lines), ""


def analyze(path):
    """Produce a compact repo-analysis text (+ a `kind` and a `note` on degrade).

    Tries code-review-graph opportunistically, else the stdlib walk (the primary, always-
    available path). Never raises."""
    rej = _path_rejected(path)
    if rej:
        return {"kind": "repo", "text": "", "note": rej}
    if not os.path.exists(path):
        return {"kind": "repo", "text": "", "note": f"missing repo path: {path}"}
    if not os.path.isdir(path):
        return {"kind": "repo", "text": "", "note": f"not a directory: {path}"}

    crg_text, crg_note = _crg_analyze(path)
    if crg_text:
        return {"kind": "repo", "text": crg_text, "note": ""}

    try:
        text, _note = _walk_summary(path)
    except OSError as e:
        return {"kind": "repo", "text": "", "note": f"repo walk failed: {e}"}
    note = "stdlib os.walk fallback (code-review-graph unavailable)"
    if crg_note:
        note += f" [{crg_note}]"
    return {"kind": "repo", "text": text, "note": note}


def ingest(path, complete=None):
    """Ingest an existing repo into structured requirement text. With a model `complete`,
    it summarizes the existing domain/features/conventions; otherwise returns the raw
    analysis text. Always returns a dict (with a `note` on degrade) — never crashes.

    Returns the same shape `doc_ingest.ingest` returns:
        {source, kind, requirements, raw, note}
    """
    name = os.path.basename(path.rstrip(os.sep)) if isinstance(path, str) and path \
        else (str(path) if path else "")
    try:
        doc = analyze(path)
    except Exception as e:  # noqa: BLE001
        return {"source": name, "kind": "repo", "requirements": "",
                "raw": "", "note": f"repo analysis failed: {e}"}
    raw = (doc["text"] or "").strip()
    if not raw:
        return {"source": name, "kind": "repo", "requirements": "",
                "raw": "", "note": doc["note"]}
    requirements = raw[:8000]
    if complete is not None:
        try:
            prompt = (
                "This is an analysis of an EXISTING repository the user wants to extend "
                "or rebuild. Infer the domain model, existing features, and conventions "
                "as terse bullet points (these are AUTHORITATIVE existing constraints). "
                f"Source: {name}\n\n{raw[:8000]}")
            res = complete(prompt, "draft")
            if res and res[0] and res[0].strip():
                requirements = res[0].strip()
        except Exception:  # noqa: BLE001  (extraction is best-effort; keep the raw text)
            pass
    return {"source": name, "kind": "repo", "requirements": requirements,
            "raw": raw[:8000], "note": doc["note"]}
