#!/usr/bin/env python3
"""DET-2: the deterministic feature-shape classifier + skeleton contract.

These pin two properties that make generation deterministic: the same spec always
classifies to the same shape, and each shape emits a precise, well-formed skeleton
contract (the schema/route/hook the model must fill).

    python3 scripts/orch/test_feature_shapes.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import feature_shapes as fs  # noqa: E402


class Classify(unittest.TestCase):
    def test_crud_list(self):
        self.assertEqual(
            fs.classify("A to-do list app where you add, edit and delete tasks."),
            "crud-list")
        self.assertEqual(
            fs.classify("Manage an inventory of items: list, create, update, "
                        "remove records."),
            "crud-list")

    def test_form(self):
        self.assertEqual(
            fs.classify("A contact form to submit feedback messages."), "form")
        self.assertEqual(
            fs.classify("An event RSVP / registration form users sign up with."),
            "form")

    def test_dashboard(self):
        self.assertEqual(
            fs.classify("A sales dashboard with charts, metrics and KPI summary."),
            "dashboard")
        self.assertEqual(
            fs.classify("Show analytics and trends in an overview report."),
            "dashboard")

    def test_single_record(self):
        self.assertEqual(
            fs.classify("A settings page to view and update your profile "
                        "preferences."),
            "single-record")

    def test_auth(self):
        self.assertEqual(
            fs.classify("A login and signup page with user sessions."), "auth")
        self.assertEqual(
            fs.classify("Sign in / sign out with authentication."), "auth")
        # a plain contact/registration form is still a form, not auth
        self.assertEqual(fs.classify("A contact form to submit feedback."), "form")

    def test_generic_fallback_when_no_signal(self):
        self.assertEqual(fs.classify("Something entirely undescribed here."),
                         "generic")
        self.assertEqual(fs.classify(""), "generic")

    def test_deterministic_repeatable(self):
        text = "A to-do list to add and delete tasks."
        self.assertEqual(fs.classify(text), fs.classify(text))

    def test_tie_breaks_by_priority_order(self):
        # Equal score for crud-list ('add'+'edit' = 2) and single-record
        # ('toggle' = 2); crud-list precedes single-record in SHAPES, so it wins
        # deterministically.
        s = fs.score("add edit toggle")
        self.assertEqual(s["crud-list"], s["single-record"])
        self.assertEqual(fs.classify("add edit toggle"), "crud-list")


class Contract(unittest.TestCase):
    def test_every_shape_has_a_nonempty_contract(self):
        for shape in fs.SHAPES:
            c = fs.skeleton_contract(shape)
            self.assertTrue(c, f"{shape} has no contract")
            self.assertIn("schema.sql", c)
            self.assertIn("server/api/", c)
            self.assertIn("src/hooks/use<Feature>.ts", c)
            self.assertIn("- test", c)
            self.assertIn("DETECTED FEATURE SHAPE", c)

    def test_generic_contract_is_empty(self):
        self.assertEqual(fs.skeleton_contract("generic"), "")

    def test_expected_dom_per_shape(self):
        # SOLID-2: input-driven shapes must render at least one input + one button.
        for shape in ("crud-list", "form", "single-record"):
            e = fs.expected_dom(shape)
            self.assertGreaterEqual(e.get("inputs", 0), 1, shape)
            self.assertGreaterEqual(e.get("buttons", 0), 1, shape)
        # read-mostly / unconstrained shapes carry no DOM requirement (no false-flag).
        self.assertEqual(fs.expected_dom("dashboard"), {})
        self.assertEqual(fs.expected_dom("generic"), {})

    def test_shape_specific_routes(self):
        self.assertIn("DELETE", fs.skeleton_contract("crud-list"))
        self.assertIn("/summary", fs.skeleton_contract("dashboard"))
        self.assertIn("single fixed row", fs.skeleton_contract("single-record"))
        self.assertIn("not edited", fs.skeleton_contract("form"))

    def test_mobile_auth_contract_is_serverless(self):
        # review fix: the mobile (Expo, no-server) auth contract must NOT reference
        # the web server primitive auth.mjs — it must use expo-sqlite + on-device.
        web = fs.skeleton_contract("auth", mobile=False)
        mob = fs.skeleton_contract("auth", mobile=True)
        # the web variant IMPORTS the server primitive; the mobile variant must NOT
        # (it may mention auth.mjs to forbid it — what matters is no import statement).
        self.assertIn("from '../auth.mjs'", web)
        self.assertNotIn("from '../auth.mjs'", mob)
        self.assertIn("expo-sqlite", mob)
        self.assertIn("password_hash", mob)   # still hashed, never plaintext
        shape, text = fs.contract_for(
            {"requirement": "a login and signup screen"}, "auth", mobile=True)
        self.assertEqual(shape, "auth")
        self.assertNotIn("from '../auth.mjs'", text)

    def test_auth_contract_uses_shipped_primitives(self):
        c = fs.skeleton_contract("auth")
        self.assertIn("auth.mjs", c)         # use the shipped primitives
        self.assertIn("hashPassword", c)     # never plaintext
        self.assertIn("401", c)              # the auth-failure case
        e = fs.expected_dom("auth")
        self.assertGreaterEqual(e.get("inputs", 0), 1)
        self.assertGreaterEqual(e.get("buttons", 0), 1)

    def test_contract_for_reads_ctx_and_fid(self):
        shape, text = fs.contract_for(
            {"requirement": "Track a list of items you can add and delete."}, "items-crud")
        self.assertEqual(shape, "crud-list")
        self.assertIn("crud-list", text)
        # fid alone can carry the signal when the spec is thin.
        shape2, _ = fs.contract_for({}, "team-dashboard-metrics")
        self.assertEqual(shape2, "dashboard")

    def test_contract_for_generic_returns_empty_text(self):
        shape, text = fs.contract_for({"requirement": "an opaque widget"}, "x")
        self.assertEqual(shape, "generic")
        self.assertEqual(text, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
