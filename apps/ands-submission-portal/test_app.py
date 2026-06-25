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
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer

import backbone
import bioequivalence
import content_model
import domain
import dr
import ectd
import esign
import fees
import hc_calendar
import lifecycle
import privacy
import qos
import rbac
import rep
import report_ingest
import retention
import server
import stf
import transmission


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

    def test_client_renderers_escape_user_data(self):
        # Regression: the submissions list and validation-error renderers must
        # HTML-escape user-controlled values before assigning innerHTML, or a
        # stored value like drug_product becomes a stored-XSS vector.
        with urllib.request.urlopen(self._url("/")) as resp:
            page = resp.read().decode()
        # The submissions table cells must be wrapped in esc(...).
        self.assertIn("esc(s.drug_product)", page)
        self.assertIn("esc(s.dossier_id)", page)
        # The previously-vulnerable raw concatenations must be gone.
        self.assertNotIn("'</td><td>' + s.drug_product +", page)
        self.assertNotIn("'<li>' + e.message + '</li>'", page)

    def test_malformed_content_length_does_not_crash(self):
        # Regression: a non-numeric Content-Length must be handled gracefully
        # (treated as an empty body) rather than raising inside the handler.
        req = urllib.request.Request(
            self._url("/api/validate"), data=b"{}", method="POST",
            headers={"Content-Type": "application/json",
                     "Content-Length": "not-a-number"})
        try:
            with urllib.request.urlopen(req) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        # Empty body -> intake validation runs and reports missing fields (200),
        # the key point is the server answered instead of dropping the request.
        self.assertEqual(status, 200)

    def test_oversized_content_length_is_refused_not_allocated(self):
        # Security: an attacker-supplied Content-Length far above the body cap
        # must NOT cause the server to allocate/read a giant body (memory-
        # exhaustion DoS). The guard treats it as an empty body, so the handler
        # answers with its normal missing-field validation (200) and we never
        # ship the claimed bytes. A tiny actual body proves the read is skipped.
        self.assertGreater(server.MAX_REQUEST_BODY_BYTES, 0)
        oversized = server.MAX_REQUEST_BODY_BYTES + 1
        req = urllib.request.Request(
            self._url("/api/validate"), data=b"{}", method="POST",
            headers={"Content-Type": "application/json",
                     "Content-Length": str(oversized)})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            status, data = e.code, json.loads(e.read().decode())
        self.assertEqual(status, 200)
        # Body ignored -> intake reports the (now-missing) required fields.
        self.assertFalse(data["valid"])
        self.assertIn("applicant_required", {e["rule"] for e in data["errors"]})

    def test_assemble_form_validates_client_side_before_request(self):
        # Regression: the crawler overwrites the repform's valid defaults with
        # junk and submits, which made assemble() fire a request the server
        # correctly rejected with 422 — surfacing as a browser console error.
        # assemble() must now pre-validate (mirroring rep.validate_assembly) and
        # render the failure inline WITHOUT firing the doomed request, exactly
        # like addLeaf()'s guard. The server keeps 422 as the source of truth.
        with urllib.request.urlopen(self._url("/")) as resp:
            page = resp.read().decode()
        self.assertIn("function repValidate(", page)
        # assemble() must short-circuit on local errors before fetching.
        idx_validate = page.index("repValidate(payload)")
        idx_fetch = page.index("/api/transactions/assemble")
        self.assertLess(idx_validate, idx_fetch,
                        "repValidate must run before the assemble fetch")
        # The client guard mirrors the server identifier formats.
        self.assertIn("/^e[0-9]{6,7}$/", page)
        self.assertIn("/^[0-9]{4}$/", page)
        self.assertIn("/^[A-Za-z0-9]{2,12}$/", page)
        # Server remains the source of truth: still 422 on malformed input.
        status, data = self._post(
            "/api/transactions/assemble", _rep(dossier_id="bad"))
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])
        self.assertIn("dossier_id_format", {e["rule"] for e in data["errors"]})

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
# REP domain logic — identifier formats (REQ-042)
# ---------------------------------------------------------------------------

class IdentifierFormatTests(unittest.TestCase):
    def test_company_id_is_opaque_token_not_5_digits(self):
        # Alphanumeric HC tokens accepted; bare digits accepted; NOT a 5-digit rule.
        for ok in ("K18276", "12345", "abc123", "ABCDEF", "X1"):
            with self.subTest(ok=ok):
                self.assertTrue(rep.is_valid_company_id(ok))
        # A 5-digit-numeric validator would wrongly reject K18276 — guard that.
        self.assertTrue(rep.is_valid_company_id("K18276"))

    def test_company_id_rejects_blank_and_punctuation(self):
        for bad in ("", "  ", "K-18276", "K 18276", "co/123", "a"):
            with self.subTest(bad=bad):
                self.assertFalse(rep.is_valid_company_id(bad))

    def test_dossier_id_prefix_by_type(self):
        self.assertTrue(rep.is_valid_dossier_id("e123456"))
        self.assertTrue(rep.is_valid_dossier_id("e1234567"))
        self.assertTrue(rep.is_valid_dossier_id("m123456", "m"))
        # default 'e' prefix rejects an 'm' value
        self.assertFalse(rep.is_valid_dossier_id("m123456"))
        for bad in ("e12345", "e12345678", "E123456", "eabcdef", "", "123456"):
            with self.subTest(bad=bad):
                self.assertFalse(rep.is_valid_dossier_id(bad))

    def test_dossier_id_rejects_bad_prefix_arg(self):
        self.assertFalse(rep.is_valid_dossier_id("e123456", "ee"))
        self.assertFalse(rep.is_valid_dossier_id("1123456", "1"))

    def test_sequence_four_digits(self):
        for ok in ("0000", "9999", "0042"):
            self.assertTrue(rep.is_valid_sequence(ok))
        for bad in ("0", "00000", "12a4", ""):
            self.assertFalse(rep.is_valid_sequence(bad))

    def test_din_eight_digits(self):
        self.assertTrue(rep.is_valid_din("02123456"))
        for bad in ("1234567", "123456789", "abcd1234", ""):
            self.assertFalse(rep.is_valid_din(bad))

    def test_validate_identifiers_collects_each_failure(self):
        errs = rep.validate_identifiers(
            {"company_id": "bad id", "dossier_id": "m123456",
             "sequence": "12", "din": "123"})
        rules = {e["rule"] for e in errs}
        self.assertEqual(rules, {"company_id_format", "dossier_id_format",
                                 "sequence_format", "din_format"})

    def test_validate_identifiers_skips_absent_fields(self):
        # DIN is optional; only present, non-empty fields are checked.
        self.assertEqual(rep.validate_identifiers({"company_id": "K18276"}), [])

    def test_validate_identifiers_honours_prefix_override(self):
        self.assertEqual(
            rep.validate_identifiers({"dossier_id": "m123456",
                                      "dossier_prefix": "m"}), [])


# ---------------------------------------------------------------------------
# REP domain logic — controlled vocabulary (REQ-005)
# ---------------------------------------------------------------------------

class ActivityVocabularyTests(unittest.TestCase):
    def test_ands_is_in_vocabulary(self):
        self.assertIn("ANDS", rep.ACTIVITY_TYPES)
        self.assertTrue(rep.is_valid_activity_type("ANDS"))

    def test_out_of_vocabulary_rejected(self):
        for bad in ("XYZ", "ands", "", "  ", "NOTACODE"):
            with self.subTest(bad=bad):
                self.assertFalse(rep.is_valid_activity_type(bad))

    def test_label_lookup(self):
        self.assertIn("Abbreviated", rep.activity_type_label("ANDS"))
        self.assertEqual(rep.activity_type_label("nope"), "")

    def test_rt_xml_carries_resolved_activity_type(self):
        xml = rep.build_rt_xml({"activity_type": "ANDS", "dossier_id": "e123456"})
        self.assertIn('code="ANDS"', xml)
        self.assertIn("Abbreviated New Drug Submission", xml)


# ---------------------------------------------------------------------------
# REP domain logic — immutable machine-generated filenames (REQ-001/006)
# ---------------------------------------------------------------------------

class RepFilenameTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2025, 9, 10, 14, 30, tzinfo=timezone.utc)

    def test_co_filename_pattern(self):
        self.assertEqual(rep.co_filename("K18276", self.now),
                         "final-com-K18276-2025-09-10-1430.xml")

    def test_rt_and_pi_filename_patterns(self):
        self.assertEqual(rep.rt_filename("e123456", self.now),
                         "final-rt-e123456-2025-09-10-1430.xml")
        self.assertEqual(rep.pi_filename("e123456", self.now),
                         "final-pi-e123456-2025-09-10-1430.xml")

    def test_rename_to_same_name_allowed(self):
        # A no-op "rename" (same name) must not raise.
        rep.assert_rep_filename_immutable("final-com-K18276-2025-09-10-1430.xml",
                                          "final-com-K18276-2025-09-10-1430.xml")

    def test_rename_blocked(self):
        with self.assertRaises(rep.ImmutableFilenameError):
            rep.assert_rep_filename_immutable("final-com-K18276-x.xml", "mine.xml")
        with self.assertRaises(rep.ImmutableFilenameError):
            rep.assert_rep_filename_immutable("final-com-K18276-x.xml",
                                              "final-com-K18276-x.txt")


# ---------------------------------------------------------------------------
# REP domain logic — XML generation (REQ-001/006) + versions
# ---------------------------------------------------------------------------

class RepXmlTests(unittest.TestCase):
    def test_co_xml_captures_company_and_contacts(self):
        xml = rep.build_co_xml({
            "company_id": "K18276", "applicant": "Acme Generics Inc.",
            "contacts": [{"name": "Pat", "email": "pat@acme.example",
                          "hc_contact_id": "C-99"}]})
        self.assertIn("<company-id>K18276</company-id>", xml)
        self.assertIn("Acme Generics Inc.", xml)
        self.assertIn("<hc-contact-id>C-99</hc-contact-id>", xml)
        self.assertIn(f'template-version="{rep.CO_TEMPLATE_VERSION}"', xml)

    def test_co_xml_escapes_special_chars(self):
        xml = rep.build_co_xml({"applicant": "A & B <Inc>", "company_id": "X1"})
        self.assertIn("A &amp; B &lt;Inc&gt;", xml)

    def test_rt_xml_pinned_version_and_date(self):
        xml = rep.build_rt_xml({"activity_type": "ANDS"})
        self.assertIn('template-version="5.1.0"', xml)
        self.assertIn('template-date="2025-09-10"', xml)
        self.assertEqual(rep.RT_TEMPLATE_VERSION, "5.1.0")

    def test_pi_xml_pinned_version(self):
        xml = rep.build_pi_xml({"dossier_id": "e123456", "din": "02123456"})
        self.assertIn('template-version="2024-02-12"', xml)
        self.assertIn("<din>02123456</din>", xml)

    def test_ca_regional_path_and_metadata(self):
        # REQ-006: drug ANDS REP metadata belongs under m1/ca/, NOT a device folder.
        self.assertEqual(rep.CA_REGIONAL_PATH, "m1/ca/ca-regional.xml")
        xml = rep.build_ca_regional_xml(
            {"dossier_id": "e123456", "company_id": "K18276",
             "activity_type": "ANDS", "sequence": "0000"})
        self.assertIn("<dossier-id>e123456</dossier-id>", xml)
        self.assertIn('code="ANDS"', xml)


# ---------------------------------------------------------------------------
# REP domain logic — single-entry assembly (REQ-043 ties 001/005/006/042)
# ---------------------------------------------------------------------------

class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2025, 9, 10, 14, 30, tzinfo=timezone.utc)

    def test_valid_assembly_emits_all_artifacts(self):
        res = rep.assemble_transaction(_rep(pi_required=True), self.now)
        self.assertTrue(res["valid"])
        t = res["transaction"]
        self.assertEqual(t["co"]["filename"], "final-com-K18276-2025-09-10-1430.xml")
        self.assertTrue(t["co"]["immutable"])
        self.assertEqual(t["rt"]["template_version"], "5.1.0")
        self.assertIsNotNone(t["pi"])
        self.assertEqual(t["ca_regional"]["path"], "m1/ca/ca-regional.xml")

    def test_pi_omitted_when_not_required(self):
        res = rep.assemble_transaction(_rep(pi_required=False), self.now)
        self.assertIsNone(res["transaction"]["pi"])

    def test_drug_ands_does_not_use_ai_template(self):
        # REQ-006: AI template / 1.04-1.05 placement are device-only.
        t = rep.assemble_transaction(_rep(), self.now)["transaction"]
        self.assertFalse(t["uses_ai_template"])
        self.assertEqual(t["rep_metadata_path"], "m1/ca/ca-regional.xml")

    def test_single_entry_flows_into_backbone_and_cover_letter(self):
        # REQ-043: one set of identifiers populates RT, ca-regional AND the
        # portal's own cover letter, with no re-keying.
        t = rep.assemble_transaction(_rep(), self.now)["transaction"]
        self.assertIn("e123456", t["ca_regional"]["xml"])
        self.assertIn("e123456", t["rt"]["xml"])
        self.assertIn("e123456", t["cover_letter"]["text"])
        self.assertEqual(t["cover_letter"]["source"], "portal-template")
        self.assertEqual(t["cover_letter"]["leaf"], "m1-0-1-cover-letter")

    def test_assembly_rejects_missing_required_fields(self):
        res = rep.assemble_transaction({})
        self.assertFalse(res["valid"])
        self.assertIsNone(res["transaction"])
        rules = {e["rule"] for e in res["errors"]}
        self.assertIn("applicant_required", rules)
        self.assertIn("company_id_required", rules)

    def test_assembly_rejects_out_of_vocabulary_activity_type(self):
        res = rep.assemble_transaction(_rep(activity_type="BOGUS"))
        self.assertFalse(res["valid"])
        self.assertIn("activity_type_cv", {e["rule"] for e in res["errors"]})

    def test_assembly_rejects_bad_identifier_formats(self):
        res = rep.assemble_transaction(_rep(dossier_id="m123456"))
        self.assertFalse(res["valid"])
        self.assertIn("dossier_id_format", {e["rule"] for e in res["errors"]})


# ---------------------------------------------------------------------------
# REP API (end-to-end against a live server)
# ---------------------------------------------------------------------------

class RepApiTests(unittest.TestCase):
    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.companies = server.CompanyStore(":memory:")
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), server.make_handler(self.store, self.companies))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.store.close()
        self.companies.close()

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

    # -- REQ-005: controlled vocabulary endpoint --------------------------
    def test_activity_types_endpoint_includes_ands(self):
        status, data = self._get("/api/activity-types")
        self.assertEqual(status, 200)
        codes = {a["code"] for a in data["activity_types"]}
        self.assertIn("ANDS", codes)

    # -- REQ-042: identifier validation endpoint --------------------------
    def test_identifiers_validate_ok(self):
        status, data = self._post("/api/identifiers/validate",
                                  {"company_id": "K18276", "dossier_id": "e123456",
                                   "sequence": "0000", "din": "02123456"})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertEqual(data["errors"], [])

    def test_identifiers_validate_reports_errors(self):
        status, data = self._post("/api/identifiers/validate",
                                  {"company_id": "bad id", "dossier_id": "m1",
                                   "din": "123"})
        self.assertEqual(status, 200)
        self.assertFalse(data["valid"])
        rules = {e["rule"] for e in data["errors"]}
        self.assertIn("company_id_format", rules)
        self.assertIn("din_format", rules)

    # -- REQ-001: company onboarding + immutable filename -----------------
    def test_company_creation_emits_immutable_co_file(self):
        status, data = self._post("/api/companies",
                                  {"applicant": "Acme Generics Inc.",
                                   "company_id": "K18276"})
        self.assertEqual(status, 201)
        self.assertTrue(data["valid"])
        self.assertTrue(data["co"]["filename"].startswith("final-com-K18276-"))
        self.assertTrue(data["co"]["filename"].endswith(".xml"))
        self.assertTrue(data["co"]["immutable"])
        # recorded against the org and listed
        _, listing = self._get("/api/companies")
        self.assertEqual(len(listing["companies"]), 1)
        self.assertEqual(listing["companies"][0]["company_id"], "K18276")

    def test_company_creation_requires_fields(self):
        status, data = self._post("/api/companies", {"applicant": ""})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])
        rules = {e["rule"] for e in data["errors"]}
        self.assertIn("applicant_required", rules)
        self.assertIn("company_id_required", rules)

    def test_rename_rep_filename_blocked(self):
        status, data = self._post("/api/companies/rename",
                                  {"original": "final-com-K18276-x.xml",
                                   "proposed": "mine.xml"})
        self.assertEqual(status, 409)
        self.assertFalse(data["allowed"])

    def test_rename_noop_allowed(self):
        status, data = self._post("/api/companies/rename",
                                  {"original": "final-com-K18276-x.xml",
                                   "proposed": "final-com-K18276-x.xml"})
        self.assertEqual(status, 200)
        self.assertTrue(data["allowed"])

    # -- REQ-043: single-entry transaction assembly -----------------------
    def test_assemble_endpoint_returns_full_transaction(self):
        status, data = self._post("/api/transactions/assemble",
                                  _rep(pi_required=True))
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        t = data["transaction"]
        self.assertEqual(t["ca_regional"]["path"], "m1/ca/ca-regional.xml")
        self.assertIsNotNone(t["pi"])
        self.assertIn("e123456", t["cover_letter"]["text"])

    def test_assemble_endpoint_422_on_bad_input(self):
        status, data = self._post("/api/transactions/assemble",
                                  _rep(activity_type="BOGUS"))
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])
        self.assertIn("activity_type_cv", {e["rule"] for e in data["errors"]})


# ---------------------------------------------------------------------------
# eCTD — Module 1 placement table (REQ-009)
# ---------------------------------------------------------------------------

class EctdPlacementTests(unittest.TestCase):
    def test_placement_table_is_versioned_data(self):
        table = ectd.module1_placement_table()
        self.assertEqual(table["version"], ectd.PLACEMENT_TABLE_VERSION)
        self.assertTrue(table["entries"])
        headings = {e["heading"] for e in table["entries"]}
        self.assertIn("1.0", headings)   # cover letter slot
        self.assertIn("1.3.1", headings)  # product monograph

    def test_cover_letter_slot_is_sponsor_authored(self):
        slot = ectd.cover_letter_slot()
        self.assertEqual(slot["heading"], "1.0")
        self.assertEqual(slot["leaf_id"], "m1-0-1-cover-letter")
        self.assertTrue(slot["sponsor_authored"])

    def test_docx_required_headings_include_product_monograph(self):
        self.assertIn("1.3.1", ectd.docx_required_headings())

    def test_placement_for_unknown_heading_is_none(self):
        self.assertIsNone(ectd.placement_for_heading("9.9"))

    def test_util_files_carry_dtd_xsd_and_xsl(self):
        util = ectd.util_files()
        self.assertIn(ectd.ICH_ECTD_DTD["util_path"], util)
        self.assertIn(ectd.CA_M1_XSD["util_path"], util)
        self.assertIn(ectd.ICH_ECTD_XSL["util_path"], util)


# ---------------------------------------------------------------------------
# eCTD — checksums (REQ-015)
# ---------------------------------------------------------------------------

class EctdChecksumTests(unittest.TestCase):
    def test_md5_is_deterministic_and_matches_hashlib(self):
        import hashlib
        self.assertEqual(ectd.md5_hex("hello"),
                         hashlib.md5(b"hello").hexdigest())
        self.assertEqual(ectd.md5_hex("hello"), ectd.md5_hex(b"hello"))

    def test_distinct_content_distinct_digest(self):
        self.assertNotEqual(ectd.md5_hex("a"), ectd.md5_hex("b"))


# ---------------------------------------------------------------------------
# eCTD — current view + leaf-operation validation (REQ-017/018)
# ---------------------------------------------------------------------------

class CurrentViewTests(unittest.TestCase):
    def test_lifecycle_semantics_across_sequences(self):
        leaves = [
            {"leaf_id": "a", "operation": "new"},
            {"leaf_id": "b", "operation": "new"},
            {"leaf_id": "a2", "operation": "replace", "modified_leaf": "a"},
            {"leaf_id": "c", "operation": "append", "modified_leaf": "b"},
            {"leaf_id": "bdel", "operation": "delete", "modified_leaf": "b"},
        ]
        view = ectd.compute_current_view(leaves)
        live = {l["leaf_id"] for l in view["live"]}
        self.assertEqual(live, {"a2", "c"})
        hist = {l["leaf_id"] for l in view["history"]}
        self.assertIn("a", hist)      # superseded by replace
        self.assertIn("b", hist)      # removed by delete
        self.assertIn("bdel", hist)   # the delete marker is never live


class LeafOperationValidationTests(unittest.TestCase):
    def test_new_must_not_reference_prior(self):
        errs = ectd.validate_leaf_operation(
            {"leaf_id": "x", "operation": "new", "modified_leaf": "y"}, set())
        self.assertIn("new_has_prior", {e["rule"] for e in errs})

    def test_replace_requires_prior(self):
        errs = ectd.validate_leaf_operation(
            {"leaf_id": "x", "operation": "replace"}, {"y"})
        self.assertIn("prior_leaf_required", {e["rule"] for e in errs})

    def test_replace_dangling_reference_blocked(self):
        errs = ectd.validate_leaf_operation(
            {"leaf_id": "x", "operation": "replace", "modified_leaf": "ghost"},
            {"y"})
        self.assertIn("dangling_reference", {e["rule"] for e in errs})

    def test_valid_replace_passes(self):
        errs = ectd.validate_leaf_operation(
            {"leaf_id": "x", "operation": "replace", "modified_leaf": "y"},
            {"y"})
        self.assertEqual(errs, [])

    def test_invalid_operation_rejected(self):
        errs = ectd.validate_leaf_operation(
            {"leaf_id": "x", "operation": "bogus"}, set())
        self.assertIn("operation_invalid", {e["rule"] for e in errs})


# ---------------------------------------------------------------------------
# eCTD — backbone generation + schema/DTD validation (REQ-014)
# ---------------------------------------------------------------------------

class BackboneTests(unittest.TestCase):
    def _leaf(self):
        return {"leaf_id": "m1-0-1-cover-letter-0000", "operation": "new",
                "heading": "1.0", "title": "Cover Letter",
                "href": "m1/ca/10-cover-letter/cl.pdf",
                "checksum": ectd.md5_hex("bytes")}

    def test_index_and_ca_backbones_are_deterministic(self):
        a = ectd.build_index_xml("e123456", "0000", [self._leaf()])
        b = ectd.build_index_xml("e123456", "0000", [self._leaf()])
        self.assertEqual(a, b)
        self.assertIn(ectd.ICH_ECTD_DTD["root_element"], a)
        ca = ectd.build_ca_regional_xml("e123456", "0000", [self._leaf()])
        self.assertIn(ectd.CA_M1_XSD["root_element"], ca)

    def test_validate_backbone_accepts_well_formed(self):
        xml = ectd.build_index_xml("e123456", "0000", [self._leaf()])
        ectd.validate_backbone(xml, ectd.ICH_ECTD_DTD)  # no raise

    def test_validate_backbone_rejects_wrong_root(self):
        with self.assertRaises(ectd.SchemaValidationError):
            ectd.validate_backbone("<wrong-root/>", ectd.ICH_ECTD_DTD)

    def test_validate_backbone_rejects_leaf_without_checksum(self):
        xml = ('<?xml version="1.0"?><' + ectd.ICH_ECTD_DTD["root_element"] +
               '><leaf ID="x" checksum-type="MD5"/></' +
               ectd.ICH_ECTD_DTD["root_element"] + '>')
        with self.assertRaises(ectd.SchemaValidationError):
            ectd.validate_backbone(xml, ectd.ICH_ECTD_DTD)


# ---------------------------------------------------------------------------
# eCTD — Dossier aggregate end-to-end (REQ-014/015/017/018/019)
# ---------------------------------------------------------------------------

class DossierTests(unittest.TestCase):
    def _dossier_with_cover(self):
        d = ectd.Dossier("e123456")
        d.add_leaf("0000", {"leaf_id": "cl-0000", "operation": "new",
                            "heading": "1.0", "title": "Cover Letter",
                            "content": "cover letter bytes"})
        return d

    def test_add_leaf_computes_checksum_and_href_from_placement(self):
        d = self._dossier_with_cover()
        leaf = d.current_view()["live"][0]
        self.assertEqual(leaf["leaf_id"], "cl-0000")
        # href derived from the placement folder for heading 1.0
        self.assertTrue(leaf["href"].startswith("m1/ca/10-cover-letter"))

    def test_replace_requires_live_prior_leaf(self):
        d = self._dossier_with_cover()
        with self.assertRaises(ectd.LeafOperationError):
            d.add_leaf("0001", {"leaf_id": "ghost-rep", "operation": "replace",
                                "modified_leaf": "does-not-exist",
                                "heading": "1.0", "title": "x",
                                "content": "y"})

    def test_current_view_reflects_replace_across_sequences(self):
        d = self._dossier_with_cover()
        d.add_leaf("0001", {"leaf_id": "cl-0001", "operation": "replace",
                            "modified_leaf": "cl-0000", "heading": "1.0",
                            "title": "Cover Letter v2", "content": "v2 bytes"})
        live = {l["leaf_id"] for l in d.current_view()["live"]}
        self.assertEqual(live, {"cl-0001"})

    def test_file_reuse_preserves_checksum_without_reshipping(self):
        # REQ-019: a later sequence re-points to an unchanged physical file.
        d = self._dossier_with_cover()
        original = d._find_leaf("cl-0000")["checksum"]
        d.add_leaf("0001", {"leaf_id": "cl-0001", "operation": "replace",
                            "modified_leaf": "cl-0000", "heading": "1.0",
                            "title": "Cover Letter (reused)",
                            "reused_from": "cl-0000"})
        reused = d._find_leaf("cl-0001")
        self.assertEqual(reused["checksum"], original)  # same bytes
        self.assertIsNone(reused["content"])            # not re-shipped
        self.assertIsNotNone(reused["reused_from"])

    def test_export_builds_validates_and_verifies(self):
        d = self._dossier_with_cover()
        result = d.export_sequence("0000")
        self.assertTrue(result["valid"])
        self.assertIn("index.xml", result["previews"])
        self.assertIn("m1/ca/ca-regional.xml", result["previews"])
        self.assertIn("index-md5.txt", result["files"])
        self.assertEqual(len(result["index_md5"]), 32)

    def test_checksum_mismatch_hard_blocks(self):
        # REQ-015: tampering with a stored checksum must hard-block on verify.
        d = self._dossier_with_cover()
        d.sequences[0]["leaves"][0]["checksum"] = "deadbeef"
        with self.assertRaises(ectd.ChecksumMismatchError):
            d.verify_checksums("0000")

    def test_roundtrip_serialization(self):
        d = self._dossier_with_cover()
        restored = ectd.Dossier.from_dict(d.to_dict())
        self.assertEqual(restored.sequence_numbers(), ["0000"])
        self.assertEqual({l["leaf_id"] for l in restored.current_view()["live"]},
                         {"cl-0000"})


# ---------------------------------------------------------------------------
# eCTD — DossierStore persistence
# ---------------------------------------------------------------------------

class DossierStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = server.DossierStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_create_get_and_save_roundtrip(self):
        self.store.create("e123456")
        d = self.store.get("e123456")
        d.add_leaf("0000", {"leaf_id": "cl-0000", "operation": "new",
                            "heading": "1.0", "title": "Cover Letter",
                            "content": "bytes"})
        self.store.save(d)
        again = self.store.get("e123456")
        self.assertEqual(len(again.live_leaf_ids()), 1)

    def test_duplicate_create_raises(self):
        self.store.create("e123456")
        with self.assertRaises(ectd.LeafOperationError):
            self.store.create("e123456")

    def test_list_reports_sequences_and_live_leaves(self):
        self.store.create("e123456")
        d = self.store.get("e123456")
        d.add_leaf("0000", {"leaf_id": "cl-0000", "operation": "new",
                            "heading": "1.0", "title": "CL", "content": "b"})
        self.store.save(d)
        listing = self.store.list()
        self.assertEqual(listing[0]["dossier_id"], "e123456")
        self.assertEqual(listing[0]["live_leaves"], 1)


# ---------------------------------------------------------------------------
# eCTD — dossier API (end-to-end against a live server)
# ---------------------------------------------------------------------------

class EctdApiTests(unittest.TestCase):
    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.companies = server.CompanyStore(":memory:")
        self.dossiers = server.DossierStore(":memory:")
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            server.make_handler(self.store, self.companies, self.dossiers))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.store.close()
        self.companies.close()
        self.dossiers.close()

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

    def _cover_leaf(self, **over):
        leaf = {"sequence": "0000", "leaf_id": "cl-0000", "operation": "new",
                "heading": "1.0", "title": "Cover Letter",
                "content": "cover letter bytes"}
        leaf.update(over)
        return leaf

    # -- REQ-009: placement endpoint --------------------------------------
    def test_placement_endpoint_returns_versioned_table(self):
        status, data = self._get("/api/ectd/placement")
        self.assertEqual(status, 200)
        self.assertEqual(data["version"], ectd.PLACEMENT_TABLE_VERSION)
        self.assertIn("1.0", {e["heading"] for e in data["entries"]})

    # -- dossier create / list --------------------------------------------
    def test_create_dossier_and_list(self):
        status, data = self._post("/api/ectd/dossiers", {"dossier_id": "e123456"})
        self.assertEqual(status, 201)
        self.assertTrue(data["valid"])
        status, listing = self._get("/api/ectd/dossiers")
        self.assertEqual(status, 200)
        self.assertIn("e123456",
                      {d["dossier_id"] for d in listing["dossiers"]})

    def test_create_rejects_bad_dossier_id(self):
        status, data = self._post("/api/ectd/dossiers", {"dossier_id": "bad"})
        self.assertEqual(status, 422)
        self.assertIn("dossier_id_format", {e["rule"] for e in data["errors"]})

    def test_duplicate_create_conflicts(self):
        self._post("/api/ectd/dossiers", {"dossier_id": "e123456"})
        status, _ = self._post("/api/ectd/dossiers", {"dossier_id": "e123456"})
        self.assertEqual(status, 409)

    # -- REQ-017: add leaf + dangling reference ---------------------------
    def test_add_leaf_then_current_view(self):
        self._post("/api/ectd/dossiers", {"dossier_id": "e123456"})
        status, data = self._post(
            "/api/ectd/dossiers/e123456/leaves", self._cover_leaf())
        self.assertEqual(status, 201)
        self.assertTrue(data["valid"])
        self.assertEqual(len(data["leaf"]["checksum"]), 32)
        status, view = self._get("/api/ectd/dossiers/e123456/current-view")
        self.assertEqual(status, 200)
        self.assertEqual({l["leaf_id"] for l in view["live"]}, {"cl-0000"})

    def test_dangling_reference_blocked_through_api(self):
        self._post("/api/ectd/dossiers", {"dossier_id": "e123456"})
        status, data = self._post(
            "/api/ectd/dossiers/e123456/leaves",
            self._cover_leaf(leaf_id="x", operation="replace",
                             modified_leaf="ghost"))
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])
        self.assertIn("not live", data["error"])

    # -- REQ-019: file reuse through the API ------------------------------
    def test_file_reuse_through_api(self):
        self._post("/api/ectd/dossiers", {"dossier_id": "e123456"})
        self._post("/api/ectd/dossiers/e123456/leaves", self._cover_leaf())
        status, data = self._post(
            "/api/ectd/dossiers/e123456/leaves",
            {"sequence": "0001", "leaf_id": "cl-0001", "operation": "replace",
             "modified_leaf": "cl-0000", "heading": "1.0",
             "title": "Reused", "reused_from": "cl-0000"})
        self.assertEqual(status, 201)
        self.assertIsNotNone(data["leaf"]["reused_from"])
        self.assertEqual(len(data["leaf"]["checksum"]), 32)

    # -- REQ-014/015: export both backbones + checksums -------------------
    def test_export_returns_backbones_and_index_md5(self):
        self._post("/api/ectd/dossiers", {"dossier_id": "e123456"})
        self._post("/api/ectd/dossiers/e123456/leaves", self._cover_leaf())
        status, data = self._get("/api/ectd/dossiers/e123456/export/0000")
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertIn("index.xml", data["previews"])
        self.assertIn("m1/ca/ca-regional.xml", data["previews"])
        self.assertEqual(len(data["index_md5"]), 32)

    def test_unknown_dossier_404(self):
        status, _ = self._get("/api/ectd/dossiers/e999999/current-view")
        self.assertEqual(status, 404)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rep(**overrides):
    """A fully valid REP single-entry transaction payload."""
    data = {
        "applicant": "Acme Generics Inc.",
        "company_id": "K18276",
        "dossier_id": "e123456",
        "activity_type": "ANDS",
        "sequence": "0000",
        "drug_product": "Metformin HCl 500 mg tablets",
    }
    data.update(overrides)
    return data


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


# ---------------------------------------------------------------------------
# Validation engine slice (REQ-022/023/024/045/059/070)
# ---------------------------------------------------------------------------

import validation


def _vctx(**over):
    """A fully-consistent, defect-free validation context (clean under v5.3)."""
    ctx = {
        "dossier_id": "e123456",
        "sequence": "0000",
        "files": [
            {"path": "0000/m1/ca/cover.pdf", "kind": "pdf", "readable": True,
             "encrypted": False, "bookmarks": True},
        ],
        "leaves": [
            {"leaf_id": "cl-0000", "href": "0000/m1/ca/cover.pdf",
             "operation": "new", "checksum": ectd.md5_hex("cover-bytes"),
             "content": "cover-bytes"},
        ],
        "module5_studies": [],
        "rep": {
            "co": {"company_id": "K18276"},
            "rt": {"dossier_id": "e123456", "company_id": "K18276"},
            "pi": {"dossier_id": "e123456", "company_id": "K18276"},
        },
        "cover_letter": {"dossier_id": "e123456", "company_id": "K18276"},
        "ca_regional": {"dossier_id": "e123456", "company_id": "K18276"},
    }
    ctx.update(over)
    return ctx


def _co_xml(company_id="K18276"):
    return (f'<rep-company template-version="{rep.CO_TEMPLATE_VERSION}">'
            f'<company-id>{company_id}</company-id></rep-company>')


def _rt_xml():
    return (f'<rep-transaction template-version="{rep.RT_TEMPLATE_VERSION}">'
            '<dossier-id>e123456</dossier-id>'
            '<company-id>K18276</company-id>'
            '<regulatory-activity-type>ANDS</regulatory-activity-type>'
            '</rep-transaction>')


# -- REQ-022: versioned ruleset engine ---------------------------------------

class RulesetEngineTests(unittest.TestCase):
    def test_active_version_is_5_3_and_newest_first(self):
        versions = validation.list_ruleset_versions()
        self.assertEqual(versions[0]["version"], "5.3")
        self.assertTrue(versions[0]["active"])
        self.assertEqual(validation.ACTIVE_RULESET_VERSION, "5.3")

    def test_ruleset_version_gating_includes_a02_and_stf_only_in_5_3(self):
        ids_53 = {r["rule_id"] for r in validation.get_ruleset("5.3")["rules"]}
        ids_52 = {r["rule_id"] for r in validation.get_ruleset("5.2")["rules"]}
        self.assertIn("A02", ids_53)
        self.assertIn("S01", ids_53)
        self.assertNotIn("A02", ids_52)
        self.assertNotIn("S01", ids_52)

    def test_unknown_ruleset_raises(self):
        with self.assertRaises(validation.UnknownRulesetError):
            validation.get_ruleset("9.9")

    def test_catalog_is_serialisable_with_required_fields(self):
        cat = validation.ruleset_catalog("5.3")
        self.assertEqual(cat["version"], "5.3")
        for rule in cat["rules"]:
            self.assertEqual(
                set(rule),
                {"rule_id", "category", "severity", "description",
                 "ruleset_version"})
            self.assertNotIn("check", rule)
            self.assertIn(rule["severity"],
                          (validation.SEVERITY_ERROR, validation.SEVERITY_WARNING))

    def test_clean_context_does_not_block(self):
        result = validation.run_validation(_vctx(), "5.3")
        self.assertFalse(result["blocking"])
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["ruleset_version"], "5.3")

    def test_error_blocks_warning_does_not(self):
        ctx = _vctx()
        ctx["files"][0]["readable"] = False        # A02 Error
        blocked = validation.run_validation(ctx, "5.3")
        self.assertTrue(blocked["blocking"])
        self.assertEqual(blocked["error_count"], 1)

        warn_ctx = _vctx()
        warn_ctx["files"][0]["bookmarks"] = False  # A11 Warning
        warned = validation.run_validation(warn_ctx, "5.3")
        self.assertFalse(warned["blocking"])
        self.assertEqual(warned["warning_count"], 1)


# -- REQ-070: A02 file/folder readability, distinct from A09 ------------------

class A02ReadabilityTests(unittest.TestCase):
    def test_unreadable_file_raises_a02(self):
        ctx = _vctx()
        ctx["files"][0]["readable"] = False
        findings = validation.run_validation(ctx, "5.3")["findings"]
        a02 = [f for f in findings if f["rule_id"] == "A02"]
        self.assertEqual(len(a02), 1)
        self.assertEqual(a02[0]["severity"], validation.SEVERITY_ERROR)
        self.assertEqual(a02[0]["category"], "General")
        self.assertEqual(a02[0]["file"], "0000/m1/ca/cover.pdf")

    def test_unreadable_folder_mapped_to_path(self):
        ctx = _vctx()
        ctx["files"].append(
            {"path": "0000/m1/empty", "is_dir": True, "readable": False})
        a02 = [f for f in validation.run_validation(ctx, "5.3")["findings"]
               if f["rule_id"] == "A02"]
        self.assertIn("0000/m1/empty", {f["file"] for f in a02})
        self.assertIn("folder", a02[0]["message"])

    def test_a02_distinct_from_a09_encryption(self):
        ctx = _vctx()
        ctx["files"][0]["readable"] = False
        ctx["files"][0]["encrypted"] = True
        ids = {f["rule_id"] for f in validation.run_validation(ctx, "5.3")["findings"]}
        self.assertIn("A02", ids)   # readability (General)
        self.assertIn("A09", ids)   # PDF encryption — separate rule
        a09 = [f for f in validation.run_validation(ctx, "5.3")["findings"]
               if f["rule_id"] == "A09"]
        self.assertEqual(a09[0]["category"], "PDF")

    def test_readable_passes_a02(self):
        ids = {f["rule_id"] for f in validation.run_validation(_vctx(), "5.3")["findings"]}
        self.assertNotIn("A02", ids)


# -- REQ-023: continuous inline gutter + one-click fixes ---------------------

class InlineGutterTests(unittest.TestCase):
    def test_gutter_maps_defect_to_file_with_colour_and_fix(self):
        ctx = _vctx()
        ctx["files"][0]["readable"] = False
        inline = validation.inline_findings(ctx, "5.3")
        self.assertTrue(inline["blocking"])
        entry = inline["gutter"]["0000/m1/ca/cover.pdf"][0]
        self.assertEqual(entry["rule_id"], "A02")
        self.assertEqual(entry["fix_id"], "grant-read")
        self.assertTrue(entry["remediable"])
        self.assertEqual(entry["colour"],
                         validation.SEVERITY_COLOUR[validation.SEVERITY_ERROR])

    def test_error_and_warning_colours_differ(self):
        self.assertNotEqual(
            validation.SEVERITY_COLOUR[validation.SEVERITY_ERROR],
            validation.SEVERITY_COLOUR[validation.SEVERITY_WARNING])

    def test_one_click_grant_read_clears_a02(self):
        ctx = _vctx()
        ctx["files"][0]["readable"] = False
        fixed = validation.apply_fix(ctx, "grant-read", "0000/m1/ca/cover.pdf")
        ids = {f["rule_id"] for f in validation.run_validation(fixed, "5.3")["findings"]}
        self.assertNotIn("A02", ids)
        # original context is not mutated (non-destructive)
        self.assertFalse(ctx["files"][0]["readable"])

    def test_one_click_decrypt_clears_a09(self):
        ctx = _vctx()
        ctx["files"][0]["encrypted"] = True
        fixed = validation.apply_fix(ctx, "decrypt-pdf", "0000/m1/ca/cover.pdf")
        ids = {f["rule_id"] for f in validation.run_validation(fixed, "5.3")["findings"]}
        self.assertNotIn("A09", ids)

    def test_unknown_fix_raises(self):
        with self.assertRaises(ValueError):
            validation.apply_fix(_vctx(), "nope", "0000/m1/ca/cover.pdf")


# -- REQ-059: cross-document consistency + packaging block -------------------

class CrossDocumentConsistencyTests(unittest.TestCase):
    def test_clean_context_is_consistent(self):
        self.assertEqual(validation.check_cross_document_consistency(_vctx()), [])

    def test_identifier_disagreement_flagged(self):
        ctx = _vctx()
        ctx["rep"]["pi"]["dossier_id"] = "e999999"
        findings = validation.check_cross_document_consistency(ctx)
        ids = {f["rule_id"] for f in findings}
        self.assertIn("P01", ids)
        self.assertEqual(findings[0]["node"], "dossier_id")

    def test_product_metadata_mismatch_flagged(self):
        ctx = _vctx()
        ctx["rep"]["pi"]["product_name"] = "Metformin"
        ctx["drug_product"] = "Ibuprofen"
        ids = {f["rule_id"] for f in
               validation.check_cross_document_consistency(ctx)}
        self.assertIn("P02", ids)

    def test_missing_stf_for_module5_study_flagged(self):
        ctx = _vctx()
        ctx["module5_studies"] = [
            {"id": "be-1", "requires_stf": True, "stf_present": False,
             "folder": "0000/m5/531"}]
        findings = validation.check_cross_document_consistency(ctx)
        stf = [f for f in findings if f["rule_id"] == "S01"]
        self.assertEqual(len(stf), 1)
        self.assertEqual(stf[0]["category"], "STF")

    def test_malformed_stf_flagged(self):
        ctx = _vctx()
        ctx["module5_studies"] = [
            {"id": "be-1", "requires_stf": True, "stf_present": True,
             "stf_valid": False, "folder": "0000/m5/531"}]
        ids = {f["rule_id"] for f in
               validation.check_cross_document_consistency(ctx)}
        self.assertIn("S01", ids)

    def test_packaging_blocked_on_inconsistency(self):
        ctx = _vctx()
        ctx["rep"]["pi"]["dossier_id"] = "e999999"
        result = validation.validate_for_packaging(ctx, "5.3")
        self.assertFalse(result["can_package"])
        self.assertTrue(result["blocking"])
        self.assertTrue(result["consistency_findings"])

    def test_packaging_allowed_when_clean(self):
        result = validation.validate_for_packaging(_vctx(), "5.3")
        self.assertTrue(result["can_package"])
        self.assertEqual(result["consistency_findings"], [])


# -- REQ-024: downloadable pre-submission report -----------------------------

class ValidationReportTests(unittest.TestCase):
    def test_report_groups_categories_with_rule_ids(self):
        ctx = _vctx()
        ctx["files"][0]["readable"] = False
        report = validation.build_validation_report(ctx, "5.3")
        self.assertTrue(report["blocking"])
        general = [c for c in report["categories"] if c["category"] == "General"]
        self.assertEqual(len(general), 1)
        self.assertEqual(general[0]["errors"][0]["rule_id"], "A02")

    def test_leaf_md5_verified_against_bytes(self):
        report = validation.build_validation_report(_vctx(), "5.3")
        self.assertTrue(all(lf["verified"] for lf in report["leaf_md5"]))

    def test_leaf_md5_mismatch_surfaced(self):
        ctx = _vctx()
        ctx["leaves"][0]["checksum"] = "0" * 32
        report = validation.build_validation_report(ctx, "5.3")
        self.assertFalse(report["leaf_md5"][0]["verified"])

    def test_rep_xml_rendered_via_version_matched_stylesheet(self):
        ctx = _vctx()
        ctx["rep_artifacts"] = [
            {"name": "RT", "xml": _rt_xml(),
             "template_version": rep.RT_TEMPLATE_VERSION}]
        report = validation.build_validation_report(ctx, "5.3")
        rendered = report["backbone_preview"]["rep_rendered"][0]
        self.assertEqual(
            rendered["stylesheet"], "rep-rt-stylesheet-" + rep.RT_TEMPLATE_VERSION)
        self.assertIn("e123456", rendered["rendered"])

    def test_render_rep_xml_version_mismatch_raises(self):
        with self.assertRaises(validation.StylesheetVersionError):
            validation.render_rep_xml(_rt_xml(), "9.9.9")

    def test_report_text_contains_verdict_and_rule_ids(self):
        ctx = _vctx()
        ctx["files"][0]["readable"] = False
        report = validation.build_validation_report(ctx, "5.3")
        text = validation.render_report_text(report)
        self.assertIn("Pre-submission Validation Report", text)
        self.assertIn("BLOCKED", text)
        self.assertIn("A02", text)

    def test_backbone_preview_includes_both_backbones(self):
        ctx = _vctx(index_xml="<index/>", ca_regional_xml="<ca/>")
        preview = validation.build_validation_report(ctx, "5.3")["backbone_preview"]
        self.assertEqual(preview["index.xml"], "<index/>")
        self.assertEqual(preview["m1/ca/ca-regional.xml"], "<ca/>")


# -- REQ-045: schema/service failure with retained-state resume --------------

class ResumableTransactionTests(unittest.TestCase):
    def test_valid_rep_artifact_passes(self):
        validation.validate_rep_artifact("co", _co_xml())  # no raise

    def test_wrong_root_raises_rep_schema_error(self):
        with self.assertRaises(validation.RepSchemaError):
            validation.validate_rep_artifact("co", "<not-company/>")

    def test_missing_required_element_raises(self):
        with self.assertRaises(validation.RepSchemaError):
            validation.validate_rep_artifact(
                "co", f'<rep-company template-version="{rep.CO_TEMPLATE_VERSION}">'
                      '<company-id></company-id></rep-company>')

    def test_schema_failure_retains_state(self):
        ctx = _vctx()
        ctx["rep_artifacts"] = [{"name": "co", "xml": "<not-company/>"}]
        result = validation.attempt_package(ctx)
        self.assertFalse(result["ok"])
        self.assertEqual(result["blocked_by"], "schema")
        self.assertTrue(result["state_retained"])
        self.assertTrue(result["resume"])

    def test_service_outage_retains_state(self):
        ctx = _vctx()
        ctx["rep_artifacts"] = [{"name": "co", "xml": _co_xml()}]
        result = validation.attempt_package(ctx, {"fda_esg": "down"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["blocked_by"], "service")
        self.assertEqual(result["service"], "fda_esg")
        self.assertTrue(result["state_retained"])

    def test_success_when_schema_ok_and_services_up(self):
        ctx = _vctx()
        ctx["rep_artifacts"] = [{"name": "co", "xml": _co_xml()}]
        result = validation.attempt_package(ctx, {"fda_esg": "up"})
        self.assertTrue(result["ok"])

    def test_resume_succeeds_after_service_recovers(self):
        ctx = _vctx()
        ctx["rep_artifacts"] = [{"name": "co", "xml": _co_xml()}]
        txn = validation.ResumableTransaction(ctx)
        first = txn.attempt({"fda_esg": "down"})
        self.assertFalse(first["ok"])
        self.assertEqual(first["attempts"], 1)
        second = txn.attempt({"fda_esg": "up"})
        self.assertTrue(second["ok"])
        self.assertEqual(second["attempts"], 2)


# -- API surface for the validation slice ------------------------------------

class ValidationApiTests(unittest.TestCase):
    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.companies = server.CompanyStore(":memory:")
        self.dossiers = server.DossierStore(":memory:")
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            server.make_handler(self.store, self.companies, self.dossiers))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.store.close()
        self.companies.close()
        self.dossiers.close()

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

    def _post_text(self, path, body):
        req = urllib.request.Request(
            self._url(path), data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as resp:
            return (resp.status, resp.read().decode(),
                    resp.headers.get("Content-Disposition", ""))

    # REQ-022
    def test_rulesets_endpoint(self):
        status, data = self._get("/api/validation/rulesets")
        self.assertEqual(status, 200)
        self.assertEqual(data["active"], "5.3")
        self.assertIn("5.3", {r["version"] for r in data["rulesets"]})

    def test_ruleset_catalog_endpoint(self):
        status, data = self._get("/api/validation/ruleset?version=5.3")
        self.assertEqual(status, 200)
        self.assertIn("A02", {r["rule_id"] for r in data["rules"]})

    def test_ruleset_unknown_version_422(self):
        status, _ = self._get("/api/validation/ruleset?version=9.9")
        self.assertEqual(status, 422)

    # REQ-045
    def test_services_endpoint(self):
        status, data = self._get("/api/validation/services")
        self.assertEqual(status, 200)
        keys = {s["key"] for s in data["services"]}
        self.assertIn("fda_esg", keys)
        self.assertIn("rep_id_return", keys)

    # REQ-022/070
    def test_run_endpoint_blocks_on_error(self):
        ctx = _vctx()
        ctx["files"][0]["readable"] = False
        status, data = self._post(
            "/api/validation/run", {"context": ctx, "version": "5.3"})
        self.assertEqual(status, 200)
        self.assertTrue(data["blocking"])
        self.assertIn("A02", {f["rule_id"] for f in data["findings"]})

    # REQ-023
    def test_inline_endpoint(self):
        ctx = _vctx()
        ctx["files"][0]["readable"] = False
        status, data = self._post("/api/validation/inline", {"context": ctx})
        self.assertEqual(status, 200)
        self.assertIn("0000/m1/ca/cover.pdf", data["gutter"])

    def test_fix_endpoint_applies_and_revalidates(self):
        ctx = _vctx()
        ctx["files"][0]["readable"] = False
        status, data = self._post("/api/validation/fix", {
            "context": ctx, "fix_id": "grant-read",
            "file": "0000/m1/ca/cover.pdf"})
        self.assertEqual(status, 200)
        self.assertTrue(data["applied"])
        self.assertFalse(data["inline"]["blocking"])

    def test_fix_endpoint_unknown_fix_422(self):
        status, _ = self._post("/api/validation/fix", {
            "context": _vctx(), "fix_id": "bogus", "file": "x"})
        self.assertEqual(status, 422)

    # REQ-024
    def test_report_endpoint(self):
        status, data = self._post("/api/validation/report", {"context": _vctx()})
        self.assertEqual(status, 200)
        self.assertEqual(data["ruleset_version"], "5.3")
        self.assertIn("text", data)
        self.assertTrue(all(lf["verified"] for lf in data["leaf_md5"]))

    def test_report_download_is_text_attachment(self):
        status, body, disposition = self._post_text(
            "/api/validation/report.txt", {"context": _vctx()})
        self.assertEqual(status, 200)
        self.assertIn("attachment", disposition)
        self.assertIn("Pre-submission Validation Report", body)

    # REQ-059
    def test_consistency_endpoint_flags_disagreement(self):
        ctx = _vctx()
        ctx["rep"]["pi"]["dossier_id"] = "e999999"
        status, data = self._post("/api/validation/consistency", {"context": ctx})
        self.assertEqual(status, 200)
        self.assertFalse(data["consistent"])
        self.assertIn("P01", {f["rule_id"] for f in data["findings"]})

    def test_package_endpoint_blocks_on_error(self):
        ctx = _vctx()
        ctx["module5_studies"] = [
            {"id": "be-1", "requires_stf": True, "stf_present": False,
             "folder": "0000/m5/531"}]
        status, data = self._post("/api/validation/package", {"context": ctx})
        self.assertEqual(status, 200)
        self.assertFalse(data["can_package"])

    # REQ-045
    def test_package_attempt_409_on_schema_failure(self):
        ctx = _vctx()
        ctx["rep_artifacts"] = [{"name": "co", "xml": "<not-company/>"}]
        status, data = self._post("/api/validation/package-attempt", {"context": ctx})
        self.assertEqual(status, 409)
        self.assertFalse(data["ok"])
        self.assertEqual(data["blocked_by"], "schema")
        self.assertTrue(data["state_retained"])

    def test_package_attempt_200_on_success(self):
        ctx = _vctx()
        ctx["rep_artifacts"] = [{"name": "co", "xml": _co_xml()}]
        status, data = self._post(
            "/api/validation/package-attempt",
            {"context": ctx, "services": {"fda_esg": "up"}})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])


# ---------------------------------------------------------------------------
# REQ-007 — Canadian Reference Product + pharmaceutical equivalence (domain)
# ---------------------------------------------------------------------------

class CrpDomainTests(unittest.TestCase):
    def _crp(self, **over):
        base = {"brand_name": "Glucophage", "din": "02229516",
                "strength": "500 mg", "dosage_form": "tablet",
                "innovator": "Innovator Pharma Inc.",
                "medicinal_ingredients": ["metformin hydrochloride"],
                "generic": {"dosage_form": "film-coated tablet",
                            "medicinal_ingredients": ["metformin hydrochloride"]}}
        base.update(over)
        return base

    def test_all_structured_fields_required(self):
        errors = bioequivalence.validate_crp({})
        rules = {e["rule"] for e in errors}
        for field in ("brand_name", "din", "strength", "dosage_form", "innovator"):
            self.assertIn(f"crp_{field}_required", rules)

    def test_complete_crp_has_no_field_errors(self):
        self.assertEqual(bioequivalence.validate_crp(self._crp()), [])

    def test_foreign_crp_requires_justification(self):
        errors = bioequivalence.validate_crp(self._crp(foreign=True))
        self.assertIn("foreign_crp_justification_required",
                      {e["rule"] for e in errors})

    def test_foreign_crp_with_justification_ok(self):
        errors = bioequivalence.validate_crp(
            self._crp(foreign=True, foreign_justification="US RLD, same formulation"))
        self.assertEqual(errors, [])

    def test_comparable_dosage_forms(self):
        self.assertTrue(
            bioequivalence.is_comparable_dosage_form("tablet", "film-coated tablet"))
        self.assertTrue(
            bioequivalence.is_comparable_dosage_form("capsule", "softgel"))
        self.assertFalse(
            bioequivalence.is_comparable_dosage_form("tablet", "capsule"))

    def test_pharmaceutical_equivalence_ingredient_mismatch(self):
        crp = self._crp()
        crp["generic"]["medicinal_ingredients"] = ["metformin"]
        defects = bioequivalence.check_pharmaceutical_equivalence(crp, crp["generic"])
        self.assertIn("pharmaceutical_equivalence_ingredient",
                      {d["rule"] for d in defects})

    def test_pharmaceutical_equivalence_dosage_form_mismatch(self):
        crp = self._crp()
        crp["generic"]["dosage_form"] = "oral solution"
        defects = bioequivalence.check_pharmaceutical_equivalence(crp, crp["generic"])
        self.assertIn("pharmaceutical_equivalence_dosage_form",
                      {d["rule"] for d in defects})

    def test_assemble_crp_valid(self):
        result = bioequivalence.assemble_crp(self._crp())
        self.assertTrue(result["valid"])
        self.assertTrue(result["crp"]["pharmaceutically_equivalent"])
        self.assertEqual(result["crp"]["din"], "02229516")

    def test_assemble_crp_invalid_blocks(self):
        crp = self._crp(din="")
        result = bioequivalence.assemble_crp(crp)
        self.assertFalse(result["valid"])
        self.assertIsNone(result["crp"])


# ---------------------------------------------------------------------------
# REQ-063 — versioned BE acceptance ruleset (domain)
# ---------------------------------------------------------------------------

class BeRulesetTests(unittest.TestCase):
    def test_ir_solid_oral_on_or_after_m13a_is_m13a(self):
        rs = bioequivalence.resolve_be_ruleset("2025-12-27", "ir_solid_oral")
        self.assertEqual(rs["version"], "M13A")
        self.assertEqual(rs["cmax_rule"], "ci90")
        self.assertEqual(rs["decimals"], 2)

    def test_ir_solid_oral_before_m13a_is_legacy(self):
        rs = bioequivalence.resolve_be_ruleset("2025-12-26", "ir_solid_oral")
        self.assertEqual(rs["version"], "legacy")
        self.assertEqual(rs["cmax_rule"], "point_estimate")

    def test_non_ir_after_m13a_is_legacy(self):
        rs = bioequivalence.resolve_be_ruleset("2026-06-01", "mr_solid_oral")
        self.assertEqual(rs["version"], "legacy")
        self.assertEqual(rs["cmax_rule"], "point_estimate")

    def test_ruleset_not_hardcoded_both_published(self):
        versions = {r["version"] for r in bioequivalence.list_be_rulesets()}
        self.assertEqual(versions, {"M13A", "legacy"})

    def test_resolved_ruleset_echoes_inputs(self):
        rs = bioequivalence.resolve_be_ruleset("2026-01-01", "ir_solid_oral")
        self.assertEqual(rs["submission_date"], "2026-01-01")
        self.assertEqual(rs["dosage_form_class"], "ir_solid_oral")


# ---------------------------------------------------------------------------
# REQ-008 / REQ-063 — Cmax branch + AUC + CS-BE builder (domain)
# ---------------------------------------------------------------------------

class CmaxBranchTests(unittest.TestCase):
    def _m13a(self):
        return bioequivalence.resolve_be_ruleset("2026-01-01", "ir_solid_oral")

    def _legacy(self):
        return bioequivalence.resolve_be_ruleset("2026-01-01", "mr_solid_oral")

    def test_m13a_requires_full_ci(self):
        findings = bioequivalence.validate_cmax({"point_estimate": 100.0}, self._m13a())
        self.assertIn("cmax_ci_required", {f["rule"] for f in findings})

    def test_m13a_ci_within_passes(self):
        findings = bioequivalence.validate_cmax(
            {"ci_lower": 81.0, "ci_upper": 120.0}, self._m13a())
        self.assertEqual(findings, [])

    def test_m13a_ci_out_of_range_fails(self):
        findings = bioequivalence.validate_cmax(
            {"ci_lower": 78.0, "ci_upper": 120.0}, self._m13a())
        self.assertIn("cmax_ci_out_of_range", {f["rule"] for f in findings})

    def test_legacy_uses_point_estimate(self):
        findings = bioequivalence.validate_cmax({"point_estimate": 112.0}, self._legacy())
        self.assertEqual(findings, [])

    def test_legacy_point_estimate_out_of_range(self):
        findings = bioequivalence.validate_cmax({"point_estimate": 130.0}, self._legacy())
        self.assertIn("cmax_point_estimate_out_of_range", {f["rule"] for f in findings})

    def test_legacy_requires_point_estimate(self):
        findings = bioequivalence.validate_cmax(
            {"ci_lower": 90.0, "ci_upper": 110.0}, self._legacy())
        self.assertIn("cmax_point_estimate_required", {f["rule"] for f in findings})

    def test_auc_always_uses_ci(self):
        findings = bioequivalence.validate_auc({"ci_lower": 92.0, "ci_upper": 110.0},
                                               self._m13a())
        self.assertEqual(findings, [])
        missing = bioequivalence.validate_auc({}, self._legacy())
        self.assertIn("auc_ci_required", {f["rule"] for f in missing})

    def test_evaluate_bioequivalence_pass_and_fail(self):
        ok = bioequivalence.evaluate_bioequivalence(
            {"auc": {"ci_lower": 90.0, "ci_upper": 112.0},
             "cmax": {"ci_lower": 85.0, "ci_upper": 118.0}},
            "2026-01-01", "ir_solid_oral")
        self.assertTrue(ok["bioequivalent"])
        self.assertEqual(ok["cmax_rule"], "ci90")
        bad = bioequivalence.evaluate_bioequivalence(
            {"auc": {"ci_lower": 90.0, "ci_upper": 112.0},
             "cmax": {"ci_lower": 70.0, "ci_upper": 118.0}},
            "2026-01-01", "ir_solid_oral")
        self.assertFalse(bad["bioequivalent"])


class CsBeBuilderTests(unittest.TestCase):
    def _data(self, **over):
        base = {"submission_date": "2026-01-15", "dosage_form_class": "ir_solid_oral",
                "auc": {"ci_lower": 92.0, "ci_upper": 110.0},
                "cmax": {"ci_lower": 88.0, "ci_upper": 116.0},
                "pivotal_reports": [{"id": "be-01", "title": "Pivotal BE study"}]}
        base.update(over)
        return base

    def test_cs_be_electronic_copy_in_module_1_6(self):
        result = bioequivalence.build_cs_be(self._data())
        self.assertTrue(result["valid"])
        self.assertEqual(result["cs_be"]["electronic_copy"]["module"], "1.6")

    def test_pivotal_reports_link_into_5_3_1_2(self):
        result = bioequivalence.build_cs_be(self._data())
        self.assertEqual(result["cs_be"]["pivotal_reports"][0]["module"], "5.3.1.2")

    def test_does_not_generate_2_7_1_and_suppresses_2_4_to_2_7(self):
        cs_be = bioequivalence.build_cs_be(self._data())["cs_be"]
        self.assertFalse(cs_be["generates_2_7_1"])
        for mod in ("2.4", "2.5", "2.6", "2.7", "2.7.1"):
            self.assertIn(mod, cs_be["suppressed_modules"])

    def test_carries_draft_flag(self):
        cs_be = bioequivalence.build_cs_be(self._data())["cs_be"]
        self.assertTrue(cs_be["draft"])
        self.assertEqual(cs_be["draft_date"], "2004-05-18")

    def test_branches_cmax_rule_by_ruleset(self):
        m13a = bioequivalence.build_cs_be(self._data())["cs_be"]
        self.assertEqual(m13a["cmax_rule"], "ci90")
        legacy = bioequivalence.build_cs_be(
            self._data(dosage_form_class="mr_solid_oral",
                       cmax={"point_estimate": 105.0}))["cs_be"]
        self.assertEqual(legacy["cmax_rule"], "point_estimate")

    def test_captures_auc_and_cmax_results(self):
        # REQ-008: the CS-BE SHALL capture the AUC and Cmax results.
        data = self._data()
        cs_be = bioequivalence.build_cs_be(data)["cs_be"]
        self.assertEqual(cs_be["auc"], data["auc"])
        self.assertEqual(cs_be["cmax"], data["cmax"])

    def test_be_failure_blocks_build(self):
        result = bioequivalence.build_cs_be(
            self._data(cmax={"ci_lower": 70.0, "ci_upper": 118.0}))
        self.assertFalse(result["valid"])
        self.assertTrue(result["errors"])

    def test_leaf_xml_is_well_formed_and_marks_no_2_7_1(self):
        from xml.dom.minidom import parseString
        cs_be = bioequivalence.build_cs_be(self._data())["cs_be"]
        xml = bioequivalence.build_cs_be_leaf_xml(cs_be)
        parseString(xml)  # raises on malformed
        self.assertIn("<generates-2-7-1>false</generates-2-7-1>", xml)


# ---------------------------------------------------------------------------
# REQ-061 — QOS-CE (domain)
# ---------------------------------------------------------------------------

class QosCeTests(unittest.TestCase):
    def _full(self):
        return {"drug_product": "Metformin HCl 500 mg tablets",
                "sections": {"introduction": "intro", "drug_substance": "DS",
                             "drug_product": "DP", "appendices": "appx",
                             "regional": "regional"}}

    def test_template_lists_module_2_3_sections(self):
        tpl = qos.qos_ce_template()
        self.assertEqual(tpl["module"], "2.3")
        keys = {s["key"] for s in tpl["sections"]}
        self.assertEqual(keys, {"introduction", "drug_substance", "drug_product",
                                "appendices", "regional"})

    def test_complete_qos_validates(self):
        self.assertEqual(qos.validate_qos_ce(self._full()), [])

    def test_incomplete_section_flagged(self):
        data = self._full()
        data["sections"]["regional"] = ""
        errors = qos.validate_qos_ce(data)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["code"], "2.3.R")

    def test_absent_qos_flags_every_section(self):
        errors = qos.validate_qos_ce({})
        self.assertEqual(len(errors), 5)

    def test_build_complete_qos(self):
        result = qos.build_qos_ce(self._full())
        self.assertTrue(result["valid"])
        self.assertEqual(result["qos_ce"]["module"], "2.3")
        self.assertTrue(result["qos_ce"]["complete"])
        self.assertIn("<qos-ce", result["qos_ce"]["document"])

    def test_build_fills_section_content(self):
        # REQ-061: the builder SHALL FILL the template — the supplied section
        # content is carried into the built QOS-CE (and its document body).
        result = qos.build_qos_ce(self._full())
        intro = next(s for s in result["qos_ce"]["sections"]
                     if s["key"] == "introduction")
        self.assertEqual(intro["content"], "intro")
        self.assertTrue(intro["complete"])
        self.assertIn("intro", result["qos_ce"]["document"])

    def test_gate_flags_screening_deficiency_when_absent(self):
        gate = qos.qos_ce_gate({})
        self.assertFalse(gate["can_pass"])
        self.assertTrue(gate["screening_deficiency_risk"])
        self.assertIn("absent", gate["risk_message"])

    def test_gate_flags_incomplete_as_screening_deficiency(self):
        data = self._full()
        data["sections"]["drug_substance"] = ""
        gate = qos.qos_ce_gate(data)
        self.assertFalse(gate["can_pass"])
        self.assertIn("incomplete", gate["risk_message"])

    def test_gate_passes_when_complete(self):
        gate = qos.qos_ce_gate(self._full())
        self.assertTrue(gate["can_pass"])
        self.assertFalse(gate["screening_deficiency_risk"])


# ---------------------------------------------------------------------------
# REQ-064 — Study Tagging File (domain)
# ---------------------------------------------------------------------------

class StfTests(unittest.TestCase):
    def test_build_stf_leaf_is_conformant(self):
        leaf = stf.build_stf_leaf({"id": "be-01", "type": "bioequivalence",
                                   "files": ["study-report-body", "synopsis"]})
        self.assertEqual(leaf["category"], "STF")
        self.assertEqual(leaf["leaf_id"], "stf-be-01")
        self.assertEqual(stf.validate_stf(leaf), [])

    def test_generate_stfs_for_studies_that_require_one(self):
        leaves = stf.generate_stfs([
            {"id": "a"}, {"id": "b", "requires_stf": False}])
        self.assertEqual([l["study_id"] for l in leaves], ["a"])

    def test_leaf_targets_module5_be_folder(self):
        # REQ-064: conformant STF leaves are generated where Module 5 BE study
        # reports appear (the comparative-BA/BE folder under 5.3.1.2).
        leaf = stf.build_stf_leaf({"id": "be-01", "type": "bioequivalence"})
        self.assertIn("5312-comp-ba-be", leaf["folder"])
        self.assertTrue(leaf["href"].endswith("stf-be-01.xml"))
        self.assertIn("5312-comp-ba-be", leaf["href"])

    def test_validate_stf_flags_malformed(self):
        findings = stf.validate_stf({"xml": "<ectd-stf><broken>"})
        self.assertIn("stf_malformed", {f["rule"] for f in findings})
        self.assertTrue(all(f["category"] == "STF" for f in findings))

    def test_validate_stf_flags_missing_element(self):
        xml = ('<?xml version="1.0"?><ectd-stf>'
               '<study-title>t</study-title>'
               '<study-category>bioequivalence</study-category>'
               '<file-tags><file-tag name="x"/></file-tags></ectd-stf>')
        findings = stf.validate_stf({"xml": xml})
        self.assertIn("stf_missing_element", {f["rule"] for f in findings})

    def test_category_blocks_when_stf_missing_and_offers_generated(self):
        result = stf.validate_stf_category([{"id": "be-01"}])
        self.assertFalse(result["valid"])
        self.assertTrue(result["blocking"])
        self.assertEqual(result["findings"][0]["rule"], "stf_required_missing")
        self.assertEqual(len(result["generated"]), 1)
        self.assertEqual(result["category"], "STF")

    def test_category_valid_when_present_and_conformant(self):
        leaf = stf.build_stf_leaf({"id": "be-01"})
        result = stf.validate_stf_category([{"id": "be-01", "stf": leaf}])
        self.assertTrue(result["valid"])

    def test_category_flags_attached_invalid_stf(self):
        result = stf.validate_stf_category(
            [{"id": "be-01", "stf": {"xml": "<wrong/>"}}])
        self.assertFalse(result["valid"])
        self.assertTrue(all(f["category"] == "STF" for f in result["findings"]))


# ---------------------------------------------------------------------------
# REQ-007/008/061/063/064 — JSON API end-to-end
# ---------------------------------------------------------------------------

class ScopeApiTests(unittest.TestCase):
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

    # -- REQ-007 ---------------------------------------------------------
    def test_crp_fields_endpoint(self):
        status, data = self._get("/api/crp/fields")
        self.assertEqual(status, 200)
        keys = {f["key"] for f in data["fields"]}
        self.assertTrue({"brand_name", "din", "dosage_form"} <= keys)

    def test_crp_validate_ok_and_invalid(self):
        good = {"brand_name": "Glucophage", "din": "02229516", "strength": "500 mg",
                "dosage_form": "tablet", "innovator": "Inv",
                "medicinal_ingredients": ["metformin hydrochloride"],
                "generic": {"dosage_form": "caplet",
                            "medicinal_ingredients": ["metformin hydrochloride"]}}
        status, data = self._post("/api/crp/validate", good)
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        status, data = self._post("/api/crp/validate", {"foreign": True})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])
        self.assertIn("foreign_crp_justification_required",
                      {e["rule"] for e in data["errors"]})

    # -- REQ-063 ---------------------------------------------------------
    def test_be_rulesets_endpoint_lists_both(self):
        status, data = self._get("/api/be/rulesets")
        self.assertEqual(status, 200)
        self.assertEqual({r["version"] for r in data["rulesets"]},
                         {"M13A", "legacy"})
        self.assertEqual(data["m13a_effective"], "2025-12-27")

    def test_be_resolve_branches_by_date_and_form(self):
        _, m13a = self._post("/api/be/resolve",
                             {"submission_date": "2026-01-01",
                              "dosage_form_class": "ir_solid_oral"})
        self.assertEqual(m13a["cmax_rule"], "ci90")
        _, legacy = self._post("/api/be/resolve",
                               {"submission_date": "2026-01-01",
                                "dosage_form_class": "mr_solid_oral"})
        self.assertEqual(legacy["cmax_rule"], "point_estimate")

    def test_be_evaluate_pass_and_fail(self):
        status, data = self._post("/api/be/evaluate",
            {"submission_date": "2026-01-01", "dosage_form_class": "ir_solid_oral",
             "auc": {"ci_lower": 92.0, "ci_upper": 110.0},
             "cmax": {"ci_lower": 85.0, "ci_upper": 118.0}})
        self.assertEqual(status, 200)
        self.assertTrue(data["bioequivalent"])
        status, data = self._post("/api/be/evaluate",
            {"submission_date": "2026-01-01", "dosage_form_class": "ir_solid_oral",
             "auc": {"ci_lower": 92.0, "ci_upper": 110.0},
             "cmax": {"ci_lower": 70.0, "ci_upper": 118.0}})
        self.assertEqual(status, 422)
        self.assertFalse(data["bioequivalent"])

    # -- REQ-008 ---------------------------------------------------------
    def test_cs_be_build_endpoint(self):
        status, data = self._post("/api/cs-be/build",
            {"submission_date": "2026-01-15", "dosage_form_class": "ir_solid_oral",
             "auc": {"ci_lower": 92.0, "ci_upper": 110.0},
             "cmax": {"ci_lower": 88.0, "ci_upper": 116.0},
             "pivotal_reports": [{"id": "be-01", "title": "Pivotal BE study"}]})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertEqual(data["cs_be"]["electronic_copy"]["module"], "1.6")
        self.assertFalse(data["cs_be"]["generates_2_7_1"])
        self.assertIn("leaf_xml", data)

    def test_cs_be_build_422_on_be_failure(self):
        status, data = self._post("/api/cs-be/build",
            {"submission_date": "2026-01-15", "dosage_form_class": "ir_solid_oral",
             "auc": {"ci_lower": 92.0, "ci_upper": 110.0},
             "cmax": {"ci_lower": 70.0, "ci_upper": 118.0}})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])

    # -- REQ-061 ---------------------------------------------------------
    def test_qos_template_endpoint(self):
        status, data = self._get("/api/qos/template")
        self.assertEqual(status, 200)
        self.assertEqual(data["module"], "2.3")

    def test_qos_build_and_gate(self):
        full = {"drug_product": "Metformin", "sections": {
            "introduction": "i", "drug_substance": "s", "drug_product": "p",
            "appendices": "a", "regional": "r"}}
        status, data = self._post("/api/qos/build", full)
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        status, data = self._post("/api/qos/gate", {})
        self.assertEqual(status, 422)
        self.assertTrue(data["screening_deficiency_risk"])

    # -- REQ-064 ---------------------------------------------------------
    def test_stf_generate_endpoint(self):
        status, data = self._post("/api/stf/generate",
            {"module5_studies": [{"id": "be-01", "type": "bioequivalence"}]})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["stfs"]), 1)
        self.assertEqual(data["stfs"][0]["category"], "STF")

    def test_stf_validate_blocks_on_missing(self):
        status, data = self._post("/api/stf/validate",
            {"module5_studies": [{"id": "be-01"}]})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])
        self.assertEqual(data["category"], "STF")
        self.assertEqual(data["findings"][0]["rule"], "stf_required_missing")

    def test_stf_validate_ok_when_conformant(self):
        leaf = stf.build_stf_leaf({"id": "be-01"})
        status, data = self._post("/api/stf/validate",
            {"module5_studies": [{"id": "be-01", "stf": leaf}]})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])


# ===========================================================================
# Transmission & ESG slice — REQ-003/025/026/027/046/058
# ===========================================================================

# -- REQ-003: ESG transmission configuration --------------------------------

class EsgConfigTests(unittest.TestCase):
    """REQ-003: FDA ESG NextGen config — account type, X.509 cert, recipient
    Center 'HC', no direct HC endpoint, pinned environment, test-gateway gate."""

    GOOD = {"account_type": "AS2", "x509_certificate": "-----PEM-----",
            "registration_id": "REG-77", "recipient_center": "HC"}

    def test_valid_account_types(self):
        self.assertTrue(transmission.is_valid_account_type("WebTrader"))
        self.assertTrue(transmission.is_valid_account_type("AS2"))
        self.assertFalse(transmission.is_valid_account_type("SFTP"))
        self.assertFalse(transmission.is_valid_account_type(""))

    def test_validate_clean_config_has_no_errors(self):
        self.assertEqual(transmission.validate_esg_config(self.GOOD), [])

    def test_bad_account_type_flagged(self):
        errs = transmission.validate_esg_config(
            dict(self.GOOD, account_type="SFTP"))
        self.assertIn("account_type_invalid", {e["rule"] for e in errs})

    def test_missing_certificate_flagged(self):
        errs = transmission.validate_esg_config(
            dict(self.GOOD, x509_certificate="  "))
        self.assertIn("x509_certificate_required", {e["rule"] for e in errs})

    def test_direct_hc_endpoint_rejected(self):
        # CESG rides on the FDA ESG — a direct HC AS2 endpoint must not target.
        errs = transmission.validate_esg_config(
            dict(self.GOOD, hc_direct_endpoint="as2://hc.gc.ca"))
        self.assertIn("no_direct_hc_endpoint", {e["rule"] for e in errs})

    def test_recipient_center_must_be_hc(self):
        errs = transmission.validate_esg_config(
            dict(self.GOOD, recipient_center="CDER"))
        self.assertIn("recipient_center_must_be_hc", {e["rule"] for e in errs})

    def test_build_config_pins_environment_and_disables_production(self):
        cfg = transmission.build_esg_config(self.GOOD)
        self.assertEqual(cfg["esg_environment"], "FDA ESG NextGen")
        self.assertEqual(cfg["esg_environment_deployed"], "2025-04")
        self.assertEqual(cfg["recipient_center"], "HC")
        self.assertFalse(cfg["production_enabled"])
        self.assertTrue(cfg["test_gateway"]["required"])
        self.assertFalse(cfg["test_gateway"]["completed"])
        self.assertFalse(cfg["direct_hc_endpoint"])
        # The certificate is fingerprinted, never stored verbatim.
        self.assertTrue(cfg["x509_certificate_fingerprint"].startswith("SHA256:"))
        self.assertNotIn("-----PEM-----", cfg["x509_certificate_fingerprint"])

    def test_configure_invalid_returns_errors_and_no_config(self):
        result = transmission.configure_transmission({"account_type": "SFTP"})
        self.assertFalse(result["valid"])
        self.assertIsNone(result["config"])
        self.assertTrue(result["errors"])

    def test_full_round_trip_unlocks_production(self):
        cfg = transmission.build_esg_config(self.GOOD)
        done = transmission.complete_test_round_trip(cfg)  # all acks default True
        self.assertTrue(done["test_gateway"]["completed"])
        self.assertTrue(done["production_enabled"])
        allowed, reason = transmission.can_transmit_production(done)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_partial_round_trip_keeps_production_blocked(self):
        cfg = transmission.build_esg_config(self.GOOD)
        done = transmission.complete_test_round_trip(
            cfg, {"mdn_received": True, "fda_ack_received": True,
                  "hc_ack_received": False})
        self.assertFalse(done["test_gateway"]["completed"])
        self.assertFalse(done["production_enabled"])
        allowed, reason = transmission.can_transmit_production(done)
        self.assertFalse(allowed)
        self.assertIn("Test-gateway", reason)

    def test_production_blocked_without_config(self):
        allowed, reason = transmission.can_transmit_production(None)
        self.assertFalse(allowed)
        with self.assertRaises(transmission.ProductionBlockedError):
            transmission.assert_production_allowed(None)


# -- REQ-025 / REQ-026: pre-flight size routing + congestion -----------------

class SizeRoutingTests(unittest.TestCase):
    """REQ-025: 10 GB ceiling routing; REQ-026: 5-10 GB congestion offer."""

    def test_under_ceiling_routes_to_gateway(self):
        r = transmission.evaluate_size_routing(3.2)
        self.assertEqual(r["route"], "gateway")
        self.assertFalse(r["over_limit"])
        self.assertTrue(r["gateway_available"])
        self.assertIsNone(r["shipping_instructions"])

    def test_exactly_ten_gb_still_routes_to_gateway(self):
        # 'at or below 10 GB' -> gateway (boundary is inclusive).
        r = transmission.evaluate_size_routing(10.0)
        self.assertEqual(r["route"], "gateway")
        self.assertFalse(r["over_limit"])

    def test_over_ceiling_routes_to_physical_media_with_shipping(self):
        r = transmission.evaluate_size_routing(12.5)
        self.assertEqual(r["route"], "physical_media")
        self.assertTrue(r["over_limit"])
        self.assertFalse(r["gateway_available"])
        self.assertIn("USB/HDD", r["shipping_instructions"])

    def test_congestion_offer_only_between_5_and_10(self):
        self.assertTrue(transmission.congestion_scheduling(5.0)["offer"])
        self.assertTrue(transmission.congestion_scheduling(7.5)["offer"])
        self.assertTrue(transmission.congestion_scheduling(10.0)["offer"])
        self.assertFalse(transmission.congestion_scheduling(4.99)["offer"])
        self.assertFalse(transmission.congestion_scheduling(10.01)["offer"])

    def test_congestion_offer_cites_1630_est(self):
        offer = transmission.congestion_scheduling(6.0)
        self.assertEqual(offer["after"], "16:30 EST")
        self.assertIn("16:30 EST", offer["reason"])

    def test_routing_folds_in_congestion(self):
        r = transmission.evaluate_size_routing(8.0)
        self.assertEqual(r["route"], "gateway")
        self.assertTrue(r["congestion"]["offer"])


# -- REQ-058: physical-media package builder --------------------------------

class MediaPackageTests(unittest.TestCase):
    """REQ-058: validated tree + backbones + checksums + manifest + cover doc."""

    TXN = {"dossier_id": "e012345", "sequence": "0003", "size_gb": 14.0}

    def test_package_is_complete_with_all_artifacts(self):
        pkg = transmission.build_media_package(self.TXN)
        self.assertTrue(pkg["complete"])
        self.assertTrue(pkg["folder_tree"])
        self.assertTrue(pkg["backbones"])
        self.assertTrue(pkg["checksums"])
        self.assertIn("manifest", pkg)
        self.assertIn("PHYSICAL MEDIA", pkg["cover_documentation"])

    def test_manifest_records_route_and_recipient(self):
        man = transmission.build_media_package(self.TXN)["manifest"]
        self.assertEqual(man["route"], "physical_media")
        self.assertEqual(man["recipient_center"], "HC")
        self.assertEqual(man["dossier_id"], "e012345")
        self.assertEqual(man["sequence"], "0003")

    def test_checksums_cover_supplied_files_and_backbones(self):
        tree = {"folders": ["0003/m1/ca"],
                "backbones": {"index.xml": "<x/>"},
                "files": [{"path": "0003/m3/study.pdf", "content": "PDF"}]}
        pkg = transmission.build_media_package(self.TXN, tree)
        self.assertIn("0003/m3/study.pdf", pkg["checksums"])
        self.assertIn("index.xml", pkg["checksums"])
        # md5 is the documented checksum algorithm.
        self.assertEqual(pkg["checksums"]["index.xml"],
                         transmission.md5_hex("<x/>"))


# -- REQ-027 / REQ-046 / REQ-058: the per-dossier ledger --------------------

class TransmissionLedgerTests(unittest.TestCase):
    T0 = "2026-06-22T10:00:00+00:00"
    T1 = "2026-06-22T10:05:00+00:00"

    def _ledger(self, dossier="e012345"):
        return transmission.TransmissionLedger(dossier)

    # REQ-027 — one transaction at a time per dossier
    def test_first_submit_dispatches_second_queues(self):
        led = self._ledger()
        a = led.submit({"sequence": "0000", "size_gb": 5}, now=self.T0)
        b = led.submit({"sequence": "0001", "size_gb": 6}, now=self.T1)
        self.assertEqual(a["state"], transmission.STATE_SENT)
        self.assertEqual(b["state"], transmission.STATE_QUEUED)
        self.assertEqual(b["queued_behind"], "0000")
        self.assertEqual(led.status()["queued"], ["0001"])

    def test_hc_ack_frees_slot_and_dequeues_next(self):
        led = self._ledger()
        led.submit({"sequence": "0000", "size_gb": 5}, now=self.T0)
        led.submit({"sequence": "0001", "size_gb": 6}, now=self.T1)
        led.receive_mdn("0000")
        led.receive_fda_ack("0000", "CORE-1")
        led.receive_hc_ack("CORE-1")
        self.assertEqual(led._find("0000")["state"],
                         transmission.STATE_RECEIVED_BY_HC)
        # The queued sequence is now dispatched.
        self.assertEqual(led._find("0001")["state"], transmission.STATE_SENT)

    def test_unrelated_dossiers_do_not_block_each_other(self):
        a = self._ledger("e012345")
        b = self._ledger("e088888")
        ra = a.submit({"sequence": "0000", "size_gb": 5}, now=self.T0)
        rb = b.submit({"sequence": "0000", "size_gb": 5}, now=self.T0)
        self.assertEqual(ra["state"], transmission.STATE_SENT)
        self.assertEqual(rb["state"], transmission.STATE_SENT)

    def test_duplicate_sequence_rejected(self):
        led = self._ledger()
        led.submit({"sequence": "0000", "size_gb": 5}, now=self.T0)
        with self.assertRaises(transmission.TransmissionError):
            led.submit({"sequence": "0000", "size_gb": 5}, now=self.T1)

    def test_missing_sequence_rejected(self):
        led = self._ledger()
        with self.assertRaises(transmission.TransmissionError):
            led.submit({"size_gb": 5})

    def test_production_submit_blocked_until_round_trip(self):
        cfg = transmission.build_esg_config(EsgConfigTests.GOOD)
        led = transmission.TransmissionLedger("e012345", cfg)
        with self.assertRaises(transmission.ProductionBlockedError):
            led.submit({"sequence": "0000", "size_gb": 5}, production=True)
        led.set_config(transmission.complete_test_round_trip(cfg))
        rec = led.submit({"sequence": "0000", "size_gb": 5}, production=True)
        self.assertEqual(rec["state"], transmission.STATE_SENT)

    # REQ-046 — stall monitors + duplicate-send prevention
    def test_monitor_flags_missing_mdn(self):
        led = self._ledger()
        led.submit({"sequence": "0000", "size_gb": 3}, now=self.T0)
        alerts = led.check_monitors(now="2026-06-22T12:00:00+00:00",
                                    mdn_timeout_s=3600)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(led._find("0000")["state"],
                         transmission.STATE_TRANSPORT_UNCONFIRMED)

    def test_monitor_flags_mdn_without_fda_ack(self):
        led = self._ledger()
        led.submit({"sequence": "0000", "size_gb": 3}, now=self.T0)
        led.receive_mdn("0000", now=self.T0)
        alerts = led.check_monitors(now="2026-06-24T10:00:00+00:00",
                                    fda_timeout_s=86400)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(led._find("0000")["state"],
                         transmission.STATE_INVESTIGATE)
        # A stalled transaction is never auto-marked received.
        self.assertFalse(led._find("0000")["hc_ack_received"])

    def test_monitor_quiet_when_within_window(self):
        led = self._ledger()
        led.submit({"sequence": "0000", "size_gb": 3}, now=self.T0)
        alerts = led.check_monitors(now=self.T1, mdn_timeout_s=3600)
        self.assertEqual(alerts, [])
        self.assertEqual(led._find("0000")["state"], transmission.STATE_SENT)

    def test_transport_rejection_marks_rejected_and_alerts(self):
        led = self._ledger()
        led.submit({"sequence": "0000", "size_gb": 3}, now=self.T0)
        led.receive_mdn("0000")
        led.receive_fda_ack("0000", "CORE-X", transport_rejected=True)
        t = led._find("0000")
        self.assertEqual(t["state"], transmission.STATE_REJECTED)
        self.assertTrue(t["alerts"])

    def test_resend_blocked_while_unresolved(self):
        led = self._ledger()
        led.submit({"sequence": "0000", "size_gb": 3}, now=self.T0)
        with self.assertRaises(transmission.DuplicateSendError):
            led.resend("0000")

    def test_resend_requires_rationale_even_with_confirm(self):
        led = self._ledger()
        led.submit({"sequence": "0000", "size_gb": 3}, now=self.T0)
        with self.assertRaises(transmission.DuplicateSendError):
            led.resend("0000", confirm=True, rationale="   ")

    def test_resend_allowed_with_confirmation_and_rationale(self):
        led = self._ledger()
        led.submit({"sequence": "0000", "size_gb": 3}, now=self.T0)
        led.check_monitors(now="2026-06-22T12:00:00+00:00", mdn_timeout_s=3600)
        t = led.resend("0000", confirm=True, rationale="ops verified lost",
                       now=self.T1)
        self.assertEqual(len(t["resends"]), 1)
        self.assertEqual(t["resends"][0]["rationale"], "ops verified lost")
        # Re-dispatched from the start of the transport chain.
        self.assertFalse(t["mdn_received"])
        self.assertEqual(t["state"], transmission.STATE_SENT)
        actions = {e["action"] for e in led.audit}
        self.assertIn("resend", actions)

    # REQ-058 — physical-media path + reconciliation
    def test_media_path_lifecycle_and_reconciliation(self):
        led = self._ledger()
        led.submit({"sequence": "0000", "size_gb": 14}, now=self.T0)
        self.assertEqual(led._find("0000")["state"],
                         transmission.STATE_MEDIA_PREP)
        pkg = led.build_media("0000")
        self.assertTrue(pkg["complete"])
        led.ship_media("0000", "Purolator", "TRK-9")
        self.assertEqual(led._find("0000")["state"],
                         transmission.STATE_MEDIA_SHIPPED)
        led.receive_media("0000")
        self.assertEqual(led._find("0000")["state"],
                         transmission.STATE_MEDIA_RECEIVED)
        # HC assigns the Core ID on receipt; bind it to the same record.
        led.receive_hc_ack("CORE-MEDIA-1", sequence="0000")
        t = led._find("0000")
        self.assertEqual(t["state"], transmission.STATE_RECEIVED_BY_HC)
        self.assertEqual(t["core_id"], "CORE-MEDIA-1")

    def test_build_media_rejected_for_gateway_route(self):
        led = self._ledger()
        led.submit({"sequence": "0000", "size_gb": 3}, now=self.T0)
        with self.assertRaises(transmission.TransmissionError):
            led.build_media("0000")

    def test_ship_requires_built_package(self):
        led = self._ledger()
        led.submit({"sequence": "0000", "size_gb": 14}, now=self.T0)
        with self.assertRaises(transmission.TransmissionError):
            led.ship_media("0000", "Purolator", "TRK-9")

    def test_hc_ack_unknown_core_id_raises(self):
        led = self._ledger()
        led.submit({"sequence": "0000", "size_gb": 3}, now=self.T0)
        with self.assertRaises(transmission.TransmissionError):
            led.receive_hc_ack("CORE-NOPE")

    def test_serialization_round_trip_preserves_state(self):
        led = self._ledger()
        led.submit({"sequence": "0000", "size_gb": 5}, now=self.T0)
        led.submit({"sequence": "0001", "size_gb": 6}, now=self.T1)
        led.receive_mdn("0000")
        revived = transmission.TransmissionLedger.from_dict(led.to_dict())
        self.assertEqual(revived.dossier_id, led.dossier_id)
        self.assertEqual([t["sequence"] for t in revived.transactions],
                         ["0000", "0001"])
        self.assertEqual(revived._find("0000")["mdn_received"], True)
        self.assertEqual(revived._find("0001")["state"],
                         transmission.STATE_QUEUED)


# -- Transmission JSON API + UI ---------------------------------------------

class TransmissionApiTests(unittest.TestCase):
    """End-to-end coverage of the Transmission Console endpoints + UI."""

    GOOD_CFG = {"account_type": "AS2", "x509_certificate": "-----PEM-----",
                "registration_id": "REG-77"}

    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                         server.make_handler(self.store))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.store.close()

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
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def _get_json(self, path):
        status, body = self._get(path)
        return status, json.loads(body)

    def _configure(self, dossier="e012345"):
        return self._post("/api/transmission/configure",
                          dict(self.GOOD_CFG, dossier_id=dossier))

    # REQ-003
    def test_account_types_endpoint(self):
        status, data = self._get_json("/api/transmission/account-types")
        self.assertEqual(status, 200)
        keys = {a["key"] for a in data["account_types"]}
        self.assertEqual(keys, {"WebTrader", "AS2"})
        self.assertEqual(data["esg_environment"], "FDA ESG NextGen")
        self.assertEqual(data["recipient_center"], "HC")
        self.assertEqual(data["gateway_ceiling_gb"], 10.0)

    def test_configure_valid_creates_ledger(self):
        status, data = self._configure()
        self.assertEqual(status, 201)
        self.assertTrue(data["valid"])
        self.assertFalse(data["config"]["production_enabled"])
        self.assertEqual(data["status"]["dossier_id"], "e012345")

    def test_configure_requires_dossier_id(self):
        status, data = self._post("/api/transmission/configure", self.GOOD_CFG)
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])

    def test_configure_invalid_account_type_422(self):
        status, data = self._post(
            "/api/transmission/configure",
            {"dossier_id": "e012345", "account_type": "SFTP",
             "x509_certificate": "PEM"})
        self.assertEqual(status, 422)
        self.assertIn("account_type_invalid", {e["rule"] for e in data["errors"]})

    def test_test_round_trip_unlocks_production(self):
        self._configure()
        status, data = self._post("/api/transmission/test-round-trip",
                                  {"dossier_id": "e012345"})
        self.assertEqual(status, 200)
        self.assertTrue(data["production_enabled"])

    def test_test_round_trip_partial_keeps_blocked(self):
        self._configure()
        status, data = self._post(
            "/api/transmission/test-round-trip",
            {"dossier_id": "e012345",
             "acks": {"mdn_received": True, "fda_ack_received": True,
                      "hc_ack_received": False}})
        self.assertEqual(status, 200)
        self.assertFalse(data["production_enabled"])

    # REQ-025 / REQ-026
    def test_route_endpoint_gateway_and_media(self):
        _, gw = self._post("/api/transmission/route", {"size_gb": 4})
        self.assertEqual(gw["routing"]["route"], "gateway")
        _, media = self._post("/api/transmission/route", {"size_gb": 11})
        self.assertEqual(media["routing"]["route"], "physical_media")
        self.assertTrue(media["routing"]["shipping_instructions"])

    def test_route_endpoint_congestion_offer(self):
        _, data = self._post("/api/transmission/route", {"size_gb": 7})
        self.assertTrue(data["routing"]["congestion"]["offer"])
        self.assertEqual(data["routing"]["congestion"]["after"], "16:30 EST")

    # REQ-027
    def test_submit_queues_second_transaction(self):
        s1, d1 = self._post("/api/transmission/submit",
                            {"dossier_id": "e012345", "sequence": "0000",
                             "size_gb": 5, "now": "2026-06-22T10:00:00+00:00"})
        self.assertEqual(s1, 201)
        self.assertEqual(d1["transaction"]["state"], "SENT")
        s2, d2 = self._post("/api/transmission/submit",
                            {"dossier_id": "e012345", "sequence": "0001",
                             "size_gb": 6, "now": "2026-06-22T10:05:00+00:00"})
        self.assertEqual(s2, 201)
        self.assertEqual(d2["transaction"]["state"], "QUEUED")
        self.assertEqual(d2["status"]["queued"], ["0001"])

    def test_production_submit_blocked_409(self):
        self._configure()
        status, data = self._post(
            "/api/transmission/submit",
            {"dossier_id": "e012345", "sequence": "0000", "size_gb": 5,
             "production": True})
        self.assertEqual(status, 409)
        self.assertEqual(data["rule"], "production_blocked")

    def test_full_ack_chain_advances_and_dequeues(self):
        self._post("/api/transmission/submit",
                   {"dossier_id": "e012345", "sequence": "0000", "size_gb": 5,
                    "now": "2026-06-22T10:00:00+00:00"})
        self._post("/api/transmission/submit",
                   {"dossier_id": "e012345", "sequence": "0001", "size_gb": 6,
                    "now": "2026-06-22T10:05:00+00:00"})
        self._post("/api/transmission/ack",
                   {"dossier_id": "e012345", "type": "mdn", "sequence": "0000"})
        self._post("/api/transmission/ack",
                   {"dossier_id": "e012345", "type": "fda", "sequence": "0000",
                    "core_id": "CORE-1"})
        status, data = self._post(
            "/api/transmission/ack",
            {"dossier_id": "e012345", "type": "hc", "core_id": "CORE-1"})
        self.assertEqual(status, 200)
        states = {t["sequence"]: t["state"] for t in data["status"]["transactions"]}
        self.assertEqual(states["0000"], "RECEIVED_BY_HC")
        self.assertEqual(states["0001"], "SENT")

    def test_ack_unknown_type_422(self):
        self._post("/api/transmission/submit",
                   {"dossier_id": "e012345", "sequence": "0000", "size_gb": 5})
        status, data = self._post(
            "/api/transmission/ack",
            {"dossier_id": "e012345", "type": "bogus", "sequence": "0000"})
        self.assertEqual(status, 422)

    def test_ack_unknown_dossier_404(self):
        status, _ = self._post("/api/transmission/ack",
                               {"dossier_id": "e999999", "type": "mdn",
                                "sequence": "0000"})
        self.assertEqual(status, 404)

    # REQ-046
    def test_monitor_raises_alert_for_stalled_transmission(self):
        self._post("/api/transmission/submit",
                   {"dossier_id": "e012345", "sequence": "0000", "size_gb": 5,
                    "now": "2026-06-22T10:00:00+00:00"})
        status, data = self._post(
            "/api/transmission/monitor",
            {"dossier_id": "e012345", "now": "2026-06-22T12:00:00+00:00",
             "mdn_timeout_s": 3600})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["alerts"]), 1)
        states = {t["sequence"]: t["state"] for t in data["status"]["transactions"]}
        self.assertEqual(states["0000"], "TRANSPORT_UNCONFIRMED")

    def test_resend_blocked_then_allowed(self):
        self._post("/api/transmission/submit",
                   {"dossier_id": "e012345", "sequence": "0000", "size_gb": 5,
                    "now": "2026-06-22T10:00:00+00:00"})
        blocked, bdata = self._post(
            "/api/transmission/resend",
            {"dossier_id": "e012345", "sequence": "0000"})
        self.assertEqual(blocked, 409)
        self.assertEqual(bdata["rule"], "duplicate_send_blocked")
        ok, odata = self._post(
            "/api/transmission/resend",
            {"dossier_id": "e012345", "sequence": "0000", "confirm": True,
             "rationale": "ops verified the prior send was lost"})
        self.assertEqual(ok, 200)
        self.assertEqual(len(odata["transaction"]["resends"]), 1)

    # REQ-058
    def test_media_build_ship_receive_and_reconcile(self):
        self._post("/api/transmission/submit",
                   {"dossier_id": "e012345", "sequence": "0000", "size_gb": 14,
                    "now": "2026-06-22T10:00:00+00:00"})
        s, d = self._post("/api/transmission/media/build",
                          {"dossier_id": "e012345", "sequence": "0000"})
        self.assertEqual(s, 201)
        self.assertTrue(d["package"]["complete"])
        self.assertIn("manifest", d["package"])
        s, _ = self._post("/api/transmission/media/ship",
                          {"dossier_id": "e012345", "sequence": "0000",
                           "carrier": "Purolator", "tracking": "TRK-9"})
        self.assertEqual(s, 200)
        s, _ = self._post("/api/transmission/media/receive",
                          {"dossier_id": "e012345", "sequence": "0000"})
        self.assertEqual(s, 200)
        s, d = self._post("/api/transmission/ack",
                          {"dossier_id": "e012345", "type": "hc",
                           "core_id": "CORE-MEDIA-1", "sequence": "0000"})
        states = {t["sequence"]: t for t in d["status"]["transactions"]}
        self.assertEqual(states["0000"]["state"], "RECEIVED_BY_HC")
        self.assertEqual(states["0000"]["core_id"], "CORE-MEDIA-1")

    def test_media_build_rejected_for_gateway_route(self):
        self._post("/api/transmission/submit",
                   {"dossier_id": "e012345", "sequence": "0000", "size_gb": 4})
        status, _ = self._post("/api/transmission/media/build",
                               {"dossier_id": "e012345", "sequence": "0000"})
        self.assertEqual(status, 422)

    # Ledger listing + UI
    def test_dossiers_list_and_detail(self):
        self._configure("e012345")
        status, data = self._get_json("/api/transmission/dossiers")
        self.assertEqual(status, 200)
        self.assertIn("e012345", [d["dossier_id"] for d in data["dossiers"]])
        status, detail = self._get_json("/api/transmission/dossiers/e012345")
        self.assertEqual(status, 200)
        self.assertEqual(detail["dossier_id"], "e012345")

    def test_dossier_detail_unknown_404(self):
        status, _ = self._get_json("/api/transmission/dossiers/e000000")
        self.assertEqual(status, 404)

    def test_index_html_has_transmission_console(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("Transmission Console", body)


# ---------------------------------------------------------------------------
# Version-pluggable backbone generator + persistent UUIDs (REQ-041)
# ---------------------------------------------------------------------------

class BackboneGeneratorDomainTests(unittest.TestCase):
    def _model(self):
        cm = backbone.ContentModel("e123456", "0000")
        cm.add_document("cl", "1.0", "m1/ca/10-cover-letter/cl.pdf",
                        content="cover bytes")
        return cm

    def test_document_uuid_is_persistent_and_deterministic(self):
        # REQ-041: same (dossier, document) -> same UUID, across calls AND
        # independent of the sequence that ships it.
        a = backbone.assign_document_uuid("e123456", "cl")
        b = backbone.assign_document_uuid("e123456", "cl")
        self.assertEqual(a, b)
        # different document -> different UUID
        self.assertNotEqual(a, backbone.assign_document_uuid("e123456", "pm"))
        # different dossier -> different UUID
        self.assertNotEqual(a, backbone.assign_document_uuid("e999999", "cl"))
        # well-formed UUID
        import uuid as _uuid
        self.assertEqual(str(_uuid.UUID(a)), a)

    def test_uuid_retained_across_sequences(self):
        # The same document shipped in two different sequences keeps one UUID.
        s0 = backbone.ContentModel("e123456", "0000")
        d0 = s0.add_document("cl", "1.0", "m1/ca/cl.pdf", content="x")
        s1 = backbone.ContentModel("e123456", "0001")
        d1 = s1.add_document("cl", "1.0", "m1/ca/cl.pdf", content="x")
        self.assertEqual(d0["uuid"], d1["uuid"])

    def test_active_version_is_v322_and_adopted(self):
        versions = {v["version"]: v for v in backbone.list_backbone_versions()}
        self.assertEqual(backbone.ACTIVE_BACKBONE_VERSION, "3.2.2")
        self.assertTrue(versions["3.2.2"]["active"])
        self.assertTrue(versions["3.2.2"]["adopted"])
        self.assertTrue(versions["3.2.2"]["fixed_by_hc"])

    def test_v40_is_not_hc_fixed_or_active(self):
        # REQ-041 caveat: v4.0 dates are industry ESTIMATES, never HC-fixed.
        versions = {v["version"]: v for v in backbone.list_backbone_versions()}
        self.assertFalse(versions["4.0"]["fixed_by_hc"])
        self.assertFalse(versions["4.0"]["adopted"])
        self.assertFalse(versions["4.0"]["active"])
        self.assertTrue(backbone.ADOPTION_ROADMAP["estimate"])
        self.assertFalse(backbone.ADOPTION_ROADMAP["hc_fixed"])

    def test_v322_emits_both_validated_backbones(self):
        out = backbone.get_generator("3.2.2").emit(self._model())
        self.assertEqual(out["version"], "3.2.2")
        self.assertIn("index.xml", out["artifacts"])
        self.assertIn("ca-regional.xml", out["artifacts"])
        self.assertTrue(out["document_uuids"]["cl"])

    def test_same_content_model_emits_v40_message(self):
        # REQ-041: the SAME content model emits the HL7-RPS v4.0 message with no
        # content re-authoring; UUIDs become the document identity.
        out = backbone.get_generator("4.0").emit(self._model())
        self.assertEqual(out["version"], "4.0")
        msg = out["artifacts"]["rps-message.xml"]
        self.assertIn("submissionUnit", msg)
        self.assertIn(out["document_uuids"]["cl"], msg)

    def test_unknown_version_raises(self):
        with self.assertRaises(backbone.UnknownBackboneVersionError):
            backbone.get_generator("9.9")

    def test_generate_backbone_is_byte_deterministic(self):
        req = {"dossier_id": "e123456", "sequence": "0000",
               "documents": [{"document_id": "cl", "heading": "1.0",
                              "href": "m1/ca/cl.pdf", "content": "bytes"}]}
        a = backbone.generate_backbone(req)["artifacts"]
        b = backbone.generate_backbone(req)["artifacts"]
        self.assertEqual(a, b)


class BackboneApiTests(unittest.TestCase):
    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                         server.make_handler(self.store))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.store.close()

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

    def _req(self, **over):
        data = {"dossier_id": "e123456", "sequence": "0000",
                "documents": [{"document_id": "cl", "heading": "1.0",
                               "href": "m1/ca/10-cover-letter/cl.pdf",
                               "content": "cover bytes"}]}
        data.update(over)
        return data

    def test_versions_endpoint_lists_generators(self):
        status, data = self._get("/api/backbone/versions")
        self.assertEqual(status, 200)
        self.assertEqual(data["active"], "3.2.2")
        self.assertEqual({v["version"] for v in data["versions"]},
                         {"3.2.2", "4.0"})
        self.assertFalse(data["adoption_roadmap"]["hc_fixed"])

    def test_generate_default_emits_v322_backbones(self):
        status, data = self._post("/api/backbone/generate", self._req())
        self.assertEqual(status, 201)
        self.assertTrue(data["valid"])
        self.assertEqual(data["version"], "3.2.2")
        self.assertIn("index.xml", data["artifacts"])
        self.assertIn("ca-regional.xml", data["artifacts"])
        self.assertTrue(data["document_uuids"]["cl"])

    def test_generate_v40_from_same_request(self):
        status, data = self._post("/api/backbone/generate",
                                  self._req(version="4.0"))
        self.assertEqual(status, 201)
        self.assertEqual(data["version"], "4.0")
        self.assertIn("rps-message.xml", data["artifacts"])

    def test_generate_unknown_version_422(self):
        status, data = self._post("/api/backbone/generate",
                                  self._req(version="9.9"))
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])
        self.assertIn("9.9", data["error"])


# ---------------------------------------------------------------------------
# Disaster recovery / business continuity (REQ-055)
# ---------------------------------------------------------------------------

def _snapshot(**over):
    snap = {c: [{"id": c}] for c in dr.PROTECTED_CONTENT_CLASSES}
    snap.update(over)
    return snap


class DrDomainTests(unittest.TestCase):
    def test_policy_reports_rpo_rto_and_classes(self):
        pol = dr.dr_policy()
        self.assertEqual(pol["rpo_minutes"], dr.RPO_MINUTES)
        self.assertEqual(pol["rto_minutes"], dr.RTO_MINUTES)
        self.assertEqual(set(pol["protected_content_classes"]),
                         set(dr.PROTECTED_CONTENT_CLASSES))
        self.assertTrue(pol["encrypted_at_rest"])

    def test_policy_residency_basis_is_value_add(self):
        # REQ-055: in-Canada residency is value-add, not an HC mandate.
        pol = dr.dr_policy(require_in_canada=True, region="ca-central-1")
        self.assertTrue(pol["residency"]["require_in_canada"])
        self.assertTrue(pol["residency"]["in_canada"])
        self.assertIn("not an HC mandate", pol["residency"]["basis"])
        self.assertFalse(
            dr.dr_policy(region="us-east-1")["residency"]["in_canada"])

    def test_backup_restore_roundtrip_preserves_all_classes(self):
        snap = _snapshot()
        backup = dr.make_backup(snap, at="2026-06-24T00:00:00Z")
        self.assertTrue(backup["encrypted_at_rest"])
        restored = dr.restore(backup)
        self.assertEqual(restored, snap)

    def test_restore_detects_corruption(self):
        backup = dr.make_backup(_snapshot(), at="t")
        backup["payload"]["sequences"] = [{"id": "tampered"}]
        with self.assertRaises(dr.IntegrityError):
            dr.restore(backup)

    def test_backup_blocks_incomplete_snapshot(self):
        with self.assertRaises(ValueError):
            dr.make_backup({"sequences": []}, at="t")

    def test_residency_pin_blocks_out_of_country_region(self):
        with self.assertRaises(dr.ResidencyError):
            dr.make_backup(_snapshot(), at="t", region="us-east-1",
                           require_in_canada=True)

    def test_unknown_region_rejected(self):
        with self.assertRaises(ValueError):
            dr.make_backup(_snapshot(), at="t", region="mars-1")

    def test_dr_test_passes_and_verifies_each_class(self):
        result = dr.run_dr_test(_snapshot(), at="2026-06-24T00:00:00Z")
        self.assertEqual(result["outcome"], "PASS")
        self.assertTrue(result["verified"])
        for cls in dr.PROTECTED_CONTENT_CLASSES:
            self.assertTrue(result["per_class_verified"][cls])


class DrApiTests(unittest.TestCase):
    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                         server.make_handler(self.store))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.store.close()

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

    def test_policy_endpoint(self):
        status, data = self._get("/api/dr/policy")
        self.assertEqual(status, 200)
        self.assertEqual(data["rpo_minutes"], dr.RPO_MINUTES)
        self.assertTrue(data["residency"]["in_canada"])  # default ca region

    def test_policy_endpoint_residency_flag(self):
        status, data = self._get(
            "/api/dr/policy?region=us-east-1&require_in_canada=1")
        self.assertEqual(status, 200)
        self.assertTrue(data["residency"]["require_in_canada"])
        self.assertFalse(data["residency"]["in_canada"])

    def test_backup_endpoint_roundtrips(self):
        status, data = self._post("/api/dr/backup",
                                  {"snapshot": _snapshot(),
                                   "at": "2026-06-24T00:00:00Z"})
        self.assertEqual(status, 201)
        self.assertTrue(data["valid"])
        self.assertTrue(data["backup"]["encrypted_at_rest"])
        self.assertEqual(len(data["backup"]["checksum"]), 64)

    def test_backup_endpoint_residency_block_422(self):
        status, data = self._post("/api/dr/backup",
                                  {"snapshot": _snapshot(), "at": "t",
                                   "region": "us-east-1",
                                   "require_in_canada": True})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])
        self.assertEqual(data["rule"], "residency")

    def test_backup_endpoint_incomplete_snapshot_422(self):
        status, data = self._post("/api/dr/backup",
                                  {"snapshot": {"sequences": []}, "at": "t"})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])

    def test_dr_test_endpoint_passes(self):
        status, data = self._post("/api/dr/test",
                                  {"snapshot": _snapshot(),
                                   "at": "2026-06-24T00:00:00Z"})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertEqual(data["result"]["outcome"], "PASS")


# ---------------------------------------------------------------------------
# Content model — submission-type router + ANDS module gating (REQ-004)
# ---------------------------------------------------------------------------

class SubmissionTypeRouterTests(unittest.TestCase):
    def test_all_router_options_present(self):
        codes = {o["code"] for o in content_model.submission_type_options()}
        self.assertEqual(codes, {"NDS", "ANDS", "SNDS", "SANDS", "DIN"})

    def test_is_valid_submission_type(self):
        self.assertTrue(content_model.is_valid_submission_type("ANDS"))
        self.assertTrue(content_model.is_valid_submission_type("ands"))  # case
        for bad in ("", "  ", "XYZ", None):
            self.assertFalse(content_model.is_valid_submission_type(bad))

    def test_route_unknown_type_is_invalid(self):
        res = content_model.route_submission_type({"submission_type": "XYZ"})
        self.assertFalse(res["valid"])
        self.assertIn("not a recognised", res["error"])

    def test_route_ands_configures_content_model(self):
        res = content_model.route_submission_type({"submission_type": "ANDS"})
        self.assertTrue(res["valid"])
        self.assertTrue(res["ands_content_model"])
        cm = res["content_model"]
        mods = {m["module"]: m for m in cm["modules"]}
        # Module 4 not required; 3 and 5 required; 2.3 required.
        self.assertFalse(cm["module4_required"])
        self.assertFalse(mods["4"]["required"])
        self.assertTrue(mods["3"]["required"])
        self.assertTrue(mods["5"]["required"])
        self.assertTrue(mods["2.3"]["required"])

    def test_route_nds_has_no_ands_content_model(self):
        res = content_model.route_submission_type({"submission_type": "NDS"})
        self.assertTrue(res["valid"])
        self.assertFalse(res["ands_content_model"])
        self.assertNotIn("content_model", res)

    def test_cs_be_only_suppresses_2_4_through_2_7(self):
        cm = content_model.ands_content_model(cs_be_only=True)
        mods = {m["module"]: m for m in cm["modules"]}
        for sup in ("2.4", "2.5", "2.6", "2.7"):
            self.assertTrue(mods[sup]["suppressed"],
                            f"{sup} must be suppressed on CS-BE path")
            self.assertFalse(mods[sup]["required"])
            self.assertFalse(mods[sup]["applicable"])
        # 2.3 QOS stays required even on the CS-BE path.
        self.assertTrue(mods["2.3"]["required"])
        self.assertFalse(mods["2.3"]["suppressed"])

    def test_non_cs_be_path_leaves_2_4_2_7_applicable_not_required(self):
        cm = content_model.ands_content_model(cs_be_only=False)
        mods = {m["module"]: m for m in cm["modules"]}
        for sec in ("2.4", "2.5", "2.6", "2.7"):
            self.assertFalse(mods[sec]["suppressed"])
            self.assertTrue(mods[sec]["applicable"])

    def test_new_indication_beyond_crp_advisory(self):
        res = content_model.route_submission_type(
            {"submission_type": "ANDS", "new_indication": True})
        rules = {a["rule"] for a in res["advisories"]}
        self.assertIn("ands_not_for_new_indication", rules)


# ---------------------------------------------------------------------------
# Content model — per-section required-document checklist gate (REQ-044)
# ---------------------------------------------------------------------------

class ChecklistGateTests(unittest.TestCase):
    def test_required_documents_includes_qos_and_be_report(self):
        keys = {d["key"] for d in content_model.required_documents()}
        self.assertIn("qos-ce", keys)
        self.assertIn("be-study-report", keys)
        # 2.3 QOS-CE requires the .docx alongside the PDF.
        qos_doc = next(d for d in content_model.required_documents()
                       if d["key"] == "qos-ce")
        self.assertEqual(set(qos_doc["formats"]), {"pdf", "docx"})

    def test_cs_be_copy_required_only_on_cs_be_path(self):
        off = {d["key"] for d in content_model.required_documents(False)}
        on = {d["key"] for d in content_model.required_documents(True)}
        self.assertNotIn("cs-be-copy", off)
        self.assertIn("cs-be-copy", on)

    def test_cover_letter_auto_satisfied_by_portal(self):
        # Supply the .docx+pdf QOS and the CMC + BE report; cover letter is
        # satisfied automatically by the portal-generated document.
        res = content_model.checklist_gate({
            "present_documents": {
                "qos-ce": ["pdf", "docx"],
                "cmc-body": ["pdf"],
                "be-study-report": ["pdf"],
            }})
        self.assertTrue(res["can_pass"], res["missing"])
        sources = {s["key"]: s["source"] for s in res["satisfied"]}
        self.assertEqual(sources["cover-letter"], "portal-generated")

    def test_missing_qos_blocks_with_section_mapping(self):
        res = content_model.checklist_gate({
            "present_documents": {"cmc-body": ["pdf"],
                                  "be-study-report": ["pdf"]}})
        self.assertFalse(res["can_pass"])
        miss = {m["key"]: m for m in res["missing"]}
        self.assertIn("qos-ce", miss)
        self.assertEqual(miss["qos-ce"]["section"], "2.3")

    def test_missing_docx_format_flagged(self):
        # PDF supplied but the required .docx alongside is absent.
        res = content_model.checklist_gate({
            "present_documents": {"qos-ce": ["pdf"], "cmc-body": ["pdf"],
                                  "be-study-report": ["pdf"]}})
        self.assertFalse(res["can_pass"])
        miss = {m["key"]: m for m in res["missing"]}
        self.assertIn("qos-ce", miss)
        self.assertEqual(miss["qos-ce"]["rule"], "missing_required_format")
        self.assertIn("docx", miss["qos-ce"]["missing_formats"])

    def test_cover_letter_not_generated_must_be_supplied(self):
        res = content_model.checklist_gate({
            "cover_letter_generated": False,
            "present_documents": {"qos-ce": ["pdf", "docx"],
                                  "cmc-body": ["pdf"],
                                  "be-study-report": ["pdf"]}})
        self.assertFalse(res["can_pass"])
        self.assertIn("cover-letter", {m["key"] for m in res["missing"]})


# ---------------------------------------------------------------------------
# E-signature — QA review, signing manifest, tamper detection (REQ-039/053/068)
# ---------------------------------------------------------------------------

class EsignDomainTests(unittest.TestCase):
    def test_policy_anchored_to_hpfb_case_by_case(self):
        p = esign.policy()
        self.assertEqual(p["acceptance"], "case-by-case")
        self.assertEqual(p["basis"], "value-add")
        self.assertIn("hc.cesg", p["request_contact"])

    def test_qa_review_requires_role_and_audit_flag(self):
        bad = esign.qa_review({"reviewer": "Pat", "role": "authorized_signer",
                               "audit_trail_reviewed": True})
        self.assertFalse(bad["valid"])
        self.assertIn("role_not_permitted", {e["rule"] for e in bad["errors"]})
        bad2 = esign.qa_review({"reviewer": "Pat", "audit_trail_reviewed": False})
        self.assertIn("audit_trail_not_reviewed",
                      {e["rule"] for e in bad2["errors"]})

    def test_qa_review_happy_path(self):
        ok = esign.qa_review({"reviewer": "Pat", "audit_trail_reviewed": True,
                              "at": "2026-06-24T00:00:00Z"})
        self.assertTrue(ok["valid"])
        self.assertTrue(ok["review"]["audit_trail_reviewed"])

    def test_sign_requires_role_auth_and_artifacts(self):
        res = esign.sign({"signer": "Dana", "role": "qa_reviewer",
                          "artifacts": []})
        rules = {e["rule"] for e in res["errors"]}
        self.assertIn("role_not_permitted", rules)
        self.assertIn("auth_method_required", rules)
        self.assertIn("artifacts_required", rules)

    def test_sign_rejects_out_of_vocabulary_meaning(self):
        res = esign.sign({"signer": "Dana", "role": "authorized_signer",
                          "auth_method": "password", "meaning": "blessed",
                          "artifacts": [{"id": "a", "content": "x"}]})
        self.assertIn("meaning_invalid", {e["rule"] for e in res["errors"]})

    def test_sign_binds_checksum_from_content(self):
        res = esign.sign({"signer": "Dana", "role": "authorized_signer",
                          "auth_method": "password", "meaning": "approved",
                          "artifacts": [{"id": "cl-0000", "content": "bytes"}]})
        self.assertTrue(res["valid"])
        m = res["manifest"]
        self.assertEqual(m["artifacts"][0]["checksum"],
                         esign.artifact_checksum("bytes"))
        self.assertTrue(m["immutable"])
        self.assertEqual(len(m["manifest_id"]), 32)

    def test_verify_manifest_detects_modification(self):
        signed = esign.sign({"signer": "Dana", "role": "authorized_signer",
                             "auth_method": "password",
                             "artifacts": [{"id": "a", "content": "v1"}]})
        m = signed["manifest"]
        clean = esign.verify_manifest(m, {"a": esign.artifact_checksum("v1")})
        self.assertTrue(clean["valid"])
        tampered = esign.verify_manifest(m, {"a": esign.artifact_checksum("v2")})
        self.assertTrue(tampered["tampered"])
        self.assertIn("signed_content_modified",
                      {f["rule"] for f in tampered["findings"]})

    def test_verify_manifest_detects_missing_artifact(self):
        signed = esign.sign({"signer": "Dana", "role": "authorized_signer",
                             "auth_method": "password",
                             "artifacts": [{"id": "a", "content": "v1"}]})
        gone = esign.verify_manifest(signed["manifest"], {})
        self.assertTrue(gone["tampered"])
        self.assertIn("signed_artifact_missing",
                      {f["rule"] for f in gone["findings"]})

    def test_transmission_gate_blocks_without_review_or_signature(self):
        res = esign.transmission_gate({})
        self.assertFalse(res["can_transmit"])
        rules = {b["rule"] for b in res["blockers"]}
        self.assertIn("qa_review_missing", rules)
        self.assertIn("signature_missing", rules)

    def test_transmission_gate_passes_with_review_and_signature(self):
        review = esign.qa_review({"reviewer": "Pat",
                                  "audit_trail_reviewed": True})["review"]
        manifest = esign.sign({"signer": "Dana", "role": "authorized_signer",
                               "auth_method": "password",
                               "artifacts": [{"id": "a", "content": "v1"}]
                               })["manifest"]
        res = esign.transmission_gate({"review": review, "manifest": manifest})
        self.assertTrue(res["can_transmit"], res["blockers"])

    def test_transmission_gate_reblocks_on_post_sign_tamper(self):
        review = esign.qa_review({"reviewer": "Pat",
                                  "audit_trail_reviewed": True})["review"]
        manifest = esign.sign({"signer": "Dana", "role": "authorized_signer",
                               "auth_method": "password",
                               "artifacts": [{"id": "a", "content": "v1"}]
                               })["manifest"]
        res = esign.transmission_gate({
            "review": review, "manifest": manifest,
            "current": {"a": esign.artifact_checksum("HACKED")}})
        self.assertFalse(res["can_transmit"])
        self.assertTrue(res["tampered"])

    def test_request_and_record_hc_acceptance(self):
        req = esign.request_hc_acceptance(
            {"approach": "PKI smartcard", "org": "Acme"})
        self.assertTrue(req["valid"])
        self.assertEqual(req["request"]["status"], "pending")
        bad = esign.request_hc_acceptance({"approach": ""})
        self.assertFalse(bad["valid"])
        rec = esign.record_hc_acceptance(
            {"approach": "PKI smartcard", "accepted": True, "org": "Acme"})
        self.assertTrue(rec["valid"])
        self.assertTrue(rec["acceptance"]["accepted"])


# ---------------------------------------------------------------------------
# Content-model + e-sign API (end-to-end against a live server)
# ---------------------------------------------------------------------------

class ContentModelAndEsignApiTests(unittest.TestCase):
    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                         server.make_handler(self.store))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.store.close()

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

    # -- REQ-004 ---------------------------------------------------------
    def test_submission_types_endpoint(self):
        status, data = self._get("/api/content-model/submission-types")
        self.assertEqual(status, 200)
        self.assertIn("ANDS",
                      {o["code"] for o in data["submission_types"]})

    def test_route_ands_endpoint(self):
        status, data = self._post("/api/content-model/route",
                                  {"submission_type": "ANDS"})
        self.assertEqual(status, 200)
        self.assertTrue(data["ands_content_model"])
        self.assertIn("content_model", data)

    def test_route_unknown_type_422(self):
        status, data = self._post("/api/content-model/route",
                                  {"submission_type": "ZZZ"})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])

    def test_ands_content_model_cs_be_query(self):
        status, data = self._get("/api/content-model/ands?cs_be_only=1")
        self.assertEqual(status, 200)
        self.assertTrue(data["cs_be_only"])
        mods = {m["module"]: m for m in data["modules"]}
        self.assertTrue(mods["2.7"]["suppressed"])

    def test_checklist_endpoint_lists_cs_be_copy(self):
        status, data = self._get("/api/content-model/checklist?cs_be_only=1")
        self.assertEqual(status, 200)
        self.assertIn("cs-be-copy",
                      {d["key"] for d in data["required_documents"]})

    # -- REQ-044 ---------------------------------------------------------
    def test_checklist_gate_endpoint_pass_and_block(self):
        ok_status, ok = self._post("/api/content-model/checklist-gate", {
            "present_documents": {"qos-ce": ["pdf", "docx"],
                                  "cmc-body": ["pdf"],
                                  "be-study-report": ["pdf"]}})
        self.assertEqual(ok_status, 200)
        self.assertTrue(ok["can_pass"])
        bad_status, bad = self._post("/api/content-model/checklist-gate",
                                     {"present_documents": {}})
        self.assertEqual(bad_status, 422)
        self.assertFalse(bad["can_pass"])

    # -- REQ-039/053/068 -------------------------------------------------
    def test_esign_policy_endpoint(self):
        status, data = self._get("/api/esign/policy")
        self.assertEqual(status, 200)
        self.assertEqual(data["policy"]["acceptance"], "case-by-case")

    def test_esign_sign_returns_201_manifest(self):
        status, data = self._post("/api/esign/sign", {
            "signer": "Dana", "role": "authorized_signer",
            "auth_method": "password", "meaning": "approved",
            "artifacts": [{"id": "cl-0000", "content": "bytes"}]})
        self.assertEqual(status, 201)
        self.assertTrue(data["valid"])
        self.assertEqual(len(data["manifest"]["manifest_id"]), 32)

    def test_esign_sign_invalid_422(self):
        status, data = self._post("/api/esign/sign",
                                  {"signer": "", "artifacts": []})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])

    def test_esign_gate_blocks_then_allows(self):
        # Missing both review + signature -> 409.
        status, data = self._post("/api/esign/gate", {})
        self.assertEqual(status, 409)
        self.assertFalse(data["can_transmit"])
        # With both -> 200.
        _, review = self._post("/api/esign/qa-review",
                               {"reviewer": "Pat",
                                "audit_trail_reviewed": True})
        _, signed = self._post("/api/esign/sign", {
            "signer": "Dana", "role": "authorized_signer",
            "auth_method": "password",
            "artifacts": [{"id": "a", "content": "v1"}]})
        status, data = self._post("/api/esign/gate", {
            "review": review["review"], "manifest": signed["manifest"]})
        self.assertEqual(status, 200)
        self.assertTrue(data["can_transmit"])

    def test_esign_verify_detects_tamper_409(self):
        _, signed = self._post("/api/esign/sign", {
            "signer": "Dana", "role": "authorized_signer",
            "auth_method": "password",
            "artifacts": [{"id": "a", "content": "v1"}]})
        status, data = self._post("/api/esign/verify", {
            "manifest": signed["manifest"],
            "current": {"a": esign.artifact_checksum("HACKED")}})
        self.assertEqual(status, 409)
        self.assertTrue(data["tampered"])


# ---------------------------------------------------------------------------
# Fees, mitigation & annual Right-to-Sell — domain logic (REQ-035/036/037)
# ---------------------------------------------------------------------------

class FeesFiscalYearTests(unittest.TestCase):
    def test_fiscal_year_april_boundary(self):
        # HC fee years run April 1 -> March 31.
        self.assertEqual(fees.fiscal_year("2025-04-01"), "2025-26")
        self.assertEqual(fees.fiscal_year("2026-03-31"), "2025-26")
        self.assertEqual(fees.fiscal_year("2025-03-31"), "2024-25")
        self.assertEqual(fees.fiscal_year("2025-06-30"), "2025-26")

    def test_fiscal_year_effective_date(self):
        self.assertEqual(fees.fiscal_year_effective_date("2025-26"), "2025-04-01")

    def test_blank_date_raises(self):
        with self.assertRaises(ValueError):
            fees.fiscal_year("")


class FeeEscalationTests(unittest.TestCase):
    def test_cpi_basis_applies_fee_plus_a_times_b(self):
        # Fee = A + (A x B); 2% CPI on 70750 -> 72165.
        self.assertEqual(fees.escalate(70750.0, fees.BASIS_CPI, 0.02), 72165.0)

    def test_ministerial_basis_is_fixed_2pct_regardless_of_cpi(self):
        self.assertEqual(
            fees.escalate(2231.0, fees.BASIS_MINISTERIAL_2PCT, 0.10), 2275.62)

    def test_unknown_basis_raises(self):
        with self.assertRaises(ValueError):
            fees.escalate(100.0, "bogus")


class AndsFeeTests(unittest.TestCase):
    def test_ands_resolves_to_comparative_studies_grouping(self):
        res = fees.resolve_ands_fee("2025-06-30")
        self.assertEqual(res["grouping"], "comparative-studies")
        self.assertEqual(res["label"], "Comparative studies")
        self.assertEqual(res["basis"], fees.BASIS_CPI)

    def test_current_fy2025_26_amount_is_70750(self):
        res = fees.resolve_ands_fee("2025-06-30")
        self.assertEqual(res["amount"], 70750.0)
        self.assertEqual(res["amount_fiscal_year"], "2025-26")
        self.assertEqual(res["effective_date"], "2025-04-01")

    def test_fy2026_27_amount_is_71953(self):
        res = fees.resolve_ands_fee("2026-05-01")
        self.assertEqual(res["amount"], 71953.0)
        self.assertEqual(res["amount_fiscal_year"], "2026-27")

    def test_never_returns_historical_anchor_seed(self):
        # $53,836 is a CPI-anchor seed only and must never surface as current.
        for d in ("2025-06-30", "2026-05-01", "2030-01-01"):
            res = fees.resolve_ands_fee(d)
            self.assertNotEqual(res["amount"], 53836.0)
            self.assertEqual(res["anchor_seed_excluded"], 53836.0)

    def test_future_year_falls_back_to_latest_published(self):
        res = fees.resolve_ands_fee("2030-01-01")
        self.assertEqual(res["amount_fiscal_year"], "2026-27")
        self.assertEqual(res["amount"], 71953.0)

    def test_unknown_grouping_raises(self):
        with self.assertRaises(ValueError):
            fees.resolve_fee("not-a-grouping", "2025-06-30")


class FeeMitigationTests(unittest.TestCase):
    def test_small_business_first_submission_is_100pct_remission(self):
        res = fees.evaluate_fee_mitigation(
            {"fee": 70750.0, "small_business": True, "first_submission": True})
        self.assertEqual(res["remission_rate"], 1.0)
        self.assertEqual(res["net_fee"], 0.0)
        self.assertEqual(res["invoice_status"], fees.INVOICE_REMITTED)
        self.assertFalse(res["requires_attestation"])

    def test_subsequent_ands_50pct_requires_attestation(self):
        # Without the attestation upload the 50% claim is gated (not applied).
        res = fees.evaluate_fee_mitigation(
            {"fee": 70750.0, "small_business": True, "first_submission": False,
             "attestation_uploaded": False})
        self.assertEqual(res["remission_rate"], 0.0)
        self.assertTrue(res["requires_attestation"])
        self.assertEqual(res["net_fee"], 70750.0)

    def test_subsequent_ands_50pct_applied_with_attestation(self):
        res = fees.evaluate_fee_mitigation(
            {"fee": 70750.0, "small_business": True, "first_submission": False,
             "attestation_uploaded": True})
        self.assertEqual(res["remission_rate"], 0.5)
        self.assertEqual(res["net_fee"], 35375.0)
        self.assertFalse(res["requires_attestation"])

    def test_deferral_until_noc(self):
        res = fees.evaluate_fee_mitigation(
            {"fee": 70750.0, "small_business": False, "defer_until_noc": True})
        self.assertTrue(res["deferred"])
        self.assertEqual(res["invoice_status"], fees.INVOICE_DEFERRED)

    def test_no_small_business_pays_full_fee(self):
        res = fees.evaluate_fee_mitigation(
            {"fee": 70750.0, "small_business": False})
        self.assertEqual(res["remission_rate"], 0.0)
        self.assertEqual(res["net_fee"], 70750.0)
        self.assertEqual(res["invoice_status"], fees.INVOICE_PENDING)


class RightToSellTests(unittest.TestCase):
    def test_amount_varies_by_drug_type(self):
        self.assertEqual(
            fees.resolve_right_to_sell("prescription", "2025-06-30")["amount"],
            5531.0)
        self.assertEqual(
            fees.resolve_right_to_sell("non-prescription", "2025-06-30")["amount"],
            3334.0)
        self.assertEqual(
            fees.resolve_right_to_sell("disinfectant", "2025-06-30")["amount"],
            1730.0)
        self.assertEqual(
            fees.resolve_right_to_sell("biocide", "2025-06-30")["amount"], 1535.0)

    def test_statutory_due_date_is_october_1(self):
        rec = fees.resolve_right_to_sell("prescription", "2025-06-30")
        self.assertEqual(rec["due_date"], "2025-10-01")

    def test_unknown_drug_type_raises(self):
        with self.assertRaises(ValueError):
            fees.resolve_right_to_sell("vitamins", "2025-06-30")

    def test_outstanding_and_reminder_within_60_days(self):
        # 2025-08-15 is within 60 days of the Oct 1 due date.
        rec = fees.right_to_sell_status("prescription", "2025-08-15", paid=False)
        self.assertTrue(rec["outstanding_balance"])
        self.assertTrue(rec["reminder_due"])
        self.assertFalse(rec["overdue"])

    def test_paid_clears_outstanding_flags(self):
        rec = fees.right_to_sell_status("prescription", "2025-08-15", paid=True)
        self.assertFalse(rec["outstanding_balance"])
        self.assertFalse(rec["reminder_due"])
        self.assertFalse(rec["overdue"])

    def test_overdue_after_due_date(self):
        rec = fees.right_to_sell_status("prescription", "2025-11-01", paid=False)
        self.assertTrue(rec["overdue"])
        self.assertTrue(rec["outstanding_balance"])


# ---------------------------------------------------------------------------
# Fees API (end-to-end against a live server) — REQ-035/036/037
# ---------------------------------------------------------------------------

class FeesApiTests(unittest.TestCase):
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

    def test_reference_endpoint_exposes_groupings_and_drug_types(self):
        status, data = self._get("/api/fees/reference")
        self.assertEqual(status, 200)
        self.assertEqual(data["ands_grouping"], "comparative-studies")
        self.assertEqual(data["anchor_seed_excluded"], 53836.0)
        keys = {g["key"] for g in data["groupings"]}
        self.assertIn("comparative-studies", keys)
        drug_types = {t["key"] for t in data["drug_types"]}
        self.assertEqual(drug_types,
                         {"prescription", "non-prescription",
                          "disinfectant", "biocide"})

    def test_ands_fee_endpoint_returns_current_amount(self):
        status, data = self._post("/api/fees/ands",
                                  {"submission_date": "2025-06-30"})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertEqual(data["amount"], 70750.0)
        self.assertNotEqual(data["amount"], 53836.0)

    def test_ands_fee_endpoint_422_on_bad_date(self):
        status, data = self._post("/api/fees/ands", {"submission_date": ""})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])

    def test_mitigation_endpoint_first_submission_full_remission(self):
        status, data = self._post("/api/fees/mitigation", {
            "fee": 70750.0, "small_business": True, "first_submission": True})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertEqual(data["remission_rate"], 1.0)
        self.assertEqual(data["net_fee"], 0.0)

    def test_mitigation_endpoint_subsequent_requires_attestation(self):
        status, data = self._post("/api/fees/mitigation", {
            "fee": 70750.0, "small_business": True, "first_submission": False})
        self.assertEqual(status, 200)
        self.assertTrue(data["requires_attestation"])

    def test_mitigation_endpoint_422_on_non_numeric_fee(self):
        status, data = self._post("/api/fees/mitigation",
                                  {"fee": "not-a-number"})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])

    def test_right_to_sell_endpoint_returns_type_amount_and_due_date(self):
        status, data = self._post("/api/fees/right-to-sell", {
            "drug_type": "prescription", "as_of": "2025-08-15", "paid": False})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertEqual(data["amount"], 5531.0)
        self.assertEqual(data["due_date"], "2025-10-01")
        self.assertTrue(data["outstanding_balance"])

    def test_right_to_sell_endpoint_422_on_unknown_type(self):
        status, data = self._post("/api/fees/right-to-sell",
                                  {"drug_type": "vitamins", "as_of": "2025-08-15"})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])

    def test_index_serves_fee_panel_and_handlers(self):
        with urllib.request.urlopen(self._url("/")) as resp:
            page = resp.read().decode()
        self.assertIn("Right-to-Sell", page)
        self.assertIn("function feeAnds(", page)
        self.assertIn("function feeMitigation(", page)
        self.assertIn("function feeRightToSell(", page)
        # User-controlled fee responses must be HTML-escaped (stored-XSS guard).
        self.assertIn("esc(d.error", page)


# ---------------------------------------------------------------------------
# REQ-002 — Dossier-ID request workflow + 8-week MAXIMUM lead-time rule.
# Closes CORRECTION C02 ('Dossier ID 8-week rule direction' — a MAXIMUM, warn
# when too early, never gate) and GAP G11 (product-type/activity request
# branches incl. clinical-trial + Master File; existing-dossier reuse; DSTS-IA).
# ---------------------------------------------------------------------------

class DossierIdRequestTests(unittest.TestCase):
    def test_branch_catalog_covers_all_product_types(self):
        branches = rep.DOSSIER_REQUEST_BRANCHES
        for key in ("pharmaceutical", "pharmaceutical-clinical-trial",
                    "biologic-clinical-trial", "veterinary", "biocide",
                    "medical-device", "master-file-ectd",
                    "master-file-non-ectd"):
            with self.subTest(branch=key):
                self.assertIn(key, branches)
        # Medical device uses the 'm' convention; pharma/biologic use 'e'.
        self.assertEqual(branches["medical-device"]["prefix"], "m")
        self.assertEqual(branches["pharmaceutical"]["prefix"], "e")
        # Master File: e+6 (eCTD) vs f+7 (non-eCTD).
        self.assertEqual(branches["master-file-ectd"]["prefix"], "e")
        self.assertEqual(branches["master-file-non-ectd"]["prefix"], "f")

    def test_eight_week_rule_is_a_maximum_warns_when_too_early(self):
        # Requested 12 weeks (84 days) before filing — MORE than the 8-week max.
        lead = rep.assess_dossier_id_lead_time("2026-01-01", "2026-03-26")
        self.assertEqual(lead["days_ahead"], 84)
        self.assertTrue(lead["too_early"])
        self.assertIsNotNone(lead["warning"])
        self.assertIn("8", lead["warning"])

    def test_within_eight_weeks_is_not_flagged(self):
        # 4 weeks ahead — well within the maximum; no warning, never gated.
        lead = rep.assess_dossier_id_lead_time("2026-03-01", "2026-03-29")
        self.assertFalse(lead["too_early"])
        self.assertIsNone(lead["warning"])

    def test_exactly_eight_weeks_is_not_too_early(self):
        # 56 days == the maximum; only MORE than 8 weeks is too early.
        lead = rep.assess_dossier_id_lead_time("2026-01-01", "2026-02-26")
        self.assertEqual(lead["days_ahead"], 56)
        self.assertFalse(lead["too_early"])

    def test_request_is_warn_only_never_a_gate(self):
        # Even when too early, the request stays VALID (warn-only, not a gate).
        res = rep.request_dossier_id({
            "branch": "pharmaceutical",
            "request_date": "2026-01-01",
            "intended_first_filing_date": "2026-06-01"})
        self.assertTrue(res["valid"])
        self.assertEqual(res["request"]["status"], "pending")
        self.assertTrue(res["request"]["warnings"])

    def test_unknown_branch_rejected(self):
        res = rep.request_dossier_id({"branch": "nope"})
        self.assertFalse(res["valid"])
        self.assertIn("branch_unknown", {e["rule"] for e in res["errors"]})

    def test_reuse_existing_dossier_skips_request(self):
        res = rep.resolve_dossier_id({
            "branch": "pharmaceutical", "existing_dossier_id": "e123456"})
        self.assertEqual(res["action"], "reuse")
        self.assertEqual(res["dossier_id"], "e123456")
        self.assertFalse(res["new_request_required"])
        self.assertIn("@", res["dsts_ia_lookup"])  # DSTS-IA lookup offered

    def test_resolve_opens_request_when_no_existing_id(self):
        res = rep.resolve_dossier_id({
            "branch": "veterinary", "request_date": "2026-01-01",
            "intended_first_filing_date": "2099-01-01"})
        self.assertEqual(res["action"], "request")
        self.assertTrue(res["new_request_required"])
        self.assertEqual(res["request"]["status"], "pending")

    def test_master_file_formats_round_trip(self):
        self.assertEqual(rep.resolve_dossier_id({
            "branch": "master-file-non-ectd",
            "existing_dossier_id": "f1234567"})["action"], "reuse")
        self.assertEqual(rep.resolve_dossier_id({
            "branch": "master-file-ectd",
            "existing_dossier_id": "e123456"})["action"], "reuse")

    def test_master_file_ectd_rejects_seven_digit_reuse(self):
        # AC REQ-002: eCTD Master File is e+6 EXACTLY; a 7-digit e-ID is
        # non-conformant and must NOT be reused (falls through to a request).
        res = rep.resolve_dossier_id({
            "branch": "master-file-ectd", "existing_dossier_id": "e1234567"})
        self.assertEqual(res["action"], "request")
        self.assertTrue(res["new_request_required"])

    def test_master_file_non_ectd_rejects_six_digit_reuse(self):
        # AC REQ-002: non-eCTD Master File is f+7 EXACTLY; a 6-digit f-ID is
        # non-conformant and must NOT be reused.
        res = rep.resolve_dossier_id({
            "branch": "master-file-non-ectd", "existing_dossier_id": "f123456"})
        self.assertEqual(res["action"], "request")

    def test_assignment_enforces_master_file_digit_count(self):
        req = rep.request_dossier_id({"branch": "master-file-ectd"})["request"]
        # 7 digits when the branch accepts only 6 -> rejected, stays pending.
        bad = rep.record_dossier_id_assignment(req, "e1234567")
        self.assertFalse(bad["valid"])
        self.assertEqual(bad["request"]["status"], "pending")
        # the correct e+6 form is accepted.
        ok = rep.record_dossier_id_assignment(req, "e123456")
        self.assertTrue(ok["valid"])
        self.assertEqual(ok["request"]["status"], "assigned")

    def test_master_file_non_ectd_assignment_rejects_e_prefix(self):
        # Cross-branch: f+7 branch must reject an e-prefixed ID (prefix guard).
        req = rep.request_dossier_id(
            {"branch": "master-file-non-ectd"})["request"]
        out = rep.record_dossier_id_assignment(req, "e123456")
        self.assertFalse(out["valid"])
        self.assertEqual(out["request"]["status"], "pending")

    def test_negative_lead_time_not_flagged(self):
        # Request placed AFTER the intended filing date -> never gated/warned.
        lead = rep.assess_dossier_id_lead_time("2026-04-01", "2026-03-01")
        self.assertLess(lead["days_ahead"], 0)
        self.assertFalse(lead["too_early"])
        self.assertIsNone(lead["warning"])

    def test_unparseable_dates_not_assessable_and_never_gate(self):
        lead = rep.assess_dossier_id_lead_time("2026-13-45", "2026-03-01")
        self.assertFalse(lead["assessable"])
        self.assertFalse(lead["too_early"])
        self.assertIsNone(lead["warning"])

    def test_assignment_transitions_pending_to_assigned(self):
        req = rep.request_dossier_id({"branch": "pharmaceutical"})["request"]
        out = rep.record_dossier_id_assignment(req, "e7654321")
        self.assertTrue(out["valid"])
        self.assertEqual(out["request"]["status"], "assigned")
        self.assertEqual(out["request"]["assigned_dossier_id"], "e7654321")

    def test_assignment_rejects_wrong_format(self):
        req = rep.request_dossier_id({"branch": "pharmaceutical"})["request"]
        out = rep.record_dossier_id_assignment(req, "m123456")  # wrong prefix
        self.assertFalse(out["valid"])
        self.assertEqual(out["request"]["status"], "pending")


class DossierIdRequestApiTests(unittest.TestCase):
    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                         server.make_handler(self.store))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.store.close()

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

    def test_branches_endpoint(self):
        status, data = self._get("/api/rep/dossier-id/branches")
        self.assertEqual(status, 200)
        keys = {b["key"] for b in data["branches"]}
        self.assertIn("master-file-non-ectd", keys)
        self.assertIn("pharmaceutical-clinical-trial", keys)
        self.assertEqual(data["max_lead_weeks"], 8)

    def test_request_too_early_warns_but_is_not_gated(self):
        status, data = self._post("/api/rep/dossier-id/request", {
            "branch": "pharmaceutical", "request_date": "2026-01-01",
            "intended_first_filing_date": "2026-06-01"})
        self.assertEqual(status, 200)   # warn-only, NOT 422
        self.assertTrue(data["valid"])
        self.assertEqual(data["action"], "request")
        self.assertTrue(data["request"]["warnings"])

    def test_request_within_window_no_warning(self):
        status, data = self._post("/api/rep/dossier-id/request", {
            "branch": "pharmaceutical", "request_date": "2026-03-01",
            "intended_first_filing_date": "2026-03-29"})
        self.assertEqual(status, 200)
        self.assertFalse(data["request"]["warnings"])

    def test_request_unparseable_dates_not_gated(self):
        # Malformed dates must never gate the request (warn-only invariant).
        status, data = self._post("/api/rep/dossier-id/request", {
            "branch": "pharmaceutical", "request_date": "bad-date",
            "intended_first_filing_date": "2026-03-01"})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertFalse(data["request"]["warnings"])

    def test_request_reuse_existing(self):
        status, data = self._post("/api/rep/dossier-id/request", {
            "branch": "pharmaceutical", "existing_dossier_id": "e123456"})
        self.assertEqual(status, 200)
        self.assertEqual(data["action"], "reuse")
        self.assertEqual(data["dossier_id"], "e123456")

    def test_request_unknown_branch_422(self):
        status, data = self._post("/api/rep/dossier-id/request",
                                  {"branch": "nope"})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])

    def test_assign_endpoint(self):
        _, opened = self._post("/api/rep/dossier-id/request",
                               {"branch": "pharmaceutical"})
        status, data = self._post("/api/rep/dossier-id/assign", {
            "request": opened["request"], "assigned_dossier_id": "e7654321"})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertEqual(data["request"]["status"], "assigned")


# ---------------------------------------------------------------------------
# NFR-005 — Privacy: PIPEDA baseline + configurable provincial overlay.
# Closes CORRECTION C15 / GAP G28 (PIPEDA is the baseline, with AB/BC/QC PIPA
# and Ontario PHIPA overlays where activity is intra-provincial or PHI is
# handled; consent + data-subject access/correction; REQ-067 basis tagging).
# ---------------------------------------------------------------------------

class PrivacyDomainTests(unittest.TestCase):
    def test_pipeda_is_the_baseline_no_overlay(self):
        pol = privacy.privacy_policy()
        self.assertEqual(pol["baseline"]["regime"], "PIPEDA")
        self.assertFalse(pol["overlay_applies"])
        self.assertEqual(pol["effective_regimes"], ["PIPEDA"])
        self.assertFalse(pol["hc_mandated"])

    def test_provincial_overlay_applies_for_phi(self):
        pol = privacy.privacy_policy(province="ON", phi=True)
        self.assertTrue(pol["overlay_applies"])
        self.assertEqual(pol["provincial_overlay"]["province"], "ON")
        self.assertIn("PHIPA", pol["provincial_overlay"]["law"])
        self.assertEqual(pol["provincial_overlay"]["basis"],
                         privacy.BASIS_PROVINCIAL)

    def test_provincial_overlay_applies_intra_provincial(self):
        pol = privacy.privacy_policy(province="AB", intra_provincial=True)
        self.assertTrue(pol["overlay_applies"])
        self.assertIn("Alberta", pol["provincial_overlay"]["law"])

    def test_no_overlay_when_neither_intra_nor_phi(self):
        pol = privacy.privacy_policy(province="BC")
        self.assertFalse(pol["overlay_applies"])
        self.assertIsNone(pol["provincial_overlay"])

    def test_unknown_province_falls_back_to_pipeda(self):
        pol = privacy.privacy_policy(province="ZZ", phi=True)
        self.assertFalse(pol["overlay_applies"])

    def test_basis_vocabulary_matches_req067(self):
        self.assertEqual(
            set(privacy.BASIS_VALUES),
            {"HC-mandate", "GC-direction", "provincial-privacy",
             "PIPEDA", "GMP-best-practice", "value-add"})

    def test_consent_must_be_express(self):
        out = privacy.capture_consent(
            {"subject": "Jane Doe", "purpose": "submission",
             "consent_type": "implied"}, at="2026-06-24T00:00:00Z")
        self.assertFalse(out["valid"])
        self.assertIn("consent_must_be_express",
                      {e["rule"] for e in out["errors"]})

    def test_capture_express_consent_record_is_retained(self):
        out = privacy.capture_consent(
            {"subject": "Jane Doe", "purpose": "ANDS submission",
             "province": "ON", "phi": True}, at="2026-06-24T00:00:00Z")
        self.assertTrue(out["valid"])
        self.assertTrue(out["record"]["retained"])
        self.assertEqual(out["record"]["consent_type"], "express")
        self.assertIn("Ontario PHIPA", out["record"]["regimes"])

    def test_data_subject_access_and_correction(self):
        for kind in ("access", "correction"):
            with self.subTest(kind=kind):
                out = privacy.handle_data_subject_request(
                    {"kind": kind, "subject": "Jane"}, at="t")
                self.assertTrue(out["valid"])
                self.assertEqual(out["request"]["kind"], kind)
                self.assertEqual(out["request"]["status"], "open")

    def test_data_subject_request_bad_kind_rejected(self):
        out = privacy.handle_data_subject_request(
            {"kind": "delete", "subject": "Jane"}, at="t")
        self.assertFalse(out["valid"])


class PrivacyApiTests(unittest.TestCase):
    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0),
                                         server.make_handler(self.store))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.store.close()

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

    def test_policy_default_is_pipeda(self):
        status, data = self._get("/api/privacy/policy")
        self.assertEqual(status, 200)
        self.assertFalse(data["overlay_applies"])
        self.assertEqual(data["baseline"]["regime"], "PIPEDA")

    def test_policy_overlay_for_phi(self):
        status, data = self._get("/api/privacy/policy?province=ON&phi=1")
        self.assertEqual(status, 200)
        self.assertTrue(data["overlay_applies"])
        self.assertIn("PHIPA", data["provincial_overlay"]["law"])

    def test_consent_endpoint_express_201(self):
        status, data = self._post("/api/privacy/consent",
                                  {"subject": "Jane", "purpose": "ANDS"})
        self.assertEqual(status, 201)
        self.assertTrue(data["valid"])
        self.assertTrue(data["record"]["retained"])

    def test_consent_endpoint_implied_422(self):
        status, data = self._post("/api/privacy/consent",
                                  {"subject": "Jane", "purpose": "ANDS",
                                   "consent_type": "implied"})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])

    def test_data_subject_request_endpoint(self):
        status, data = self._post("/api/privacy/data-subject-request",
                                  {"kind": "access", "subject": "Jane"})
        self.assertEqual(status, 201)
        self.assertTrue(data["valid"])

    def test_data_subject_request_bad_kind_422(self):
        status, data = self._post("/api/privacy/data-subject-request",
                                  {"kind": "delete", "subject": "Jane"})
        self.assertEqual(status, 422)


if __name__ == "__main__":
    unittest.main()
