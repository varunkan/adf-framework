#!/usr/bin/env python3
"""Unit tests for export_app.py — the ownership half of the moat. An app exports
as a portable, self-verifying zip: full source + the sealed audit bundle + the
Proof of Build. Your code, your machine — take it and prove it anywhere. (Heavy
build dirs + the live DB are excluded so the zip stays portable.)

    python3 scripts/orch/test_export_app.py
"""
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import export_app as ea  # noqa: E402


def _w(app, rel, content):
    p = os.path.join(app, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)


class Export(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = os.path.join(self.tmp, "apps", "demo")
        _w(self.app, "src/App.tsx", "export const App = () => null\n")
        _w(self.app, "server/index.mjs", "// server\n")
        _w(self.app, ".adf-proof.json", '{"seal":"adf1:abc"}')
        _w(self.app, "node_modules/junk/index.js", "should not ship\n")
        _w(self.app, "data.db", "BINARYDB")
        self.out = os.path.join(self.tmp, "demo.zip")

    def _names(self):
        with zipfile.ZipFile(self.out) as z:
            return set(z.namelist())

    def test_zips_source_bundle_and_readme(self):
        rep = ea.export_app(self.app, self.out,
                            audit_bundle={"format": "adf-audit-bundle/1"},
                            feature_id="demo")
        self.assertTrue(rep["ok"])
        self.assertTrue(os.path.isfile(self.out))
        names = self._names()
        self.assertIn("app/src/App.tsx", names)
        self.assertIn("app/.adf-proof.json", names)
        self.assertIn("audit-bundle.json", names)
        self.assertIn("README.md", names)

    def test_excludes_node_modules_and_live_db(self):
        ea.export_app(self.app, self.out, feature_id="demo")
        names = self._names()
        self.assertFalse(any(n.startswith("app/node_modules/") for n in names))
        self.assertNotIn("app/data.db", names)

    def test_reports_file_count_and_size(self):
        rep = ea.export_app(self.app, self.out, feature_id="demo")
        self.assertGreater(rep["files"], 0)
        self.assertGreater(rep["bytes"], 0)

    def test_missing_app_is_an_error(self):
        rep = ea._main([
            "--app", os.path.join(self.tmp, "nope"),
            "--out", self.out, "--json",
        ])
        self.assertEqual(rep, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
