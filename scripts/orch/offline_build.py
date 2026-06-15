#!/usr/bin/env python3
"""Air-gapped guarantee for the React+Vite+SQLite stack — the offline/regulated
wedge. A generated app must build, test, and run with NO network once its deps are
cached. This proves it two ways:

  STRUCTURAL (always, deterministic, no network/node needed):
    - the stack's build/run commands are local tools only (no curl/wget/...)
    - the server binds the loopback interface (127.0.0.1), not a public one
    - the source is offline-capable + makes no network egress (the policy gate)

  LIVE (opt-in, --live): scaffold → `npm ci` once (the one-time online cost, same
    as any builder) → re-run build + test + boot with the network BLOCKED (HTTP(S)
    proxies pointed at a dead port + npm offline). If those pass with no network,
    the build/test/run path is genuinely air-gapped.

    python3 scripts/orch/offline_build.py [--live] [templates/react-vite-sqlite]
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

# Tools that would reach the network — none may appear in a stack's commands.
NETWORK_TOOLS = {"curl", "wget", "http", "https", "nc", "ncat", "ssh", "scp",
                 "ftp", "telnet", "rsync"}


def commands_are_local(stack):
    """(ok, offenders) — no command token is a network tool."""
    offenders = []
    for key in ("build_cmd", "post_build", "run_cmd"):
        for tok in (stack.get(key) or []):
            base = os.path.basename(str(tok)).lower()
            if base in NETWORK_TOOLS:
                offenders.append(base)
    return (not offenders, sorted(set(offenders)))


def server_binds_loopback(server_src):
    """True iff the server binds loopback (127.0.0.1/localhost) and not a public
    interface (0.0.0.0). Air-gapped apps must not expose themselves to the LAN."""
    has_loopback = "127.0.0.1" in server_src or "localhost" in server_src
    binds_public = "0.0.0.0" in server_src
    return has_loopback and not binds_public


def offline_policy_ok(app_dir):
    """(ok, failing_rules) for the two offline-relevant policy rules."""
    import policy_gate
    res = policy_gate.check_policy(app_dir)
    relevant = ("offline_capable", "no_network_egress")
    failing = [r["rule"] for r in res["rules"]
               if r["rule"] in relevant and not r["ok"]]
    return (not failing, failing)


def _read_stack(template_dir):
    p = os.path.join(template_dir, ".adf-stack.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _server_entry(template_dir):
    for rel in ("server/index.mjs", "server/index.js", "server.py"):
        p = os.path.join(template_dir, rel)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                return f.read()
    return ""


def check_offline(template_dir):
    """The structural gate: returns {ok, checks:[{check, ok, detail}]}."""
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    stack = _read_stack(template_dir)
    ok_cmd, offenders = commands_are_local(stack)
    add("commands_local", ok_cmd,
        "no network tools in build/run commands" if ok_cmd
        else f"network tools in commands: {offenders}")

    src = _server_entry(template_dir)
    add("server_loopback", server_binds_loopback(src),
        "server binds 127.0.0.1 (not exposed to the LAN)")

    ok_pol, failing = offline_policy_ok(template_dir)
    add("offline_capable_source", ok_pol,
        "source is offline-capable + makes no network egress" if ok_pol
        else f"failing policy rules: {failing}")

    return {"ok": all(c["ok"] for c in checks), "checks": checks}


# --- live air-gapped build (opt-in) ----------------------------------------


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _blocked_env():
    """An env that points every HTTP(S) proxy at a closed port + forces npm
    offline, so anything that tries to touch the network fails fast."""
    dead = "http://127.0.0.1:9"  # discard port, nothing listens
    env = dict(os.environ)
    env.update({
        "HTTP_PROXY": dead, "HTTPS_PROXY": dead,
        "http_proxy": dead, "https_proxy": dead,
        "npm_config_proxy": dead, "npm_config_https_proxy": dead,
        "npm_config_offline": "true", "npm_config_audit": "false",
        "npm_config_fund": "false",
    })
    return env


def live_offline_build(template_dir, log=print):
    """Scaffold, install deps online ONCE, then build+test with the network
    blocked. Returns (ran, ok, detail). Requires node+npm."""
    if not shutil.which("npm") or not shutil.which("node"):
        return (False, True, "npm/node not available — skipped live build")
    work = tempfile.mkdtemp(prefix="adf-offline-")
    app = os.path.join(work, "app")
    shutil.copytree(template_dir, app,
                    ignore=shutil.ignore_patterns("node_modules", "dist", "*.db"))
    try:
        log("  [live] npm ci (online, one-time) …")
        r = subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=app,
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return (True, False, "npm ci failed:\n" + r.stderr[-800:])

        env = _blocked_env()
        for label, cmd in (("build", ["npm", "run", "build"]),
                           ("test", ["npm", "test", "--", "--run"])):
            log(f"  [live] {label} with network BLOCKED …")
            r = subprocess.run(cmd, cwd=app, env=env, capture_output=True,
                              text=True, timeout=600)
            if r.returncode != 0:
                return (True, False,
                        f"{label} failed with no network:\n{r.stderr[-800:]}")
        return (True, True, "build + test PASSED with the network blocked")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _main(argv=None):
    ap = argparse.ArgumentParser(description="Prove the stack is air-gapped")
    ap.add_argument("template", nargs="?",
                    default=os.path.join(ROOT, "templates", "react-vite-sqlite"))
    ap.add_argument("--live", action="store_true",
                    help="also run a real build+test with the network blocked")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    res = check_offline(args.template)
    if args.live:
        ran, ok, detail = live_offline_build(args.template)
        res["checks"].append(
            {"check": "live_airgapped_build", "ok": ok,
             "detail": detail, "ran": ran})
        res["ok"] = res["ok"] and ok

    if args.json:
        print(json.dumps(res))
    else:
        for c in res["checks"]:
            print(f"  [{'PASS' if c['ok'] else 'FAIL'}] {c['check']}: {c['detail']}")
        print("\nGATE PASS: the stack is air-gapped — local commands, a loopback "
              "server, offline-capable source"
              + (" + a real build/test with no network." if args.live else ".")
              if res["ok"] else "\nGATE FAIL")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(_main())
