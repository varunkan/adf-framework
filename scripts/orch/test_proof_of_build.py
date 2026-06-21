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

    def test_backend_is_metadata_not_in_the_root(self):
        # G14: `backend` is provenance metadata, NEVER folded into the root — so the
        # same app re-verifies VERIFIED after switching backends (no false TAMPERED).
        files = [("a.ts", "1")]
        r1 = pob.compute_proof("d", "s", files, "spec", {**BUILD, "backend": "stub"})
        r2 = pob.compute_proof("d", "s", files, "spec",
                               {**BUILD, "backend": "claude-opus-4-8"})
        self.assertEqual(r1["merkle_root"], r2["merkle_root"])

    def test_model_is_metadata_not_in_the_root(self):
        # G14: `model` is provenance metadata, NEVER folded into the root — same app,
        # different model, identical root (the seal is a pure function of substance).
        files = [("a.ts", "1")]
        r1 = pob.compute_proof("d", "s", files, "spec", {**BUILD, "model": "test"})
        r2 = pob.compute_proof("d", "s", files, "spec",
                               {**BUILD, "model": "claude-opus-4-8-20251101"})
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

    def test_process_facts_are_sealed_and_tamper_evident(self):
        # The engineering discipline (verify gates / TDD / root-cause) folds into the
        # SEALED verdict, so "built WITH discipline X" is attested + tamper-evident.
        files = [("a.ts", "x")]
        proc = {"schema": "adf-process/1", "enforced": ["verification_evidence"],
                "blocked": [], "facts": {"verification_evidence": {
                    "status": "proven", "gates": ["build", "test", "boot", "render"]}}}
        proof = pob.compute_proof("d", "react-vite-sqlite", files, "spec",
                                  {**BUILD, "process": proc})
        self.assertEqual(proof["verdict"]["process"]["facts"]
                         ["verification_evidence"]["status"], "proven")
        # changing a sealed process fact breaks the Merkle root
        tampered = {**proc, "facts": {"verification_evidence": {
            "status": "proven", "gates": ["build"]}}}
        self.assertNotEqual(
            proof["merkle_root"],
            pob.compute_proof("d", "react-vite-sqlite", files, "spec",
                              {**BUILD, "process": tampered})["merkle_root"])
        # backward compatible: a build without process facts has no process field, so
        # every historical seal re-seals to the byte-identical root
        plain = pob.compute_proof("d", "react-vite-sqlite", files, "spec", BUILD)
        self.assertNotIn("process", plain["verdict"])

    def test_mobile_facts_are_sealed_and_tamper_evident(self):
        # G04: Mobile APK facts must fold into the sealed Merkle root so a
        # swapped/tampered APK binary is detectable by recomputing offline.
        files = [("a.ts", "x")]
        mobile = {
            "apk": "outputs/app-release.apk",
            "package": "com.adf.demo",
            "size_bytes": 10_485_760,
            "sha256": "deadbeef" * 8,
            "screenshot": ".adf-mobile/screenshot.png",
            "preview": "booted on emulator-5554",
        }
        with_mobile = {**BUILD, "mobile": mobile}
        proof = pob.compute_proof("d", "expo-rn", files, "spec", with_mobile)

        # (a) sealed mobile sub-dict is present and carries the input sha256
        self.assertIn("mobile", proof["verdict"])
        self.assertEqual(proof["verdict"]["mobile"]["sha256"], "deadbeef" * 8)
        self.assertEqual(proof["verdict"]["mobile"]["package"], "com.adf.demo")
        self.assertEqual(proof["verdict"]["mobile"]["size_bytes"], 10_485_760)

        # (b) mutating only the APK sha256 changes the Merkle root (tamper-evidence)
        tampered_mobile = {**mobile, "sha256": "CHANGED__" * 8}
        tampered_proof = pob.compute_proof("d", "expo-rn", files, "spec",
                                           {**BUILD, "mobile": tampered_mobile})
        self.assertNotEqual(proof["merkle_root"], tampered_proof["merkle_root"])

        # (c) back-compat: a web build with no mobile key has no 'mobile' in verdict
        plain = pob.compute_proof("d", "react-vite-sqlite", files, "spec", BUILD)
        self.assertNotIn("mobile", plain["verdict"])


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

    def test_mobile_facts_survive_verify_round_trip(self):
        # G04: a proof sealed with mobile facts must verify VERIFIED on unchanged
        # disk — verify_proof re-serializes verdict['mobile'] identically.
        mobile = {"apk": "out/app.apk", "package": "com.test", "size_bytes": 1024,
                  "sha256": "abc" * 21 + "ab", "screenshot": None, "preview": None}
        pob.seal_app(self.app, "demo", "expo-rn", "the spec",
                     {**BUILD, "mobile": mobile})
        ok, report = pob.verify_proof(self.app)
        self.assertTrue(ok, report)
        self.assertEqual(report["status"], "VERIFIED")


@unittest.skipUnless(pob.signing_available(),
                     "cryptography lib required for Ed25519 provenance")
class Provenance(unittest.TestCase):
    """OPTIONAL Ed25519 provenance signing — ADDITIVE to (never replacing) the
    keyless integrity seal. The steelman: keyless proves INTEGRITY (no key needed);
    a signature adds AUTHENTICITY for the buyer who needs it. Both must compose
    correctly and the keyless default must be untouched."""

    def setUp(self):
        self.app = tempfile.mkdtemp()
        with open(os.path.join(self.app, "main.ts"), "w") as f:
            f.write("export const main = () => 7\n")
        self.seed, self.pub = pob.generate_keypair()

    def _seal(self, seed=None):
        return pob.seal_app(self.app, "demo", "react-vite-sqlite", "spec", BUILD,
                            signing_seed=seed)

    def test_unsigned_proof_still_verifies_keyless(self):
        # the default path is unchanged: no key => no signature => still VERIFIED.
        self._seal(seed=None)
        ok, r = pob.verify_proof(self.app)
        self.assertTrue(ok)
        self.assertEqual(r["signature"], "unsigned")
        self.assertIsNone(r["signer"])

    def test_signed_proof_round_trips_and_reports_signer(self):
        proof = self._seal(seed=self.seed)
        self.assertEqual(proof["signature"]["alg"], "ed25519")
        ok, r = pob.verify_proof(self.app, trusted_pubkeys=[self.pub])
        self.assertTrue(ok)                         # integrity
        self.assertEqual(r["signature"], "valid")   # provenance
        self.assertEqual(r["signer"], self.pub)
        self.assertTrue(r["signer_trusted"])

    def test_signature_is_deterministic_reseal_is_stable(self):
        a = self._seal(seed=self.seed)
        b = self._seal(seed=self.seed)
        # same app + same key => identical root AND identical signature.
        self.assertEqual(a["merkle_root"], b["merkle_root"])
        self.assertEqual(a["signature"]["sig"], b["signature"]["sig"])

    def test_signature_is_not_folded_into_the_root(self):
        # signing must not change the keyless root (it signs it).
        unsigned = pob.compute_proof("demo", "s", [("a.ts", "x")], "spec", BUILD)
        signed = pob.compute_proof("demo", "s", [("a.ts", "x")], "spec", BUILD,
                                   signing_seed=self.seed)
        self.assertEqual(unsigned["merkle_root"], signed["merkle_root"])

    def test_tampered_file_is_TAMPERED_even_when_signed(self):
        self._seal(seed=self.seed)
        with open(os.path.join(self.app, "main.ts"), "a") as f:
            f.write("// evil\n")
        ok, r = pob.verify_proof(self.app, trusted_pubkeys=[self.pub])
        self.assertFalse(ok)                          # integrity fails
        self.assertEqual(r["status"], "TAMPERED")
        # the signature is over the OLD root, so it can't rescue a content change:
        # the recomputed root no longer equals the signed root.
        self.assertFalse(r["root_ok"])

    def test_forged_signature_is_rejected(self):
        proof = self._seal(seed=self.seed)
        # flip the signature in the on-disk proof.
        import json
        pj = os.path.join(self.app, ".adf-proof.json")
        with open(pj) as f:
            d = json.load(f)
        d["signature"]["sig"] = ("00" * 64)
        with open(pj, "w") as f:
            json.dump(d, f)
        _ok, r = pob.verify_proof(self.app, trusted_pubkeys=[self.pub])
        self.assertEqual(r["signature"], "invalid")

    def test_signer_with_different_key_is_untrusted(self):
        self._seal(seed=self.seed)
        other_seed, other_pub = pob.generate_keypair()
        ok, r = pob.verify_proof(self.app, trusted_pubkeys=[other_pub])
        self.assertTrue(ok)                       # integrity still fine
        self.assertEqual(r["signature"], "valid")  # signature is mathematically valid
        self.assertFalse(r["signer_trusted"])     # ...but NOT your trusted key
        self.assertNotEqual(other_pub, self.pub)

    def test_resolve_signing_seed_from_env(self):
        self.assertIsNone(pob.resolve_signing_seed({}))
        self.assertEqual(pob.resolve_signing_seed({"ADF_SIGNING_KEY": self.seed}),
                         bytes.fromhex(self.seed))
        self.assertIsNone(pob.resolve_signing_seed({"ADF_SIGNING_KEY": "nothex"}))

    # --- adversarial-review fixes (provenance must not be able to LIE) ---
    def test_forged_signature_is_never_trusted(self):
        # must-fix: trust requires a VALID signature, not mere membership of the
        # (public) trusted key. Inject the trusted pubkey with a garbage sig.
        self._seal(seed=self.seed)
        import json
        pj = os.path.join(self.app, ".adf-proof.json")
        with open(pj) as f:
            d = json.load(f)
        d["signature"]["sig"] = "00" * 64
        with open(pj, "w") as f:
            json.dump(d, f)
        _ok, r = pob.verify_proof(self.app, trusted_pubkeys=[self.pub])
        self.assertEqual(r["signature"], "invalid")
        self.assertIsNot(r["signer_trusted"], True)   # NOT trusted on a bad sig

    def test_attacker_supplied_domain_is_rejected(self):
        # must-fix: the verifier pins SIG_DOMAIN; a signature carrying a foreign
        # domain must not verify (defeats cross-protocol replay).
        proof = self._seal(seed=self.seed)
        sig = dict(proof["signature"])
        sig["domain"] = "some-other-protocol-v9:"
        self.assertEqual(
            pob.verify_signature(sig, proof["merkle_root"]), "invalid")

    def test_signature_invalidated_by_tamper_via_recomputed_root(self):
        # must-fix: the signature is checked against the RECOMPUTED root, so a
        # tampered file flips provenance to invalid too (not just integrity).
        self._seal(seed=self.seed)
        with open(os.path.join(self.app, "main.ts"), "a") as f:
            f.write("// evil\n")
        _ok, r = pob.verify_proof(self.app, trusted_pubkeys=[self.pub])
        self.assertEqual(r["signature"], "invalid")
        self.assertIsNot(r["signer_trusted"], True)

    def test_binary_key_file_degrades_to_keyless(self):
        # must-fix: a non-UTF-8/corrupt ADF_SIGNING_KEY file must degrade to keyless,
        # not crash the seal.
        kf = os.path.join(self.app, "badkey.bin")
        with open(kf, "wb") as f:
            f.write(b"\xff\xfe\x00\x01")
        self.assertIsNone(pob.resolve_signing_seed({"ADF_SIGNING_KEY": kf}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
