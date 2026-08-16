#!/usr/bin/env python3
"""ADF test agent: duplicate code / UI-component reuse enforcement.

The rule the user wants enforced: if a UI component (or code block) is created for
one feature, the SAME component must be reused — not copy-pasted. This agent finds
near-identical blocks repeated across the app and flags them as reuse violations,
so the heal loop extracts a shared component/helper instead of duplicating.

Detects:
  - duplicated CODE blocks (>= MIN_LINES normalized lines appearing in 2+ places)
  - duplicated UI MARKUP blocks (repeated HTML fragments — a component not reused)

Contract: prints {"agent","ok","findings":[{severity,title,detail,location}],"summary"}.
"""
import hashlib
import json
import os
import re
import sys

MIN_LINES = 8       # a duplicated run of >= this many normalized lines is a finding
MIN_CHARS = 200     # ...and at least this many chars (ignore trivial repetition)
MARKUP_MIN = 220    # repeated HTML fragment length that signals an un-reused component
MAX_FINDINGS = 40


def _norm(line):
    return re.sub(r"\s+", " ", line.strip())


def _code_dups(files):
    # window-hash normalized non-blank lines; report windows seen in 2+ locations
    seen = {}
    findings = []
    for path, text in files:
        lines = [(_norm(l), i + 1) for i, l in enumerate(text.splitlines())]
        lines = [(l, n) for (l, n) in lines if l and not l.startswith(("#", "//", "*"))]
        for i in range(0, max(0, len(lines) - MIN_LINES + 1)):
            window = lines[i:i + MIN_LINES]
            blob = "\n".join(l for (l, _n) in window)
            if len(blob) < MIN_CHARS:
                continue
            h = hashlib.sha1(blob.encode()).hexdigest()
            loc = f"{os.path.basename(path)}:{window[0][1]}"
            seen.setdefault(h, []).append(loc)
    reported = set()
    for h, locs in seen.items():
        uniq = sorted(set(locs))
        if len(uniq) >= 2 and h not in reported:
            reported.add(h)
            # 3+ copies of a real block is an unambiguous reuse violation (block);
            # a 2-place dup is worth flagging but advisory.
            sev = "high" if len(uniq) >= 3 else "medium"
            findings.append({
                "severity": sev,
                "title": "Duplicated code block (extract a shared helper and reuse it)",
                "detail": f"a {MIN_LINES}+-line block is repeated in {len(uniq)} places",
                "location": ", ".join(uniq[:5]),
            })
    return findings


def _markup_dups(html):
    # repeated sizable HTML fragments => a component that was copy-pasted, not reused
    findings = []
    frags = re.findall(r"<(div|section|article|form|li|tr|fieldset)\b[^>]*>.*?</\1>",
                       html, re.S | re.I)
    counts = {}
    for f in frags:
        key = re.sub(r"\s+", " ", f).strip()
        if len(key) >= MARKUP_MIN:
            counts[key] = counts.get(key, 0) + 1
    for key, c in counts.items():
        if c >= 2:
            snippet = re.sub(r"<[^>]+>", "", key)[:60].strip()
            sev = "high" if c >= 3 else "medium"
            findings.append({
                "severity": sev,
                "title": "Repeated UI markup — make it a reusable component, render it N times",
                "detail": f'identical {len(key)}-char fragment rendered {c}x ("{snippet}…")',
                "location": "server.py / index.html (UI template)",
            })
    return findings


# Vendored deps / build output / VCS / caches — NOT app-authored code. Duplication
# inside third-party bundles (rollup, vite, chokidar, …) or compiled output is not a
# reuse violation the heal loop can or should fix, so never scan these.
_SKIP_DIRS = {
    "node_modules", "dist", "build", "out", ".next", "coverage",
    ".venv", "venv", "__pycache__", ".git", ".cache", "vendor",
}


def run(app_dir):
    code_files, html = [], ""
    for root, dirs, names in os.walk(app_dir):
        # prune vendored/build/cache dirs in place so os.walk doesn't descend into them
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".adf-")]
        if any(s in root for s in (".adf-", "__pycache__", ".git")) or \
                any(part in _SKIP_DIRS for part in root.split(os.sep)):
            continue
        for n in names:
            # Skip test files: duplicated test setup is expected and DRY-ing tests
            # to death hurts readability — reuse enforcement targets shipped code.
            if n.startswith("test_") or n.endswith(("_test.py", ".spec.js", ".test.js")):
                continue
            p = os.path.join(root, n)
            try:
                t = open(p, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            if n.endswith(".py"):
                code_files.append((p, t))
                html += "\n".join(re.findall(r'"""(.*?)"""|\'\'\'(.*?)\'\'\'', t, re.S)
                                  and [m for pair in re.findall(r'"""(.*?)"""', t, re.S) for m in [pair]] or [])
            elif n.endswith((".html", ".js")):
                code_files.append((p, t))
                if n.endswith(".html"):
                    html += t
    # also pull HTML embedded in python triple-quoted strings
    for p, t in code_files:
        if p.endswith(".py"):
            for m in re.findall(r'(?:"""|\'\'\')(.*?)(?:"""|\'\'\')', t, re.S):
                if "<" in m and ">" in m:
                    html += "\n" + m
    findings = _code_dups(code_files) + _markup_dups(html)
    findings = findings[:MAX_FINDINGS]
    return {
        "agent": "duplicate-components",
        "ok": len(findings) == 0,
        "findings": findings,
        "summary": f"{len(findings)} duplication/reuse issue(s) across "
                   f"{len(code_files)} files",
    }


if __name__ == "__main__":
    print(json.dumps(run(os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")), indent=2))
