import json
import threading
import unittest
import http.client

from server import (
    make_server,
    RequestHandler,
    calculate_tip,
    split_shares,
    tip_presets,
    reverse_tip,
    calculate_with_tax,
    suggest_tip,
    suggest_tip_percent,
    split_weighted,
    split_itemized,
    _largest_remainder,
    round_total_to,
    round_total_up,
    format_money,
    build_receipt,
)


class TipCalculatorTest(unittest.TestCase):
    def setUp(self):
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _post(self, path, payload):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        body = json.dumps(payload)
        conn.request("POST", path, body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        status = resp.status
        conn.close()
        return status, data

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", path)
        resp = conn.getresponse()
        data = resp.read()
        status = resp.status
        ctype = resp.getheader("Content-Type")
        conn.close()
        return status, data, ctype

    def test_index_served(self):
        status, data, ctype = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"Tip Calculator", data)

    def test_tip_calculation(self):
        status, data = self._post("/api/tip", {"bill": 100, "tip_percent": 15})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["tip"], 15.0)
        self.assertEqual(payload["total"], 115.0)

    def test_tip_rounding(self):
        status, data = self._post("/api/tip", {"bill": 53.27, "tip_percent": 18})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["tip"], 9.59)
        self.assertEqual(payload["total"], 62.86)

    def test_zero_bill(self):
        status, data = self._post("/api/tip", {"bill": 0, "tip_percent": 20})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["tip"], 0.0)
        self.assertEqual(payload["total"], 0.0)

    def test_negative_bill_invalid(self):
        status, data = self._post("/api/tip", {"bill": -5, "tip_percent": 10})
        self.assertEqual(status, 400)

    def test_tip_percent_out_of_range(self):
        status, data = self._post("/api/tip", {"bill": 50, "tip_percent": 150})
        self.assertEqual(status, 400)

    def test_missing_fields(self):
        status, data = self._post("/api/tip", {})
        self.assertEqual(status, 400)

    def test_non_numeric(self):
        status, data = self._post("/api/tip", {"bill": "abc", "tip_percent": 10})
        self.assertEqual(status, 400)

    def test_unknown_route_404(self):
        status, data, _ = self._get("/nope")
        self.assertEqual(status, 404)

    def test_split_between_people(self):
        status, data = self._post(
            "/api/split", {"bill": 100, "tip_percent": 20, "people": 4})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["tip"], 20.0)
        self.assertEqual(payload["total"], 120.0)
        self.assertEqual(payload["people"], 4)
        self.assertEqual(payload["per_person"], 30.0)

    def test_round_total_up(self):
        status, data = self._post(
            "/api/split",
            {"bill": 53.27, "tip_percent": 18, "round_total": True})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertTrue(payload["rounded"])
        self.assertEqual(payload["total"], 63.0)
        # tip absorbs the rounding so bill + tip == total
        self.assertEqual(round(53.27 + payload["tip"], 2), 63.0)

    def test_split_invalid_people(self):
        status, data = self._post(
            "/api/split", {"bill": 50, "tip_percent": 10, "people": 0})
        self.assertEqual(status, 400)

    def test_calculate_tip_unit(self):
        self.assertEqual(calculate_tip(200, 10), (20.0, 220.0))
        with self.assertRaises(ValueError):
            calculate_tip(-1, 10)
        with self.assertRaises(ValueError):
            calculate_tip(10, 200)

    # --- exact per-person shares (added) ---

    def test_split_shares_exact_uneven(self):
        # $100 + 0% over 3 people -> 33.34 / 33.33 / 33.33, summing exactly.
        shares = split_shares(100.0, 3)
        self.assertEqual(shares, [33.34, 33.33, 33.33])
        self.assertEqual(round(sum(shares), 2), 100.0)

    def test_split_shares_even(self):
        self.assertEqual(split_shares(120.0, 4), [30.0, 30.0, 30.0, 30.0])

    def test_split_shares_unit(self):
        # split_shares should round-trip the cents for arbitrary inputs.
        for total, count in [(62.86, 3), (10.0, 7), (0.0, 5), (99.99, 4)]:
            shares = split_shares(total, count)
            self.assertEqual(len(shares), count)
            self.assertEqual(round(sum(shares), 2), round(total, 2))

    def test_split_response_has_exact_shares(self):
        status, data = self._post(
            "/api/split", {"bill": 100, "tip_percent": 0, "people": 3})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["shares"], [33.34, 33.33, 33.33])
        self.assertEqual(payload["remainder_cents"], 1)
        self.assertEqual(payload["per_person_max"], 33.34)
        self.assertEqual(payload["per_person_min"], 33.33)
        self.assertEqual(round(sum(payload["shares"]), 2), payload["total"])

    def test_split_preserves_legacy_fields(self):
        # The original split contract must remain intact.
        status, data = self._post(
            "/api/split", {"bill": 100, "tip_percent": 20, "people": 4})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["per_person"], 30.0)
        self.assertEqual(payload["per_person_tip"], 5.0)
        self.assertEqual(len(payload["shares"]), 4)

    # --- tip presets endpoint (added) ---

    def test_presets_defaults(self):
        status, data = self._post("/api/presets", {"bill": 100})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["bill"], 100.0)
        percents = [o["tip_percent"] for o in payload["options"]]
        self.assertEqual(percents, [10.0, 15.0, 18.0, 20.0, 25.0])
        twenty = next(o for o in payload["options"] if o["tip_percent"] == 20.0)
        self.assertEqual(twenty["tip"], 20.0)
        self.assertEqual(twenty["total"], 120.0)

    def test_presets_custom_percents(self):
        status, data = self._post(
            "/api/presets", {"bill": 50, "percents": [5, 12.5]})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(len(payload["options"]), 2)
        self.assertEqual(payload["options"][0]["tip"], 2.5)
        self.assertEqual(payload["options"][1]["tip"], 6.25)

    def test_presets_invalid_bill(self):
        status, data = self._post("/api/presets", {"bill": -1})
        self.assertEqual(status, 400)

    def test_presets_invalid_percent(self):
        status, data = self._post(
            "/api/presets", {"bill": 50, "percents": [10, 200]})
        self.assertEqual(status, 400)

    def test_presets_unit(self):
        result = tip_presets(80, [10, 20])
        self.assertEqual(result["options"][0]["total"], 88.0)
        self.assertEqual(result["options"][1]["total"], 96.0)
        with self.assertRaises(ValueError):
            tip_presets(50, "abc")
        with self.assertRaises(ValueError):
            tip_presets(50, [])

    # --- reverse tip endpoint (added) ---

    def test_reverse_tip(self):
        status, data = self._post(
            "/api/reverse", {"bill": 100, "total": 118})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["tip"], 18.0)
        self.assertEqual(payload["tip_percent"], 18.0)
        self.assertEqual(payload["total"], 118.0)

    def test_reverse_tip_fractional_percent(self):
        status, data = self._post(
            "/api/reverse", {"bill": 53.27, "total": 63})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["tip"], 9.73)
        self.assertEqual(payload["tip_percent"], 18.27)

    def test_reverse_tip_target_below_bill(self):
        status, data = self._post(
            "/api/reverse", {"bill": 100, "total": 90})
        self.assertEqual(status, 400)

    def test_reverse_tip_zero_bill(self):
        status, data = self._post(
            "/api/reverse", {"bill": 0, "total": 10})
        self.assertEqual(status, 400)

    def test_reverse_tip_unit(self):
        result = reverse_tip(200, 230)
        self.assertEqual(result["tip"], 30.0)
        self.assertEqual(result["tip_percent"], 15.0)
        with self.assertRaises(ValueError):
            reverse_tip(None, 10)
        with self.assertRaises(ValueError):
            reverse_tip(-5, 10)

    # --- tax-aware totals (added) ---

    def test_tax_default_pretax(self):
        # Tip on the pre-tax subtotal; tax added on top.
        status, data = self._post(
            "/api/tax", {"bill": 100, "tip_percent": 20, "tax_percent": 8})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["subtotal"], 100.0)
        self.assertEqual(payload["tax"], 8.0)
        self.assertEqual(payload["tip"], 20.0)  # 20% of 100, not of 108
        self.assertEqual(payload["total"], 128.0)
        self.assertEqual(payload["tip_on"], "pretax")

    def test_tax_posttax_tip(self):
        # Tip taken on the post-tax amount.
        status, data = self._post(
            "/api/tax",
            {"bill": 100, "tip_percent": 20, "tax_percent": 8,
             "tip_on": "posttax"})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["tax"], 8.0)
        self.assertEqual(payload["tip"], 21.6)  # 20% of 108
        self.assertEqual(payload["total"], 129.6)

    def test_tax_defaults_to_zero(self):
        # Omitting tax_percent behaves like the plain tip calc.
        status, data = self._post(
            "/api/tax", {"bill": 50, "tip_percent": 10})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["tax"], 0.0)
        self.assertEqual(payload["tip"], 5.0)
        self.assertEqual(payload["total"], 55.0)

    def test_tax_invalid_tax_percent(self):
        status, data = self._post(
            "/api/tax", {"bill": 50, "tip_percent": 10, "tax_percent": 200})
        self.assertEqual(status, 400)

    def test_tax_invalid_tip_on(self):
        status, data = self._post(
            "/api/tax",
            {"bill": 50, "tip_percent": 10, "tip_on": "sideways"})
        self.assertEqual(status, 400)

    def test_tax_unit(self):
        result = calculate_with_tax(200, 15, 5)
        self.assertEqual(result["tax"], 10.0)
        self.assertEqual(result["tip"], 30.0)
        self.assertEqual(result["total"], 240.0)
        with self.assertRaises(ValueError):
            calculate_with_tax(-1, 10, 5)
        with self.assertRaises(ValueError):
            calculate_with_tax(10, 10, -5)

    # --- service-rating suggested tip (added) ---

    def test_suggest_excellent(self):
        status, data = self._post(
            "/api/suggest", {"bill": 100, "rating": 5})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["rating"], 5)
        self.assertEqual(payload["label"], "excellent")
        self.assertEqual(payload["tip_percent"], 25.0)
        self.assertEqual(payload["tip"], 25.0)
        self.assertEqual(payload["total"], 125.0)

    def test_suggest_poor(self):
        status, data = self._post(
            "/api/suggest", {"bill": 80, "rating": 1})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["tip_percent"], 10.0)
        self.assertEqual(payload["tip"], 8.0)
        self.assertEqual(payload["total"], 88.0)

    def test_suggest_invalid_rating(self):
        status, data = self._post(
            "/api/suggest", {"bill": 100, "rating": 9})
        self.assertEqual(status, 400)

    def test_suggest_fractional_rating(self):
        status, data = self._post(
            "/api/suggest", {"bill": 100, "rating": 3.5})
        self.assertEqual(status, 400)

    def test_suggest_unit(self):
        self.assertEqual(suggest_tip_percent(4), 4)
        self.assertEqual(suggest_tip("50", 3)["tip"], 9.0)  # 18% of 50
        with self.assertRaises(ValueError):
            suggest_tip_percent(0)
        with self.assertRaises(ValueError):
            suggest_tip_percent("x")

    # --- weighted (uneven) splits (added) ---

    def test_split_weighted_endpoint(self):
        # $120 split 1:1:2 -> 30 / 30 / 60.
        status, data = self._post(
            "/api/split",
            {"bill": 100, "tip_percent": 20, "weights": [1, 1, 2]})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["total"], 120.0)
        self.assertEqual(payload["people"], 3)
        self.assertEqual(payload["shares"], [30.0, 30.0, 60.0])
        self.assertEqual(payload["weights"], [1.0, 1.0, 2.0])
        self.assertEqual(round(sum(payload["shares"]), 2), 120.0)

    def test_split_weighted_exact_cents(self):
        # Uneven, non-divisible total still sums exactly.
        shares = split_weighted(100.0, [1, 1, 1])
        self.assertEqual(round(sum(shares), 2), 100.0)
        self.assertEqual(len(shares), 3)
        # leftover cent goes to a largest-remainder payer
        self.assertEqual(sorted(shares), [33.33, 33.33, 33.34])

    def test_split_weighted_invalid_weight(self):
        status, data = self._post(
            "/api/split",
            {"bill": 100, "tip_percent": 20, "weights": [1, 0, 2]})
        self.assertEqual(status, 400)

    def test_split_weighted_empty(self):
        with self.assertRaises(ValueError):
            split_weighted(100.0, [])
        with self.assertRaises(ValueError):
            split_weighted(100.0, "nope")

    def test_split_weighted_unit(self):
        for total, weights in [(62.86, [1, 2, 3]), (10.0, [5, 1]),
                               (0.0, [1, 1]), (99.99, [2, 2, 1, 4])]:
            shares = split_weighted(total, weights)
            self.assertEqual(len(shares), len(weights))
            self.assertEqual(round(sum(shares), 2), round(total, 2))


    # --- itemized bill split (added) ---

    def test_itemize_basic_pretax(self):
        # Two diners, items 40 and 60; 20% tip on the $100 pre-tax subtotal.
        status, data = self._post(
            "/api/itemize",
            {"people": [
                {"name": "Alice", "items": [40]},
                {"name": "Bob", "items": [60]},
            ], "tip_percent": 20})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["subtotal"], 100.0)
        self.assertEqual(payload["tip"], 20.0)
        self.assertEqual(payload["total"], 120.0)
        self.assertEqual(payload["people"], 2)
        alice, bob = payload["breakdown"]
        self.assertEqual(alice["name"], "Alice")
        self.assertEqual(alice["subtotal"], 40.0)
        self.assertEqual(alice["tip"], 8.0)   # 40% of the 20 tip
        self.assertEqual(alice["total"], 48.0)
        self.assertEqual(bob["tip"], 12.0)     # 60% of the 20 tip
        self.assertEqual(bob["total"], 72.0)

    def test_itemize_with_tax(self):
        # Tip and tax both apportioned by each diner's share of the bill.
        status, data = self._post(
            "/api/itemize",
            {"people": [
                {"name": "A", "items": [50, 25]},   # 75
                {"name": "B", "items": [25]},        # 25
            ], "tip_percent": 20, "tax_percent": 10})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["subtotal"], 100.0)
        self.assertEqual(payload["tax"], 10.0)
        self.assertEqual(payload["tip"], 20.0)
        self.assertEqual(payload["total"], 130.0)
        a, b = payload["breakdown"]
        self.assertEqual(a["subtotal"], 75.0)
        self.assertEqual(a["tax"], 7.5)
        self.assertEqual(a["tip"], 15.0)
        self.assertEqual(a["total"], 97.5)
        self.assertEqual(b["total"], 32.5)
        # per-person totals sum exactly to the grand total
        self.assertEqual(
            round(sum(p["total"] for p in payload["breakdown"]), 2),
            payload["total"])

    def test_itemize_exact_cents(self):
        # Indivisible tip cents are handed out so the breakdown sums exactly.
        status, data = self._post(
            "/api/itemize",
            {"people": [
                {"items": [10]},
                {"items": [10]},
                {"items": [10]},
            ], "tip_percent": 10})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["tip"], 3.0)
        self.assertEqual(
            round(sum(p["total"] for p in payload["breakdown"]), 2),
            payload["total"])
        # default names are assigned when omitted
        self.assertEqual(payload["breakdown"][0]["name"], "Person 1")

    def test_itemize_zero_bill(self):
        status, data = self._post(
            "/api/itemize",
            {"people": [{"items": []}, {"items": [0]}], "tip_percent": 20})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["total"], 0.0)
        self.assertEqual(payload["breakdown"][0]["total"], 0.0)
        self.assertEqual(payload["breakdown"][1]["total"], 0.0)

    def test_itemize_invalid_people(self):
        status, data = self._post("/api/itemize", {"people": [], "tip_percent": 10})
        self.assertEqual(status, 400)
        status, data = self._post(
            "/api/itemize", {"people": "nope", "tip_percent": 10})
        self.assertEqual(status, 400)

    def test_itemize_invalid_item(self):
        status, data = self._post(
            "/api/itemize",
            {"people": [{"items": [-5]}], "tip_percent": 10})
        self.assertEqual(status, 400)
        status, data = self._post(
            "/api/itemize",
            {"people": [{"items": "x"}], "tip_percent": 10})
        self.assertEqual(status, 400)

    def test_itemize_invalid_tip_percent(self):
        status, data = self._post(
            "/api/itemize",
            {"people": [{"items": [10]}], "tip_percent": 200})
        self.assertEqual(status, 400)

    def test_itemize_unit(self):
        result = split_itemized(
            [{"name": "X", "items": [30]}, {"name": "Y", "items": [70]}], 10)
        self.assertEqual(result["tip"], 10.0)
        self.assertEqual(result["breakdown"][0]["tip"], 3.0)
        self.assertEqual(result["breakdown"][1]["tip"], 7.0)
        with self.assertRaises(ValueError):
            split_itemized([{"items": [10]}], -1)   # bad tip percent
        with self.assertRaises(ValueError):
            split_itemized([42], 10)                 # non-dict person

    def test_largest_remainder_unit(self):
        # Sums exactly and biggest fractional shares win the leftover cents.
        self.assertEqual(_largest_remainder(100, [1, 1, 1]), [34, 33, 33])
        self.assertEqual(sum(_largest_remainder(101, [3, 5, 2])), 101)
        self.assertEqual(_largest_remainder(0, [1, 2, 3]), [0, 0, 0])

    # --- configurable total rounding (added) ---

    def test_round_total_to_modes_unit(self):
        # $53.27 bill, total 62.86 -> up 63, down 62, nearest 63.
        self.assertEqual(round_total_to(53.27, 62.86, "up"), (9.73, 63.0))
        self.assertEqual(round_total_to(53.27, 62.86, "down"), (8.73, 62.0))
        self.assertEqual(round_total_to(53.27, 62.86, "nearest"), (9.73, 63.0))
        # nearest rounds a .5 step up.
        self.assertEqual(round_total_to(0, 62.5, "nearest"), (63.0, 63.0))

    def test_round_total_to_increment_unit(self):
        # Round to the nearest $5 and to quarters.
        self.assertEqual(round_total_to(0, 62.86, "up", 5.0), (65.0, 65.0))
        self.assertEqual(round_total_to(0, 62.86, "down", 5.0), (60.0, 60.0))
        self.assertEqual(round_total_to(0, 62.10, "nearest", 0.25),
                         (62.0, 62.0))

    def test_round_total_to_never_below_bill(self):
        # Rounding down past the bill clamps to the bill (tip stays >= 0).
        tip, total = round_total_to(53.27, 62.86, "down", 100.0)
        self.assertEqual(total, 53.27)
        self.assertEqual(tip, 0.0)

    def test_round_total_to_invalid_unit(self):
        with self.assertRaises(ValueError):
            round_total_to(10, 12, "sideways")
        with self.assertRaises(ValueError):
            round_total_to(10, 12, "up", 0)
        with self.assertRaises(ValueError):
            round_total_to(10, 12, "up", -5)

    def test_round_total_up_still_rounds_up(self):
        # Backward-compat wrapper unchanged.
        self.assertEqual(round_total_up(53.27, 62.86), (9.73, 63.0))

    def test_split_round_mode_down(self):
        status, data = self._post(
            "/api/split",
            {"bill": 53.27, "tip_percent": 18, "round_total": True,
             "round_mode": "down"})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertTrue(payload["rounded"])
        self.assertEqual(payload["total"], 62.0)
        self.assertEqual(payload["round_mode"], "down")
        self.assertEqual(payload["round_increment"], 1.0)
        self.assertEqual(round(53.27 + payload["tip"], 2), 62.0)

    def test_split_round_mode_nearest_five(self):
        status, data = self._post(
            "/api/split",
            {"bill": 50, "tip_percent": 18, "round_total": True,
             "round_mode": "nearest", "round_increment": 5})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        # 50 + 18% = 59.0 -> nearest $5 is 60.
        self.assertEqual(payload["total"], 60.0)
        self.assertEqual(payload["round_increment"], 5.0)

    def test_split_round_mode_invalid(self):
        status, data = self._post(
            "/api/split",
            {"bill": 50, "tip_percent": 18, "round_total": True,
             "round_mode": "nope"})
        self.assertEqual(status, 400)

    def test_split_unrounded_has_no_round_fields(self):
        # round_mode/round_increment only appear when actually rounded.
        status, data = self._post(
            "/api/split", {"bill": 100, "tip_percent": 20, "people": 4})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertNotIn("round_mode", payload)
        self.assertNotIn("round_increment", payload)

    # --- currency formatting (added) ---

    def test_format_money_unit(self):
        self.assertEqual(format_money(1234.5), "$1,234.50")
        self.assertEqual(format_money(0), "$0.00")
        self.assertEqual(format_money(-5), "-$5.00")
        self.assertEqual(format_money(1000000), "$1,000,000.00")
        self.assertEqual(format_money(9.999), "$10.00")
        self.assertEqual(format_money(5, "€"), "€5.00")
        with self.assertRaises(ValueError):
            format_money("abc")
        with self.assertRaises(ValueError):
            format_money(5, "")

    # --- shareable receipt endpoint (added) ---

    def test_receipt_basic(self):
        status, data = self._post(
            "/api/receipt", {"bill": 100, "tip_percent": 20})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["subtotal"], 100.0)
        self.assertEqual(payload["tip"], 20.0)
        self.assertEqual(payload["total"], 120.0)
        self.assertEqual(payload["people"], 1)
        self.assertIn("Receipt", payload["text"])
        self.assertIn("$120.00", payload["text"])
        self.assertIn("Tip (20%)", payload["text"])
        # No tax line when there is no tax.
        self.assertNotIn("Tax", payload["text"])

    def test_receipt_with_tax_and_people(self):
        status, data = self._post(
            "/api/receipt",
            {"bill": 100, "tip_percent": 20, "tax_percent": 8, "people": 4})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["tax"], 8.0)
        self.assertEqual(payload["total"], 128.0)
        self.assertEqual(payload["people"], 4)
        self.assertEqual(len(payload["shares"]), 4)
        self.assertEqual(round(sum(payload["shares"]), 2), payload["total"])
        self.assertIn("Tax (8%)", payload["text"])
        self.assertIn("Person 4", payload["text"])

    def test_receipt_weighted_and_symbol(self):
        status, data = self._post(
            "/api/receipt",
            {"bill": 100, "tip_percent": 20, "weights": [1, 1, 2],
             "symbol": "£", "title": "Dinner"})
        self.assertEqual(status, 200)
        payload = json.loads(data.decode("utf-8"))
        self.assertEqual(payload["people"], 3)
        self.assertEqual(payload["shares"], [30.0, 30.0, 60.0])
        self.assertTrue(payload["text"].startswith("Dinner"))
        self.assertIn("£60.00", payload["text"])

    def test_receipt_invalid_bill(self):
        status, data = self._post(
            "/api/receipt", {"bill": -1, "tip_percent": 20})
        self.assertEqual(status, 400)

    def test_receipt_invalid_symbol(self):
        status, data = self._post(
            "/api/receipt", {"bill": 100, "tip_percent": 20, "symbol": ""})
        self.assertEqual(status, 400)

    def test_receipt_unit(self):
        result = build_receipt(50, 10, tax_percent=10)
        self.assertEqual(result["subtotal"], 50.0)
        self.assertEqual(result["tax"], 5.0)
        self.assertEqual(result["tip"], 5.0)
        self.assertEqual(result["total"], 60.0)
        self.assertEqual(result["lines"][0], "Receipt")
        # per-person totals from a weighted receipt sum exactly to the total.
        weighted = build_receipt(99.99, 18, weights=[2, 1, 1])
        self.assertEqual(round(sum(weighted["shares"]), 2), weighted["total"])
        with self.assertRaises(ValueError):
            build_receipt(100, 20, title="")


if __name__ == "__main__":
    unittest.main()
