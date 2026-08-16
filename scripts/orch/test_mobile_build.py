#!/usr/bin/env python3
"""Tests for mobile_build.py — the native-build decisions ADF owns.

    python3 scripts/orch/test_mobile_build.py
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mobile_build as mb  # noqa: E402


class MobileBuild(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.app = os.path.join(self.tmp, "app")
        os.makedirs(os.path.join(self.app, "app"))
        os.makedirs(os.path.join(self.app, "src"))
        json.dump({"expo": {"name": "adf-expo-app"}},
                  open(os.path.join(self.app, "app.json"), "w"))
        json.dump({"dependencies": {
            "expo-router": "1", "expo-sqlite": "14", "react-native": "0.74"}},
            open(os.path.join(self.app, "package.json"), "w"))
        os.makedirs(os.path.join(self.app, "node_modules", "expo-sqlite"))

    def _write(self, rel, content):
        with open(os.path.join(self.app, rel), "w") as f:
            f.write(content)

    def test_package_id_sanitized_and_namespaced(self):
        self.assertEqual(mb.package_id("calculator"), "com.adf.calculator")
        self.assertEqual(mb.package_id("tip-calc_2"), "com.adf.tipcalc2")
        self.assertEqual(mb.package_id(""), "com.adf.app")
        # always under com.adf.* → can never collide with the host's app id
        self.assertTrue(mb.package_id("anything").startswith("com.adf."))

    def test_strip_removes_unused_native(self):
        self._write("app/index.tsx", "import {View} from 'react-native';")
        stripped = mb.strip_unused_native(self.app)
        self.assertIn("expo-sqlite", stripped)
        pkg = json.load(open(os.path.join(self.app, "package.json")))
        self.assertNotIn("expo-sqlite", pkg["dependencies"])
        self.assertFalse(
            os.path.isdir(os.path.join(self.app, "node_modules", "expo-sqlite")))
        self.assertIn("expo-router", pkg["dependencies"])  # core kept

    def test_strip_keeps_used_native(self):
        self._write("src/db.ts", "import * as SQLite from 'expo-sqlite';")
        stripped = mb.strip_unused_native(self.app)
        self.assertNotIn("expo-sqlite", stripped)
        pkg = json.load(open(os.path.join(self.app, "package.json")))
        self.assertIn("expo-sqlite", pkg["dependencies"])
        self.assertTrue(
            os.path.isdir(os.path.join(self.app, "node_modules", "expo-sqlite")))

    def test_ensure_native_ids(self):
        pkg, name = mb._ensure_native_ids(self.app, "tip-calc")
        self.assertEqual(pkg, "com.adf.tipcalc")
        self.assertEqual(name, "Tip Calc")
        exp = json.load(open(os.path.join(self.app, "app.json")))["expo"]
        self.assertEqual(exp["android"]["package"], "com.adf.tipcalc")
        self.assertEqual(exp["ios"]["bundleIdentifier"], "com.adf.tipcalc")

    def test_build_apk_gated_without_toolchain(self):
        with mock.patch.object(mb, "android_sdk", return_value=None):
            ok, detail, apk = mb.build_apk(self.app, "calculator")
        self.assertFalse(ok)
        self.assertIsNone(apk)
        self.assertIn("toolchain absent", detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
