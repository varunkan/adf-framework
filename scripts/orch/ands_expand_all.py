#!/usr/bin/env python3
"""Relentlessly drive ADF to cover ALL ANDS requirements, one slice at a time.

For each thematic slice of requirements this driver:
  1. writes specs/<id>/mvp-scope.md as an ADDITIVE slice scope (grow, never shrink),
  2. POST /features/<id>/run  (the relentless self-heal loop drives it to green),
  3. waits until ADF reconciles the build to tests_green (or the slice is blocked),
  4. POST /features/<id>/compact  ("compaction at every phase"),
  5. records progress in a coverage ledger, then moves to the next slice.

It keeps fighting: a blocked slice is retried (heal reset) up to SLICE_RETRIES
times before it is logged and the driver moves on, so one hard slice never stalls
the whole portal.
"""
import json, os, time, urllib.request, urllib.error, sys

FW = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ID = "ands-submission-portal"
BASE = os.environ.get("ADF_BASE", "http://127.0.0.1:3847")
SPEC = f"{FW}/specs/{ID}"
STATE = f"{FW}/.adf/orchestration/features/{ID}/state.json"
RUNST = f"{FW}/.adf/orchestration/features/{ID}/run-status.json"
LEDGER = f"{FW}/.adf/orchestration/features/{ID}/coverage-ledger.json"
SCOPE = f"{SPEC}/mvp-scope.md"

SLICE_BUDGET_SEC = int(os.environ.get("SLICE_BUDGET_SEC", "3600"))   # per-slice wall clock
SLICE_RETRIES = int(os.environ.get("SLICE_RETRIES", "2"))           # re-kicks after a blocked slice
POLL = 20

# Thematic, additive slices over the 70 requirements (MVP slice 1 already green).
SLICES = [
    ("identifiers-rep", "Identifiers & REP (CO/RT/PI)",
     ["REQ-001", "REQ-005", "REQ-006", "REQ-042", "REQ-043"]),
    ("ectd-structure", "eCTD tree, backbones, leaf lifecycle & current view",
     ["REQ-009", "REQ-014", "REQ-015", "REQ-017", "REQ-018", "REQ-019"]),
    ("documents", "Document handling: PDF conformance, bookmarks, hyperlinks, naming hygiene",
     ["REQ-010", "REQ-011", "REQ-012", "REQ-013", "REQ-020", "REQ-021"]),
    ("validation-engine", "Versioned eCTD validation engine + reports + cross-doc consistency",
     ["REQ-022", "REQ-023", "REQ-024", "REQ-045", "REQ-059", "REQ-070"]),
    ("crp-be-qos", "Canadian Reference Product, bioequivalence, QOS, STF",
     ["REQ-007", "REQ-008", "REQ-061", "REQ-063", "REQ-064"]),
    ("transmission", "Transmission & ESG: size routing, queueing, physical media, retries",
     ["REQ-003", "REQ-025", "REQ-026", "REQ-027", "REQ-046", "REQ-058"]),
    ("ack-lifecycle", "Acknowledgement state machine, DSTS lifecycle, deadlines",
     ["REQ-028", "REQ-029", "REQ-030", "REQ-031", "REQ-052", "REQ-062"]),
    ("deficiencies", "Deficiency responses, withdrawals, admin/corrective & ownership transfer",
     ["REQ-032", "REQ-033", "REQ-048", "REQ-049", "REQ-050", "REQ-051"]),
    ("fees", "Fee grouping, mitigation eligibility, Right-to-Sell",
     ["REQ-035", "REQ-036", "REQ-037"]),
    ("portfolio-rbac-qa", "Portfolio dashboard, RBAC, QA approval gate, locking, checklist, vocab",
     ["REQ-034", "REQ-038", "REQ-039", "REQ-040", "REQ-044", "REQ-047", "REQ-057"]),
    ("compliance-signatures", "E-signatures, retention/legal-hold, audit export, basis classification",
     ["REQ-053", "REQ-054", "REQ-060", "REQ-067", "REQ-068", "REQ-069"]),
    ("platform-versioning", "Version-plugin architecture, HC ruleset/vocab updates, stylesheets, DR/BCP",
     ["REQ-041", "REQ-055", "REQ-056", "REQ-065", "REQ-066"]),
]


def http(method, path, body=None):
    data = json.dumps(body or {}).encode() if method == "POST" else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or "{}")


def load(path, default=None):
    try:
        return json.load(open(path))
    except Exception:
        return default if default is not None else {}


def req_block(rids):
    """Pull each REQ's header + first body line from requirements.md."""
    lines = open(f"{SPEC}/requirements.md").read().splitlines()
    want = set(rids)
    out, i = [], 0
    import re
    while i < len(lines):
        m = re.match(r'^###\s+(REQ-\d+)\s*(.*)$', lines[i])
        if m and m.group(1) in want:
            title = m.group(2).strip()
            j = i + 1
            while not title and j < min(i + 5, len(lines)):
                if lines[j].strip():
                    title = lines[j].strip()
                j += 1
            out.append(f"- {m.group(1)}: {title}")
        i += 1
    return "\n".join(out)


def write_scope(name, desc, rids):
    body = f"""# ANDS Portal — slice: {desc} (ADDITIVELY extend the existing app)

The app at `apps/{ID}/` ALREADY EXISTS and passes its tests. ADD coverage for the
requirements below WITHOUT removing, weakening, or shrinking anything already built.
Keep every existing test green and add new tests for each requirement here. Use
`requirements.md` and `spec.md` for the exact rules, formats, and field names.

## Requirements to ADD in this slice
{req_block(rids)}

Build real domain logic + JSON API endpoints + UI for each, plus unittest coverage.
The full suite (old + new) must pass with `python3 -m unittest -v`, and
`python3 server.py` must still boot.
"""
    open(SCOPE, "w").write(body)


def set_state(**kw):
    s = load(STATE)
    s.update(kw)
    json.dump(s, open(STATE, "w"), indent=2)


def kick():
    set_state(status="active", heal_attempts=0, awaiting_user=False)
    return http("POST", f"/features/{ID}/run", {})


def wait_green(start_finished):
    """Poll until ADF reconciles a fresh build to tests_green, or it blocks."""
    deadline = time.time() + SLICE_BUDGET_SEC
    while time.time() < deadline:
        time.sleep(POLL)
        rs = load(RUNST)
        st = load(STATE)
        status = rs.get("status")
        green = (st.get("gates", {}) or {}).get("tests_green") is True
        finished = rs.get("finished_at")
        fresh = finished and finished != start_finished
        if status == "blocked":
            return "blocked"
        if fresh and status in ("idle", "awaiting_approval") and green:
            return "green"
    return "timeout"


def ntests():
    try:
        import subprocess
        r = subprocess.run(["python3", "-m", "unittest", "-v"],
                           cwd=f"{FW}/apps/{ID}", capture_output=True, text=True, timeout=300)
        import re
        m = re.search(r"Ran (\d+) test", r.stdout + r.stderr)
        ok = (r.returncode == 0)
        return (int(m.group(1)) if m else 0, ok)
    except Exception:
        return (0, False)


def main():
    ledger = load(LEDGER, {"done": [], "log": []})
    print(f"[driver] ANDS expansion — {len(SLICES)} slices, base={BASE}", flush=True)
    for name, desc, rids in SLICES:
        if name in ledger["done"]:
            print(f"[driver] SKIP {name} (already done)", flush=True)
            continue
        print(f"\n[driver] === SLICE {name}: {desc} ({len(rids)} reqs) ===", flush=True)
        outcome = None
        for attempt in range(1, SLICE_RETRIES + 2):
            write_scope(name, desc, rids)
            start_finished = load(RUNST).get("finished_at")
            kick()
            print(f"[driver] kicked build for {name} (attempt {attempt})", flush=True)
            outcome = wait_green(start_finished)
            print(f"[driver] {name} attempt {attempt} -> {outcome}", flush=True)
            if outcome == "green":
                break
            # relentless: reset heal and try the slice again
            set_state(status="active", heal_attempts=0)
            time.sleep(5)
        n, ok = ntests()
        rec = {"slice": name, "outcome": outcome, "tests": n, "tests_ok": ok}
        ledger["log"].append(rec)
        if outcome == "green":
            ledger["done"].append(name)
        json.dump(ledger, open(LEDGER, "w"), indent=2)
        # compaction at every phase
        try:
            http("POST", f"/features/{ID}/compact", {})
            print(f"[driver] compacted after {name}", flush=True)
        except Exception as e:
            print(f"[driver] compact failed (non-fatal): {e}", flush=True)
        print(f"[driver] LEDGER {name}: {rec}  | done={len(ledger['done'])}/{len(SLICES)}", flush=True)
    n, ok = ntests()
    print(f"\n[driver] DONE. slices green={len(ledger['done'])}/{len(SLICES)} | app tests={n} ok={ok}", flush=True)


if __name__ == "__main__":
    main()
