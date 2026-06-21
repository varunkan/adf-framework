#!/usr/bin/env python3
"""Unit tests for audio_ingest.py — ASR/transcript ingest (graceful degrade, offline).

The headline contract in CI is the DEGRADE path: no ASR backend is installed, so
`ingest` returns a valid dict with `requirements=''` and a human-readable `note`,
without raising. Path traversal is rejected before any file/subprocess access.

    python3 scripts/orch/test_audio_ingest.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audio_ingest as ai  # noqa: E402


class Transcribe(unittest.TestCase):
    def test_missing_file_notes(self):
        # tmp dir is outside the project tree, so confine the root to it (R8) — we are
        # testing the missing-file degrade, not the subtree guard, here.
        d = tempfile.mkdtemp()
        res = ai.transcribe(os.path.join(d, "voice.wav"), allowed_root=d)
        self.assertEqual(res["text"], "")
        self.assertIn("missing file", res["note"].lower())
        self.assertEqual(res["kind"], "audio")

    def test_no_backend_degrades(self):
        # A real (existing) audio file but no transcriber backend in CI → degrade note.
        d = tempfile.mkdtemp()
        p = os.path.join(d, "clip.wav")
        with open(p, "wb") as f:
            f.write(b"RIFF....WAVEfmt ")  # not a real transcribable wav; backend absent
        res = ai.transcribe(p, allowed_root=d)
        self.assertEqual(res["kind"], "audio")
        # With no backend/ADF_ASR_CMD the text is '' and a note explains the degrade.
        if not res["text"]:
            self.assertTrue(res["note"])


class Ingest(unittest.TestCase):
    def test_degrades_without_backend(self):
        # RED test #3 from the spec: import + no-backend degrade. Confine the root to the
        # tmp dir (R8) so we test the no-backend/missing-file degrade, not the subtree
        # guard — and so the note is NOT a subtree rejection.
        d = tempfile.mkdtemp()
        res = ai.ingest(os.path.join(d, "nonexistent.wav"), complete=None,
                        allowed_root=d)
        self.assertEqual(res["requirements"], "")
        self.assertTrue(res["note"])
        self.assertNotIn("subtree", res["note"].lower())
        self.assertEqual(res["kind"], "audio")

    def test_contract_shape(self):
        d = tempfile.mkdtemp()
        res = ai.ingest(os.path.join(d, "nonexistent.wav"), complete=None,
                        allowed_root=d)
        for key in ("source", "kind", "requirements", "raw", "note"):
            self.assertIn(key, res)
        self.assertEqual(res["source"], "nonexistent.wav")

    def test_path_traversal_rejected(self):
        # RED test #5 from the spec.
        res = ai.ingest("../../../etc/passwd")
        self.assertEqual(res["requirements"], "")
        note = res["note"].lower()
        self.assertTrue("rejected" in note or "traversal" in note)

    def test_transcript_returned_as_requirements_when_no_model(self):
        # ADF_ASR_CMD that emits a transcript to stdout; path passed safely (shell=False).
        d = tempfile.mkdtemp()
        p = os.path.join(d, "memo.wav")
        with open(p, "wb") as f:
            f.write(b"audio-bytes")
        # A tiny portable transcriber: python prints a fixed transcript, ignoring path.
        py = sys.executable
        os.environ["ADF_ASR_CMD"] = (
            f"{py} -c \"print('the app SHALL let users log time')\" {{path}}")
        try:
            res = ai.ingest(p, complete=None, allowed_root=d)
        finally:
            del os.environ["ADF_ASR_CMD"]
        self.assertEqual(res["kind"], "audio")
        self.assertIn("log time", res["requirements"])
        self.assertEqual(res["source"], "memo.wav")

    def test_model_extract_pass(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "memo.wav")
        with open(p, "wb") as f:
            f.write(b"audio-bytes")
        py = sys.executable
        os.environ["ADF_ASR_CMD"] = (
            f"{py} -c \"print('rambling spoken notes about a tracker')\" {{path}}")

        def complete(prompt, role):
            self.assertIn("AUTHORITATIVE", prompt)
            return ("- SHALL track habits daily", {})
        try:
            res = ai.ingest(p, complete, allowed_root=d)
        finally:
            del os.environ["ADF_ASR_CMD"]
        self.assertIn("track habits daily", res["requirements"])

    def test_never_raises(self):
        # Even a totally bogus path type-shape must not raise.
        try:
            ai.ingest("")
        except Exception as e:  # noqa: BLE001
            self.fail(f"ingest raised: {e}")

    def test_absolute_path_outside_root_rejected(self):
        # R8 subtree confinement: an absolute path with NO '..' that resolves outside the
        # allowed root (e.g. /etc) must still be rejected — the '..'-only guard missed it.
        d = tempfile.mkdtemp()
        res = ai.ingest("/etc/passwd", allowed_root=d)
        self.assertEqual(res["requirements"], "")
        note = res["note"].lower()
        self.assertTrue("rejected" in note or "subtree" in note)

    def test_subtree_guard_via_env_root(self):
        # The confinement root can also come from ADF_INGEST_ROOT (the env override).
        d = tempfile.mkdtemp()
        os.environ["ADF_INGEST_ROOT"] = d
        try:
            res = ai.ingest("/etc/passwd")
        finally:
            os.environ.pop("ADF_INGEST_ROOT", None)
        self.assertEqual(res["requirements"], "")
        self.assertTrue("rejected" in res["note"].lower())

    def test_path_under_allowed_root_not_subtree_rejected(self):
        # A path UNDER the allowed root passes the subtree guard (it degrades on the
        # missing file / absent backend, NOT on a subtree rejection).
        d = tempfile.mkdtemp()
        res = ai.transcribe(os.path.join(d, "inside.wav"), allowed_root=d)
        self.assertNotIn("subtree", res["note"].lower())
        self.assertNotIn("rejected", res["note"].lower())


if __name__ == "__main__":
    unittest.main()
