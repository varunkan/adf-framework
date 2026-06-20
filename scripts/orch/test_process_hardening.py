#!/usr/bin/env python3
"""Hardening tests for the process-discipline integrity surface — the failures the
adversarial audit (and the completeness critic) surfaced: evidence planting, stale
prior-build evidence, non-dict/tampered artifacts, and malformed sealed proofs.

    python3 scripts/orch/test_process_hardening.py
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import process_facts as pf  # noqa: E402


def _plant(app, name, obj):
    """Write a raw artifact the way a MODEL would (no _nonce stamp), bypassing _write."""
    d = os.path.join(app, pf.PROCESS_DIR)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        json.dump(obj, f)


class NonceBinding(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()

    def test_same_nonce_is_read(self):
        pf._write(self.app, "tdd.json", {"proven": True}, env={"ADF_BUILD_NONCE": "A"})
        self.assertIsNotNone(pf._read(self.app, "tdd.json", env={"ADF_BUILD_NONCE": "A"}))

    def test_stale_prior_build_nonce_is_absent(self):
        # written by build "A", read by build "B" → must be treated as absent
        pf._write(self.app, "tdd.json", {"proven": True}, env={"ADF_BUILD_NONCE": "A"})
        self.assertIsNone(pf._read(self.app, "tdd.json", env={"ADF_BUILD_NONCE": "B"}))

    def test_planted_file_without_nonce_is_absent(self):
        # a model-authored evidence file cannot know the per-build nonce
        _plant(self.app, "tdd.json", {"proven": True})
        self.assertIsNone(pf._read(self.app, "tdd.json", env={"ADF_BUILD_NONCE": "real"}))

    def test_planted_proven_tdd_does_not_seal(self):
        # end-to-end: a planted proven tdd.json is ignored by read_process_facts under
        # a real build nonce → no tdd_followed fact (and here, no facts at all)
        _plant(self.app, "tdd.json", {"proven": True})
        self.assertIsNone(pf.read_process_facts(self.app, env={"ADF_BUILD_NONCE": "real"}))

    def test_planted_proven_tdd_cannot_satisfy_strict(self):
        # the worst case: under strict, a plant must NOT satisfy the enforcement gate.
        pf.record_verification(self.app, "react-vite-sqlite")  # stamps nonce "" (unset)
        _plant(self.app, "tdd.json", {"proven": True})
        env = {"ADF_BUILD_NONCE": "real", "ADF_TDD": "strict"}
        # record_verification above used a DIFFERENT (empty) nonce, so under "real" the
        # verification evidence is also absent → read returns None → nothing to enforce
        obj = pf.read_process_facts(self.app, env=env)
        # the plant never becomes a proven tdd fact
        facts = (obj or {}).get("facts", {})
        self.assertNotEqual(facts.get("tdd_followed", {}).get("status"), "proven")


class NonDictArtifacts(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()

    def test_non_dict_artifact_reads_as_absent(self):
        _plant(self.app, "heal.json", [1, 2, 3])     # a list, not a dict
        self.assertIsNone(pf._read(self.app, "heal.json", env={}))

    def test_read_process_facts_does_not_crash_on_non_dict(self):
        for name in ("verification.json", "tdd.json", "heal.json", "review.json",
                     "design.json"):
            _plant(self.app, name, ["weird"])
        # must not raise, and must surface no facts from the junk
        self.assertIsNone(pf.read_process_facts(self.app, env={}))


class MalformedSealedProof(unittest.TestCase):
    """verify_proof feeds these whatever is in a (possibly tampered) .adf-proof.json."""

    def test_summary_line_tolerates_non_dict_process(self):
        self.assertEqual(pf.process_summary_line({"process": ["weird"]}), "")
        self.assertEqual(pf.process_summary_line({"process": {"facts": ["x"]}}), "")
        self.assertEqual(
            pf.process_summary_line({"process": {"facts": {"tdd_followed": "nope"}}}), "")

    def test_required_disciplines_tolerates_malformed(self):
        ok, missing = pf.required_disciplines_met(
            {"process": {"facts": "nope"}}, ["tdd_followed"])
        self.assertFalse(ok)
        self.assertEqual(missing, ["tdd_followed"])
        # a non-dict fact value is not "proven"
        ok2, _ = pf.required_disciplines_met(
            {"process": {"facts": {"tdd_followed": "proven"}}}, ["tdd_followed"])
        self.assertFalse(ok2)


if __name__ == "__main__":
    unittest.main()
