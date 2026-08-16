#!/usr/bin/env python3
"""ADF app verification gate — proves the RUNNING app is clean, which unit tests
and the reviewer were NOT checking (the serious gap).

Boots the app once, then collects defects from two layers:
  1. HTTP: GET / must be 200 with no traceback; every /api route the UI references
     must not 5xx or return a traceback.
  2. BROWSER (headless Chrome via browser_smoke.mjs): no uncaught JS exceptions,
     no console.error, no failed (>=400) network calls — on load AND while a user
     fills inputs and clicks every button.

Prints JSON {"ok": bool, "defects": [...]}. ADF gates 'complete' on ok==true.
If node/Chrome is unavailable the browser layer is skipped (HTTP still gates).
"""
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

PORT = int(os.environ.get("ADF_SMOKE_PORT", "8000"))
BASE = f"http://127.0.0.1:{PORT}"
HERE = os.path.dirname(os.path.abspath(__file__))
ERR_RE = re.compile(
    r"Traceback \(most recent call last\)|Internal Server Error|"
    r"\b(NameError|KeyError|TypeError|AttributeError|ValueError|UnboundLocalError|"
    r"ImportError|ModuleNotFoundError|IndentationError|SyntaxError|sqlite3\.\w*Error)\b"
)


def _free_port():
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{PORT}"],
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


def _alive(url):
    try:
        urllib.request.urlopen(url, timeout=3)
        return True
    except urllib.error.HTTPError:
        return True  # responded (even a 4xx) → server is up
    except Exception:
        return False


def _get(path):
    try:
        r = urllib.request.urlopen(BASE + path, timeout=8)
        return r.getcode(), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        return e.code, body
    except Exception as e:
        return None, repr(e)


def _http_defects():
    defects = []
    code, html = _get("/")
    if code != 200:
        defects.append(f"GET / -> HTTP {code} (the UI page did not load)")
    if html and ERR_RE.search(html):
        defects.append("GET / response body contains a server error / traceback")
    eps = set(re.findall(r"""["'`](/api/[A-Za-z0-9_/\-]+)["'`]""", html or ""))
    eps |= set(re.findall(r"""(?:href|action)\s*=\s*["'](/[A-Za-z0-9_/\-]+)["']""", html or ""))
    eps.discard("/")
    for ep in sorted(eps):
        c, b = _get(ep)
        if c is None:
            defects.append(f"{ep} -> request failed: {b[:100]}")
        elif c >= 500:
            defects.append(f"{ep} -> HTTP {c} (server error on a route the UI calls)")
        elif b and ERR_RE.search(b):
            defects.append(f"{ep} -> response body contains a traceback")
    return defects


def _browser_defects(app_dir):
    """Full visual validation (visual_verify.mjs) — crawl every view + form on
    desktop AND mobile, screenshot each, flag blank renders / on-screen error text
    / JS exceptions / console.error / failed network calls. Falls back to the
    lighter browser_smoke.mjs, then to nothing if node/Chrome is unavailable."""
    node = os.environ.get("ADF_NODE", "node")
    visual = os.path.join(HERE, "visual_verify.mjs")
    smoke = os.path.join(HERE, "browser_smoke.mjs")
    if os.path.exists(visual):
        shot = os.path.join(app_dir, ".adf-visual")
        mjs, args, timeout = visual, [BASE + "/", shot], 600
    elif os.path.exists(smoke):
        mjs, args, timeout = smoke, [BASE + "/"], 120
    else:
        return []
    try:
        r = subprocess.run([node, mjs, *args], capture_output=True,
                           text=True, timeout=timeout)
    except FileNotFoundError:
        return []  # node unavailable → skip browser layer (HTTP still gates)
    except subprocess.TimeoutExpired:
        return ["visual validation timed out (a view may hang)"]
    blob = (r.stdout or "").strip()
    if not blob:
        return ["visual validation produced no output: " + (r.stderr or "")[-200:]]
    # The validator prints one pretty-printed (multi-line) JSON object; parse the
    # whole object (first '{' .. last '}'), not just the last line.
    try:
        res = json.loads(blob[blob.index("{"): blob.rindex("}") + 1])
    except Exception:
        return ["visual validation output unparseable: " + blob[-200:]]
    # NOTE: lines are informational (caps/budget), not defects.
    return [] if res.get("ok", True) else [
        d for d in res.get("defects", []) if not str(d).startswith("NOTE:")]


def verify(app_dir):
    if not os.path.exists(os.path.join(app_dir, "server.py")):
        return {"ok": False, "defects": ["no server.py in app"]}
    # REUSE a shared instance: when the orchestrator (run_test_agents.py) has
    # already booted the app and points ADF_APP_URL at it, do NOT free/boot/kill
    # our own — that would race the shared server other dynamic agents depend on.
    # Just verify against it. Only boot our own when running standalone.
    shared = os.environ.get("ADF_APP_URL", "").strip()
    if shared and _alive(shared):
        defects = _http_defects() + _browser_defects(app_dir)
        uniq = list(dict.fromkeys(defects))
        return {"ok": len(uniq) == 0, "defects": uniq}
    _free_port()
    proc = subprocess.Popen([sys.executable, "server.py"], cwd=app_dir,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, preexec_fn=os.setsid)
    defects = []
    try:
        up = False
        for _ in range(60):
            c, _b = _get("/")
            if c is not None:
                up = True
                break
            if proc.poll() is not None:
                break
            time.sleep(0.25)
        if not up:
            log = ""
            try:
                if proc.poll() is not None and proc.stdout:
                    log = proc.stdout.read()[:800]
            except Exception:
                pass
            return {"ok": False,
                    "defects": [f"server.py did not boot on :{PORT}. {log.strip()[:500]}"]}
        defects += _http_defects()
        defects += _browser_defects(app_dir)
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        for db in ("submissions.db", "data.db", "app.db"):
            try:
                os.remove(os.path.join(app_dir, db))
            except Exception:
                pass
    uniq = list(dict.fromkeys(defects))
    return {"ok": len(uniq) == 0, "defects": uniq}


if __name__ == "__main__":
    app = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
    print(json.dumps(verify(app), indent=2))
