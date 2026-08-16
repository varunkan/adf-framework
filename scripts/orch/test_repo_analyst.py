#!/usr/bin/env python3
"""Unit tests for repo_analyst.py — existing-repo analysis ingest (stdlib fallback).

In CI the code-review-graph binary is NOT on $PATH and ADF_CODE_REVIEW_GRAPH_BIN is
pointed at a nonexistent path, so the tests exercise the PRIMARY path: the stdlib
`os.walk` fallback. Path traversal is rejected before any file/subprocess access.

    python3 scripts/orch/test_repo_analyst.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import repo_analyst as ra  # noqa: E402


def _mkrepo():
    d = tempfile.mkdtemp()
    open(os.path.join(d, "sub.py"), "w").close()
    open(os.path.join(d, "README.md"), "w").close()
    os.makedirs(os.path.join(d, "pkg"))
    open(os.path.join(d, "pkg", "core.py"), "w").close()
    return d


class Analyze(unittest.TestCase):
    def setUp(self):
        # Force the stdlib fallback regardless of host machine state.
        os.environ["ADF_CODE_REVIEW_GRAPH_BIN"] = "/nonexistent/bin/crg"
        # tmp repos live outside the project tree; confine the subtree-guard (R8) to the
        # system temp dir so these tests exercise analysis, not the subtree rejection.
        os.environ["ADF_INGEST_ROOT"] = tempfile.gettempdir()

    def tearDown(self):
        os.environ.pop("ADF_CODE_REVIEW_GRAPH_BIN", None)
        os.environ.pop("ADF_INGEST_ROOT", None)

    def test_stdlib_fallback_lists_files(self):
        d = _mkrepo()
        res = ra.analyze(d)
        self.assertEqual(res["kind"], "repo")
        self.assertTrue(res["note"])  # marks the stdlib fallback
        self.assertTrue("sub.py" in res["text"] or "README" in res["text"])

    def test_missing_dir_notes(self):
        res = ra.analyze(os.path.join(tempfile.gettempdir(), "no_such_repo_here_xyz"))
        self.assertEqual(res["text"], "")
        self.assertIn("missing repo path", res["note"].lower())

    def test_file_not_dir_notes(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "afile.txt")
        open(p, "w").close()
        res = ra.analyze(p)
        self.assertEqual(res["text"], "")
        self.assertTrue(res["note"])


class Ingest(unittest.TestCase):
    def setUp(self):
        os.environ["ADF_CODE_REVIEW_GRAPH_BIN"] = "/nonexistent/bin/crg"
        os.environ["ADF_INGEST_ROOT"] = tempfile.gettempdir()

    def tearDown(self):
        os.environ.pop("ADF_CODE_REVIEW_GRAPH_BIN", None)
        os.environ.pop("ADF_INGEST_ROOT", None)

    def test_stdlib_fallback_summarizes_dir(self):
        # RED test #4 from the spec.
        d = _mkrepo()
        res = ra.ingest(d, complete=None)
        self.assertIn("kind", res)
        self.assertEqual(res["kind"], "repo")
        self.assertTrue(res["note"])
        self.assertTrue("sub.py" in res["raw"] or "README" in res["raw"])

    def test_contract_shape(self):
        d = _mkrepo()
        res = ra.ingest(d, complete=None)
        for key in ("source", "kind", "requirements", "raw", "note"):
            self.assertIn(key, res)
        self.assertEqual(res["source"], os.path.basename(d))

    def test_raw_capped(self):
        d = _mkrepo()
        res = ra.ingest(d, complete=None)
        self.assertLessEqual(len(res["raw"]), 8000)

    def test_path_traversal_rejected(self):
        res = ra.ingest("../../../etc")
        self.assertEqual(res["requirements"], "")
        note = res["note"].lower()
        self.assertTrue("rejected" in note or "traversal" in note)

    def test_model_extract_pass(self):
        d = _mkrepo()

        def complete(prompt, role):
            self.assertEqual(role, "draft")
            return ("- existing app uses a pkg/core module", {})
        res = ra.ingest(d, complete)
        self.assertIn("pkg/core module", res["requirements"])

    def test_never_raises(self):
        try:
            ra.ingest("")
        except Exception as e:  # noqa: BLE001
            self.fail(f"ingest raised: {e}")

    def test_absolute_path_outside_root_rejected(self):
        # R8 subtree confinement: /etc has no '..' but resolves outside the allowed root,
        # so it must be rejected — the system tree is never folded into the LLM prompt.
        d = tempfile.mkdtemp()
        res = ra.ingest("/etc", allowed_root=d)
        self.assertEqual(res["requirements"], "")
        note = res["note"].lower()
        self.assertTrue("rejected" in note or "subtree" in note)

    def test_path_under_allowed_root_accepted(self):
        # A repo UNDER the allowed root passes the subtree guard and is summarized.
        d = tempfile.mkdtemp()
        repo = os.path.join(d, "myrepo")
        os.makedirs(repo)
        open(os.path.join(repo, "known.py"), "w").close()
        res = ra.ingest(repo, complete=None, allowed_root=d)
        self.assertEqual(res["kind"], "repo")
        self.assertNotIn("rejected", res["note"].lower())
        self.assertIn("known.py", res["raw"])


if __name__ == "__main__":
    unittest.main()
