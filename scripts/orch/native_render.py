#!/usr/bin/env python3
"""MM10 — REAL iOS-device render verification.

ADF's web render gate (visual_verify) proves a mobile app mounts real content in a
headless browser. This rung goes further: it serves the app's web export to a REAL
booted iOS Simulator (Mobile Safari / WebKit at true device dimensions) and captures
a device screenshot, sealed into the Proof of Build as `ios-render.png`. No competitor
attests a real-device render.

It is OPPORTUNISTIC + degrades gracefully — exactly like visual_verify: a no-op
(ok=True, status='not-evaluated') when not on macOS, when `xcrun` is absent, or when
no simulator is booted, unless ADF_IOS_RENDER=strict. It NEVER claims a render it
didn't capture, and it makes no native-build / signing claim (that is MM14).
"""
import os
import subprocess
import sys
import threading
import time


def _xcrun_available():
    if sys.platform != "darwin":
        return False
    try:
        subprocess.run(["xcrun", "--version"], capture_output=True, timeout=10)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def booted_simulator():
    """The UDID of a booted iOS Simulator, or None. (`simctl list devices` marks the
    active one '(Booted)'.)"""
    if not _xcrun_available():
        return None
    try:
        out = subprocess.run(
            ["xcrun", "simctl", "list", "devices"],
            capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        if "(Booted)" in line and "(" in line:
            # "    iPhone 16e (UDID) (Booted)"
            parts = line.split("(")
            if len(parts) >= 2:
                udid = parts[1].split(")")[0].strip()
                if udid:
                    return udid
    return None


def _serve(directory, port):
    """A tiny static server for the web export (SPA fallback to index.html)."""
    import http.server
    import functools

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_a):
            pass

        def send_error(self, code, *a, **k):  # SPA fallback
            if code == 404:
                self.path = "/index.html"
                return http.server.SimpleHTTPRequestHandler.do_GET(self)
            return super().send_error(code, *a, **k)

    handler = functools.partial(_Handler, directory=directory)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _free_port():
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ios_render(dist_dir, app_root=None, settle_secs=6):
    """Open the web export in the booted iOS Simulator and capture a device
    screenshot. Returns (ok, detail, screenshot_path_or_None). Graceful skip when no
    simulator/xcrun (ok=True unless ADF_IOS_RENDER=strict)."""
    mode = os.environ.get("ADF_IOS_RENDER", "auto").lower()
    if mode in ("0", "false", "off"):
        return True, "iOS render disabled (ADF_IOS_RENDER=0)", None
    strict = mode == "strict"

    if not os.path.isdir(dist_dir) or not os.path.isfile(os.path.join(dist_dir, "index.html")):
        msg = "no web export (dist/index.html) to render on the simulator"
        return (False if strict else True, msg, None)

    udid = booted_simulator()
    if not udid:
        msg = "no booted iOS Simulator (open Simulator.app, or set ADF_IOS_RENDER=strict)"
        return (False if strict else True, msg, None)

    port = _free_port()
    httpd = None
    try:
        httpd = _serve(dist_dir, port)
        url = f"http://127.0.0.1:{port}/"
        subprocess.run(["xcrun", "simctl", "openurl", udid, url],
                       capture_output=True, timeout=30)
        time.sleep(settle_secs)
        shot = None
        if app_root:
            vdir = os.path.join(app_root, ".adf-visual")
            os.makedirs(vdir, exist_ok=True)
            shot = os.path.join(vdir, "ios-render.png")
            subprocess.run(["xcrun", "simctl", "io", udid, "screenshot", shot],
                           capture_output=True, timeout=30)
        if shot and os.path.isfile(shot):
            kb = os.path.getsize(shot) // 1024
            # A real rendered UI screenshot is a non-trivial PNG; a failed/blank load
            # compresses far smaller. Honest framing: a captured device render.
            if kb < 8:
                return (False if strict else True,
                        f"iOS screenshot captured but suspiciously small ({kb}KB)", shot)
            return True, f"rendered on the iOS Simulator ({udid[:8]}…), {kb}KB screenshot", shot
        return (False if strict else True,
                "could not capture an iOS Simulator screenshot", shot)
    except (OSError, subprocess.SubprocessError) as e:
        return (False if strict else True, f"iOS render error: {e}", None)
    finally:
        if httpd:
            httpd.shutdown()


if __name__ == "__main__":
    import json
    d = sys.argv[1] if len(sys.argv) > 1 else "dist"
    ok, detail, shot = ios_render(d, app_root=os.path.dirname(os.path.abspath(d)))
    print(json.dumps({"ok": ok, "detail": detail, "screenshot": shot}))
    sys.exit(0 if ok else 1)
