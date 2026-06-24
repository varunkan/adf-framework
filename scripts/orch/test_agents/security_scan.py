#!/usr/bin/env python3
"""ADF test agent: security & pen-test — OWASP-grade static vulnerability scan.

Reads the app's shipped source (server + modules + js/html) and reports the
exploitable classes a pen-tester looks for first: injection (SQL / command /
code), insecure deserialization, path traversal, hardcoded secrets, reflected
XSS, weak crypto for auth, and insecure transport/config.

It is deliberately CONTEXT-AWARE to avoid the false positives that make scanners
ignored: e.g. md5/sha1 used for an eCTD `index-md5.txt` checksum is correct and
NOT flagged as weak crypto — only md5/sha1 in an authentication/secret context
is. Parameterized SQL is not flagged; only string-built SQL is.

Severity drives the gate: 'critical'/'high' block 'complete'; 'medium'/'low' are
advisory (reported and fed to the heal loop as guidance).

Contract: prints {"agent","ok","findings":[{severity,title,detail,location}],
"summary"}. Exit 0 regardless.

Usage: security_scan.py <app_dir>
"""
import json
import os
import re
import sys

MAX_FINDINGS = 80
SKIP_DIRS = (".adf-", "__pycache__", ".git", "node_modules", ".adf-visual", ".adf-proof")

# ---- context detectors -----------------------------------------------------
AUTH_CTX = re.compile(r"password|passwd|\bpwd\b|secret|\btoken\b|auth|login|"
                      r"credential|session|api[_-]?key|sign|hmac|jwt", re.I)
# NB: no bare 'digest' — `.hexdigest()` is on every hash call (incl. password
# hashing), so it must not count as checksum context.
CHECKSUM_CTX = re.compile(r"checksum|index-?md5|\bectd\b|etag|integrity|"
                          r"fingerprint|content[_-]?hash|file_?hash|backbone", re.I)
PLACEHOLDER = re.compile(r"^\s*$|example|changeme|change-me|your[-_ ]?|xxx+|"
                         r"placeholder|<.*>|\{\{?.*\}?\}|todo|dummy|sample|test[-_]?key",
                         re.I)
USERINPUT = re.compile(r"request|\bparams?\b|\bquery\b|\bbody\b|\bform\b|\bargs\b|"
                       r"payload|\.json|user_?input|self\.path|rfile|getvalue|"
                       r"environ|querystring|post_?data", re.I)


def _ctx(lines, idx, radius=3):
    lo, hi = max(0, idx - radius), min(len(lines), idx + radius + 1)
    return " ".join(lines[lo:hi])


def _add(findings, sev, title, detail, path, lineno):
    findings.append({"severity": sev, "title": title, "detail": detail,
                     "location": f"{os.path.basename(path)}:{lineno}"})


# ---- per-line / per-file rules ---------------------------------------------
def _scan_py(path, text, findings):
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        line = raw.strip()
        ln = i + 1
        if line.startswith("#"):
            continue
        low = line.lower()

        # SQL injection — only string-BUILT SQL, not parameterized execute().
        if re.search(r"\.execute(many)?\s*\(", line):
            arg = line + (" " + lines[i + 1].strip() if i + 1 < len(lines) else "")
            if (re.search(r"execute(many)?\s*\(\s*f['\"]", arg)
                    or re.search(r"execute(many)?\s*\([^)]*%[^)]*['\"]", arg)
                    or re.search(r"execute(many)?\s*\([^)]*\.format\(", arg)
                    or re.search(r"execute(many)?\s*\([^)]*['\"]\s*\+", arg)
                    or re.search(r"\+\s*['\"]?\s*(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM)", arg, re.I)):
                _add(findings, "high", "Possible SQL injection (string-built query)",
                     "SQL is assembled with f-string/format/%/concat instead of "
                     "parameterized placeholders — use execute(sql, (params,))",
                     path, ln)

        # Code injection
        if re.search(r"\beval\s*\(", line) and "ast.literal_eval" not in line:
            sev = "high" if USERINPUT.search(_ctx(lines, i)) else "medium"
            _add(findings, sev, "Use of eval() (code injection risk)",
                 "eval executes arbitrary code; use ast.literal_eval or a parser", path, ln)
        if re.search(r"\bexec\s*\(", line):
            sev = "high" if USERINPUT.search(_ctx(lines, i)) else "medium"
            _add(findings, sev, "Use of exec() (code injection risk)",
                 "exec runs arbitrary statements", path, ln)
        if re.search(r"(pickle|cPickle)\.loads?\s*\(|marshal\.loads?\s*\(", line):
            sev = "critical" if USERINPUT.search(_ctx(lines, i)) else "high"
            _add(findings, sev, "Insecure deserialization (pickle/marshal)",
                 "pickle/marshal on untrusted data → RCE; use json", path, ln)
        if re.search(r"yaml\.load\s*\(", line) and "Loader" not in line and "SafeLoader" not in _ctx(lines, i):
            _add(findings, "high", "Unsafe yaml.load()",
                 "yaml.load without SafeLoader can instantiate arbitrary objects; "
                 "use yaml.safe_load", path, ln)

        # Command injection
        if "shell=true" in low:
            _add(findings, "high", "subprocess with shell=True",
                 "shell=True + any interpolated value → command injection; pass an arg list",
                 path, ln)
        if re.search(r"os\.system\s*\(|os\.popen\s*\(", line):
            sev = "high" if (USERINPUT.search(_ctx(lines, i)) or re.search(r"f['\"]|%|\.format|\+", line)) else "medium"
            _add(findings, sev, "os.system/os.popen (command execution)",
                 "shells out to the OS; injection-prone if any value is interpolated", path, ln)

        # Weak crypto — ONLY in auth context (md5/sha1 for checksums is correct).
        # Key on the actual primitive `hashlib.md5/sha1` (or `.new("md5")`), so a
        # checksum helper like md5_hex() and its call sites are not flagged.
        if re.search(r"hashlib\.(md5|sha1)\b|hashlib\.new\(\s*['\"](md5|sha1)['\"]", line):
            ctx = _ctx(lines, i)
            if AUTH_CTX.search(ctx) and not CHECKSUM_CTX.search(ctx):
                _add(findings, "high", "Weak hash for authentication (md5/sha1)",
                     "md5/sha1 are broken for password/token hashing; use bcrypt/scrypt/argon2 or hashlib.pbkdf2_hmac with a salt",
                     path, ln)
            # checksum/etag/digest usage → correct, intentionally not reported.

        # TLS verification disabled
        if re.search(r"verify\s*=\s*False", line) or "ssl._create_unverified_context" in line:
            _add(findings, "high", "TLS certificate verification disabled",
                 "verify=False / unverified SSL context enables MITM", path, ln)

        # Debug server in production
        if re.search(r"debug\s*=\s*True", line) and re.search(r"run\(|Flask|app\.", _ctx(lines, i)):
            _add(findings, "high", "Debug mode enabled",
                 "a debug server exposes an interactive console / stack traces to clients", path, ln)

        # CORS wildcard
        if "access-control-allow-origin" in low and '"*"' in line.replace("'", '"'):
            cred = "allow-credentials" in text.lower()
            _add(findings, "high" if cred else "medium",
                 "CORS allows any origin (*)",
                 "Access-Control-Allow-Origin:* " + ("WITH credentials is exploitable" if cred else "widens the attack surface"),
                 path, ln)

        # Path traversal
        if re.search(r"\bopen\s*\(", line) and (re.search(r"f['\"]|%|\.format|\+", line)):
            if USERINPUT.search(_ctx(lines, i)) and not re.search(r"abspath|realpath|normpath|basename|secure_filename|startswith", _ctx(lines, i)):
                _add(findings, "medium", "Possible path traversal in open()",
                     "a user-influenced path is opened without normalization / '..' rejection", path, ln)

        # Hardcoded secrets
        m = re.search(r"""(?ix)\b([A-Za-z_]*(?:api[_-]?key|secret|password|passwd|
                          access[_-]?key|client[_-]?secret|auth[_-]?token|
                          private[_-]?key|token))\s*=\s*['"]([^'"]+)['"]""", line)
        if m and "os.environ" not in line and "getenv" not in line:
            val = m.group(2)
            if len(val) >= 8 and not PLACEHOLDER.search(val):
                _add(findings, "high", "Hardcoded secret in source",
                     f"{m.group(1)} assigned a literal value — move to env/secret store", path, ln)

        # High-signal credential patterns (any file type handles via _scan_any)


def _scan_any(path, text, findings):
    # Provider key fingerprints — exact, near-zero false positives.
    pats = [
        (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
        (r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", "private key material"),
        (r"xox[baprs]-[0-9A-Za-z-]{10,}", "Slack token"),
        (r"AIza[0-9A-Za-z_\-]{35}", "Google API key"),
        (r"sk-(ant-)?[A-Za-z0-9_\-]{20,}", "API secret key (sk-...)"),
        (r"ghp_[A-Za-z0-9]{36}", "GitHub personal access token"),
    ]
    for i, raw in enumerate(text.splitlines()):
        for pat, what in pats:
            if re.search(pat, raw):
                _add(findings, "critical", "Committed credential / key material",
                     f"{what} found in source — revoke and move to a secret store",
                     path, i + 1)


def _scan_js_html(path, text, findings):
    for i, raw in enumerate(text.splitlines()):
        line = raw.strip()
        ln = i + 1
        # DOM XSS sinks fed by non-literal values (downgrade if escaped on the line)
        if re.search(r"\.innerHTML\s*[+]?=|insertAdjacentHTML\s*\(|document\.write\s*\(", line):
            if not re.search(r"=\s*['\"`]", line) or re.search(r"\+|\$\{|`.*\$\{", line):
                escaped = re.search(r"\besc\w*\(|escapeHtml|textContent|encodeURI|sanitize|DOMPurify", line)
                # An already-escaped sink is defensible -> 'info' (advisory, never
                # blocks) so the heal loop doesn't chase a non-issue forever; an
                # un-escaped dynamic sink is a real 'medium' defect to fix.
                _add(findings, "info" if escaped else "medium",
                     "Potential DOM XSS sink",
                     "innerHTML/document.write with a dynamic value"
                     + (" (appears escaped — verify)" if escaped else " — set textContent or escape first"),
                     path, ln)


def run(app_dir):
    findings = []
    for root, dirs, names in os.walk(app_dir):
        dirs[:] = [d for d in dirs if not any(s in d for s in SKIP_DIRS)]
        if any(s in root for s in SKIP_DIRS):
            continue
        for n in names:
            if n.startswith("test_") or n.endswith((".pyc", ".db", ".png", ".json", ".md")):
                continue
            p = os.path.join(root, n)
            try:
                text = open(p, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            _scan_any(p, text, findings)
            if n.endswith(".py"):
                _scan_py(p, text, findings)
            elif n.endswith((".js", ".html", ".htm")):
                _scan_js_html(p, text, findings)

    # de-dup identical (title, location)
    uniq, seen = [], set()
    for f in findings:
        k = (f["title"], f["location"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(f)
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    uniq.sort(key=lambda f: order.get(f["severity"], 9))
    uniq = uniq[:MAX_FINDINGS]
    by = {}
    for f in uniq:
        by[f["severity"]] = by.get(f["severity"], 0) + 1
    return {
        "agent": "security-pentest",
        "ok": len(uniq) == 0,
        "findings": uniq,
        "summary": (f"{len(uniq)} security finding(s): "
                    + ", ".join(f"{by[s]} {s}" for s in ("critical", "high", "medium", "low", "info") if by.get(s))
                    if uniq else "no security findings"),
    }


if __name__ == "__main__":
    app = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    print(json.dumps(run(app), indent=2))
