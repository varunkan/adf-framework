#!/usr/bin/env python3
"""Unit tests for proof_of_build.py — ADF's Proof of Build: a tamper-evident
Merkle seal shipped INSIDE every generated app, recomputable offline by anyone.

    python3 scripts/orch/test_proof_of_build.py
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proof_of_build as pob  # noqa: E402

BUILD = {"backend": "stub", "model": "test", "verified": True,
         "verify_summary": "build + vitest passed; boots on :5"}


class Merkle(unittest.TestCase):
    def test_seal_is_deterministic(self):
        files = [("a.ts", "export const a = 1\n"), ("b.ts", "export const b = 2\n")]
        p1 = pob.compute_proof("demo", "react-vite-sqlite", files, "spec", BUILD)
        p2 = pob.compute_proof("demo", "react-vite-sqlite", files, "spec", BUILD)
        self.assertEqual(p1["merkle_root"], p2["merkle_root"])
        self.assertTrue(p1["seal"].startswith("adf1:"))

    def test_seal_is_order_independent(self):
        a = [("a.ts", "1"), ("b.ts", "2")]
        b = [("b.ts", "2"), ("a.ts", "1")]
        self.assertEqual(
            pob.compute_proof("d", "s", a, "spec", BUILD)["merkle_root"],
            pob.compute_proof("d", "s", b, "spec", BUILD)["merkle_root"],
        )

    def test_any_byte_change_breaks_the_seal(self):
        base = [("a.ts", "export const a = 1\n")]
        changed = [("a.ts", "export const a = 2\n")]
        self.assertNotEqual(
            pob.compute_proof("d", "s", base, "spec", BUILD)["merkle_root"],
            pob.compute_proof("d", "s", changed, "spec", BUILD)["merkle_root"],
        )

    def test_spec_and_verdict_are_part_of_the_seal(self):
        files = [("a.ts", "1")]
        root = pob.compute_proof("d", "s", files, "spec-A", BUILD)["merkle_root"]
        self.assertNotEqual(
            root, pob.compute_proof("d", "s", files, "spec-B", BUILD)["merkle_root"])
        tampered_verdict = {**BUILD, "verified": False}
        self.assertNotEqual(
            root,
            pob.compute_proof("d", "s", files, "spec-A", tampered_verdict)["merkle_root"])

    def test_created_at_is_metadata_not_in_the_root(self):
        files = [("a.ts", "1")]
        r1 = pob.compute_proof("d", "s", files, "spec", BUILD, created_at="2026-01-01")
        r2 = pob.compute_proof("d", "s", files, "spec", BUILD, created_at="2030-12-31")
        self.assertEqual(r1["merkle_root"], r2["merkle_root"])

    def test_render_facts_are_sealed_and_tamper_evident(self):
        # MM11: the render platforms (web/iOS) fold into the SEALED verdict, so
        # "renders on iOS" is cryptographically attested + tamper-evident.
        files = [("a.ts", "x")]
        with_render = {**BUILD, "render": {"platforms": ["web", "ios"],
                                           "proven": True, "js_bytes": 1234}}
        proof = pob.compute_proof("d", "expo-rn", files, "spec", with_render)
        self.assertEqual(proof["verdict"]["render"]["platforms"], ["web", "ios"])
        # changing a sealed render platform breaks the Merkle root
        tampered = {**BUILD, "render": {"platforms": ["web"],
                                        "proven": True, "js_bytes": 1234}}
        self.assertNotEqual(
            proof["merkle_root"],
            pob.compute_proof("d", "expo-rn", files, "spec", tampered)["merkle_root"])
        # backward compatible: a build without render facts has no render field
        plain = pob.compute_proof("d", "react-vite-sqlite", files, "spec", BUILD)
        self.assertNotIn("render", plain["verdict"])


class SealAndVerify(unittest.TestCase):
    def setUp(self):
        self.app = tempfile.mkdtemp()
        with open(os.path.join(self.app, "main.ts"), "w") as f:
            f.write("export const main = () => 42\n")
        os.makedirs(os.path.join(self.app, "server"))
        with open(os.path.join(self.app, "server", "api.mjs"), "w") as f:
            f.write("export default async function(){}\n")

    def test_seal_app_writes_proof_artifacts(self):
        pob.seal_app(self.app, "demo", "react-vite-sqlite", "the spec", BUILD)
        self.assertTrue(os.path.isfile(os.path.join(self.app, ".adf-proof.json")))
        self.assertTrue(os.path.isfile(os.path.join(self.app, "PROOF.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.app, ".adf-proof", "spec.md")))

    def test_freshly_sealed_app_verifies(self):
        pob.seal_app(self.app, "demo", "react-vite-sqlite", "the spec", BUILD)
        ok, report = pob.verify_proof(self.app)
        self.assertTrue(ok, report)
        self.assertEqual(report["status"], "VERIFIED")
        self.assertTrue(all(f["status"] == "ok" for f in report["files"]))

    def test_modifying_a_sealed_file_is_detected(self):
        pob.seal_app(self.app, "demo", "react-vite-sqlite", "the spec", BUILD)
        with open(os.path.join(self.app, "main.ts"), "a") as f:
            f.write("// sneaky\n")
        ok, report = pob.verify_proof(self.app)
        self.assertFalse(ok)
        self.assertEqual(report["status"], "TAMPERED")
        bad = [f for f in report["files"] if f["status"] != "ok"]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["path"], "main.ts")
        self.assertEqual(bad[0]["status"], "modified")

    def test_deleting_a_sealed_file_is_detected(self):
        pob.seal_app(self.app, "demo", "react-vite-sqlite", "the spec", BUILD)
        os.remove(os.path.join(self.app, "server", "api.mjs"))
        ok, report = pob.verify_proof(self.app)
        self.assertFalse(ok)
        missing = [f for f in report["files"] if f["status"] == "missing"]
        self.assertEqual([f["path"] for f in missing], [os.path.join("server", "api.mjs")])

    def test_tampering_the_sealed_spec_is_detected(self):
        pob.seal_app(self.app, "demo", "react-vite-sqlite", "the spec", BUILD)
        with open(os.path.join(self.app, ".adf-proof", "spec.md"), "w") as f:
            f.write("a different spec entirely\n")
        ok, report = pob.verify_proof(self.app)
        self.assertFalse(ok)
        self.assertFalse(report["spec_ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
