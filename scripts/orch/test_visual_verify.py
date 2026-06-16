#!/usr/bin/env python3
"""Tests for visual_verify.py — the build's EYES. A React SPA returns HTTP 200 with
an empty `<div id="root">`; only a browser that executes the bundle can tell whether
it rendered. These tests prove the verifier (a) PASSES a page whose #root is filled
by JavaScript (i.e. it really executes the app), and (b) FAILS a blank/non-mounting
page — the white-screen defect the old GET/->200 check shipped as 'verified'.

    python3 scripts/orch/test_visual_verify.py
"""
import http.server
import os
import socketserver
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import visual_verify as vv  # noqa: E402


def _serve(directory):
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(
        *a, directory=directory, **k)
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    httpd.allow_reuse_address = True
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, port


class VisualVerify(unittest.TestCase):
    def setUp(self):
        if not vv.find_chrome():
            self.skipTest("no headless browser found")
        self.dir = tempfile.mkdtemp()

    def _write(self, html):
        with open(os.path.join(self.dir, "index.html"), "w") as f:
            f.write("<!doctype html><html><head><title>App</title></head>"
                    "<body>" + html + "</body></html>")

    def test_client_rendered_content_passes(self):
        # empty #root that JS fills — exactly the SPA case curl can't see.
        self._write('<div id="root"></div><script>'
                    'document.getElementById("root").innerHTML='
                    '"<h1>Hello App</h1><button>Go</button><p>ready</p>";'
                    '</script>')
        httpd, port = _serve(self.dir)
        try:
            ok, msg, shot = vv.visual_verify(
                f"http://127.0.0.1:{port}/", app_root=self.dir)
            self.assertTrue(ok, f"a JS-rendered page must pass: {msg}")
            # and it captured a screenshot artifact
            self.assertTrue(shot and os.path.isfile(shot), "screenshot artifact")
        finally:
            httpd.shutdown()

    def test_blank_non_mounting_root_fails(self):
        self._write('<div id="root"></div><script>/* never mounts */</script>')
        httpd, port = _serve(self.dir)
        try:
            ok, msg, _ = vv.visual_verify(f"http://127.0.0.1:{port}/")
            self.assertFalse(ok, "a blank/non-mounting SPA must FAIL render verify")
            self.assertIn("render", msg.lower())
        finally:
            httpd.shutdown()

    def test_disabled_via_env_is_a_noop_pass(self):
        os.environ["ADF_VISUAL_VERIFY"] = "0"
        try:
            ok, msg, _ = vv.visual_verify("http://127.0.0.1:1/")
            self.assertTrue(ok)
            self.assertIn("disabled", msg.lower())
        finally:
            os.environ.pop("ADF_VISUAL_VERIFY", None)


class AssessDom(unittest.TestCase):
    """The DOM assessment is pure + deterministic — testable without a browser."""

    def test_blank_root_has_no_body_content(self):
        a = vv.assess_dom('<html><body><div id="root"></div>'
                          '<script>x()</script></body></html>')
        self.assertFalse(a["rendered"])

    def test_real_content_is_detected(self):
        a = vv.assess_dom('<html><body><div id="root">'
                          '<h1>Tip Calculator</h1><button>Calculate</button>'
                          '</div></body></html>')
        self.assertTrue(a["rendered"])
        self.assertGreaterEqual(a["interactive"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
