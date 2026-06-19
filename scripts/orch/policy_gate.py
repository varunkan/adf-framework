#!/usr/bin/env python3
"""ADF Policy Gate — provable governance for generated apps.

After a build verifies, ADF runs a set of static, deterministic policy checks over
the app's own source and records the verdict. The verdict is sealed INTO the Proof
of Build, so an org can prove offline that an app was not only built and tested,
but is **policy-compliant**: no hardcoded secrets, no external network egress,
offline-capable (no CDNs), no plaintext PII columns, only vetted dependencies.

This is the regulated/enterprise wedge a hosted black-box can't serve: you don't
trust ADF's word — you recompute the seal and read the sealed policy verdict.

  load_policy(app_dir, repo_root) -> policy dict (app > repo > built-in default)
  check_policy(app_dir, policy)   -> {ok, policy_id, rules:[...], n_violations}
  policy_summary(result)          -> canonical, sealable subset of the verdict
"""
import json
import os
import re

POLICY_SCHEMA = "adf-policy/1"
POLICY_FILE = ".adf-policy.json"
REPO_POLICY_FILE = "adf-policy.json"

# Dependencies a react-vite-sqlite app may use without review — mirrors the
# checked-in template's pinned set. Anything else trips dependency_allowlist.
_DEFAULT_ALLOWLIST = sorted({
    "react", "react-dom", "fastify", "@fastify/static", "better-sqlite3",
    "vite", "@vitejs/plugin-react", "typescript", "vitest",
    "tailwindcss", "postcss", "autoprefixer",
    "@types/react", "@types/react-dom",
})

DEFAULT_POLICY = {
    "schema": POLICY_SCHEMA,
    "id": "adf-default-secure",
    "rules": {
        "no_secrets": True,
        "no_network_egress": True,
        "offline_capable": True,
        "no_plaintext_pii": True,
        "dependency_allowlist": True,
    },
    "allowlist": _DEFAULT_ALLOWLIST,
}

# --- detectors -------------------------------------------------------------
_SECRET_PATTERNS = [
    ("openai_key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("slack_token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("generic_secret", re.compile(
        r"(?i)(api[_-]?key|secret|password|passwd|token|access[_-]?key)"
        r"\s*[:=]\s*['\"][^'\"\s]{12,}['\"]")),
]
# An external URL = http(s) to a host that isn't loopback.
_EXTERNAL_URL = re.compile(r"https?://(?!127\.0\.0\.1|localhost|0\.0\.0\.0)[^\s'\"<>)]+")
_OUTBOUND_LIBS = re.compile(
    r"(?:from\s*['\"]|require\(\s*['\"])(axios|node-fetch|got|undici|request|superagent)['\"]")
_CDN_TAG = re.compile(
    r"""<(?:script|link)[^>]*(?:src|href)\s*=\s*['"](?:https?:)?//[^'"]+['"]""",
    re.IGNORECASE)
# Column whose name implies plaintext-sensitive storage.
_PII_COLUMNS = re.compile(
    r"(?i)\b(password|passwd|ssn|social_security|credit_card|card_number|cardnumber|cvv|cvc)\b")
_HASHED_OK = re.compile(r"(?i)(password|passwd)_(hash|digest)")
# A SENSITIVE COLUMN *DEFINITION*: the column name DIRECTLY followed by a SQL column
# type (`password TEXT`, `ssn VARCHAR(11)`). Adjacency is what makes this a storage
# decision — it catches inline expo-sqlite `CREATE TABLE … password TEXT` while NOT
# false-flagging a TypeScript param/type signature (`password: string` on a line that
# happens to also contain `Promise<boolean>` — `boolean` is a SQL type keyword too)
# or a UI state var (`const [password] = useState()`). (Found by a real secure
# mobile-auth build that the old "type keyword ANYWHERE on the line" heuristic
# false-flagged 4×.) The SQL types intentionally EXCLUDE `boolean`/`bool` (collides
# with TS `Promise<boolean>`); a password is never a boolean column anyway.
_PII_PLAINTEXT_COL = re.compile(
    r"(?i)\b(password|passwd|ssn|social_security|credit_card|card_number|cardnumber|cvv|cvc)\b"
    r"\s+(?:text|varchar|nvarchar|nchar|char|clob|blob|integer|int|numeric|decimal|real)\b")
# Source files that may carry an inline SQL schema (no dedicated .sql file).
_INLINE_SQL_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py")
# A raw hex color literal — banned in mobile components (use theme tokens) so every
# generated app is on-theme + light/dark-correct by construction.
_RAW_HEX = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?(?:[0-9a-fA-F]{2})?\b")


def _norm(path):
    return path.replace(os.sep, "/")


# A test/spec file — its literal "passwords"/"tokens" are fixtures, not leaked
# secrets (e.g. `const password = 'superSecret123'` asserting a hash never returns
# it). The generic_secret heuristic is skipped here; real provider keys (sk-/AKIA/…)
# are STILL flagged everywhere.
_TEST_FILE = re.compile(
    r"(?i)(^|/)(__tests__|tests?)/|(\.test|\.spec)\.(?:tsx?|jsx?|mjs|cjs)$")


def _is_test_file(path):
    return bool(_TEST_FILE.search(_norm(path)))


def _source_files(app_dir, files=None):
    """(relpath, content) for the app's source. Reuses the runner's editable-file
    walker (skips deps/build/caches/dotfiles/lockfiles). Lazy import avoids a
    load-time cycle."""
    if files is not None:
        return files
    import agent_runner
    return agent_runner.current_app_files(app_dir)


def load_policy(app_dir, repo_root=None):
    """App-level `.adf-policy.json` wins, else a repo-level `adf-policy.json`,
    else the built-in secure default."""
    for path in (os.path.join(app_dir, POLICY_FILE),
                 os.path.join(repo_root, REPO_POLICY_FILE) if repo_root else None):
        if path and os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    p = json.load(f)
                p.setdefault("rules", DEFAULT_POLICY["rules"])
                p.setdefault("allowlist", DEFAULT_POLICY["allowlist"])
                p.setdefault("id", os.path.basename(path))
                return p
            except (OSError, ValueError):
                pass
    return DEFAULT_POLICY


def _lineno(content, idx):
    return content.count("\n", 0, idx) + 1


def _check_no_secrets(files):
    out = []
    for path, content in files:
        is_test = _is_test_file(path)
        for name, pat in _SECRET_PATTERNS:
            # In test/spec files a literal password/token is a fixture, not a leak —
            # skip the generic heuristic there; real provider keys still get flagged.
            if name == "generic_secret" and is_test:
                continue
            for m in pat.finditer(content):
                out.append({"file": _norm(path), "line": _lineno(content, m.start()),
                            "detail": f"possible {name} literal in source"})
    return out


def _check_no_network_egress(files):
    out = []
    for path, content in files:
        n = _norm(path)
        if not (n.startswith("src/") or n.startswith("server/")
                or n.endswith(".mjs") or n.endswith(".ts") or n.endswith(".tsx")
                or n.endswith(".js")):
            continue
        for m in _EXTERNAL_URL.finditer(content):
            out.append({"file": n, "line": _lineno(content, m.start()),
                        "detail": f"external URL: {m.group(0)[:60]}"})
        for m in _OUTBOUND_LIBS.finditer(content):
            out.append({"file": n, "line": _lineno(content, m.start()),
                        "detail": f"outbound HTTP client: {m.group(1)}"})
    return out


def _check_offline_capable(files):
    out = []
    for path, content in files:
        if not _norm(path).endswith(".html"):
            continue
        for m in _CDN_TAG.finditer(content):
            out.append({"file": _norm(path), "line": _lineno(content, m.start()),
                        "detail": "external CDN asset (breaks offline use)"})
    return out


def _check_no_plaintext_pii(files):
    """Flag a sensitive column stored in plaintext. Scans `.sql` files fully; in
    SOURCE files (inline expo-sqlite / sqlite3 `CREATE TABLE …`) only flags a
    sensitive column NAME that sits next to a SQL column-type keyword, so a schema
    line (`password TEXT`) is caught but a UI state var (`const [password]`) is not.
    (X1 — closes the vacuous pass on non-web/mobile code.)"""
    out = []
    for path, content in files:
        n = _norm(path)
        is_sql = n.endswith(".sql")
        is_source = n.endswith(_INLINE_SQL_EXTS)
        if not (is_sql or is_source):
            continue
        for line_i, line in enumerate(content.splitlines(), 1):
            if _HASHED_OK.search(line):
                continue
            # A plaintext column is a column DEFINITION: the sensitive name DIRECTLY
            # followed by a SQL type (`password TEXT`). Adjacency holds in both .sql
            # and inline-SQL source, and is precise enough not to flag TS signatures.
            m = _PII_PLAINTEXT_COL.search(line)
            if not m:
                continue
            out.append({"file": n, "line": line_i,
                        "detail": f"sensitive column '{m.group(1)}' suggests "
                                  f"plaintext PII — store hashed/encrypted or remove"})
    return out


def _check_dependency_allowlist(files, allowlist):
    out = []
    allow = set(allowlist)
    for path, content in files:
        if _norm(path) != "package.json":
            continue
        try:
            pkg = json.loads(content)
        except ValueError:
            out.append({"file": "package.json", "line": 1,
                        "detail": "package.json is not valid JSON"})
            continue
        for section in ("dependencies", "devDependencies"):
            for dep in (pkg.get(section) or {}):
                if dep not in allow:
                    out.append({"file": "package.json", "line": 1,
                                "detail": f"dependency '{dep}' not in the allowlist"})
    return out


def _check_no_raw_hex(files):
    """Design-system enforcement (mobile): a raw hex color in a COMPONENT (.tsx) means
    the app bypassed the theme tokens, breaking on-theme + light/dark correctness. The
    token source (src/theme/) legitimately defines hex and is exempt. Only runs on the
    mobile stack (its .adf-policy.json enables it); web uses Tailwind classes."""
    out = []
    for path, content in files:
        n = _norm(path)
        if not n.endswith(".tsx") or "src/theme/" in n:
            continue
        for m in _RAW_HEX.finditer(content):
            out.append({"file": n, "line": _lineno(content, m.start()),
                        "detail": f"raw hex color '{m.group(0)}' — use a theme token "
                                  f"(`const t = useTheme()`) instead of a literal color"})
    return out


_CHECKS = {
    "no_secrets": lambda files, pol: _check_no_secrets(files),
    "no_raw_hex": lambda files, pol: _check_no_raw_hex(files),
    "no_network_egress": lambda files, pol: _check_no_network_egress(files),
    "offline_capable": lambda files, pol: _check_offline_capable(files),
    "no_plaintext_pii": lambda files, pol: _check_no_plaintext_pii(files),
    "dependency_allowlist":
        lambda files, pol: _check_dependency_allowlist(files, pol.get("allowlist", [])),
}


def check_policy(app_dir, policy=None, files=None):
    """Run the enabled rules over the app's source. Returns a structured verdict
    with per-rule pass/fail + located violations."""
    policy = policy or load_policy(app_dir)
    files = _source_files(app_dir, files)
    rules_out, total = [], 0
    for rule, enabled in policy.get("rules", {}).items():
        check = _CHECKS.get(rule)
        if not enabled or check is None:
            rules_out.append({"rule": rule, "enabled": bool(enabled),
                              "ok": True, "violations": []})
            continue
        violations = check(files, policy)
        total += len(violations)
        rules_out.append({"rule": rule, "enabled": True,
                          "ok": len(violations) == 0, "violations": violations})
    return {
        "ok": total == 0,
        "policy_id": policy.get("id", "adf-default-secure"),
        "rules": rules_out,
        "n_violations": total,
        "n_files": len(files),
    }


def policy_summary(result):
    """The canonical, sealable subset of the verdict (goes into the Proof of
    Build): outcome + which rules passed, no file bodies. Stable key order."""
    return {
        "checked": True,
        "ok": bool(result["ok"]),
        "policy_id": result.get("policy_id"),
        "n_violations": result.get("n_violations", 0),
        "rules": sorted(
            f"{r['rule']}:{'pass' if r['ok'] else 'FAIL'}"
            for r in result.get("rules", []) if r.get("enabled")),
    }


def _main(argv):
    """CLI: report an app's policy compliance. `--json` for machine output.
    Exit 0 = compliant."""
    args = argv[1:]
    as_json = False
    if args and args[0] == "--json":
        as_json, args = True, args[1:]
    if len(args) != 1:
        print("usage: policy_gate.py [--json] <app-dir>", file=__import__("sys").stderr)
        return 2
    res = check_policy(args[0])
    if as_json:
        print(json.dumps(res))
        return 0 if res["ok"] else 1
    print(f"\U0001F6E1️  ADF Policy Gate — {res['policy_id']} "
          f"({res['n_files']} files)")
    for r in res["rules"]:
        if not r["enabled"]:
            mark, note = "·", "skipped"
        elif r["ok"]:
            mark, note = "✔", "pass"
        else:
            mark, note = "✘", f"{len(r['violations'])} violation(s)"
        print(f"   {mark} {r['rule']}: {note}")
        for v in r["violations"][:6]:
            print(f"       - {v['file']}:{v['line']}  {v['detail']}")
    print("   ✅ COMPLIANT — policy verdict will be sealed into the Proof of Build."
          if res["ok"] else
          f"   ❌ {res['n_violations']} VIOLATION(S) — app builds but breaches policy.")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv))
