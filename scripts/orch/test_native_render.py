#!/usr/bin/env python3
"""MM10 — the real iOS-Simulator render rung degrades gracefully (cross-platform)
and is honest: it never claims a render it didn't capture. The live device path is
exercised on a Mac with a booted simulator; here we pin the graceful-skip contract.

    python3 scripts/orch/test_native_render.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import native_render as nr  # noqa: E402


class NativeRenderGraceful(unittest.TestCase):
    def test_disabled_is_ok(self):
        os.environ["ADF_IOS_RENDER"] = "0"
        try:
            ok, detail, shot = nr.ios_render("/nope/dist")
        finally:
            os.environ.pop("ADF_IOS_RENDER", None)
        self.assertTrue(ok)
        self.assertIn("disabled", detail)
        self.assertIsNone(shot)

    def test_no_export_skips_in_auto_but_fails_in_strict(self):
        ok, _detail, shot = nr.ios_render("/nope/dist", app_root=None)
        self.assertTrue(ok)            # auto → graceful skip, never blocks a build
        self.assertIsNone(shot)
        os.environ["ADF_IOS_RENDER"] = "strict"
        try:
            ok_strict, _d, _s = nr.ios_render("/nope/dist", app_root=None)
        finally:
            os.environ.pop("ADF_IOS_RENDER", None)
        self.assertFalse(ok_strict)    # strict → loud failure, no silent pass

    def test_no_booted_simulator_without_xcrun(self):
        orig = nr._xcrun_available
        nr._xcrun_available = lambda: False
        try:
            self.assertIsNone(nr.booted_simulator())
        finally:
            nr._xcrun_available = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
