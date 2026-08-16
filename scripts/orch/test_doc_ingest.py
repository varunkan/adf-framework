#!/usr/bin/env python3
"""Unit tests for doc_ingest.py — multimodal document ingest (graceful degrade).

    python3 scripts/orch/test_doc_ingest.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import doc_ingest as di  # noqa: E402


def _tmp(name, content):
    d = tempfile.mkdtemp()
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


class ExtractText(unittest.TestCase):
    def test_markdown(self):
        p = _tmp("req.md", "# Requirements\n\nThe app must store bookmarks.")
        doc = di.extract_text(p)
        self.assertEqual(doc["kind"], "text")
        self.assertIn("store bookmarks", doc["text"])

    def test_csv_profiles_columns_and_rows(self):
        p = _tmp("data.csv", "id,name,dose\n1,DrugA,10mg\n2,DrugB,20mg\n")
        doc = di.extract_text(p)
        self.assertEqual(doc["kind"], "data")
        self.assertIn("Columns: id, name, dose", doc["text"])
        self.assertIn("DrugA", doc["text"])

    def test_missing_file_notes(self):
        doc = di.extract_text("/no/such/file.md")
        self.assertEqual(doc["text"], "")
        self.assertIn("missing file", doc["note"])

    def test_pdf_without_lib_degrades(self):
        p = _tmp("doc.pdf", "%PDF-1.4 fake")
        doc = di.extract_text(p)
        # no pdf lib in the test env → graceful note, no crash
        if not doc["text"]:
            self.assertIn("pdf", doc["note"].lower())

    def test_unsupported_type(self):
        p = _tmp("a.weird", "x")
        self.assertIn("unsupported", di.extract_text(p)["note"])


class Ingest(unittest.TestCase):
    def test_raw_when_no_model(self):
        p = _tmp("req.txt", "Must support ANDS submission.")
        out = di.ingest(p)
        self.assertEqual(out["source"], "req.txt")
        self.assertIn("ANDS submission", out["requirements"])

    def test_model_extracts_requirements(self):
        p = _tmp("req.md", "long doc body describing the regulated workflow")

        def complete(prompt, role):
            self.assertIn("AUTHORITATIVE", prompt)
            return ("- SHALL track submission status\n- SHALL store eCTD modules", {})
        out = di.ingest(p, complete)
        self.assertIn("track submission status", out["requirements"])

    def test_empty_doc_is_safe(self):
        p = _tmp("empty.txt", "")
        out = di.ingest(p)
        self.assertEqual(out["requirements"], "")
        self.assertEqual(out["source"], "empty.txt")


if __name__ == "__main__":
    unittest.main()
