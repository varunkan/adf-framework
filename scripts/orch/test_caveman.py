#!/usr/bin/env python3
"""Unit tests for caveman.py — deterministic, governance-safe prose brevity.

    python3 scripts/orch/test_caveman.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import caveman  # noqa: E402


class Intensity(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(caveman.intensity({}), "off")
        self.assertEqual(caveman.intensity({"ADF_CAVEMAN": "lite"}), "lite")
        self.assertEqual(caveman.intensity({"ADF_CAVEMAN": "FULL"}), "full")
        self.assertEqual(caveman.intensity({"ADF_CAVEMAN": "garbage"}), "off")
        self.assertFalse(caveman.is_enabled({}))


class Compress(unittest.TestCase):
    def test_lite_strips_articles(self):
        out = caveman.compress("Build the app with a server and an api", "lite")
        self.assertNotRegex(out, r"\bthe\b")
        self.assertNotRegex(out, r"\ban\b")
        self.assertIn("Build", out)
        self.assertIn("server", out)
        self.assertIn("api", out)

    def test_full_strips_filler_and_hedges(self):
        out = caveman.compress(
            "I think you should just simply build the app", "full")
        self.assertNotIn("I think", out)
        self.assertNotIn("just", out)
        self.assertNotIn("simply", out)
        self.assertIn("build", out)

    def test_off_is_noop(self):
        s = "the a an just"
        self.assertEqual(caveman.compress(s, "off"), s)

    def test_no_space_before_punctuation(self):
        out = caveman.compress("This is the end.", "lite")
        self.assertNotIn(" .", out)


class GovernanceGuard(unittest.TestCase):
    """The honesty constraint: caveman NEVER alters code, file markers, or
    security/governance text — even when enabled."""

    def test_code_lines_pass_verbatim(self):
        block = ("Build the calculator app.\n"
                 "<<<FILE: src/db.ts>>>\n"
                 "export const the = an + a // keep the article words in CODE\n"
                 "<<<END>>>")
        out = caveman.compress_prose(block, {"ADF_CAVEMAN": "full"})
        self.assertIn("export const the = an + a", out)            # code untouched
        self.assertIn("<<<FILE: src/db.ts>>>", out)                # marker untouched
        self.assertNotRegex(out.split("\n")[0], r"\bthe\b")        # prose line compressed

    def test_security_lines_pass_verbatim(self):
        block = ("Use the helper.\n"
                 "The password and the secret token must use a real crypto API.\n"
                 "ROOT CAUSE: the missing the import")
        out = caveman.compress_prose(block, {"ADF_CAVEMAN": "full"})
        self.assertIn("The password and the secret token must use a real crypto API.",
                      out)
        self.assertIn("ROOT CAUSE: the missing the import", out)
        self.assertNotRegex(out.split("\n")[0], r"\bthe\b")        # benign prose compressed

    def test_disabled_is_total_noop(self):
        block = "the a an I think just build the app"
        self.assertEqual(caveman.compress_prose(block, {}), block)


class Savings(unittest.TestCase):
    def test_estimate_reports_reduction(self):
        before = "the the the the the the the the"
        after = caveman.compress(before, "lite")
        s = caveman.estimate_savings(before, after)
        self.assertGreater(s["chars_before"], s["chars_after"])
        self.assertGreaterEqual(s["pct"], 0.0)

    def test_empty_is_safe(self):
        self.assertEqual(caveman.estimate_savings("", "")["pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
