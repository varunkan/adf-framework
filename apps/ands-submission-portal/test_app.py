#!/usr/bin/env python3
"""
Test suite for the ANDS Submission Portal MVP.

Covers the core domain logic (Dossier-ID format, sequence format + lifecycle,
required fields / email / submission type) and the JSON API end-to-end against a
live server bound to a fresh in-memory store.

Run:  python3 -m unittest -v
"""

import json
import os
import re
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer

import backbone
import bioequivalence
import content_model
import cv
import domain
import dr
import ectd
import esign
import fees
import hc_calendar
import journey
import lifecycle
import privacy
import qos
import rbac
import readiness
import rep
import report_ingest
import retention
import server
import navigation
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

    def test_client_esc_also_escapes_quotes(self):
        # Security: esc() values land inside double-quoted style/attribute
        # contexts (e.g. data-* attrs), so esc() must escape both quote chars,
        # not only &<>. A &<>-only escaper lets a " or ' break out (DOM-XSS).
        with urllib.request.urlopen(self._url("/")) as resp:
            page = resp.read().decode()
        self.assertIn("&quot;", page)
        self.assertIn("&#39;", page)
        self.assertIn("/[&<>\"']/g", page)

    def test_inline_fix_button_uses_static_handler_not_interpolated_quotes(self):
        # Security: the one-click-fix button must carry user-controlled fix_id
        # and file path in data-* attributes and call a STATIC onclick handler
        # reading this.dataset — never interpolate them into a single-quoted JS
        # string, where a quote in a filename would break out (DOM-XSS).
        with urllib.request.urlopen(self._url("/")) as resp:
            page = resp.read().decode()
        self.assertIn("onclick=\"valFix(this.dataset.fix, this.dataset.file)\"",
                      page)
        self.assertIn("data-fix=", page)
        self.assertIn("data-file=", page)
        # The old, injectable inline form must be gone.
        self.assertNotIn("valFix(\\'", page)

    def test_every_onclick_handler_is_defined(self):
        # Regression: every JS function referenced from an inline onclick="" in
        # INDEX_HTML must actually be defined in the page <script>, or the button
        # throws an uncaught ReferenceError and the whole journey is dead in the
        # UI (e.g. the DSTS lifecycle, rejection-ingest and calendar cards once
        # shipped with their onclick handlers wired to undefined functions).
        with urllib.request.urlopen(self._url("/")) as resp:
            page = resp.read().decode()
        # Pull the bare function name out of each onclick="fnName(...)".
        called = set(re.findall(r'onclick="([A-Za-z_$][\w$]*)\s*\(', page))
        self.assertTrue(called, "expected onclick handlers in the page")
        missing = []
        for fn in sorted(called):
            # A function is "defined" if the script declares it as a function
            # declaration or assigns it to a name (function/const/let/var).
            if re.search(r'(?:async\s+)?function\s+' + re.escape(fn) + r'\s*\(',
                         page):
                continue
            if re.search(r'(?:const|let|var)\s+' + re.escape(fn) + r'\s*=', page):
                continue
            missing.append(fn)
        self.assertEqual(missing, [],
                         f"onclick handlers with no definition: {missing}")
        # Explicitly assert the previously-dead handlers are now present.
        for fn in ("lcStart", "lcTransition", "lcScreening", "lcClarifax",
                   "lcDecision", "lcServiceStandard", "lcLoad", "rejIngest",
                   "calCompute", "calHolidays"):
            self.assertIn(fn, called, f"{fn} button missing from page")
            self.assertRegex(page, r'function\s+' + fn + r'\s*\(',
                             f"{fn} referenced but not defined")

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

    def test_favicon_served_not_404(self):
        # Regression: the browser's automatic /favicon.ico request must not 404
        # (it dirtied the console as a "Failed to load resource" error). The
        # route serves an inline SVG icon with a 200.
        with urllib.request.urlopen(self._url("/favicon.ico")) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(resp.headers.get("Content-Type"), "image/svg+xml")
            self.assertTrue(resp.read())  # non-empty body

    def test_health_probe_reports_both_servers_ready(self):
        # Client requirement (2026-06-26): the web server and the API server must
        # both be up before the UI is presented. /api/health is the readiness
        # probe the UI polls. It touches the API/DB tier (store.list()), so a 200
        # means BOTH the web listener answered AND the API is genuinely live —
        # not a socket-accept-only false ready that the orphaned-:8000 stale
        # server problem warned about.
        status, data = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["web"])
        self.assertTrue(data["api"])

    def test_ui_gated_on_readiness_until_servers_up(self):
        # The portal must not present (or fire its API loaders) until the
        # readiness probe confirms both servers are up: the page ships a boot
        # gate that polls /api/health and only then reveals the portal and runs
        # the loaders.
        with urllib.request.urlopen(self._url("/")) as resp:
            page = resp.read().decode()
        self.assertIn("/api/health", page)      # the UI polls readiness
        self.assertIn("boot-overlay", page)     # a "starting servers" splash
        self.assertIn("function boot(", page)   # gate runs before the loaders
        # The readiness fetch must precede the loader invocations inside boot().
        idx_health = page.index("/api/health")
        idx_loaders = page.index("loadActivityTypes();")
        self.assertLess(idx_health, idx_loaders,
                        "readiness check must gate the UI loaders")

    def test_add_leaf_guarded_before_dossier_selected(self):
        # Regression: clicking "Add leaf" before a dossier was created/opened
        # fired POST /api/ectd/dossiers/null/leaves (CURRENT_DOSSIER === null),
        # which 404'd. addLeaf() must short-circuit on the null guard BEFORE the
        # /leaves fetch, rendering an inline "create or open a dossier first".
        with urllib.request.urlopen(self._url("/")) as resp:
            page = resp.read().decode()
        idx_guard = page.index("create or open a dossier first")
        idx_fetch = page.index("/leaves'")
        self.assertLess(idx_guard, idx_fetch,
                        "the null-dossier guard must precede the /leaves fetch")
        # Server still 404s a literal 'null' id — the guard is what prevents the
        # doomed request from ever firing (defence in depth).
        try:
            with urllib.request.urlopen(self._url(
                    "/api/ectd/dossiers/null/leaves")) as resp:
                self.fail("expected 404 for a non-existent dossier")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

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

    def test_calendar_holidays_out_of_range_year_422(self):
        # year=0 and year>9999 must return 422, not crash with 500.
        status, _ = self._get("/api/calendar/holidays?start=0")
        self.assertEqual(status, 422)
        status2, _ = self._get("/api/calendar/holidays?start=99999&end=100000")
        self.assertEqual(status2, 422)


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
# Security: every caller-supplied-XML path is hardened against billion-laughs /
# XXE through the shared ``xmlsafe`` guard, not just the validation endpoints.
# ---------------------------------------------------------------------------
class XmlEntityHardeningTests(unittest.TestCase):
    # A classic "billion laughs" internal-entity bomb.
    _LOL = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE ectd-stf ['
        '  <!ENTITY lol "lol">'
        '  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;">'
        ']>'
        '<ectd-stf>&lol2;</ectd-stf>'
    )
    # An external-entity (XXE) file-exfiltration payload.
    _XXE = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE backbone [ <!ENTITY xxe SYSTEM "file:///etc/passwd"> ]>'
        '<ectd>&xxe;</ectd>'
    )

    def test_xmlsafe_rejects_internal_entity_bomb(self):
        import xmlsafe
        with self.assertRaises(xmlsafe.UnsafeXmlError):
            xmlsafe.safe_parse_xml(self._LOL)

    def test_xmlsafe_rejects_external_entity(self):
        import xmlsafe
        with self.assertRaises(xmlsafe.UnsafeXmlError):
            xmlsafe.safe_parse_xml(self._XXE)

    def test_validation_safe_parse_xml_reexports_guard(self):
        # The historical public name keeps working and shares the SAME class.
        import xmlsafe
        self.assertIs(validation.UnsafeXmlError, xmlsafe.UnsafeXmlError)
        with self.assertRaises(validation.UnsafeXmlError):
            validation.safe_parse_xml(self._XXE)

    def test_backbone_validation_rejects_entity_attack(self):
        # ectd.validate_backbone now routes through the guard and converts an
        # entity attack into a clean SchemaValidationError (not a crash / DoS).
        with self.assertRaises(ectd.SchemaValidationError) as ctx:
            ectd.validate_backbone(self._XXE, ectd.ICH_ECTD_DTD)
        self.assertIn("safety", str(ctx.exception).lower())

    def test_stf_validation_flags_entity_attack(self):
        # An STF body posted from an untrusted client is reported as a finding,
        # never parsed by the raw (unhardened) parser.
        findings = stf.validate_stf({"xml": self._LOL})
        self.assertIn("stf_unsafe_xml", {f["rule"] for f in findings})
        self.assertTrue(all(f["category"] == "STF" for f in findings))

    def test_well_formed_xml_still_parses(self):
        # Regression guard: the hardening must NOT break ordinary, entity-free XML.
        import xmlsafe
        dom = xmlsafe.safe_parse_xml('<?xml version="1.0"?><ectd-stf/>')
        self.assertEqual(dom.documentElement.tagName, "ectd-stf")


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

    def test_placeholder_backbones_escape_injected_xml(self):
        # SECURITY: a dossier_id/sequence carrying XML metacharacters must be
        # escaped into the placeholder backbones, never breaking out of the
        # attribute/element to produce malformed or attacker-shaped XML.
        from xml.dom.minidom import parseString
        hostile = {"dossier_id": "e1' onload='x\"><inject>&",
                   "sequence": "00<00", "size_gb": 14.0}
        pkg = transmission.build_media_package(hostile)
        idx = pkg["backbones"]["index.xml"]
        reg = pkg["backbones"]["m1/ca/ca-regional.xml"]
        # No raw injection markers survive into the serialized XML.
        self.assertNotIn("<inject>", idx)
        self.assertNotIn("<inject>", reg)
        # Both backbones remain well-formed and round-trip the real value.
        parseString(idx)
        dom = parseString(reg)
        self.assertEqual(
            dom.getElementsByTagName("dossier-id")[0].firstChild.data,
            hostile["dossier_id"])


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

    def test_monitor_non_numeric_timeout_422(self):
        # mdn_timeout_s / fda_timeout_s must reject non-numeric values with 422,
        # not crash with an unhandled ValueError/TypeError (500).
        self._configure()
        status, _ = self._post(
            "/api/transmission/monitor",
            {"dossier_id": "e012345", "mdn_timeout_s": "abc"})
        self.assertEqual(status, 422)
        status2, _ = self._post(
            "/api/transmission/monitor",
            {"dossier_id": "e012345", "fda_timeout_s": {}})
        self.assertEqual(status2, 422)

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


# ---------------------------------------------------------------------------
# REQ-040 / REQ-056 — Management-of-drug-submissions guidance edition pinned.
# Closes OPEN C33 / G18: the day-count tables (processing/screening targets,
# service standards, clarifax + inactive windows) must trace to a pinned,
# version-tracked HC guidance edition, recorded on each transaction at build.
# ---------------------------------------------------------------------------

class GuidanceEditionTests(unittest.TestCase):
    def test_mosp_guidance_edition_pinned(self):
        self.assertEqual(lifecycle.GUIDANCE_EDITION, "2025-10-01")
        ref = lifecycle.guidance_reference()
        self.assertEqual(ref["edition"], "2025-10-01")
        self.assertIn("Management", ref["title"])
        # it governs the day-count tables in this module.
        self.assertIn("screening_target_days", ref["governs"])
        self.assertIn("service_standards", ref["governs"])

    def test_status_view_pins_guidance_edition(self):
        lc = lifecycle.Lifecycle("e123456", "ANDS")
        lc.start(now="2026-01-01")
        view = lc.status_view(now="2026-01-02")
        self.assertEqual(view["guidance_edition"], "2025-10-01")


# ---------------------------------------------------------------------------
# REQ-005 / REQ-040 / REQ-066 — HC Module 1 controlled-vocabulary ingestion.
# Closes OPEN G34: enumerations are ingested as VERSIONED DATA keyed to the
# schema version (a single source, updatable without code), and out-of-vocab
# metadata is rejected via rules I08 (activity/submission type) / H08 (other
# Module-1 attribute/enumeration values). rep sources its activity types here.
# ---------------------------------------------------------------------------

class ControlledVocabularyTests(unittest.TestCase):
    def test_load_cv_keyed_to_schema_version(self):
        cvset = cv.load_cv("2.2")
        self.assertIn("activity_type", cvset)
        self.assertIn("ANDS", cvset["activity_type"])
        self.assertIn("dosage_form", cvset)
        self.assertIn("route_of_administration", cvset)

    def test_unknown_schema_version_raises(self):
        with self.assertRaises(cv.ControlledVocabularyError):
            cv.load_cv("9.9")

    def test_activity_type_out_of_cv_raises_i08(self):
        errs = cv.validate_value("activity_type", "BOGUS")
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["rule"], "I08")
        self.assertEqual(errs[0]["severity"], "Error")

    def test_dosage_form_out_of_cv_raises_h08(self):
        errs = cv.validate_value("dosage_form", "frisbee")
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]["rule"], "H08")

    def test_valid_values_pass(self):
        self.assertEqual(cv.validate_value("activity_type", "ANDS"), [])
        self.assertEqual(cv.validate_value("dosage_form", "tablet"), [])
        self.assertEqual(cv.validate_value("route_of_administration", "oral"), [])

    def test_empty_value_is_not_a_cv_violation(self):
        # Emptiness is a separate required-field concern, not an I08/H08.
        self.assertEqual(cv.validate_value("activity_type", ""), [])

    def test_validate_metadata_collects_all_violations(self):
        errs = cv.validate_metadata({
            "activity_type": "ANDS",                  # ok
            "dosage_form": "frisbee",                 # H08
            "route_of_administration": "teleport"})   # H08
        self.assertEqual(sorted(e["rule"] for e in errs), ["H08", "H08"])

    def test_returned_cv_is_a_copy_not_canonical(self):
        cvset = cv.load_cv("2.2")
        cvset["activity_type"]["ZZZ"] = "Injected"
        self.assertFalse(cv.is_in_cv("activity_type", "ZZZ"))

    def test_rep_activity_types_sourced_from_cv(self):
        # REQ-066: rep's selectable activity types come from the ingested CV.
        self.assertEqual(set(rep.ACTIVITY_TYPES),
                         set(cv.vocabulary("activity_type")))
        self.assertTrue(rep.is_valid_activity_type("ANDS"))
        self.assertIn("Abbreviated", rep.activity_type_label("ANDS"))


class CvApiTests(unittest.TestCase):
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

    def test_cv_list_endpoint(self):
        status, data = self._get("/api/cv")
        self.assertEqual(status, 200)
        self.assertEqual(data["schema_version"], "2.2")
        self.assertIn("activity_type", data["vocabularies"])

    def test_cv_validate_flags_out_of_vocab_h08(self):
        status, data = self._post("/api/cv/validate", {
            "metadata": {"activity_type": "ANDS", "dosage_form": "frisbee"}})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])
        self.assertIn("H08", {e["rule"] for e in data["errors"]})

    def test_cv_validate_clean_metadata(self):
        status, data = self._post("/api/cv/validate", {
            "metadata": {"activity_type": "ANDS", "dosage_form": "tablet"}})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])


# ---------------------------------------------------------------------------
# REQ-014 — ca-regional.xml root element is <hcsc_ectd> (CA Module 1 Schema v2.2).
# Closes OPEN C29: both backbone builders emitted the wrong root; the structural
# validator resolves the required root FROM the pinned schema descriptor.
# ---------------------------------------------------------------------------

class CaRegionalRootTests(unittest.TestCase):
    def test_ca_module1_root_is_hcsc_ectd(self):
        self.assertEqual(ectd.CA_M1_XSD["root_element"], "hcsc_ectd")

    def test_build_ca_regional_emits_hcsc_ectd_and_validates(self):
        ca = ectd.build_ca_regional_xml("e123456", "0000", [])
        self.assertIn("<hcsc_ectd", ca)
        self.assertIn("</hcsc_ectd>", ca)
        ectd.validate_backbone(ca, ectd.CA_M1_XSD)  # must not raise

    def test_validate_backbone_rejects_legacy_root(self):
        bad = ('<?xml version="1.0"?>'
               '<ectd_ca><dossier-id>e123456</dossier-id></ectd_ca>')
        with self.assertRaises(ectd.SchemaValidationError):
            ectd.validate_backbone(bad, ectd.CA_M1_XSD)

    def test_rep_ca_regional_uses_hcsc_ectd_root(self):
        xml = rep.build_ca_regional_xml(
            {"dossier_id": "e123456", "company_id": "K18276",
             "activity_type": "ANDS", "sequence": "0000"})
        self.assertIn("<hcsc_ectd", xml)
        self.assertIn("</hcsc_ectd>", xml)
        # metadata children still present (no regression).
        self.assertIn("<dossier-id>e123456</dossier-id>", xml)


# ---------------------------------------------------------------------------
# REQ-032 — Q&A response-sequence builder (domain)
# ---------------------------------------------------------------------------
import response_builder


class ResponseBuilderTests(unittest.TestCase):
    """REQ-032: attach the original notice, author section-referencing answers,
    and file the response as the next valid eCTD sequence in the same format."""

    def _dossier(self, *sequences):
        d = ectd.Dossier("e123456")
        for i, seq in enumerate(sequences):
            d.add_sequence(seq)
            # give each prior sequence a content leaf so it is non-trivial
            d.add_leaf(seq, {"leaf_id": f"seed-{seq}", "operation": "new",
                             "heading": "1.0", "title": "Cover",
                             "content": f"seed {i}"})
        return d

    def _notice(self, kind="SDN"):
        return {"kind": kind, "notice_id": "sdn-1",
                "issued_at": "2026-01-10",
                "content": "Deficiency: please clarify the dissolution method."}

    def _answers(self):
        return [
            {"section": "2.7.1", "question": "Clarify dissolution method?",
             "answer": "Method per USP <711>, Apparatus 2, 50 rpm."},
            {"section": "3.2.P.5.1", "question": "Provide the spec table?",
             "answer": "Updated specification provided in 3.2.P.5.1."},
        ]

    # -- AC1: the builder attaches a COPY of the original notice --------------
    def test_response_attaches_copy_of_original_notice(self):
        d = self._dossier("0000")
        result = response_builder.file_response_sequence(
            d, self._notice("SDN"), self._answers())
        # the notice copy is in the result and is marked a copy
        self.assertTrue(result["notice"]["is_copy"])
        self.assertEqual(result["notice"]["kind"], "SDN")
        self.assertEqual(
            result["notice"]["content"],
            "Deficiency: please clarify the dissolution method.")
        # and a leaf carrying the notice bytes lives in the new sequence
        seq = d._get_sequence(result["sequence"])
        notice_leaf = next(lf for lf in seq["leaves"]
                           if lf["leaf_id"] == result["notice_leaf_id"])
        self.assertEqual(notice_leaf["content"],
                         "Deficiency: please clarify the dissolution method.")
        self.assertEqual(notice_leaf["operation"], "new")

    def test_all_notice_kinds_accepted(self):
        for kind in ("SDN", "clarifax", "NOD", "NON"):
            d = self._dossier("0000")
            result = response_builder.file_response_sequence(
                d, self._notice(kind), self._answers())
            self.assertEqual(result["notice"]["kind"],
                             response_builder.normalize_kind(kind))

    def test_unknown_notice_kind_rejected(self):
        d = self._dossier("0000")
        with self.assertRaises(response_builder.ResponseBuilderError):
            response_builder.file_response_sequence(
                d, {"kind": "bogus", "content": "x"}, self._answers())

    # -- AC2: each answer references the applicable submission section --------
    def test_each_answer_references_a_submission_section(self):
        d = self._dossier("0000")
        result = response_builder.file_response_sequence(
            d, self._notice(), self._answers())
        refs = [a["section_ref"] for a in result["answers"]]
        self.assertEqual(refs, ["2.7.1", "3.2.P.5.1"])
        # the rendered Q&A document threads the section next to each answer
        self.assertIn("2.7.1", result["answers_document"])
        self.assertIn("3.2.P.5.1", result["answers_document"])

    def test_answer_without_section_is_rejected(self):
        d = self._dossier("0000")
        bad = [{"section": "", "question": "q", "answer": "a"}]
        with self.assertRaises(response_builder.ResponseBuilderError):
            response_builder.file_response_sequence(d, self._notice(), bad)
        # dossier left unchanged — no new sequence appended
        self.assertEqual(d.sequence_numbers(), ["0000"])

    def test_empty_answer_set_rejected(self):
        errs = response_builder.validate_answers([])
        self.assertTrue(any(e["rule"] == "answers_required" for e in errs))

    # -- AC3: files as the next valid eCTD sequence in the same format --------
    def test_next_sequence_number_is_monotonic(self):
        self.assertEqual(
            response_builder.next_sequence_number(self._dossier()), "0000")
        self.assertEqual(
            response_builder.next_sequence_number(self._dossier("0000")),
            "0001")
        self.assertEqual(
            response_builder.next_sequence_number(
                self._dossier("0000", "0001", "0002")), "0003")

    def test_filed_response_is_next_ectd_sequence_in_same_format(self):
        d = self._dossier("0000", "0001")
        result = response_builder.file_response_sequence(
            d, self._notice(), self._answers())
        # next valid 4-digit eCTD sequence
        self.assertEqual(result["sequence"], "0002")
        self.assertEqual(result["format"], "eCTD")
        self.assertIn("0002", d.sequence_numbers())
        # built in the SAME eCTD format: index.xml + ca-regional backbones
        self.assertIn("index.xml", result["files"])
        self.assertIn("m1/ca/ca-regional.xml", result["files"])
        # and the new sequence exports cleanly (checksums verify)
        export = d.export_sequence("0002")
        self.assertTrue(export["valid"])

    def test_explicit_sequence_override_respected(self):
        d = self._dossier("0000")
        result = response_builder.file_response_sequence(
            d, self._notice(), self._answers(), sequence="0005")
        self.assertEqual(result["sequence"], "0005")


class ResponseBuilderApiTests(unittest.TestCase):
    """REQ-032: the /api/response/file route files a Q&A response sequence."""

    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.companies = server.CompanyStore(":memory:")
        self.dossiers = server.DossierStore(":memory:")
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            server.make_handler(self.store, self.companies, self.dossiers))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                        daemon=True)
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

    def _seed_dossier(self):
        self._post("/api/ectd/dossiers", {"dossier_id": "e123456"})
        self._post("/api/ectd/dossiers/e123456/leaves",
                   {"sequence": "0000", "leaf_id": "cl-0000",
                    "operation": "new", "heading": "1.0",
                    "title": "Cover Letter", "content": "cover"})

    def test_file_response_creates_next_sequence(self):
        self._seed_dossier()
        status, data = self._post("/api/response/file", {
            "dossier_id": "e123456",
            "notice": {"kind": "SDN", "notice_id": "sdn-1",
                       "content": "please clarify dissolution"},
            "answers": [
                {"section": "2.7.1", "question": "q1", "answer": "a1"},
                {"section": "3.2.P.5.1", "question": "q2", "answer": "a2"}]})
        self.assertEqual(status, 201)
        self.assertTrue(data["valid"])
        # AC1: a copy of the notice attached
        self.assertTrue(data["response"]["notice"]["is_copy"])
        # AC2: each answer carries its section reference
        self.assertEqual(
            [a["section_ref"] for a in data["response"]["answers"]],
            ["2.7.1", "3.2.P.5.1"])
        # AC3: filed as next eCTD sequence in the same format
        self.assertEqual(data["response"]["sequence"], "0001")
        self.assertEqual(data["response"]["format"], "eCTD")
        self.assertIn("index.xml", data["response"]["files"])

    def test_file_response_unknown_dossier_404(self):
        status, data = self._post("/api/response/file", {
            "dossier_id": "e999999",
            "notice": {"kind": "SDN", "content": "x"},
            "answers": [{"section": "2.7.1", "answer": "a"}]})
        self.assertEqual(status, 404)

    def test_file_response_missing_section_422(self):
        self._seed_dossier()
        status, data = self._post("/api/response/file", {
            "dossier_id": "e123456",
            "notice": {"kind": "SDN", "content": "x"},
            "answers": [{"section": "", "answer": "a"}]})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])


# ==========================================================================
# Coverage backfill: requirements with real implementations that previously
# had no dedicated test. Each class below locks in an existing behaviour so a
# regression would be caught. No production code is changed by these tests.
# ==========================================================================


def _rule_ids(ctx, version="5.3"):
    return {f["rule_id"] for f in validation.run_validation(ctx, version)["findings"]}


class PdfConformanceTests(unittest.TestCase):
    """REQ-010 / REQ-069: PDF version, OCR/searchable, Track Changes, and the
    DRM/IRM/restricted-access/rights-management security-settings block."""

    def test_pdf_version_outside_1_4_to_1_7_is_blocked(self):
        ctx = _vctx()
        ctx["files"][0]["pdf_version"] = "2.0"
        self.assertIn("D03", _rule_ids(ctx))

    def test_pdf_version_1_4_to_1_7_passes(self):
        ctx = _vctx()
        ctx["files"][0]["pdf_version"] = "1.7"
        self.assertNotIn("D03", _rule_ids(ctx))

    def test_scanned_non_searchable_pdf_flagged_for_ocr(self):
        ctx = _vctx()
        ctx["files"][0]["scanned"] = True
        ctx["files"][0]["searchable"] = False
        self.assertIn("B49", _rule_ids(ctx))

    def test_track_changes_enabled_is_blocked(self):
        ctx = _vctx()
        ctx["files"][0]["track_changes"] = True
        self.assertIn("D04", _rule_ids(ctx))

    def test_drm_irm_security_settings_blocked_distinct_from_a09(self):
        # REQ-069: DRM/IRM/restricted-access/rights-management is its own rule
        # (A10), separate from the A09 password/encryption check.
        for flag in ("drm", "irm", "restricted_access", "rights_management"):
            ctx = _vctx()
            ctx["files"][0][flag] = True
            ids = _rule_ids(ctx)
            self.assertIn("A10", ids, f"{flag} should raise A10")
            self.assertNotIn("A09", ids, f"{flag} must not be reported as A09")

    def test_clean_pdf_raises_no_conformance_defect(self):
        ids = _rule_ids(_vctx())
        for rid in ("D03", "D04", "B49", "A10"):
            self.assertNotIn(rid, ids)


class PdfBookmarkAndHyperlinkTests(unittest.TestCase):
    """REQ-011: bookmarks (A11 warning); REQ-012: relative-only hyperlinks (D12)."""

    def test_pdf_without_bookmarks_warns_non_blocking(self):
        ctx = _vctx()
        ctx["files"][0]["bookmarks"] = False
        result = validation.run_validation(ctx, "5.3")
        ids = {f["rule_id"] for f in result["findings"]}
        self.assertIn("A11", ids)
        a11 = [f for f in result["findings"] if f["rule_id"] == "A11"][0]
        self.assertEqual(a11["severity"], validation.SEVERITY_WARNING)
        self.assertFalse(result["blocking"])

    def test_external_absolute_hyperlink_is_blocked(self):
        ctx = _vctx()
        ctx["files"][0]["links"] = ["https://example.com/external"]
        self.assertIn("D12", _rule_ids(ctx))

    def test_relative_internal_hyperlink_passes(self):
        ctx = _vctx()
        ctx["files"][0]["links"] = ["../m3/quality.pdf"]
        self.assertNotIn("D12", _rule_ids(ctx))

    def test_broken_link_flagged(self):
        ctx = _vctx()
        ctx["files"][0]["links"] = [{"target": "../m3/quality.pdf", "broken": True}]
        self.assertIn("D12", _rule_ids(ctx))


class FileSizeBandTests(unittest.TestCase):
    """REQ-013: A03a warn 150-200 MB band; A03b block >= 200 MB."""

    def test_170mb_warns_non_blocking(self):
        ctx = _vctx()
        ctx["files"][0]["size_mb"] = 170
        result = validation.run_validation(ctx, "5.3")
        ids = {f["rule_id"] for f in result["findings"]}
        self.assertIn("A03a", ids)
        self.assertNotIn("A03b", ids)
        self.assertFalse(result["blocking"])

    def test_210mb_blocks(self):
        ctx = _vctx()
        ctx["files"][0]["size_mb"] = 210
        result = validation.run_validation(ctx, "5.3")
        ids = {f["rule_id"] for f in result["findings"]}
        self.assertIn("A03b", ids)
        self.assertTrue(result["blocking"])

    def test_200mb_boundary_blocks(self):
        ctx = _vctx()
        ctx["files"][0]["size_mb"] = 200
        self.assertIn("A03b", _rule_ids(ctx))

    def test_small_file_clean(self):
        ctx = _vctx()
        ctx["files"][0]["size_mb"] = 10
        ids = _rule_ids(ctx)
        self.assertNotIn("A03a", ids)
        self.assertNotIn("A03b", ids)


class NamingHygieneTests(unittest.TestCase):
    """REQ-020: B08 path length, B32 naming charset, B47 unique leaf IDs,
    B48 reserved Windows device names."""

    def test_path_over_200_chars_blocks_b08(self):
        ctx = _vctx()
        long_path = "0000/m1/ca/" + ("a" * 200) + ".pdf"
        ctx["files"].append({"path": long_path, "kind": "pdf", "readable": True})
        self.assertIn("B08", _rule_ids(ctx))

    def test_uppercase_or_space_name_blocks_b32(self):
        ctx = _vctx()
        ctx["files"].append(
            {"path": "0000/m1/ca/Cover Letter.pdf", "kind": "pdf",
             "readable": True})
        self.assertIn("B32", _rule_ids(ctx))

    def test_reserved_windows_name_blocks_b48(self):
        ctx = _vctx()
        ctx["files"].append(
            {"path": "0000/m1/ca/con.pdf", "kind": "pdf", "readable": True})
        self.assertIn("B48", _rule_ids(ctx))

    def test_duplicate_leaf_ids_block_b47(self):
        ctx = _vctx()
        ctx["leaves"].append(
            {"leaf_id": "cl-0000", "href": "0000/m1/ca/cover.pdf",
             "operation": "new", "checksum": ectd.md5_hex("x"), "content": "x"})
        self.assertIn("B47", _rule_ids(ctx))

    def test_compliant_names_pass(self):
        ids = _rule_ids(_vctx())
        for rid in ("B08", "B32", "B47", "B48"):
            self.assertNotIn(rid, ids)


class EmptyFolderTests(unittest.TestCase):
    """REQ-021 / rule A01: a sequence may not contain an empty folder."""

    def test_empty_folder_blocks_a01(self):
        ctx = _vctx()
        ctx["files"].append(
            {"path": "0000/m4", "is_dir": True, "empty": True, "readable": True})
        result = validation.run_validation(ctx, "5.3")
        ids = {f["rule_id"] for f in result["findings"]}
        self.assertIn("A01", ids)
        self.assertTrue(result["blocking"])
        a01 = [f for f in result["findings"] if f["rule_id"] == "A01"][0]
        self.assertEqual(a01["file"], "0000/m4")

    def test_non_empty_folders_pass(self):
        self.assertNotIn("A01", _rule_ids(_vctx()))


class SequenceGapTests(unittest.TestCase):
    """REQ-016: auto-assigned 4-digit sequences, no gaps/repeats (A05/A07)."""

    def test_next_expected_first_is_0000(self):
        self.assertEqual(domain.next_expected_sequence([]), "0000")

    def test_next_expected_is_strict_increment(self):
        self.assertEqual(domain.next_expected_sequence(["0000", "0001"]), "0002")

    def test_gap_is_blocked_by_intake(self):
        # Filing 0002 while only 0000 exists must raise the lifecycle defect.
        errs = domain.validate_intake(
            {"applicant": "Acme", "drug_product": "Metformin",
             "dossier_id": "e123456", "sequence": "0002",
             "submission_type": "ANDS", "contact_email": "ra@acme.example"},
            prior_sequences=["0000"])
        rules = {e["rule"] for e in errs}
        self.assertIn("sequence_lifecycle", rules)

    def test_in_order_sequence_accepted(self):
        errs = domain.validate_intake(
            {"applicant": "Acme", "drug_product": "Metformin",
             "dossier_id": "e123456", "sequence": "0001",
             "submission_type": "ANDS", "contact_email": "ra@acme.example"},
            prior_sequences=["0000"])
        rules = {e["rule"] for e in errs}
        self.assertNotIn("sequence_lifecycle", rules)


class DstsLifecycleTests(unittest.TestCase):
    """REQ-030: Processing -> Screening -> Review -> decision; type-derived
    Inactive window. REQ-031: deadline timers + clock-stop. REQ-062: 25% fee
    credit on a missed service standard."""

    def _ands(self):
        lc = lifecycle.Lifecycle("e123456", "ANDS", fee_paid=70750.0)
        lc.start(now="2026-01-01")
        return lc

    def test_phases_advance_processing_screening_review(self):
        lc = self._ands()
        self.assertEqual(lc.phase, lifecycle.PHASE_PROCESSING)
        lc.to_screening(now="2026-01-11")
        self.assertEqual(lc.phase, lifecycle.PHASE_SCREENING)
        lc.record_screening_outcome("SAL", now="2026-02-01")  # SAL -> Review
        self.assertEqual(lc.phase, lifecycle.PHASE_REVIEW)

    def test_sdn_sets_inactive_45_and_opens_timer(self):
        lc = self._ands()
        lc.to_screening(now="2026-01-11")
        status = lc.record_screening_outcome("SDN", now="2026-02-01")
        self.assertEqual(status, lifecycle.STATUS_INACTIVE_45)
        kinds = {t["kind"] for t in lc.open_timers()}
        self.assertIn("SDN", kinds)

    def test_nod_inactive_window_is_type_derived_not_hardcoded(self):
        # ANDS (non-DIN) -> Inactive-90; DIN -> Inactive-45.
        self.assertEqual(lifecycle.inactive_window_days("ANDS"), 90)
        self.assertEqual(lifecycle.inactive_window_days("DIN"), 45)
        lc = self._ands()
        lc.to_screening(now="2026-01-11")
        lc.record_screening_outcome("SAL", now="2026-02-01")
        status = lc.record_decision("NOD", now="2026-03-01")
        self.assertEqual(status, lifecycle.STATUS_INACTIVE_90)

    def test_noc_approves(self):
        lc = self._ands()
        lc.to_screening(now="2026-01-11")
        lc.record_screening_outcome("SAL", now="2026-02-01")
        status = lc.record_decision("NOC", now="2026-03-01")
        self.assertEqual(status, lifecycle.STATUS_APPROVED)

    def test_clarifax_overridable_window_and_clock_stop(self):
        lc = self._ands()
        lc.to_screening(now="2026-01-11")
        lc.record_screening_outcome("SAL", now="2026-02-01")
        timer = lc.issue_clarifax(response_days=2, now="2026-02-15")
        self.assertEqual(timer["days"], 2)
        self.assertTrue(timer["overridden"])
        # a 2-day window is outside the nominal 2-15? 2 is the min, so inside.
        self.assertTrue(any(cs.get("reason") == "clarifax response window"
                            for cs in lc.clock_stops))
        lc.resume_clock(now="2026-02-17")
        self.assertEqual(lc.status, lifecycle.STATUS_ACTIVE)

    def test_missed_service_standard_triggers_25pct_fee_credit(self):
        lc = self._ands()
        lc.to_screening(now="2026-01-11")
        lc.record_screening_outcome("SAL", now="2026-02-01")
        # 200 calendar days in Review with no decision > 180-day ANDS target.
        result = lc.check_service_standard(now="2026-08-20")
        self.assertTrue(result["missed_standard"])
        self.assertIsNotNone(result["fee_credit"])
        self.assertEqual(result["fee_credit"]["rate"], 0.25)
        self.assertAlmostEqual(result["fee_credit"]["amount"], round(70750.0 * 0.25, 2))
        self.assertEqual(result["fee_credit"]["authority"], "SOR/2019-124")

    def test_on_time_review_has_no_fee_credit(self):
        lc = self._ands()
        lc.to_screening(now="2026-01-11")
        lc.record_screening_outcome("SAL", now="2026-02-01")
        result = lc.check_service_standard(now="2026-02-20")  # ~19 days < 180
        self.assertFalse(result["missed_standard"])
        self.assertIsNone(result["fee_credit"])


class WithdrawalStatusTests(unittest.TestCase):
    """REQ-033: withdrawal / refiling / reconsideration with HC's exact
    hyphenated NOD-W / NON-W acronyms."""

    def _to_review(self):
        lc = lifecycle.Lifecycle("e123456", "ANDS")
        lc.start(now="2026-01-01")
        lc.to_screening(now="2026-01-11")
        lc.record_screening_outcome("SAL", now="2026-02-01")
        return lc

    def test_explicit_withdrawal_lands_in_withdrawn(self):
        lc = self._to_review()
        status = lc.withdraw(now="2026-03-01", reason="sponsor decision")
        self.assertEqual(status, lifecycle.STATUS_WITHDRAWN)
        self.assertTrue(lc.withdrawn)

    def test_auto_interpreted_nod_lapse_uses_hyphenated_nod_w(self):
        lc = self._to_review()
        lc.record_decision("NOD", now="2026-03-01")
        status = lc.withdraw(now="2026-07-01", auto=True,
                             w_status=lifecycle.STATUS_WITHDRAWN_NOD)
        self.assertEqual(status, "NOD-W")
        self.assertTrue(lc.withdrawal["auto"])

    def test_refile_after_withdrawal_allowed(self):
        lc = self._to_review()
        lc.withdraw(now="2026-03-01")
        result = lc.refile(now="2026-04-01")
        self.assertIsNotNone(result)
        self.assertTrue(lc.refilings)

    def test_cannot_withdraw_twice(self):
        lc = self._to_review()
        lc.withdraw(now="2026-03-01")
        with self.assertRaises(lifecycle.LifecycleError):
            lc.withdraw(now="2026-03-02")


class WithdrawRefileApiTests(unittest.TestCase):
    """REQ-033: withdraw / refile / reconsider and check-deadlines wired into
    server.py — API-level coverage for the previously-dead routes."""

    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), server.make_handler(self.store))
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

    def _start_to_review(self, dossier="e999001"):
        self._post("/api/lifecycle/start",
                   {"dossier_id": dossier, "submission_type": "ANDS",
                    "now": "2026-01-01"})
        self._post("/api/lifecycle/transition",
                   {"dossier_id": dossier, "action": "to_screening",
                    "now": "2026-01-11"})
        self._post("/api/lifecycle/transition",
                   {"dossier_id": dossier, "action": "screening_outcome",
                    "outcome": "SAL", "now": "2026-02-01"})

    def test_withdraw_action_sets_status_withdrawn(self):
        self._start_to_review()
        status, data = self._post(
            "/api/lifecycle/transition",
            {"dossier_id": "e999001", "action": "withdraw",
             "reason": "sponsor decision", "now": "2026-03-01"})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertEqual(data["status"]["status"], lifecycle.STATUS_WITHDRAWN)

    def test_refile_action_after_withdrawal(self):
        self._start_to_review("e999002")
        self._post("/api/lifecycle/transition",
                   {"dossier_id": "e999002", "action": "withdraw",
                    "now": "2026-03-01"})
        status, data = self._post(
            "/api/lifecycle/transition",
            {"dossier_id": "e999002", "action": "refile", "now": "2026-04-01"})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertIn("refiled", data["timer"])

    def test_reconsider_action_after_non(self):
        self._start_to_review("e999003")
        self._post("/api/lifecycle/transition",
                   {"dossier_id": "e999003", "action": "decision",
                    "decision": "NON", "now": "2026-03-01"})
        status, data = self._post(
            "/api/lifecycle/transition",
            {"dossier_id": "e999003", "action": "reconsider",
             "now": "2026-04-01"})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertTrue(data["timer"]["requested"])

    def test_check_deadlines_auto_withdraws_lapsed_nod(self):
        self._start_to_review("e999004")
        self._post("/api/lifecycle/transition",
                   {"dossier_id": "e999004", "action": "decision",
                    "decision": "NOD", "now": "2026-03-01"})
        # Advance past the 90-day NOD response window
        status, data = self._post(
            "/api/lifecycle/check-deadlines",
            {"dossier_id": "e999004", "now": "2026-07-01"})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertTrue(len(data["lapsed"]) > 0)
        self.assertEqual(data["status"]["status"], lifecycle.STATUS_WITHDRAWN_NOD)

    def test_check_deadlines_no_lapse_returns_empty(self):
        self._start_to_review("e999005")
        status, data = self._post(
            "/api/lifecycle/check-deadlines",
            {"dossier_id": "e999005", "now": "2026-02-05"})
        self.assertEqual(status, 200)
        self.assertTrue(data["valid"])
        self.assertEqual(data["lapsed"], [])

    def test_unknown_action_returns_422(self):
        self._start_to_review("e999006")
        status, data = self._post(
            "/api/lifecycle/transition",
            {"dossier_id": "e999006", "action": "bogus"})
        self.assertEqual(status, 422)
        self.assertFalse(data["valid"])
        self.assertIn("reconsider", data["error"])


class PortfolioServiceStandardTests(unittest.TestCase):
    """REQ-034: ANDS measured against 100% on-time; NC/CTA against 90%."""

    def test_ands_held_to_100pct_standard(self):
        std = lifecycle.service_standard("ANDS")
        self.assertEqual(std["on_time_pct"], 100)
        self.assertEqual(std["review_target_days"], 180)

    def test_nc_and_cta_held_to_90pct(self):
        self.assertEqual(lifecycle.service_standard("NC")["on_time_pct"], 90)
        self.assertEqual(lifecycle.service_standard("CTA")["on_time_pct"], 90)


class RbacTenantIsolationTests(unittest.TestCase):
    """REQ-038: least-privilege roles, hard tenant isolation, per-dossier scope;
    every denial is audit-logged."""

    def test_cross_org_access_denied_and_audited(self):
        p = rbac.Principal("u1", "orgA", [rbac.ROLE_REGULATORY_AUTHOR])
        decision = rbac.authorize(p, rbac.CAP_READ,
                                  {"org_id": "orgB", "dossier_id": "e1"})
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["rule"], "tenant_isolation")
        self.assertFalse(decision["audit"]["allowed"])

    def test_read_only_user_cannot_author_or_transmit(self):
        p = rbac.Principal("u2", "orgA", [rbac.ROLE_READ_ONLY])
        self.assertTrue(rbac.authorize(p, rbac.CAP_READ,
                                       {"org_id": "orgA"})["allowed"])
        self.assertFalse(rbac.authorize(p, rbac.CAP_AUTHOR,
                                        {"org_id": "orgA"})["allowed"])
        self.assertFalse(rbac.authorize(p, rbac.CAP_TRANSMIT,
                                        {"org_id": "orgA"})["allowed"])

    def test_per_dossier_scope_enforced(self):
        p = rbac.Principal("u3", "orgA", [rbac.ROLE_REGULATORY_AUTHOR],
                           dossier_scope=["e111111"])
        ok = rbac.authorize(p, rbac.CAP_AUTHOR,
                            {"org_id": "orgA", "dossier_id": "e111111"})
        no = rbac.authorize(p, rbac.CAP_AUTHOR,
                            {"org_id": "orgA", "dossier_id": "e222222"})
        self.assertTrue(ok["allowed"])
        self.assertFalse(no["allowed"])
        self.assertEqual(no["rule"], "dossier_scope")

    def test_org_admin_can_manage_users(self):
        p = rbac.Principal("u4", "orgA", [rbac.ROLE_ORG_ADMIN])
        self.assertTrue(rbac.authorize(p, rbac.CAP_MANAGE_USERS,
                                       {"org_id": "orgA"})["allowed"])


class FeeMitigationTests2(unittest.TestCase):
    """REQ-036: 100% first-submission remission, 50% subsequent-ANDS gated on
    attestation, deferral-until-NOC."""

    def test_first_submission_100pct_remission(self):
        r = fees.evaluate_fee_mitigation(
            {"fee": 70750.0, "small_business": True, "first_submission": True})
        self.assertEqual(r["remission_rate"], 1.0)
        self.assertEqual(r["net_fee"], 0.0)

    def test_subsequent_ands_requires_attestation(self):
        without = fees.evaluate_fee_mitigation(
            {"fee": 70750.0, "small_business": True, "first_submission": False,
             "attestation_uploaded": False})
        self.assertTrue(without["requires_attestation"])
        self.assertEqual(without["remission_rate"], 0.0)
        with_att = fees.evaluate_fee_mitigation(
            {"fee": 70750.0, "small_business": True, "first_submission": False,
             "attestation_uploaded": True})
        self.assertEqual(with_att["remission_rate"], 0.5)

    def test_deferral_until_noc(self):
        r = fees.evaluate_fee_mitigation(
            {"fee": 70750.0, "small_business": False, "defer_until_noc": True})
        self.assertEqual(r["invoice_status"], fees.INVOICE_DEFERRED)


class RightToSellTests2(unittest.TestCase):
    """REQ-037: per-DIN annual Right-to-Sell fee by drug type, Oct-1 due date,
    outstanding-balance flag."""

    def test_amount_by_drug_type_and_oct_1_due_date(self):
        rec = fees.resolve_right_to_sell("prescription", "2025-11-01")
        self.assertEqual(rec["amount"], 5531.0)
        self.assertTrue(rec["due_date"].endswith("-10-01"))

    def test_unpaid_shows_outstanding_balance(self):
        rec = fees.right_to_sell_status("prescription", "2025-09-15", paid=False)
        self.assertTrue(rec["outstanding_balance"])

    def test_unknown_drug_type_raises(self):
        with self.assertRaises(ValueError):
            fees.resolve_right_to_sell("nonsense", "2025-11-01")


class HcCalendarDeadlineTests(unittest.TestCase):
    """REQ-052: HC calendar conventions — calendar vs business days, statutory
    holidays, no silent weekend/holiday roll."""

    def test_weekend_deadline_rolls_forward_and_is_surfaced(self):
        # 2026-01-01 + 2 calendar days = 2026-01-03 (Saturday) -> rolls to Mon.
        result = hc_calendar.compute_deadline("2026-01-01", 2, basis="calendar")
        self.assertTrue(result["adjusted"])
        self.assertIsNotNone(result["adjustment_reason"])
        # Adjusted due date must be a business day.
        self.assertTrue(
            hc_calendar.is_business_day(hc_calendar._as_date(result["due"])))

    def test_business_basis_lands_on_business_day(self):
        result = hc_calendar.compute_deadline("2026-01-01", 5, basis="business")
        self.assertEqual(result["basis"], "business")
        self.assertTrue(
            hc_calendar.is_business_day(hc_calendar._as_date(result["due"])))

    def test_statutory_holiday_recognised(self):
        holidays = hc_calendar.statutory_holidays(2026)
        # Canada Day, July 1, is a federal statutory holiday.
        self.assertTrue(hc_calendar.is_holiday(
            hc_calendar._as_date("2026-07-01"), holidays))


class RejectionReportIngestTests(unittest.TestCase):
    """REQ-029: ingest the emailed validation report, correlate by Core ID, map
    each error back to the exact leaf/node, target the next sequence."""

    REPORT = (
        "Core ID: CORE-789\n"
        "Dossier ID: e123456\n"
        "Sequence: 0001\n"
        "Validation Result: FAILED\n"
        "[Error] B07|0001/index.xml|backbone checksum mismatch\n"
        "[Error] A09|0001/m1/ca/cover.pdf|PDF is encrypted\n"
    )

    def test_parse_extracts_header_and_errors(self):
        parsed = report_ingest.parse_validation_report(self.REPORT)
        self.assertEqual(parsed["core_id"], "CORE-789")
        self.assertEqual(parsed["dossier_id"], "e123456")
        self.assertEqual(len(parsed["errors"]), 2)
        self.assertEqual(parsed["errors"][0]["rule_id"], "B07")

    def test_empty_report_raises(self):
        with self.assertRaises(report_ingest.ReportParseError):
            report_ingest.parse_validation_report("   ")

    def test_correlate_by_core_id_and_map_to_leaf(self):
        transactions = [{"core_id": "CORE-789", "sequence": "0001",
                         "state": "HC_REJECTED"}]
        leaves = [{"leaf_id": "cover-0001", "href": "0001/m1/ca/cover.pdf",
                   "heading": "1.0", "title": "Cover Letter"}]
        result = report_ingest.correlate_rejection(
            self.REPORT, transactions=transactions, leaves=leaves,
            existing_sequences=["0000", "0001"])
        self.assertTrue(result["correlated"])
        self.assertEqual(result["remediation"]["next_sequence"], "0002")
        mapped = [e for e in result["errors"] if e["mapped"]]
        self.assertTrue(mapped)  # cover.pdf error maps to the leaf

    def test_uncorrelated_when_core_id_unknown(self):
        result = report_ingest.correlate_rejection(
            self.REPORT, transactions=[{"core_id": "OTHER"}], leaves=[])
        self.assertFalse(result["correlated"])


class EsignManifestTamperTests(unittest.TestCase):
    """REQ-053: immutable signature manifest binding artifact checksums at
    signing time + post-signature tamper detection. REQ-068: HPFB anchoring."""

    def _signed(self):
        return esign.sign({
            "signer": "jane.qa", "role": esign.ROLE_SIGNER,
            "auth_method": "password+otp", "meaning": "approved",
            "at": "2026-03-01T10:00:00", "tz": "America/Toronto",
            "artifacts": [{"id": "seq-0001", "kind": "sequence",
                           "content": "the-signed-bytes"}],
        })

    def test_sign_emits_manifest_with_checksums_and_policy(self):
        result = self._signed()
        self.assertTrue(result["valid"])
        man = result["manifest"]
        self.assertTrue(man["immutable"])
        self.assertEqual(man["artifacts"][0]["checksum"],
                         esign.artifact_checksum("the-signed-bytes"))
        self.assertEqual(man["policy"], esign.HPFB_POLICY["name"])
        self.assertIn("manifest_id", man)

    def test_unsigned_role_cannot_sign(self):
        result = esign.sign({
            "signer": "bob", "role": "regulatory_author",
            "auth_method": "password", "meaning": "approved",
            "artifacts": [{"id": "x", "content": "y"}]})
        self.assertFalse(result["valid"])
        rules = {e["rule"] for e in result["errors"]}
        self.assertIn("role_not_permitted", rules)

    def test_post_signature_modification_invalidates(self):
        man = self._signed()["manifest"]
        verdict = esign.verify_manifest(man, {"seq-0001": "DIFFERENT-bytes"})
        self.assertFalse(verdict["valid"])
        self.assertTrue(verdict["tampered"])

    def test_unmodified_content_verifies(self):
        man = self._signed()["manifest"]
        verdict = esign.verify_manifest(
            man, {"seq-0001": esign.artifact_checksum("the-signed-bytes")})
        self.assertTrue(verdict["valid"])

    def test_hpfb_acceptance_workflow(self):
        # REQ-068: request + record HC's case-by-case acceptance.
        req = esign.request_hc_acceptance(
            {"approach": "OTP-backed e-sig", "org": "Acme Generics"})
        self.assertTrue(req["valid"])
        self.assertEqual(req["request"]["to"], esign.HPFB_POLICY["request_contact"])
        rec = esign.record_hc_acceptance(
            {"approach": "OTP-backed e-sig", "accepted": True, "org": "Acme"})
        self.assertTrue(rec["acceptance"]["accepted"])


class RetentionLegalHoldTests(unittest.TestCase):
    """REQ-054: retention windows >= PIPEDA 24-month minimum, legal-hold block,
    disposition logging (including blocked attempts)."""

    def test_breach_record_minimum_is_pipeda_24_months(self):
        self.assertEqual(retention.retention_months("breach_record"), 24)
        self.assertGreaterEqual(
            retention.PIPEDA_BREACH_RECORD_MIN_MONTHS, 24)

    def test_within_window_disposition_blocked(self):
        rec = {"record_class": "submission", "created_at": "2026-01-01",
               "record_id": "s1"}
        verdict = retention.can_dispose(rec, "2026-06-01")
        self.assertFalse(verdict["allowed"])
        rules = {b["rule"] for b in verdict["blockers"]}
        self.assertIn("within_retention", rules)

    def test_legal_hold_blocks_even_after_window(self):
        rec = {"record_class": "submission", "created_at": "2000-01-01",
               "legal_hold": True, "record_id": "s2"}
        verdict = retention.can_dispose(rec, "2026-06-01")
        self.assertFalse(verdict["allowed"])
        rules = {b["rule"] for b in verdict["blockers"]}
        self.assertIn("legal_hold", rules)

    def test_blocked_disposition_is_logged(self):
        rec = {"record_class": "submission", "created_at": "2026-01-01",
               "record_id": "s3", "legal_hold": True}
        event = retention.disposition_event(rec, actor="ops", now="2026-06-01")
        self.assertTrue(event["blocked"])
        self.assertFalse(event["executed"])
        self.assertEqual(event["actor"], "ops")

    def test_past_window_no_hold_disposes_and_logs(self):
        rec = {"record_class": "submission", "created_at": "2000-01-01",
               "record_id": "s4"}
        event = retention.disposition_event(rec, actor="ops", now="2026-06-01")
        self.assertTrue(event["executed"])
        self.assertFalse(event["blocked"])


class AuditExportTests(unittest.TestCase):
    """REQ-060: complete, time-ordered, human-readable audit export."""

    def setUp(self):
        self.audits = server.AuditStore(":memory:")

    def tearDown(self):
        self.audits.close()

    def test_export_is_time_ordered_and_complete(self):
        self.audits.append("auth", "login", actor="jane", dossier_id="e123456")
        self.audits.append("transmit", "send", actor="ops", dossier_id="e123456",
                           allowed=False, rule="not_signed")
        text = self.audits.export_text("e123456")
        self.assertIn("AUDIT TRAIL", text)
        self.assertIn("auth/login", text)
        self.assertIn("DENIED (not_signed)", text)
        self.assertIn("Events: 2", text)

    def test_export_scoped_by_dossier(self):
        self.audits.append("auth", "login", actor="a", dossier_id="e111111")
        self.audits.append("auth", "login", actor="b", dossier_id="e222222")
        text = self.audits.export_text("e111111")
        self.assertIn("e111111", text)
        self.assertIn("Events: 1", text)


# ===========================================================================
# Phase A — multi-tenant SaaS control plane (REQ-077..084)
# ===========================================================================

import auth as auth_mod
import entitlements as entitlements_mod
import tenancy as tenancy_mod


class PasswordHashTests(unittest.TestCase):
    """REQ-077/083: passwords are salted + hashed, never stored in clear."""

    def test_hash_is_salted_and_verifiable(self):
        salt, h = auth_mod.hash_password("hunter2")
        self.assertNotEqual(h, "hunter2")
        self.assertTrue(auth_mod.verify_password("hunter2", salt, h))
        self.assertFalse(auth_mod.verify_password("wrong", salt, h))

    def test_distinct_salts_for_same_password(self):
        s1, h1 = auth_mod.hash_password("same")
        s2, h2 = auth_mod.hash_password("same")
        self.assertNotEqual(s1, s2)
        self.assertNotEqual(h1, h2)

    def test_empty_password_rejected(self):
        with self.assertRaises(ValueError):
            auth_mod.hash_password("")


class AuthStoreTests(unittest.TestCase):
    def setUp(self):
        self.auth = auth_mod.AuthStore(":memory:")

    def tearDown(self):
        self.auth.close()

    def test_create_and_authenticate(self):
        u = self.auth.create_user("tenA", "a@x.com", "pw", "tenant-admin")
        self.assertEqual(u["role"], "tenant-admin")
        self.assertIsNotNone(self.auth.authenticate("tenA", "a@x.com", "pw"))
        self.assertIsNone(self.auth.authenticate("tenA", "a@x.com", "bad"))

    def test_credentials_are_tenant_scoped(self):
        # REQ-083: a tenant-A credential must NEVER authenticate into tenant B.
        self.auth.create_user("tenA", "a@x.com", "pw", "user")
        self.assertIsNone(self.auth.authenticate("tenB", "a@x.com", "pw"))

    def test_duplicate_email_in_tenant_rejected(self):
        self.auth.create_user("tenA", "a@x.com", "pw", "user")
        with self.assertRaises(ValueError):
            self.auth.create_user("tenA", "a@x.com", "pw2", "user")

    def test_same_email_different_tenants_allowed(self):
        self.auth.create_user("tenA", "a@x.com", "pw", "user")
        self.auth.create_user("tenB", "a@x.com", "pw", "user")  # no raise

    def test_session_lifecycle(self):
        u = self.auth.create_user("tenA", "a@x.com", "pw", "user")
        tok = self.auth.start_session(u)
        sess = self.auth.resolve_session(tok)
        self.assertEqual(sess["tenant_id"], "tenA")
        self.auth.end_session(tok)
        self.assertIsNone(self.auth.resolve_session(tok))

    def test_resolve_unknown_token_is_none(self):
        self.assertIsNone(self.auth.resolve_session("nope"))

    def test_ensure_owner_idempotent(self):
        o1 = self.auth.ensure_owner("owner@p", "pw")
        o2 = self.auth.ensure_owner("owner@p", "pw")
        self.assertEqual(o1["id"], o2["id"])
        self.assertEqual(o1["role"], "owner")


class EntitlementStoreTests(unittest.TestCase):
    def setUp(self):
        self.ent = entitlements_mod.EntitlementStore(":memory:")

    def tearDown(self):
        self.ent.close()

    def test_default_plan_grants_all_features(self):
        plan = self.ent.get_plan(entitlements_mod.DEFAULT_PLAN_ID)
        self.assertEqual(set(plan["features"]), set(entitlements_mod.FEATURES))

    def test_new_tenant_effective_is_all_features(self):
        # REQ-081: a brand-new tenant (default plan, no overrides) = ALL on.
        eff = self.ent.effective("t1", entitlements_mod.DEFAULT_PLAN_ID)
        self.assertTrue(all(v["enabled"] for v in eff.values()))
        self.assertTrue(all(v["source"] == "plan" for v in eff.values()))

    def test_create_plan_normalizes_features(self):
        plan = self.ent.create_plan("Basic", ["dashboard", "bogus", "fees"])
        self.assertEqual(plan["features"], ["dashboard", "fees"])

    def test_override_wins_over_plan(self):
        # REQ-081: explicit per-tenant override beats the plan grant.
        self.ent.set_override("t1", "fees", False)
        eff = self.ent.effective("t1", entitlements_mod.DEFAULT_PLAN_ID)
        self.assertFalse(eff["fees"]["enabled"])
        self.assertEqual(eff["fees"]["source"], "override")
        self.assertFalse(
            self.ent.is_entitled("t1", entitlements_mod.DEFAULT_PLAN_ID, "fees"))

    def test_remove_override_reverts_to_plan(self):
        self.ent.set_override("t1", "fees", False)
        self.ent.remove_override("t1", "fees")
        self.assertTrue(
            self.ent.is_entitled("t1", entitlements_mod.DEFAULT_PLAN_ID, "fees"))

    def test_enable_override_grants_feature_plan_lacks(self):
        basic = self.ent.create_plan("Lite", ["dashboard"])
        self.assertFalse(self.ent.is_entitled("t1", basic["id"], "fees"))
        self.ent.set_override("t1", "fees", True)
        self.assertTrue(self.ent.is_entitled("t1", basic["id"], "fees"))

    def test_update_plan_changes_baseline(self):
        basic = self.ent.create_plan("Trial", ["dashboard"])
        self.ent.update_plan(basic["id"], ["dashboard", "validation"])
        self.assertTrue(self.ent.is_entitled("t1", basic["id"], "validation"))

    def test_unknown_feature_override_rejected(self):
        with self.assertRaises(ValueError):
            self.ent.set_override("t1", "telepathy", True)


class TenancyStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ands-tentest-")
        self.ten = tenancy_mod.TenancyStore(":memory:", tenants_root=self.root)

    def tearDown(self):
        self.ten.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_create_tenant_has_immutable_id_and_active(self):
        t = self.ten.create_tenant("Acme Pharma", "reg@acme.com")
        self.assertTrue(t["id"])
        self.assertEqual(t["status"], "active")
        self.assertEqual(t["plan_id"], "all-features")

    def test_duplicate_registration_email_routes_not_duplicates(self):
        # REQ-077: a duplicate registration email must NOT silently duplicate.
        t = self.ten.create_tenant("Acme", "reg@acme.com")
        with self.assertRaises(tenancy_mod.DuplicateTenant) as ctx:
            self.ten.create_tenant("Acme Two", "reg@acme.com")
        self.assertEqual(ctx.exception.existing["id"], t["id"])

    def test_per_tenant_db_files_are_isolated(self):
        # REQ-078: data written to tenant A is NEVER visible to tenant B.
        a = self.ten.create_tenant("Acme", "a@acme.com")
        b = self.ten.create_tenant("Beta", "b@beta.com")
        da = tenancy_mod.TenantData(self.ten.tenant_db_path(a["id"]))
        da.add("submission", {"drug": "X"})
        db = tenancy_mod.TenantData(self.ten.tenant_db_path(b["id"]))
        self.assertEqual(da.count(), 1)
        self.assertEqual(db.count(), 0)
        self.assertNotEqual(self.ten.tenant_db_path(a["id"]),
                            self.ten.tenant_db_path(b["id"]))
        da.close()
        db.close()

    def test_suspend_resume_audited_with_before_after(self):
        t = self.ten.create_tenant("Acme", "a@acme.com")
        self.ten.suspend(t["id"], "owner@p")
        self.assertEqual(self.ten.get_tenant(t["id"])["status"], "suspended")
        self.ten.resume(t["id"], "owner@p")
        self.assertEqual(self.ten.get_tenant(t["id"])["status"], "active")
        actions = [a["action"] for a in self.ten.list_audit()]
        self.assertIn("tenant.suspended", actions)
        self.assertIn("tenant.active", actions)
        # Audit records before/after state (REQ-084).
        suspend_evt = next(a for a in self.ten.list_audit()
                           if a["action"] == "tenant.suspended")
        self.assertEqual(suspend_evt["before"]["status"], "active")
        self.assertEqual(suspend_evt["after"]["status"], "suspended")

    def test_delete_archives_db_file(self):
        t = self.ten.create_tenant("Acme", "a@acme.com")
        path = self.ten.tenant_db_path(t["id"])
        self.assertTrue(os.path.exists(path))
        result = self.ten.delete(t["id"], "owner@p", archive=True)
        self.assertEqual(result["status"], "deleted")
        self.assertEqual(result["retention"], "archived")
        self.assertFalse(os.path.exists(path))

    def test_deleted_tenant_excluded_from_active_list(self):
        t = self.ten.create_tenant("Acme", "a@acme.com")
        self.ten.delete(t["id"], "owner@p")
        ids = [x["id"] for x in self.ten.list_tenants()]
        self.assertNotIn(t["id"], ids)
        ids_all = [x["id"] for x in self.ten.list_tenants(include_deleted=True)]
        self.assertIn(t["id"], ids_all)


class SqliteStoreBaseTests(unittest.TestCase):
    """Lock in the _SqliteStore refactor — both stores must share the base."""

    def test_auth_store_inherits_sqlite_store(self):
        self.assertTrue(issubclass(auth_mod.AuthStore, auth_mod._SqliteStore))

    def test_entitlement_store_inherits_sqlite_store(self):
        self.assertTrue(issubclass(
            entitlements_mod.EntitlementStore, auth_mod._SqliteStore))

    def test_close_is_inherited_not_overridden(self):
        # close() must live on _SqliteStore, not re-defined on the subclasses
        self.assertIs(auth_mod.AuthStore.close, auth_mod._SqliteStore.close)
        self.assertIs(entitlements_mod.EntitlementStore.close,
                      auth_mod._SqliteStore.close)

    def test_init_is_inherited_not_overridden(self):
        self.assertIs(auth_mod.AuthStore.__init__, auth_mod._SqliteStore.__init__)
        self.assertIs(entitlements_mod.EntitlementStore.__init__,
                      auth_mod._SqliteStore.__init__)


class ControlPlaneApiTests(unittest.TestCase):
    """End-to-end HTTP tests for the multi-tenant control plane."""

    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.auth = auth_mod.AuthStore(":memory:")
        self.auth.ensure_owner("owner@platform", "ownerpw")
        self.ent = entitlements_mod.EntitlementStore(":memory:")
        self.root = tempfile.mkdtemp(prefix="ands-cpapi-")
        self.ten = tenancy_mod.TenancyStore(":memory:", tenants_root=self.root)
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            server.make_handler(self.store, auth_store=self.auth,
                                tenancy_store=self.ten,
                                entitlement_store=self.ent))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.store.close()
        self.auth.close()
        self.ent.close()
        self.ten.close()
        shutil.rmtree(self.root, ignore_errors=True)

    # -- helpers --------------------------------------------------------
    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def _req(self, method, path, body=None, token=""):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self._url(path), data=data,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            code, payload = e.code, json.loads(e.read().decode())
            e.close()
            return code, payload

    def _owner_token(self):
        _, data = self._req("POST", "/api/auth/login",
                            {"email": "owner@platform", "password": "ownerpw"})
        return data["token"]

    def _signup(self, company, email, password="pw"):
        return self._req("POST", "/api/auth/signup",
                         {"company": company, "email": email,
                          "password": password})

    # -- sign-up / login (REQ-077) --------------------------------------
    def test_signup_creates_tenant_admin_and_autologs_in(self):
        status, data = self._signup("Acme Pharma", "admin@acme.com")
        self.assertEqual(status, 201)
        self.assertEqual(data["user"]["role"], "tenant-admin")
        self.assertTrue(data["token"])
        # The session resolves to that tenant.
        s, me = self._req("GET", "/api/auth/me", token=data["token"])
        self.assertEqual(s, 200)
        self.assertEqual(me["tenant_id"], data["tenant"]["id"])

    def test_signup_duplicate_email_409_routes_to_existing(self):
        _, first = self._signup("Acme", "admin@acme.com")
        status, data = self._signup("Acme Clone", "admin@acme.com")
        self.assertEqual(status, 409)
        self.assertEqual(data["tenant_id"], first["tenant"]["id"])

    def test_signup_requires_fields(self):
        status, _ = self._req("POST", "/api/auth/signup",
                             {"company": "X"})
        self.assertEqual(status, 400)

    def test_signup_non_string_fields_returns_4xx_not_500(self):
        # Non-string fields must not crash the handler (500).
        # str() coercion may let numeric company/email through or produce a 400,
        # but must never produce a 500.
        status, _ = self._req("POST", "/api/auth/signup",
                             {"company": 123, "email": "a@b.com", "password": "pw"})
        self.assertNotEqual(status, 500)
        status2, _ = self._req("POST", "/api/auth/signup",
                              {"company": True, "email": True, "password": "pw"})
        self.assertNotEqual(status2, 500)

    def test_login_non_string_email_returns_4xx_not_500(self):
        status, _ = self._req("POST", "/api/auth/login",
                             {"email": 123, "password": "x"})
        self.assertNotEqual(status, 500)
        status2, _ = self._req("POST", "/api/auth/login",
                              {"email": [1, 2], "password": "x", "tenant_id": 99})
        self.assertNotEqual(status2, 500)

    def test_login_bad_credentials_401(self):
        self._signup("Acme", "admin@acme.com", "right")
        status, _ = self._req("POST", "/api/auth/login",
                             {"email": "admin@acme.com", "password": "wrong"})
        self.assertEqual(status, 401)

    def test_logout_invalidates_session(self):
        _, data = self._signup("Acme", "admin@acme.com")
        tok = data["token"]
        self._req("POST", "/api/auth/logout", {}, token=tok)
        status, _ = self._req("GET", "/api/auth/me", token=tok)
        self.assertEqual(status, 401)

    # -- owner control plane access control (REQ-079) -------------------
    def test_owner_routes_forbidden_without_owner_session(self):
        status, _ = self._req("GET", "/api/owner/tenants")
        self.assertEqual(status, 403)
        # A tenant-admin must also be refused the control plane.
        _, data = self._signup("Acme", "admin@acme.com")
        status, _ = self._req("GET", "/api/owner/tenants", token=data["token"])
        self.assertEqual(status, 403)

    def test_denied_control_plane_access_is_audited(self):
        self._req("GET", "/api/owner/tenants")  # anonymous, denied
        tok = self._owner_token()
        _, data = self._req("GET", "/api/owner/audit", token=tok)
        actions = [a["action"] for a in data["audit"]]
        self.assertIn("control_plane.access_denied", actions)

    def test_owner_login_redirects_to_console(self):
        status, data = self._req("POST", "/api/auth/login",
                                {"email": "owner@platform",
                                 "password": "ownerpw"})
        self.assertEqual(status, 200)
        self.assertEqual(data["role"], "owner")
        self.assertEqual(data["redirect"], "/owner")

    def test_owner_can_list_tenants_with_status_and_usage(self):
        self._signup("Acme", "admin@acme.com")
        tok = self._owner_token()
        status, data = self._req("GET", "/api/owner/tenants", token=tok)
        self.assertEqual(status, 200)
        self.assertEqual(len(data["tenants"]), 1)
        self.assertIn("status", data["tenants"][0])
        self.assertIn("usage", data["tenants"][0])

    # -- owner provisioning (REQ-077) -----------------------------------
    def test_owner_provisions_tenant_with_invite_password(self):
        tok = self._owner_token()
        status, data = self._req("POST", "/api/owner/tenants",
                                {"company": "Owned Co",
                                 "email": "boss@owned.com"}, token=tok)
        self.assertEqual(status, 201)
        self.assertTrue(data["invite_password"])
        self.assertEqual(data["admin"]["role"], "tenant-admin")
        # The provisioned admin can log in with the invite password.
        s, login = self._req("POST", "/api/auth/login",
                            {"email": "boss@owned.com",
                             "password": data["invite_password"]})
        self.assertEqual(s, 200)

    # -- plans + overrides (REQ-080/081) --------------------------------
    def test_owner_creates_plan_and_assigns_to_tenant(self):
        _, signup = self._signup("Acme", "admin@acme.com")
        tid = signup["tenant"]["id"]
        tok = self._owner_token()
        s, _ = self._req("POST", "/api/owner/plans",
                       {"name": "Basic", "features": ["dashboard", "dossiers"]},
                       token=tok)
        self.assertEqual(s, 201)
        s, _ = self._req("POST", f"/api/owner/tenants/{tid}/plan",
                       {"plan_id": "basic"}, token=tok)
        self.assertEqual(s, 200)
        s, ent = self._req("GET", f"/api/owner/tenants/{tid}/entitlements",
                         token=tok)
        self.assertFalse(ent["features"]["fees"]["enabled"])
        self.assertTrue(ent["features"]["dashboard"]["enabled"])

    def test_owner_override_beats_plan(self):
        _, signup = self._signup("Acme", "admin@acme.com")
        tid = signup["tenant"]["id"]
        tok = self._owner_token()
        s, data = self._req("POST", f"/api/owner/tenants/{tid}/overrides",
                          {"feature": "fees", "enabled": False}, token=tok)
        self.assertEqual(s, 200)
        self.assertFalse(data["effective"]["fees"]["enabled"])
        self.assertEqual(data["effective"]["fees"]["source"], "override")

    # -- entitlement enforcement at the API (REQ-082) -------------------
    def test_disabled_feature_returns_403_at_api(self):
        _, signup = self._signup("Acme", "admin@acme.com")
        tid = signup["tenant"]["id"]
        tok = signup["token"]
        # Entitled by default -> works.
        s, _ = self._req("POST", "/api/tenant/submissions",
                       {"drug_product": "Aspirin"}, token=tok)
        self.assertEqual(s, 201)
        # Owner disables 'dossiers' -> direct API call now 403 (defense in depth).
        otok = self._owner_token()
        self._req("POST", f"/api/owner/tenants/{tid}/overrides",
                  {"feature": "dossiers", "enabled": False}, token=otok)
        s, data = self._req("POST", "/api/tenant/submissions",
                          {"drug_product": "Aspirin"}, token=tok)
        self.assertEqual(s, 403)
        self.assertEqual(data["feature"], "dossiers")

    def test_tenant_entitlements_endpoint_lists_entitled(self):
        _, signup = self._signup("Acme", "admin@acme.com")
        s, data = self._req("GET", "/api/tenant/entitlements",
                          token=signup["token"])
        self.assertEqual(s, 200)
        self.assertEqual(set(data["entitled"]),
                         set(entitlements_mod.FEATURES))

    # -- tenant lifecycle blocks sign-in (REQ-084) ----------------------
    def test_suspended_tenant_user_blocked_at_login(self):
        _, signup = self._signup("Acme", "admin@acme.com")
        tid = signup["tenant"]["id"]
        otok = self._owner_token()
        self._req("POST", f"/api/owner/tenants/{tid}/suspend", {}, token=otok)
        status, data = self._req("POST", "/api/auth/login",
                                {"email": "admin@acme.com", "password": "pw"})
        self.assertEqual(status, 403)
        self.assertEqual(data["error"], "suspended")

    def test_resumed_tenant_user_can_login_again(self):
        _, signup = self._signup("Acme", "admin@acme.com")
        tid = signup["tenant"]["id"]
        otok = self._owner_token()
        self._req("POST", f"/api/owner/tenants/{tid}/suspend", {}, token=otok)
        self._req("POST", f"/api/owner/tenants/{tid}/resume", {}, token=otok)
        status, _ = self._req("POST", "/api/auth/login",
                            {"email": "admin@acme.com", "password": "pw"})
        self.assertEqual(status, 200)

    # -- cross-tenant data isolation over HTTP (REQ-078) ----------------
    def test_cross_tenant_data_isolation_over_http(self):
        _, a = self._signup("Acme", "a@acme.com")
        _, b = self._signup("Beta", "b@beta.com")
        self._req("POST", "/api/tenant/submissions",
                  {"drug_product": "AcmeDrug"}, token=a["token"])
        # Tenant B sees ONLY its own (empty) data, never Acme's.
        _, bdata = self._req("GET", "/api/tenant/submissions", token=b["token"])
        self.assertEqual(bdata["submissions"], [])
        _, adata = self._req("GET", "/api/tenant/submissions", token=a["token"])
        self.assertEqual(len(adata["submissions"]), 1)

    def test_no_tenant_context_denied(self):
        # REQ-078: an unauthenticated tenant-data request is rejected.
        status, _ = self._req("GET", "/api/tenant/submissions")
        self.assertEqual(status, 401)

    # -- the two control-plane / auth pages render (REQ-079/085) --------
    def test_owner_console_page_renders(self):
        with urllib.request.urlopen(self._url("/owner")) as resp:
            page = resp.read().decode()
        self.assertEqual(resp.status, 200)
        self.assertIn("Owner Control Plane", page)
        self.assertIn('lang="en"', page)
        self.assertIn("<label", page)  # WCAG: labelled controls

    def test_auth_page_renders(self):
        with urllib.request.urlopen(self._url("/login")) as resp:
            page = resp.read().decode()
        self.assertEqual(resp.status, 200)
        self.assertIn("Register your company", page)
        self.assertIn('lang="en"', page)

    # -- REQ-071 / UI-2: submission-readiness dashboard -----------------
    def test_dashboard_empty_state_for_new_tenant(self):
        # GIVEN no dossiers yet THEN the dashboard reports an empty state
        # (the UI shows a "Start a submission" CTA, not a blank form-wall).
        _, signup = self._signup("Acme", "admin@acme.com")
        s, data = self._req("GET", "/api/tenant/dashboard",
                            token=signup["token"])
        self.assertEqual(s, 200)
        self.assertTrue(data["empty"])
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["submissions"], [])

    def test_dashboard_blocked_submission_lists_blocking_items(self):
        # A freshly-created submission is BLOCKED on validation, Module-1,
        # fees and e-signature, each drilling in to where it is resolved.
        _, signup = self._signup("Acme", "admin@acme.com")
        tok = signup["token"]
        self._req("POST", "/api/tenant/submissions",
                  {"drug_product": "Aspirin", "dossier_id": "e123456"},
                  token=tok)
        s, data = self._req("GET", "/api/tenant/dashboard", token=tok)
        self.assertEqual(s, 200)
        self.assertFalse(data["empty"])
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["blocked"], 1)
        card = data["submissions"][0]
        self.assertEqual(card["status"], "BLOCKED")
        self.assertFalse(card["ready"])
        self.assertEqual(card["title"], "Aspirin")
        self.assertEqual(card["dossier_id"], "e123456")
        signals = {b["signal"] for b in card["blocking_items"]}
        self.assertEqual(signals,
                         {"validation", "module1", "fees", "esign"})
        routes = {b["route"] for b in card["blocking_items"]}
        self.assertIn("/validation", routes)
        self.assertIn("/fees", routes)
        # every required tile is present
        keys = {t["key"] for t in card["tiles"]}
        self.assertEqual(keys, {"lifecycle", "validation", "module1", "fees",
                                "esign", "transmission", "deadline"})

    def test_dashboard_ready_when_all_signals_satisfied(self):
        # A submission carrying clean signals shows READY with no blockers.
        _, signup = self._signup("Acme", "admin@acme.com")
        tok = signup["token"]
        present = [{"key": d["key"], "formats": d["formats"]}
                   for d in content_model.required_documents(False)]
        self._req("POST", "/api/tenant/submissions", {
            "drug_product": "Betadrug", "dossier_id": "e999999",
            "validation": {"ran": True, "errors": 0, "warnings": 2},
            "content": {"present_documents": present},
            "fees": {"paid": True}, "esign": {"signed": True},
            "transmission": {"state": "RECEIVED_BY_HC"},
            "lifecycle": {"status": "Active"},
            "deadline": {"start": "2026-06-01", "days": 45,
                         "notice_type": "SDN"}}, token=tok)
        s, data = self._req("GET", "/api/tenant/dashboard?today=2026-06-27",
                            token=tok)
        self.assertEqual(s, 200)
        self.assertEqual(data["ready"], 1)
        self.assertEqual(data["blocked"], 0)
        card = data["submissions"][0]
        self.assertEqual(card["status"], "READY")
        self.assertEqual(card["blocking_items"], [])
        m1 = next(t for t in card["tiles"] if t["key"] == "module1")
        self.assertTrue(m1["complete"])
        dl = next(t for t in card["tiles"] if t["key"] == "deadline")
        self.assertEqual(dl["days_remaining"], 19)  # 2026-07-16 due

    def test_dashboard_requires_tenant_session(self):
        # REQ-078: an unauthenticated dashboard request is rejected.
        s, _ = self._req("GET", "/api/tenant/dashboard")
        self.assertEqual(s, 401)

    def test_dashboard_gated_by_entitlement(self):
        # REQ-082: owner disables the 'dashboard' feature -> 403 at the API.
        _, signup = self._signup("Acme", "admin@acme.com")
        tid = signup["tenant"]["id"]
        tok = signup["token"]
        s, _ = self._req("GET", "/api/tenant/dashboard", token=tok)
        self.assertEqual(s, 200)
        otok = self._owner_token()
        self._req("POST", f"/api/owner/tenants/{tid}/overrides",
                  {"feature": "dashboard", "enabled": False}, token=otok)
        s, data = self._req("GET", "/api/tenant/dashboard", token=tok)
        self.assertEqual(s, 403)
        self.assertEqual(data["feature"], "dashboard")

    def test_dashboard_isolated_per_tenant(self):
        # REQ-078: one tenant's dashboard never surfaces another's submissions.
        _, a = self._signup("Acme", "a@acme.com")
        _, b = self._signup("Beta", "b@beta.com")
        self._req("POST", "/api/tenant/submissions",
                  {"drug_product": "AcmeDrug"}, token=a["token"])
        _, bdash = self._req("GET", "/api/tenant/dashboard", token=b["token"])
        self.assertTrue(bdash["empty"])
        _, adash = self._req("GET", "/api/tenant/dashboard", token=a["token"])
        self.assertEqual(adash["total"], 1)

    def test_workspace_shell_renders_dashboard_client(self):
        # The workspace shell ships the readiness-dashboard renderer + REQ tag.
        with urllib.request.urlopen(self._url("/dashboard")) as resp:
            page = resp.read().decode()
        self.assertEqual(resp.status, 200)
        self.assertIn("renderDashboard", page)
        self.assertIn("/api/tenant/dashboard", page)
        self.assertIn("REQ-071", page)
        self.assertIn('lang="en"', page)

    # -- JRNY-REQ-001: GET /api/journey/{id} (journey spine as an API) ---
    def _new_submission(self, tok, body):
        s, data = self._req("POST", "/api/tenant/submissions", body, token=tok)
        self.assertEqual(s, 201)
        return data["saved"]["id"]

    def test_journey_endpoint_returns_stages_position_and_readiness(self):
        # JRNY-REQ-001 (MUST): the gated journey served by the BFF returns
        # stages (done/current/locked + reason) + position + readiness.
        _, signup = self._signup("Acme", "admin@acme.com")
        tok = signup["token"]
        sid = self._new_submission(
            tok, {"drug_product": "Aspirin", "dossier_id": "e123456"})
        s, data = self._req("GET", f"/api/journey/{sid}", token=tok)
        self.assertEqual(s, 200)
        # stages: the full gated walk, each annotated with a status
        self.assertEqual(len(data["stages"]), len(journey.STAGES))
        for st in data["stages"]:
            self.assertIn(st["status"], ("done", "current", "locked"))
        locked = [st for st in data["stages"] if st["status"] == "locked"]
        self.assertTrue(all(st["gate"]["reason"] for st in locked))  # +reason
        # position: the compact Resume roll-up
        self.assertIn("resume", data["position"])
        self.assertEqual(data["position"]["current"], data["current"])
        # readiness: the READY/BLOCKED card (REQ-071) folded in
        self.assertIn(data["readiness"]["status"], ("READY", "BLOCKED"))
        self.assertEqual(data["readiness"]["dossier_id"], "e123456")
        self.assertIn("tiles", data["readiness"])

    def test_journey_endpoint_404_for_unknown_submission(self):
        _, signup = self._signup("Acme", "admin@acme.com")
        s, data = self._req("GET", "/api/journey/999999",
                            token=signup["token"])
        self.assertEqual(s, 404)

    def test_journey_endpoint_404_for_non_numeric_id(self):
        _, signup = self._signup("Acme", "admin@acme.com")
        s, _d = self._req("GET", "/api/journey/not-an-id",
                          token=signup["token"])
        self.assertEqual(s, 404)

    def test_journey_endpoint_requires_tenant_session(self):
        s, _d = self._req("GET", "/api/journey/1")   # no token
        self.assertEqual(s, 401)

    def test_journey_endpoint_is_tenant_isolated(self):
        # A submission created in tenant A is not reachable from tenant B.
        _, a = self._signup("Acme", "admin@acme.com")
        sid = self._new_submission(a["token"], {"drug_product": "Aspirin"})
        _, b = self._signup("Beta", "admin@beta.com")
        s, _d = self._req("GET", f"/api/journey/{sid}", token=b["token"])
        self.assertEqual(s, 404)

    def test_journey_endpoint_advances_with_carried_signals(self):
        # Carry-through: a submission that records company_id + dossier_id +
        # sequence has walked past orientation/company/dossier, so the journey
        # reports 'submission' (create-the-sequence) as the current stage.
        _, signup = self._signup("Acme", "admin@acme.com")
        tok = signup["token"]
        sid = self._new_submission(tok, {
            "drug_product": "Aspirin", "dossier_id": "e123456",
            "company_id": "100000", "sequence": "0000"})
        s, data = self._req("GET", f"/api/journey/{sid}", token=tok)
        self.assertEqual(s, 200)
        self.assertEqual(data["position"]["current_key"], "content")
        # orientation/company/dossier/submission are done
        done = {st["key"] for st in data["stages"] if st["status"] == "done"}
        self.assertTrue({"orient", "company", "dossier", "submission"} <= done)

    def test_journey_endpoint_today_anchors_readiness_countdown(self):
        _, signup = self._signup("Acme", "admin@acme.com")
        tok = signup["token"]
        sid = self._new_submission(tok, {
            "drug_product": "Aspirin", "dossier_id": "e123456",
            "deadline": {"start": "2026-06-01", "days": 45,
                         "notice_type": "SDN"}})
        s, data = self._req("GET", f"/api/journey/{sid}?today=2026-06-27",
                            token=tok)
        self.assertEqual(s, 200)
        deadline = [t for t in data["readiness"]["tiles"]
                    if t["key"] == "deadline"][0]
        self.assertIsNotNone(deadline.get("days_remaining"))


class JourneyDomainTests(unittest.TestCase):
    """REQ-073 / JRNY-REQ-001 guided-journey spine — pure domain (no HTTP).

    Characterises every stage of the gated 11-stage walk and the compact
    ``position`` roll-up. journey.py had zero tests before this class; these
    lock in the linear-gate contract (exactly one CURRENT stage; everything
    after it LOCKED with a plain-language reason; everything before it DONE)."""

    @staticmethod
    def _content_present():
        # A content sub-object that satisfies content_model's checklist gate,
        # built the same way the REQ-071 dashboard tests do.
        present = [{"key": d["key"], "formats": d["formats"]}
                   for d in content_model.required_documents(False)]
        return {"present_documents": present}

    def _walk_payload(self, upto_key):
        """Return a payload whose signals make every stage BEFORE ``upto_key``
        complete, so ``upto_key`` is the CURRENT stage."""
        order = [s["key"] for s in journey.STAGES]
        idx = order.index(upto_key)
        signals = {
            "orient":     {"oriented": True},
            "company":    {"company_id": "100000"},
            "dossier":    {"dossier_id": "e123456"},
            "submission": {"sequence": "0000"},
            "content":    {"content": self._content_present()},
            "validate":   {"validation": {"ran": True, "errors": 0,
                                          "warnings": 2}},
            "fees":       {"fees": {"paid": True}},
            "review":     {"reviews": {"approved": True}},
            "sign":       {"esign": {"signed": True}},
            "transmit":   {"transmission": {"state": "RECEIVED_BY_HC"}},
        }
        payload: dict = {}
        for key in order[:idx]:            # complete every predecessor
            payload.update(signals.get(key, {}))
        return payload

    # -- new / empty journey -------------------------------------------
    def test_empty_payload_starts_at_orientation(self):
        sts = journey.stages({})
        self.assertEqual(len(sts), len(journey.STAGES))     # all 11 present
        self.assertEqual(sts[0]["status"], journey.CURRENT)  # orient current
        self.assertTrue(sts[0]["current"])
        self.assertFalse(sts[0]["done"])
        # everything after the current stage is locked with a gate reason
        for st in sts[1:]:
            self.assertEqual(st["status"], journey.LOCKED)
            self.assertIsNotNone(st["gate"])

    def test_locked_stage_gate_names_the_exact_predecessor(self):
        sts = journey.stages({})
        company = sts[1]                    # "Set up your company" is locked
        self.assertEqual(company["status"], journey.LOCKED)
        gate = company["gate"]
        self.assertIn("Get oriented", gate["reason"])       # plain-language
        self.assertEqual(gate["needs_key"], "orient")
        self.assertEqual(gate["needs_route"], "/submit")    # where to satisfy
        self.assertEqual(gate["requirement"], journey.STAGES[1]["unlocks"])

    # -- the linear walk, stage by stage -------------------------------
    def test_each_stage_becomes_current_when_predecessors_complete(self):
        for key in [s["key"] for s in journey.STAGES if s["key"] != "track"]:
            payload = self._walk_payload(key)
            pos = journey.position(payload)
            self.assertEqual(pos["current_key"], key,
                             f"expected {key} to be current for {payload}")
            sts = journey.stages(payload)
            n = pos["current"]
            self.assertEqual(sts[n]["status"], journey.CURRENT)
            # predecessors done, successors locked
            for i in range(n):
                self.assertEqual(sts[i]["status"], journey.DONE)
            for i in range(n + 1, len(sts)):
                self.assertEqual(sts[i]["status"], journey.LOCKED)

    def test_company_id_implies_orientation_is_done(self):
        # A Company ID means the user has visibly moved past orientation.
        sts = journey.stages({"company_id": "100000"})
        self.assertEqual(sts[0]["status"], journey.DONE)     # orient
        self.assertEqual(sts[1]["status"], journey.DONE)     # company
        self.assertEqual(sts[2]["status"], journey.CURRENT)  # dossier

    def test_validation_with_errors_does_not_advance_past_validate(self):
        payload = self._walk_payload("validate")
        payload["validation"] = {"ran": True, "errors": 3}
        pos = journey.position(payload)
        self.assertEqual(pos["current_key"], "validate")
        self.assertFalse(journey.stages(payload)[5]["done"])

    # -- terminal / track stage ----------------------------------------
    def test_fully_transmitted_lives_in_track(self):
        payload = self._walk_payload("transmit")
        payload["transmission"] = {"state": "RECEIVED_BY_HC"}
        pos = journey.position(payload)
        self.assertTrue(pos["complete"])
        self.assertTrue(pos["transmitted"])
        self.assertEqual(pos["done"], pos["total"])          # 10 of 10
        self.assertEqual(pos["percent"], 100)
        sts = journey.stages(payload)
        track = sts[-1]
        self.assertEqual(track["key"], "track")
        self.assertEqual(track["status"], journey.CURRENT)   # ongoing, not done

    def test_track_is_locked_before_transmit(self):
        payload = self._walk_payload("transmit")             # at transmit, not sent
        self.assertEqual(journey.stages(payload)[-1]["status"], journey.LOCKED)

    # -- position roll-up ----------------------------------------------
    def test_position_resume_target_is_the_current_stage(self):
        payload = self._walk_payload("fees")
        pos = journey.position(payload)
        self.assertEqual(pos["resume"]["key"], "fees")
        self.assertEqual(pos["resume"]["route"], "/fees")
        self.assertEqual(pos["current_route"], "/fees")
        self.assertEqual(pos["done"], 6)                     # orient..review? no
        self.assertEqual(pos["percent"], round(6 * 100 / 10))

    # -- journey() wrapper + payload shapes ----------------------------
    def test_journey_wraps_record_identity_and_title(self):
        rec = {"id": 7, "payload": {"drug_product": "Aspirin",
                                    "dossier_id": "e123456"}}
        view = journey.journey(rec)
        self.assertEqual(view["id"], 7)
        self.assertEqual(view["title"], "Aspirin")
        self.assertEqual(view["dossier_id"], "e123456")
        self.assertEqual(len(view["stages"]), len(journey.STAGES))
        self.assertIn("position", view)
        self.assertEqual(view["current"], view["position"]["current"])

    def test_journey_title_falls_back_to_submission_id(self):
        view = journey.journey({}, sub_id=42)
        self.assertEqual(view["title"], "Submission 42")
        view2 = journey.journey({})
        self.assertEqual(view2["title"], "New submission")

    def test_record_and_bare_payload_are_equivalent(self):
        payload = {"company_id": "100000", "dossier_id": "e1"}
        bare = journey.stages(payload)
        wrapped = journey.stages(journey._payload_of({"payload": payload}))
        self.assertEqual([s["status"] for s in bare],
                         [s["status"] for s in wrapped])


class ReadinessDashboardDomainTests(unittest.TestCase):
    """REQ-071 readiness aggregation — pure domain (no HTTP)."""

    def _present_all(self, cs_be_only=False):
        return [{"key": d["key"], "formats": d["formats"]}
                for d in content_model.required_documents(cs_be_only)]

    def test_draft_is_blocked_on_every_prerequisite(self):
        r = readiness.submission_readiness(
            {"payload": {"drug_product": "Aspirin", "dossier_id": "e123456"}},
            today="2026-06-27")
        self.assertEqual(r["status"], "BLOCKED")
        self.assertFalse(r["ready"])
        self.assertEqual({b["signal"] for b in r["blocking_items"]},
                         {"validation", "module1", "fees", "esign"})

    def test_module1_completeness_is_x_of_y(self):
        r = readiness.submission_readiness(
            {"payload": {"content": {"present_documents": self._present_all()}}})
        tile = next(t for t in r["tiles"] if t["key"] == "module1")
        self.assertTrue(tile["complete"])
        self.assertEqual(tile["present"], tile["required"])
        self.assertEqual(tile["value"],
                         f"{tile['present']} of {tile['required']}")

    def test_validation_errors_block_and_count(self):
        r = readiness.submission_readiness(
            {"payload": {"validation": {"ran": True, "errors": 3,
                                        "warnings": 1}}})
        v = next(t for t in r["tiles"] if t["key"] == "validation")
        self.assertEqual(v["state"], "fail")
        self.assertEqual(v["errors"], 3)
        block = next(b for b in r["blocking_items"]
                     if b["signal"] == "validation")
        self.assertEqual(block["count"], 3)

    def test_warnings_only_validation_passes_but_warns(self):
        r = readiness.submission_readiness(
            {"payload": {"validation": {"ran": True, "errors": 0,
                                        "warnings": 5}}})
        v = next(t for t in r["tiles"] if t["key"] == "validation")
        self.assertEqual(v["state"], "warn")
        self.assertTrue(v["passed"])
        self.assertNotIn("validation",
                         {b["signal"] for b in r["blocking_items"]})

    def test_deadline_overdue_is_negative_and_flagged(self):
        r = readiness.submission_readiness(
            {"payload": {"deadline": {"due": "2026-06-01"}}},
            today="2026-06-27")
        dl = next(t for t in r["tiles"] if t["key"] == "deadline")
        self.assertEqual(dl["days_remaining"], -26)
        self.assertEqual(dl["state"], "fail")

    def test_deadline_soon_is_warned(self):
        r = readiness.submission_readiness(
            {"payload": {"deadline": {"due": "2026-07-05"}}},
            today="2026-06-27")
        dl = next(t for t in r["tiles"] if t["key"] == "deadline")
        self.assertEqual(dl["state"], "warn")

    def test_deadline_without_anchor_shows_date_no_countdown(self):
        r = readiness.submission_readiness(
            {"payload": {"deadline": {"start": "2026-06-01", "days": 45}}})
        dl = next(t for t in r["tiles"] if t["key"] == "deadline")
        self.assertEqual(dl["due"], "2026-07-16")
        self.assertIsNone(dl["days_remaining"])

    def test_transmission_delivered_is_positive(self):
        r = readiness.submission_readiness(
            {"payload": {"transmission": {"state": "RECEIVED_BY_HC"}}})
        tx = next(t for t in r["tiles"] if t["key"] == "transmission")
        self.assertTrue(tx["delivered"])
        self.assertEqual(tx["state"], "pass")

    def test_bare_payload_without_id_titles_untitled(self):
        r = readiness.submission_readiness({})
        self.assertEqual(r["title"], "Untitled submission")

    def test_dashboard_rollup_counts(self):
        ready_sub = {"payload": {
            "validation": {"ran": True, "errors": 0, "warnings": 0},
            "content": {"present_documents": self._present_all()},
            "fees": {"paid": True}, "esign": {"signed": True}}}
        blocked = {"payload": {"drug_product": "X"}}
        d = readiness.dashboard([ready_sub, blocked], today="2026-06-27")
        self.assertEqual(d["total"], 2)
        self.assertEqual(d["ready"], 1)
        self.assertEqual(d["blocked"], 1)
        self.assertFalse(d["empty"])


class StoreGcNoLeakTests(unittest.TestCase):
    """A dropped store must close its sqlite connection — no ResourceWarning."""

    def test_dropped_store_emits_no_resource_warning(self):
        import gc, warnings
        for ctor in (
            lambda: auth_mod.AuthStore(":memory:"),
            lambda: entitlements_mod.EntitlementStore(":memory:"),
            lambda: tenancy_mod.TenancyStore(":memory:"),
        ):
            with warnings.catch_warnings():
                warnings.simplefilter("error", ResourceWarning)
                store = ctor()
                del store
                gc.collect()  # __del__ must close cleanly; no warning raised

    def test_all_store_classes_define_del(self):
        for cls in (auth_mod._SqliteStore, tenancy_mod.TenantData,
                    tenancy_mod.TenancyStore):
            self.assertIn("__del__", cls.__dict__)


# ---------------------------------------------------------------------------
# REQ-065: REP XML stylesheet package — bundled, version-tracked, render-for-review
# ---------------------------------------------------------------------------

class RepStylesheetPackageTests(unittest.TestCase):
    """Unit tests for rep_stylesheet.py (REQ-065)."""

    def setUp(self):
        import rep_stylesheet as rs
        self.rs = rs

    def test_package_manifest_has_active_version(self):
        m = self.rs.package_manifest()
        self.assertEqual(m["package"], "pharmabio_stylesheets")
        self.assertEqual(m["active_version"], "2025-09-10")
        self.assertEqual(m["review_stage"], "pre-file")
        self.assertTrue(len(m["versions"]) >= 1)

    def test_bundled_covers_all_four_kinds(self):
        pkg = self.rs.load_stylesheet("2025-09-10")
        self.assertIn("co", pkg["views"])
        self.assertIn("rt", pkg["views"])
        self.assertIn("pi", pkg["views"])
        self.assertIn("ca_regional", pkg["views"])

    def test_load_unknown_version_raises(self):
        with self.assertRaises(self.rs.StylesheetVersionError):
            self.rs.load_stylesheet("9999-99-99")

    def test_available_versions_contains_bundled(self):
        self.assertIn("2025-09-10", self.rs.available_versions())

    def test_stylesheet_for_template_matches_rt(self):
        m = self.rs.stylesheet_for_template("rt", rep.RT_TEMPLATE_VERSION)
        self.assertEqual(m["version"], "2025-09-10")
        self.assertEqual(m["view"]["root_tag"], "rep-transaction")

    def test_stylesheet_for_template_unmatched_raises(self):
        with self.assertRaises(self.rs.StylesheetVersionError):
            self.rs.stylesheet_for_template("rt", "9.9.9")

    def _rt_xml(self):
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<rep-transaction template-version="{rep.RT_TEMPLATE_VERSION}" '
            f'template-date="2025-09-10">'
            '<dossier-id>e123456</dossier-id>'
            '<company-id>K18276</company-id>'
            '<regulatory-activity-type code="ANDS">'
            'Abbreviated New Drug Submission (ANDS)</regulatory-activity-type>'
            '<regulatory-activity-lead>Pharmaceuticals</regulatory-activity-lead>'
            '<sequence>0000</sequence>'
            '</rep-transaction>'
        )

    def _co_xml(self):
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<rep-company template-version="{rep.CO_TEMPLATE_VERSION}">'
            '<company-id>K18276</company-id>'
            '<company-name>Acme Generics Inc.</company-name>'
            '</rep-company>'
        )

    def _pi_xml(self):
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<rep-product-information template-version="{rep.PI_TEMPLATE_VERSION}">'
            '<dossier-id>e123456</dossier-id>'
            '<product-name>Metformin HCl 500 mg</product-name>'
            '<din>02123456</din>'
            '</rep-product-information>'
        )

    def test_render_rt_xml_returns_kind_and_html(self):
        result = self.rs.render_rep_xml(self._rt_xml())
        self.assertEqual(result["kind"], "rt")
        self.assertTrue(result["matched"])
        self.assertEqual(result["review_stage"], "pre-file")
        self.assertIn("e123456", result["html"])
        self.assertIn("ANDS", result["html"])
        self.assertIn("<table", result["html"])

    def test_render_co_xml_fields(self):
        result = self.rs.render_rep_xml(self._co_xml())
        self.assertEqual(result["kind"], "co")
        self.assertIn("K18276", result["html"])
        self.assertIn("Acme Generics Inc.", result["html"])

    def test_render_pi_xml_fields(self):
        result = self.rs.render_rep_xml(self._pi_xml())
        self.assertEqual(result["kind"], "pi")
        self.assertIn("Metformin", result["html"])
        self.assertIn("02123456", result["html"])

    def test_render_version_auto_detected_from_attribute(self):
        # template version on the element drives stylesheet matching
        result = self.rs.render_rep_xml(self._rt_xml())
        self.assertEqual(result["stylesheet"]["version"], "2025-09-10")

    def test_render_explicit_template_version_overrides(self):
        result = self.rs.render_rep_xml(
            self._rt_xml(), template_version=rep.RT_TEMPLATE_VERSION)
        self.assertTrue(result["matched"])

    def test_render_unknown_root_raises(self):
        with self.assertRaises(self.rs.StylesheetRenderError):
            self.rs.render_rep_xml('<unknown-element/>')

    def test_render_malformed_xml_raises(self):
        with self.assertRaises(self.rs.StylesheetRenderError):
            self.rs.render_rep_xml('not xml at all <<<')

    def test_render_entity_attack_raises(self):
        bomb = ('<?xml version="1.0"?><!DOCTYPE lol [<!ENTITY lol "lol">]>'
                '<rep-transaction>&lol;</rep-transaction>')
        with self.assertRaises((self.rs.StylesheetRenderError,
                                __import__('xmlsafe').UnsafeXmlError)):
            self.rs.render_rep_xml(bomb)

    def test_render_transaction_renders_all_artifacts(self):
        import rep as rep_mod
        txn = rep_mod.assemble_transaction({
            "applicant": "Acme", "company_id": "K18276",
            "dossier_id": "e123456", "activity_type": "ANDS",
            "sequence": "0000", "drug_product": "Metformin 500mg",
        })["transaction"]
        result = self.rs.render_transaction(txn)
        self.assertEqual(result["review_stage"], "pre-file")
        kinds = [a["kind"] for a in result["artifacts"]]
        self.assertIn("co", kinds)
        self.assertIn("rt", kinds)
        self.assertIn("ca_regional", kinds)

    def test_render_transaction_with_pi(self):
        import rep as rep_mod
        txn = rep_mod.assemble_transaction({
            "applicant": "Acme", "company_id": "K18276",
            "dossier_id": "e123456", "activity_type": "ANDS",
            "sequence": "0000", "drug_product": "Metformin 500mg",
            "pi_required": True, "din": "02123456",
        })["transaction"]
        result = self.rs.render_transaction(txn)
        kinds = [a["kind"] for a in result["artifacts"]]
        self.assertIn("pi", kinds)

    def test_register_new_package_and_render(self):
        # Simulate a stylesheet update from HC — register as data, render works.
        new_pkg = {
            "package": "pharmabio_stylesheets",
            "published": "2026-01-01",
            "title": "HC REP stylesheet (future)",
            "covers_templates": {
                "rt": ["5.2.0"],
            },
            "views": {
                "rt": {
                    "root_tag": "rep-transaction",
                    "title": "REP RT (future)",
                    "version_attr": "template-version",
                    "fields": [{"path": "dossier-id", "label": "Dossier ID"}],
                },
            },
        }
        self.rs.register_stylesheet_package("2026-01-01", new_pkg)
        self.assertIn("2026-01-01", self.rs.available_versions())
        # Clean up so other tests are unaffected
        del self.rs._STYLESHEET_PACKAGES["2026-01-01"]

    def test_register_empty_version_raises(self):
        with self.assertRaises(ValueError):
            self.rs.register_stylesheet_package("", {})

    def test_register_package_without_views_raises(self):
        with self.assertRaises(ValueError):
            self.rs.register_stylesheet_package("2026-02-01", {"foo": "bar"})


class RepStylesheetApiTests(unittest.TestCase):
    """HTTP API tests for /api/rep/stylesheet (GET) and /api/rep/stylesheet/render (POST)."""

    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), server.make_handler(self.store))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def _get(self, path):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", path)
        r = conn.getresponse()
        return r.status, json.loads(r.read())

    def _post(self, path, body):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        data = json.dumps(body).encode()
        conn.request("POST", path, body=data,
                     headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        return r.status, json.loads(r.read())

    def _rt_xml(self):
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<rep-transaction template-version="{rep.RT_TEMPLATE_VERSION}" '
            'template-date="2025-09-10">'
            '<dossier-id>e123456</dossier-id>'
            '<company-id>K18276</company-id>'
            '<regulatory-activity-type code="ANDS">'
            'Abbreviated New Drug Submission (ANDS)</regulatory-activity-type>'
            '<regulatory-activity-lead>Pharmaceuticals</regulatory-activity-lead>'
            '<sequence>0000</sequence>'
            '</rep-transaction>'
        )

    def test_get_manifest_200(self):
        status, data = self._get("/api/rep/stylesheet")
        self.assertEqual(status, 200)
        self.assertEqual(data["package"], "pharmabio_stylesheets")
        self.assertIn("active_version", data)
        self.assertIn("versions", data)

    def test_get_manifest_bundled_version(self):
        _, data = self._get("/api/rep/stylesheet")
        self.assertEqual(data["active_version"], "2025-09-10")
        kinds = data["versions"][0]["kinds"]
        for k in ("co", "rt", "pi", "ca_regional"):
            self.assertIn(k, kinds)

    def test_post_render_single_xml(self):
        status, data = self._post("/api/rep/stylesheet/render",
                                  {"xml": self._rt_xml()})
        self.assertEqual(status, 200)
        self.assertEqual(data["kind"], "rt")
        self.assertTrue(data["matched"])
        self.assertIn("e123456", data["html"])

    def test_post_render_transaction(self):
        import rep as rep_mod
        txn = rep_mod.assemble_transaction({
            "applicant": "Acme", "company_id": "K18276",
            "dossier_id": "e123456", "activity_type": "ANDS",
            "sequence": "0000", "drug_product": "Metformin 500mg",
        })["transaction"]
        status, data = self._post("/api/rep/stylesheet/render",
                                  {"transaction": txn})
        self.assertEqual(status, 200)
        self.assertIn("artifacts", data)
        kinds = [a["kind"] for a in data["artifacts"]]
        self.assertIn("co", kinds)
        self.assertIn("rt", kinds)

    def test_post_render_malformed_xml_422(self):
        status, data = self._post("/api/rep/stylesheet/render",
                                  {"xml": "<<<not xml"})
        self.assertEqual(status, 422)
        self.assertIn("error", data)

    def test_post_render_unknown_root_422(self):
        status, data = self._post("/api/rep/stylesheet/render",
                                  {"xml": "<unknown-element/>"})
        self.assertEqual(status, 422)
        self.assertIn("error", data)


# ---------------------------------------------------------------------------
# App shell + client-side router (REQ-085 / UI-1)
# ---------------------------------------------------------------------------

class NavigationDomainTests(unittest.TestCase):
    """The route map is the single source of truth for both shells."""

    def test_tenant_nav_keys_are_all_entitlement_features(self):
        # Every nav entry MUST tie to a real entitlement feature so filtering
        # by entitlement (REQ-082) is exact, with no second list to drift.
        feats = {item["feature"] for item in navigation.TENANT_NAV}
        self.assertEqual(feats, set(entitlements_mod.FEATURES))

    def test_tenant_nav_filters_to_entitled_features_only(self):
        nav = navigation.tenant_nav(["dashboard", "validation"])
        routes = [n["route"] for n in nav]
        self.assertEqual(routes, ["/dashboard", "/validation"])
        # hidden areas never appear
        self.assertNotIn("/fees", routes)

    def test_tenant_nav_entries_carry_label_route_and_breadcrumb(self):
        nav = navigation.tenant_nav(["fees"])
        self.assertEqual(len(nav), 1)
        entry = nav[0]
        self.assertEqual(entry["route"], "/fees")
        self.assertEqual(entry["label"], entitlements_mod.FEATURE_LABELS["fees"])
        # breadcrumb starts at the workspace home and ends at this page
        self.assertEqual(entry["breadcrumb"][0], navigation.WORKSPACE_HOME["label"])
        self.assertEqual(entry["breadcrumb"][-1], entry["label"])

    def test_tenant_nav_preserves_catalogue_order(self):
        nav = navigation.tenant_nav(list(entitlements_mod.FEATURES))
        self.assertEqual([n["feature"] for n in nav],
                         list(entitlements_mod.FEATURES))

    def test_resolve_top_level_route(self):
        self.assertEqual(navigation.resolve_tenant_route("/validation"),
                         ("validation", None))

    def test_resolve_trailing_slash_and_root(self):
        self.assertEqual(navigation.resolve_tenant_route("/fees/"),
                         ("fees", None))
        # bare "/" is NOT a workspace route (legacy single page lives there)
        self.assertIsNone(navigation.resolve_tenant_route("/"))

    def test_resolve_deep_linkable_detail_route(self):
        self.assertEqual(navigation.resolve_tenant_route("/dossiers/e123456"),
                         ("dossiers", "e123456"))

    def test_resolve_unknown_route_is_none(self):
        self.assertIsNone(navigation.resolve_tenant_route("/api/health"))
        self.assertIsNone(navigation.resolve_tenant_route("/nope"))

    def test_owner_route_detection(self):
        self.assertTrue(navigation.is_owner_route("/owner/plans"))
        self.assertTrue(navigation.is_owner_route("/owner/tenants/abc"))
        self.assertFalse(navigation.is_owner_route("/dashboard"))

    def test_owner_nav_has_breadcrumbs(self):
        nav = navigation.owner_nav()
        self.assertEqual([n["route"] for n in nav], ["/owner", "/owner/plans"])
        self.assertTrue(all(n["breadcrumb"][0] == "Control plane" for n in nav))


class AppShellRoutingApiTests(unittest.TestCase):
    """HTTP behaviour of the workspace shell + entitlement-filtered nav API."""

    def setUp(self):
        self.store = server.SubmissionStore(":memory:")
        self.auth = auth_mod.AuthStore(":memory:")
        self.auth.ensure_owner("owner@platform", "ownerpw")
        self.ent = entitlements_mod.EntitlementStore(":memory:")
        self.root = tempfile.mkdtemp(prefix="ands-shell-")
        self.ten = tenancy_mod.TenancyStore(":memory:", tenants_root=self.root)
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            server.make_handler(self.store, auth_store=self.auth,
                                tenancy_store=self.ten,
                                entitlement_store=self.ent))
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()
        self.store.close()
        self.auth.close()
        self.ent.close()
        self.ten.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def _get_html(self, path):
        try:
            with urllib.request.urlopen(self._url(path)) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            e.close()
            return e.code, body

    def _req(self, method, path, body=None, token=""):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self._url(path), data=data,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            code, payload = e.code, json.loads(e.read().decode())
            e.close()
            return code, payload

    def _signup(self, company="Acme", email="admin@acme.com", password="pw"):
        return self._req("POST", "/api/auth/signup",
                         {"company": company, "email": email,
                          "password": password})

    # -- shell is served for every deep-linkable workspace route -----------
    def test_legacy_single_page_still_served_at_root(self):
        # The legacy page MUST remain (additive constraint) at "/".
        status, body = self._get_html("/")
        self.assertEqual(status, 200)
        self.assertIn("Transmission Console", body)

    def test_every_workspace_route_serves_the_shell(self):
        for route in navigation.all_tenant_routes():
            status, body = self._get_html(route)
            self.assertEqual(status, 200, route)
            self.assertIn("ANDS Workspace", body)
            self.assertIn('id="nav-rail"', body)

    def test_deep_link_detail_route_serves_shell(self):
        # A bookmarked /dossiers/<id> must load the shell (router resolves it).
        status, body = self._get_html("/dossiers/e123456")
        self.assertEqual(status, 200)
        self.assertIn("ANDS Workspace", body)

    def test_shell_uses_history_api_router_and_active_nav(self):
        _, body = self._get_html("/dashboard")
        self.assertIn("history.pushState", body)      # real URL changes
        self.assertIn("popstate", body)               # Back button works
        self.assertIn('aria-current="page"', body)    # active-nav state
        self.assertIn('id="crumbs"', body)            # breadcrumbs

    def test_unknown_route_still_404s(self):
        status, _ = self._get_html("/definitely-not-a-route")
        self.assertEqual(status, 404)

    # -- entitlement-filtered nav API (REQ-082) ----------------------------
    def test_tenant_nav_requires_session(self):
        status, _ = self._req("GET", "/api/tenant/nav")
        self.assertEqual(status, 401)

    def test_tenant_nav_returns_full_set_for_default_plan(self):
        _, data = self._signup()
        status, payload = self._req("GET", "/api/tenant/nav",
                                    token=data["token"])
        self.assertEqual(status, 200)
        routes = [n["route"] for n in payload["nav"]]
        self.assertEqual(routes, navigation.all_tenant_routes())
        self.assertEqual(payload["home"]["route"], "/dashboard")

    def test_tenant_nav_hides_non_entitled_area(self):
        # Owner disables 'fees' for this tenant -> its tab disappears (REQ-082).
        _, data = self._signup()
        tid = data["tenant"]["id"]
        self.ent.set_override(tid, "fees", False)
        _, payload = self._req("GET", "/api/tenant/nav", token=data["token"])
        routes = [n["route"] for n in payload["nav"]]
        self.assertNotIn("/fees", routes)
        self.assertIn("/dashboard", routes)

    # -- owner nav API is owner-only (REQ-079) -----------------------------
    def test_owner_nav_forbidden_without_owner(self):
        status, _ = self._req("GET", "/api/owner/nav")
        self.assertEqual(status, 403)
        _, data = self._signup()
        status, _ = self._req("GET", "/api/owner/nav", token=data["token"])
        self.assertEqual(status, 403)

    def test_owner_nav_returns_pages_for_owner(self):
        _, login = self._req("POST", "/api/auth/login",
                             {"email": "owner@platform", "password": "ownerpw"})
        status, payload = self._req("GET", "/api/owner/nav",
                                    token=login["token"])
        self.assertEqual(status, 200)
        self.assertEqual([n["route"] for n in payload["nav"]],
                         ["/owner", "/owner/plans"])

    def test_owner_deep_link_routes_serve_owner_shell(self):
        for route in ("/owner/plans", "/owner/tenants/abc123"):
            status, body = self._get_html(route)
            self.assertEqual(status, 200, route)

    # -- UI-2: each workspace page renders REAL content, not a placeholder ----
    # The route->endpoint binding for every workflow page in the UI-2 table.
    PAGE_BINDINGS = {
        "/dossiers": "/api/tenant/submissions",
        "/enrolment": "/api/activity-types",
        "/validation": "/api/validation/rulesets",
        "/fees": "/api/fees/reference",
        "/transmission": "/api/transmission/account-types",
        "/reviews": "/api/esign/policy",
        "/admin": "/api/rbac/roles",
    }

    def test_ui2_no_placeholder_stub_text_in_shell(self):
        # The old "This is the <page> page (route ...)" stub MUST be gone — each
        # page now renders real content from an existing endpoint.
        _, body = self._get_html("/dashboard")
        self.assertNotIn("This is the <strong>", body)
        self.assertNotIn("page (route <code>", body)

    def test_ui2_every_page_route_is_bound_to_its_endpoint(self):
        # The served shell wires each workflow route to its REAL endpoint via the
        # PAGE_VIEWS registry (UI-2 "reuses existing endpoints" column).
        _, body = self._get_html("/dashboard")
        self.assertIn("PAGE_VIEWS", body)
        for route, endpoint in self.PAGE_BINDINGS.items():
            self.assertIn("'" + route + "'", body, route)
            self.assertIn("'" + endpoint + "'", body, endpoint)

    def test_ui2_bound_endpoints_serve_real_data(self):
        # Each page binds to a LIVE endpoint that returns real, non-empty data —
        # proving the pages are not stubs pointing at dead routes.
        self._signup()  # establish a tenant session for tenant-scoped endpoints
        checks = {
            "/api/activity-types": "activity_types",
            "/api/validation/rulesets": "rulesets",
            "/api/fees/reference": "groupings",
            "/api/transmission/account-types": "account_types",
            "/api/esign/policy": "policy",
            "/api/rbac/roles": "roles",
        }
        for endpoint, key in checks.items():
            status, payload = self._req("GET", endpoint)
            self.assertEqual(status, 200, endpoint)
            self.assertIn(key, payload, endpoint)
            self.assertTrue(payload[key], endpoint)  # non-empty

    def test_ui2_submit_journey_stepper_is_real(self):
        # /submit is the guided journey index: a real ordered stepper linking to
        # each workflow page (REQ-073), not a placeholder.
        _, body = self._get_html("/submit")
        self.assertIn("SUBMIT_STAGES", body)
        self.assertIn("renderSubmit", body)
        self.assertIn("stepper", body)

    def test_ui2_dossier_detail_renders_ectd_tree(self):
        # /dossiers/:id renders the eCTD Module 1-5 tree bound to the existing
        # placement table (REQ-072), deep-linkable.
        _, body = self._get_html("/dossiers/e123456")
        self.assertIn("renderDossierTree", body)
        self.assertIn("/api/ectd/placement", body)
        self.assertIn("ectd-tree", body)
        # the placement endpoint it consumes is live and non-empty
        status, payload = self._req("GET", "/api/ectd/placement")
        self.assertEqual(status, 200)
        self.assertTrue(payload["entries"])


class Req075IntegrityValidationTests(unittest.TestCase):
    """REQ-075: referential + checksum integrity between the eCTD backbone and
    the document store, surfaced as BLOCKING validation findings before export."""

    def _ctx(self, **over):
        ctx = {
            "leaves": [{"leaf_id": "cl", "href": "0000/m1/ca/cover.pdf",
                        "operation": "new", "content": "cover-bytes",
                        "checksum": ectd.md5_hex("cover-bytes")}],
            "files": [{"path": "0000/m1/ca/cover.pdf"}],
        }
        ctx.update(over)
        return ctx

    def _ids(self, ctx):
        return {f["rule_id"] for f in validation.run_validation(ctx, "5.3")["findings"]}

    def test_clean_transaction_has_no_integrity_findings(self):
        ids = self._ids(self._ctx())
        self.assertNotIn("R06", ids)
        self.assertNotIn("B07b", ids)

    def test_orphaned_file_is_blocking(self):
        ctx = self._ctx()
        ctx["files"].append({"path": "0000/m1/ca/stray.pdf"})  # referenced by no leaf
        result = validation.run_validation(ctx, "5.3")
        self.assertTrue(result["blocking"])
        r06 = [f for f in result["findings"] if f["rule_id"] == "R06"]
        self.assertEqual(r06[0]["file"], "0000/m1/ca/stray.pdf")
        self.assertIn("orphaned", r06[0]["message"])

    def test_checksum_mismatch_is_blocking(self):
        ctx = self._ctx()
        ctx["leaves"][0]["checksum"] = "0" * 32  # disagrees with the bytes
        result = validation.run_validation(ctx, "5.3")
        self.assertTrue(result["blocking"])
        b07b = [f for f in result["findings"] if f["rule_id"] == "B07b"]
        self.assertEqual(b07b[0]["node"], "cl")
        self.assertIn("mismatch", b07b[0]["message"])

    def test_reused_leaf_without_shipped_bytes_not_flagged(self):
        # A reused leaf re-ships no content; its bytes are unchanged from the
        # prior verified sequence, so it must NOT raise a false mismatch.
        ctx = self._ctx()
        ctx["leaves"][0]["content"] = None
        self.assertNotIn("B07b", self._ids(ctx))

    def test_directory_and_backbone_artifacts_are_not_orphans(self):
        ctx = self._ctx()
        ctx["files"] += [{"path": "0000/m1/empty", "is_dir": True},
                         {"path": "0000/index.xml"},
                         {"path": "0000/index-md5.txt"}]
        self.assertNotIn("R06", self._ids(ctx))

    def test_integrity_rules_gated_to_5_3(self):
        ids_53 = {r["rule_id"] for r in validation.get_ruleset("5.3")["rules"]}
        ids_52 = {r["rule_id"] for r in validation.get_ruleset("5.2")["rules"]}
        self.assertEqual({"R06", "B07b"} & ids_53, {"R06", "B07b"})
        self.assertEqual({"R06", "B07b"} & ids_52, set())


class CoverageTraceabilityTests(unittest.TestCase):
    """Lock-in tests for requirements that had real implementations but no
    token-traceable test. Each asserts existing behaviour; no production code
    is changed by these tests."""

    def test_req_018_current_view_reconstruction(self):
        leaves = [
            {"leaf_id": "a", "operation": "new"},
            {"leaf_id": "a2", "operation": "replace", "modified_leaf": "a"},
            {"leaf_id": "b", "operation": "new"},
            {"leaf_id": "bdel", "operation": "delete", "modified_leaf": "b"},
        ]
        live = {l["leaf_id"] for l in ectd.compute_current_view(leaves)["live"]}
        self.assertEqual(live, {"a2"})  # REQ-018: replace supersedes, delete removes

    def test_req_028_received_by_hc_only_on_hc_ack(self):
        led = transmission.TransmissionLedger("e012345")
        led.submit({"sequence": "0000", "size_gb": 5},
                   now="2026-06-22T10:00:00+00:00")
        led.receive_mdn("0000")
        # REQ-028: an MDN alone (and even the FDA ack) is NOT HC delivery.
        self.assertNotEqual(led._find("0000")["state"],
                            transmission.STATE_RECEIVED_BY_HC)
        led.receive_fda_ack("0000", "CORE-9")
        self.assertNotEqual(led._find("0000")["state"],
                            transmission.STATE_RECEIVED_BY_HC)
        led.receive_hc_ack("CORE-9")
        rec = led._find("0000")
        self.assertEqual(rec["state"], transmission.STATE_RECEIVED_BY_HC)
        self.assertEqual(rec.get("core_id"), "CORE-9")  # Core ID captured

    def test_req_047_cross_dossier_reference_blocked(self):
        pf = rbac.Portfolio("org-1")
        pf.add_dossier("e100001", product_family="acme", din="02000001")
        pf.add_dossier("e100002", product_family="acme", din="02000002")
        self.assertTrue(pf.owns("e100001"))
        self.assertEqual(len(pf.family_members("acme")), 2)  # one family, two DINs
        # REQ-047: a prior-leaf ref that is not live in THIS dossier is blocked.
        findings = pf.validate_prior_leaf_reference(
            "e100001", "leaf-from-other", dossier_live_leaves=["own-leaf"])
        self.assertTrue(findings)

    def test_req_050_response_quality_vocabulary_and_window_guard(self):
        # REQ-050: HC distinguishes acceptable / deficient / unsolicited responses.
        self.assertEqual(
            lifecycle.RESPONSE_QUALITIES,
            frozenset({"acceptable", "deficient", "unsolicited"}))
        lc = lifecycle.Lifecycle("e123456", "ANDS")
        lc.start(now="2026-01-01")
        lc.to_screening(now="2026-01-11")
        lc.record_screening_outcome("SAL", now="2026-02-01")
        # No open window -> a response cannot be filed (window closed guard).
        with self.assertRaises(lifecycle.LifecycleError):
            lc.resume_clock(now="2026-02-05")

    def test_req_051_concurrent_notice_ids_are_unique(self):
        # REQ-051: concurrent deficiency notices must be individually addressable.
        lc = lifecycle.Lifecycle("e123456", "ANDS")
        ids = [lc._next_notice_id("clarifax") for _ in range(3)]
        self.assertEqual(len(set(ids)), 3)

    def test_req_071_to_076_workspace_nav_features_present(self):
        feats = set(entitlements_mod.FEATURES)
        # REQ-071 dashboard, REQ-072 dossiers/tree, REQ-073 guided submit,
        # REQ-074 validation/export, REQ-076 review & approval.
        for f in ("dashboard", "dossiers", "submit", "validation", "reviews"):
            self.assertIn(f, feats)
        # normalize_features keeps only known features, in canonical order.
        self.assertEqual(
            entitlements_mod.normalize_features(["reviews", "bogus", "dashboard"]),
            [f for f in entitlements_mod.FEATURES if f in {"reviews", "dashboard"}])


class PrismDesignSystemTests(unittest.TestCase):
    """REQ-086 / UI-4 — Prism/3D design system: self-contained tokens applied
    consistently across tenant workspace AND owner control plane."""

    def _html(self, path):
        store = server.SubmissionStore(":memory:")
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(store))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}{path}"
            try:
                return urllib.request.urlopen(url, timeout=5).read().decode()
            except urllib.error.HTTPError as e:
                return e.read().decode()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join()
            store.close()

    def test_req_086_prism_tokens_present_in_server_module(self):
        # REQ-086: all CSS/tokens are vendored inline in server.py — no CDN.
        self.assertIn("--prism-radius", server._PRISM_TOKENS)
        self.assertIn("--prism-shadow", server._PRISM_TOKENS)
        self.assertIn("--prism-accent", server._PRISM_TOKENS)
        self.assertIn("prefers-reduced-motion", server._PRISM_TOKENS)
        self.assertIn("prefers-reduced-transparency", server._PRISM_TOKENS)

    def test_req_086_dark_surfaces_include_prism_tokens(self):
        # Owner console + auth surfaces reuse _PRISM_CSS (= _PRISM_TOKENS + dark theme).
        for surface in (server.OWNER_CONSOLE_HTML, server.AUTH_HTML):
            self.assertIn("--prism-radius", surface)
            self.assertIn("prefers-reduced-motion", surface)

    def test_req_086_workspace_includes_prism_tokens(self):
        # Tenant workspace shares the same token layer (light theme variant).
        self.assertIn("--prism-radius", server.WORKSPACE_HTML)
        self.assertIn("prefers-reduced-motion", server.WORKSPACE_HTML)
        self.assertIn("REQ-086", server.WORKSPACE_HTML)

    def test_req_086_no_external_cdn_or_font_fetch(self):
        # REQ-086 offline constraint: no http(s) URLs in the design system.
        for fragment in (server._PRISM_TOKENS, server._PRISM_CSS,
                         server.WORKSPACE_HTML, server.OWNER_CONSOLE_HTML):
            self.assertNotIn("fonts.googleapis", fragment)
            self.assertNotIn("cdn.jsdelivr", fragment)
            self.assertNotIn("unpkg.com", fragment)
            # No web-font fetch / framework import sneaking in via @import or src.
            self.assertNotIn("@import url(http", fragment)
            self.assertNotIn("src:url(http", fragment.replace(" ", ""))

    def test_req_086_layered_elevation_and_z_tiers(self):
        # AC: layered elevation — three multi-level shadow tiers AND a z-layer
        # stack (surface < card < panel < modal) define the depth/3D system.
        for tier in ("--prism-shadow-1", "--prism-shadow-2", "--prism-shadow-3"):
            self.assertIn(tier, server._PRISM_TOKENS)
        for z in ("--prism-z-surface", "--prism-z-card",
                  "--prism-z-panel", "--prism-z-modal"):
            self.assertIn(z, server._PRISM_TOKENS)
        # The z-stack is strictly increasing (surface behind … modal in front).
        self.assertIn("--prism-z-surface:0", server._PRISM_TOKENS)
        self.assertIn("--prism-z-modal:100", server._PRISM_TOKENS)

    def test_req_086_glassmorphism_backdrop_blur_in_both_shells(self):
        # AC: translucent frosted panels with backdrop blur — present in the
        # tenant workspace AND the owner/auth (dark) shells.
        self.assertIn("backdrop-filter:blur", server.WORKSPACE_HTML)
        self.assertIn("backdrop-filter:blur", server._PRISM_CSS)
        # The blur radius is token-driven so the reduced-transparency guard can
        # zero it out in one place.
        self.assertIn("blur(var(--prism-blur))", server._PRISM_CSS)

    def test_req_086_prismatic_gradient_accent_defined_and_used(self):
        # AC: subtle prismatic gradients/accent colours for primary surfaces.
        self.assertIn("--prism-accent:linear-gradient", server._PRISM_TOKENS)
        # The accent token is actually applied (top-bar / accent strip), not dead.
        self.assertIn("var(--prism-accent)", server.WORKSPACE_HTML)

    def test_req_086_rounded_cards(self):
        # AC: generously rounded cards via the shared radius token.
        self.assertIn("--prism-radius:14px", server._PRISM_TOKENS)
        self.assertIn("border-radius:var(--prism-radius)", server.WORKSPACE_HTML)

    def test_req_086_micro_interactions_transitions_and_hover(self):
        # AC: tasteful micro-interactions — transitions plus hover/active lift.
        self.assertIn("transition:transform var(--prism-ease)", server._PRISM_TOKENS)
        self.assertIn(".card:hover", server._PRISM_TOKENS)
        self.assertIn("button:active", server._PRISM_TOKENS)

    def test_req_086_reduced_transparency_guard_in_all_surfaces(self):
        # GUARD AC: honour prefers-reduced-transparency everywhere (the token
        # layer is shared, so every surface inherits the opaque fallback).
        for surface in (server.WORKSPACE_HTML, server.OWNER_CONSOLE_HTML,
                        server.AUTH_HTML):
            self.assertIn("prefers-reduced-transparency", surface)
        # …and it actually neutralises the blur rather than just declaring it.
        self.assertIn("--prism-blur:0px", server._PRISM_TOKENS)

    def test_req_086_visible_focus_rings_in_both_shells(self):
        # GUARD AC: visible focus indication preserved on the glass aesthetic.
        self.assertIn(":focus-visible", server.WORKSPACE_HTML)
        self.assertIn(":focus", server._PRISM_CSS)
        self.assertIn("outline:3px", server.WORKSPACE_HTML)

    def test_req_086_responsive_breakpoint_in_workspace(self):
        # AC: responsive from mobile to wide desktop — the shell collapses the
        # side rail at a small-viewport breakpoint.
        self.assertIn("@media (max-width:720px)", server.WORKSPACE_HTML)

    def test_req_086_form_controls_keep_labels_on_glass(self):
        # GUARD AC: labels are never sacrificed for the glass look — the design
        # system styles a real <label> block on both shells.
        self.assertIn("label{display:block", server._PRISM_CSS)
        self.assertIn("label", server.WORKSPACE_HTML)

    def test_req_086_served_pages_carry_prism_system_live(self):
        # AC: applied consistently across EVERY rendered screen — assert the
        # actually-served HTML (not just the constants) carries the system.
        for path in ("/owner", "/login", "/dashboard"):
            html = self._html(path)
            self.assertIn("--prism-radius", html,
                          msg="Prism tokens missing on served %s" % path)
            self.assertIn("prefers-reduced-motion", html,
                          msg="reduced-motion guard missing on served %s" % path)
            self.assertIn('lang="en"', html,
                          msg="lang attribute missing on served %s" % path)

if __name__ == "__main__":
    unittest.main()
