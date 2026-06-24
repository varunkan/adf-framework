#!/usr/bin/env python3
"""Tests for the tip calculator — core domain logic and HTTP API."""
import json
import threading
import unittest
import urllib.request
import urllib.error

from http.server import ThreadingHTTPServer

import server
from server import (
    calculate_tip,
    reverse_tip,
    round_up_split,
    suggest_tips,
    split_by_shares,
    split_by_items,
    settle_up,
    tip_for_rating,
    change_due,
    combine_checks,
    apply_discount,
    tip_pool,
    split_with_caps,
    build_bill,
    service_charge,
    convert_currency,
    auto_gratuity,
    split_by_percentage,
    tip_for_target_per_person,
    round_total_to,
    split_comped,
    gross_up_tip,
    split_shared_items,
    recommend_regional_tip,
    charity_round_up,
    tip_excluding,
    tip_by_diner,
    TipError,
    Handler,
)


# ---------------------------------------------------------------------------
# Domain logic tests
# ---------------------------------------------------------------------------


class TestCalculateTip(unittest.TestCase):
    # TC-1.1 — REQ-001 happy path: tip and total from bill + percent
    def test_basic_tip_and_total(self):
        r = calculate_tip(100, 15)
        self.assertEqual(r["tip"], 15.0)
        self.assertEqual(r["total"], 115.0)

    def test_twenty_percent(self):
        r = calculate_tip(50, 20)
        self.assertEqual(r["tip"], 10.0)
        self.assertEqual(r["total"], 60.0)

    def test_rounding_to_cents(self):
        r = calculate_tip(53.27, 18)
        self.assertEqual(r["tip"], 9.59)      # 9.5886 -> 9.59
        self.assertEqual(r["total"], 62.86)

    def test_zero_tip(self):
        r = calculate_tip(80, 0)
        self.assertEqual(r["tip"], 0.0)
        self.assertEqual(r["total"], 80.0)

    def test_zero_bill(self):
        r = calculate_tip(0, 20)
        self.assertEqual(r["tip"], 0.0)
        self.assertEqual(r["total"], 0.0)

    # TC-2.1 — REQ-002 happy path: split across people
    def test_split_even(self):
        r = calculate_tip(100, 20, 4)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["total_per_person"], 30.0)
        self.assertEqual(r["tip_per_person"], 5.0)

    def test_split_default_one_person(self):
        r = calculate_tip(100, 10)
        self.assertEqual(r["people"], 1)
        self.assertEqual(r["total_per_person"], r["total"])

    def test_split_with_rounding(self):
        r = calculate_tip(100, 15, 3)
        self.assertEqual(r["total"], 115.0)
        self.assertEqual(r["total_per_person"], 38.33)  # 115/3 = 38.333

    def test_string_inputs_coerced(self):
        r = calculate_tip("100", "15", "2")
        self.assertEqual(r["total"], 115.0)
        self.assertEqual(r["total_per_person"], 57.5)

    # TC-1.2 / TC-2.2 — edge & failure: fail safe with clear errors
    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            calculate_tip(-5, 15)

    def test_negative_tip_rejected(self):
        with self.assertRaises(TipError):
            calculate_tip(100, -1)

    def test_zero_people_rejected(self):
        with self.assertRaises(TipError):
            calculate_tip(100, 15, 0)

    def test_fractional_people_rejected(self):
        with self.assertRaises(TipError):
            calculate_tip(100, 15, 2.5)

    def test_non_numeric_bill_rejected(self):
        with self.assertRaises(TipError):
            calculate_tip("abc", 15)

    def test_bool_bill_rejected(self):
        with self.assertRaises(TipError):
            calculate_tip(True, 15)

    def test_none_bill_rejected(self):
        with self.assertRaises(TipError):
            calculate_tip(None, 15)

    def test_nan_rejected(self):
        with self.assertRaises(TipError):
            calculate_tip(float("nan"), 15)


# ---------------------------------------------------------------------------
# Tax-aware tipping (REQ-001 extension)
# ---------------------------------------------------------------------------


class TestTaxAwareTip(unittest.TestCase):
    def test_default_no_tax_unchanged(self):
        # Backwards compatible: tax defaults to 0, tip_on to "total".
        r = calculate_tip(100, 15)
        self.assertEqual(r["tip"], 15.0)
        self.assertEqual(r["total"], 115.0)
        self.assertEqual(r["tax"], 0.0)
        self.assertEqual(r["subtotal"], 100.0)
        self.assertEqual(r["tip_on"], "total")

    def test_tip_on_subtotal_excludes_tax(self):
        # Bill 110 includes 10 tax; tipping 20% on the 100 subtotal -> 20 tip.
        r = calculate_tip(110, 20, tax=10, tip_on="subtotal")
        self.assertEqual(r["subtotal"], 100.0)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["total"], 130.0)

    def test_tip_on_total_includes_tax(self):
        # Same bill, but tipping on the full tax-inclusive amount -> 22 tip.
        r = calculate_tip(110, 20, tax=10, tip_on="total")
        self.assertEqual(r["tip"], 22.0)
        self.assertEqual(r["total"], 132.0)

    def test_tip_on_aliases(self):
        a = calculate_tip(110, 20, tax=10, tip_on="pretax")
        b = calculate_tip(110, 20, tax=10, tip_on="net")
        self.assertEqual(a["tip"], 20.0)
        self.assertEqual(b["tip"], 20.0)

    def test_tax_string_coerced(self):
        r = calculate_tip("110", "20", tax="10", tip_on="subtotal")
        self.assertEqual(r["tip"], 20.0)

    def test_negative_tax_rejected(self):
        with self.assertRaises(TipError):
            calculate_tip(100, 15, tax=-1)

    def test_tax_exceeding_bill_rejected(self):
        with self.assertRaises(TipError):
            calculate_tip(100, 15, tax=150)

    def test_bad_tip_on_rejected(self):
        with self.assertRaises(TipError):
            calculate_tip(100, 15, tip_on="sideways")

    def test_subtotal_split_across_people(self):
        r = calculate_tip(110, 20, people=2, tax=10, tip_on="subtotal")
        self.assertEqual(r["total"], 130.0)
        self.assertEqual(r["total_per_person"], 65.0)


# ---------------------------------------------------------------------------
# Reverse tip calculator (REQ-001 extension)
# ---------------------------------------------------------------------------


class TestReverseTip(unittest.TestCase):
    def test_basic_reverse(self):
        r = reverse_tip(100, 120)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["effective_tip_percent"], 20.0)
        self.assertEqual(r["total"], 120.0)

    def test_reverse_split(self):
        r = reverse_tip(100, 120, 4)
        self.assertEqual(r["total_per_person"], 30.0)
        self.assertEqual(r["tip_per_person"], 5.0)

    def test_reverse_exact_bill_zero_tip(self):
        r = reverse_tip(100, 100)
        self.assertEqual(r["tip"], 0.0)
        self.assertEqual(r["effective_tip_percent"], 0.0)

    def test_reverse_fractional_percent(self):
        r = reverse_tip(53.27, 60)
        self.assertEqual(r["tip"], 6.73)
        self.assertEqual(r["effective_tip_percent"], 12.63)  # 6.73/53.27

    def test_target_below_bill_rejected(self):
        with self.assertRaises(TipError):
            reverse_tip(100, 90)

    def test_reverse_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            reverse_tip(-1, 100)

    def test_reverse_zero_people_rejected(self):
        with self.assertRaises(TipError):
            reverse_tip(100, 120, 0)


# ---------------------------------------------------------------------------
# Round-up split (REQ-002 extension)
# ---------------------------------------------------------------------------


class TestRoundUpSplit(unittest.TestCase):
    def test_round_up_to_dollar(self):
        # 115 / 3 = 38.33 -> rounds each share up to 39.
        r = round_up_split(100, 15, 3)
        self.assertEqual(r["per_person"], 39.0)
        self.assertEqual(r["collected"], 117.0)
        self.assertEqual(r["surplus"], 2.0)

    def test_exact_division_no_surplus(self):
        # 120 / 4 = 30 exactly -> no rounding surplus.
        r = round_up_split(100, 20, 4)
        self.assertEqual(r["per_person"], 30.0)
        self.assertEqual(r["surplus"], 0.0)

    def test_round_up_to_nickel(self):
        # 62.86 / 1 -> next nickel is 62.90.
        r = round_up_split(53.27, 18, 1, nearest=0.05)
        self.assertEqual(r["per_person"], 62.9)
        self.assertEqual(r["surplus"], 0.04)

    def test_effective_percent_grows_with_surplus(self):
        r = round_up_split(100, 15, 3)
        self.assertGreater(r["effective_tip_percent"], 15.0)
        self.assertEqual(r["effective_tip_percent"], 17.0)  # (117-100)/100

    def test_nearest_must_be_positive(self):
        with self.assertRaises(TipError):
            round_up_split(100, 15, 3, nearest=0)

    def test_round_up_invalid_people(self):
        with self.assertRaises(TipError):
            round_up_split(100, 15, 0)


# ---------------------------------------------------------------------------
# Tip suggestions (REQ-001 extension)
# ---------------------------------------------------------------------------


class TestSuggestTips(unittest.TestCase):
    def test_default_tiers(self):
        r = suggest_tips(100)
        self.assertEqual(r["bill"], 100.0)
        self.assertEqual([t["tip_percent"] for t in r["tiers"]], [10, 15, 18, 20, 25])

    def test_tier_values_match_calculate(self):
        r = suggest_tips(100, 2)
        twenty = next(t for t in r["tiers"] if t["tip_percent"] == 20)
        self.assertEqual(twenty["tip"], 20.0)
        self.assertEqual(twenty["total"], 120.0)
        self.assertEqual(twenty["total_per_person"], 60.0)

    def test_custom_percents(self):
        r = suggest_tips(50, percents=[0, 5])
        self.assertEqual([t["tip_percent"] for t in r["tiers"]], [0, 5])
        self.assertEqual(r["tiers"][1]["tip"], 2.5)

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            suggest_tips(-1)

    def test_string_percents_rejected(self):
        with self.assertRaises(TipError):
            suggest_tips(100, percents="oops")


# ---------------------------------------------------------------------------
# Weighted share split (REQ-002 extension)
# ---------------------------------------------------------------------------


class TestSplitByShares(unittest.TestCase):
    def test_equal_shares(self):
        r = split_by_shares(100, 20, [1, 1])
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["amounts"], [60.0, 60.0])

    def test_weighted_shares_sum_exactly(self):
        r = split_by_shares(100, 20, [1, 1, 2])
        self.assertEqual(sum(r["amounts"]), r["total"])

    def test_largest_remainder_distribution(self):
        # 115 / 3 weights -> cents must still sum to 11500.
        r = split_by_shares(100, 15, [1, 1, 1])
        self.assertEqual(round(sum(r["amounts"]), 2), 115.0)

    def test_empty_shares_rejected(self):
        with self.assertRaises(TipError):
            split_by_shares(100, 15, [])

    def test_zero_weight_rejected(self):
        with self.assertRaises(TipError):
            split_by_shares(100, 15, [1, 0])

    def test_non_list_shares_rejected(self):
        with self.assertRaises(TipError):
            split_by_shares(100, 15, "abc")


# ---------------------------------------------------------------------------
# Itemized split (REQ-002 extension)
# ---------------------------------------------------------------------------


class TestSplitByItems(unittest.TestCase):
    def test_each_pays_own_items(self):
        # No tax, no tip: each diner pays exactly what they ordered.
        r = split_by_items([[10], [20], [30]], 0)
        self.assertEqual([p["amount"] for p in r["people"]], [10.0, 20.0, 30.0])
        self.assertEqual(r["total"], 60.0)

    def test_tip_apportioned_by_subtotal(self):
        # 20% tip on a 60 food bill = 12 tip, split 1:2:3 by what each ordered.
        r = split_by_items([[10], [20], [30]], 20)
        self.assertEqual(r["tip"], 12.0)
        self.assertEqual([p["tip"] for p in r["people"]], [2.0, 4.0, 6.0])
        self.assertEqual([p["amount"] for p in r["people"]], [12.0, 24.0, 36.0])

    def test_amounts_sum_exactly_to_total(self):
        r = split_by_items([[12.5, 4], [9], [20, 5.25]], 18, tax=3.33)
        self.assertEqual(round(sum(p["amount"] for p in r["people"]), 2), r["total"])

    def test_tax_apportioned(self):
        r = split_by_items([[50], [50]], 0, tax=10)
        self.assertEqual([p["tax"] for p in r["people"]], [5.0, 5.0])
        self.assertEqual(r["total"], 110.0)

    def test_tip_on_total_includes_tax(self):
        r = split_by_items([[100]], 10, tax=10, tip_on="total")
        self.assertEqual(r["tip"], 11.0)   # 10% of 110
        self.assertEqual(r["total"], 121.0)

    def test_multiple_items_per_diner(self):
        r = split_by_items([[10, 5, 5], [30]], 0)
        self.assertEqual(r["people"][0]["subtotal"], 20.0)
        self.assertEqual(r["people"][1]["subtotal"], 30.0)

    def test_zero_subtotal_diner(self):
        # A diner who ordered nothing pays nothing of the food/tip.
        r = split_by_items([[40], []], 25)
        self.assertEqual(r["people"][1]["amount"], 0.0)
        self.assertEqual(r["people"][0]["amount"], 50.0)

    def test_empty_people_items_rejected(self):
        with self.assertRaises(TipError):
            split_by_items([], 15)

    def test_negative_item_rejected(self):
        with self.assertRaises(TipError):
            split_by_items([[10, -1]], 15)

    def test_non_list_people_items_rejected(self):
        with self.assertRaises(TipError):
            split_by_items("nope", 15)

    def test_diner_entry_must_be_list(self):
        with self.assertRaises(TipError):
            split_by_items([10, 20], 15)

    def test_negative_tip_rejected(self):
        with self.assertRaises(TipError):
            split_by_items([[10]], -5)


# ---------------------------------------------------------------------------
# Settle up — who owes whom (REQ-002 extension)
# ---------------------------------------------------------------------------


class TestSettleUp(unittest.TestCase):
    def test_one_payer_even_split(self):
        # Bill 100 + 20% = 120, one diner fronted it all, 3-way even.
        r = settle_up(100, 20, [120, 0, 0])
        self.assertEqual(r["total"], 120.0)
        self.assertEqual([p["owed"] for p in r["people"]], [40.0, 40.0, 40.0])
        self.assertEqual([p["balance"] for p in r["people"]], [80.0, -40.0, -40.0])
        # The two debtors each repay diner 0.
        self.assertEqual(r["transfers"], [
            {"from": 1, "to": 0, "amount": 40.0},
            {"from": 2, "to": 0, "amount": 40.0},
        ])

    def test_already_even_no_transfers(self):
        r = settle_up(100, 20, [40, 40, 40])
        self.assertEqual(r["transfers"], [])
        self.assertEqual([p["balance"] for p in r["people"]], [0.0, 0.0, 0.0])

    def test_weighted_shares(self):
        # Third diner owes double; diner 0 paid the whole 120.
        r = settle_up(100, 20, [120, 0, 0], shares=[1, 1, 2])
        self.assertEqual([p["owed"] for p in r["people"]], [30.0, 30.0, 60.0])
        self.assertEqual(r["transfers"], [
            {"from": 2, "to": 0, "amount": 60.0},
            {"from": 1, "to": 0, "amount": 30.0},
        ])

    def test_two_people(self):
        r = settle_up(50, 0, [50, 0])
        self.assertEqual(r["transfers"], [{"from": 1, "to": 0, "amount": 25.0}])

    def test_transfers_settle_everyone(self):
        # After applying transfers every diner's net contribution == their share.
        r = settle_up(100, 15, [115, 0, 0])
        net = [p["paid"] for p in r["people"]]
        for t in r["transfers"]:
            net[t["from"]] += t["amount"]
            net[t["to"]] -= t["amount"]
        owed = [p["owed"] for p in r["people"]]
        for got, want in zip(net, owed):
            self.assertAlmostEqual(got, want, places=2)

    def test_transfer_amounts_sum_to_debt(self):
        # 115 / 3 -> uneven shares; transfers must reconcile to the cent.
        r = settle_up(100, 15, [115, 0, 0])
        debt = sum(-p["balance"] for p in r["people"] if p["balance"] < 0)
        self.assertEqual(round(sum(t["amount"] for t in r["transfers"]), 2),
                         round(debt, 2))

    def test_largest_remainder_owed_sums_to_total(self):
        r = settle_up(100, 15, [50, 40, 25])  # 115 total covered
        self.assertEqual(round(sum(p["owed"] for p in r["people"]), 2), 115.0)

    def test_string_inputs_coerced(self):
        r = settle_up("100", "20", ["120", "0", "0"])
        self.assertEqual(r["total"], 120.0)

    def test_payments_must_cover_total(self):
        with self.assertRaises(TipError):
            settle_up(100, 20, [100, 0, 0])  # only 100 of 120 paid

    def test_overpayment_rejected(self):
        with self.assertRaises(TipError):
            settle_up(100, 20, [130, 0, 0])  # 130 of 120

    def test_empty_paid_rejected(self):
        with self.assertRaises(TipError):
            settle_up(100, 20, [])

    def test_negative_payment_rejected(self):
        with self.assertRaises(TipError):
            settle_up(100, 20, [130, -10, 0])

    def test_non_list_paid_rejected(self):
        with self.assertRaises(TipError):
            settle_up(100, 20, "nope")

    def test_shares_length_mismatch_rejected(self):
        with self.assertRaises(TipError):
            settle_up(100, 20, [120, 0, 0], shares=[1, 1])

    def test_zero_share_rejected(self):
        with self.assertRaises(TipError):
            settle_up(100, 20, [120, 0, 0], shares=[1, 1, 0])

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            settle_up(-1, 20, [0])

    def test_negative_tip_rejected(self):
        with self.assertRaises(TipError):
            settle_up(100, -5, [100])


# ---------------------------------------------------------------------------
# Tip by service rating (REQ-001 extension)
# ---------------------------------------------------------------------------


class TestTipForRating(unittest.TestCase):
    def test_whole_star_maps_to_scale(self):
        # 5★ -> 20% on a 100 bill.
        r = tip_for_rating(100, 5)
        self.assertEqual(r["tip_percent"], 20.0)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["rating"], 5.0)

    def test_one_star_low_tip(self):
        r = tip_for_rating(100, 1)
        self.assertEqual(r["tip_percent"], 10.0)
        self.assertEqual(r["total"], 110.0)

    def test_three_star_mid_tip(self):
        r = tip_for_rating(200, 3)
        self.assertEqual(r["tip_percent"], 15.0)
        self.assertEqual(r["tip"], 30.0)

    def test_half_star_interpolates(self):
        # 4.5★ -> halfway between 18% and 20% = 19%.
        r = tip_for_rating(100, 4.5)
        self.assertEqual(r["tip_percent"], 19.0)
        self.assertEqual(r["tip"], 19.0)

    def test_rating_respects_people_split(self):
        r = tip_for_rating(100, 5, people=4)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["total_per_person"], 30.0)

    def test_rating_string_coerced(self):
        r = tip_for_rating("100", "5")
        self.assertEqual(r["tip"], 20.0)

    def test_rating_below_one_rejected(self):
        with self.assertRaises(TipError):
            tip_for_rating(100, 0.5)

    def test_rating_above_five_rejected(self):
        with self.assertRaises(TipError):
            tip_for_rating(100, 6)

    def test_rating_non_numeric_rejected(self):
        with self.assertRaises(TipError):
            tip_for_rating(100, "great")


# ---------------------------------------------------------------------------
# Cash change with denomination breakdown (REQ-002 extension)
# ---------------------------------------------------------------------------


class TestChangeDue(unittest.TestCase):
    def test_basic_change(self):
        r = change_due(115, 120)
        self.assertEqual(r["change"], 5.0)
        self.assertFalse(r["exact"])

    def test_exact_payment_no_change(self):
        r = change_due(100, 100)
        self.assertEqual(r["change"], 0.0)
        self.assertTrue(r["exact"])
        self.assertEqual(r["breakdown"], [])

    def test_denomination_breakdown(self):
        # 137.89 -> $100 + $20 + $10 + $5 + $1 + 50c(25c*2) + 25c... compute change.
        r = change_due(0, 137.89)
        # rebuild the change from the breakdown and confirm it matches.
        rebuilt = sum(b["value"] * b["count"] for b in r["breakdown"])
        self.assertEqual(round(rebuilt, 2), 137.89)

    def test_breakdown_is_minimal_for_canonical_set(self):
        # 41.67 -> $20*2, $1*1, 25c*2, 10c*1, 5c*1, 1c*2 = 9 pieces.
        r = change_due(0, 41.67)
        total_pieces = sum(b["count"] for b in r["breakdown"])
        self.assertEqual(total_pieces, 9)

    def test_change_string_coerced(self):
        r = change_due("100", "150.5")
        self.assertEqual(r["change"], 50.5)

    def test_short_payment_rejected(self):
        with self.assertRaises(TipError):
            change_due(120, 100)

    def test_negative_total_rejected(self):
        with self.assertRaises(TipError):
            change_due(-1, 10)

    def test_negative_paid_rejected(self):
        with self.assertRaises(TipError):
            change_due(10, -1)


# ---------------------------------------------------------------------------
# Combine multiple checks (REQ-002 extension)
# ---------------------------------------------------------------------------


class TestCombineChecks(unittest.TestCase):
    def test_combine_totals(self):
        r = combine_checks([
            {"bill": 40, "tip_percent": 20},
            {"bill": 60, "tip_percent": 20},
        ])
        self.assertEqual(r["bill"], 100.0)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["count"], 2)

    def test_per_check_breakdown_preserved(self):
        r = combine_checks([
            {"bill": 40, "tip_percent": 10},
            {"bill": 60, "tip_percent": 25},
        ])
        self.assertEqual(r["checks"][0]["tip"], 4.0)
        self.assertEqual(r["checks"][1]["tip"], 15.0)

    def test_split_across_people_sums_exactly(self):
        r = combine_checks([
            {"bill": 40, "tip_percent": 18},
            {"bill": 60, "tip_percent": 20},
            {"bill": 15, "tip_percent": 15},
        ], people=3)
        self.assertEqual(round(sum(r["amounts"]), 2), r["total"])
        self.assertEqual(len(r["amounts"]), 3)

    def test_different_tip_rates_per_check(self):
        r = combine_checks([
            {"bill": 100, "tip_percent": 0},
            {"bill": 100, "tip_percent": 50},
        ])
        self.assertEqual(r["tip"], 50.0)
        self.assertEqual(r["total"], 250.0)

    def test_check_with_tax(self):
        r = combine_checks([
            {"bill": 110, "tip_percent": 20, "tax": 10, "tip_on": "subtotal"},
        ])
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["total"], 130.0)

    def test_default_tip_percent_zero(self):
        r = combine_checks([{"bill": 50}])
        self.assertEqual(r["tip"], 0.0)
        self.assertEqual(r["total"], 50.0)

    def test_single_person_total_per_person(self):
        r = combine_checks([{"bill": 100, "tip_percent": 20}])
        self.assertEqual(r["total_per_person"], 120.0)

    def test_empty_checks_rejected(self):
        with self.assertRaises(TipError):
            combine_checks([])

    def test_non_list_checks_rejected(self):
        with self.assertRaises(TipError):
            combine_checks("nope")

    def test_non_object_check_rejected(self):
        with self.assertRaises(TipError):
            combine_checks([42])

    def test_invalid_people_rejected(self):
        with self.assertRaises(TipError):
            combine_checks([{"bill": 100, "tip_percent": 20}], people=0)

    def test_bad_bill_in_check_rejected(self):
        with self.assertRaises(TipError):
            combine_checks([{"bill": -5, "tip_percent": 20}])


# ---------------------------------------------------------------------------
# Coupon / discount before tipping (REQ-001 extension)
# ---------------------------------------------------------------------------


class TestApplyDiscount(unittest.TestCase):
    def test_flat_amount_discount(self):
        # $10 off a $100 bill -> tip on the discounted $90.
        r = apply_discount(100, 20, 10)
        self.assertEqual(r["savings"], 10.0)
        self.assertEqual(r["discounted_bill"], 90.0)
        self.assertEqual(r["tip"], 18.0)       # 20% of 90
        self.assertEqual(r["total"], 108.0)

    def test_percent_discount(self):
        # 25% off a $80 bill -> $60 discounted, 15% tip on 60 = 9.
        r = apply_discount(80, 15, 25, discount_type="percent")
        self.assertEqual(r["savings"], 20.0)
        self.assertEqual(r["discounted_bill"], 60.0)
        self.assertEqual(r["tip"], 9.0)
        self.assertEqual(r["total"], 69.0)

    def test_tip_on_original_amount(self):
        # Tip on the pre-discount $100 even though only $90 is owed.
        r = apply_discount(100, 20, 10, tip_on_discounted=False)
        self.assertEqual(r["tip"], 20.0)       # 20% of 100
        self.assertEqual(r["total"], 110.0)    # 90 + 20

    def test_discount_type_aliases(self):
        a = apply_discount(100, 10, 50, discount_type="off")
        b = apply_discount(100, 10, 50, discount_type="percent")
        self.assertEqual(a["savings"], 50.0)
        self.assertEqual(b["savings"], 50.0)
        c = apply_discount(100, 10, 5, discount_type="flat")
        self.assertEqual(c["savings"], 5.0)

    def test_discount_split_across_people(self):
        r = apply_discount(100, 20, 10, people=2)
        self.assertEqual(r["total"], 108.0)
        self.assertEqual(r["total_per_person"], 54.0)

    def test_zero_discount_unchanged(self):
        r = apply_discount(100, 15, 0)
        self.assertEqual(r["discounted_bill"], 100.0)
        self.assertEqual(r["total"], 115.0)

    def test_string_inputs_coerced(self):
        r = apply_discount("100", "20", "10")
        self.assertEqual(r["total"], 108.0)

    def test_amount_exceeding_bill_rejected(self):
        with self.assertRaises(TipError):
            apply_discount(100, 15, 150)

    def test_percent_over_100_rejected(self):
        with self.assertRaises(TipError):
            apply_discount(100, 15, 150, discount_type="percent")

    def test_negative_discount_rejected(self):
        with self.assertRaises(TipError):
            apply_discount(100, 15, -5)

    def test_bad_discount_type_rejected(self):
        with self.assertRaises(TipError):
            apply_discount(100, 15, 10, discount_type="sideways")

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            apply_discount(-1, 15, 10)

    def test_negative_tip_rejected(self):
        with self.assertRaises(TipError):
            apply_discount(100, -5, 10)


# ---------------------------------------------------------------------------
# Tip pool distribution among staff (REQ-002 extension)
# ---------------------------------------------------------------------------


class TestTipPool(unittest.TestCase):
    def test_even_split(self):
        r = tip_pool(100, [1, 1, 1, 1])
        self.assertEqual(r["shares"], [25.0, 25.0, 25.0, 25.0])
        self.assertEqual(r["total"], 100.0)

    def test_weighted_by_hours(self):
        # 8/6/4 hours of an 18-hour shift sharing a $90 pool -> 40/30/20.
        r = tip_pool(90, [8, 6, 4])
        self.assertEqual(r["shares"], [40.0, 30.0, 20.0])

    def test_shares_sum_exactly_to_pool(self):
        # 100 / 3 doesn't divide evenly -> largest-remainder must still reconcile.
        r = tip_pool(100, [1, 1, 1])
        self.assertEqual(round(sum(r["shares"]), 2), 100.0)

    def test_single_staff_gets_all(self):
        r = tip_pool(73.5, [5])
        self.assertEqual(r["shares"], [73.5])

    def test_fractional_weights(self):
        r = tip_pool(50, [2.5, 2.5])
        self.assertEqual(r["shares"], [25.0, 25.0])

    def test_string_inputs_coerced(self):
        r = tip_pool("90", ["8", "6", "4"])
        self.assertEqual(r["shares"], [40.0, 30.0, 20.0])

    def test_zero_pool(self):
        r = tip_pool(0, [1, 2, 3])
        self.assertEqual(r["shares"], [0.0, 0.0, 0.0])
        self.assertEqual(r["total"], 0.0)

    def test_negative_pool_rejected(self):
        with self.assertRaises(TipError):
            tip_pool(-1, [1, 1])

    def test_empty_weights_rejected(self):
        with self.assertRaises(TipError):
            tip_pool(100, [])

    def test_zero_weight_rejected(self):
        with self.assertRaises(TipError):
            tip_pool(100, [1, 0])

    def test_negative_weight_rejected(self):
        with self.assertRaises(TipError):
            tip_pool(100, [1, -2])

    def test_non_list_weights_rejected(self):
        with self.assertRaises(TipError):
            tip_pool(100, "nope")


class TestBuildBill(unittest.TestCase):
    def test_bare_prices_subtotal(self):
        r = build_bill([10, 20, 5])
        self.assertEqual(r["subtotal"], 35.0)
        self.assertEqual(r["total"], 35.0)  # no tax/tip by default
        self.assertEqual(len(r["line_items"]), 3)

    def test_price_and_qty_pairs(self):
        r = build_bill([[12.50, 2], [9], [20, 1]])
        # 25 + 9 + 20 = 54
        self.assertEqual(r["subtotal"], 54.0)
        self.assertEqual(r["line_items"][0]["amount"], 25.0)
        self.assertEqual(r["line_items"][0]["qty"], 2)

    def test_tax_and_tip_applied_on_subtotal(self):
        # subtotal 100, 10% tax = 10, 20% tip on subtotal = 20 -> 130
        r = build_bill([100], tax_percent=10, tip_percent=20)
        self.assertEqual(r["subtotal"], 100.0)
        self.assertEqual(r["tax"], 10.0)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["total"], 130.0)

    def test_split_per_person(self):
        r = build_bill([100], tax_percent=0, tip_percent=20, people=4)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["total_per_person"], 30.0)
        self.assertEqual(r["tip_per_person"], 5.0)

    def test_dict_items_with_name_and_qty(self):
        r = build_bill([{"name": "Burger", "price": 12, "qty": 2},
                        {"name": "Soda", "price": 3}])
        self.assertEqual(r["subtotal"], 27.0)
        self.assertEqual(r["line_items"][0]["name"], "Burger")
        self.assertEqual(r["line_items"][1]["name"], "Soda")
        self.assertEqual(r["line_items"][1]["qty"], 1)

    def test_default_names_when_unnamed(self):
        r = build_bill([5, 6])
        self.assertEqual(r["line_items"][0]["name"], "Item 1")
        self.assertEqual(r["line_items"][1]["name"], "Item 2")

    def test_fractional_qty_allowed(self):
        # sold by weight: 2.5 units at $4 -> $10
        r = build_bill([{"price": 4, "qty": 2.5}])
        self.assertEqual(r["subtotal"], 10.0)
        self.assertEqual(r["line_items"][0]["qty"], 2.5)

    def test_string_inputs_coerced(self):
        r = build_bill(["10", "20"], tax_percent="5", tip_percent="10")
        self.assertEqual(r["subtotal"], 30.0)
        self.assertEqual(r["tax"], 1.5)
        self.assertEqual(r["tip"], 3.0)

    def test_empty_items_rejected(self):
        with self.assertRaises(TipError):
            build_bill([])

    def test_non_list_items_rejected(self):
        with self.assertRaises(TipError):
            build_bill("nope")

    def test_negative_price_rejected(self):
        with self.assertRaises(TipError):
            build_bill([-5])

    def test_zero_qty_rejected(self):
        with self.assertRaises(TipError):
            build_bill([[10, 0]])

    def test_negative_tax_rejected(self):
        with self.assertRaises(TipError):
            build_bill([10], tax_percent=-1)

    def test_dict_without_price_rejected(self):
        with self.assertRaises(TipError):
            build_bill([{"qty": 2}])

    def test_too_long_list_line_rejected(self):
        with self.assertRaises(TipError):
            build_bill([[10, 2, 3]])


class TestServiceCharge(unittest.TestCase):
    def test_mandatory_only(self):
        r = service_charge(100, 12.5)
        self.assertEqual(r["service"], 12.5)
        self.assertEqual(r["top_up"], 0.0)
        self.assertEqual(r["total"], 112.5)
        self.assertEqual(r["effective_tip_percent"], 12.5)

    def test_top_up_to_desired(self):
        # 12.5% mandatory, want 18% overall -> top up 5.5% of 100 = 5.50
        r = service_charge(100, 12.5, desired_percent=18)
        self.assertEqual(r["service"], 12.5)
        self.assertEqual(r["top_up"], 5.5)
        self.assertEqual(r["gratuity"], 18.0)
        self.assertEqual(r["total"], 118.0)
        self.assertEqual(r["effective_tip_percent"], 18.0)

    def test_desired_below_service_no_topup(self):
        # mandatory 20% already beats desired 15% -> no top-up, effective stays 20
        r = service_charge(100, 20, desired_percent=15)
        self.assertEqual(r["top_up"], 0.0)
        self.assertEqual(r["gratuity"], 20.0)
        self.assertEqual(r["effective_tip_percent"], 20.0)

    def test_desired_equal_service(self):
        r = service_charge(80, 10, desired_percent=10)
        self.assertEqual(r["top_up"], 0.0)
        self.assertEqual(r["effective_tip_percent"], 10.0)

    def test_split_per_person(self):
        r = service_charge(100, 10, desired_percent=20, people=4)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["total_per_person"], 30.0)
        self.assertEqual(r["tip_per_person"], 5.0)

    def test_zero_bill(self):
        r = service_charge(0, 15, desired_percent=20)
        self.assertEqual(r["service"], 0.0)
        self.assertEqual(r["top_up"], 0.0)
        self.assertEqual(r["total"], 0.0)

    def test_string_inputs_coerced(self):
        r = service_charge("100", "12.5", desired_percent="18")
        self.assertEqual(r["total"], 118.0)

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            service_charge(-1, 10)

    def test_negative_service_rejected(self):
        with self.assertRaises(TipError):
            service_charge(100, -5)

    def test_negative_desired_rejected(self):
        with self.assertRaises(TipError):
            service_charge(100, 10, desired_percent=-1)

    def test_missing_bill_rejected(self):
        with self.assertRaises(TipError):
            service_charge(None, 10)


class TestConvertCurrency(unittest.TestCase):
    def test_basic_conversion(self):
        r = convert_currency(100, 20, rate=0.9, currency="EUR")
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["converted"]["total"], 108.0)
        self.assertEqual(r["currency"], "EUR")

    def test_per_person_converted(self):
        r = convert_currency(100, 20, rate=2, people=4)
        self.assertEqual(r["total_per_person"], 30.0)
        self.assertEqual(r["converted"]["total_per_person"], 60.0)
        self.assertEqual(r["converted"]["tip_per_person"], 10.0)

    def test_rate_one_is_identity(self):
        r = convert_currency(50, 10, rate=1)
        self.assertEqual(r["total"], r["converted"]["total"])

    def test_currency_normalised_uppercase(self):
        r = convert_currency(10, 0, rate=1.1, currency="gbp")
        self.assertEqual(r["currency"], "GBP")

    def test_currency_defaults_to_usd(self):
        r = convert_currency(10, 0, rate=1.1)
        self.assertEqual(r["currency"], "USD")

    def test_string_inputs_coerced(self):
        r = convert_currency("100", "20", rate="0.9", currency="EUR")
        self.assertEqual(r["converted"]["total"], 108.0)

    def test_zero_rate_rejected(self):
        with self.assertRaises(TipError):
            convert_currency(100, 20, rate=0)

    def test_negative_rate_rejected(self):
        with self.assertRaises(TipError):
            convert_currency(100, 20, rate=-1)

    def test_invalid_currency_rejected(self):
        with self.assertRaises(TipError):
            convert_currency(100, 20, rate=1, currency="12$")

    def test_too_long_currency_rejected(self):
        with self.assertRaises(TipError):
            convert_currency(100, 20, rate=1, currency="DOLLARS")

    def test_propagates_base_validation(self):
        with self.assertRaises(TipError):
            convert_currency(-1, 20, rate=1)


# ---------------------------------------------------------------------------
# Large-party automatic gratuity (REQ-001 extension)
# ---------------------------------------------------------------------------


class TestAutoGratuity(unittest.TestCase):
    def test_applies_for_large_party(self):
        # Party of 6 hits the default threshold -> mandatory 18%.
        r = auto_gratuity(100, 6)
        self.assertTrue(r["applied"])
        self.assertEqual(r["tip_percent"], 18.0)
        self.assertEqual(r["tip"], 18.0)
        self.assertEqual(r["total"], 118.0)

    def test_not_applied_below_threshold(self):
        # Party of 4, no chosen tip -> voluntary 0%.
        r = auto_gratuity(100, 4)
        self.assertFalse(r["applied"])
        self.assertEqual(r["tip_percent"], 0.0)
        self.assertEqual(r["total"], 100.0)

    def test_chosen_below_auto_is_bumped_up(self):
        # Large party choosing 10% is forced up to the 18% mandatory rate.
        r = auto_gratuity(100, 8, chosen_percent=10)
        self.assertTrue(r["applied"])
        self.assertEqual(r["tip_percent"], 18.0)

    def test_chosen_above_auto_is_honoured(self):
        # A more generous choice stands.
        r = auto_gratuity(100, 8, chosen_percent=25)
        self.assertEqual(r["tip_percent"], 25.0)
        self.assertEqual(r["tip"], 25.0)

    def test_small_party_uses_chosen(self):
        r = auto_gratuity(100, 2, chosen_percent=15)
        self.assertFalse(r["applied"])
        self.assertEqual(r["tip_percent"], 15.0)
        self.assertEqual(r["total"], 115.0)

    def test_custom_threshold_and_percent(self):
        r = auto_gratuity(200, 5, threshold=5, auto_percent=20)
        self.assertTrue(r["applied"])
        self.assertEqual(r["tip"], 40.0)
        self.assertEqual(r["auto_percent"], 20.0)

    def test_split_per_person(self):
        r = auto_gratuity(100, 6)
        self.assertEqual(r["total_per_person"], round(118.0 / 6, 2))
        self.assertEqual(r["people"], 6)

    def test_string_inputs_coerced(self):
        r = auto_gratuity("100", "6", threshold="6", auto_percent="18")
        self.assertEqual(r["total"], 118.0)

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            auto_gratuity(-1, 6)

    def test_zero_people_rejected(self):
        with self.assertRaises(TipError):
            auto_gratuity(100, 0)

    def test_negative_auto_percent_rejected(self):
        with self.assertRaises(TipError):
            auto_gratuity(100, 6, auto_percent=-5)

    def test_negative_chosen_rejected(self):
        with self.assertRaises(TipError):
            auto_gratuity(100, 6, chosen_percent=-1)


# ---------------------------------------------------------------------------
# Split by percentage allocation (REQ-002 extension)
# ---------------------------------------------------------------------------


class TestSplitByPercentage(unittest.TestCase):
    def test_basic_percentages(self):
        r = split_by_percentage(100, 20, [50, 30, 20])
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["amounts"], [60.0, 36.0, 24.0])

    def test_even_percentages_sum_exactly(self):
        # 33.33/33.33/33.34 of 115 must still reconcile to the cent.
        r = split_by_percentage(100, 15, [33.33, 33.33, 33.34])
        self.assertEqual(round(sum(r["amounts"]), 2), 115.0)

    def test_two_way_split(self):
        r = split_by_percentage(100, 0, [60, 40])
        self.assertEqual(r["amounts"], [60.0, 40.0])

    def test_tolerance_allows_small_drift(self):
        # 99.99 is within the half-percent rounding tolerance of 100.
        r = split_by_percentage(50, 0, [33.33, 33.33, 33.33])
        self.assertEqual(round(sum(r["amounts"]), 2), 50.0)

    def test_string_inputs_coerced(self):
        r = split_by_percentage("100", "20", ["50", "50"])
        self.assertEqual(r["amounts"], [60.0, 60.0])

    def test_does_not_sum_to_100_rejected(self):
        with self.assertRaises(TipError):
            split_by_percentage(100, 20, [50, 30])

    def test_over_100_rejected(self):
        with self.assertRaises(TipError):
            split_by_percentage(100, 20, [60, 60])

    def test_empty_percentages_rejected(self):
        with self.assertRaises(TipError):
            split_by_percentage(100, 20, [])

    def test_negative_percentage_rejected(self):
        with self.assertRaises(TipError):
            split_by_percentage(100, 20, [110, -10])

    def test_non_list_percentages_rejected(self):
        with self.assertRaises(TipError):
            split_by_percentage(100, 20, "nope")

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            split_by_percentage(-1, 20, [100])

    def test_negative_tip_rejected(self):
        with self.assertRaises(TipError):
            split_by_percentage(100, -5, [100])


# ---------------------------------------------------------------------------
# Tip for a target per-person amount (REQ-001/002 extension)
# ---------------------------------------------------------------------------


class TestTipForTargetPerPerson(unittest.TestCase):
    def test_basic_target(self):
        # 100 bill, want $40 each across 3 -> 120 total, 20 tip.
        r = tip_for_target_per_person(100, 40, 3)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["effective_tip_percent"], 20.0)
        self.assertEqual(r["total_per_person"], 40.0)

    def test_single_person(self):
        r = tip_for_target_per_person(100, 115)
        self.assertEqual(r["tip"], 15.0)
        self.assertEqual(r["total"], 115.0)

    def test_exact_bill_zero_tip(self):
        r = tip_for_target_per_person(120, 40, 3)
        self.assertEqual(r["tip"], 0.0)
        self.assertEqual(r["effective_tip_percent"], 0.0)

    def test_tip_per_person(self):
        r = tip_for_target_per_person(100, 40, 3)
        self.assertEqual(r["tip_per_person"], round(20.0 / 3, 2))

    def test_string_inputs_coerced(self):
        r = tip_for_target_per_person("100", "40", "3")
        self.assertEqual(r["total"], 120.0)

    def test_target_too_low_rejected(self):
        # 3 * 30 = 90 < 100 bill -> tip would be negative.
        with self.assertRaises(TipError):
            tip_for_target_per_person(100, 30, 3)

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            tip_for_target_per_person(-1, 40)

    def test_negative_target_rejected(self):
        with self.assertRaises(TipError):
            tip_for_target_per_person(100, -40)

    def test_zero_people_rejected(self):
        with self.assertRaises(TipError):
            tip_for_target_per_person(100, 40, 0)


# ---------------------------------------------------------------------------
# Round the grand total to a clean increment (REQ-001/002 extension)
# ---------------------------------------------------------------------------


class TestRoundTotalTo(unittest.TestCase):
    def test_round_up_to_nearest_five(self):
        # 100 bill, 0 base tip -> base total 100; rounding UP to next $5 = 100.
        r = round_total_to(100, 0, nearest=5)
        self.assertEqual(r["total"], 100.0)
        self.assertEqual(r["tip"], 0.0)

    def test_round_up_folds_into_tip(self):
        # 100 + 15% = 115; round up to next $5 -> 115 already a multiple.
        r = round_total_to(100, 15, nearest=5)
        self.assertEqual(r["total"], 115.0)
        self.assertEqual(r["tip"], 15.0)

    def test_round_up_adds_bonus(self):
        # 100 + 18% = 118; round up to next $5 = 120, tip becomes 20.
        r = round_total_to(100, 18, nearest=5)
        self.assertEqual(r["base_total"], 118.0)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["bonus"], 2.0)
        self.assertEqual(r["effective_tip_percent"], 20.0)

    def test_round_nearest_rounds_down(self):
        # 118 to nearest 5 -> 120 (118 is closer to 120 than 115).
        r = round_total_to(100, 18, nearest=5, direction="nearest")
        self.assertEqual(r["total"], 120.0)

    def test_round_nearest_picks_lower(self):
        # 116 to nearest 5 -> 115.
        r = round_total_to(100, 16, nearest=5, direction="nearest")
        self.assertEqual(r["total"], 115.0)
        self.assertEqual(r["tip"], 15.0)

    def test_round_down_trims_tip(self):
        # 118 down to next 5 -> 115.
        r = round_total_to(100, 18, nearest=5, direction="down")
        self.assertEqual(r["total"], 115.0)
        self.assertEqual(r["tip"], 15.0)
        self.assertEqual(r["bonus"], -3.0)

    def test_round_down_below_bill_rejected(self):
        # 100 bill, 2% tip -> 102; rounding down to next 5 = 100 (ok, == bill).
        # but 100 bill, base 0, down to 5 with nearest 5 is 100 (fine);
        # force negative: bill 102, nearest 5, down -> 100 < 102.
        with self.assertRaises(TipError):
            round_total_to(102, 0, nearest=5, direction="down")

    def test_split_across_people_sums_exactly(self):
        r = round_total_to(100, 18, nearest=5, people=3)
        self.assertEqual(round(sum(r["per_person_amounts"]), 2), r["total"])
        self.assertEqual(len(r["per_person_amounts"]), 3)

    def test_round_with_tax_on_subtotal(self):
        # bill 110 incl 10 tax; tip 20% on subtotal 100 = 20 -> base total 130.
        r = round_total_to(110, 20, nearest=5, tax=10, tip_on="subtotal")
        self.assertEqual(r["base_total"], 130.0)
        self.assertEqual(r["total"], 130.0)

    def test_aliases_for_direction(self):
        a = round_total_to(100, 18, nearest=5, direction="ceil")
        b = round_total_to(100, 18, nearest=5, direction="up")
        self.assertEqual(a["total"], b["total"])

    def test_string_inputs_coerced(self):
        r = round_total_to("100", "18", nearest="5")
        self.assertEqual(r["total"], 120.0)

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            round_total_to(-1, 10)

    def test_negative_base_percent_rejected(self):
        with self.assertRaises(TipError):
            round_total_to(100, -5)

    def test_zero_nearest_rejected(self):
        with self.assertRaises(TipError):
            round_total_to(100, 10, nearest=0)

    def test_bad_direction_rejected(self):
        with self.assertRaises(TipError):
            round_total_to(100, 10, direction="sideways")

    def test_tax_exceeding_bill_rejected(self):
        with self.assertRaises(TipError):
            round_total_to(100, 10, tax=150)


# ---------------------------------------------------------------------------
# Comp a diner — birthday treat (REQ-002 extension)
# ---------------------------------------------------------------------------


class TestSplitComped(unittest.TestCase):
    def test_comp_one_diner(self):
        # 100 + 20% = 120 across 3, comp diner index 2 -> 2 payers pay 60 each.
        r = split_comped(100, 20, 3, [2])
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["payers"], 2)
        self.assertEqual([p["amount"] for p in r["people_detail"]], [60.0, 60.0, 0.0])
        self.assertEqual([p["comped"] for p in r["people_detail"]], [False, False, True])

    def test_no_comp_even_split(self):
        # Empty comp list behaves like an even split.
        r = split_comped(100, 20, 4, [])
        self.assertEqual(r["amounts"], [30.0, 30.0, 30.0, 30.0])
        self.assertEqual(r["payers"], 4)

    def test_amounts_sum_exactly(self):
        # 115 / 2 payers doesn't divide evenly -> still reconciles to the cent.
        r = split_comped(100, 15, 3, [0])
        self.assertEqual(round(sum(r["amounts"]), 2), 115.0)

    def test_comped_diners_pay_zero(self):
        r = split_comped(90, 0, 3, [1])
        self.assertEqual(r["people_detail"][1]["amount"], 0.0)
        self.assertEqual(r["amounts"][0] + r["amounts"][2], 90.0)

    def test_multiple_comped(self):
        r = split_comped(120, 0, 4, [2, 3])
        self.assertEqual([p["amount"] for p in r["people_detail"]], [60.0, 60.0, 0.0, 0.0])
        self.assertEqual(r["payers"], 2)

    def test_fair_share_reported(self):
        r = split_comped(100, 20, 3, [2])
        self.assertEqual(r["fair_share"], 60.0)

    def test_comped_normalised_and_sorted(self):
        # Duplicate / unordered indices are de-duped and sorted.
        r = split_comped(100, 0, 4, [3, 1, 1])
        self.assertEqual(r["comped"], [1, 3])

    def test_string_inputs_coerced(self):
        r = split_comped("100", "20", "3", ["2"])
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["payers"], 2)

    def test_comp_everyone_rejected(self):
        with self.assertRaises(TipError):
            split_comped(100, 20, 3, [0, 1, 2])

    def test_index_out_of_range_rejected(self):
        with self.assertRaises(TipError):
            split_comped(100, 20, 3, [5])

    def test_negative_index_rejected(self):
        with self.assertRaises(TipError):
            split_comped(100, 20, 3, [-1])

    def test_fractional_index_rejected(self):
        with self.assertRaises(TipError):
            split_comped(100, 20, 3, [1.5])

    def test_non_list_comped_rejected(self):
        with self.assertRaises(TipError):
            split_comped(100, 20, 3, "nope")

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            split_comped(-1, 20, 3, [0])

    def test_negative_tip_rejected(self):
        with self.assertRaises(TipError):
            split_comped(100, -5, 3, [0])

    def test_zero_people_rejected(self):
        with self.assertRaises(TipError):
            split_comped(100, 20, 0, [])


# ---------------------------------------------------------------------------
# Card-fee gross-up (REQ-001 extension)
# ---------------------------------------------------------------------------


class TestGrossUpTip(unittest.TestCase):
    def test_no_fee_is_plain_tip(self):
        r = gross_up_tip(100, 20, 0)
        self.assertEqual(r["intended_tip"], 20.0)
        self.assertEqual(r["gross_tip"], 20.0)
        self.assertEqual(r["fee"], 0.0)
        self.assertEqual(r["total"], 120.0)

    def test_gross_up_for_fee(self):
        # Want server to net 20 (20% of 100) after a 20% fee.
        # gross = 20 / 0.8 = 25; fee = 5; total = 125.
        r = gross_up_tip(100, 20, 20)
        self.assertEqual(r["intended_tip"], 20.0)
        self.assertEqual(r["gross_tip"], 25.0)
        self.assertEqual(r["fee"], 5.0)
        self.assertEqual(r["total"], 125.0)
        self.assertEqual(r["effective_tip_percent"], 25.0)

    def test_server_nets_intended_after_fee(self):
        # The grossed-up tip, minus the fee, equals the intended tip.
        r = gross_up_tip(80, 18, 3)
        netted = r["gross_tip"] * (1 - 0.03)
        self.assertAlmostEqual(netted, r["intended_tip"], places=2)

    def test_typical_card_fee(self):
        # 100 bill, 20% intended, 3% fee -> gross 20/0.97 = 20.62.
        r = gross_up_tip(100, 20, 3)
        self.assertEqual(r["gross_tip"], 20.62)
        self.assertEqual(r["fee"], 0.62)

    def test_split_per_person(self):
        r = gross_up_tip(100, 20, 20, people=5)
        self.assertEqual(r["total"], 125.0)
        self.assertEqual(r["total_per_person"], 25.0)
        self.assertEqual(r["tip_per_person"], 5.0)

    def test_zero_bill(self):
        r = gross_up_tip(0, 20, 3)
        self.assertEqual(r["gross_tip"], 0.0)
        self.assertEqual(r["total"], 0.0)
        self.assertEqual(r["effective_tip_percent"], 20.0)

    def test_string_inputs_coerced(self):
        r = gross_up_tip("100", "20", "20")
        self.assertEqual(r["gross_tip"], 25.0)

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            gross_up_tip(-1, 20, 3)

    def test_negative_tip_rejected(self):
        with self.assertRaises(TipError):
            gross_up_tip(100, -5, 3)

    def test_negative_fee_rejected(self):
        with self.assertRaises(TipError):
            gross_up_tip(100, 20, -1)

    def test_fee_100_or_more_rejected(self):
        with self.assertRaises(TipError):
            gross_up_tip(100, 20, 100)

    def test_zero_people_rejected(self):
        with self.assertRaises(TipError):
            gross_up_tip(100, 20, 3, people=0)


# ---------------------------------------------------------------------------
# Shared-items split — personal + shared items (REQ-002 extension)
# ---------------------------------------------------------------------------


class TestSplitSharedItems(unittest.TestCase):
    def test_personal_only_no_tip(self):
        # No shared items, no tax/tip: each diner pays exactly their own.
        r = split_shared_items([[10], [20], [30]], tip_percent=0)
        self.assertEqual([p["amount"] for p in r["people"]], [10.0, 20.0, 30.0])
        self.assertEqual(r["total"], 60.0)

    def test_shared_item_split_evenly_when_no_sharers(self):
        # A bare-price shared item is split across EVERYONE.
        r = split_shared_items([[0], [0]], [30], tip_percent=0)
        self.assertEqual(r["people"][0]["shared"], 15.0)
        self.assertEqual(r["people"][1]["shared"], 15.0)
        self.assertEqual(r["total"], 30.0)

    def test_shared_item_among_subset(self):
        # 30 appetiser shared only by diners 0 and 1 (not diner 2).
        r = split_shared_items([[10], [10], [10]],
                               [{"price": 30, "sharers": [0, 1]}], tip_percent=0)
        self.assertEqual(r["people"][0]["shared"], 15.0)
        self.assertEqual(r["people"][1]["shared"], 15.0)
        self.assertEqual(r["people"][2]["shared"], 0.0)
        self.assertEqual([p["amount"] for p in r["people"]], [25.0, 25.0, 10.0])

    def test_shared_item_list_form(self):
        # [price, [sharers]] is accepted alongside the mapping form.
        r = split_shared_items([[0], [0]], [[18, [0, 1]]], tip_percent=0)
        self.assertEqual(r["people"][0]["shared"], 9.0)
        self.assertEqual(r["people"][1]["shared"], 9.0)

    def test_tip_apportioned_by_consumption(self):
        # Personal 10/20/30 (=60) + 20% tip = 12, split 1:2:3.
        r = split_shared_items([[10], [20], [30]], tip_percent=20)
        self.assertEqual(r["tip"], 12.0)
        self.assertEqual([p["tip"] for p in r["people"]], [2.0, 4.0, 6.0])

    def test_amounts_sum_exactly_to_total(self):
        r = split_shared_items([[12.5, 4], [9]],
                               [{"price": 17.77, "sharers": [0, 1]}],
                               tip_percent=18, tax=3.33)
        self.assertEqual(round(sum(p["amount"] for p in r["people"]), 2), r["total"])

    def test_tax_apportioned(self):
        r = split_shared_items([[50], [50]], tip_percent=0, tax=10)
        self.assertEqual([p["tax"] for p in r["people"]], [5.0, 5.0])
        self.assertEqual(r["total"], 110.0)

    def test_tip_on_total_includes_tax(self):
        r = split_shared_items([[100]], tip_percent=10, tax=10, tip_on="total")
        self.assertEqual(r["tip"], 11.0)  # 10% of 110
        self.assertEqual(r["total"], 121.0)

    def test_no_shared_items_defaults_empty(self):
        r = split_shared_items([[10], [20]], None, tip_percent=0)
        self.assertEqual(r["total"], 30.0)

    def test_string_inputs_coerced(self):
        r = split_shared_items([["10"], ["10"]], [["30", ["0", "1"]]],
                               tip_percent="0")
        self.assertEqual(r["people"][0]["amount"], 25.0)
        self.assertEqual(r["people"][1]["amount"], 25.0)

    def test_empty_diners_rejected(self):
        with self.assertRaises(TipError):
            split_shared_items([], [], tip_percent=15)

    def test_non_list_diners_rejected(self):
        with self.assertRaises(TipError):
            split_shared_items("nope", [], tip_percent=15)

    def test_diner_entry_must_be_list(self):
        with self.assertRaises(TipError):
            split_shared_items([10, 20], [], tip_percent=15)

    def test_negative_personal_item_rejected(self):
        with self.assertRaises(TipError):
            split_shared_items([[10, -1]], [], tip_percent=15)

    def test_shared_item_out_of_range_rejected(self):
        with self.assertRaises(TipError):
            split_shared_items([[10], [10]],
                               [{"price": 30, "sharers": [0, 5]}], tip_percent=0)

    def test_shared_item_missing_price_rejected(self):
        with self.assertRaises(TipError):
            split_shared_items([[10]], [{"sharers": [0]}], tip_percent=0)

    def test_shared_item_empty_sharers_rejected(self):
        with self.assertRaises(TipError):
            split_shared_items([[10], [10]],
                               [{"price": 30, "sharers": []}], tip_percent=0)

    def test_negative_tip_rejected(self):
        with self.assertRaises(TipError):
            split_shared_items([[10]], [], tip_percent=-5)

    def test_negative_tax_rejected(self):
        with self.assertRaises(TipError):
            split_shared_items([[10]], [], tip_percent=15, tax=-1)


# ---------------------------------------------------------------------------
# Regional customary tip (REQ-001 extension)
# ---------------------------------------------------------------------------


class TestRecommendRegionalTip(unittest.TestCase):
    def test_us_customary(self):
        r = recommend_regional_tip(100, "US")
        self.assertEqual(r["customary"], 18.0)
        self.assertEqual(r["tip"], 18.0)
        self.assertEqual(r["total"], 118.0)
        self.assertEqual(r["region"], "US")
        self.assertEqual(r["region_name"], "United States")

    def test_japan_no_tip(self):
        r = recommend_regional_tip(100, "Japan")
        self.assertEqual(r["customary"], 0.0)
        self.assertEqual(r["tip"], 0.0)
        self.assertEqual(r["total"], 100.0)

    def test_low_high_range_reported(self):
        r = recommend_regional_tip(100, "UK")
        self.assertEqual(r["customary"], 12.5)
        self.assertEqual(r["low"], 10.0)
        self.assertEqual(r["high"], 15.0)

    def test_region_code_case_insensitive(self):
        r = recommend_regional_tip(100, "jp")
        self.assertEqual(r["region"], "JP")

    def test_region_alias_full_name(self):
        a = recommend_regional_tip(100, "united states")
        b = recommend_regional_tip(100, "USA")
        self.assertEqual(a["region"], "US")
        self.assertEqual(b["region"], "US")

    def test_split_per_person(self):
        r = recommend_regional_tip(100, "US", people=4)
        self.assertEqual(r["total"], 118.0)
        self.assertEqual(r["total_per_person"], 29.5)

    def test_string_inputs_coerced(self):
        r = recommend_regional_tip("100", "FR")
        self.assertEqual(r["customary"], 5.0)
        self.assertEqual(r["total"], 105.0)

    def test_unknown_region_rejected(self):
        with self.assertRaises(TipError):
            recommend_regional_tip(100, "Atlantis")

    def test_missing_region_rejected(self):
        with self.assertRaises(TipError):
            recommend_regional_tip(100, None)

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            recommend_regional_tip(-1, "US")

    def test_non_string_region_rejected(self):
        with self.assertRaises(TipError):
            recommend_regional_tip(100, 42)


# ---------------------------------------------------------------------------
# Round up for charity (REQ-001/002 extension)
# ---------------------------------------------------------------------------


class TestCharityRoundUp(unittest.TestCase):
    def test_round_up_to_dollar(self):
        # 100 + 15% = 115; already whole -> donates 0.
        r = charity_round_up(100, 15)
        self.assertEqual(r["base_total"], 115.0)
        self.assertEqual(r["donation"], 0.0)
        self.assertEqual(r["total"], 115.0)

    def test_round_up_with_cents(self):
        # 53.27 + 18% = 62.86; round up to next dollar 63 -> donate 0.14.
        r = charity_round_up(53.27, 18)
        self.assertEqual(r["base_total"], 62.86)
        self.assertEqual(r["donation"], 0.14)
        self.assertEqual(r["total"], 63.0)

    def test_tip_unaffected_by_donation(self):
        # Unlike round_total_to, the server's tip stays the plain percent tip.
        r = charity_round_up(53.27, 18)
        self.assertEqual(r["tip"], 9.59)  # same as calculate_tip(53.27, 18)

    def test_round_up_to_five(self):
        # 100 + 18% = 118; round up to next $5 = 120 -> donate 2.
        r = charity_round_up(100, 18, round_to=5)
        self.assertEqual(r["donation"], 2.0)
        self.assertEqual(r["total"], 120.0)

    def test_explicit_donation_amount(self):
        # A fixed gift ignores round_to.
        r = charity_round_up(100, 15, donation=10, round_to=5)
        self.assertEqual(r["donation"], 10.0)
        self.assertEqual(r["total"], 125.0)

    def test_donation_zero_when_explicit_zero(self):
        r = charity_round_up(100, 15, donation=0)
        self.assertEqual(r["donation"], 0.0)
        self.assertEqual(r["total"], 115.0)

    def test_split_across_people_sums_exactly(self):
        r = charity_round_up(100, 18, people=3, round_to=5)
        self.assertEqual(round(sum(r["per_person_amounts"]), 2), r["total"])
        self.assertEqual(len(r["per_person_amounts"]), 3)
        self.assertEqual(r["total_per_person"], 40.0)

    def test_tax_on_subtotal_carried_through(self):
        # bill 110 incl 10 tax; tip 20% on subtotal 100 = 20 -> base 130.
        r = charity_round_up(110, 20, tax=10, tip_on="subtotal", round_to=5)
        self.assertEqual(r["base_total"], 130.0)
        self.assertEqual(r["donation"], 0.0)
        self.assertEqual(r["subtotal"], 100.0)

    def test_donation_per_person(self):
        r = charity_round_up(100, 18, people=4, round_to=5)
        self.assertEqual(r["donation"], 2.0)
        self.assertEqual(r["donation_per_person"], 0.5)

    def test_string_inputs_coerced(self):
        r = charity_round_up("100", "18", round_to="5")
        self.assertEqual(r["total"], 120.0)

    def test_negative_donation_rejected(self):
        with self.assertRaises(TipError):
            charity_round_up(100, 15, donation=-5)

    def test_zero_round_to_rejected(self):
        with self.assertRaises(TipError):
            charity_round_up(100, 15, round_to=0)

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            charity_round_up(-1, 15)

    def test_negative_tip_rejected(self):
        with self.assertRaises(TipError):
            charity_round_up(100, -5)

    def test_zero_people_rejected(self):
        with self.assertRaises(TipError):
            charity_round_up(100, 15, people=0)


class TestTipByDiner(unittest.TestCase):
    def test_each_diner_uses_own_rate(self):
        r = tip_by_diner([
            {"name": "Sam", "amount": 30, "tip_percent": 20},
            {"name": "Alex", "amount": 45, "tip_percent": 15},
            {"name": "Jo", "amount": 25, "tip_percent": 25},
        ])
        tips = {d["name"]: d["tip"] for d in r["diners"]}
        self.assertEqual(tips["Sam"], 6.0)    # 30 @ 20%
        self.assertEqual(tips["Alex"], 6.75)  # 45 @ 15%
        self.assertEqual(tips["Jo"], 6.25)    # 25 @ 25%

    def test_grand_totals(self):
        r = tip_by_diner([
            {"amount": 30, "tip_percent": 20},
            {"amount": 45, "tip_percent": 15},
            {"amount": 25, "tip_percent": 25},
        ])
        self.assertEqual(r["subtotal"], 100.0)
        self.assertEqual(r["tip"], 19.0)
        self.assertEqual(r["total"], 119.0)
        self.assertEqual(r["people"], 3)

    def test_per_diner_totals_reconcile_to_grand_total(self):
        r = tip_by_diner([
            {"amount": 33.33, "tip_percent": 18},
            {"amount": 41.11, "tip_percent": 22},
            {"amount": 25.55, "tip_percent": 15},
        ], tax=8.77)
        self.assertEqual(round(sum(d["total"] for d in r["diners"]), 2), r["total"])

    def test_diner_total_is_amount_plus_tax_plus_tip(self):
        r = tip_by_diner([{"amount": 50, "tip_percent": 20}], tax=5)
        d = r["diners"][0]
        self.assertEqual(d["amount"], 50.0)
        self.assertEqual(d["tax"], 5.0)
        self.assertEqual(d["tip"], 10.0)
        self.assertEqual(d["total"], 65.0)

    def test_tax_allocated_proportionally(self):
        # amounts 75 / 25 -> tax 10 splits 7.50 / 2.50.
        r = tip_by_diner([
            {"amount": 75, "tip_percent": 0},
            {"amount": 25, "tip_percent": 0},
        ], tax=10)
        taxes = [d["tax"] for d in r["diners"]]
        self.assertEqual(taxes, [7.5, 2.5])
        self.assertEqual(sum(taxes), r["tax"])

    def test_tax_shares_sum_exactly_with_remainder(self):
        # 10 cents over 3 equal amounts -> shares sum to exactly 0.10.
        r = tip_by_diner([
            {"amount": 10, "tip_percent": 0},
            {"amount": 10, "tip_percent": 0},
            {"amount": 10, "tip_percent": 0},
        ], tax=0.10)
        self.assertEqual(round(sum(d["tax"] for d in r["diners"]), 2), 0.10)

    def test_zero_tax_default(self):
        r = tip_by_diner([{"amount": 40, "tip_percent": 10}])
        self.assertEqual(r["tax"], 0.0)
        self.assertEqual(r["diners"][0]["tax"], 0.0)

    def test_effective_tip_percent(self):
        # tip 19 on subtotal 100 -> 19%.
        r = tip_by_diner([
            {"amount": 30, "tip_percent": 20},
            {"amount": 45, "tip_percent": 15},
            {"amount": 25, "tip_percent": 25},
        ])
        self.assertEqual(r["effective_tip_percent"], 19.0)

    def test_default_names(self):
        r = tip_by_diner([
            {"amount": 10, "tip_percent": 10},
            {"amount": 20, "tip_percent": 10},
        ])
        self.assertEqual([d["name"] for d in r["diners"]], ["Diner 1", "Diner 2"])

    def test_string_inputs_coerced(self):
        r = tip_by_diner([{"name": "Sam", "amount": "30", "tip_percent": "20"}], tax="3")
        self.assertEqual(r["diners"][0]["tip"], 6.0)
        self.assertEqual(r["total"], 39.0)

    def test_zero_amount_diner_pays_only_tax_share_zero(self):
        r = tip_by_diner([
            {"amount": 0, "tip_percent": 20},
            {"amount": 50, "tip_percent": 20},
        ], tax=5)
        # zero-amount diner gets no proportional tax and no tip.
        self.assertEqual(r["diners"][0]["total"], 0.0)
        self.assertEqual(r["diners"][1]["tax"], 5.0)

    def test_empty_list_rejected(self):
        with self.assertRaises(TipError):
            tip_by_diner([])

    def test_none_rejected(self):
        with self.assertRaises(TipError):
            tip_by_diner(None)

    def test_non_list_rejected(self):
        with self.assertRaises(TipError):
            tip_by_diner({"amount": 10, "tip_percent": 10})

    def test_diner_not_object_rejected(self):
        with self.assertRaises(TipError):
            tip_by_diner([42])

    def test_negative_amount_rejected(self):
        with self.assertRaises(TipError):
            tip_by_diner([{"amount": -1, "tip_percent": 10}])

    def test_negative_tip_percent_rejected(self):
        with self.assertRaises(TipError):
            tip_by_diner([{"amount": 10, "tip_percent": -5}])

    def test_negative_tax_rejected(self):
        with self.assertRaises(TipError):
            tip_by_diner([{"amount": 10, "tip_percent": 10}], tax=-1)


# ---------------------------------------------------------------------------
# HTTP API tests
# ---------------------------------------------------------------------------


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def _post_to(self, path, body):
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self._url(path), data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def _post(self, body):
        return self._post_to("/api/calculate", body)

    def test_get_index_html(self):
        with urllib.request.urlopen(self._url("/")) as resp:
            self.assertEqual(resp.status, 200)
            self.assertIn("text/html", resp.headers.get("Content-Type", ""))
            self.assertIn("Tip Calculator", resp.read().decode("utf-8"))

    def test_health(self):
        with urllib.request.urlopen(self._url("/health")) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(json.loads(resp.read())["status"], "ok")

    def test_api_happy_path(self):
        status, data = self._post({"bill": 100, "tip_percent": 20, "people": 4})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip"], 20.0)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(data["total_per_person"], 30.0)

    def test_api_validation_error(self):
        status, data = self._post({"bill": -10, "tip_percent": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_missing_bill(self):
        status, data = self._post({"tip_percent": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_invalid_json(self):
        req = urllib.request.Request(
            self._url("/api/calculate"), data=b"not json",
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req)
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)

    def test_api_unknown_route(self):
        try:
            urllib.request.urlopen(self._url("/nope"))
            self.fail("expected 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_api_calculate_with_tax(self):
        status, data = self._post(
            {"bill": 110, "tip_percent": 20, "tax": 10, "tip_on": "subtotal"})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip"], 20.0)
        self.assertEqual(data["total"], 130.0)
        self.assertEqual(data["subtotal"], 100.0)

    def test_api_calculate_bad_tip_on(self):
        status, data = self._post(
            {"bill": 100, "tip_percent": 20, "tip_on": "sideways"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_reverse_happy(self):
        status, data = self._post_to("/api/reverse", {"bill": 100, "target_total": 120})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip"], 20.0)
        self.assertEqual(data["effective_tip_percent"], 20.0)

    def test_api_reverse_below_bill(self):
        status, data = self._post_to("/api/reverse", {"bill": 100, "target_total": 90})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_round_split_happy(self):
        status, data = self._post_to(
            "/api/round-split", {"bill": 100, "tip_percent": 15, "people": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["per_person"], 39.0)
        self.assertEqual(data["collected"], 117.0)
        self.assertEqual(data["surplus"], 2.0)

    def test_api_round_split_validation(self):
        status, data = self._post_to(
            "/api/round-split", {"bill": 100, "tip_percent": 15, "people": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_suggestions_happy(self):
        status, data = self._post_to("/api/suggestions", {"bill": 100, "people": 2})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["tiers"]), 5)
        self.assertEqual(data["tiers"][0]["tip_percent"], 10)

    def test_api_suggestions_validation(self):
        status, data = self._post_to("/api/suggestions", {"bill": -1})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_split_happy(self):
        status, data = self._post_to(
            "/api/split", {"bill": 100, "tip_percent": 20, "shares": [1, 1, 2]})
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(round(sum(data["amounts"]), 2), 120.0)

    def test_api_split_validation(self):
        status, data = self._post_to(
            "/api/split", {"bill": 100, "tip_percent": 20, "shares": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_items_split_happy(self):
        status, data = self._post_to(
            "/api/items-split",
            {"people_items": [[10], [20], [30]], "tip_percent": 20})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip"], 12.0)
        self.assertEqual([p["amount"] for p in data["people"]], [12.0, 24.0, 36.0])
        self.assertEqual(data["total"], 72.0)

    def test_api_items_split_validation(self):
        status, data = self._post_to(
            "/api/items-split", {"people_items": [], "tip_percent": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_settle_happy(self):
        status, data = self._post_to(
            "/api/settle", {"bill": 100, "tip_percent": 20, "paid": [120, 0, 0]})
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(data["transfers"], [
            {"from": 1, "to": 0, "amount": 40.0},
            {"from": 2, "to": 0, "amount": 40.0},
        ])

    def test_api_settle_weighted(self):
        status, data = self._post_to(
            "/api/settle",
            {"bill": 100, "tip_percent": 20, "paid": [120, 0, 0], "shares": [1, 1, 2]})
        self.assertEqual(status, 200)
        self.assertEqual([p["owed"] for p in data["people"]], [30.0, 30.0, 60.0])

    def test_api_settle_validation(self):
        status, data = self._post_to(
            "/api/settle", {"bill": 100, "tip_percent": 20, "paid": [100, 0, 0]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_rating_happy(self):
        status, data = self._post_to(
            "/api/rating", {"bill": 100, "rating": 5, "people": 4})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip_percent"], 20.0)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(data["total_per_person"], 30.0)

    def test_api_rating_validation(self):
        status, data = self._post_to("/api/rating", {"bill": 100, "rating": 9})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_change_happy(self):
        status, data = self._post_to("/api/change", {"total": 115, "paid": 120})
        self.assertEqual(status, 200)
        self.assertEqual(data["change"], 5.0)
        self.assertFalse(data["exact"])

    def test_api_change_validation(self):
        status, data = self._post_to("/api/change", {"total": 120, "paid": 100})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_combine_happy(self):
        status, data = self._post_to("/api/combine", {
            "checks": [{"bill": 40, "tip_percent": 20},
                       {"bill": 60, "tip_percent": 20}],
            "people": 2,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(round(sum(data["amounts"]), 2), 120.0)

    def test_api_combine_validation(self):
        status, data = self._post_to("/api/combine", {"checks": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_discount_happy(self):
        status, data = self._post_to(
            "/api/discount", {"bill": 100, "tip_percent": 20, "discount": 10})
        self.assertEqual(status, 200)
        self.assertEqual(data["savings"], 10.0)
        self.assertEqual(data["discounted_bill"], 90.0)
        self.assertEqual(data["tip"], 18.0)
        self.assertEqual(data["total"], 108.0)

    def test_api_discount_percent(self):
        status, data = self._post_to(
            "/api/discount",
            {"bill": 80, "tip_percent": 15, "discount": 25, "discount_type": "percent"})
        self.assertEqual(status, 200)
        self.assertEqual(data["discounted_bill"], 60.0)
        self.assertEqual(data["total"], 69.0)

    def test_api_discount_validation(self):
        status, data = self._post_to(
            "/api/discount", {"bill": 100, "tip_percent": 20, "discount": 150})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_tip_pool_happy(self):
        status, data = self._post_to(
            "/api/tip-pool", {"pool": 90, "weights": [8, 6, 4]})
        self.assertEqual(status, 200)
        self.assertEqual(data["shares"], [40.0, 30.0, 20.0])
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_api_tip_pool_validation(self):
        status, data = self._post_to("/api/tip-pool", {"pool": 100, "weights": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_build_bill_happy(self):
        status, data = self._post_to(
            "/api/build-bill",
            {"items": [[10, 2], [5]], "tax_percent": 10, "tip_percent": 20, "people": 5})
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 25.0)
        self.assertEqual(data["total"], 32.5)  # 25 + 2.5 tax + 5 tip
        self.assertEqual(data["total_per_person"], 6.5)

    def test_api_build_bill_validation(self):
        status, data = self._post_to("/api/build-bill", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_service_charge_happy(self):
        status, data = self._post_to(
            "/api/service-charge",
            {"bill": 100, "service_percent": 12.5, "desired_percent": 18})
        self.assertEqual(status, 200)
        self.assertEqual(data["top_up"], 5.5)
        self.assertEqual(data["total"], 118.0)

    def test_api_service_charge_validation(self):
        status, data = self._post_to(
            "/api/service-charge", {"bill": -1, "service_percent": 10})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_convert_happy(self):
        status, data = self._post_to(
            "/api/convert",
            {"bill": 100, "tip_percent": 20, "rate": 0.9, "currency": "EUR"})
        self.assertEqual(status, 200)
        self.assertEqual(data["converted"]["total"], 108.0)
        self.assertEqual(data["currency"], "EUR")

    def test_api_convert_validation(self):
        status, data = self._post_to(
            "/api/convert", {"bill": 100, "tip_percent": 20, "rate": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_auto_gratuity_happy(self):
        status, data = self._post_to(
            "/api/auto-gratuity", {"bill": 100, "people": 6})
        self.assertEqual(status, 200)
        self.assertTrue(data["applied"])
        self.assertEqual(data["tip_percent"], 18.0)
        self.assertEqual(data["total"], 118.0)

    def test_api_auto_gratuity_small_party(self):
        status, data = self._post_to(
            "/api/auto-gratuity",
            {"bill": 100, "people": 2, "chosen_percent": 15})
        self.assertEqual(status, 200)
        self.assertFalse(data["applied"])
        self.assertEqual(data["total"], 115.0)

    def test_api_auto_gratuity_validation(self):
        status, data = self._post_to(
            "/api/auto-gratuity", {"bill": -1, "people": 6})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_split_percentage_happy(self):
        status, data = self._post_to(
            "/api/split-percentage",
            {"bill": 100, "tip_percent": 20, "percentages": [50, 30, 20]})
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(data["amounts"], [60.0, 36.0, 24.0])

    def test_api_split_percentage_validation(self):
        status, data = self._post_to(
            "/api/split-percentage",
            {"bill": 100, "tip_percent": 20, "percentages": [50, 30]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_target_per_person_happy(self):
        status, data = self._post_to(
            "/api/target-per-person",
            {"bill": 100, "target_per_person": 40, "people": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(data["tip"], 20.0)

    def test_api_target_per_person_validation(self):
        status, data = self._post_to(
            "/api/target-per-person",
            {"bill": 100, "target_per_person": 30, "people": 3})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_round_total_happy(self):
        status, data = self._post_to(
            "/api/round-total",
            {"bill": 100, "base_percent": 18, "nearest": 5})
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(data["tip"], 20.0)
        self.assertEqual(data["bonus"], 2.0)

    def test_api_round_total_direction(self):
        status, data = self._post_to(
            "/api/round-total",
            {"bill": 100, "base_percent": 18, "nearest": 5, "direction": "down"})
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 115.0)

    def test_api_round_total_validation(self):
        status, data = self._post_to(
            "/api/round-total",
            {"bill": 100, "base_percent": 18, "nearest": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_split_comped_happy(self):
        status, data = self._post_to(
            "/api/split-comped",
            {"bill": 100, "tip_percent": 20, "people": 3, "comped": [2]})
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(data["payers"], 2)
        self.assertEqual([p["amount"] for p in data["people_detail"]],
                         [60.0, 60.0, 0.0])

    def test_api_split_comped_validation(self):
        status, data = self._post_to(
            "/api/split-comped",
            {"bill": 100, "tip_percent": 20, "people": 3, "comped": [0, 1, 2]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_gross_up_tip_happy(self):
        status, data = self._post_to(
            "/api/gross-up-tip",
            {"bill": 100, "tip_percent": 20, "fee_percent": 20})
        self.assertEqual(status, 200)
        self.assertEqual(data["gross_tip"], 25.0)
        self.assertEqual(data["fee"], 5.0)
        self.assertEqual(data["total"], 125.0)

    def test_api_gross_up_tip_validation(self):
        status, data = self._post_to(
            "/api/gross-up-tip",
            {"bill": 100, "tip_percent": 20, "fee_percent": 100})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_shared_items_happy(self):
        status, data = self._post_to(
            "/api/shared-items",
            {"diners": [[10], [10], [10]],
             "shared_items": [{"price": 30, "sharers": [0, 1]}],
             "tip_percent": 0})
        self.assertEqual(status, 200)
        self.assertEqual([p["amount"] for p in data["people"]], [25.0, 25.0, 10.0])
        self.assertEqual(data["total"], 60.0)

    def test_api_shared_items_validation(self):
        status, data = self._post_to(
            "/api/shared-items", {"diners": [], "tip_percent": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_regional_tip_happy(self):
        status, data = self._post_to(
            "/api/regional-tip", {"bill": 100, "region": "US"})
        self.assertEqual(status, 200)
        self.assertEqual(data["customary"], 18.0)
        self.assertEqual(data["total"], 118.0)
        self.assertEqual(data["region"], "US")

    def test_api_regional_tip_validation(self):
        status, data = self._post_to(
            "/api/regional-tip", {"bill": 100, "region": "Atlantis"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_charity_happy(self):
        status, data = self._post_to(
            "/api/charity", {"bill": 100, "tip_percent": 18, "round_to": 5})
        self.assertEqual(status, 200)
        self.assertEqual(data["donation"], 2.0)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(data["tip"], 18.0)

    def test_api_charity_validation(self):
        status, data = self._post_to(
            "/api/charity", {"bill": 100, "tip_percent": 18, "round_to": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_diner_tips_happy(self):
        status, data = self._post_to("/api/diner-tips", {"diners": [
            {"name": "Sam", "amount": 30, "tip_percent": 20},
            {"name": "Alex", "amount": 45, "tip_percent": 15},
            {"name": "Jo", "amount": 25, "tip_percent": 25},
        ]})
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 100.0)
        self.assertEqual(data["tip"], 19.0)
        self.assertEqual(data["total"], 119.0)
        self.assertEqual([d["tip"] for d in data["diners"]], [6.0, 6.75, 6.25])

    def test_api_diner_tips_with_tax(self):
        status, data = self._post_to("/api/diner-tips", {
            "diners": [{"amount": 50, "tip_percent": 20}], "tax": 5})
        self.assertEqual(status, 200)
        self.assertEqual(data["diners"][0]["total"], 65.0)

    def test_api_diner_tips_validation(self):
        status, data = self._post_to("/api/diner-tips", {"diners": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()
