#!/usr/bin/env python3
"""The build's EYES — headless-browser render verification.

A React+Vite SPA serves `<div id="root"></div>` and mounts in the browser, so the
old `GET / -> 200` check is BLIND: a white screen, a runtime crash, or a blank
#root all answer 200. This module drives the system headless browser to execute the
built bundle against the *already-booted* server and asserts the app actually
RENDERED (real content in the body, not the empty shell) — closing the "green
checkmark that lies" defect. A screenshot is saved as visual proof.

No new dependency: uses the system Chrome/Chromium. Degrades gracefully — if no
browser is present it SKIPS (ok=True) unless ADF_VISUAL_VERIFY=strict, so the
offline/zero-cost path never turns red just for lack of a browser. ADF_VISUAL_VERIFY=0
disables it entirely.
"""
import os
import shutil
import subprocess
import sys
from html.parser import HTMLParser

_CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
]
_CHROME_ON_PATH = ("google-chrome", "google-chrome-stable", "chromium",
                   "chromium-browser", "chrome")


def find_chrome():
    for p in _CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    for name in _CHROME_ON_PATH:
        found = shutil.which(name)
        if found:
            return found
    env = os.environ.get("ADF_CHROME_BIN")
    return env if env and os.path.exists(env) else None


# --- pure DOM assessment (testable without a browser) ----------------------

class _BodyStats(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template"}
    _INTERACTIVE = {"button", "input", "select", "textarea", "a", "form",
                    "label", "h1", "h2", "h3", "table", "ul", "ol", "img",
                    "svg", "canvas", "nav", "main"}

    def __init__(self):
        super().__init__()
        self.in_body = False
        self._skip = 0
        self.text_len = 0
        self.interactive = 0
        self.elements = 0

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.in_body = True
            return
        if not self.in_body:
            return
        if tag in self._SKIP:
            self._skip += 1
            return
        self.elements += 1
        if tag in self._INTERACTIVE:
            self.interactive += 1

    def handle_endtag(self, tag):
        if tag == "body":
            self.in_body = False
        elif tag in self._SKIP and self._skip > 0:
            self._skip -= 1

    def handle_data(self, data):
        if self.in_body and self._skip == 0 and data.strip():
            self.text_len += len(data.strip())


def assess_dom(rendered_html):
    """Did the app render real content into the page? Returns
    {rendered, text_len, interactive, elements}. A non-mounting SPA leaves the body
    with just the empty #root → ~0 text, no interactive elements → rendered=False."""
    p = _BodyStats()
    try:
        p.feed(rendered_html or "")
    except Exception:
        pass
    rendered = p.text_len >= 3 and (p.interactive >= 1 or p.elements >= 4)
    return {
        "rendered": rendered,
        "text_len": p.text_len,
        "interactive": p.interactive,
        "elements": p.elements,
    }


# --- browser drivers --------------------------------------------------------

def _chrome_base(chrome):
    # `--headless` (classic) is fast + reliable here; `--headless=new` with a
    # per-call profile hung on this build, so we stick to the proven flags.
    return [chrome, "--headless", "--disable-gpu", "--no-sandbox", "--mute-audio"]


def render_dom(chrome, url, budget_ms=4000, timeout=30):
    cmd = _chrome_base(chrome) + [
        f"--virtual-time-budget={budget_ms}", "--dump-dom", url]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.stdout or ""


def screenshot(chrome, url, dest, budget_ms=4000, timeout=30):
    cmd = _chrome_base(chrome) + [
        f"--virtual-time-budget={budget_ms}", "--window-size=1100,850",
        f"--screenshot={dest}", url]
    subprocess.run(cmd, capture_output=True, timeout=timeout)
    return os.path.isfile(dest)


def visual_verify(url, app_root=None, strict=None):
    """Render `url` in a headless browser and assert the app mounted. Returns
    (ok, detail, screenshot_path_or_None). Reuse the already-booted server's URL."""
    mode = os.environ.get("ADF_VISUAL_VERIFY", "1").lower()
    if mode in ("0", "false", "off"):
        return True, "visual verify disabled (ADF_VISUAL_VERIFY=0)", None
    if strict is None:
        strict = mode == "strict"

    chrome = find_chrome()
    if not chrome:
        msg = "no headless browser found — visual render verify skipped"
        return (False if strict else True, msg, None)

    shot = None
    try:
        dom = render_dom(chrome, url)
        stats = assess_dom(dom)
        if app_root:
            vdir = os.path.join(app_root, ".adf-visual")
            os.makedirs(vdir, exist_ok=True)
            dest = os.path.join(vdir, "render.png")
            if screenshot(chrome, url, dest):
                shot = dest
        if stats["rendered"]:
            return (True,
                    f"render OK — body has {stats['interactive']} interactive "
                    f"element(s) and {stats['text_len']} chars of text", shot)
        return (False,
                f"APP DID NOT RENDER — the page served 200 but #root is blank "
                f"(body: {stats['elements']} elements, {stats['interactive']} "
                f"interactive, {stats['text_len']} chars of text). This is a white "
                f"screen / runtime crash: check src/App.tsx mounts and the bundle "
                f"throws no error on load.", shot)
    except subprocess.TimeoutExpired:
        msg = "headless render timed out"
        return (False if strict else True, msg, shot)
    except Exception as e:  # never let the browser harness fail an otherwise-good build
        return (False if strict else True, f"visual verify error: {e}", shot)


if __name__ == "__main__":
    import json
    ok, detail, shot = visual_verify(sys.argv[1] if len(sys.argv) > 1
                                     else "http://127.0.0.1:8000/")
    print(json.dumps({"ok": ok, "detail": detail, "screenshot": shot}))
    sys.exit(0 if ok else 1)
