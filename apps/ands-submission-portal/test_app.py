#!/usr/bin/env python3
"""
Test suite for the ANDS Submission Portal MVP.

Covers the core domain logic (Dossier-ID format, sequence format + lifecycle,
required fields / email / submission type) and the JSON API end-to-end against a
live server bound to a fresh in-memory store.

Run:  python3 -m unittest -v
"""

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import domain
import server


# ---------------------------------------------------------------------------
# Domain logic
# ---------------------------------------------------------------------------

class DossierIdFormatTests(unittest.TestCase):
    def test_valid_six_and_seven_digits(self):
        self.assertTrue(domain.is_valid_dossier_id("e123456"))
        self.assertTrue(domain.is_valid_dossier_id("e1234567"))

    def test_invalid_dossier_ids(self):
        for bad in ("123456", "e12345", "e12345678", "eabcdef", "E123456", "", "  "):
            with self.subTest(bad=bad):
                self.assertFalse(domain.is_valid_dossier_id(bad))

    def test_intake_flags_bad_dossier_format(self):
        errs = domain.validate_intake(_base(dossier_id="e12345"))
        self._assert_rule(errs, "dossier_id_format")

    def _assert_rule(self, errors, rule):
        self.assertIn(rule, {e["rule"] for e in errors})


class SequenceFormatTests(unittest.TestCase):
    def test_valid_sequences(self):
        for ok in ("0000", "0001", "9999", "4321"):
            self.assertTrue(domain.is_valid_sequence(ok))

    def test_invalid_sequences(self):
        for bad in ("0", "00", "000", "00000", "abcd", "12a4", "", "12 4"):
            with self.subTest(bad=bad):
                self.assertFalse(domain.is_valid_sequence(bad))

    def test_intake_flags_non_four_digit_sequence(self):
        errs = domain.validate_intake(_base(sequence="12"))
        self.assertIn("sequence_format", {e["rule"] for e in errs})


class SequenceLifecycleTests(unittest.TestCase):
    def test_next_expected_first_is_0000(self):
        self.assertEqual(domain.next_expected_sequence([]), "0000")

    def test_next_expected_increments(self):
        self.assertEqual(domain.next_expected_sequence(["0000"]), "0001")
        self.assertEqual(domain.next_expected_sequence(["0000", "0001"]), "0002")

    def test_first_must_be_0000(self):
        errs = domain.validate_intake(_base(sequence="0001"), prior_sequences=[])
        self.assertIn("sequence_lifecycle", {e["rule"] for e in errs})

    def test_first_0000_accepted(self):
        errs = domain.validate_intake(_base(sequence="0000"), prior_sequences=[])
        self.assertEqual(errs, [])

    def test_0001_after_0000_accepted(self):
        errs = domain.validate_intake(_base(sequence="0001"),
                                      prior_sequences=["0000"])
        self.assertEqual(errs, [])

    def test_reject_gap(self):
        # 0001 already exists (0000,0001 accepted); next must be 0002 not 0003.
        errs = domain.validate_intake(_base(sequence="0003"),
                                      prior_sequences=["0000", "0001"])
        rule = next(e for e in errs if e["rule"] == "sequence_lifecycle")
        self.assertIn("0002", rule["message"])

    def test_reject_duplicate(self):
        errs = domain.validate_intake(_base(sequence="0000"),
                                      prior_sequences=["0000"])
        rule = next(e for e in errs if e["rule"] == "sequence_lifecycle")
        self.assertIn("0001", rule["message"])  # names expected next

    def test_lifecycle_skipped_when_format_bad(self):
        # A non-4-digit sequence should not also raise a lifecycle error.
        errs = domain.validate_intake(_base(sequence="12"), prior_sequences=[])
        rules = {e["rule"] for e in errs}
        self.assertIn("sequence_format", rules)
        self.assertNotIn("sequence_lifecycle", rules)


class RequiredFieldAndTypeTests(unittest.TestCase):
    def test_all_required_fields_flagged_when_empty(self):
        errs = domain.validate_intake({"submission_type": "ANDS"})
        rules = {e["rule"] for e in errs}
        for field_name in domain.INTAKE_FIELDS:
            self.assertIn(f"{field_name}_required", rules)

    def test_email_must_look_like_email(self):
        errs = domain.validate_intake(_base(contact_email="not-an-email"))
        self.assertIn("contact_email_format", {e["rule"] for e in errs})

    def test_valid_email_accepted(self):
        self.assertTrue(domain.is_valid_email("ra@acme.example"))
        self.assertFalse(domain.is_valid_email("ra@acme"))

    def test_submission_type_must_be_ands(self):
        errs = domain.validate_intake(_base(submission_type="NDS"))
        self.assertIn("submission_type", {e["rule"] for e in errs})

    def test_fully_valid_submission_has_no_errors(self):
        self.assertEqual(domain.validate_intake(_base()), [])

    def test_lists_every_failing_rule(self):
        # Non-empty-but-invalid dossier/sequence trigger format (not required)
        # rules; the two empty fields trigger required rules.
        bad = {"applicant": "", "drug_product": "", "dossier_id": "bad",
               "sequence": "9", "contact_email": "nope", "submission_type": "X"}
        rules = {e["rule"] for e in domain.validate_intake(bad)}
        self.assertTrue({"applicant_required", "drug_product_required",
                         "dossier_id_format", "sequence_format",
                         "contact_email_format", "submission_type"} <= rules)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = server.SubmissionStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_add_and_get_roundtrip(self):
        rec = self.store.add(_base())
        self.assertEqual(rec["dossier_id"], "e123456")
        self.assertEqual(rec["submission_type"], "ANDS")
        self.assertIsNotNone(rec["created_at"])
        self.assertEqual(self.store.get(rec["id"])["id"], rec["id"])

    def test_prior_sequences_scoped_per_dossier(self):
        self.store.add(_base(sequence="0000"))
        self.store.add(_base(sequence="0001"))
        self.store.add(_base(dossier_id="e999999", sequence="0000"))
        self.assertEqual(self.store.prior_sequences("e123456"), ["0000", "0001"])
        self.assertEqual(self.store.prior_sequences("e999999"), ["0000"])

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.store.get(999))


# ---------------------------------------------------------------------------
# API (end-to-end against a live server)
# ---------------------------------------------------------------------------

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                         server.make_handler(self.store))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.store.close()

    # -- helpers --------------------------------------------------------
    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def _post(self, path, body):
        req = urllib.request.Request(
            self._url(path), data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    def _get(self, path):
        try:
            with urllib.request.urlopen(self._url(path)) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())

    # -- tests ----------------------------------------------------------
    def test_index_served(self):
        with urllib.request.urlopen(self._url("/")) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("ANDS Submission Portal", resp.read().decode())

    def test_validate_dry_run_does_not_store(self):
        status, data = self._post("/api/validate", _base())
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        # nothing stored
        _, listing = self._get("/api/submissions")
        self.assertEqual(listing["submissions"], [])

    def test_validate_reports_errors(self):
        status, data = self._post("/api/validate", _base(dossier_id="bad"))
        self.assertEqual(status, 200)
        self.assertFalse(data["valid"])
        self.assertIn("dossier_id_format", {e["rule"] for e in data["errors"]})

    def test_valid_post_stores_and_returns_201(self):
        status, data = self._post("/api/submissions", _base())
        self.assertEqual(status, 201)
        self.assertTrue(data["valid"])
        self.assertEqual(data["record"]["dossier_id"], "e123456")
        _, listing = self._get("/api/submissions")
        self.assertEqual(len(listing["submissions"]), 1)

    def test_invalid_post_returns_422_and_does_not_store(self):
        status, data = self._post("/api/submissions", _base(contact_email="x"))
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])
        self.assertIn("contact_email_format", {e["rule"] for e in data["errors"]})
        _, listing = self._get("/api/submissions")
        self.assertEqual(listing["submissions"], [])

    def test_lifecycle_enforced_through_api(self):
        self.assertEqual(self._post("/api/submissions", _base(sequence="0000"))[0], 201)
        self.assertEqual(self._post("/api/submissions", _base(sequence="0001"))[0], 201)
        # gap: next must be 0002
        status, data = self._post("/api/submissions", _base(sequence="0003"))
        self.assertEqual(status, 422)
        self.assertIn("sequence_lifecycle", {e["rule"] for e in data["errors"]})
        # duplicate
        status, _ = self._post("/api/submissions", _base(sequence="0000"))
        self.assertEqual(status, 422)

    def test_get_by_id_and_404(self):
        _, created = self._post("/api/submissions", _base())
        sid = created["record"]["id"]
        status, rec = self._get(f"/api/submissions/{sid}")
        self.assertEqual(status, 200)
        self.assertEqual(rec["id"], sid)
        status, _ = self._get("/api/submissions/9999")
        self.assertEqual(status, 404)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base(**overrides):
    """A fully valid submission payload; override individual fields per test."""
    data = {
        "applicant": "Acme Generics Inc.",
        "drug_product": "Metformin HCl 500 mg tablets",
        "dossier_id": "e123456",
        "submission_type": "ANDS",
        "sequence": "0000",
        "contact_email": "ra@acme.example",
    }
    data.update(overrides)
    return data


if __name__ == "__main__":
    unittest.main()
