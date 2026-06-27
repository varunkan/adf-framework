#!/usr/bin/env python3
"""Tests for the tip calculator — core domain logic and HTTP API."""
import json
import socket
import threading
import time
import http.client
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
    tip_matrix,
    affordable_bill,
    card_cash_split,
    tiered_tax_split,
    guest_of_honor_split,
    clean_share_split,
    redeem_loyalty,
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


class TestCardCashSplit(unittest.TestCase):
    def test_only_card_payers_pay_surcharge(self):
        r = card_cash_split([
            {"name": "Sam", "amount": 30, "method": "card"},
            {"name": "Alex", "amount": 45, "method": "cash"},
            {"name": "Jo", "amount": 25, "method": "card"},
        ], tip_percent=0, card_surcharge=3)
        by = {d["name"]: d for d in r["diners"]}
        self.assertEqual(by["Sam"]["surcharge"], 0.9)   # 3% of 30
        self.assertEqual(by["Alex"]["surcharge"], 0.0)  # cash pays nothing
        self.assertEqual(by["Jo"]["surcharge"], 0.75)   # 3% of 25
        self.assertEqual(r["surcharge"], 1.65)

    def test_surcharge_levied_on_amount_plus_tax_plus_tip(self):
        # one card diner: amount 50, tip 20% (=10), tax 5 -> base 65; 4% -> 2.60.
        r = card_cash_split([{"amount": 50, "method": "card"}],
                            tip_percent=20, tax=5, card_surcharge=4)
        d = r["diners"][0]
        self.assertEqual(d["tip"], 10.0)
        self.assertEqual(d["tax"], 5.0)
        self.assertEqual(d["surcharge"], 2.6)
        self.assertEqual(d["total"], 67.6)

    def test_grand_total_reconciles_to_per_diner_totals(self):
        r = card_cash_split([
            {"amount": 33.33, "method": "card"},
            {"amount": 41.11, "method": "cash"},
            {"amount": 25.55, "method": "card"},
        ], tip_percent=18, tax=8.77, card_surcharge=2.5)
        self.assertEqual(round(sum(d["total"] for d in r["diners"]), 2), r["total"])

    def test_totals_breakdown(self):
        r = card_cash_split([
            {"amount": 30, "method": "card"},
            {"amount": 70, "method": "cash"},
        ], tip_percent=10, card_surcharge=2)
        self.assertEqual(r["subtotal"], 100.0)
        self.assertEqual(r["tip"], 10.0)          # 10% of 100
        # card diner base = 30 + tip 3 = 33; 2% -> 0.66.
        self.assertEqual(r["surcharge"], 0.66)
        self.assertEqual(r["total"], 110.66)
        self.assertEqual(r["people"], 2)

    def test_card_and_cash_counts(self):
        r = card_cash_split([
            {"amount": 10, "method": "card"},
            {"amount": 10, "method": "cash"},
            {"amount": 10, "method": "card"},
        ])
        self.assertEqual(r["card_count"], 2)
        self.assertEqual(r["cash_count"], 1)

    def test_method_defaults_to_cash(self):
        r = card_cash_split([{"amount": 40}], card_surcharge=5)
        self.assertEqual(r["diners"][0]["method"], "cash")
        self.assertEqual(r["diners"][0]["surcharge"], 0.0)
        self.assertEqual(r["cash_count"], 1)

    def test_method_case_insensitive(self):
        r = card_cash_split([{"amount": 10, "method": "CARD"}], card_surcharge=10)
        self.assertEqual(r["diners"][0]["method"], "card")
        self.assertEqual(r["diners"][0]["surcharge"], 1.0)

    def test_tax_allocated_proportionally(self):
        # amounts 75 / 25 -> tax 10 splits 7.50 / 2.50.
        r = card_cash_split([
            {"amount": 75, "method": "cash"},
            {"amount": 25, "method": "cash"},
        ], tax=10)
        self.assertEqual([d["tax"] for d in r["diners"]], [7.5, 2.5])
        self.assertEqual(sum(d["tax"] for d in r["diners"]), r["tax"])

    def test_zero_surcharge_means_no_extra(self):
        r = card_cash_split([{"amount": 50, "method": "card"}], tip_percent=20)
        self.assertEqual(r["surcharge"], 0.0)
        self.assertEqual(r["diners"][0]["total"], 60.0)

    def test_string_inputs_coerced(self):
        r = card_cash_split([{"amount": "30", "method": "card"}],
                            tip_percent="0", tax="0", card_surcharge="3")
        self.assertEqual(r["diners"][0]["surcharge"], 0.9)

    def test_default_names(self):
        r = card_cash_split([{"amount": 10}, {"amount": 20}])
        self.assertEqual([d["name"] for d in r["diners"]], ["Diner 1", "Diner 2"])

    def test_empty_list_rejected(self):
        with self.assertRaises(TipError):
            card_cash_split([])

    def test_none_rejected(self):
        with self.assertRaises(TipError):
            card_cash_split(None)

    def test_non_list_rejected(self):
        with self.assertRaises(TipError):
            card_cash_split({"amount": 10})

    def test_diner_not_object_rejected(self):
        with self.assertRaises(TipError):
            card_cash_split([42])

    def test_bad_method_rejected(self):
        with self.assertRaises(TipError):
            card_cash_split([{"amount": 10, "method": "bitcoin"}])

    def test_negative_amount_rejected(self):
        with self.assertRaises(TipError):
            card_cash_split([{"amount": -1, "method": "card"}])

    def test_negative_surcharge_rejected(self):
        with self.assertRaises(TipError):
            card_cash_split([{"amount": 10, "method": "card"}], card_surcharge=-1)

    def test_negative_tip_percent_rejected(self):
        with self.assertRaises(TipError):
            card_cash_split([{"amount": 10}], tip_percent=-5)

    def test_negative_tax_rejected(self):
        with self.assertRaises(TipError):
            card_cash_split([{"amount": 10}], tax=-1)


class TestDinerSplitSharedHelpers(unittest.TestCase):
    # Locks in the shared diner-parsing helpers extracted from tip_by_diner /
    # card_cash_split so the two stay behaviourally identical (no dup drift).
    def test_validate_diners_list_rejects_empties_and_scalars(self):
        for bad in (None, "", [], "abc", {"amount": 1}, 5):
            with self.assertRaises(TipError):
                server._validate_diners_list(bad)
        self.assertEqual(server._validate_diners_list([{"amount": 1}]),
                         [{"amount": 1}])

    def test_parse_diner_name_amount_defaults_and_validation(self):
        name, cents = server._parse_diner_name_amount({"amount": 12.34}, 2)
        self.assertEqual((name, cents), ("Diner 3", 1234))
        name, cents = server._parse_diner_name_amount(
            {"name": "Pat", "amount": "5"}, 0)
        self.assertEqual((name, cents), ("Pat", 500))
        with self.assertRaises(TipError):
            server._parse_diner_name_amount("nope", 0)
        with self.assertRaises(TipError):
            server._parse_diner_name_amount({"amount": -1}, 0)

    def test_parse_tax_shares_sums_exactly(self):
        total, shares = server._parse_tax_shares(10, [3333, 3333, 3334])
        self.assertEqual(total, 1000)
        self.assertEqual(sum(shares), 1000)
        self.assertEqual(server._parse_tax_shares(None, [100])[0], 0)
        with self.assertRaises(TipError):
            server._parse_tax_shares(-1, [100])

    def test_both_callers_share_identical_diner_parsing(self):
        # Same diners through both functions must agree on name/amount/tax split.
        diners = [{"name": "X", "amount": 40, "tip_percent": 0},
                  {"amount": 60, "tip_percent": 0}]
        a = tip_by_diner(diners, tax=10)
        b = card_cash_split(diners, tax=10)
        for da, db in zip(a["diners"], b["diners"]):
            self.assertEqual(da["name"], db["name"])
            self.assertEqual(da["amount"], db["amount"])
            self.assertEqual(da["tax"], db["tax"])


# ---------------------------------------------------------------------------
# HTTP API tests
# ---------------------------------------------------------------------------


class TestAffordableBill(unittest.TestCase):
    # Inverse planner: solve for the affordable bill given a per-person budget.

    def test_happy_post_tax_tip(self):
        # $50pp x 4 = $200, tip on tax-inclusive total: 200 / (1.08*1.20) = 154.32.
        r = affordable_bill(50, 4, 20, 8)
        self.assertEqual(r["bill"], 154.32)
        self.assertEqual(r["tax"], 12.35)
        self.assertEqual(r["tip"], 33.33)
        self.assertEqual(r["total"], 200.0)
        self.assertEqual(r["per_person"], 50.0)

    def test_subtotal_mode(self):
        # tip on pre-tax subtotal: 60 / (1 + 0.10 + 0.15) = 48.00 exactly.
        r = affordable_bill(60, 1, 15, 10, "subtotal")
        self.assertEqual(r["bill"], 48.0)
        self.assertEqual(r["tax"], 4.8)
        self.assertEqual(r["tip"], 7.2)
        self.assertEqual(r["total"], 60.0)
        self.assertEqual(r["tip_on"], "subtotal")

    def test_never_exceeds_budget(self):
        # Across many awkward inputs the grand total must stay within budget.
        for budget in (10, 23.45, 50, 99.99, 137):
            for people in (1, 2, 3, 5):
                for tip in (0, 15, 18.5, 22):
                    for tax in (0, 7, 8.875):
                        for mode in ("total", "subtotal"):
                            r = affordable_bill(budget, people, tip, tax, mode)
                            self.assertLessEqual(
                                r["total"], round(budget * people, 2) + 1e-9,
                                (budget, people, tip, tax, mode))
                            self.assertGreaterEqual(r["headroom"], 0.0)

    def test_amounts_sum_to_total(self):
        r = affordable_bill(33.33, 3, 18, 6)
        self.assertEqual(round(sum(r["amounts"]), 2), r["total"])
        self.assertEqual(len(r["amounts"]), 3)

    def test_headroom_reported(self):
        r = affordable_bill(50, 4, 20, 8)
        self.assertEqual(r["headroom"], round(r["total_budget"] - r["total"], 2))

    def test_zero_tip_and_tax(self):
        r = affordable_bill(25, 2, 0, 0)
        self.assertEqual(r["bill"], 50.0)
        self.assertEqual(r["total"], 50.0)
        self.assertEqual(r["tip"], 0.0)
        self.assertEqual(r["tax"], 0.0)
        self.assertEqual(r["effective_tip_percent"], 0.0)

    def test_zero_budget(self):
        r = affordable_bill(0, 4, 20, 8)
        self.assertEqual(r["bill"], 0.0)
        self.assertEqual(r["total"], 0.0)
        self.assertEqual(r["amounts"], [0.0, 0.0, 0.0, 0.0])

    def test_string_inputs_coerced(self):
        r = affordable_bill("50", "4", "20", "8")
        self.assertEqual(r["bill"], 154.32)
        self.assertEqual(r["people"], 4)

    def test_defaults_no_tip_no_tax(self):
        # people defaults to 1; tip/tax default to 0 -> bill equals budget.
        r = affordable_bill(40)
        self.assertEqual(r["people"], 1)
        self.assertEqual(r["bill"], 40.0)
        self.assertEqual(r["total"], 40.0)

    def test_effective_tip_percent(self):
        # Post-tax tipping makes the effective pre-tax rate exceed the nominal one.
        r = affordable_bill(50, 4, 20, 8)
        self.assertGreater(r["effective_tip_percent"], 20.0)

    def test_negative_budget_rejected(self):
        with self.assertRaises(TipError):
            affordable_bill(-5, 4, 20, 8)

    def test_negative_tip_rejected(self):
        with self.assertRaises(TipError):
            affordable_bill(50, 4, -20, 8)

    def test_negative_tax_rejected(self):
        with self.assertRaises(TipError):
            affordable_bill(50, 4, 20, -8)

    def test_zero_people_rejected(self):
        with self.assertRaises(TipError):
            affordable_bill(50, 0, 20, 8)

    def test_fractional_people_rejected(self):
        with self.assertRaises(TipError):
            affordable_bill(50, 2.5, 20, 8)

    def test_missing_budget_rejected(self):
        with self.assertRaises(TipError):
            affordable_bill(None, 4, 20, 8)

    def test_bad_tip_on_rejected(self):
        with self.assertRaises(TipError):
            affordable_bill(50, 4, 20, 8, "sideways")


class TestTieredTaxSplit(unittest.TestCase):
    # Split-rate tax: food and alcohol taxed at their own rates, then tip + split.

    def test_happy_separate_rates(self):
        # Food 80 @ 6% = 4.80; alcohol 40 @ 10% = 4.00; subtotal 120, tax 8.80.
        # Tip on pre-tax subtotal (default): 120 * 20% = 24.00; total = 152.80.
        r = tiered_tax_split(80, 40, 6, 10, 20, 2)
        self.assertEqual(r["food_tax"], 4.8)
        self.assertEqual(r["alcohol_tax"], 4.0)
        self.assertEqual(r["subtotal"], 120.0)
        self.assertEqual(r["tax"], 8.8)
        self.assertEqual(r["tip"], 24.0)
        self.assertEqual(r["total"], 152.8)
        self.assertEqual(r["tip_on"], "subtotal")

    def test_per_category_rates_differ(self):
        # The whole point: alcohol is taxed harder than food.
        r = tiered_tax_split(100, 100, 5, 15, 0, 1)
        self.assertEqual(r["food_tax"], 5.0)
        self.assertEqual(r["alcohol_tax"], 15.0)
        self.assertEqual(r["tax"], 20.0)

    def test_blended_tax_percent(self):
        # 8.80 tax on 120 subtotal -> 7.33% blended.
        r = tiered_tax_split(80, 40, 6, 10, 20, 2)
        self.assertEqual(r["blended_tax_percent"], 7.33)

    def test_tip_on_total_mode(self):
        # tip_on=total tips on the tax-inclusive amount, so tip is larger.
        sub = tiered_tax_split(80, 40, 6, 10, 20, 2, "subtotal")
        tot = tiered_tax_split(80, 40, 6, 10, 20, 2, "total")
        self.assertEqual(sub["tip"], 24.0)
        self.assertEqual(tot["tip"], 25.76)  # 20% of (120 + 8.80)
        self.assertGreater(tot["tip"], sub["tip"])

    def test_amounts_sum_to_total_exactly(self):
        # Largest-remainder split must reconcile to the cent across people.
        for people in (1, 2, 3, 5, 7):
            r = tiered_tax_split(33.33, 17.77, 6.25, 9.5, 18, people)
            self.assertEqual(len(r["amounts"]), people)
            self.assertEqual(round(sum(r["amounts"]), 2), r["total"])

    def test_alcohol_defaults_to_zero(self):
        # No drinks: behaves like a single-rate food bill.
        r = tiered_tax_split(50, food_tax_percent=8, tip_percent=20)
        self.assertEqual(r["alcohol"], 0.0)
        self.assertEqual(r["alcohol_tax"], 0.0)
        self.assertEqual(r["tax"], 4.0)
        self.assertEqual(r["tip"], 10.0)
        self.assertEqual(r["total"], 64.0)

    def test_string_inputs_coerced(self):
        r = tiered_tax_split("80", "40", "6", "10", "20", "2")
        self.assertEqual(r["total"], 152.8)
        self.assertEqual(r["people"], 2)

    def test_zero_tax_and_tip(self):
        r = tiered_tax_split(60, 40, 0, 0, 0, 1)
        self.assertEqual(r["tax"], 0.0)
        self.assertEqual(r["tip"], 0.0)
        self.assertEqual(r["total"], 100.0)
        self.assertEqual(r["blended_tax_percent"], 0.0)
        self.assertEqual(r["effective_tip_percent"], 0.0)

    def test_effective_tip_percent_subtotal(self):
        # Tipping 20% on subtotal yields exactly 20% effective vs subtotal.
        r = tiered_tax_split(80, 40, 6, 10, 20, 2)
        self.assertEqual(r["effective_tip_percent"], 20.0)

    def test_zero_subtotal_no_div_by_zero(self):
        r = tiered_tax_split(0, 0, 6, 10, 20, 3)
        self.assertEqual(r["total"], 0.0)
        self.assertEqual(r["amounts"], [0.0, 0.0, 0.0])
        self.assertEqual(r["blended_tax_percent"], 0.0)

    def test_negative_food_rejected(self):
        with self.assertRaises(TipError):
            tiered_tax_split(-5, 10, 6, 10, 20, 2)

    def test_negative_alcohol_rejected(self):
        with self.assertRaises(TipError):
            tiered_tax_split(50, -10, 6, 10, 20, 2)

    def test_negative_food_tax_rejected(self):
        with self.assertRaises(TipError):
            tiered_tax_split(50, 10, -6, 10, 20, 2)

    def test_negative_alcohol_tax_rejected(self):
        with self.assertRaises(TipError):
            tiered_tax_split(50, 10, 6, -10, 20, 2)

    def test_negative_tip_rejected(self):
        with self.assertRaises(TipError):
            tiered_tax_split(50, 10, 6, 10, -20, 2)

    def test_missing_food_rejected(self):
        with self.assertRaises(TipError):
            tiered_tax_split(None, 10, 6, 10, 20, 2)

    def test_zero_people_rejected(self):
        with self.assertRaises(TipError):
            tiered_tax_split(50, 10, 6, 10, 20, 0)

    def test_fractional_people_rejected(self):
        with self.assertRaises(TipError):
            tiered_tax_split(50, 10, 6, 10, 20, 2.5)

    def test_bad_tip_on_rejected(self):
        with self.assertRaises(TipError):
            tiered_tax_split(50, 10, 6, 10, 20, 2, "sideways")

    def test_overflow_rejected(self):
        with self.assertRaises(TipError):
            tiered_tax_split(1e308, 1e308, 1e308, 1e308, 1e308, 1)


class TestSplitWithCaps(unittest.TestCase):
    """split_with_caps — water-filling when some diners have a spending cap."""

    def test_no_caps_even_split(self):
        # All caps None → plain even split.
        r = split_with_caps(100, 20, 3, [None, None, None])
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["fair_share"], 40.0)
        self.assertFalse(any(p["capped"] for p in r["people_detail"]))

    def test_one_capped_overflow_redistributed(self):
        # Bill 100 + 20% tip = 120 / 3 = 40 each.
        # Diner 0 capped at 20 → shortfall 20 split between diners 1 & 2.
        r = split_with_caps(100, 20, 3, [20, None, None])
        self.assertEqual(r["amounts"][0], 20.0)
        self.assertTrue(r["people_detail"][0]["capped"])
        self.assertEqual(round(sum(r["amounts"]), 2), 120.0)

    def test_amounts_sum_exactly_to_total(self):
        # Exact cent reconciliation under odd split.
        for people in (3, 5, 7):
            caps = [None] * people
            caps[0] = 5.0
            r = split_with_caps(33.33, 15, people, caps)
            self.assertEqual(round(sum(r["amounts"]), 2), r["total"])

    def test_all_caps_insufficient_raises(self):
        # Total = 120; all three capped at 10 (30 total) — cannot cover.
        with self.assertRaises(TipError):
            split_with_caps(100, 20, 3, [10, 10, 10])

    def test_caps_wrong_length_raises(self):
        with self.assertRaises(TipError):
            split_with_caps(100, 20, 3, [None, None])  # 2 caps, 3 people

    def test_caps_not_list_raises(self):
        with self.assertRaises(TipError):
            split_with_caps(100, 20, 2, "bad")

    def test_negative_cap_raises(self):
        with self.assertRaises(TipError):
            split_with_caps(100, 20, 2, [-5, None])

    def test_capped_flag_false_when_below_cap(self):
        # Diner 0 capped at 100, fair share is 40 → not capped.
        r = split_with_caps(100, 20, 3, [100, None, None])
        self.assertFalse(r["people_detail"][0]["capped"])

    def test_null_string_cap_treated_as_uncapped(self):
        r = split_with_caps(100, 20, 2, ["", None])
        self.assertFalse(r["people_detail"][0]["capped"])
        self.assertEqual(round(sum(r["amounts"]), 2), 120.0)

    def test_returns_bill_tip_people_fields(self):
        r = split_with_caps(80, 25, 2, [None, None])
        self.assertEqual(r["bill"], 80.0)
        self.assertEqual(r["tip_percent"], 25.0)
        self.assertEqual(r["people"], 2)
        self.assertEqual(r["tip"], 20.0)


class TestTipExcluding(unittest.TestCase):
    """tip_excluding — gratuity on a subset of the bill."""

    def test_basic_exclusion(self):
        # Bill 100, exclude 40 → tip on 60 @ 20% = 12; total = 112.
        r = tip_excluding(100, 20, 40)
        self.assertEqual(r["excluded"], 40.0)
        self.assertEqual(r["eligible"], 60.0)
        self.assertEqual(r["tip"], 12.0)
        self.assertEqual(r["total"], 112.0)

    def test_excluded_list_summed(self):
        # Exclude [25, 15] = 40.
        r = tip_excluding(100, 20, [25, 15])
        self.assertEqual(r["excluded"], 40.0)
        self.assertEqual(r["tip"], 12.0)

    def test_excluded_string_number(self):
        r = tip_excluding(100, 20, "30")
        self.assertEqual(r["excluded"], 30.0)
        self.assertEqual(r["eligible"], 70.0)

    def test_excluded_none_defaults_zero(self):
        r = tip_excluding(100, 20, None)
        self.assertEqual(r["excluded"], 0.0)
        self.assertEqual(r["tip"], 20.0)

    def test_excluded_empty_string_defaults_zero(self):
        r = tip_excluding(100, 20, "")
        self.assertEqual(r["excluded"], 0.0)

    def test_excluded_equals_bill_zero_tip(self):
        r = tip_excluding(100, 20, 100)
        self.assertEqual(r["eligible"], 0.0)
        self.assertEqual(r["tip"], 0.0)
        self.assertEqual(r["total"], 100.0)

    def test_per_person_split_exact(self):
        for people in (1, 2, 3, 5):
            r = tip_excluding(100, 18, 30, people)
            self.assertEqual(len(r["per_person_amounts"]), people)
            self.assertEqual(round(sum(r["per_person_amounts"]), 2), r["total"])

    def test_zero_bill_effective_equals_tip_percent(self):
        r = tip_excluding(0, 20, 0)
        self.assertEqual(r["total"], 0.0)
        self.assertEqual(r["effective_tip_percent"], 20.0)

    def test_excluded_exceeds_bill_raises(self):
        with self.assertRaises(TipError):
            tip_excluding(80, 20, 100)

    def test_negative_excluded_in_list_raises(self):
        with self.assertRaises(TipError):
            tip_excluding(100, 20, [30, -5])

    def test_negative_bill_raises(self):
        with self.assertRaises(TipError):
            tip_excluding(-10, 20, 0)

    def test_effective_tip_less_than_nominal(self):
        # Tip of 20% on 60/100 eligible → 12/100 = 12% effective.
        r = tip_excluding(100, 20, 40)
        self.assertAlmostEqual(r["effective_tip_percent"], 12.0)


class TestTipMatrix(unittest.TestCase):
    """tip_matrix — 2-D grid of tip percents × party sizes."""

    def test_basic_matrix_shape(self):
        r = tip_matrix(100, [15, 20], [1, 2, 4])
        self.assertEqual(len(r["rows"]), 2)
        self.assertEqual(len(r["rows"][0]["cells"]), 3)

    def test_cheapest_priciest_populated(self):
        r = tip_matrix(100, [15, 20], [1, 2])
        self.assertIsNotNone(r["cheapest"])
        self.assertIsNotNone(r["priciest"])
        # Cheapest is smallest percent × most people; priciest is opposite.
        self.assertLessEqual(
            r["cheapest"]["total_per_person"], r["priciest"]["total_per_person"])

    def test_row_totals_consistent(self):
        r = tip_matrix(80, [15, 20, 25], [1, 2, 4])
        for row in r["rows"]:
            for cell in row["cells"]:
                self.assertIn("total_per_person", cell)

    def test_default_percents_and_people(self):
        r = tip_matrix(100)
        self.assertEqual(r["people_options"], [1, 2, 4])
        self.assertEqual(len(r["rows"]), 4)  # default (15, 18, 20, 25)

    def test_tax_passed_through(self):
        r_no_tax = tip_matrix(110, [20], [1], tax=0)
        r_tax = tip_matrix(110, [20], [1], tax=10)
        # With tax=10, tip base is the same ($110) but result keys include tax.
        self.assertIn("tax", r_no_tax)
        self.assertAlmostEqual(r_tax["tax"], 10.0)

    def test_negative_bill_raises(self):
        with self.assertRaises(TipError):
            tip_matrix(-1, [15], [1])

    def test_empty_percents_raises(self):
        with self.assertRaises(TipError):
            tip_matrix(100, [], [1])

    def test_empty_people_options_raises(self):
        with self.assertRaises(TipError):
            tip_matrix(100, [15], [])

    def test_percents_not_list_raises(self):
        with self.assertRaises(TipError):
            tip_matrix(100, "bad", [1])

    def test_people_options_not_list_raises(self):
        with self.assertRaises(TipError):
            tip_matrix(100, [15], "bad")


class TestCoverageGaps(unittest.TestCase):
    """Targeted tests for previously uncovered branches."""

    # _validate_people edge cases (lines 52, 54, 57-58)
    def test_people_bool_rejected(self):
        with self.assertRaises(TipError):
            calculate_tip(100, 20, True)

    def test_people_none_defaults_to_one(self):
        r = calculate_tip(100, 20, None)
        self.assertEqual(r["people"], 1)

    def test_people_empty_string_defaults_to_one(self):
        r = calculate_tip(100, 20, "")
        self.assertEqual(r["people"], 1)

    # _normalise_tip_on edge cases (lines 89, 91)
    def test_tip_on_none_defaults_total(self):
        r = calculate_tip(110, 20, tip_on=None, tax=10)
        self.assertEqual(r["tip_on"], "total")

    def test_tip_on_non_string_raises(self):
        with self.assertRaises(TipError):
            calculate_tip(100, 20, tip_on=42)

    # calculate_tip round_total=True (lines 160-161)
    def test_round_total_true_rounds_up(self):
        # 100 + 18% = 118 — already whole, so stays 118.
        r = calculate_tip(100, 18, round_total=True)
        self.assertEqual(r["total"], 118.0)
        r2 = calculate_tip(100, 15.5, round_total=True)
        self.assertEqual(r2["total"], float(int(r2["total"])))

    # reverse_tip zero bill (line 211)
    def test_reverse_tip_zero_bill_effective_zero(self):
        from server import reverse_tip
        r = reverse_tip(0, 0)
        self.assertEqual(r["effective_tip_percent"], 0.0)

    # round_up_split zero bill / zero effective (line 257)
    def test_round_up_split_zero_bill_uses_tip_percent(self):
        r = round_up_split(0, 20, 1)
        self.assertEqual(r["effective_tip_percent"], 20.0)

    # suggest_tips default percents (line 285)
    def test_suggest_tips_default_percents(self):
        r = suggest_tips(100)
        percents = [t["tip_percent"] for t in r["tiers"]]
        self.assertIn(10.0, percents)
        self.assertIn(15.0, percents)

    # _largest_remainder zero-weight edge (lines 361-366)
    def test_largest_remainder_zero_weights_spreads_evenly(self):
        from server import _largest_remainder
        result = _largest_remainder(10, [0, 0, 0])
        self.assertEqual(sum(result), 10)
        self.assertEqual(len(result), 3)

    # settle_up shares-not-list (line 490)
    def test_settle_up_shares_not_list_raises(self):
        with self.assertRaises(TipError):
            settle_up(100, 20, [120, 0, 0], shares="bad")

    # _normalise_discount_type (lines 700, 702)
    def test_discount_type_none_defaults_amount(self):
        from server import _normalise_discount_type
        self.assertEqual(_normalise_discount_type(None), "amount")

    def test_discount_type_non_string_raises(self):
        from server import _normalise_discount_type
        with self.assertRaises(TipError):
            _normalise_discount_type(42)

    # build_bill negative tip_percent (line 968)
    def test_build_bill_negative_tip_percent_raises(self):
        with self.assertRaises(TipError):
            build_bill([10], 0, -5)

    # _normalise_currency (lines 1056, 1058)
    def test_currency_none_defaults_usd(self):
        from server import _normalise_currency
        self.assertEqual(_normalise_currency(None), "USD")

    def test_currency_non_string_raises(self):
        from server import _normalise_currency
        with self.assertRaises(TipError):
            _normalise_currency(42)

    # split_by_percentage zero-sum percents (line 1177)
    def test_split_percentage_zero_sum_raises(self):
        with self.assertRaises(TipError):
            split_by_percentage(100, 20, [0, 0, 0])

    # tip_for_target_per_person zero bill (line 1226)
    def test_target_per_person_zero_bill_effective_zero(self):
        r = tip_for_target_per_person(0, 0)
        self.assertEqual(r["effective_tip_percent"], 0.0)

    # _normalise_direction (lines 1243, 1245)
    def test_direction_none_defaults_up(self):
        from server import _normalise_direction
        self.assertEqual(_normalise_direction(None), "up")

    def test_direction_non_string_raises(self):
        from server import _normalise_direction
        with self.assertRaises(TipError):
            _normalise_direction(42)

    # round_total_to (lines 1296, 1312, 1335)
    def test_round_total_negative_tax_raises(self):
        with self.assertRaises(TipError):
            round_total_to(100, 18, tax=-5)

    def test_round_total_zero_bill_effective_equals_base(self):
        r = round_total_to(0, 20, nearest=1)
        self.assertEqual(r["effective_tip_percent"], 20.0)

    # split_comped edge cases (lines 1379, 1387, 1390-1391)
    def test_split_comped_none_comped_defaults_empty(self):
        r = split_comped(100, 20, 3, comped=None)
        self.assertEqual(r["payers"], 3)

    def test_split_comped_bool_index_raises(self):
        with self.assertRaises(TipError):
            split_comped(100, 20, 2, comped=[True])

    def test_split_comped_non_numeric_index_raises(self):
        with self.assertRaises(TipError):
            split_comped(100, 20, 2, comped=["a"])

    # _parse_shared_item edge cases (lines 1506, 1516, 1522, 1528, 1532-1533, 1536)
    def test_shared_item_empty_list_raises(self):
        with self.assertRaises(TipError):
            split_shared_items([[10], [10]], shared_items=[[]])

    def test_shared_item_negative_price_raises(self):
        with self.assertRaises(TipError):
            split_shared_items([[10], [10]], shared_items=[[-5]])

    def test_shared_item_sharers_not_list_raises(self):
        with self.assertRaises(TipError):
            split_shared_items([[10], [10]], shared_items=[{"price": 5, "sharers": "bad"}])

    def test_shared_item_bool_sharer_raises(self):
        with self.assertRaises(TipError):
            split_shared_items([[10], [10]], shared_items=[{"price": 5, "sharers": [True]}])

    def test_shared_item_non_numeric_sharer_raises(self):
        with self.assertRaises(TipError):
            split_shared_items([[10], [10]], shared_items=[{"price": 5, "sharers": ["x"]}])

    def test_shared_item_fractional_sharer_raises(self):
        with self.assertRaises(TipError):
            split_shared_items([[10], [10]], shared_items=[{"price": 5, "sharers": [0.5]}])

    # split_shared_items shared_items not list (line 1604)
    def test_split_shared_items_not_list_raises(self):
        with self.assertRaises(TipError):
            split_shared_items([[10], [10]], shared_items="bad")

    # charity_round_up very small round_to (line 1770)
    def test_charity_round_up_tiny_round_to_raises(self):
        with self.assertRaises(TipError):
            charity_round_up(100, 18, round_to=0.001)

    # tip_by_diner zero subtotal (line 1976)
    def test_tip_by_diner_zero_subtotal_effective_zero(self):
        r = tip_by_diner([{"name": "Sam", "amount": 0, "tip_percent": 0}])
        self.assertEqual(r["effective_tip_percent"], 0.0)

    # affordable_bill edge cases (lines 2245, 2250-2251)
    def test_affordable_bill_zero_budget_per_person(self):
        r = affordable_bill(0, 1)
        self.assertEqual(r["bill"], 0.0)
        self.assertEqual(r["total"], 0.0)

    # _validate_people: int() raises on a non-numeric string (lines 57-58)
    def test_people_unparseable_string_raises(self):
        with self.assertRaises(TipError):
            calculate_tip(100, 20, "abc")

    # reverse_tip negative target_total (line 203)
    def test_reverse_tip_negative_target_raises(self):
        with self.assertRaises(TipError):
            reverse_tip(100, -5)

    # round_up_split: nearest > 0 but rounds to zero cents (line 247)
    def test_round_up_split_sub_cent_nearest_raises(self):
        with self.assertRaises(TipError):
            round_up_split(100, 20, 1, 0.001)

    # suggest_tips None / empty percents fall back to defaults (line 285)
    def test_suggest_tips_none_percents_uses_defaults(self):
        r = suggest_tips(100, percents=None)
        self.assertEqual(len(r["tiers"]), 5)
        r2 = suggest_tips(100, percents="")
        self.assertEqual(len(r2["tiers"]), 5)

    # split_by_shares negative bill / tip (lines 313, 315)
    def test_split_by_shares_negative_bill_raises(self):
        with self.assertRaises(TipError):
            split_by_shares(-1, 20, [1, 1])

    def test_split_by_shares_negative_tip_raises(self):
        with self.assertRaises(TipError):
            split_by_shares(100, -1, [1, 1])

    # round_total_to: nearest > 0 but rounds to zero cents (line 1312)
    def test_round_total_to_sub_cent_nearest_raises(self):
        with self.assertRaises(TipError):
            round_total_to(100, 18, nearest=0.001)

    # tip_excluding negative tip / excluded (lines 1840, 1842)
    def test_tip_excluding_negative_tip_raises(self):
        with self.assertRaises(TipError):
            tip_excluding(100, -1, 0)

    def test_tip_excluding_negative_excluded_raises(self):
        with self.assertRaises(TipError):
            tip_excluding(100, 20, -5)

    # tip_matrix None / empty percents and people_options use defaults
    # (lines 2125, 2133)
    def test_tip_matrix_none_percents_uses_defaults(self):
        r = tip_matrix(100, percents=None)
        self.assertEqual(len(r["rows"]), 4)  # default (15, 18, 20, 25)
        r2 = tip_matrix(100, percents="")
        self.assertEqual(len(r2["rows"]), 4)

    def test_tip_matrix_none_people_options_uses_defaults(self):
        r = tip_matrix(100, people_options=None)
        self.assertTrue(len(r["people_options"]) >= 1)
        r2 = tip_matrix(100, people_options="")
        self.assertTrue(len(r2["people_options"]) >= 1)

    # affordable_bill: tiny budget where rounding tax/tip up would overshoot the
    # budget, exercising the step-down reconciliation loop (lines 2250-2251).
    def test_affordable_bill_stepdown_loop_stays_within_budget(self):
        r = affordable_bill(0.04, 1, 12.6, 16.7, "total")
        self.assertLessEqual(r["total"], 0.04 + 1e-9)
        self.assertGreaterEqual(r["headroom"], 0.0)


class TestGuestOfHonorSplit(unittest.TestCase):
    # REQ-002 extension: treat one or more diners; the rest split the whole total.
    def test_treat_one_diner_others_cover(self):
        r = guest_of_honor_split(120, 20, 4, [1])
        # Total = 144; diner index 1 is treated, the other three split 144.
        self.assertEqual(r["total"], 144.0)
        self.assertEqual(r["tip"], 24.0)
        self.assertEqual(r["payers"], 3)
        self.assertEqual(r["guests"], [1])
        self.assertEqual(r["people_detail"][1]["amount"], 0.0)
        self.assertTrue(r["people_detail"][1]["guest"])
        self.assertEqual(round(sum(r["amounts"]), 2), 144.0)
        # The three payers each cover 48.00.
        self.assertEqual([r["amounts"][i] for i in (0, 2, 3)], [48.0, 48.0, 48.0])

    def test_amounts_reconcile_exactly_with_odd_total(self):
        # 100 + 10% = 110 split by 3 payers -> 36.67/36.67/36.66 (largest remainder)
        r = guest_of_honor_split(100, 10, 4, [3])
        payer_amounts = [r["amounts"][i] for i in (0, 1, 2)]
        self.assertEqual(sorted(payer_amounts), [36.66, 36.67, 36.67])
        self.assertEqual(r["amounts"][3], 0.0)
        self.assertEqual(round(sum(r["amounts"]), 2), 110.0)

    def test_no_guests_is_plain_even_split(self):
        r = guest_of_honor_split(100, 20, 4)
        self.assertEqual(r["guests"], [])
        self.assertEqual(r["payers"], 4)
        self.assertEqual(r["amounts"], [30.0, 30.0, 30.0, 30.0])

    def test_empty_guest_list_allowed(self):
        r = guest_of_honor_split(80, 0, 2, [])
        self.assertEqual(r["payers"], 2)
        self.assertEqual(r["amounts"], [40.0, 40.0])

    def test_multiple_guests(self):
        r = guest_of_honor_split(200, 0, 5, [0, 4])
        self.assertEqual(r["guests"], [0, 4])
        self.assertEqual(r["payers"], 3)
        self.assertEqual(r["amounts"][0], 0.0)
        self.assertEqual(r["amounts"][4], 0.0)
        self.assertEqual(round(sum(r["amounts"]), 2), 200.0)

    def test_fair_share_reported(self):
        r = guest_of_honor_split(90, 0, 3, [2])
        self.assertEqual(r["fair_share"], 45.0)

    def test_treating_everyone_fails_safe(self):
        with self.assertRaises(TipError):
            guest_of_honor_split(100, 20, 3, [0, 1, 2])

    def test_guest_index_out_of_range_rejected(self):
        with self.assertRaises(TipError):
            guest_of_honor_split(100, 20, 3, [3])

    def test_negative_guest_index_rejected(self):
        with self.assertRaises(TipError):
            guest_of_honor_split(100, 20, 3, [-1])

    def test_duplicate_guest_rejected(self):
        with self.assertRaises(TipError):
            guest_of_honor_split(100, 20, 3, [1, 1])

    def test_non_integer_guest_rejected(self):
        with self.assertRaises(TipError):
            guest_of_honor_split(100, 20, 3, [1.5])

    def test_boolean_guest_rejected(self):
        with self.assertRaises(TipError):
            guest_of_honor_split(100, 20, 3, [True])

    def test_guests_not_a_list_rejected(self):
        with self.assertRaises(TipError):
            guest_of_honor_split(100, 20, 3, "1")

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            guest_of_honor_split(-10, 20, 3, [0])

    def test_negative_tip_rejected(self):
        with self.assertRaises(TipError):
            guest_of_honor_split(100, -5, 3, [0])

    def test_zero_bill_zero_amounts(self):
        r = guest_of_honor_split(0, 20, 3, [0])
        self.assertEqual(r["total"], 0.0)
        self.assertEqual(r["amounts"], [0.0, 0.0, 0.0])


class TestCleanShareSplit(unittest.TestCase):
    # REQ-002 extension: even split where everyone pays a clean amount and the
    # organizer absorbs the rounding remainder.
    def test_even_total_no_rounding_needed(self):
        # 100 + 20% = 120 split by 3 -> 40 each, already clean.
        r = clean_share_split(100, 20, 3, organizer=0)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["amounts"], [40.0, 40.0, 40.0])
        self.assertEqual(r["organizer"], 0)
        self.assertEqual(r["organizer_delta"], 0.0)

    def test_others_round_organizer_absorbs(self):
        # 100 + 0% = 100 split by 3 -> fair 33.33; others pay clean $33,
        # organizer covers 100 - 66 = 34.
        r = clean_share_split(100, 0, 3, organizer=0, nearest=1.0)
        self.assertEqual(r["clean_amount"], 33.0)
        self.assertEqual(r["amounts"][1], 33.0)
        self.assertEqual(r["amounts"][2], 33.0)
        self.assertEqual(r["amounts"][0], 34.0)
        self.assertEqual(round(sum(r["amounts"]), 2), 100.0)
        self.assertEqual(r["organizer_delta"], 0.67)

    def test_sum_is_exactly_total(self):
        r = clean_share_split(87.41, 18, 5, organizer=2, nearest=1.0)
        self.assertEqual(round(sum(r["amounts"]), 2), r["total"])
        self.assertEqual(r["amounts"][2], r["organizer_amount"])

    def test_organizer_index_honoured(self):
        r = clean_share_split(100, 0, 3, organizer=2)
        self.assertTrue(r["people_detail"][2]["organizer"])
        self.assertFalse(r["people_detail"][0]["organizer"])
        self.assertEqual(r["amounts"][2], 34.0)

    def test_nearest_increment_five(self):
        # 100 split by 3, round others to nearest $5 -> 35 each (33.33 -> 35),
        # organizer covers 100 - 70 = 30.
        r = clean_share_split(100, 0, 3, organizer=0, nearest=5.0)
        self.assertEqual(r["amounts"][1], 35.0)
        self.assertEqual(r["amounts"][2], 35.0)
        self.assertEqual(r["amounts"][0], 30.0)
        self.assertEqual(round(sum(r["amounts"]), 2), 100.0)

    def test_single_person_pays_full_total(self):
        r = clean_share_split(50, 10, 1)
        self.assertEqual(r["amounts"], [55.0])
        self.assertEqual(r["organizer_amount"], 55.0)

    def test_default_organizer_is_zero(self):
        r = clean_share_split(100, 0, 3)
        self.assertEqual(r["organizer"], 0)

    def test_tip_on_subtotal(self):
        # bill 110 includes 10 tax; tip 20% on the 100 subtotal = 20 -> total 130.
        r = clean_share_split(110, 20, 2, organizer=0, tax=10, tip_on="subtotal")
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["total"], 130.0)
        self.assertEqual(r["subtotal"], 100.0)

    def test_nearest_too_large_fails_safe(self):
        # nearest $50 on a $90 cheque: each $30 share rounds UP to $50, so the
        # two others would owe $100 together — more than the whole total, which
        # would force the organizer's share negative -> fail safe.
        with self.assertRaises(TipError):
            clean_share_split(90, 0, 3, organizer=0, nearest=50.0)

    def test_organizer_out_of_range_rejected(self):
        with self.assertRaises(TipError):
            clean_share_split(100, 20, 3, organizer=3)

    def test_negative_organizer_rejected(self):
        with self.assertRaises(TipError):
            clean_share_split(100, 20, 3, organizer=-1)

    def test_non_integer_organizer_rejected(self):
        with self.assertRaises(TipError):
            clean_share_split(100, 20, 3, organizer=1.5)

    def test_boolean_organizer_rejected(self):
        with self.assertRaises(TipError):
            clean_share_split(100, 20, 3, organizer=True)

    def test_zero_nearest_rejected(self):
        with self.assertRaises(TipError):
            clean_share_split(100, 20, 3, nearest=0)

    def test_negative_nearest_rejected(self):
        with self.assertRaises(TipError):
            clean_share_split(100, 20, 3, nearest=-1)

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            clean_share_split(-10, 20, 3)

    def test_negative_tip_rejected(self):
        with self.assertRaises(TipError):
            clean_share_split(100, -5, 3)

    def test_tax_exceeds_bill_rejected(self):
        with self.assertRaises(TipError):
            clean_share_split(50, 10, 2, tax=60)

    def test_negative_tax_rejected(self):
        with self.assertRaises(TipError):
            clean_share_split(100, 10, 2, tax=-5)

    def test_zero_bill_zero_amounts(self):
        r = clean_share_split(0, 20, 3, organizer=1)
        self.assertEqual(r["total"], 0.0)
        self.assertEqual(r["amounts"], [0.0, 0.0, 0.0])


class TestRedeemLoyalty(unittest.TestCase):
    # REQ-001/002 extension: burn loyalty points as a payment credit while the
    # gratuity is still charged on the FULL pre-redemption service value.
    def test_happy_path_tip_on_full_bill(self):
        # 500 pts @ $0.01 = $5 credit; tip is 20% of the full $100, NOT $95.
        r = redeem_loyalty(100, 20, points=500, point_value=0.01, people=1)
        self.assertEqual(r["redemption"], 5.0)
        self.assertEqual(r["tip"], 20.0)          # tipped on full value
        self.assertEqual(r["amount_due"], 115.0)  # 100 - 5 + 20
        self.assertEqual(r["remaining_points"], 0.0)
        self.assertEqual(r["effective_discount_percent"], 5.0)

    def test_points_redeem_only_in_whole_increments(self):
        # 550 points in 100-point blocks -> only 500 burn, 50 stay on the card.
        r = redeem_loyalty(100, 20, points=550, point_value=0.01, increment=100)
        self.assertEqual(r["redeemed_points"], 500.0)
        self.assertEqual(r["remaining_points"], 50.0)
        self.assertEqual(r["redemption"], 5.0)

    def test_redemption_capped_at_amount_owed(self):
        # $10 of points offered against a $4 cheque: credit caps at $4, the rest
        # of the points are handed back and the bill can never go negative.
        r = redeem_loyalty(4, 0, points=1000, point_value=0.01)
        self.assertEqual(r["redemption"], 4.0)
        self.assertEqual(r["redeemed_points"], 400.0)
        self.assertEqual(r["remaining_points"], 600.0)
        self.assertEqual(r["amount_due"], 0.0)

    def test_explicit_max_redeem_cap(self):
        # max_redeem holds the credit below what the points alone would buy.
        r = redeem_loyalty(100, 20, points=2000, point_value=0.01, max_redeem=7)
        self.assertEqual(r["redemption"], 7.0)
        self.assertEqual(r["amount_due"], 113.0)  # 100 - 7 + 20

    def test_cap_respects_increment_blocks(self):
        # cap is $4 but points only burn in 300-point ($3) blocks, so the credit
        # rounds DOWN to $3, never up past the cap.
        r = redeem_loyalty(4, 0, points=1000, point_value=0.01, increment=300)
        self.assertEqual(r["redeemed_points"], 300.0)
        self.assertEqual(r["redemption"], 3.0)
        self.assertEqual(r["amount_due"], 1.0)

    def test_tip_on_total_includes_tax(self):
        # tip_on="total" tips on bill+tax; redemption still only credits payment.
        r = redeem_loyalty(100, 10, points=0, tax=8, tip_on="total")
        self.assertEqual(r["tip"], 10.8)          # 10% of 108
        self.assertEqual(r["amount_due"], 118.8)  # 108 - 0 + 10.8

    def test_split_is_exact_across_people(self):
        r = redeem_loyalty(100, 20, points=500, point_value=0.01, people=3)
        self.assertEqual(round(sum(r["per_person_amounts"]), 2), r["amount_due"])
        self.assertEqual(len(r["per_person_amounts"]), 3)

    def test_no_points_is_a_plain_bill(self):
        r = redeem_loyalty(50, 20, points=0)
        self.assertEqual(r["redemption"], 0.0)
        self.assertEqual(r["amount_due"], 60.0)

    def test_negative_bill_rejected(self):
        with self.assertRaises(TipError):
            redeem_loyalty(-1, 20, points=100)

    def test_negative_points_rejected(self):
        with self.assertRaises(TipError):
            redeem_loyalty(100, 20, points=-5)

    def test_negative_point_value_rejected(self):
        with self.assertRaises(TipError):
            redeem_loyalty(100, 20, points=100, point_value=-0.01)

    def test_non_positive_increment_rejected(self):
        with self.assertRaises(TipError):
            redeem_loyalty(100, 20, points=100, increment=0)

    def test_negative_max_redeem_rejected(self):
        with self.assertRaises(TipError):
            redeem_loyalty(100, 20, points=100, max_redeem=-1)


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

    def test_api_health_alias(self):
        # The ADF verify harness probes /api/health; it must alias /health.
        with urllib.request.urlopen(self._url("/api/health")) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(json.loads(resp.read())["status"], "ok")

    def test_favicon_no_404(self):
        # The browser implicitly requests /favicon.ico; it must not 404
        # (which would surface as a console error on the home page).
        with urllib.request.urlopen(self._url("/favicon.ico")) as resp:
            self.assertEqual(resp.status, 204)

    def test_index_inline_js_is_syntactically_valid(self):
        # Regression: INDEX_HTML is a non-raw Python string, so a JS string
        # literal like split("\\n") must keep its backslash escaped in the
        # source or Python turns it into a real newline and breaks the JS,
        # raising "SyntaxError: Invalid or unexpected token" in the browser.
        import re
        html = server.INDEX_HTML
        script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
        # No string literal may contain an unescaped raw newline.
        self.assertNotIn('split("\n', script)
        # The intended two-character escape must survive into the served JS.
        self.assertIn('split("\\n")', script)

    def test_index_escapes_user_names_in_dom(self):
        # DOM-XSS guard: user-controlled name strings (a diner's name, a built
        # bill's line-item name) are echoed back from the API and injected via
        # innerHTML. They MUST pass through esc() so a name like
        # "<img src=x onerror=alert(1)>" cannot execute script in the browser.
        import re
        html = server.INDEX_HTML
        script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
        # The escape helper itself must be defined and cover every HTML metachar.
        self.assertIn("const esc =", script)
        for ch in ("&", "<", ">", '"', "'"):
            self.assertIn(ch, script.split("const esc =", 1)[1][:200])
        # Both user-controlled name sinks must be wrapped in esc(...).
        self.assertIn("esc(d.name)", script)
        self.assertIn("esc(it.name)", script)
        # Regression: the raw, unescaped sinks must NOT reappear.
        self.assertNotIn("+ d.name +", script)
        self.assertNotIn("' + it.name + '", script)

    def test_diner_name_is_preserved_verbatim_by_api(self):
        # The server stores the diner name as-is (escaping is the browser's job
        # via esc()); confirm a script-y name round-trips unchanged through the
        # API so the client-side guard is the single, tested point of defense.
        status, data = self._post_to(
            "/api/diner-tips",
            {"diners": [{"name": "<b>Sam</b>", "amount": 30, "tip_percent": 20}]})
        self.assertEqual(status, 200)
        self.assertEqual(data["diners"][0]["name"], "<b>Sam</b>")

    def test_api_card_split_happy_path(self):
        status, data = self._post_to("/api/card-split", {
            "diners": [
                {"name": "Sam", "amount": 30, "method": "card"},
                {"name": "Alex", "amount": 70, "method": "cash"},
            ],
            "tip_percent": 10,
            "card_surcharge": 2,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 100.0)
        self.assertEqual(data["tip"], 10.0)
        self.assertEqual(data["surcharge"], 0.66)   # 2% of (30 + 3 tip)
        self.assertEqual(data["total"], 110.66)
        self.assertEqual(data["card_count"], 1)
        self.assertEqual(data["cash_count"], 1)

    def test_api_card_split_validation_error(self):
        status, data = self._post_to(
            "/api/card-split", {"diners": [{"amount": 10, "method": "crypto"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

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

    def test_api_affordable_bill_happy(self):
        status, data = self._post_to("/api/affordable-bill", {
            "budget": 50, "people": 4, "tip_percent": 20, "tax_percent": 8})
        self.assertEqual(status, 200)
        self.assertEqual(data["bill"], 154.32)
        self.assertEqual(data["total"], 200.0)
        self.assertEqual(data["per_person"], 50.0)
        self.assertEqual(data["headroom"], 0.0)

    def test_api_affordable_bill_subtotal_mode(self):
        status, data = self._post_to("/api/affordable-bill", {
            "budget": 60, "tip_percent": 15, "tax_percent": 10,
            "tip_on": "subtotal"})
        self.assertEqual(status, 200)
        self.assertEqual(data["bill"], 48.0)
        self.assertEqual(data["tip_on"], "subtotal")

    def test_api_affordable_bill_defaults(self):
        status, data = self._post_to("/api/affordable-bill", {"budget": 40})
        self.assertEqual(status, 200)
        self.assertEqual(data["people"], 1)
        self.assertEqual(data["bill"], 40.0)

    def test_api_affordable_bill_validation(self):
        status, data = self._post_to("/api/affordable-bill", {"budget": -5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_tiered_tax_happy(self):
        status, data = self._post_to("/api/tiered-tax", {
            "food": 80, "alcohol": 40, "food_tax_percent": 6,
            "alcohol_tax_percent": 10, "tip_percent": 20, "people": 2})
        self.assertEqual(status, 200)
        self.assertEqual(data["food_tax"], 4.8)
        self.assertEqual(data["alcohol_tax"], 4.0)
        self.assertEqual(data["tax"], 8.8)
        self.assertEqual(data["tip"], 24.0)
        self.assertEqual(data["total"], 152.8)
        self.assertEqual(round(sum(data["amounts"]), 2), data["total"])

    def test_api_tiered_tax_total_mode(self):
        status, data = self._post_to("/api/tiered-tax", {
            "food": 80, "alcohol": 40, "food_tax_percent": 6,
            "alcohol_tax_percent": 10, "tip_percent": 20, "people": 2,
            "tip_on": "total"})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip"], 25.76)
        self.assertEqual(data["tip_on"], "total")

    def test_api_tiered_tax_alcohol_defaults_zero(self):
        status, data = self._post_to("/api/tiered-tax", {
            "food": 50, "food_tax_percent": 8, "tip_percent": 20})
        self.assertEqual(status, 200)
        self.assertEqual(data["alcohol"], 0.0)
        self.assertEqual(data["total"], 64.0)

    def test_api_tiered_tax_validation_error(self):
        status, data = self._post_to("/api/tiered-tax", {"food": -5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_tiered_tax_missing_food(self):
        status, data = self._post_to("/api/tiered-tax", {"alcohol": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_guest_of_honor_happy(self):
        status, data = self._post_to("/api/guest-of-honor", {
            "bill": 120, "tip_percent": 20, "people": 4, "guests": [1]})
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 144.0)
        self.assertEqual(data["payers"], 3)
        self.assertEqual(data["guests"], [1])
        self.assertEqual(data["amounts"][1], 0.0)
        self.assertEqual(round(sum(data["amounts"]), 2), data["total"])

    def test_api_guest_of_honor_no_guests_even_split(self):
        status, data = self._post_to("/api/guest-of-honor", {
            "bill": 100, "tip_percent": 20, "people": 4})
        self.assertEqual(status, 200)
        self.assertEqual(data["guests"], [])
        self.assertEqual(data["amounts"], [30.0, 30.0, 30.0, 30.0])

    def test_api_guest_of_honor_treat_everyone_error(self):
        status, data = self._post_to("/api/guest-of-honor", {
            "bill": 100, "tip_percent": 20, "people": 3, "guests": [0, 1, 2]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_guest_of_honor_out_of_range_error(self):
        status, data = self._post_to("/api/guest-of-honor", {
            "bill": 100, "tip_percent": 20, "people": 3, "guests": [5]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_clean_split_happy(self):
        status, data = self._post_to("/api/clean-split", {
            "bill": 100, "tip_percent": 0, "people": 3, "organizer": 0, "nearest": 1})
        self.assertEqual(status, 200)
        self.assertEqual(data["amounts"], [34.0, 33.0, 33.0])
        self.assertEqual(round(sum(data["amounts"]), 2), data["total"])
        self.assertEqual(data["organizer"], 0)

    def test_api_clean_split_defaults_organizer(self):
        status, data = self._post_to("/api/clean-split", {
            "bill": 100, "tip_percent": 20, "people": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["organizer"], 0)
        self.assertEqual(data["amounts"], [40.0, 40.0, 40.0])

    def test_api_clean_split_organizer_out_of_range_error(self):
        status, data = self._post_to("/api/clean-split", {
            "bill": 100, "tip_percent": 20, "people": 3, "organizer": 9})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_clean_split_nearest_too_large_error(self):
        status, data = self._post_to("/api/clean-split", {
            "bill": 90, "tip_percent": 0, "people": 3, "nearest": 50})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- Defect 1: unbounded people count (DoS) ---

    def test_people_max_boundary_accepted(self):
        """people=10000 (max) must succeed."""
        status, data = self._post_to("/api/calculate", {"bill": 10, "tip_percent": 15, "people": 10000})
        self.assertEqual(status, 200)
        self.assertEqual(data["people"], 10000)

    def test_people_over_max_rejected(self):
        """people=10001 must be rejected with 400."""
        status, data = self._post_to("/api/calculate", {"bill": 10, "tip_percent": 15, "people": 10001})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_people_huge_integer_rejected(self):
        """people=100_000_000 (memory DoS) must be rejected."""
        status, data = self._post_to("/api/charity", {"bill": 10, "tip_percent": 15, "people": 100000000})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_people_large_float_rejected(self):
        """people=1e20 (huge float coerced to int) must be rejected."""
        status, data = self._post_to("/api/round-total", {"bill": 10, "base_percent": 15, "people": 1e20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_people_huge_on_comp_endpoint(self):
        """split_comped with huge people must be rejected cleanly."""
        status, data = self._post_to("/api/split-comped",
                                     {"bill": 10, "tip_percent": 15, "people": 9999999})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_people_huge_on_combine_endpoint(self):
        """combine_checks with huge people must be rejected cleanly."""
        status, data = self._post_to("/api/combine",
                                     {"checks": [{"bill": 10, "tip_percent": 15}], "people": 50000})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- Defect 2: numeric overflow → non-finite JSON ---

    def test_overflow_calculate_returns_400_not_infinity_json(self):
        """Huge bill*tip_percent must return 400, not 200 with Infinity body."""
        status, data = self._post_to("/api/calculate", {"bill": 1e308, "tip_percent": 1e308})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_overflow_convert_large_rate_rejected(self):
        """convert_currency with rate that overflows converted total must return 400."""
        status, data = self._post_to("/api/convert",
                                     {"bill": 1e308, "tip_percent": 15, "rate": 1e308})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_overflow_round_total_large_inputs_rejected(self):
        """round_total_to with inputs that overflow intermediate base_cents must return 400."""
        status, data = self._post_to("/api/round-total",
                                     {"bill": 1e308, "base_percent": 1e308})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_overflow_gross_up_tip_near_100_fee(self):
        """gross_up_tip with fee_percent causing huge gross_tip must return 400, not 500."""
        status, data = self._post_to("/api/gross-up-tip",
                                     {"bill": 1e308, "tip_percent": 20, "fee_percent": 50})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_overflow_build_bill_large_price_qty(self):
        """build_bill with price*qty overflow must return 400."""
        status, data = self._post_to("/api/build-bill",
                                     {"items": [{"price": 1e308, "qty": 2}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # Previously-untested dispatch routes (server.py lines 3798, 3895, 3907).
    def test_api_split_caps_happy_path(self):
        status, data = self._post_to("/api/split-caps", {
            "bill": 100, "tip_percent": 20, "people": 3,
            "caps": [50, 50, 50]})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["amounts"]), 2), data["total"])

    def test_api_split_caps_validation_error(self):
        status, data = self._post_to("/api/split-caps",
                                     {"bill": -1, "tip_percent": 20, "people": 2})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_tip_excluding_happy_path(self):
        status, data = self._post_to("/api/tip-excluding", {
            "bill": 100, "tip_percent": 20, "excluded": 20, "people": 1})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip"], 16.0)  # 20% of (100 - 20)

    def test_api_tip_excluding_validation_error(self):
        status, data = self._post_to("/api/tip-excluding",
                                     {"bill": 100, "tip_percent": 20,
                                      "excluded": 200})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_loyalty_redeem_happy_path(self):
        status, data = self._post_to("/api/loyalty-redeem", {
            "bill": 100, "tip_percent": 20, "points": 500,
            "point_value": 0.01, "people": 2})
        self.assertEqual(status, 200)
        self.assertEqual(data["redemption"], 5.0)
        self.assertEqual(data["tip"], 20.0)
        self.assertEqual(data["amount_due"], 115.0)
        self.assertEqual(round(sum(data["per_person_amounts"]), 2),
                         data["amount_due"])

    def test_api_loyalty_redeem_validation_error(self):
        status, data = self._post_to("/api/loyalty-redeem",
                                     {"bill": 100, "tip_percent": 20,
                                      "points": -5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_api_tip_matrix_happy_path(self):
        status, data = self._post_to("/api/tip-matrix", {
            "bill": 100, "percents": [15, 20], "people_options": [1, 2]})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["rows"]), 2)

    def test_api_tip_matrix_validation_error(self):
        status, data = self._post_to("/api/tip-matrix", {"bill": -1})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # POST error paths (server.py lines 3709-3710, 3713-3714, 3722-3723).
    def test_api_unknown_post_route_404(self):
        status, data = self._post_to("/api/does-not-exist", {})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_api_post_body_not_object_400(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("POST", "/api/calculate", body=b"[1,2,3]",
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = json.loads(resp.read())
        conn.close()
        self.assertEqual(resp.status, 400)
        self.assertIn("error", body)

    def test_api_post_bad_content_length_header(self):
        # A non-integer Content-Length must not crash the handler: it falls back
        # to a zero-length body, which then yields a clean validation error.
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.putrequest("POST", "/api/calculate", skip_accept_encoding=True)
        conn.putheader("Content-Length", "abc")
        conn.putheader("Content-Type", "application/json")
        conn.endheaders(message_body=b"")
        resp = conn.getresponse()
        body = json.loads(resp.read())
        conn.close()
        self.assertEqual(resp.status, 400)
        self.assertIn("error", body)


class TestRunServer(unittest.TestCase):
    """Exercise the run() entry point (server.py lines 3958-3965)."""

    def test_run_boots_and_serves_health(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        t = threading.Thread(
            target=server.run, kwargs={"host": "127.0.0.1", "port": port},
            daemon=True)
        t.start()
        last_err = None
        for _ in range(100):
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/health" % port, timeout=1) as resp:
                    self.assertEqual(json.loads(resp.read())["status"], "ok")
                    return
            except Exception as e:  # not up yet
                last_err = e
                time.sleep(0.05)
        self.fail("run() server did not come up: %r" % last_err)

    def test_run_handles_keyboard_interrupt_cleanly(self):
        # Simulate Ctrl-C: serve_forever raises KeyboardInterrupt, which run()
        # must swallow and still close the server in its finally block.
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        original = ThreadingHTTPServer.serve_forever

        def _interrupt(self, *a, **k):
            raise KeyboardInterrupt

        ThreadingHTTPServer.serve_forever = _interrupt
        try:
            server.run(host="127.0.0.1", port=port)  # returns cleanly
        finally:
            ThreadingHTTPServer.serve_forever = original


if __name__ == "__main__":
    unittest.main()
