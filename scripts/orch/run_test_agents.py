#!/usr/bin/env python3
"""ADF test-agent ecosystem orchestrator — the verification gate.

Runs every enabled agent in scripts/orch/test_agents/registry.json against the
built app, aggregates their findings, and decides whether the app is COMPLETE.
A blocking agent fails the gate only on findings at/above its `block_severity`
threshold (default "high"); lower-severity findings from a blocking agent, and
ALL findings from an advisory agent, are reported but don't block. This keeps the
relentless heal loop focused on real defects instead of thrashing on a firehose
of low-severity advisories. A blocking agent whose script doesn't exist yet is
reported as 'not implemented' (advisory) so the ecosystem rolls out incrementally.

Output (compatible with the existing UI gate): {"ok":bool,"defects":[str],
"advisory":[str],"agents":[{id,ok,gate,findings|note}]}. `defects` are the
blocking findings flattened to strings; ADF feeds them to the relentless heal loop.

Usage: run_test_agents.py <app_dir>
"""
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

FW = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.path.join(FW, "scripts", "orch", "test_agents", "registry.json")
BASE_URL = os.environ.get("ADF_APP_URL", "http://127.0.0.1:8000")
PER_AGENT_TIMEOUT = int(os.environ.get("ADF_AGENT_TIMEOUT", "600"))


def _alive(url):
    try:
        urllib.request.urlopen(url, timeout=3)
        return True
    except urllib.error.HTTPError:
        return True  # responded (even a 4xx) → server is up
    except Exception:
        return False


def _free_fixed_port(port):
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}"],
                             capture_output=True, text=True).stdout.split()
        for pid in out:
            try:
                os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass
        if out:
            time.sleep(1)
    except Exception:
        pass


def _boot_app(app_dir):
    """Boot the app ONCE so every dynamic agent (ui-visual, accessibility, the
    LLM journeys) shares one live instance, then app_verify.py reuses it instead
    of double-booting. Apps follow the ADF convention of binding port 8000 (many
    ignore $PORT), so we free and use that fixed port. Returns (proc, base_url);
    proc is None when nothing was booted (already-live server, or boot failed —
    ui-visual then still falls back to booting its own)."""
    if _alive(BASE_URL):
        return None, BASE_URL
    if not os.path.exists(os.path.join(app_dir, "server.py")):
        return None, BASE_URL
    port = int(os.environ.get("ADF_SMOKE_PORT", "8000"))
    base = f"http://127.0.0.1:{port}"
    _free_fixed_port(port)
    env = dict(os.environ, ADF_SMOKE_PORT=str(port), PORT=str(port))
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=app_dir,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env=env, preexec_fn=os.setsid)
    for _ in range(80):
        if _alive(base):
            return proc, base
        if proc.poll() is not None:
            break
        time.sleep(0.25)
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        pass
    return None, BASE_URL  # failed to boot → ui-visual will still try its own boot
SEV_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def _run(agent, app_dir):
    cmd = [tok.replace("{app_dir}", app_dir).replace("{base_url}", BASE_URL)
           for tok in agent["cmd"]]
    # Resolve a script-relative path to check existence (cmd[1] is the script).
    script = None
    for tok in cmd:
        if tok.endswith((".py", ".mjs", ".js")):
            script = tok if os.path.isabs(tok) else os.path.join(FW, tok)
            break
    if script and not os.path.exists(script):
        return {"id": agent["id"], "ok": True, "gate": agent["gate"],
                "note": "not implemented yet", "implemented": False, "findings": []}
    try:
        r = subprocess.run(cmd, cwd=FW, capture_output=True, text=True,
                           timeout=PER_AGENT_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"id": agent["id"], "ok": False, "gate": agent["gate"],
                "implemented": True,
                "findings": [{"severity": "high", "title": "agent timed out",
                              "detail": f"{agent['id']} exceeded {PER_AGENT_TIMEOUT}s"}]}
    blob = (r.stdout or "").strip()
    if not blob:
        return {"id": agent["id"], "ok": False, "gate": agent["gate"], "implemented": True,
                "findings": [{"severity": "high", "title": "no output",
                              "detail": (r.stderr or "")[-200:]}]}
    try:
        res = json.loads(blob[blob.index("{"):blob.rindex("}") + 1])
    except Exception:
        return {"id": agent["id"], "ok": False, "gate": agent["gate"], "implemented": True,
                "findings": [{"severity": "high", "title": "unparseable output",
                              "detail": blob[-200:]}]}
    # Normalize: accept {findings:[...]} or {defects:[str]}.
    findings = res.get("findings")
    if findings is None:
        findings = [{"severity": "high", "title": d} for d in res.get("defects", [])]
    findings = [f for f in findings
                if not str(f.get("title", "")).startswith("NOTE:")]
    ok = res.get("ok", len(findings) == 0)
    return {"id": agent["id"], "ok": ok and len(findings) == 0, "gate": agent["gate"],
            "implemented": True, "findings": findings,
            "summary": res.get("summary", "")}


def main(app_dir):
    global BASE_URL
    reg = json.load(open(REGISTRY))
    # Boot the app ONCE up front so every dynamic agent shares one live instance
    # (accessibility/e2e/etc. don't boot their own); app_verify.py reuses it.
    needs_app = any(a.get("enabled", True) and a.get("kind") in ("dynamic", "llm")
                    for a in reg["agents"])
    proc = None
    if needs_app:
        proc, BASE_URL = _boot_app(app_dir)
        os.environ["ADF_APP_URL"] = BASE_URL  # children (app_verify) reuse it
    try:
        return _run_all(reg, app_dir)
    finally:
        if proc is not None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass


def _run_all(reg, app_dir):
    results, defects, advisory = [], [], []
    for agent in reg["agents"]:
        if not agent.get("enabled", True):
            continue
        res = _run(agent, app_dir)
        results.append(res)
        if not res.get("implemented", True):
            advisory.append(f"{res['id']}: not implemented yet")
            continue
        # NOTHING IS SKIPPED. A blocking agent blocks on findings at/above its
        # threshold; the default is 'low', so EVERY real defect in the built app
        # (any severity) is fixed one-by-one by the heal loop before the build is
        # called complete. Severity only orders the queue (worst first). Only
        # 'info' (a deliberately defensible / non-actionable note) is advisory.
        # The single exception is an agent whose findings are unbuilt future-scope
        # rather than defects in the current build (the 'functional' coverage
        # agent), which raises its threshold to 'critical' so the campaign can
        # sequence requirement coverage slice-by-slice instead of deadlocking.
        block_at = SEV_RANK.get(str(agent.get("block_severity", "low")).lower(), 1)
        blockers = 0
        for f in res.get("findings", []):
            sev = str(f.get("severity", "high")).lower()
            line = f"[{res['id']}/{sev}] {f.get('title', '')}" \
                   + (f" — {f.get('detail')}" if f.get("detail") else "") \
                   + (f" @ {f.get('location')}" if f.get("location") else "")
            if res["gate"] == "blocking" and SEV_RANK.get(sev, 3) >= block_at:
                defects.append(line)
                blockers += 1
            else:
                advisory.append(line)
        res["blockers"] = blockers
    return {"ok": len(defects) == 0, "defects": defects, "advisory": advisory,
            "agents": [{"id": r["id"], "ok": r["ok"], "gate": r["gate"],
                        "findings": len(r.get("findings", [])),
                        "blockers": r.get("blockers", 0),
                        "summary": r.get("summary", ""),
                        "note": r.get("note")} for r in results]}


if __name__ == "__main__":
    app = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    print(json.dumps(main(app), indent=2))
