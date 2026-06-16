#!/usr/bin/env python3
"""Tests for component_manifest.py — the per-app COMPONENT MANIFEST (the
project-specific artifact). It scans a generated app's src/components for the
self-contained, reusable components it produced, captures each one's exported
props (its public API), and writes .adf-components.json + COMPONENTS.md so the
components are discoverable and reusable by future features.

    python3 scripts/orch/test_component_manifest.py
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import component_manifest as cm  # noqa: E402


def _w(app, rel, content):
    p = os.path.join(app, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)


class Extract(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()
        _w(self.app, "src/components/Counter/Counter.tsx",
           "interface CounterProps { count: number; onInc: () => void; "
           "label?: string }\n"
           "export default function Counter(props: CounterProps) { return null }\n")
        _w(self.app, "src/components/ui/Button.tsx",
           "export interface ButtonProps { onClick: () => void }\n"
           "export const Button = (p: ButtonProps) => null\n")
        _w(self.app, "src/App.tsx",
           "export default function App() { return null }\n")
        _w(self.app, "src/main.tsx", "// bootstrap, not a component\n")

    def test_finds_components_with_paths(self):
        comps = cm.extract_components(self.app)
        names = {c["name"] for c in comps}
        self.assertIn("Counter", names)
        self.assertIn("Button", names)
        # main.tsx is bootstrap, not listed as a reusable component
        self.assertNotIn("main", names)

    def test_captures_exported_props_api(self):
        comps = cm.extract_components(self.app)
        counter = next(c for c in comps if c["name"] == "Counter")
        pnames = {p["name"]: p for p in counter["props"]}
        self.assertEqual(pnames["count"]["type"], "number")
        self.assertFalse(pnames["count"]["optional"])
        self.assertTrue(pnames["label"]["optional"])

    def test_excludes_non_component_constants(self):
        _w(self.app, "src/components/consts.tsx",
           "export const MAX = 5\nexport const API_URL = '/api'\n")
        names = {c["name"] for c in cm.extract_components(self.app)}
        self.assertNotIn("MAX", names)
        self.assertNotIn("API_URL", names)


class Manifest(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()
        _w(self.app, "src/components/Card.tsx",
           "interface CardProps { title: string }\n"
           "export function Card(p: CardProps) { return null }\n")

    def test_writes_json_and_markdown(self):
        data = cm.generate(self.app)
        self.assertEqual(data["format"], "adf-components/1")
        self.assertGreaterEqual(data["count"], 1)
        self.assertTrue(os.path.isfile(
            os.path.join(self.app, ".adf-components.json")))
        md = open(os.path.join(self.app, "COMPONENTS.md")).read()
        self.assertIn("Card", md)
        self.assertIn("title", md)
        # the json round-trips
        j = json.load(open(os.path.join(self.app, ".adf-components.json")))
        self.assertEqual(j["count"], data["count"])

    def test_no_components_dir_is_safe(self):
        empty = tempfile.mkdtemp()
        data = cm.generate(empty)
        self.assertEqual(data["count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
