#!/usr/bin/env python3
"""ADF test-agent ecosystem orchestrator — the verification gate.

Runs every enabled agent in scripts/orch/test_agents/registry.json against the
built app, aggregates their findings, and decides whether the app is COMPLETE.
A blocking agent with any finding fails the gate; advisory agents are reported
but don't block. A blocking agent whose script doesn't exist yet is reported as
'not implemented' (advisory) so the ecosystem rolls out incrementally.

Output (compatible with the existing UI gate): {"ok":bool,"defects":[str],
"advisory":[str],"agents":[{id,ok,gate,findings|note}]}. `defects` are the
blocking findings flattened to strings; ADF feeds them to the relentless heal loop.

Usage: run_test_agents.py <app_dir>
"""
import json
import os
import subprocess
import sys

FW = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.path.join(FW, "scripts", "orch", "test_agents", "registry.json")
BASE_URL = os.environ.get("ADF_APP_URL", "http://127.0.0.1:8000")
PER_AGENT_TIMEOUT = int(os.environ.get("ADF_AGENT_TIMEOUT", "600"))


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
    reg = json.load(open(REGISTRY))
    results, defects, advisory = [], [], []
    for agent in reg["agents"]:
        if not agent.get("enabled", True):
            continue
        res = _run(agent, app_dir)
        results.append(res)
        if not res.get("implemented", True):
            advisory.append(f"{res['id']}: not implemented yet")
            continue
        for f in res.get("findings", []):
            line = f"[{res['id']}/{f.get('severity', '?')}] {f.get('title', '')}" \
                   + (f" — {f.get('detail')}" if f.get("detail") else "") \
                   + (f" @ {f.get('location')}" if f.get("location") else "")
            (defects if res["gate"] == "blocking" else advisory).append(line)
    return {"ok": len(defects) == 0, "defects": defects, "advisory": advisory,
            "agents": [{"id": r["id"], "ok": r["ok"], "gate": r["gate"],
                        "findings": len(r.get("findings", [])),
                        "note": r.get("note")} for r in results]}


if __name__ == "__main__":
    app = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    print(json.dumps(main(app), indent=2))
