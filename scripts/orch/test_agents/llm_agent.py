#!/usr/bin/env python3
"""ADF generic DEEP LLM test agent — one script, four adversarial testers.

Backs four registry agents (e2e, integration, black-box, white-box) via a mode
arg. Each makes ONE headless Claude/Opus call that acts as that kind of tester
of the app under test, and returns structured findings.

Invoked as:  python3 llm_agent.py <mode> <app_dir> [<base_url>]
  mode      one of: e2e | integration | black-box | white-box
  app_dir   the built app's directory (contains server.py, domain.py, ...)
  base_url  http://127.0.0.1:8000  (default; the app's running base URL)

Contract (ADF test-agent): prints ONE JSON object to stdout and nothing else:
  {"agent": <id>, "ok": <bool>, "findings": [
      {"severity":"critical|high|medium|low","title":..,"detail":..,"location":..}
   ], "summary": ..}
  ok is true IFF findings is empty. ALWAYS exit 0. Never crash — any error
  (no token / no binary / parse failure / running-app failure) is reported as a
  single low-severity finding, not a stack trace.

COST CONTROL: these are EXPENSIVE (each is one Opus call). To keep the per-build
gate fast, they RUN ONLY when env ADF_DEEP_AGENTS=1. Otherwise they immediately
print the "skipped" object and exit 0.

The Claude CLI is invoked headless:
  <bin> -p "<prompt>" --model opus --output-format text
with CLAUDE_CODE_OAUTH_TOKEN passed through. The binary is env ADF_CLAUDE_PATH,
else `command -v claude`, else the newest claude under the macOS app-support dir.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys

# mode -> registry agent id (verbatim, per registry.json).
MODE_TO_ID = {
    "e2e": "e2e",
    "integration": "integration",
    "black-box": "black-box",
    "white-box": "white-box",
}

SOURCE_BUDGET = 120_000   # max chars of concatenated app source fed to the model
REQS_BUDGET = 40_000      # max chars of requirements.md fed to the model
LLM_TIMEOUT = int(os.environ.get("ADF_DEEP_AGENT_TIMEOUT", "540"))  # seconds


# --------------------------------------------------------------------------- #
# Output helper — every exit path goes through here so we never break the JSON.
# --------------------------------------------------------------------------- #
def emit(agent_id, findings, summary):
    findings = findings or []
    print(json.dumps({
        "agent": agent_id,
        "ok": len(findings) == 0,
        "findings": findings,
        "summary": summary,
    }))
    sys.exit(0)


def info_finding(title, detail, location="llm_agent.py"):
    # INFRA/error reports (no token, CLI timeout, unparseable output, crash) are
    # NOT defects of the app under test — severity 'info' so the gate reports them
    # but never BLOCKS the build on an infrastructure hiccup.
    return [{"severity": "info", "title": title, "detail": detail, "location": location}]


# --------------------------------------------------------------------------- #
# Claude CLI discovery + invocation.
# --------------------------------------------------------------------------- #
def find_claude_bin():
    env = os.environ.get("ADF_CLAUDE_PATH")
    if env and os.path.exists(env):
        return env
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    pattern = os.path.expanduser(
        "~/Library/Application Support/Claude/claude-code/*/claude.app/Contents/MacOS/claude")
    cands = sorted(glob.glob(pattern), key=lambda p: os.path.getmtime(p), reverse=True)
    return cands[0] if cands else None


def call_claude(prompt):
    """Return (text, error). On success error is None."""
    binpath = find_claude_bin()
    if not binpath:
        return None, "no Claude CLI binary found (set ADF_CLAUDE_PATH)"
    if not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return None, "CLAUDE_CODE_OAUTH_TOKEN not set in environment"
    try:
        r = subprocess.run(
            [binpath, "-p", prompt, "--model", "opus", "--output-format", "text"],
            capture_output=True, text=True, timeout=LLM_TIMEOUT,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        return None, f"Claude CLI timed out after {LLM_TIMEOUT}s"
    except Exception as e:  # noqa: BLE001 — never crash the agent
        return None, f"Claude CLI invocation error: {e}"
    out = (r.stdout or "").strip()
    if not out:
        return None, f"Claude CLI produced no output (stderr: {(r.stderr or '')[-300:]})"
    return out, None


# --------------------------------------------------------------------------- #
# Gather the app source + requirements to feed the model.
# --------------------------------------------------------------------------- #
def gather_source(app_dir):
    """Concatenate .py files under app_dir (server.py first), truncated to budget."""
    py_files = []
    for root, dirs, names in os.walk(app_dir):
        dirs[:] = [d for d in dirs
                   if d not in ("__pycache__", ".git", ".adf-context", ".adf-visual")
                   and not d.startswith(".adf-")]
        for n in names:
            if n.endswith(".py"):
                py_files.append(os.path.join(root, n))

    # Order: server.py, domain.py, then the rest alphabetically. Tests last (big).
    def rank(p):
        b = os.path.basename(p)
        if b == "server.py":
            return (0, b)
        if b == "domain.py":
            return (1, b)
        if b.startswith("test_") or b.endswith("_test.py"):
            return (3, b)
        return (2, b)

    py_files.sort(key=rank)

    chunks, total = [], 0
    for p in py_files:
        try:
            text = open(p, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        rel = os.path.relpath(p, app_dir)
        header = f"\n\n===== FILE: {rel} =====\n"
        remaining = SOURCE_BUDGET - total
        if remaining <= len(header):
            chunks.append(f"\n\n[...source truncated at {SOURCE_BUDGET} char budget...]\n")
            break
        body = text[: max(0, remaining - len(header))]
        chunks.append(header + body)
        total += len(header) + len(body)
        if body != text:
            chunks.append(f"\n[...{rel} truncated...]\n")
            break
    return "".join(chunks) or "[no .py source files found under app_dir]"


def gather_requirements(app_dir):
    """Find requirements.md for this app; truncate to budget. Best-effort."""
    candidates = []
    app_name = os.path.basename(os.path.abspath(app_dir.rstrip("/")))
    # 1) specs/<app>/requirements.md relative to the framework root.
    fw = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidates.append(os.path.join(fw, "specs", app_name, "requirements.md"))
    # 2) anything named requirements.md inside the app dir.
    candidates.append(os.path.join(app_dir, "requirements.md"))
    candidates.append(os.path.join(app_dir, "specs", "requirements.md"))
    for c in candidates:
        if os.path.isfile(c):
            try:
                return open(c, encoding="utf-8", errors="replace").read()[:REQS_BUDGET]
            except Exception:
                continue
    # 3) glob fallback under specs/.
    for c in glob.glob(os.path.join(fw, "specs", "*", "requirements.md")):
        if app_name in c:
            try:
                return open(c, encoding="utf-8", errors="replace").read()[:REQS_BUDGET]
            except Exception:
                continue
    return "[requirements.md not found — infer expected behavior from the source]"


# --------------------------------------------------------------------------- #
# Mode-specific adversarial prompts.
# --------------------------------------------------------------------------- #
MODE_BRIEF = {
    "e2e": (
        "You are an END-TO-END test engineer. Trace COMPLETE user journeys through "
        "the UI + API, start to finish — e.g. create a submission -> validate it -> "
        "submit -> sequence lifecycle (supersede/withdraw) -> transmit to Health "
        "Canada. Walk each journey step by step and report any journey that is "
        "BROKEN, INCOMPLETE, or DEAD-ENDS (a step with no UI/API to reach the next, "
        "a state the user can enter but never leave, missing wiring between steps). "
        "Focus on whole-journey integrity, not individual functions."
    ),
    "integration": (
        "You are an INTEGRATION test engineer. Verify that the domain modules "
        "(ectd, rep, transmission, validation, qos, stf, bioequivalence, lifecycle, "
        "backbone, dr, hc_calendar, report_ingest), the HTTP API in server.py, and "
        "the sqlite storage integrate correctly ACROSS boundaries. Report mismatches "
        "and CONTRACT BREAKS between layers: an API endpoint that passes the wrong "
        "shape to a module, a module return value the API mis-handles, DB columns / "
        "rows that don't round-trip, serialization mismatches, state that one layer "
        "writes and another reads inconsistently."
    ),
    "black-box": (
        "You are a BLACK-BOX tester. Test ONLY through the API/UI contract — you may "
        "read requirements.md for EXPECTED behavior but you must NOT rely on internal "
        "implementation details. Probe BOUNDARY VALUES, INVALID and MALICIOUS inputs, "
        "and FUZZING: empty/huge/oversized payloads, wrong types, missing required "
        "fields, out-of-range numbers, unexpected enum values, injection-style strings, "
        "malformed JSON, unknown routes/methods. Report concrete inputs that CRASH the "
        "server, return a 500, leak a stack trace, or are otherwise MISHANDLED vs. the "
        "documented contract. Give the exact endpoint + payload for each finding."
    ),
    "white-box": (
        "You are a WHITE-BOX tester with FULL knowledge of the source. Find "
        "UNDER-TESTED critical paths: branches/conditions with no test coverage, "
        "error-handling paths never exercised, DEAD CODE (unreachable branches, "
        "unused functions), and LOGIC ERRORS (off-by-one, wrong comparison, swapped "
        "args, incorrect state transitions, missing validation a branch assumes). "
        "Cross-reference test_app.py to judge what is actually covered. Prioritize "
        "the critical domain logic of the app under test, as described by its "
        "requirements (validation rules, state/lifecycle transitions, and any "
        "external transmission or integration paths)."
    ),
}


def build_prompt(mode, source, requirements, base_url):
    brief = MODE_BRIEF[mode]
    return (
        f"{brief}\n\n"
        f"The app under test is a Python 3 standard-library single-page app. "
        f"server.py runs http.server on {base_url}, serving an HTML/JS UI at \"/\" "
        f"and a JSON API under /api/... . Domain logic lives in domain.py plus its "
        f"sibling modules; data persists in a local sqlite database. Infer the "
        f"application's domain from the requirements and source below — do not "
        f"assume one.\n\n"
        f"================ REQUIREMENTS (requirements.md) ================\n"
        f"{requirements}\n\n"
        f"================ APP SOURCE (.py files) ================\n"
        f"{source}\n\n"
        f"================ YOUR TASK ================\n"
        f"Analyze the app as the tester described above and identify REAL defects. "
        f"Do not invent issues; report only defects you can justify from the "
        f"source/requirements. Prefer fewer, higher-confidence findings over noise.\n\n"
        f"Respond with ONLY a JSON array (no prose, no markdown fences) of findings. "
        f"Each element MUST be an object with EXACTLY these keys:\n"
        f'  "severity": one of "critical" | "high" | "medium" | "low"\n'
        f'  "title":    a short one-line summary of the defect\n'
        f'  "detail":   how to reproduce / why it is wrong / impact\n'
        f'  "location": "file:line" or "endpoint" or "view/url" pinpointing it\n'
        f"If you find NO defects, respond with exactly: []\n"
        f"Output ONLY the JSON array."
    )


# --------------------------------------------------------------------------- #
# Parse the model's JSON-array answer robustly.
# --------------------------------------------------------------------------- #
_SEV = {"critical", "high", "medium", "low"}


def parse_findings(text):
    """Extract a JSON array of findings from arbitrary model output. (list, error)."""
    if text is None:
        return None, "no model output"
    # Strip code fences if the model added them despite instructions.
    stripped = text.strip()
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None, f"no JSON array in model output: {stripped[:300]}"
    blob = stripped[start: end + 1]
    try:
        data = json.loads(blob)
    except Exception as e:  # noqa: BLE001
        return None, f"could not parse JSON array ({e}): {blob[:300]}"
    if not isinstance(data, list):
        return None, "model output was not a JSON array"

    cleaned = []
    for item in data:
        if not isinstance(item, dict):
            continue
        sev = str(item.get("severity", "medium")).strip().lower()
        if sev not in _SEV:
            sev = "medium"
        title = str(item.get("title", "")).strip() or "unspecified finding"
        detail = str(item.get("detail", "")).strip()
        location = str(item.get("location", "")).strip() or "n/a"
        cleaned.append({
            "severity": sev,
            "title": title[:300],
            "detail": detail[:1500],
            "location": location[:300],
        })
    return cleaned, None


# --------------------------------------------------------------------------- #
# Main.
# --------------------------------------------------------------------------- #
def main(argv):
    mode = (argv[0] if len(argv) > 0 else "").strip().lower()
    app_dir = os.path.abspath(argv[1]) if len(argv) > 1 else os.getcwd()
    base_url = argv[2] if len(argv) > 2 else "http://127.0.0.1:8000"

    agent_id = MODE_TO_ID.get(mode)
    if agent_id is None:
        # Unknown mode — report as a finding under the raw mode string, never crash.
        emit(mode or "llm-agent",
             info_finding("unknown deep-agent mode",
                         f"mode must be one of {sorted(MODE_TO_ID)}; got {mode!r}"),
             "invalid mode argument")

    # COST GATE: only run when explicitly enabled.
    if os.environ.get("ADF_DEEP_AGENTS") != "1":
        emit(agent_id, [], "deep agent skipped (set ADF_DEEP_AGENTS=1)")

    # Gather inputs (best-effort; never crash).
    try:
        source = gather_source(app_dir)
        requirements = gather_requirements(app_dir)
    except Exception as e:  # noqa: BLE001
        emit(agent_id,
             info_finding("could not read app source/requirements", str(e)),
             "deep agent setup error")

    prompt = build_prompt(mode, source, requirements, base_url)

    text, err = call_claude(prompt)
    if err:
        emit(agent_id,
             info_finding("deep agent could not run", err),
             f"{agent_id} deep agent error (not a defect of the app)")

    findings, perr = parse_findings(text)
    if perr:
        emit(agent_id,
             info_finding("deep agent output not parseable", perr),
             f"{agent_id} could not parse model findings")

    n = len(findings)
    emit(agent_id, findings,
         f"{agent_id} deep agent: {n} finding(s)" if n
         else f"{agent_id} deep agent: no defects found")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — last-resort: still emit valid JSON.
        mode_guess = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "llm-agent"
        emit(MODE_TO_ID.get(mode_guess, mode_guess or "llm-agent"),
             info_finding("deep agent crashed", str(e)),
             "unexpected error")
