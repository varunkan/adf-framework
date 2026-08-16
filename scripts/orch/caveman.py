#!/usr/bin/env python3
"""Caveman — deterministic brevity for ADF ("why use many token when few token do
trick"). A rule-based, model-free compressor that strips FILLER from PROSE while
preserving every byte that carries meaning: code, identifiers, numbers, URLs, the
`<<<FILE:>>>` markers, and — per caveman's OWN exception — anything
SECURITY/GOVERNANCE/CRITICAL, which is never compressed.

Why this is safe for ADF specifically: ADF's model OUTPUT is CODE (the deliverable)
and it SEALS governance artifacts (the moat). Neither is ever touched. Caveman applies
only to PROSE seams — instructional boilerplate, recall guidance — to trim INPUT tokens
across the 9-phase pipeline. Measured, not assumed: estimate_savings + the bench A/B it
before raising intensity. Default OFF (ADF_CAVEMAN unset).

  intensity(env)            -> 'off' | 'lite' | 'full'
  compress(text, level)     -> terser PROSE (raw rule engine; pass-through for 'off')
  compress_prose(text, env) -> GUARDED: passes code / markers / governance lines verbatim
  estimate_savings(a, b)    -> {chars_before, chars_after, est_tokens_saved, pct}
"""
import os
import re

_ARTICLES = re.compile(r"\b(a|an|the)\b", re.I)
_FILLER = re.compile(
    r"\b(just|simply|basically|actually|really|very|quite|please|kindly|"
    r"as you can see|it'?s worth noting)\b", re.I)
_HEDGES = re.compile(r"\b(I think|I believe|perhaps|maybe|it seems|"
                     r"sort of|kind of)\b", re.I)
_MULTISPACE = re.compile(r"[ \t]{2,}")
_MULTINL = re.compile(r"\n{3,}")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?])")

# Hard exclusions: a line that looks like CODE, a FILE MARKER, or carries a
# SECURITY/GOVERNANCE keyword is passed through verbatim — caveman's "keep verbosity
# for the critical stuff" rule, made into a guard so brevity never corrupts meaning.
_CODEISH = re.compile(
    r"<<<FILE|<<<END|```|[{};=<>]|"
    r"\b(function|const|let|var|import|export|def|class|return|async|await)\b|"
    r"^\s{2,}\S")
_GOVERNANCE = re.compile(
    r"\b(security|secret|password|passwd|token|credential|crypto|PII|policy|proof|"
    r"seal|merkle|signature|vulnerab|injection|xss|csrf|ROOT CAUSE)\b", re.I)


def intensity(env=None):
    env = env if env is not None else os.environ
    v = env.get("ADF_CAVEMAN", "").strip().lower()
    return v if v in ("lite", "full") else "off"


def is_enabled(env=None):
    return intensity(env) != "off"


def compress(text, level="lite"):
    """Compress PROSE deterministically. 'lite' strips articles + collapses whitespace;
    'full' also strips filler + hedges. 'off' is a no-op. This is the raw rule engine —
    the caller (compress_prose) guards code/governance; never call it on raw code."""
    if level == "off" or not text:
        return text
    out = _ARTICLES.sub("", text)
    if level == "full":
        out = _FILLER.sub("", out)
        out = _HEDGES.sub("", out)
    out = _MULTISPACE.sub(" ", out)
    out = _MULTINL.sub("\n\n", out)
    out = _SPACE_BEFORE_PUNCT.sub(r"\1", out)
    # collapse a leading space left by a stripped article at the start of a line
    return "\n".join(ln.lstrip(" ") if ln[:1] == " " else ln for ln in out.split("\n"))


def _is_protected(line):
    return bool(_CODEISH.search(line) or _GOVERNANCE.search(line))


def compress_prose(text, env=None):
    """Guarded compression of a mixed block: compress only PROSE lines, passing any
    code-ish / file-marker / security-governance line through VERBATIM. Honors
    ADF_CAVEMAN; a no-op when disabled. This is the only entry point callers should
    use on pipeline text."""
    level = intensity(env)
    if level == "off" or not text:
        return text
    return "\n".join(
        line if _is_protected(line) else compress(line, level)
        for line in text.split("\n"))


def estimate_savings(before, after):
    """A rough token-savings estimate (≈4 chars/token, matching compaction.py)."""
    cb, ca = len(before or ""), len(after or "")
    saved = max(0, cb - ca)
    return {"chars_before": cb, "chars_after": ca,
            "est_tokens_saved": saved // 4,
            "pct": round(100.0 * saved / cb, 1) if cb else 0.0}


def _main(argv):
    """CLI: compress stdin as PROSE and report savings. `ADF_CAVEMAN=full caveman.py`."""
    import sys
    src = sys.stdin.read()
    out = compress_prose(src, env={"ADF_CAVEMAN": (argv[1] if len(argv) > 1 else "lite")})
    sys.stderr.write(json.dumps(estimate_savings(src, out)) + "\n")
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    import json
    import sys
    sys.exit(_main(sys.argv))
