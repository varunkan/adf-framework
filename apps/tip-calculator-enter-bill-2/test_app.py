"""Test suite for tip-calculator-enter-bill-2.

Covers the pure domain logic (cents conversion, fair splitting, tip
calculation, presets) and the HTTP API surface (index, health, /api/tip,
/api/presets, error handling). Pure Python 3 standard library only.

Run:  python3 -m unittest -v
"""

import json
import threading
import unittest
import urllib.error
import urllib.request

import server
from server import (
    _coerce_coupons,
    _coerce_discount,
    _coerce_items,
    _coerce_percents,
    _coerce_weights,
    _from_cents,
    _to_cents,
    _coerce_amounts,
    _coerce_categories,
    _coerce_comped,
    _coerce_increment,
    _coerce_percent_range,
    _coerce_seat_list,
    _coerce_brackets,
    _coerce_gift_card,
    _coerce_fee,
    _coerce_percent_shares,
    _coerce_bill_entries,
    _coerce_tipouts,
    _coerce_tax_categories,
    distribute_tipout,
    multi_rate_tax_bill,
    summarize_bills,
    apply_coupons,
    calculate,
    calculate_bill,
    calculate_with_discount,
    card_surcharge_bill,
    charity_round_up,
    combine_bills,
    comp_diner_split,
    delivery_order,
    extract_tax_bill,
    split_by_percentage,
    split_mixed_payment,
    tip_by_category,
    compare_scenarios,
    convert_currency,
    distribute_pool,
    format_receipt,
    gift_card_split,
    make_server,
    recommend_tip,
    round_total_to_nearest,
    service_charge_bill,
    split_amount,
    split_bill_by_weights,
    split_by_items,
    split_by_assignment,
    split_shared_items,
    split_round_up_per_person,
    split_custom_tips,
    split_items_custom_tips,
    split_to_denomination,
    settle_up,
    settle_payments,
    tiered_tip,
    split_weighted,
    suggest_tips,
    tip_guide,
    tip_for_total,
    tip_from_amount,
    tip_from_per_person,
    tip_within_budget,
    DEFAULT_PRESET_PERCENTS,
    DISCOUNT_KINDS,
    ROUNDING_MODES,
    SERVICE_RATINGS,
    TIPOUT_BASES,
)


class CentsConversionTests(unittest.TestCase):
    def test_to_cents_rounds_to_nearest_cent(self):
        self.assertEqual(_to_cents(10), 1000)
        self.assertEqual(_to_cents("12.34"), 1234)
        self.assertEqual(_to_cents(0), 0)

    def test_to_cents_handles_float_drift(self):
        # 0.1 + 0.2 style drift must not leak into the cent count.
        self.assertEqual(_to_cents(19.99), 1999)
        self.assertEqual(_to_cents(0.1), 10)

    def test_from_cents_returns_two_decimal_dollars(self):
        self.assertEqual(_from_cents(1999), 19.99)
        self.assertEqual(_from_cents(0), 0.0)
        self.assertEqual(_from_cents(5), 0.05)

    def test_round_trip_is_stable(self):
        for dollars in ("0.00", "1.05", "99.99", "1234.56"):
            self.assertEqual(_from_cents(_to_cents(dollars)), float(dollars))


class SplitAmountTests(unittest.TestCase):
    def test_even_split(self):
        self.assertEqual(split_amount(1000, 4), [250, 250, 250, 250])

    def test_remainder_handed_to_first_people(self):
        # 1001 cents across 3 -> 334, 334, 333 (sums back to 1001).
        self.assertEqual(split_amount(1001, 3), [334, 334, 333])

    def test_shares_sum_back_to_total(self):
        for total in (0, 1, 7, 100, 1003, 99999):
            for people in (1, 2, 3, 5, 7, 13):
                shares = split_amount(total, people)
                self.assertEqual(sum(shares), total)
                self.assertEqual(len(shares), people)

    def test_shares_differ_by_at_most_one_cent(self):
        shares = split_amount(1003, 4)
        self.assertLessEqual(max(shares) - min(shares), 1)

    def test_single_person_gets_everything(self):
        self.assertEqual(split_amount(777, 1), [777])


class CalculateTests(unittest.TestCase):
    def test_basic_tip_and_total(self):
        r = calculate(100, 20)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["people"], 1)
        self.assertEqual(r["per_person"], 120.0)
        self.assertFalse(r["rounded"])

    def test_zero_tip(self):
        r = calculate(50, 0)
        self.assertEqual(r["tip"], 0.0)
        self.assertEqual(r["total"], 50.0)

    def test_zero_bill(self):
        r = calculate(0, 20)
        self.assertEqual(r["tip"], 0.0)
        self.assertEqual(r["total"], 0.0)

    def test_string_inputs_accepted(self):
        r = calculate("50.00", "18", "2")
        self.assertEqual(r["total"], 59.0)
        self.assertEqual(r["people"], 2)

    def test_split_across_people(self):
        r = calculate(100, 0, 3)
        self.assertEqual(r["shares"], [33.34, 33.33, 33.33])
        self.assertEqual(round(sum(r["shares"]), 2), 100.0)
        self.assertEqual(r["per_person"], 33.34)

    def test_per_person_tip(self):
        r = calculate(100, 20, 4)
        self.assertEqual(r["per_person_tip"], 5.0)

    def test_people_defaults_to_one_when_none(self):
        r = calculate(40, 10, None)
        self.assertEqual(r["people"], 1)

    def test_round_total_up_absorbs_into_tip(self):
        # 23.45 + 18% = 27.671 -> total 27.67, rounds up to 28.00.
        r = calculate(23.45, 18, 1, round_total=True)
        self.assertTrue(r["rounded"])
        self.assertEqual(r["total"], 28.0)
        # bill + tip must still equal total exactly.
        self.assertEqual(round(r["bill"] + r["tip"], 2), r["total"])

    def test_round_total_keeps_shares_summing(self):
        r = calculate(23.45, 18, 3, round_total=True)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])

    def test_round_total_noop_on_whole_dollar(self):
        r = calculate(100, 0, 1, round_total=True)
        self.assertEqual(r["total"], 100.0)

    def test_tip_percent_rounding_in_response(self):
        r = calculate(10, 33.333333)
        self.assertEqual(r["tip_percent"], 33.3333)

    # --- validation ---
    def test_missing_bill_raises(self):
        with self.assertRaises(ValueError):
            calculate(None, 20)

    def test_missing_tip_raises(self):
        with self.assertRaises(ValueError):
            calculate(100, None)

    def test_non_numeric_bill_raises(self):
        with self.assertRaises(ValueError):
            calculate("abc", 20)

    def test_negative_bill_raises(self):
        with self.assertRaises(ValueError):
            calculate(-1, 20)

    def test_negative_tip_raises(self):
        with self.assertRaises(ValueError):
            calculate(100, -5)

    def test_tip_over_100_raises(self):
        with self.assertRaises(ValueError):
            calculate(100, 101)

    def test_fractional_people_raises(self):
        with self.assertRaises(ValueError):
            calculate(100, 20, 2.5)

    def test_zero_people_raises(self):
        with self.assertRaises(ValueError):
            calculate(100, 20, 0)

    def test_nan_bill_raises(self):
        with self.assertRaises(ValueError):
            calculate(float("nan"), 20)


class CoercePercentsTests(unittest.TestCase):
    def test_none_falls_back_to_defaults(self):
        self.assertEqual(_coerce_percents(None), list(DEFAULT_PRESET_PERCENTS))

    def test_list_of_numbers(self):
        self.assertEqual(_coerce_percents([10, 15, 20]), [10.0, 15.0, 20.0])

    def test_string_numbers_coerced(self):
        self.assertEqual(_coerce_percents(["10", "12.5"]), [10.0, 12.5])

    def test_empty_list_raises(self):
        with self.assertRaises(ValueError):
            _coerce_percents([])

    def test_string_is_not_a_valid_list(self):
        with self.assertRaises(ValueError):
            _coerce_percents("20")

    def test_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            _coerce_percents([10, 150])

    def test_non_numeric_entry_raises(self):
        with self.assertRaises(ValueError):
            _coerce_percents([10, "abc"])


class SuggestTipsTests(unittest.TestCase):
    def test_default_presets(self):
        out = suggest_tips(100)
        self.assertEqual(len(out), len(DEFAULT_PRESET_PERCENTS))
        self.assertEqual([s["tip_percent"] for s in out], list(DEFAULT_PRESET_PERCENTS))

    def test_suggestions_carry_totals(self):
        out = suggest_tips(100, 1, [20])
        self.assertEqual(out[0]["tip"], 20.0)
        self.assertEqual(out[0]["total"], 120.0)
        self.assertEqual(out[0]["per_person"], 120.0)

    def test_custom_percents(self):
        out = suggest_tips(50, 2, [10])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["tip_percent"], 10.0)
        self.assertEqual(out[0]["per_person"], 27.5)

    def test_invalid_bill_raises(self):
        with self.assertRaises(ValueError):
            suggest_tips(-1)

    def test_invalid_percents_raise(self):
        with self.assertRaises(ValueError):
            suggest_tips(100, 1, [200])


class CalculateBillTests(unittest.TestCase):
    def test_subtotal_tax_and_tip_separated(self):
        # $100 bill, 10% tax, 20% tip on the pre-tax subtotal.
        r = calculate_bill(100, 20, tax_percent=10)
        self.assertEqual(r["subtotal"], 100.0)
        self.assertEqual(r["tax"], 10.0)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["total"], 130.0)
        self.assertEqual(r["tip_on"], "pretax")

    def test_zero_tax_matches_plain_calculate(self):
        bill_r = calculate_bill(50, 18, people=2)
        plain = calculate(50, 18, people=2)
        self.assertEqual(bill_r["tip"], plain["tip"])
        self.assertEqual(bill_r["total"], plain["total"])
        self.assertEqual(bill_r["per_person"], plain["per_person"])
        self.assertEqual(bill_r["tax"], 0.0)

    def test_tip_on_posttax_uses_taxed_base(self):
        # 20% tip on (100 + 10 tax) = 110 -> tip 22.00, total 132.00.
        r = calculate_bill(100, 20, tax_percent=10, tip_on="posttax")
        self.assertEqual(r["tip"], 22.0)
        self.assertEqual(r["total"], 132.0)

    def test_shares_sum_back_to_total(self):
        r = calculate_bill(100, 18, people=3, tax_percent=13)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])

    def test_per_person_tax_splits_fairly(self):
        r = calculate_bill(100, 0, people=3, tax_percent=10)
        # 1000 tax cents across 3 -> first person carries the extra cent.
        self.assertEqual(r["per_person_tax"], 3.34)

    def test_round_total_absorbs_into_tip(self):
        r = calculate_bill(23.45, 18, tax_percent=5, round_total=True)
        self.assertTrue(r["rounded"])
        self.assertEqual(r["total"], int(r["total"]))
        self.assertEqual(
            round(r["subtotal"] + r["tax"] + r["tip"], 2), r["total"])

    def test_invalid_tax_raises(self):
        with self.assertRaises(ValueError):
            calculate_bill(100, 20, tax_percent="abc")

    def test_tax_over_100_raises(self):
        with self.assertRaises(ValueError):
            calculate_bill(100, 20, tax_percent=150)

    def test_negative_tax_raises(self):
        with self.assertRaises(ValueError):
            calculate_bill(100, 20, tax_percent=-1)

    def test_invalid_tip_on_raises(self):
        with self.assertRaises(ValueError):
            calculate_bill(100, 20, tip_on="midtax")


class SplitWeightedTests(unittest.TestCase):
    def test_proportional_split(self):
        # 2:1:1 weights over 400 cents -> 200, 100, 100.
        self.assertEqual(split_weighted(400, [2, 1, 1]), [200, 100, 100])

    def test_shares_sum_back_to_total(self):
        for total in (0, 1, 7, 100, 1003, 99999):
            shares = split_weighted(total, [3, 2, 1])
            self.assertEqual(sum(shares), total)
            self.assertEqual(len(shares), 3)

    def test_largest_remainder_gets_extra_cent(self):
        # 100 cents over [1, 1, 1]: exact 33.33 each, remainder cent goes to
        # the first largest fractional remainder.
        shares = split_weighted(100, [1, 1, 1])
        self.assertEqual(sum(shares), 100)
        self.assertEqual(max(shares) - min(shares), 1)

    def test_equal_weights_match_even_split(self):
        self.assertEqual(split_weighted(1000, [1, 1, 1, 1]), [250, 250, 250, 250])

    def test_zero_weight_person_gets_nothing(self):
        self.assertEqual(split_weighted(300, [0, 1, 1]), [0, 150, 150])


class CoerceWeightsTests(unittest.TestCase):
    def test_list_of_numbers(self):
        self.assertEqual(_coerce_weights([2, 1, 1]), [2.0, 1.0, 1.0])

    def test_string_numbers_coerced(self):
        self.assertEqual(_coerce_weights(["2", "1"]), [2.0, 1.0])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            _coerce_weights([])

    def test_all_zero_raises(self):
        with self.assertRaises(ValueError):
            _coerce_weights([0, 0])

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            _coerce_weights([1, -1])

    def test_string_is_not_a_valid_list(self):
        with self.assertRaises(ValueError):
            _coerce_weights("21")

    def test_non_numeric_entry_raises(self):
        with self.assertRaises(ValueError):
            _coerce_weights([1, "abc"])


class SplitBillByWeightsTests(unittest.TestCase):
    def test_people_count_matches_weights(self):
        r = split_bill_by_weights(100, 20, [2, 1, 1])
        self.assertEqual(r["people"], 3)
        self.assertEqual(r["weights"], [2.0, 1.0, 1.0])

    def test_shares_sum_back_to_total(self):
        r = split_bill_by_weights(120, 18, [3, 2, 1], tax_percent=13)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])

    def test_tip_shares_sum_back_to_tip(self):
        r = split_bill_by_weights(120, 18, [3, 2, 1])
        self.assertEqual(round(sum(r["tip_shares"]), 2), r["tip"])

    def test_heavier_weight_pays_more(self):
        r = split_bill_by_weights(300, 0, [2, 1])
        self.assertGreater(r["shares"][0], r["shares"][1])

    def test_invalid_weights_raise(self):
        with self.assertRaises(ValueError):
            split_bill_by_weights(100, 20, [])


class RecommendTipTests(unittest.TestCase):
    def test_known_ratings_map_to_percent(self):
        for rating, percent in SERVICE_RATINGS.items():
            r = recommend_tip(100, rating)
            self.assertEqual(r["recommended_percent"], percent)
            self.assertEqual(r["tip_percent"], float(percent))
            self.assertEqual(r["rating"], rating)

    def test_good_service_breakdown(self):
        r = recommend_tip(100, "good")
        self.assertEqual(r["tip"], 18.0)
        self.assertEqual(r["total"], 118.0)

    def test_rating_is_case_and_space_insensitive(self):
        r = recommend_tip(100, "  GREAT  ")
        self.assertEqual(r["rating"], "great")
        self.assertEqual(r["recommended_percent"], 20)

    def test_carries_tax_and_split(self):
        r = recommend_tip(100, "good", people=2, tax_percent=10)
        self.assertEqual(r["tax"], 10.0)
        self.assertEqual(r["total"], 128.0)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])

    def test_missing_rating_raises(self):
        with self.assertRaises(ValueError):
            recommend_tip(100, None)

    def test_unknown_rating_raises(self):
        with self.assertRaises(ValueError):
            recommend_tip(100, "terrible")

    def test_invalid_bill_raises(self):
        with self.assertRaises(ValueError):
            recommend_tip(-1, "good")


class SplitByItemsTests(unittest.TestCase):
    def test_bill_is_sum_of_items(self):
        # Two people order $40 and $60 -> $100 bill, 0% tip/tax.
        r = split_by_items([40, 60], 0)
        self.assertEqual(r["subtotal"], 100.0)
        self.assertEqual(r["total"], 100.0)
        self.assertEqual(r["shares"], [40.0, 60.0])

    def test_per_person_item_lists_are_summed(self):
        r = split_by_items([[10, 5], [20]], 0)
        self.assertEqual(r["subtotal"], 35.0)
        self.assertEqual(r["breakdown"][0]["subtotal"], 15.0)
        self.assertEqual(r["breakdown"][1]["subtotal"], 20.0)

    def test_tip_apportioned_by_each_share(self):
        # 20% tip on $100, ordered $40 / $60 -> tip $8 / $12.
        r = split_by_items([40, 60], 20)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["breakdown"][0]["tip"], 8.0)
        self.assertEqual(r["breakdown"][1]["tip"], 12.0)

    def test_shares_and_breakdown_sum_back(self):
        r = split_by_items([[12.50, 3.25], [9.99], [20.00, 5.00]], 18,
                           tax_percent=13)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])
        self.assertEqual(round(sum(r["tip_shares"]), 2), r["tip"])
        for person in r["breakdown"]:
            self.assertEqual(
                round(person["subtotal"] + person["tax"] + person["tip"], 2),
                person["total"])

    def test_fully_comped_bill_splits_tip_evenly(self):
        # Everyone ordered nothing: tip/tax fall back to an even split.
        r = split_by_items([0, 0], 0, tax_percent=0)
        self.assertEqual(r["total"], 0.0)
        self.assertEqual(r["shares"], [0.0, 0.0])

    def test_empty_items_raise(self):
        with self.assertRaises(ValueError):
            split_by_items([], 20)

    def test_negative_item_raises(self):
        with self.assertRaises(ValueError):
            split_by_items([10, -5], 20)

    def test_non_list_items_raise(self):
        with self.assertRaises(ValueError):
            split_by_items("10,20", 20)


class CoerceItemsTests(unittest.TestCase):
    def test_numbers_become_singleton_lists(self):
        self.assertEqual(_coerce_items([10, 20]), [[10.0], [20.0]])

    def test_nested_lists_preserved(self):
        self.assertEqual(_coerce_items([[10, 5], [20]]), [[10.0, 5.0], [20.0]])

    def test_bool_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_items([True, 5])


class TipForTotalTests(unittest.TestCase):
    def test_derives_tip_from_target(self):
        # Bill 100, want to pay exactly 120 -> tip 20, effective 20%.
        r = tip_for_total(100, 120)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["tip_percent"], 20.0)

    def test_target_accounts_for_tax(self):
        # Bill 100 + 10% tax = 110 base; target 130 -> tip 20.
        r = tip_for_total(100, 130, tax_percent=10)
        self.assertEqual(r["tax"], 10.0)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["total"], 130.0)

    def test_target_split_sums_back(self):
        r = tip_for_total(100, 130, people=3)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])

    def test_target_below_base_raises(self):
        with self.assertRaises(ValueError):
            tip_for_total(100, 90, tax_percent=10)

    def test_missing_target_raises(self):
        with self.assertRaises(ValueError):
            tip_for_total(100, None)

    def test_negative_target_raises(self):
        with self.assertRaises(ValueError):
            tip_for_total(100, -10)


class CoerceDiscountTests(unittest.TestCase):
    def test_percent_off(self):
        # 10% off a $100 (10000 cents) bill -> 1000 cents.
        self.assertEqual(_coerce_discount(10, "percent", 10000), 1000)

    def test_amount_off(self):
        self.assertEqual(_coerce_discount(15, "amount", 10000), 1500)

    def test_amount_capped_at_bill(self):
        # A flat coupon larger than the bill can't go below zero.
        self.assertEqual(_coerce_discount(200, "amount", 10000), 10000)

    def test_string_coerced(self):
        self.assertEqual(_coerce_discount("25", "percent", 10000), 2500)

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            _coerce_discount(10, "fraction", 10000)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            _coerce_discount(-5, "percent", 10000)

    def test_percent_over_100_raises(self):
        with self.assertRaises(ValueError):
            _coerce_discount(150, "percent", 10000)

    def test_non_numeric_raises(self):
        with self.assertRaises(ValueError):
            _coerce_discount("abc", "percent", 10000)

    def test_kinds_constant_exposed(self):
        self.assertEqual(DISCOUNT_KINDS, ("percent", "amount"))


class CalculateWithDiscountTests(unittest.TestCase):
    def test_percent_discount_reduces_tip_and_tax(self):
        # $100, 10% off -> $90 subtotal; 20% tip on 90 = 18, total 108.
        r = calculate_with_discount(100, 20, 10, "percent")
        self.assertEqual(r["original_subtotal"], 100.0)
        self.assertEqual(r["discount_amount"], 10.0)
        self.assertEqual(r["subtotal"], 90.0)
        self.assertEqual(r["tip"], 18.0)
        self.assertEqual(r["total"], 108.0)

    def test_amount_discount(self):
        # $100, $25 off -> $75 subtotal; 0% tip, total 75.
        r = calculate_with_discount(100, 0, 25, "amount")
        self.assertEqual(r["discount_amount"], 25.0)
        self.assertEqual(r["subtotal"], 75.0)
        self.assertEqual(r["total"], 75.0)

    def test_discount_with_tax_and_tip(self):
        # $100, 10% off -> $90; 10% tax = 9; 20% tip on 90 = 18; total 117.
        r = calculate_with_discount(100, 20, 10, "percent", tax_percent=10)
        self.assertEqual(r["subtotal"], 90.0)
        self.assertEqual(r["tax"], 9.0)
        self.assertEqual(r["tip"], 18.0)
        self.assertEqual(r["total"], 117.0)

    def test_zero_discount_matches_calculate_bill(self):
        d = calculate_with_discount(100, 18, 0, "percent", people=3,
                                    tax_percent=13)
        b = calculate_bill(100, 18, people=3, tax_percent=13)
        self.assertEqual(d["total"], b["total"])
        self.assertEqual(d["tip"], b["tip"])
        self.assertEqual(d["discount_amount"], 0.0)

    def test_amount_over_bill_zeroes_subtotal(self):
        r = calculate_with_discount(20, 20, 100, "amount")
        self.assertEqual(r["subtotal"], 0.0)
        self.assertEqual(r["discount_amount"], 20.0)
        self.assertEqual(r["total"], 0.0)

    def test_shares_sum_back_to_total(self):
        r = calculate_with_discount(123.45, 18, 15, "percent", people=3,
                                    tax_percent=13)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])

    def test_invalid_discount_kind_raises(self):
        with self.assertRaises(ValueError):
            calculate_with_discount(100, 20, 10, "half-off")

    def test_negative_discount_raises(self):
        with self.assertRaises(ValueError):
            calculate_with_discount(100, 20, -5, "percent")


class CoerceCouponsTests(unittest.TestCase):
    def test_single_percent(self):
        applied, final = _coerce_coupons([{"kind": "percent", "value": 10}],
                                         10000)
        self.assertEqual(final, 9000)
        self.assertEqual(applied[0]["discount"], 10.0)
        self.assertEqual(applied[0]["subtotal_after"], 90.0)

    def test_percent_defaults_when_kind_omitted(self):
        # A coupon with no "kind" is treated as a percent (matches the default).
        applied, final = _coerce_coupons([{"value": 25}], 10000)
        self.assertEqual(final, 7500)
        self.assertEqual(applied[0]["kind"], "percent")

    def test_percents_compound(self):
        # 50% then 50% off $100 leaves 25%, not 0%.
        applied, final = _coerce_coupons(
            [{"kind": "percent", "value": 50}, {"kind": "percent", "value": 50}],
            10000)
        self.assertEqual(final, 2500)
        self.assertEqual(applied[0]["subtotal_after"], 50.0)
        self.assertEqual(applied[1]["subtotal_after"], 25.0)

    def test_amount_then_percent_order_matters(self):
        # $20 off then 10% off $100 -> 80 -> 72.
        applied, final = _coerce_coupons(
            [{"kind": "amount", "value": 20}, {"kind": "percent", "value": 10}],
            10000)
        self.assertEqual(final, 7200)

    def test_amount_capped_at_running_subtotal(self):
        # A flat coupon larger than what's left can't push below zero.
        applied, final = _coerce_coupons(
            [{"kind": "amount", "value": 80}, {"kind": "amount", "value": 50}],
            10000)
        self.assertEqual(final, 0)
        self.assertEqual(applied[1]["discount"], 20.0)

    def test_empty_list_raises(self):
        with self.assertRaises(ValueError):
            _coerce_coupons([], 10000)

    def test_non_list_raises(self):
        with self.assertRaises(ValueError):
            _coerce_coupons("20%", 10000)

    def test_non_dict_entry_raises(self):
        with self.assertRaises(ValueError):
            _coerce_coupons([10], 10000)

    def test_bad_kind_raises(self):
        with self.assertRaises(ValueError):
            _coerce_coupons([{"kind": "bogus", "value": 10}], 10000)

    def test_percent_over_100_raises(self):
        with self.assertRaises(ValueError):
            _coerce_coupons([{"kind": "percent", "value": 150}], 10000)

    def test_negative_value_raises(self):
        with self.assertRaises(ValueError):
            _coerce_coupons([{"kind": "amount", "value": -5}], 10000)


class ApplyCouponsTests(unittest.TestCase):
    def test_stack_reduces_tip_and_tax(self):
        # $100, [10% off, $5 off] -> 90 -> 85 subtotal; 20% tip on 85 = 17;
        # total 102 (no tax).
        r = apply_coupons(100, 20,
                          [{"kind": "percent", "value": 10},
                           {"kind": "amount", "value": 5}])
        self.assertEqual(r["original_subtotal"], 100.0)
        self.assertEqual(r["total_discount"], 15.0)
        self.assertEqual(r["subtotal"], 85.0)
        self.assertEqual(r["tip"], 17.0)
        self.assertEqual(r["total"], 102.0)
        self.assertEqual(len(r["coupons_applied"]), 2)

    def test_with_tax_and_tip(self):
        # $100, 10% off -> 90; 10% tax = 9; 20% tip on 90 = 18; total 117.
        r = apply_coupons(100, 20, [{"kind": "percent", "value": 10}],
                          tax_percent=10)
        self.assertEqual(r["subtotal"], 90.0)
        self.assertEqual(r["tax"], 9.0)
        self.assertEqual(r["tip"], 18.0)
        self.assertEqual(r["total"], 117.0)

    def test_single_coupon_matches_calculate_with_discount(self):
        a = apply_coupons(100, 18, [{"kind": "percent", "value": 15}],
                          people=3, tax_percent=13)
        d = calculate_with_discount(100, 18, 15, "percent", people=3,
                                    tax_percent=13)
        self.assertEqual(a["subtotal"], d["subtotal"])
        self.assertEqual(a["total"], d["total"])
        self.assertEqual(a["tip"], d["tip"])

    def test_shares_sum_back_to_total(self):
        r = apply_coupons(123.45, 18,
                          [{"kind": "percent", "value": 10},
                           {"kind": "amount", "value": 7.5}],
                          people=3, tax_percent=13)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])

    def test_coupons_can_zero_the_bill(self):
        r = apply_coupons(20, 20, [{"kind": "amount", "value": 100}])
        self.assertEqual(r["subtotal"], 0.0)
        self.assertEqual(r["total_discount"], 20.0)
        self.assertEqual(r["total"], 0.0)

    def test_empty_coupons_raises(self):
        with self.assertRaises(ValueError):
            apply_coupons(100, 20, [])

    def test_bad_bill_raises(self):
        with self.assertRaises(ValueError):
            apply_coupons(-5, 20, [{"kind": "percent", "value": 10}])


class _ServerTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base + path, data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _get(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as resp:
                return resp.status, resp.read(), resp.headers.get("Content-Type")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Content-Type")


class HttpGetTests(_ServerTestBase):
    def test_index_served(self):
        status, body, ctype = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"Tip Calculator", body)

    def test_index_html_path(self):
        status, body, _ = self._get("/index.html")
        self.assertEqual(status, 200)
        self.assertIn(b"Tip Calculator", body)

    def test_health(self):
        status, body, _ = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body.decode("utf-8")), {"status": "ok"})

    def test_unknown_get_is_404(self):
        status, _, _ = self._get("/nope")
        self.assertEqual(status, 404)


class HttpTipTests(_ServerTestBase):
    def test_basic_calc(self):
        status, data = self._post("/api/tip", {"bill": 100, "tip_percent": 20})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip"], 20.0)
        self.assertEqual(data["total"], 120.0)

    def test_split_calc(self):
        status, data = self._post(
            "/api/tip", {"bill": 100, "tip_percent": 0, "people": 3})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), 100.0)

    def test_round_total(self):
        status, data = self._post(
            "/api/tip",
            {"bill": 23.45, "tip_percent": 18, "round_total": True})
        self.assertEqual(status, 200)
        self.assertTrue(data["rounded"])
        self.assertEqual(data["total"], 28.0)

    def test_validation_error_is_400(self):
        status, data = self._post("/api/tip", {"bill": -1, "tip_percent": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_fields_is_400(self):
        status, data = self._post("/api/tip", {"bill": 100})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_invalid_json_is_400(self):
        status, data = self._post("/api/tip", None, raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_non_object_json_is_400(self):
        status, data = self._post("/api/tip", None, raw=b"[1, 2, 3]")
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpPresetsTests(_ServerTestBase):
    def test_default_presets(self):
        status, data = self._post("/api/presets", {"bill": 100})
        self.assertEqual(status, 200)
        self.assertEqual(
            len(data["suggestions"]), len(DEFAULT_PRESET_PERCENTS))

    def test_custom_percents(self):
        status, data = self._post(
            "/api/presets", {"bill": 100, "percents": [10, 25]})
        self.assertEqual(status, 200)
        self.assertEqual(
            [s["tip_percent"] for s in data["suggestions"]], [10.0, 25.0])

    def test_presets_with_people(self):
        status, data = self._post(
            "/api/presets", {"bill": 90, "people": 3, "percents": [0]})
        self.assertEqual(status, 200)
        self.assertEqual(data["suggestions"][0]["per_person"], 30.0)

    def test_invalid_percents_is_400(self):
        status, data = self._post(
            "/api/presets", {"bill": 100, "percents": [200]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_invalid_bill_is_400(self):
        status, data = self._post("/api/presets", {"bill": -5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_unknown_post_is_404(self):
        status, data = self._post("/api/unknown", {})
        self.assertEqual(status, 404)


class HttpBillTests(_ServerTestBase):
    def test_bill_with_tax(self):
        status, data = self._post(
            "/api/bill", {"bill": 100, "tip_percent": 20, "tax_percent": 10})
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 100.0)
        self.assertEqual(data["tax"], 10.0)
        self.assertEqual(data["total"], 130.0)

    def test_bill_posttax_tip(self):
        status, data = self._post(
            "/api/bill",
            {"bill": 100, "tip_percent": 20, "tax_percent": 10,
             "tip_on": "posttax"})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip"], 22.0)

    def test_bill_split_sums_back(self):
        status, data = self._post(
            "/api/bill",
            {"bill": 100, "tip_percent": 18, "people": 3, "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_bad_tax_is_400(self):
        status, data = self._post(
            "/api/bill", {"bill": 100, "tip_percent": 20, "tax_percent": 150})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_bad_tip_on_is_400(self):
        status, data = self._post(
            "/api/bill", {"bill": 100, "tip_percent": 20, "tip_on": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpSplitTests(_ServerTestBase):
    def test_weighted_split(self):
        status, data = self._post(
            "/api/split", {"bill": 100, "tip_percent": 0, "weights": [2, 1, 1]})
        self.assertEqual(status, 200)
        self.assertEqual(data["people"], 3)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])
        self.assertGreater(data["shares"][0], data["shares"][1])

    def test_split_with_tax(self):
        status, data = self._post(
            "/api/split",
            {"bill": 120, "tip_percent": 18, "weights": [3, 2, 1],
             "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["tip_shares"]), 2), data["tip"])

    def test_empty_weights_is_400(self):
        status, data = self._post(
            "/api/split", {"bill": 100, "tip_percent": 20, "weights": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_weights_is_400(self):
        status, data = self._post(
            "/api/split", {"bill": 100, "tip_percent": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpRecommendTests(_ServerTestBase):
    def test_recommend_good(self):
        status, data = self._post(
            "/api/recommend", {"bill": 100, "rating": "good"})
        self.assertEqual(status, 200)
        self.assertEqual(data["recommended_percent"], 18)
        self.assertEqual(data["tip"], 18.0)
        self.assertEqual(data["total"], 118.0)

    def test_recommend_with_tax_and_people(self):
        status, data = self._post(
            "/api/recommend",
            {"bill": 100, "rating": "great", "people": 2, "tax_percent": 10})
        self.assertEqual(status, 200)
        self.assertEqual(data["recommended_percent"], 20)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_unknown_rating_is_400(self):
        status, data = self._post(
            "/api/recommend", {"bill": 100, "rating": "terrible"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_rating_is_400(self):
        status, data = self._post("/api/recommend", {"bill": 100})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpItemsTests(_ServerTestBase):
    def test_split_by_items(self):
        status, data = self._post(
            "/api/items", {"items": [40, 60], "tip_percent": 20})
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 100.0)
        self.assertEqual(data["breakdown"][0]["tip"], 8.0)
        self.assertEqual(data["breakdown"][1]["tip"], 12.0)

    def test_items_with_tax_sum_back(self):
        status, data = self._post(
            "/api/items",
            {"items": [[12.5, 3.25], [9.99]], "tip_percent": 18,
             "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_empty_items_is_400(self):
        status, data = self._post(
            "/api/items", {"items": [], "tip_percent": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_items_is_400(self):
        status, data = self._post("/api/items", {"tip_percent": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpTargetTests(_ServerTestBase):
    def test_tip_for_target_total(self):
        status, data = self._post(
            "/api/target", {"bill": 100, "target_total": 120})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip"], 20.0)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(data["tip_percent"], 20.0)

    def test_target_with_tax_and_split(self):
        status, data = self._post(
            "/api/target",
            {"bill": 100, "target_total": 130, "tax_percent": 10, "people": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["tax"], 10.0)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_target_below_base_is_400(self):
        status, data = self._post(
            "/api/target",
            {"bill": 100, "target_total": 90, "tax_percent": 10})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_target_is_400(self):
        status, data = self._post("/api/target", {"bill": 100})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpDiscountTests(_ServerTestBase):
    def test_percent_discount(self):
        status, data = self._post(
            "/api/discount",
            {"bill": 100, "tip_percent": 20, "discount": 10,
             "discount_kind": "percent"})
        self.assertEqual(status, 200)
        self.assertEqual(data["original_subtotal"], 100.0)
        self.assertEqual(data["discount_amount"], 10.0)
        self.assertEqual(data["subtotal"], 90.0)
        self.assertEqual(data["tip"], 18.0)
        self.assertEqual(data["total"], 108.0)

    def test_amount_discount_defaults_when_kind_omitted(self):
        # discount_kind defaults to "percent".
        status, data = self._post(
            "/api/discount", {"bill": 100, "tip_percent": 0, "discount": 25})
        self.assertEqual(status, 200)
        self.assertEqual(data["discount_kind"], "percent")
        self.assertEqual(data["subtotal"], 75.0)

    def test_flat_amount_discount(self):
        status, data = self._post(
            "/api/discount",
            {"bill": 100, "tip_percent": 0, "discount": 25,
             "discount_kind": "amount"})
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 75.0)
        self.assertEqual(data["total"], 75.0)

    def test_discount_split_sums_back(self):
        status, data = self._post(
            "/api/discount",
            {"bill": 123.45, "tip_percent": 18, "discount": 15,
             "people": 3, "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_bad_discount_kind_is_400(self):
        status, data = self._post(
            "/api/discount",
            {"bill": 100, "tip_percent": 20, "discount": 10,
             "discount_kind": "half"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_negative_discount_is_400(self):
        status, data = self._post(
            "/api/discount",
            {"bill": 100, "tip_percent": 20, "discount": -5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class ServiceChargeBillTests(unittest.TestCase):
    def test_mandatory_service_plus_optional_tip(self):
        # $100, 18% auto-gratuity, plus a 5% extra tip, no tax.
        r = service_charge_bill(100, 18, tip_percent=5)
        self.assertEqual(r["subtotal"], 100.0)
        self.assertEqual(r["service_charge"], 18.0)
        self.assertEqual(r["tip"], 5.0)
        self.assertEqual(r["total"], 123.0)
        self.assertEqual(r["service_percent"], 18.0)

    def test_service_charge_only_no_extra_tip(self):
        # Default tip_percent is 0: just the mandatory charge.
        r = service_charge_bill(200, 20)
        self.assertEqual(r["service_charge"], 40.0)
        self.assertEqual(r["tip"], 0.0)
        self.assertEqual(r["total"], 240.0)

    def test_service_with_tax(self):
        # $100 + 10% tax (10) + 18% service (18) + 0 tip = 128.
        r = service_charge_bill(100, 18, tax_percent=10)
        self.assertEqual(r["tax"], 10.0)
        self.assertEqual(r["service_charge"], 18.0)
        self.assertEqual(r["total"], 128.0)

    def test_posttax_base_for_service_and_tip(self):
        # 18% service on (100 + 10 tax) = 110 -> 19.80; 0 tip; total 129.80.
        r = service_charge_bill(100, 18, tax_percent=10, tip_on="posttax")
        self.assertEqual(r["service_charge"], 19.8)
        self.assertEqual(r["total"], 129.8)

    def test_split_sums_back_to_total(self):
        r = service_charge_bill(123.45, 18, tip_percent=7, people=3,
                                tax_percent=13)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])
        self.assertEqual(r["people"], 3)

    def test_per_person_breakdowns_present(self):
        r = service_charge_bill(100, 20, tip_percent=10, people=4)
        self.assertEqual(r["per_person_service"], 5.0)
        self.assertEqual(r["per_person_tip"], 2.5)

    def test_round_total_absorbs_into_tip(self):
        r = service_charge_bill(23.45, 18, tip_percent=3, tax_percent=5,
                                round_total=True)
        self.assertTrue(r["rounded"])
        self.assertEqual(r["total"], int(r["total"]))
        self.assertEqual(
            round(r["subtotal"] + r["tax"] + r["service_charge"] + r["tip"], 2),
            r["total"])

    def test_invalid_service_percent_raises(self):
        with self.assertRaises(ValueError):
            service_charge_bill(100, 150)

    def test_negative_service_percent_raises(self):
        with self.assertRaises(ValueError):
            service_charge_bill(100, -1)

    def test_non_numeric_service_raises(self):
        with self.assertRaises(ValueError):
            service_charge_bill(100, "abc")

    def test_invalid_tip_on_raises(self):
        with self.assertRaises(ValueError):
            service_charge_bill(100, 18, tip_on="midtax")

    def test_invalid_bill_raises(self):
        with self.assertRaises(ValueError):
            service_charge_bill(-1, 18)


class SplitRoundUpPerPersonTests(unittest.TestCase):
    def test_each_share_is_whole_dollar(self):
        # $100, 18% tip -> $118 total over 3 -> fair 39.34/39.33/39.33,
        # each rounded up to 40 -> shares all 40.
        r = split_round_up_per_person(100, 18, 3)
        self.assertEqual(r["shares"], [40.0, 40.0, 40.0])
        for share in r["shares"]:
            self.assertEqual(share, int(share))

    def test_surplus_added_to_tip(self):
        r = split_round_up_per_person(100, 18, 3)
        # New total 120, original 118 -> surplus 2 folded into the tip.
        self.assertEqual(r["original_total"], 118.0)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["surplus"], 2.0)
        self.assertEqual(r["tip"], 20.0)

    def test_total_equals_sum_of_shares(self):
        r = split_round_up_per_person(123.45, 18, 4, tax_percent=13)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])

    def test_components_still_sum_to_total(self):
        r = split_round_up_per_person(87.65, 20, 3, tax_percent=8)
        self.assertEqual(
            round(r["subtotal"] + r["tax"] + r["tip"], 2), r["total"])

    def test_already_whole_is_noop(self):
        # $100, 0% tip, 0 tax over 4 -> each pays exactly 25, nothing to bump.
        r = split_round_up_per_person(100, 0, 4)
        self.assertEqual(r["shares"], [25.0, 25.0, 25.0, 25.0])
        self.assertEqual(r["surplus"], 0.0)
        self.assertEqual(r["total"], 100.0)

    def test_single_person(self):
        r = split_round_up_per_person(23.45, 18, 1)
        # 23.45 + 18% = 27.671 -> total 27.67 -> rounds to 28.
        self.assertEqual(r["total"], 28.0)
        self.assertEqual(r["shares"], [28.0])

    def test_effective_tip_percent_reported(self):
        r = split_round_up_per_person(100, 18, 3)
        # tip 20 on a 100 subtotal -> effective 20%.
        self.assertEqual(r["tip_percent"], 20.0)

    def test_invalid_bill_raises(self):
        with self.assertRaises(ValueError):
            split_round_up_per_person(-1, 18, 3)

    def test_zero_people_raises(self):
        with self.assertRaises(ValueError):
            split_round_up_per_person(100, 18, 0)


class HttpServiceTests(_ServerTestBase):
    def test_service_charge(self):
        status, data = self._post(
            "/api/service",
            {"bill": 100, "service_percent": 18, "tip_percent": 5})
        self.assertEqual(status, 200)
        self.assertEqual(data["service_charge"], 18.0)
        self.assertEqual(data["tip"], 5.0)
        self.assertEqual(data["total"], 123.0)

    def test_service_with_tax_and_split(self):
        status, data = self._post(
            "/api/service",
            {"bill": 120, "service_percent": 18, "tip_percent": 0,
             "people": 3, "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_service_defaults_tip_to_zero(self):
        status, data = self._post(
            "/api/service", {"bill": 200, "service_percent": 20})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip"], 0.0)
        self.assertEqual(data["total"], 240.0)

    def test_bad_service_percent_is_400(self):
        status, data = self._post(
            "/api/service", {"bill": 100, "service_percent": 150})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_service_percent_is_400(self):
        status, data = self._post("/api/service", {"bill": 100})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpRoundSplitTests(_ServerTestBase):
    def test_round_split_whole_dollars(self):
        status, data = self._post(
            "/api/roundsplit", {"bill": 100, "tip_percent": 18, "people": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["shares"], [40.0, 40.0, 40.0])
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(data["surplus"], 2.0)

    def test_round_split_sums_back(self):
        status, data = self._post(
            "/api/roundsplit",
            {"bill": 123.45, "tip_percent": 18, "people": 4, "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_round_split_invalid_bill_is_400(self):
        status, data = self._post(
            "/api/roundsplit", {"bill": -1, "tip_percent": 18, "people": 3})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_round_split_missing_tip_is_400(self):
        status, data = self._post("/api/roundsplit", {"bill": 100})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class DistributePoolTests(unittest.TestCase):
    def test_proportional_distribution(self):
        # $300 pool shared 2:1 -> $200 / $100.
        r = distribute_pool(300, [2, 1])
        self.assertEqual(r["pool"], 300.0)
        self.assertEqual(r["people"], 2)
        self.assertEqual(r["shares"], [200.0, 100.0])
        self.assertEqual(r["weights"], [2.0, 1.0])

    def test_shares_sum_back_to_pool(self):
        r = distribute_pool(123.45, [3, 2, 1, 1])
        self.assertEqual(round(sum(r["shares"]), 2), r["pool"])
        self.assertEqual(len(r["shares"]), 4)

    def test_equal_weights_split_evenly(self):
        # $100 over three equal workers -> 33.34 / 33.33 / 33.33, summing back.
        r = distribute_pool(100, [1, 1, 1])
        self.assertEqual(round(sum(r["shares"]), 2), 100.0)
        # Compare in rounded cents: the shares differ by at most one cent. (A raw
        # float subtraction yields 0.0100000000000051 here, which is the intent
        # but trips an exact 0.01 bound.)
        self.assertLessEqual(round(max(r["shares"]) - min(r["shares"]), 2), 0.01)

    def test_per_person_is_largest_cut(self):
        r = distribute_pool(300, [2, 1])
        self.assertEqual(r["per_person"], 200.0)

    def test_zero_weight_worker_gets_nothing(self):
        r = distribute_pool(200, [0, 1, 1])
        self.assertEqual(r["shares"][0], 0.0)
        self.assertEqual(round(sum(r["shares"]), 2), 200.0)

    def test_string_inputs_accepted(self):
        r = distribute_pool("90", ["2", "1"])
        self.assertEqual(r["shares"], [60.0, 30.0])

    def test_missing_pool_raises(self):
        with self.assertRaises(ValueError):
            distribute_pool(None, [1, 1])

    def test_negative_pool_raises(self):
        with self.assertRaises(ValueError):
            distribute_pool(-10, [1, 1])

    def test_non_numeric_pool_raises(self):
        with self.assertRaises(ValueError):
            distribute_pool("abc", [1, 1])

    def test_invalid_weights_raise(self):
        with self.assertRaises(ValueError):
            distribute_pool(100, [])

    def test_all_zero_weights_raise(self):
        with self.assertRaises(ValueError):
            distribute_pool(100, [0, 0])


class SplitToDenominationTests(unittest.TestCase):
    def test_quarter_denomination(self):
        # $100, 18% tip -> $118 over 3 -> fair 39.34/39.33/39.33, each rounded
        # up to the next quarter -> 39.50 each.
        r = split_to_denomination(100, 18, 3, denomination=0.25)
        self.assertEqual(r["shares"], [39.5, 39.5, 39.5])
        self.assertEqual(r["denomination"], 0.25)
        for share in r["shares"]:
            # every share is a whole number of quarters
            self.assertEqual(round(share / 0.25) * 0.25, share)

    def test_whole_dollar_matches_round_up_per_person(self):
        # denomination=1 must reproduce split_round_up_per_person exactly.
        a = split_to_denomination(123.45, 18, 4, denomination=1, tax_percent=13)
        b = split_round_up_per_person(123.45, 18, 4, tax_percent=13)
        self.assertEqual(a["shares"], b["shares"])
        self.assertEqual(a["total"], b["total"])
        self.assertEqual(a["tip"], b["tip"])
        self.assertEqual(a["surplus"], b["surplus"])

    def test_total_equals_sum_of_shares(self):
        r = split_to_denomination(87.65, 20, 3, denomination=0.05, tax_percent=8)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])

    def test_surplus_folded_into_tip(self):
        r = split_to_denomination(100, 18, 3, denomination=0.25)
        # New total = 3 * 39.50 = 118.50; original 118 -> surplus 0.50 into tip.
        self.assertEqual(r["original_total"], 118.0)
        self.assertEqual(r["total"], 118.5)
        self.assertEqual(r["surplus"], 0.5)
        self.assertEqual(r["tip"], 18.5)

    def test_components_still_sum_to_total(self):
        r = split_to_denomination(87.65, 20, 3, denomination=0.25, tax_percent=8)
        self.assertEqual(
            round(r["subtotal"] + r["tax"] + r["tip"], 2), r["total"])

    def test_five_dollar_denomination(self):
        # Each share rounded up to the next $5.
        r = split_to_denomination(100, 0, 3, denomination=5)
        for share in r["shares"]:
            self.assertEqual(share % 5, 0.0)
        self.assertGreaterEqual(r["total"], 100.0)

    def test_already_on_denomination_is_noop(self):
        # $100, 0% tip over 4 -> 25 each, already a multiple of 0.25.
        r = split_to_denomination(100, 0, 4, denomination=0.25)
        self.assertEqual(r["shares"], [25.0, 25.0, 25.0, 25.0])
        self.assertEqual(r["surplus"], 0.0)
        self.assertEqual(r["total"], 100.0)

    def test_effective_tip_percent_reported(self):
        r = split_to_denomination(100, 18, 3, denomination=0.25)
        # tip 18.50 on a 100 subtotal -> effective 18.5%.
        self.assertEqual(r["tip_percent"], 18.5)

    def test_zero_denomination_raises(self):
        with self.assertRaises(ValueError):
            split_to_denomination(100, 18, 3, denomination=0)

    def test_negative_denomination_raises(self):
        with self.assertRaises(ValueError):
            split_to_denomination(100, 18, 3, denomination=-1)

    def test_non_numeric_denomination_raises(self):
        with self.assertRaises(ValueError):
            split_to_denomination(100, 18, 3, denomination="abc")

    def test_invalid_bill_raises(self):
        with self.assertRaises(ValueError):
            split_to_denomination(-1, 18, 3, denomination=0.25)


class HttpPoolTests(_ServerTestBase):
    def test_pool_distribution(self):
        status, data = self._post(
            "/api/pool", {"pool": 300, "weights": [2, 1]})
        self.assertEqual(status, 200)
        self.assertEqual(data["shares"], [200.0, 100.0])
        self.assertEqual(data["people"], 2)

    def test_pool_sums_back(self):
        status, data = self._post(
            "/api/pool", {"pool": 123.45, "weights": [3, 2, 1, 1]})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["pool"])

    def test_missing_weights_is_400(self):
        status, data = self._post("/api/pool", {"pool": 100})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_pool_is_400(self):
        status, data = self._post("/api/pool", {"weights": [1, 1]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_negative_pool_is_400(self):
        status, data = self._post(
            "/api/pool", {"pool": -5, "weights": [1, 1]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpCashSplitTests(_ServerTestBase):
    def test_quarter_split(self):
        status, data = self._post(
            "/api/cashsplit",
            {"bill": 100, "tip_percent": 18, "people": 3,
             "denomination": 0.25})
        self.assertEqual(status, 200)
        self.assertEqual(data["shares"], [39.5, 39.5, 39.5])
        self.assertEqual(data["total"], 118.5)
        self.assertEqual(data["surplus"], 0.5)

    def test_defaults_to_whole_dollar(self):
        # denomination defaults to 1.0 -> matches the roundsplit behaviour.
        status, data = self._post(
            "/api/cashsplit",
            {"bill": 100, "tip_percent": 18, "people": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["shares"], [40.0, 40.0, 40.0])
        self.assertEqual(data["denomination"], 1.0)

    def test_cashsplit_sums_back(self):
        status, data = self._post(
            "/api/cashsplit",
            {"bill": 123.45, "tip_percent": 18, "people": 4,
             "denomination": 0.05, "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_zero_denomination_is_400(self):
        status, data = self._post(
            "/api/cashsplit",
            {"bill": 100, "tip_percent": 18, "people": 3, "denomination": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_invalid_bill_is_400(self):
        status, data = self._post(
            "/api/cashsplit",
            {"bill": -1, "tip_percent": 18, "people": 3})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class TipFromPerPersonTests(unittest.TestCase):
    def test_derives_tip_from_per_person_target(self):
        # Bill 100 over 4 people; each wants to pay exactly 30 -> total 120,
        # tip 20, effective 20%.
        r = tip_from_per_person(100, 30, 4)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["tip_percent"], 20.0)
        self.assertEqual(r["per_person_target"], 30.0)

    def test_single_person_matches_tip_for_total(self):
        a = tip_from_per_person(100, 120, 1)
        b = tip_for_total(100, 120, 1)
        self.assertEqual(a["tip"], b["tip"])
        self.assertEqual(a["total"], b["total"])

    def test_target_accounts_for_tax(self):
        # Bill 100 + 10% tax = 110 base over 2; each pays 65 -> total 130,
        # tip 20.
        r = tip_from_per_person(100, 65, 2, tax_percent=10)
        self.assertEqual(r["tax"], 10.0)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["total"], 130.0)

    def test_shares_sum_back_to_total(self):
        r = tip_from_per_person(123.45, 50, 3, tax_percent=13)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])

    def test_per_person_matches_target(self):
        r = tip_from_per_person(80, 25, 4)
        self.assertEqual(r["per_person"], 25.0)

    def test_target_below_share_raises(self):
        # Each person's bill share is 50; asking to pay 40 is impossible.
        with self.assertRaises(ValueError):
            tip_from_per_person(100, 40, 2)

    def test_missing_target_raises(self):
        with self.assertRaises(ValueError):
            tip_from_per_person(100, None, 2)

    def test_negative_target_raises(self):
        with self.assertRaises(ValueError):
            tip_from_per_person(100, -5, 2)

    def test_non_numeric_target_raises(self):
        with self.assertRaises(ValueError):
            tip_from_per_person(100, "abc", 2)

    def test_invalid_bill_raises(self):
        with self.assertRaises(ValueError):
            tip_from_per_person(-1, 30, 2)


class RoundTotalToNearestTests(unittest.TestCase):
    def test_nearest_rounds_down_when_closer(self):
        # 23.45 + 18% = 27.671 -> total 27.67; nearest dollar is 28.
        r = round_total_to_nearest(23.45, 18)
        self.assertEqual(r["total"], 28.0)
        self.assertEqual(r["mode"], "nearest")
        self.assertTrue(r["rounded"])

    def test_nearest_snaps_to_lower_dollar(self):
        # 100 + 20% = 120.40 -> nearest dollar is 120 (rounds DOWN), tip 20.
        r = round_total_to_nearest(102, 18)
        # 102 + 18% = 120.36 -> nearest is 120, adjustment -0.36 off the tip.
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["original_total"], 120.36)
        self.assertEqual(r["adjustment"], -0.36)
        self.assertEqual(round(r["subtotal"] + r["tax"] + r["tip"], 2),
                         r["total"])

    def test_up_mode_always_rounds_up(self):
        r = round_total_to_nearest(102, 18, mode="up")
        self.assertEqual(r["total"], 121.0)
        self.assertGreater(r["adjustment"], 0)

    def test_down_mode_always_rounds_down(self):
        r = round_total_to_nearest(102, 18, mode="down")
        self.assertEqual(r["total"], 120.0)
        self.assertLess(r["adjustment"], 0)

    def test_custom_round_to_step(self):
        # Round to the nearest $5. 102 + 18% = 120.36 -> nearest $5 is 120.
        r = round_total_to_nearest(102, 18, round_to=5)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["round_to"], 5.0)

    def test_components_sum_to_total(self):
        r = round_total_to_nearest(87.65, 20, people=3, tax_percent=8,
                                   round_to=0.25)
        self.assertEqual(round(r["subtotal"] + r["tax"] + r["tip"], 2),
                         r["total"])

    def test_shares_sum_back_to_total(self):
        r = round_total_to_nearest(123.45, 18, people=4, tax_percent=13,
                                   mode="up")
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])

    def test_effective_tip_percent_reported(self):
        # 100 + 18% = 118; nearest dollar leaves it at 118, tip 18 -> 18%.
        r = round_total_to_nearest(100, 18)
        self.assertEqual(r["total"], 118.0)
        self.assertEqual(r["tip_percent"], 18.0)

    def test_down_below_bill_plus_tax_raises(self):
        # 100 + 1% tip = 101; rounding down to the nearest $30 lands on $90,
        # which is below the bill, so the tip would go negative.
        with self.assertRaises(ValueError):
            round_total_to_nearest(100, 1, round_to=30, mode="down")

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            round_total_to_nearest(100, 18, mode="sideways")

    def test_zero_round_to_raises(self):
        with self.assertRaises(ValueError):
            round_total_to_nearest(100, 18, round_to=0)

    def test_negative_round_to_raises(self):
        with self.assertRaises(ValueError):
            round_total_to_nearest(100, 18, round_to=-1)

    def test_non_numeric_round_to_raises(self):
        with self.assertRaises(ValueError):
            round_total_to_nearest(100, 18, round_to="abc")

    def test_invalid_bill_raises(self):
        with self.assertRaises(ValueError):
            round_total_to_nearest(-1, 18)

    def test_modes_constant_exposed(self):
        self.assertEqual(ROUNDING_MODES, ("up", "down", "nearest"))


class FormatReceiptTests(unittest.TestCase):
    def test_receipt_contains_core_lines(self):
        r = format_receipt(100, 20, tax_percent=10)
        text = r["receipt"]
        self.assertIn("Subtotal", text)
        self.assertIn("$100.00", text)
        self.assertIn("Tax (10%)", text)
        self.assertIn("Tip (20%)", text)
        self.assertIn("Total", text)
        self.assertIn("$130.00", text)

    def test_lines_match_receipt(self):
        r = format_receipt(50, 18)
        self.assertEqual("\n".join(r["lines"]), r["receipt"])

    def test_tax_line_omitted_when_zero(self):
        r = format_receipt(50, 18)
        self.assertNotIn("Tax", r["receipt"])

    def test_split_shows_one_line_per_person(self):
        r = format_receipt(100, 0, people=3)
        self.assertIn("Split 3 ways:", r["receipt"])
        self.assertIn("Person 1", r["receipt"])
        self.assertIn("Person 3", r["receipt"])

    def test_single_person_has_no_split_section(self):
        r = format_receipt(100, 20)
        self.assertNotIn("Split", r["receipt"])
        self.assertNotIn("Person", r["receipt"])

    def test_custom_title_used(self):
        r = format_receipt(100, 20, title="Dinner")
        self.assertEqual(r["title"], "Dinner")
        self.assertTrue(r["receipt"].startswith("Dinner"))

    def test_carries_breakdown_fields(self):
        r = format_receipt(100, 20, tax_percent=10)
        self.assertEqual(r["subtotal"], 100.0)
        self.assertEqual(r["tax"], 10.0)
        self.assertEqual(r["total"], 130.0)

    def test_percent_formatted_without_trailing_zero(self):
        r = format_receipt(100, 20)
        self.assertIn("Tip (20%)", r["receipt"])
        self.assertNotIn("Tip (20.0%)", r["receipt"])

    def test_invalid_bill_raises(self):
        with self.assertRaises(ValueError):
            format_receipt(-1, 20)


class HttpPerPersonTests(_ServerTestBase):
    def test_per_person_goal(self):
        status, data = self._post(
            "/api/perperson",
            {"bill": 100, "per_person_target": 30, "people": 4})
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(data["tip"], 20.0)
        self.assertEqual(data["per_person_target"], 30.0)

    def test_per_person_with_tax_sums_back(self):
        status, data = self._post(
            "/api/perperson",
            {"bill": 123.45, "per_person_target": 50, "people": 3,
             "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_target_too_low_is_400(self):
        status, data = self._post(
            "/api/perperson",
            {"bill": 100, "per_person_target": 40, "people": 2})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_target_is_400(self):
        status, data = self._post("/api/perperson", {"bill": 100, "people": 2})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpRoundTests(_ServerTestBase):
    def test_round_nearest(self):
        status, data = self._post(
            "/api/round", {"bill": 102, "tip_percent": 18})
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(data["mode"], "nearest")

    def test_round_up_mode(self):
        status, data = self._post(
            "/api/round", {"bill": 102, "tip_percent": 18, "mode": "up"})
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 121.0)

    def test_round_custom_step_sums_back(self):
        status, data = self._post(
            "/api/round",
            {"bill": 123.45, "tip_percent": 18, "people": 4,
             "tax_percent": 13, "round_to": 0.25})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_bad_mode_is_400(self):
        status, data = self._post(
            "/api/round", {"bill": 100, "tip_percent": 18, "mode": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_tip_is_400(self):
        status, data = self._post("/api/round", {"bill": 100})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpReceiptTests(_ServerTestBase):
    def test_receipt_rendered(self):
        status, data = self._post(
            "/api/receipt",
            {"bill": 100, "tip_percent": 20, "tax_percent": 10})
        self.assertEqual(status, 200)
        self.assertIn("Total", data["receipt"])
        self.assertIn("$130.00", data["receipt"])
        self.assertEqual(data["total"], 130.0)

    def test_receipt_split_lines(self):
        status, data = self._post(
            "/api/receipt", {"bill": 100, "tip_percent": 0, "people": 3})
        self.assertEqual(status, 200)
        self.assertIn("Split 3 ways:", data["receipt"])

    def test_receipt_custom_title(self):
        status, data = self._post(
            "/api/receipt",
            {"bill": 50, "tip_percent": 18, "title": "Lunch"})
        self.assertEqual(status, 200)
        self.assertTrue(data["receipt"].startswith("Lunch"))

    def test_receipt_invalid_bill_is_400(self):
        status, data = self._post(
            "/api/receipt", {"bill": -1, "tip_percent": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_receipt_missing_tip_is_400(self):
        status, data = self._post("/api/receipt", {"bill": 100})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class TipFromAmountTests(unittest.TestCase):
    def test_flat_tip_amount_and_effective_percent(self):
        # Bill 100, leave a flat $20 tip -> total 120, effective 20%.
        r = tip_from_amount(100, 20)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["tip_percent"], 20.0)

    def test_zero_tip(self):
        r = tip_from_amount(50, 0)
        self.assertEqual(r["tip"], 0.0)
        self.assertEqual(r["total"], 50.0)
        self.assertEqual(r["tip_percent"], 0.0)

    def test_tip_amount_with_tax(self):
        # Bill 100 + 10% tax = 110, plus a flat $15 tip -> total 125.
        r = tip_from_amount(100, 15, tax_percent=10)
        self.assertEqual(r["tax"], 10.0)
        self.assertEqual(r["tip"], 15.0)
        self.assertEqual(r["total"], 125.0)
        self.assertEqual(r["tip_percent"], 15.0)

    def test_split_sums_back(self):
        r = tip_from_amount(123.45, 17, people=3, tax_percent=13)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])

    def test_per_person_tip(self):
        r = tip_from_amount(100, 20, people=4)
        self.assertEqual(r["per_person_tip"], 5.0)

    def test_zero_bill_reports_zero_percent(self):
        r = tip_from_amount(0, 5)
        self.assertEqual(r["tip"], 5.0)
        self.assertEqual(r["tip_percent"], 0.0)

    def test_string_inputs_accepted(self):
        r = tip_from_amount("100", "12.50", "2")
        self.assertEqual(r["tip"], 12.5)
        self.assertEqual(r["people"], 2)

    def test_missing_tip_amount_raises(self):
        with self.assertRaises(ValueError):
            tip_from_amount(100, None)

    def test_negative_tip_amount_raises(self):
        with self.assertRaises(ValueError):
            tip_from_amount(100, -5)

    def test_non_numeric_tip_amount_raises(self):
        with self.assertRaises(ValueError):
            tip_from_amount(100, "abc")

    def test_invalid_bill_raises(self):
        with self.assertRaises(ValueError):
            tip_from_amount(-1, 10)

    def test_invalid_tax_raises(self):
        with self.assertRaises(ValueError):
            tip_from_amount(100, 10, tax_percent=150)


class CompareScenariosTests(unittest.TestCase):
    def test_default_percents(self):
        out = compare_scenarios(100)
        self.assertEqual(
            [s["tip_percent"] for s in out["scenarios"]],
            list(DEFAULT_PRESET_PERCENTS))

    def test_none_falls_back_to_defaults(self):
        out = compare_scenarios(100, None)
        self.assertEqual(
            len(out["scenarios"]), len(DEFAULT_PRESET_PERCENTS))

    def test_full_breakdown_per_scenario(self):
        out = compare_scenarios(100, [20])
        s = out["scenarios"][0]
        self.assertEqual(s["tip"], 20.0)
        self.assertEqual(s["total"], 120.0)
        self.assertEqual(s["per_person"], 120.0)
        self.assertEqual(s["per_person_tip"], 20.0)

    def test_carries_subtotal_and_tax(self):
        out = compare_scenarios(100, [15, 20], tax_percent=10)
        self.assertEqual(out["subtotal"], 100.0)
        self.assertEqual(out["tax"], 10.0)

    def test_scenarios_honour_tax_in_total(self):
        # 100 + 10 tax + 20 tip = 130 for the 20% scenario.
        out = compare_scenarios(100, [20], tax_percent=10)
        self.assertEqual(out["scenarios"][0]["total"], 130.0)

    def test_posttax_base_changes_tip(self):
        # 20% on (100 + 10 tax) = 22.
        out = compare_scenarios(100, [20], tax_percent=10, tip_on="posttax")
        self.assertEqual(out["scenarios"][0]["tip"], 22.0)
        self.assertEqual(out["tip_on"], "posttax")

    def test_per_person_reflects_split(self):
        out = compare_scenarios(90, [0], people=3)
        self.assertEqual(out["people"], 3)
        self.assertEqual(out["scenarios"][0]["per_person"], 30.0)

    def test_custom_percents(self):
        out = compare_scenarios(50, [10, 30])
        self.assertEqual(
            [s["tip_percent"] for s in out["scenarios"]], [10.0, 30.0])

    def test_invalid_bill_raises(self):
        with self.assertRaises(ValueError):
            compare_scenarios(-1)

    def test_empty_percents_raise(self):
        with self.assertRaises(ValueError):
            compare_scenarios(100, [])

    def test_out_of_range_percents_raise(self):
        with self.assertRaises(ValueError):
            compare_scenarios(100, [150])

    def test_invalid_tax_raises(self):
        with self.assertRaises(ValueError):
            compare_scenarios(100, [20], tax_percent=-1)


class HttpTipAmountTests(_ServerTestBase):
    def test_flat_tip_amount(self):
        status, data = self._post(
            "/api/tipamount", {"bill": 100, "tip_amount": 20})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip"], 20.0)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(data["tip_percent"], 20.0)

    def test_tip_amount_with_tax_and_split(self):
        status, data = self._post(
            "/api/tipamount",
            {"bill": 123.45, "tip_amount": 17, "people": 3, "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_missing_tip_amount_is_400(self):
        status, data = self._post("/api/tipamount", {"bill": 100})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_negative_tip_amount_is_400(self):
        status, data = self._post(
            "/api/tipamount", {"bill": 100, "tip_amount": -5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_invalid_bill_is_400(self):
        status, data = self._post(
            "/api/tipamount", {"bill": -1, "tip_amount": 10})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpCompareTests(_ServerTestBase):
    def test_default_compare(self):
        status, data = self._post("/api/compare", {"bill": 100})
        self.assertEqual(status, 200)
        self.assertEqual(
            len(data["scenarios"]), len(DEFAULT_PRESET_PERCENTS))

    def test_compare_custom_percents_with_tax(self):
        status, data = self._post(
            "/api/compare",
            {"bill": 100, "percents": [15, 20], "tax_percent": 10})
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 100.0)
        self.assertEqual(data["tax"], 10.0)
        self.assertEqual(
            [s["tip_percent"] for s in data["scenarios"]], [15.0, 20.0])

    def test_compare_with_people(self):
        status, data = self._post(
            "/api/compare", {"bill": 90, "percents": [0], "people": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["scenarios"][0]["per_person"], 30.0)

    def test_invalid_percents_is_400(self):
        status, data = self._post(
            "/api/compare", {"bill": 100, "percents": [150]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_invalid_bill_is_400(self):
        status, data = self._post("/api/compare", {"bill": -5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class CoerceAmountsTests(unittest.TestCase):
    def test_valid_list(self):
        self.assertEqual(_coerce_amounts([10, 20.5, 0], "bills"), [10.0, 20.5, 0.0])

    def test_rejects_non_list(self):
        with self.assertRaises(ValueError):
            _coerce_amounts("10", "bills")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            _coerce_amounts([], "bills")

    def test_rejects_negative(self):
        with self.assertRaises(ValueError):
            _coerce_amounts([10, -1], "bills")

    def test_rejects_non_number(self):
        with self.assertRaises(ValueError):
            _coerce_amounts([10, "x"], "bills")

    def test_label_appears_in_error(self):
        with self.assertRaises(ValueError) as cm:
            _coerce_amounts([], "tip_percents")
        self.assertIn("tip_percents", str(cm.exception))


class CombineBillsTests(unittest.TestCase):
    def test_sums_bills(self):
        result = combine_bills([40, 35, 25], 20)
        self.assertEqual(result["subtotal"], 100.0)
        self.assertEqual(result["tip"], 20.0)
        self.assertEqual(result["total"], 120.0)
        self.assertEqual(result["bills"], [40.0, 35.0, 25.0])
        self.assertEqual(result["bill_count"], 3)

    def test_matches_single_bill(self):
        combined = combine_bills([60, 40], 18, people=2, tax_percent=8)
        single = calculate_bill(100, 18, 2, 8)
        self.assertEqual(combined["total"], single["total"])
        self.assertEqual(combined["tip"], single["tip"])
        self.assertEqual(combined["tax"], single["tax"])

    def test_split_sums_back(self):
        result = combine_bills([33.33, 33.33, 33.34], 15, people=3)
        self.assertAlmostEqual(sum(result["shares"]), result["total"], places=2)

    def test_single_bill_in_list(self):
        result = combine_bills([100], 20)
        self.assertEqual(result["bill_count"], 1)
        self.assertEqual(result["total"], 120.0)

    def test_empty_bills_is_error(self):
        with self.assertRaises(ValueError):
            combine_bills([], 20)

    def test_invalid_tip_is_error(self):
        with self.assertRaises(ValueError):
            combine_bills([10, 20], 150)


class ConvertCurrencyTests(unittest.TestCase):
    def test_converts_money_fields(self):
        result = convert_currency(100, 20, rate=1.5, symbol="€")
        self.assertEqual(result["base"]["total"], 120.0)
        self.assertEqual(result["converted"]["total"], 180.0)
        self.assertEqual(result["converted"]["tip"], 30.0)
        self.assertEqual(result["converted"]["subtotal"], 150.0)
        self.assertEqual(result["symbol"], "€")
        self.assertEqual(result["rate"], 1.5)

    def test_rate_one_is_identity(self):
        result = convert_currency(80, 15, rate=1.0)
        self.assertEqual(result["base"]["total"], result["converted"]["total"])

    def test_converts_shares(self):
        result = convert_currency(100, 0, rate=2, people=4)
        self.assertEqual(result["converted"]["shares"], [50.0, 50.0, 50.0, 50.0])

    def test_default_symbol(self):
        result = convert_currency(50, 10, rate=1.2)
        self.assertEqual(result["symbol"], "$")

    def test_zero_rate_is_error(self):
        with self.assertRaises(ValueError):
            convert_currency(100, 20, rate=0)

    def test_negative_rate_is_error(self):
        with self.assertRaises(ValueError):
            convert_currency(100, 20, rate=-1)

    def test_non_number_rate_is_error(self):
        with self.assertRaises(ValueError):
            convert_currency(100, 20, rate="x")


class TipWithinBudgetTests(unittest.TestCase):
    def test_budget_caps_tip(self):
        # Bill 100, budget 115 -> tip can only be 15.
        result = tip_within_budget(100, 115)
        self.assertEqual(result["tip"], 15.0)
        self.assertEqual(result["total"], 115.0)
        self.assertTrue(result["within_budget"])
        self.assertEqual(result["effective_tip_percent"], 15.0)

    def test_max_tip_percent_binds_before_budget(self):
        # Generous budget, but max_tip_percent caps the tip at 20%.
        result = tip_within_budget(100, 200, max_tip_percent=20)
        self.assertEqual(result["tip"], 20.0)
        self.assertEqual(result["total"], 120.0)

    def test_budget_below_subtotal_gives_zero_tip(self):
        result = tip_within_budget(100, 90)
        self.assertEqual(result["tip"], 0.0)
        self.assertFalse(result["within_budget"])

    def test_budget_with_tax(self):
        # Bill 100 + 10 tax = 110; budget 120 leaves 10 for tip.
        result = tip_within_budget(100, 120, tax_percent=10)
        self.assertEqual(result["tax"], 10.0)
        self.assertEqual(result["tip"], 10.0)
        self.assertEqual(result["total"], 120.0)

    def test_split_across_people(self):
        result = tip_within_budget(100, 120, people=4)
        self.assertEqual(result["per_person"], 30.0)
        self.assertAlmostEqual(sum(result["shares"]), result["total"], places=2)

    def test_negative_budget_is_error(self):
        with self.assertRaises(ValueError):
            tip_within_budget(100, -5)

    def test_bad_max_tip_percent_is_error(self):
        with self.assertRaises(ValueError):
            tip_within_budget(100, 150, max_tip_percent=150)


class SplitCustomTipsTests(unittest.TestCase):
    def test_per_person_own_tip(self):
        # Bill 100 split 2 ways: 50 each. One tips 20% (10), one tips 10% (5).
        result = split_custom_tips(100, [20, 10])
        self.assertEqual(result["people"], 2)
        self.assertEqual(result["per_person"][0]["share"], 50.0)
        self.assertEqual(result["per_person"][0]["tip"], 10.0)
        self.assertEqual(result["per_person"][1]["tip"], 5.0)
        self.assertEqual(result["tip"], 15.0)
        self.assertEqual(result["total"], 115.0)

    def test_shares_sum_to_total(self):
        result = split_custom_tips(99.99, [15, 18, 20])
        self.assertAlmostEqual(sum(result["shares"]), result["total"], places=2)
        self.assertAlmostEqual(sum(result["tip_shares"]), result["tip"], places=2)

    def test_with_tax_pretax_base(self):
        result = split_custom_tips(100, [20, 20], tax_percent=10)
        self.assertEqual(result["tax"], 10.0)
        # tip on pretax share of 50 -> 10 each.
        self.assertEqual(result["per_person"][0]["tip"], 10.0)
        self.assertEqual(result["per_person"][0]["total"], 65.0)

    def test_posttax_base(self):
        result = split_custom_tips(100, [20], tax_percent=10, tip_on="posttax")
        # one person: subtotal 100 + tax 10 = 110 base, tip 22.
        self.assertEqual(result["per_person"][0]["tip"], 22.0)

    def test_empty_percents_is_error(self):
        with self.assertRaises(ValueError):
            split_custom_tips(100, [])

    def test_bad_percent_is_error(self):
        with self.assertRaises(ValueError):
            split_custom_tips(100, [20, 150])


class HttpMultiBillTests(_ServerTestBase):
    def test_combines(self):
        status, data = self._post(
            "/api/multibill", {"bills": [40, 35, 25], "tip_percent": 20})
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 100.0)
        self.assertEqual(data["total"], 120.0)
        self.assertEqual(data["bill_count"], 3)

    def test_missing_bills_is_400(self):
        status, data = self._post("/api/multibill", {"tip_percent": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_invalid_bill_value_is_400(self):
        status, data = self._post(
            "/api/multibill", {"bills": [10, -5], "tip_percent": 20})
        self.assertEqual(status, 400)


class HttpConvertTests(_ServerTestBase):
    def test_convert(self):
        status, data = self._post(
            "/api/convert",
            {"bill": 100, "tip_percent": 20, "rate": 1.5, "symbol": "€"})
        self.assertEqual(status, 200)
        self.assertEqual(data["converted"]["total"], 180.0)
        self.assertEqual(data["symbol"], "€")

    def test_missing_rate_is_400(self):
        status, data = self._post(
            "/api/convert", {"bill": 100, "tip_percent": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_bad_rate_is_400(self):
        status, data = self._post(
            "/api/convert", {"bill": 100, "tip_percent": 20, "rate": 0})
        self.assertEqual(status, 400)


class HttpBudgetTests(_ServerTestBase):
    def test_budget_caps_tip(self):
        status, data = self._post(
            "/api/budget", {"bill": 100, "budget": 115})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip"], 15.0)
        self.assertTrue(data["within_budget"])

    def test_over_budget(self):
        status, data = self._post(
            "/api/budget", {"bill": 100, "budget": 90})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip"], 0.0)
        self.assertFalse(data["within_budget"])

    def test_missing_budget_is_400(self):
        status, data = self._post("/api/budget", {"bill": 100})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpCustomTests(_ServerTestBase):
    def test_custom_tips(self):
        status, data = self._post(
            "/api/custom", {"bill": 100, "tip_percents": [20, 10]})
        self.assertEqual(status, 200)
        self.assertEqual(data["people"], 2)
        self.assertEqual(data["tip"], 15.0)
        self.assertEqual(data["per_person"][0]["tip"], 10.0)

    def test_missing_percents_falls_back_to_presets(self):
        # Like the presets/compare endpoints, an omitted list uses the defaults.
        status, data = self._post("/api/custom", {"bill": 100})
        self.assertEqual(status, 200)
        self.assertEqual(data["people"], len(DEFAULT_PRESET_PERCENTS))

    def test_bad_percent_is_400(self):
        status, data = self._post(
            "/api/custom", {"bill": 100, "tip_percents": [20, 150]})
        self.assertEqual(status, 400)


class CardSurchargeBillTests(unittest.TestCase):
    def test_surcharge_grosses_up_total(self):
        # $100 + 20% tip = $120 total; a 3% card surcharge adds $3.60.
        r = card_surcharge_bill(100, 20, 3)
        self.assertEqual(r["subtotal"], 100.0)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["pre_surcharge_total"], 120.0)
        self.assertEqual(r["surcharge"], 3.6)
        self.assertEqual(r["surcharge_percent"], 3.0)
        self.assertEqual(r["total"], 123.6)

    def test_surcharge_with_tax(self):
        # $100 + 10% tax = $110, +20% tip on pre-tax = $20 -> $130; +2% = $2.60.
        r = card_surcharge_bill(100, 20, 2, tax_percent=10)
        self.assertEqual(r["tax"], 10.0)
        self.assertEqual(r["pre_surcharge_total"], 130.0)
        self.assertEqual(r["surcharge"], 2.6)
        self.assertEqual(r["total"], 132.6)

    def test_zero_surcharge_matches_plain_bill(self):
        plain = calculate_bill(80, 18)
        r = card_surcharge_bill(80, 18, 0)
        self.assertEqual(r["surcharge"], 0.0)
        self.assertEqual(r["total"], plain["total"])
        self.assertEqual(r["pre_surcharge_total"], plain["total"])

    def test_shares_sum_to_total(self):
        r = card_surcharge_bill(100, 20, 3, people=3)
        self.assertEqual(len(r["shares"]), 3)
        self.assertAlmostEqual(sum(r["shares"]), r["total"], places=2)
        # Shares differ by at most a cent (fair integer split).
        self.assertLessEqual(max(r["shares"]) - min(r["shares"]), 0.01)

    def test_per_person_surcharge_reported(self):
        r = card_surcharge_bill(100, 0, 4, people=2)
        # $100 bill, no tip, 4% surcharge = $4.00 over 2 people -> $2.00 each.
        self.assertEqual(r["surcharge"], 4.0)
        self.assertEqual(r["per_person_surcharge"], 2.0)

    def test_round_total_then_surcharge(self):
        # round_total bumps the pre-surcharge total to a whole dollar first.
        r = card_surcharge_bill(10.10, 15, 0, round_total=True)
        self.assertTrue(r["rounded"])
        self.assertEqual(r["pre_surcharge_total"], 12.0)

    def test_negative_surcharge_rejected(self):
        with self.assertRaises(ValueError):
            card_surcharge_bill(100, 20, -1)

    def test_surcharge_over_100_rejected(self):
        with self.assertRaises(ValueError):
            card_surcharge_bill(100, 20, 150)

    def test_non_numeric_surcharge_rejected(self):
        with self.assertRaises(ValueError):
            card_surcharge_bill(100, 20, "abc")

    def test_invalid_bill_rejected(self):
        with self.assertRaises(ValueError):
            card_surcharge_bill(-1, 20, 3)


class CoerceCompedTests(unittest.TestCase):
    def test_none_means_nobody_comped(self):
        self.assertEqual(_coerce_comped(None, 4), [])

    def test_sorts_and_dedupes(self):
        self.assertEqual(_coerce_comped([3, 1, 1], 4), [1, 3])

    def test_rejects_everyone_comped(self):
        with self.assertRaises(ValueError):
            _coerce_comped([1, 2], 2)

    def test_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            _coerce_comped([5], 4)
        with self.assertRaises(ValueError):
            _coerce_comped([0], 4)

    def test_rejects_non_integer(self):
        with self.assertRaises(ValueError):
            _coerce_comped([1.5], 4)

    def test_rejects_bool(self):
        with self.assertRaises(ValueError):
            _coerce_comped([True], 4)

    def test_rejects_non_list(self):
        with self.assertRaises(ValueError):
            _coerce_comped("1", 4)


class CompDinerSplitTests(unittest.TestCase):
    def test_comped_diner_pays_nothing(self):
        # $120 total split over 3, one comped -> 2 pay $60 each, comped pays $0.
        r = comp_diner_split(100, 20, 3, comped=[2])
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["paying"], 2)
        self.assertEqual(r["comped"], [2])
        self.assertEqual(r["shares"], [60.0, 0.0, 60.0])

    def test_shares_sum_to_total(self):
        r = comp_diner_split(100, 18, 4, comped=[1])
        self.assertEqual(len(r["shares"]), 4)
        self.assertAlmostEqual(sum(r["shares"]), r["total"], places=2)
        self.assertEqual(r["shares"][0], 0.0)

    def test_nobody_comped_matches_even_split(self):
        plain = calculate_bill(90, 20, people=3)
        r = comp_diner_split(90, 20, 3)
        self.assertEqual(r["comped"], [])
        self.assertEqual(r["paying"], 3)
        self.assertAlmostEqual(sum(r["shares"]), plain["total"], places=2)

    def test_per_person_is_largest_paying_share(self):
        # $121 total over 3, one comped -> 2 pay $60.50 each.
        r = comp_diner_split(100, 21, 3, comped=[3])
        self.assertEqual(r["per_person"], r["shares"][0])
        self.assertEqual(r["shares"][2], 0.0)

    def test_everyone_comped_rejected(self):
        with self.assertRaises(ValueError):
            comp_diner_split(100, 20, 2, comped=[1, 2])

    def test_out_of_range_comped_rejected(self):
        with self.assertRaises(ValueError):
            comp_diner_split(100, 20, 3, comped=[9])

    def test_invalid_bill_rejected(self):
        with self.assertRaises(ValueError):
            comp_diner_split(-1, 20, 3, comped=[1])


class HttpCardFeeTests(_ServerTestBase):
    def test_cardfee_grosses_up(self):
        status, data = self._post(
            "/api/cardfee",
            {"bill": 100, "tip_percent": 20, "surcharge_percent": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["surcharge"], 3.6)
        self.assertEqual(data["total"], 123.6)
        self.assertEqual(data["pre_surcharge_total"], 120.0)

    def test_cardfee_split(self):
        status, data = self._post(
            "/api/cardfee",
            {"bill": 100, "tip_percent": 20, "surcharge_percent": 3,
             "people": 3})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["shares"]), 3)
        self.assertAlmostEqual(sum(data["shares"]), data["total"], places=2)

    def test_bad_surcharge_is_400(self):
        status, data = self._post(
            "/api/cardfee",
            {"bill": 100, "tip_percent": 20, "surcharge_percent": 150})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_surcharge_is_400(self):
        status, data = self._post(
            "/api/cardfee", {"bill": 100, "tip_percent": 20})
        self.assertEqual(status, 400)


class HttpCompTests(_ServerTestBase):
    def test_comp_one_diner(self):
        status, data = self._post(
            "/api/comp",
            {"bill": 100, "tip_percent": 20, "people": 3, "comped": [2]})
        self.assertEqual(status, 200)
        self.assertEqual(data["paying"], 2)
        self.assertEqual(data["shares"], [60.0, 0.0, 60.0])

    def test_comp_nobody(self):
        status, data = self._post(
            "/api/comp", {"bill": 90, "tip_percent": 20, "people": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["comped"], [])
        self.assertEqual(data["paying"], 3)

    def test_everyone_comped_is_400(self):
        status, data = self._post(
            "/api/comp",
            {"bill": 100, "tip_percent": 20, "people": 2, "comped": [1, 2]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_bad_comped_is_400(self):
        status, data = self._post(
            "/api/comp",
            {"bill": 100, "tip_percent": 20, "people": 3, "comped": [9]})
        self.assertEqual(status, 400)


class ExtractTaxBillTests(unittest.TestCase):
    def test_backs_out_subtotal_and_tax(self):
        # $110 already includes 10% tax -> $100 subtotal + $10 tax.
        result = extract_tax_bill(110, 0, tax_percent=10)
        self.assertEqual(result["subtotal"], 100.0)
        self.assertEqual(result["tax"], 10.0)
        self.assertEqual(result["tax_inclusive"], 110.0)
        self.assertEqual(result["total"], 110.0)

    def test_subtotal_plus_tax_equals_inclusive(self):
        result = extract_tax_bill(113, 0, tax_percent=13)  # Ontario HST
        self.assertEqual(result["subtotal"], 100.0)
        self.assertEqual(result["tax"], 13.0)
        self.assertEqual(
            round(result["subtotal"] + result["tax"], 2),
            result["tax_inclusive"])

    def test_tip_pretax_is_on_recovered_subtotal(self):
        # Tip 20% on the $100 pre-tax subtotal, not on the $110 inclusive price.
        result = extract_tax_bill(110, 20, tax_percent=10, tip_on="pretax")
        self.assertEqual(result["tip"], 20.0)
        self.assertEqual(result["total"], 130.0)

    def test_tip_posttax_is_on_inclusive_amount(self):
        result = extract_tax_bill(110, 20, tax_percent=10, tip_on="posttax")
        self.assertEqual(result["tip"], 22.0)
        self.assertEqual(result["total"], 132.0)

    def test_zero_tax_is_passthrough(self):
        result = extract_tax_bill(50, 0, tax_percent=0)
        self.assertEqual(result["subtotal"], 50.0)
        self.assertEqual(result["tax"], 0.0)

    def test_split_shares_sum_to_total(self):
        result = extract_tax_bill(110, 20, people=3, tax_percent=10)
        self.assertEqual(len(result["shares"]), 3)
        self.assertEqual(round(sum(result["shares"]), 2), result["total"])

    def test_round_total_absorbs_into_tip(self):
        # $110 incl. 10% tax, tip 17.5% -> $127.50, rounded up to $128.
        result = extract_tax_bill(
            110, 17.5, tax_percent=10, round_total=True)
        self.assertTrue(result["rounded"])
        self.assertEqual(result["total"], 128.0)
        self.assertEqual(result["total"], result["total"] // 1)

    def test_negative_amount_raises(self):
        with self.assertRaises(ValueError):
            extract_tax_bill(-1, 20, tax_percent=10)

    def test_bad_tip_on_raises(self):
        with self.assertRaises(ValueError):
            extract_tax_bill(110, 20, tax_percent=10, tip_on="sideways")


class CoerceIncrementTests(unittest.TestCase):
    def test_dollars_to_cents(self):
        self.assertEqual(_coerce_increment(5), 500)
        self.assertEqual(_coerce_increment("2.5"), 250)

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            _coerce_increment(0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            _coerce_increment(-1)

    def test_non_number_raises(self):
        with self.assertRaises(ValueError):
            _coerce_increment("abc")


class CharityRoundUpTests(unittest.TestCase):
    def test_rounds_total_up_to_increment(self):
        # $92 total rounds up to the next $5 -> $95, $3 donated.
        result = charity_round_up(92, 0, increment=5)
        self.assertEqual(result["pre_donation_total"], 92.0)
        self.assertEqual(result["donation"], 3.0)
        self.assertEqual(result["total"], 95.0)

    def test_exact_multiple_donates_nothing(self):
        result = charity_round_up(100, 0, increment=5)
        self.assertEqual(result["donation"], 0.0)
        self.assertEqual(result["total"], 100.0)

    def test_default_increment_is_five(self):
        result = charity_round_up(92, 0)
        self.assertEqual(result["increment"], 5.0)
        self.assertEqual(result["total"], 95.0)

    def test_ten_dollar_increment(self):
        result = charity_round_up(92, 0, increment=10)
        self.assertEqual(result["donation"], 8.0)
        self.assertEqual(result["total"], 100.0)

    def test_donation_is_separate_from_tip(self):
        # The tip stays exactly what the percentage gives; the surplus is the
        # donation line, not folded into the tip.
        result = charity_round_up(100, 20, increment=5)
        self.assertEqual(result["tip"], 20.0)
        self.assertEqual(result["pre_donation_total"], 120.0)
        self.assertEqual(result["total"], 120.0)
        self.assertEqual(result["donation"], 0.0)

    def test_split_shares_and_donation_sum_back(self):
        # $92 -> $95 total, $3 donation, evenly across 4 people.
        result = charity_round_up(92, 0, people=4, increment=5)
        self.assertEqual(round(sum(result["shares"]), 2), result["total"])
        self.assertEqual(result["donation"], 3.0)
        self.assertEqual(result["per_person_donation"], 0.75)

    def test_bad_increment_raises(self):
        with self.assertRaises(ValueError):
            charity_round_up(100, 20, increment=0)


class CoerceSeatListTests(unittest.TestCase):
    def test_none_is_empty(self):
        self.assertEqual(_coerce_seat_list(None, 4, "card_payers"), [])

    def test_dedupes_and_sorts(self):
        self.assertEqual(
            _coerce_seat_list([2, 1, 1], 3, "card_payers"), [1, 2])

    def test_full_table_allowed(self):
        # Unlike comped diners, everyone may be in the list.
        self.assertEqual(
            _coerce_seat_list([1, 2, 3], 3, "card_payers"), [1, 2, 3])

    def test_out_of_range_raises(self):
        with self.assertRaises(ValueError):
            _coerce_seat_list([4], 3, "card_payers")

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            _coerce_seat_list([0], 3, "card_payers")

    def test_string_raises(self):
        with self.assertRaises(ValueError):
            _coerce_seat_list("12", 3, "card_payers")

    def test_non_integer_raises(self):
        with self.assertRaises(ValueError):
            _coerce_seat_list([1.5], 3, "card_payers")

    def test_bool_raises(self):
        with self.assertRaises(ValueError):
            _coerce_seat_list([True], 3, "card_payers")


class SplitMixedPaymentTests(unittest.TestCase):
    def test_card_payers_charged_surcharge_on_their_share(self):
        result = split_mixed_payment(
            100, 0, 4, card_payers=[1, 2], surcharge_percent=10)
        self.assertEqual(result["shares"], [25.0, 25.0, 25.0, 25.0])
        self.assertEqual(result["surcharges"], [2.5, 2.5, 0.0, 0.0])
        self.assertEqual(result["payments"], [27.5, 27.5, 25.0, 25.0])

    def test_collected_is_total_plus_surcharges(self):
        result = split_mixed_payment(
            100, 0, 4, card_payers=[1, 2], surcharge_percent=10)
        self.assertEqual(result["surcharge_total"], 5.0)
        self.assertEqual(result["collected"], 105.0)
        self.assertEqual(
            round(result["total"] + result["surcharge_total"], 2),
            result["collected"])

    def test_no_card_payers_is_plain_split(self):
        result = split_mixed_payment(100, 0, 4)
        self.assertEqual(result["card_payers"], [])
        self.assertEqual(result["surcharges"], [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(result["payments"], result["shares"])
        self.assertEqual(result["collected"], result["total"])

    def test_everyone_pays_by_card(self):
        result = split_mixed_payment(
            100, 0, 2, card_payers=[1, 2], surcharge_percent=5)
        self.assertEqual(result["surcharges"], [2.5, 2.5])
        self.assertEqual(result["collected"], 105.0)

    def test_payments_sum_to_collected(self):
        result = split_mixed_payment(
            87.65, 18, 3, card_payers=[2], surcharge_percent=3)
        self.assertEqual(round(sum(result["payments"]), 2), result["collected"])

    def test_per_person_is_largest_payment(self):
        result = split_mixed_payment(
            100, 0, 4, card_payers=[1], surcharge_percent=10)
        self.assertEqual(result["per_person"], max(result["payments"]))

    def test_bad_surcharge_raises(self):
        with self.assertRaises(ValueError):
            split_mixed_payment(
                100, 0, 4, card_payers=[1], surcharge_percent=150)

    def test_bad_card_payer_raises(self):
        with self.assertRaises(ValueError):
            split_mixed_payment(
                100, 0, 4, card_payers=[9], surcharge_percent=10)


class HttpExtractTaxTests(_ServerTestBase):
    def test_backs_out_subtotal(self):
        status, data = self._post(
            "/api/extracttax",
            {"total_with_tax": 110, "tip_percent": 0, "tax_percent": 10})
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 100.0)
        self.assertEqual(data["tax"], 10.0)

    def test_tip_on_subtotal(self):
        status, data = self._post(
            "/api/extracttax",
            {"total_with_tax": 110, "tip_percent": 20, "tax_percent": 10})
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 130.0)

    def test_validation_error_is_400(self):
        status, data = self._post(
            "/api/extracttax",
            {"total_with_tax": -1, "tip_percent": 20, "tax_percent": 10})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_fields_is_400(self):
        status, data = self._post("/api/extracttax", {"tax_percent": 10})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpCharityTests(_ServerTestBase):
    def test_rounds_up_and_donates(self):
        status, data = self._post(
            "/api/charity",
            {"bill": 92, "tip_percent": 0, "increment": 5})
        self.assertEqual(status, 200)
        self.assertEqual(data["donation"], 3.0)
        self.assertEqual(data["total"], 95.0)

    def test_default_increment(self):
        status, data = self._post(
            "/api/charity", {"bill": 92, "tip_percent": 0})
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 95.0)

    def test_bad_increment_is_400(self):
        status, data = self._post(
            "/api/charity",
            {"bill": 92, "tip_percent": 0, "increment": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpMixedPayTests(_ServerTestBase):
    def test_mixed_split(self):
        status, data = self._post(
            "/api/mixedpay",
            {"bill": 100, "tip_percent": 0, "people": 4,
             "card_payers": [1, 2], "surcharge_percent": 10})
        self.assertEqual(status, 200)
        self.assertEqual(data["payments"], [27.5, 27.5, 25.0, 25.0])
        self.assertEqual(data["collected"], 105.0)

    def test_no_card_payers(self):
        status, data = self._post(
            "/api/mixedpay",
            {"bill": 100, "tip_percent": 0, "people": 4})
        self.assertEqual(status, 200)
        self.assertEqual(data["collected"], data["total"])

    def test_bad_card_payer_is_400(self):
        status, data = self._post(
            "/api/mixedpay",
            {"bill": 100, "tip_percent": 0, "people": 4,
             "card_payers": [9], "surcharge_percent": 10})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class SplitSharedItemsTests(unittest.TestCase):
    def test_shared_split_evenly_on_top_of_own(self):
        # Two diners order $40 / $60; a $20 shared appetiser is split evenly.
        r = split_shared_items([40, 60], [20], 0)
        self.assertEqual(r["subtotal"], 120.0)
        self.assertEqual(r["shared_total"], 20.0)
        self.assertEqual(r["shared_per_person"], [10.0, 10.0])
        self.assertEqual(r["breakdown"][0]["own"], 40.0)
        self.assertEqual(r["breakdown"][0]["shared"], 10.0)
        self.assertEqual(r["breakdown"][0]["subtotal"], 50.0)
        self.assertEqual(r["breakdown"][1]["subtotal"], 70.0)
        self.assertEqual(r["shares"], [50.0, 70.0])

    def test_no_shared_matches_split_by_items(self):
        a = split_shared_items([40, 60], None, 18, tax_percent=13)
        b = split_by_items([40, 60], 18, tax_percent=13)
        self.assertEqual(a["total"], b["total"])
        self.assertEqual(a["tip"], b["tip"])
        self.assertEqual(a["shares"], b["shares"])
        self.assertEqual(a["shared_total"], 0.0)

    def test_empty_shared_list_means_no_shared(self):
        r = split_shared_items([40, 60], [], 0)
        self.assertEqual(r["shared_total"], 0.0)
        self.assertEqual(r["shared_per_person"], [0.0, 0.0])
        self.assertEqual(r["shares"], [40.0, 60.0])

    def test_tip_apportioned_by_combined_subtotal(self):
        # $40/$60 own + $20 shared -> subtotals $50/$70, bill $120.
        # 20% tip = $24 split 50:70 -> $10 / $14.
        r = split_shared_items([40, 60], [20], 20)
        self.assertEqual(r["tip"], 24.0)
        self.assertEqual(r["breakdown"][0]["tip"], 10.0)
        self.assertEqual(r["breakdown"][1]["tip"], 14.0)

    def test_shared_per_person_sums_back_to_shared_total(self):
        r = split_shared_items([10, 10, 10], [10.01], 0)
        self.assertEqual(round(sum(r["shared_per_person"]), 2),
                         r["shared_total"])

    def test_shares_and_breakdown_sum_back(self):
        r = split_shared_items([[12.50, 3.25], [9.99], [20.00]],
                               [15.75, 4.00], 18, tax_percent=13)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])
        self.assertEqual(round(sum(r["tip_shares"]), 2), r["tip"])
        for person in r["breakdown"]:
            self.assertEqual(
                round(person["own"] + person["shared"], 2), person["subtotal"])
            self.assertEqual(
                round(person["subtotal"] + person["tax"] + person["tip"], 2),
                person["total"])

    def test_nested_own_items_summed(self):
        r = split_shared_items([[10, 5], [20]], [6], 0)
        self.assertEqual(r["breakdown"][0]["own"], 15.0)
        self.assertEqual(r["breakdown"][1]["own"], 20.0)
        self.assertEqual(r["breakdown"][0]["shared"], 3.0)
        self.assertEqual(r["subtotal"], 41.0)

    def test_fully_comped_table_splits_evenly(self):
        # No own items, no shared -> nothing owed, tax/tip even-split fallback.
        r = split_shared_items([0, 0], [], 20, tax_percent=10)
        self.assertEqual(r["total"], 0.0)
        self.assertEqual(r["shares"], [0.0, 0.0])

    def test_empty_items_raise(self):
        with self.assertRaises(ValueError):
            split_shared_items([], [20], 0)

    def test_negative_shared_raises(self):
        with self.assertRaises(ValueError):
            split_shared_items([10, 20], [-5], 0)

    def test_non_list_shared_raises(self):
        with self.assertRaises(ValueError):
            split_shared_items([10, 20], "5,5", 0)

    def test_non_list_items_raise(self):
        with self.assertRaises(ValueError):
            split_shared_items("10,20", [5], 0)


class HttpSharedItemsTests(_ServerTestBase):
    def test_shared_items_split(self):
        status, data = self._post(
            "/api/shareditems",
            {"items": [40, 60], "shared": [20], "tip_percent": 20})
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 120.0)
        self.assertEqual(data["shared_total"], 20.0)
        self.assertEqual(data["breakdown"][0]["tip"], 10.0)
        self.assertEqual(data["breakdown"][1]["tip"], 14.0)

    def test_shared_items_with_tax_sum_back(self):
        status, data = self._post(
            "/api/shareditems",
            {"items": [[12.5, 3.25], [9.99]], "shared": [8.5],
             "tip_percent": 18, "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_shared_omitted_defaults_to_no_shared(self):
        status, data = self._post(
            "/api/shareditems", {"items": [40, 60], "tip_percent": 0})
        self.assertEqual(status, 200)
        self.assertEqual(data["shared_total"], 0.0)
        self.assertEqual(data["shares"], [40.0, 60.0])

    def test_empty_items_is_400(self):
        status, data = self._post(
            "/api/shareditems", {"items": [], "shared": [20]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_negative_shared_is_400(self):
        status, data = self._post(
            "/api/shareditems",
            {"items": [10, 20], "shared": [-5], "tip_percent": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class CoerceCategoriesTests(unittest.TestCase):
    def test_basic_categories(self):
        cats = _coerce_categories(
            [{"name": "Food", "amount": 80, "tip_percent": 20},
             {"name": "Bar", "amount": 20, "tip_percent": 10}])
        self.assertEqual(cats,
                         [("Food", 80.0, 20.0), ("Bar", 20.0, 10.0)])

    def test_missing_name_is_filled_in(self):
        cats = _coerce_categories([{"amount": 50, "tip_percent": 18}])
        self.assertEqual(cats[0][0], "Category 1")

    def test_string_numbers_coerced(self):
        cats = _coerce_categories([{"amount": "40.5", "tip_percent": "15"}])
        self.assertEqual(cats[0][1], 40.5)
        self.assertEqual(cats[0][2], 15.0)

    def test_empty_list_raises(self):
        with self.assertRaises(ValueError):
            _coerce_categories([])

    def test_string_is_not_a_valid_list(self):
        with self.assertRaises(ValueError):
            _coerce_categories("food")

    def test_non_dict_entry_raises(self):
        with self.assertRaises(ValueError):
            _coerce_categories([[40, 20]])

    def test_missing_amount_raises(self):
        with self.assertRaises(ValueError):
            _coerce_categories([{"tip_percent": 20}])

    def test_missing_tip_percent_raises(self):
        with self.assertRaises(ValueError):
            _coerce_categories([{"amount": 40}])

    def test_negative_amount_raises(self):
        with self.assertRaises(ValueError):
            _coerce_categories([{"amount": -1, "tip_percent": 20}])

    def test_tip_percent_over_100_raises(self):
        with self.assertRaises(ValueError):
            _coerce_categories([{"amount": 40, "tip_percent": 150}])

    def test_bool_amount_raises(self):
        with self.assertRaises(ValueError):
            _coerce_categories([{"amount": True, "tip_percent": 20}])

    def test_non_numeric_raises(self):
        with self.assertRaises(ValueError):
            _coerce_categories([{"amount": "abc", "tip_percent": 20}])


class TipByCategoryTests(unittest.TestCase):
    def test_food_and_bar_tipped_separately(self):
        # $80 food @ 20% (16) + $20 bar @ 10% (2) -> tip 18, total 118.
        r = tip_by_category(
            [{"name": "Food", "amount": 80, "tip_percent": 20},
             {"name": "Bar", "amount": 20, "tip_percent": 10}])
        self.assertEqual(r["subtotal"], 100.0)
        self.assertEqual(r["tip"], 18.0)
        self.assertEqual(r["total"], 118.0)
        self.assertEqual(r["categories"][0]["tip"], 16.0)
        self.assertEqual(r["categories"][1]["tip"], 2.0)

    def test_effective_blended_percent(self):
        # tip 18 on a 100 subtotal -> effective 18%.
        r = tip_by_category(
            [{"amount": 80, "tip_percent": 20}, {"amount": 20, "tip_percent": 10}])
        self.assertEqual(r["tip_percent"], 18.0)

    def test_single_category_matches_calculate(self):
        cat = tip_by_category([{"amount": 100, "tip_percent": 20}])
        plain = calculate(100, 20)
        self.assertEqual(cat["tip"], plain["tip"])
        self.assertEqual(cat["total"], plain["total"])

    def test_zero_tip_on_bar(self):
        # No tip on the bar tab at all.
        r = tip_by_category(
            [{"name": "Food", "amount": 50, "tip_percent": 20},
             {"name": "Bar", "amount": 50, "tip_percent": 0}])
        self.assertEqual(r["tip"], 10.0)
        self.assertEqual(r["total"], 110.0)

    def test_tax_on_combined_subtotal(self):
        # 10% tax on the $100 combined subtotal = 10; tip 18 -> total 128.
        r = tip_by_category(
            [{"amount": 80, "tip_percent": 20}, {"amount": 20, "tip_percent": 10}],
            tax_percent=10)
        self.assertEqual(r["tax"], 10.0)
        self.assertEqual(r["total"], 128.0)

    def test_split_sums_back_to_total(self):
        r = tip_by_category(
            [{"amount": 41.37, "tip_percent": 20},
             {"amount": 17.49, "tip_percent": 15}],
            people=3, tax_percent=13)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])
        self.assertEqual(r["people"], 3)

    def test_round_total_absorbs_into_tip(self):
        r = tip_by_category(
            [{"amount": 23.45, "tip_percent": 18}], round_total=True)
        self.assertTrue(r["rounded"])
        self.assertEqual(r["total"], int(r["total"]))
        self.assertEqual(
            round(r["subtotal"] + r["tax"] + r["tip"], 2), r["total"])

    def test_per_person_tip_present(self):
        r = tip_by_category(
            [{"amount": 80, "tip_percent": 20}, {"amount": 20, "tip_percent": 10}],
            people=2)
        self.assertEqual(r["per_person_tip"], 9.0)

    def test_empty_categories_raises(self):
        with self.assertRaises(ValueError):
            tip_by_category([])

    def test_invalid_category_raises(self):
        with self.assertRaises(ValueError):
            tip_by_category([{"amount": -5, "tip_percent": 20}])

    def test_zero_people_raises(self):
        with self.assertRaises(ValueError):
            tip_by_category([{"amount": 40, "tip_percent": 20}], people=0)

    def test_bad_tax_raises(self):
        with self.assertRaises(ValueError):
            tip_by_category([{"amount": 40, "tip_percent": 20}], tax_percent=150)


class HttpCategoryTests(_ServerTestBase):
    def test_category_split(self):
        status, data = self._post(
            "/api/category",
            {"categories": [{"name": "Food", "amount": 80, "tip_percent": 20},
                            {"name": "Bar", "amount": 20, "tip_percent": 10}]})
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 100.0)
        self.assertEqual(data["tip"], 18.0)
        self.assertEqual(data["total"], 118.0)
        self.assertEqual(data["categories"][1]["name"], "Bar")

    def test_category_with_tax_and_people_sum_back(self):
        status, data = self._post(
            "/api/category",
            {"categories": [{"amount": 41.37, "tip_percent": 20},
                            {"amount": 17.49, "tip_percent": 15}],
             "people": 3, "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_empty_categories_is_400(self):
        status, data = self._post("/api/category", {"categories": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_categories_is_400(self):
        status, data = self._post("/api/category", {"people": 2})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_invalid_category_is_400(self):
        status, data = self._post(
            "/api/category",
            {"categories": [{"amount": 40, "tip_percent": 150}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class SettlePaymentsTests(unittest.TestCase):
    def test_one_payer_covered_everyone(self):
        # $120 bill, no tip, 4 people = $30 each. Person 1 paid the whole $120,
        # the other three paid nothing -> each owes person 1 $30.
        result = settle_payments(120, 0, 4, [120, 0, 0, 0])
        self.assertEqual(result["transfer_count"], 3)
        for t in result["transfers"]:
            self.assertEqual(t["to"], 1)
            self.assertEqual(t["amount"], 30.0)
        froms = sorted(t["from"] for t in result["transfers"])
        self.assertEqual(froms, [2, 3, 4])

    def test_already_settled_has_no_transfers(self):
        # Everyone paid exactly their fair share -> nothing to reconcile.
        result = settle_payments(100, 0, 4, [25, 25, 25, 25])
        self.assertEqual(result["transfers"], [])
        self.assertEqual(result["transfer_count"], 0)

    def test_transfers_net_each_debtor_and_creditor(self):
        # $100 / 4 = $25 each. P1 paid $70, P2 $30, P3/P4 nothing.
        # Credits: P1 +45, P2 +5. Debts: P3 25, P4 25.
        result = settle_payments(100, 0, 4, [70, 30, 0, 0])
        # Transfers must exactly clear every debtor's debt.
        paid_by = {}
        for t in result["transfers"]:
            paid_by[t["from"]] = paid_by.get(t["from"], 0) + t["amount"]
        self.assertEqual(round(paid_by.get(3, 0), 2), 25.0)
        self.assertEqual(round(paid_by.get(4, 0), 2), 25.0)
        # ...and exactly settle every creditor.
        received = {}
        for t in result["transfers"]:
            received[t["to"]] = received.get(t["to"], 0) + t["amount"]
        self.assertEqual(round(received.get(1, 0), 2), 45.0)
        self.assertEqual(round(received.get(2, 0), 2), 5.0)

    def test_transfers_sum_to_total_moved(self):
        # The sum of all transfers equals the total credit (= total debt) when
        # the table paid exactly the grand total.
        result = settle_payments(100, 20, 3, [120, 0, 0])
        moved = round(sum(t["amount"] for t in result["transfers"]), 2)
        # P1 overpaid by total - share = 120 - 40 = 80.
        self.assertEqual(moved, 80.0)
        self.assertEqual(result["outstanding"], 0.0)

    def test_minimal_transfer_count(self):
        # A clean pairing should need at most people-1 transfers.
        result = settle_payments(100, 0, 4, [50, 50, 0, 0])
        self.assertLessEqual(result["transfer_count"], 3)
        # P1/P2 each overpaid 25, P3/P4 each owe 25 -> 2 clean transfers.
        self.assertEqual(result["transfer_count"], 2)

    def test_keeps_settle_up_fields(self):
        result = settle_payments(100, 0, 4, [120, 0, 0, 0])
        # The settle_up surface is preserved unchanged.
        self.assertIn("balances", result)
        self.assertIn("outstanding", result)
        self.assertIn("paid_total", result)
        self.assertEqual(result["total"], 100.0)

    def test_underpaid_house_leaves_outstanding(self):
        # The table paid only $80 of a $100 bill: $20 is still owed to the house
        # and cannot be settled internally, but the diners still reconcile.
        result = settle_payments(100, 0, 4, [80, 0, 0, 0])
        self.assertEqual(result["outstanding"], 20.0)
        # P1 overpaid their $25 share by $55; the others owe $25 each ($75),
        # so only $55 can be matched internally.
        moved = round(sum(t["amount"] for t in result["transfers"]), 2)
        self.assertEqual(moved, 55.0)

    def test_transfers_use_one_based_diner_numbers(self):
        result = settle_payments(60, 0, 3, [60, 0, 0])
        for t in result["transfers"]:
            self.assertGreaterEqual(t["from"], 1)
            self.assertLessEqual(t["from"], 3)
            self.assertGreaterEqual(t["to"], 1)
            self.assertLessEqual(t["to"], 3)
            self.assertNotEqual(t["from"], t["to"])

    def test_bad_paid_length_raises(self):
        with self.assertRaises(ValueError):
            settle_payments(100, 0, 4, [25, 25, 25])

    def test_with_tax_and_tip_still_reconciles(self):
        # $100 + 10% tax + 20% tip (pretax) = $130, 2 people = $65 each.
        # P1 paid all $130 -> P2 owes P1 $65.
        result = settle_payments(100, 20, 2, [130, 0], tax_percent=10)
        self.assertEqual(result["total"], 130.0)
        self.assertEqual(result["transfer_count"], 1)
        self.assertEqual(result["transfers"][0]["from"], 2)
        self.assertEqual(result["transfers"][0]["to"], 1)
        self.assertEqual(result["transfers"][0]["amount"], 65.0)


class CoerceBracketsTests(unittest.TestCase):
    def test_basic_table(self):
        table = _coerce_brackets([
            {"up_to": 50, "tip_percent": 18},
            {"up_to": 100, "tip_percent": 20},
            {"tip_percent": 22},
        ])
        self.assertEqual(table, [(5000, 18.0), (10000, 20.0), (None, 22.0)])

    def test_open_bracket_must_be_last(self):
        with self.assertRaises(ValueError):
            _coerce_brackets([
                {"tip_percent": 18},
                {"up_to": 100, "tip_percent": 20},
            ])

    def test_bounds_must_increase(self):
        with self.assertRaises(ValueError):
            _coerce_brackets([
                {"up_to": 100, "tip_percent": 18},
                {"up_to": 50, "tip_percent": 20},
            ])

    def test_equal_bounds_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_brackets([
                {"up_to": 50, "tip_percent": 18},
                {"up_to": 50, "tip_percent": 20},
            ])

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_brackets([])

    def test_missing_tip_percent_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_brackets([{"up_to": 50}])

    def test_out_of_range_tip_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_brackets([{"up_to": 50, "tip_percent": 150}])

    def test_non_positive_up_to_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_brackets([{"up_to": 0, "tip_percent": 18},
                              {"tip_percent": 20}])

    def test_string_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_brackets("nope")

    def test_single_open_bracket_ok(self):
        self.assertEqual(_coerce_brackets([{"tip_percent": 20}]),
                         [(None, 20.0)])


class TieredTipTests(unittest.TestCase):
    BRACKETS = [
        {"up_to": 50, "tip_percent": 18},
        {"up_to": 100, "tip_percent": 20},
        {"tip_percent": 22},
    ]

    def test_small_bill_uses_first_bracket(self):
        result = tiered_tip(40, self.BRACKETS)
        self.assertEqual(result["applied_percent"], 18.0)
        self.assertEqual(result["matched_bracket"], 1)
        self.assertEqual(result["tip"], 7.2)

    def test_boundary_is_inclusive_of_upper_bound(self):
        # Exactly $50 still falls in the "up to $50" bracket.
        result = tiered_tip(50, self.BRACKETS)
        self.assertEqual(result["applied_percent"], 18.0)
        self.assertEqual(result["matched_bracket"], 1)

    def test_middle_bracket(self):
        result = tiered_tip(80, self.BRACKETS)
        self.assertEqual(result["applied_percent"], 20.0)
        self.assertEqual(result["matched_bracket"], 2)
        self.assertEqual(result["tip"], 16.0)

    def test_open_ended_bracket_catches_large_bill(self):
        result = tiered_tip(250, self.BRACKETS)
        self.assertEqual(result["applied_percent"], 22.0)
        self.assertEqual(result["matched_bracket"], 3)
        self.assertEqual(result["tip"], 55.0)

    def test_no_open_bracket_falls_back_to_highest(self):
        # A finite-only table still prices a bill above every bound, using the
        # last (highest) bracket rather than failing.
        result = tiered_tip(500, [{"up_to": 50, "tip_percent": 18},
                                  {"up_to": 100, "tip_percent": 20}])
        self.assertEqual(result["applied_percent"], 20.0)
        self.assertEqual(result["matched_bracket"], 2)

    def test_keeps_calculate_bill_surface(self):
        result = tiered_tip(80, self.BRACKETS, people=4, tax_percent=10)
        self.assertEqual(result["subtotal"], 80.0)
        self.assertEqual(result["tax"], 8.0)
        self.assertEqual(round(sum(result["shares"]), 2), result["total"])
        self.assertEqual(result["brackets"][2]["up_to"], None)

    def test_invalid_brackets_raise(self):
        with self.assertRaises(ValueError):
            tiered_tip(80, [])

    def test_invalid_bill_raises(self):
        with self.assertRaises(ValueError):
            tiered_tip(-5, self.BRACKETS)


class HttpReconcileTests(_ServerTestBase):
    def test_reconcile_one_payer(self):
        status, data = self._post(
            "/api/reconcile",
            {"bill": 120, "tip_percent": 0, "people": 4,
             "paid": [120, 0, 0, 0]})
        self.assertEqual(status, 200)
        self.assertEqual(data["transfer_count"], 3)
        self.assertTrue(all(t["to"] == 1 for t in data["transfers"]))

    def test_reconcile_settled_table(self):
        status, data = self._post(
            "/api/reconcile",
            {"bill": 100, "tip_percent": 0, "people": 4,
             "paid": [25, 25, 25, 25]})
        self.assertEqual(status, 200)
        self.assertEqual(data["transfers"], [])

    def test_reconcile_bad_paid_is_400(self):
        status, data = self._post(
            "/api/reconcile",
            {"bill": 100, "tip_percent": 0, "people": 4, "paid": [25, 25]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_reconcile_missing_paid_is_400(self):
        status, data = self._post(
            "/api/reconcile",
            {"bill": 100, "tip_percent": 0, "people": 4})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpTieredTests(_ServerTestBase):
    BRACKETS = [
        {"up_to": 50, "tip_percent": 18},
        {"up_to": 100, "tip_percent": 20},
        {"tip_percent": 22},
    ]

    def test_tiered_middle_bracket(self):
        status, data = self._post(
            "/api/tiered", {"bill": 80, "brackets": self.BRACKETS})
        self.assertEqual(status, 200)
        self.assertEqual(data["applied_percent"], 20.0)
        self.assertEqual(data["matched_bracket"], 2)
        self.assertEqual(data["tip"], 16.0)

    def test_tiered_open_bracket(self):
        status, data = self._post(
            "/api/tiered", {"bill": 250, "brackets": self.BRACKETS})
        self.assertEqual(status, 200)
        self.assertEqual(data["applied_percent"], 22.0)

    def test_tiered_with_people_sum_back(self):
        status, data = self._post(
            "/api/tiered",
            {"bill": 80, "brackets": self.BRACKETS, "people": 3,
             "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_tiered_empty_brackets_is_400(self):
        status, data = self._post(
            "/api/tiered", {"bill": 80, "brackets": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_tiered_missing_brackets_is_400(self):
        status, data = self._post("/api/tiered", {"bill": 80})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class CoerceGiftCardTests(unittest.TestCase):
    def test_dollars_to_cents(self):
        self.assertEqual(_coerce_gift_card(25), 2500)
        self.assertEqual(_coerce_gift_card("12.50"), 1250)

    def test_zero_is_allowed(self):
        self.assertEqual(_coerce_gift_card(0), 0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            _coerce_gift_card(-1)

    def test_non_number_raises(self):
        with self.assertRaises(ValueError):
            _coerce_gift_card("abc")

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            _coerce_gift_card(None)

    def test_bool_raises(self):
        with self.assertRaises(ValueError):
            _coerce_gift_card(True)

    def test_nan_raises(self):
        with self.assertRaises(ValueError):
            _coerce_gift_card(float("nan"))

    def test_inf_raises(self):
        with self.assertRaises(ValueError):
            _coerce_gift_card(float("inf"))


class GiftCardSplitTests(unittest.TestCase):
    def test_card_reduces_balance_owed(self):
        # $100 + 20% tip = $120 total; a $50 gift card leaves $70 to pay.
        r = gift_card_split(100, 20, 1, 50)
        self.assertEqual(r["full_total"], 120.0)
        self.assertEqual(r["gift_card"], 50.0)
        self.assertEqual(r["applied"], 50.0)
        self.assertEqual(r["unused"], 0.0)
        self.assertEqual(r["remaining"], 70.0)
        self.assertEqual(r["per_person"], 70.0)

    def test_tax_and_tip_still_on_full_bill(self):
        # Unlike a discount, the card does NOT shrink the taxable base: the tax
        # and tip match a plain bill, only the final balance changes.
        plain = calculate_bill(100, 20, tax_percent=10)
        r = gift_card_split(100, 20, 1, 30, tax_percent=10)
        self.assertEqual(r["tax"], plain["tax"])
        self.assertEqual(r["tip"], plain["tip"])
        self.assertEqual(r["full_total"], plain["total"])
        self.assertEqual(r["remaining"], round(plain["total"] - 30, 2))

    def test_card_larger_than_total_zeroes_balance(self):
        # A $200 card on a $120 bill covers it all; $80 surplus is unused.
        r = gift_card_split(100, 20, 3, 200)
        self.assertEqual(r["applied"], 120.0)
        self.assertEqual(r["unused"], 80.0)
        self.assertEqual(r["remaining"], 0.0)
        self.assertEqual(r["shares"], [0.0, 0.0, 0.0])

    def test_zero_card_matches_plain_bill(self):
        plain = calculate_bill(80, 18, people=4)
        r = gift_card_split(80, 18, 4, 0)
        self.assertEqual(r["remaining"], plain["total"])
        self.assertEqual(r["applied"], 0.0)
        self.assertEqual(r["unused"], 0.0)
        self.assertAlmostEqual(sum(r["shares"]), plain["total"], places=2)

    def test_remaining_split_sums_back_exactly(self):
        # $120 total, $25 card -> $95 over 3 people, fair to the cent.
        r = gift_card_split(100, 20, 3, 25)
        self.assertEqual(len(r["shares"]), 3)
        self.assertAlmostEqual(sum(r["shares"]), r["remaining"], places=2)
        self.assertLessEqual(round(max(r["shares"]) - min(r["shares"]), 2), 0.01)
        self.assertEqual(r["per_person_remaining"], r["shares"][0])

    def test_round_total_then_card(self):
        # round_total bumps the grand total to a whole dollar before the card.
        r = gift_card_split(10.10, 15, 1, 5, round_total=True)
        self.assertTrue(r["rounded"])
        self.assertEqual(r["full_total"], 12.0)
        self.assertEqual(r["remaining"], 7.0)

    def test_negative_card_rejected(self):
        with self.assertRaises(ValueError):
            gift_card_split(100, 20, 1, -5)

    def test_non_numeric_card_rejected(self):
        with self.assertRaises(ValueError):
            gift_card_split(100, 20, 1, "abc")

    def test_invalid_bill_rejected(self):
        with self.assertRaises(ValueError):
            gift_card_split(-1, 20, 1, 10)


class HttpGiftCardTests(_ServerTestBase):
    def test_giftcard_reduces_balance(self):
        status, data = self._post(
            "/api/giftcard",
            {"bill": 100, "tip_percent": 20, "gift_card": 50})
        self.assertEqual(status, 200)
        self.assertEqual(data["full_total"], 120.0)
        self.assertEqual(data["remaining"], 70.0)
        self.assertEqual(data["applied"], 50.0)

    def test_giftcard_split(self):
        status, data = self._post(
            "/api/giftcard",
            {"bill": 100, "tip_percent": 20, "gift_card": 25, "people": 3})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["shares"]), 3)
        self.assertAlmostEqual(sum(data["shares"]), data["remaining"], places=2)

    def test_giftcard_over_total_zeroes_balance(self):
        status, data = self._post(
            "/api/giftcard",
            {"bill": 100, "tip_percent": 20, "gift_card": 500})
        self.assertEqual(status, 200)
        self.assertEqual(data["remaining"], 0.0)
        self.assertEqual(data["unused"], 380.0)

    def test_negative_card_is_400(self):
        status, data = self._post(
            "/api/giftcard",
            {"bill": 100, "tip_percent": 20, "gift_card": -5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_card_is_400(self):
        status, data = self._post(
            "/api/giftcard", {"bill": 100, "tip_percent": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class CoerceFeeTests(unittest.TestCase):
    def test_number_to_cents(self):
        self.assertEqual(_coerce_fee(5, "delivery_fee"), 500)
        self.assertEqual(_coerce_fee("2.5", "delivery_fee"), 250)
        self.assertEqual(_coerce_fee(0, "delivery_fee"), 0)

    def test_float_drift_handled(self):
        self.assertEqual(_coerce_fee(4.99, "delivery_fee"), 499)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            _coerce_fee(-1, "delivery_fee")

    def test_bool_raises(self):
        with self.assertRaises(ValueError):
            _coerce_fee(True, "delivery_fee")

    def test_nan_raises(self):
        with self.assertRaises(ValueError):
            _coerce_fee(float("nan"), "delivery_fee")

    def test_inf_raises(self):
        with self.assertRaises(ValueError):
            _coerce_fee(float("inf"), "delivery_fee")

    def test_non_numeric_raises(self):
        with self.assertRaises(ValueError):
            _coerce_fee("abc", "delivery_fee")

    def test_error_names_the_field(self):
        with self.assertRaises(ValueError) as ctx:
            _coerce_fee(-1, "service_fee")
        self.assertIn("service_fee", str(ctx.exception))


class DeliveryOrderTests(unittest.TestCase):
    def test_flat_fees_added_to_total(self):
        # $50 food, $5 delivery, $2 service, 20% tip on food (= 10), no tax.
        r = delivery_order(50, 20, delivery_fee=5, service_fee=2)
        self.assertEqual(r["subtotal"], 50.0)
        self.assertEqual(r["delivery_fee"], 5.0)
        self.assertEqual(r["service_fee"], 2.0)
        self.assertEqual(r["fees"], 7.0)
        self.assertEqual(r["tip"], 10.0)
        self.assertEqual(r["total"], 67.0)

    def test_tip_ignores_fees(self):
        # The tip is figured on the food subtotal, never on the flat fees.
        with_fees = delivery_order(50, 20, delivery_fee=9, service_fee=6)
        without_fees = delivery_order(50, 20)
        self.assertEqual(with_fees["tip"], without_fees["tip"])
        self.assertEqual(with_fees["tip"], 10.0)

    def test_tax_on_subtotal_only(self):
        # $100 food + 10% tax (10) + $5 delivery + 20% tip (20) = 135.
        r = delivery_order(100, 20, delivery_fee=5, tax_percent=10)
        self.assertEqual(r["tax"], 10.0)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["total"], 135.0)

    def test_posttax_tip_base(self):
        # 20% tip on (100 + 10 tax) = 110 -> 22; total 100+10+5+22 = 137.
        r = delivery_order(100, 20, delivery_fee=5, tax_percent=10,
                           tip_on="posttax")
        self.assertEqual(r["tip"], 22.0)
        self.assertEqual(r["total"], 137.0)

    def test_zero_fees_matches_calculate_bill(self):
        d = delivery_order(100, 18, people=2, tax_percent=13)
        b = calculate_bill(100, 18, people=2, tax_percent=13)
        self.assertEqual(d["total"], b["total"])
        self.assertEqual(d["tip"], b["tip"])
        self.assertEqual(d["per_person"], b["per_person"])
        self.assertEqual(d["fees"], 0.0)

    def test_shares_sum_back_to_total(self):
        r = delivery_order(123.45, 18, delivery_fee=4.99, service_fee=2.50,
                           people=3, tax_percent=13)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])

    def test_per_person_fees_split_fairly(self):
        r = delivery_order(100, 0, delivery_fee=10, people=4)
        self.assertEqual(r["per_person_fees"], 2.5)

    def test_round_total_absorbs_into_tip(self):
        r = delivery_order(23.45, 18, delivery_fee=1.50, tax_percent=5,
                           round_total=True)
        self.assertTrue(r["rounded"])
        self.assertEqual(r["total"], int(r["total"]))
        self.assertEqual(
            round(r["subtotal"] + r["tax"] + r["fees"] + r["tip"], 2),
            r["total"])

    def test_string_inputs_accepted(self):
        r = delivery_order("50", "20", delivery_fee="5", service_fee="2")
        self.assertEqual(r["total"], 67.0)

    def test_negative_delivery_fee_raises(self):
        with self.assertRaises(ValueError):
            delivery_order(50, 20, delivery_fee=-1)

    def test_negative_service_fee_raises(self):
        with self.assertRaises(ValueError):
            delivery_order(50, 20, service_fee=-1)

    def test_non_numeric_fee_raises(self):
        with self.assertRaises(ValueError):
            delivery_order(50, 20, delivery_fee="abc")

    def test_invalid_bill_raises(self):
        with self.assertRaises(ValueError):
            delivery_order(-1, 20, delivery_fee=5)

    def test_invalid_tip_on_raises(self):
        with self.assertRaises(ValueError):
            delivery_order(50, 20, delivery_fee=5, tip_on="midtax")

    def test_invalid_tax_raises(self):
        with self.assertRaises(ValueError):
            delivery_order(50, 20, delivery_fee=5, tax_percent=150)


class CoercePercentSharesTests(unittest.TestCase):
    def test_valid_shares(self):
        self.assertEqual(_coerce_percent_shares([50, 30, 20]),
                         [50.0, 30.0, 20.0])

    def test_string_numbers_coerced(self):
        self.assertEqual(_coerce_percent_shares(["50", "50"]), [50.0, 50.0])

    def test_single_full_share(self):
        self.assertEqual(_coerce_percent_shares([100]), [100.0])

    def test_must_sum_to_100(self):
        with self.assertRaises(ValueError):
            _coerce_percent_shares([50, 40])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            _coerce_percent_shares([])

    def test_entry_over_100_raises(self):
        with self.assertRaises(ValueError):
            _coerce_percent_shares([150, -50])

    def test_negative_entry_raises(self):
        with self.assertRaises(ValueError):
            _coerce_percent_shares([110, -10])

    def test_string_is_not_a_valid_list(self):
        with self.assertRaises(ValueError):
            _coerce_percent_shares("100")

    def test_bool_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_percent_shares([True, 99])

    def test_non_numeric_entry_raises(self):
        with self.assertRaises(ValueError):
            _coerce_percent_shares([50, "abc"])


class SplitByPercentageTests(unittest.TestCase):
    def test_people_count_matches_shares(self):
        r = split_by_percentage(100, 0, [50, 30, 20])
        self.assertEqual(r["people"], 3)
        self.assertEqual(r["percent_shares"], [50.0, 30.0, 20.0])
        self.assertEqual(r["shares"], [50.0, 30.0, 20.0])
        self.assertEqual(r["total"], 100.0)

    def test_tip_apportioned_by_percentage(self):
        # $100, 20% tip -> total 120 split 50/50 -> 60/60, tip 10/10.
        r = split_by_percentage(100, 20, [50, 50])
        self.assertEqual(r["total"], 120.0)
        self.assertEqual(r["shares"], [60.0, 60.0])
        self.assertEqual(r["tip_shares"], [10.0, 10.0])

    def test_shares_and_tip_sum_back(self):
        r = split_by_percentage(123.45, 18, [50, 30, 20], tax_percent=13)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])
        self.assertEqual(round(sum(r["tip_shares"]), 2), r["tip"])

    def test_larger_percent_pays_more(self):
        r = split_by_percentage(300, 0, [70, 30])
        self.assertGreater(r["shares"][0], r["shares"][1])

    def test_zero_percent_person_pays_nothing(self):
        r = split_by_percentage(100, 0, [0, 100])
        self.assertEqual(r["shares"][0], 0.0)
        self.assertEqual(r["shares"][1], 100.0)

    def test_not_summing_to_100_raises(self):
        with self.assertRaises(ValueError):
            split_by_percentage(100, 20, [50, 40])

    def test_empty_shares_raise(self):
        with self.assertRaises(ValueError):
            split_by_percentage(100, 20, [])

    def test_invalid_bill_raises(self):
        with self.assertRaises(ValueError):
            split_by_percentage(-1, 20, [50, 50])


class HttpDeliveryTests(_ServerTestBase):
    def test_delivery_basic(self):
        status, data = self._post(
            "/api/delivery",
            {"bill": 50, "tip_percent": 20, "delivery_fee": 5,
             "service_fee": 2})
        self.assertEqual(status, 200)
        self.assertEqual(data["fees"], 7.0)
        self.assertEqual(data["tip"], 10.0)
        self.assertEqual(data["total"], 67.0)

    def test_delivery_with_tax_and_split(self):
        status, data = self._post(
            "/api/delivery",
            {"bill": 123.45, "tip_percent": 18, "delivery_fee": 4.99,
             "service_fee": 2.50, "people": 3, "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_delivery_tip_ignores_fees(self):
        status, data = self._post(
            "/api/delivery",
            {"bill": 50, "tip_percent": 20, "delivery_fee": 9,
             "service_fee": 6})
        self.assertEqual(status, 200)
        self.assertEqual(data["tip"], 10.0)

    def test_delivery_defaults_fees_to_zero(self):
        status, data = self._post(
            "/api/delivery", {"bill": 50, "tip_percent": 20})
        self.assertEqual(status, 200)
        self.assertEqual(data["fees"], 0.0)
        self.assertEqual(data["total"], 60.0)

    def test_bad_fee_is_400(self):
        status, data = self._post(
            "/api/delivery",
            {"bill": 50, "tip_percent": 20, "delivery_fee": -5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_bill_is_400(self):
        status, data = self._post(
            "/api/delivery", {"tip_percent": 20, "delivery_fee": 5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpPercentSplitTests(_ServerTestBase):
    def test_percent_split_basic(self):
        status, data = self._post(
            "/api/percentsplit",
            {"bill": 100, "tip_percent": 0, "percent_shares": [50, 30, 20]})
        self.assertEqual(status, 200)
        self.assertEqual(data["people"], 3)
        self.assertEqual(data["shares"], [50.0, 30.0, 20.0])

    def test_percent_split_sums_back_with_tax(self):
        status, data = self._post(
            "/api/percentsplit",
            {"bill": 123.45, "tip_percent": 18, "percent_shares": [50, 30, 20],
             "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])
        self.assertEqual(round(sum(data["tip_shares"]), 2), data["tip"])

    def test_not_summing_to_100_is_400(self):
        status, data = self._post(
            "/api/percentsplit",
            {"bill": 100, "tip_percent": 20, "percent_shares": [50, 40]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_percent_shares_is_400(self):
        status, data = self._post(
            "/api/percentsplit", {"bill": 100, "tip_percent": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class SplitByAssignmentTests(unittest.TestCase):
    def test_disjoint_items_charge_each_diner_their_own(self):
        # Person 0 ate the $40 item, person 1 the $60 item; no tax/tip.
        r = split_by_assignment([40, 60], [[0], [1]], 0)
        self.assertEqual(r["people"], 2)
        self.assertEqual(r["subtotal"], 100.0)
        self.assertEqual(r["shares"], [40.0, 60.0])
        self.assertEqual(r["breakdown"][0]["subtotal"], 40.0)
        self.assertEqual(r["breakdown"][1]["subtotal"], 60.0)
        self.assertEqual(r["item_count"], 2)

    def test_shared_item_splits_evenly_among_assignees(self):
        # A $30 appetiser shared by persons 0 and 1 only (person 2 abstains).
        r = split_by_assignment([30], [[0, 1]], 0, people=3)
        self.assertEqual(r["people"], 3)
        self.assertEqual(r["shares"], [15.0, 15.0, 0.0])

    def test_none_entry_shares_item_across_whole_table(self):
        # A None (or empty) assignment means the whole table shares the item.
        r = split_by_assignment([30], [None], 0, people=3)
        self.assertEqual(r["shares"], [10.0, 10.0, 10.0])
        r2 = split_by_assignment([30], [[]], 0, people=3)
        self.assertEqual(r2["shares"], [10.0, 10.0, 10.0])

    def test_people_inferred_from_largest_index(self):
        r = split_by_assignment([10, 20], [[0], [2]], 0)
        self.assertEqual(r["people"], 3)
        self.assertEqual(r["shares"], [10.0, 0.0, 20.0])

    def test_tax_and_tip_apportioned_by_subtotal(self):
        # Person 0: $40, person 1: $60; 20% tip, 10% tax on the $100 bill.
        r = split_by_assignment([40, 60], [[0], [1]], 20, people=2, tax_percent=10)
        self.assertEqual(r["subtotal"], 100.0)
        self.assertEqual(r["tax"], 10.0)
        self.assertEqual(r["tip"], 20.0)
        self.assertEqual(r["total"], 130.0)
        # 40/60 split of a $20 tip and $10 tax.
        self.assertEqual(r["tip_shares"], [8.0, 12.0])
        self.assertEqual(r["breakdown"][0]["tax"], 4.0)
        self.assertEqual(r["breakdown"][1]["tax"], 6.0)

    def test_shares_and_tip_sum_back_exactly(self):
        r = split_by_assignment(
            [12.37, 8.05, 21.99, 5.5],
            [[0], [0, 1], [1, 2], None], 18.5, people=3, tax_percent=8.25)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])
        self.assertEqual(round(sum(r["tip_shares"]), 2), r["tip"])
        self.assertEqual(round(sum(p["subtotal"] for p in r["breakdown"]), 2),
                         r["subtotal"])

    def test_indistinct_indices_are_deduped(self):
        # Repeated indices in one assignment count the diner once.
        r = split_by_assignment([30], [[0, 0, 1]], 0, people=2)
        self.assertEqual(r["assignments"], [[0, 1]])
        self.assertEqual(r["shares"], [15.0, 15.0])

    def test_fully_comped_table_even_tip_split(self):
        # Zero subtotal everywhere -> tip falls back to an even split.
        r = split_by_assignment([0, 0], [[0], [1]], 0, people=2)
        self.assertEqual(r["shares"], [0.0, 0.0])

    def test_index_beyond_people_raises(self):
        with self.assertRaises(ValueError):
            split_by_assignment([10], [[5]], 0, people=2)

    def test_assignments_wrong_length_raises(self):
        with self.assertRaises(ValueError):
            split_by_assignment([10, 20], [[0]], 0)

    def test_non_integer_index_raises(self):
        with self.assertRaises(ValueError):
            split_by_assignment([10], [[1.5]], 0, people=3)

    def test_negative_index_raises(self):
        with self.assertRaises(ValueError):
            split_by_assignment([10], [[-1]], 0, people=2)

    def test_bad_item_amount_raises(self):
        with self.assertRaises(ValueError):
            split_by_assignment([-5], [[0]], 0, people=1)


class HttpAssignTests(_ServerTestBase):
    def test_assign_basic(self):
        status, data = self._post(
            "/api/assign",
            {"items": [40, 60], "assignments": [[0], [1]], "tip_percent": 0})
        self.assertEqual(status, 200)
        self.assertEqual(data["people"], 2)
        self.assertEqual(data["shares"], [40.0, 60.0])

    def test_assign_shared_with_tax_and_tip_sums_back(self):
        status, data = self._post(
            "/api/assign",
            {"items": [25.5, 18.75, 9.99], "assignments": [[0], [1], None],
             "tip_percent": 18, "tax_percent": 13, "people": 2})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])
        self.assertEqual(round(sum(data["tip_shares"]), 2), data["tip"])

    def test_assign_infers_people(self):
        status, data = self._post(
            "/api/assign",
            {"items": [10, 20], "assignments": [[0], [2]], "tip_percent": 0})
        self.assertEqual(status, 200)
        self.assertEqual(data["people"], 3)

    def test_assign_index_out_of_range_is_400(self):
        status, data = self._post(
            "/api/assign",
            {"items": [10], "assignments": [[3]], "tip_percent": 0, "people": 2})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_assign_missing_assignments_is_400(self):
        status, data = self._post(
            "/api/assign", {"items": [10, 20], "tip_percent": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class HttpCouponsTests(_ServerTestBase):
    def test_coupons_stack(self):
        status, data = self._post(
            "/api/coupons",
            {"bill": 100, "tip_percent": 0,
             "coupons": [{"kind": "percent", "value": 50},
                         {"kind": "percent", "value": 50}]})
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 25.0)
        self.assertEqual(data["total_discount"], 75.0)
        self.assertEqual(len(data["coupons_applied"]), 2)

    def test_coupons_with_tax_tip_split_sums_back(self):
        status, data = self._post(
            "/api/coupons",
            {"bill": 123.45, "tip_percent": 18, "tax_percent": 13, "people": 3,
             "coupons": [{"kind": "amount", "value": 10},
                         {"kind": "percent", "value": 5}]})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_coupons_empty_is_400(self):
        status, data = self._post(
            "/api/coupons", {"bill": 100, "tip_percent": 0, "coupons": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_coupons_missing_is_400(self):
        status, data = self._post(
            "/api/coupons", {"bill": 100, "tip_percent": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_coupons_bad_percent_is_400(self):
        status, data = self._post(
            "/api/coupons",
            {"bill": 100, "tip_percent": 0,
             "coupons": [{"kind": "percent", "value": 150}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class CoerceBillEntriesTests(unittest.TestCase):
    def test_normalises_and_fills_defaults(self):
        entries = _coerce_bill_entries([{"bill": 50, "tip_percent": 20}])
        self.assertEqual(len(entries), 1)
        e = entries[0]
        self.assertEqual(e["bill"], 50)
        self.assertEqual(e["tip_percent"], 20)
        self.assertEqual(e["tax_percent"], 0)
        self.assertEqual(e["people"], 1)
        self.assertEqual(e["tip_on"], "pretax")
        self.assertEqual(e["round_total"], False)
        self.assertEqual(e["label"], "Bill 1")

    def test_keeps_explicit_label_and_fields(self):
        entries = _coerce_bill_entries([
            {"bill": 80, "tip_percent": 18, "tax_percent": 8,
             "people": 4, "tip_on": "posttax", "round_total": True,
             "label": "Dinner"},
        ])
        e = entries[0]
        self.assertEqual(e["label"], "Dinner")
        self.assertEqual(e["tax_percent"], 8)
        self.assertEqual(e["people"], 4)
        self.assertEqual(e["tip_on"], "posttax")
        self.assertEqual(e["round_total"], True)

    def test_default_labels_are_one_indexed(self):
        entries = _coerce_bill_entries([
            {"bill": 10, "tip_percent": 10},
            {"bill": 20, "tip_percent": 20},
        ])
        self.assertEqual([e["label"] for e in entries], ["Bill 1", "Bill 2"])

    def test_rejects_non_list(self):
        with self.assertRaises(ValueError):
            _coerce_bill_entries("nope")

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            _coerce_bill_entries([])

    def test_rejects_non_object_entry(self):
        with self.assertRaises(ValueError):
            _coerce_bill_entries([[50, 20]])


class SummarizeBillsTests(unittest.TestCase):
    def test_single_bill_matches_calculate_bill(self):
        s = summarize_bills([{"bill": 100, "tip_percent": 20}])
        self.assertEqual(s["count"], 1)
        self.assertEqual(s["total_subtotal"], 100.0)
        self.assertEqual(s["total_tip"], 20.0)
        self.assertEqual(s["total"], 120.0)
        self.assertEqual(s["average_subtotal"], 100.0)
        self.assertEqual(s["average_tip"], 20.0)
        self.assertEqual(s["average_total"], 120.0)
        self.assertEqual(s["average_tip_percent"], 20.0)

    def test_totals_sum_across_bills(self):
        s = summarize_bills([
            {"bill": 100, "tip_percent": 20},
            {"bill": 50, "tip_percent": 10},
        ])
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["total_subtotal"], 150.0)
        self.assertEqual(s["total_tip"], 25.0)   # 20 + 5
        self.assertEqual(s["total"], 175.0)
        self.assertEqual(s["average_subtotal"], 75.0)
        self.assertEqual(s["average_tip"], 12.5)
        self.assertEqual(s["average_total"], 87.5)

    def test_blended_rate_weights_by_subtotal(self):
        # A big 20% bill and a small 0% bill: the blended rate is the dollar-
        # weighted figure (20 / 110), NOT the simple mean of 20% and 0%.
        s = summarize_bills([
            {"bill": 100, "tip_percent": 20},
            {"bill": 10, "tip_percent": 0},
        ])
        self.assertEqual(s["total_tip"], 20.0)
        self.assertEqual(s["total_subtotal"], 110.0)
        self.assertAlmostEqual(s["average_tip_percent"], 20.0 / 110.0 * 100.0,
                               places=2)

    def test_min_max_and_extremes(self):
        s = summarize_bills([
            {"bill": 30, "tip_percent": 25},
            {"bill": 120, "tip_percent": 15},
            {"bill": 75, "tip_percent": 18},
        ])
        self.assertEqual(s["min_tip_percent"], 15.0)
        self.assertEqual(s["max_tip_percent"], 25.0)
        self.assertEqual(s["largest_bill"], 120.0)
        self.assertEqual(s["smallest_bill"], 30.0)

    def test_includes_tax_in_totals(self):
        s = summarize_bills([
            {"bill": 100, "tip_percent": 20, "tax_percent": 10},
        ])
        self.assertEqual(s["total_tax"], 10.0)
        self.assertEqual(s["total"], 130.0)   # 100 + 10 tax + 20 tip

    def test_per_bill_breakdown_shape(self):
        s = summarize_bills([
            {"bill": 40, "tip_percent": 15, "label": "Lunch", "people": 2},
        ])
        self.assertEqual(len(s["bills"]), 1)
        row = s["bills"][0]
        self.assertEqual(row["label"], "Lunch")
        self.assertEqual(row["subtotal"], 40.0)
        self.assertEqual(row["tip"], 6.0)
        self.assertEqual(row["total"], 46.0)
        self.assertEqual(row["people"], 2)
        self.assertEqual(row["tip_percent"], 15.0)

    def test_grand_total_equals_sum_of_per_bill_totals(self):
        s = summarize_bills([
            {"bill": 19.99, "tip_percent": 18, "tax_percent": 7},
            {"bill": 33.33, "tip_percent": 22},
            {"bill": 5.55, "tip_percent": 10},
        ])
        self.assertEqual(round(sum(b["total"] for b in s["bills"]), 2),
                         s["total"])
        self.assertEqual(round(sum(b["tip"] for b in s["bills"]), 2),
                         s["total_tip"])

    def test_invalid_bill_propagates_value_error(self):
        with self.assertRaises(ValueError):
            summarize_bills([{"bill": -5, "tip_percent": 20}])

    def test_invalid_tip_percent_propagates_value_error(self):
        with self.assertRaises(ValueError):
            summarize_bills([{"bill": 50, "tip_percent": 200}])

    def test_empty_list_raises(self):
        with self.assertRaises(ValueError):
            summarize_bills([])


class HttpSummaryTests(_ServerTestBase):
    def test_summary_basic(self):
        status, data = self._post("/api/summary", {"bills": [
            {"bill": 100, "tip_percent": 20},
            {"bill": 50, "tip_percent": 10},
        ]})
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["total_subtotal"], 150.0)
        self.assertEqual(data["total_tip"], 25.0)
        self.assertEqual(data["total"], 175.0)
        self.assertEqual(len(data["bills"]), 2)

    def test_summary_reports_spread(self):
        status, data = self._post("/api/summary", {"bills": [
            {"bill": 30, "tip_percent": 25, "label": "Brunch"},
            {"bill": 120, "tip_percent": 15},
        ]})
        self.assertEqual(status, 200)
        self.assertEqual(data["min_tip_percent"], 15.0)
        self.assertEqual(data["max_tip_percent"], 25.0)
        self.assertEqual(data["bills"][0]["label"], "Brunch")
        self.assertEqual(data["bills"][1]["label"], "Bill 2")

    def test_summary_missing_bills_is_400(self):
        status, data = self._post("/api/summary", {})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_summary_empty_bills_is_400(self):
        status, data = self._post("/api/summary", {"bills": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_summary_invalid_entry_is_400(self):
        status, data = self._post(
            "/api/summary", {"bills": [{"bill": -1, "tip_percent": 20}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class CoerceTipoutsTests(unittest.TestCase):
    def test_normalises_roles_and_percents(self):
        out = _coerce_tipouts([
            {"role": "busser", "percent": 3},
            {"role": "bartender", "percent": 1.5},
        ])
        self.assertEqual(out, [
            {"role": "busser", "percent": 3.0},
            {"role": "bartender", "percent": 1.5},
        ])

    def test_missing_role_gets_default_label(self):
        out = _coerce_tipouts([{"percent": 2}, {"percent": 1}])
        self.assertEqual(out[0]["role"], "support 1")
        self.assertEqual(out[1]["role"], "support 2")

    def test_blank_role_falls_back_to_default(self):
        out = _coerce_tipouts([{"role": "   ", "percent": 2}])
        self.assertEqual(out[0]["role"], "support 1")

    def test_role_is_stripped(self):
        out = _coerce_tipouts([{"role": "  runner ", "percent": 1}])
        self.assertEqual(out[0]["role"], "runner")

    def test_non_list_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_tipouts("busser 3")

    def test_empty_list_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_tipouts([])

    def test_non_dict_entry_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_tipouts([["busser", 3]])

    def test_missing_percent_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_tipouts([{"role": "busser"}])

    def test_out_of_range_percent_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_tipouts([{"role": "busser", "percent": 150}])


class DistributeTipoutTests(unittest.TestCase):
    def test_percent_of_sales_default(self):
        out = distribute_tipout(1000, 200, [
            {"role": "busser", "percent": 3},
            {"role": "bartender", "percent": 1},
        ])
        self.assertEqual(out["basis"], "sales")
        self.assertEqual(out["tipouts"][0]["amount"], 30.0)
        self.assertEqual(out["tipouts"][1]["amount"], 10.0)
        self.assertEqual(out["total_tipout"], 40.0)
        self.assertEqual(out["server_keep"], 160.0)

    def test_percent_of_tips_basis(self):
        out = distribute_tipout(1000, 200, [
            {"role": "busser", "percent": 10},
        ], basis="tips")
        self.assertEqual(out["basis"], "tips")
        self.assertEqual(out["tipouts"][0]["amount"], 20.0)
        self.assertEqual(out["server_keep"], 180.0)

    def test_payouts_and_keep_sum_to_tips(self):
        out = distribute_tipout(723.45, 137.80, [
            {"role": "busser", "percent": 3.3},
            {"role": "bar", "percent": 1.7},
            {"role": "runner", "percent": 0.9},
        ])
        paid = sum(t["amount"] for t in out["tipouts"])
        self.assertAlmostEqual(paid + out["server_keep"], out["tip_total"], places=2)
        self.assertAlmostEqual(out["total_tipout"], paid, places=2)

    def test_keep_percent_reported(self):
        out = distribute_tipout(1000, 200, [{"role": "b", "percent": 5}])
        # 5% of 1000 = 50 tipped out, keep 150 of 200 = 75%.
        self.assertEqual(out["server_keep"], 150.0)
        self.assertEqual(out["server_keep_percent"], 75.0)

    def test_zero_tips_keep_percent_is_zero(self):
        out = distribute_tipout(1000, 0, [{"role": "b", "percent": 0}])
        self.assertEqual(out["server_keep"], 0.0)
        self.assertEqual(out["server_keep_percent"], 0.0)

    def test_tipout_exceeding_tips_rejected(self):
        with self.assertRaises(ValueError):
            distribute_tipout(1000, 20, [{"role": "busser", "percent": 5}])

    def test_negative_sales_rejected(self):
        with self.assertRaises(ValueError):
            distribute_tipout(-1, 100, [{"role": "b", "percent": 1}])

    def test_negative_tips_rejected(self):
        with self.assertRaises(ValueError):
            distribute_tipout(1000, -1, [{"role": "b", "percent": 1}])

    def test_non_numeric_sales_rejected(self):
        with self.assertRaises(ValueError):
            distribute_tipout("lots", 100, [{"role": "b", "percent": 1}])

    def test_bad_basis_rejected(self):
        with self.assertRaises(ValueError):
            distribute_tipout(1000, 100, [{"role": "b", "percent": 1}],
                              basis="profit")

    def test_basis_in_tipout_bases(self):
        self.assertIn("sales", TIPOUT_BASES)
        self.assertIn("tips", TIPOUT_BASES)


class HttpTipoutTests(_ServerTestBase):
    def test_basic_tipout(self):
        status, data = self._post("/api/tipout", {
            "sales": 1000, "tip_total": 200,
            "tipouts": [{"role": "busser", "percent": 3}],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["total_tipout"], 30.0)
        self.assertEqual(data["server_keep"], 170.0)

    def test_tips_basis(self):
        status, data = self._post("/api/tipout", {
            "sales": 1000, "tip_total": 200, "basis": "tips",
            "tipouts": [{"role": "busser", "percent": 25}],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["tipouts"][0]["amount"], 50.0)
        self.assertEqual(data["server_keep"], 150.0)

    def test_excessive_tipout_is_400(self):
        status, data = self._post("/api/tipout", {
            "sales": 1000, "tip_total": 10,
            "tipouts": [{"role": "busser", "percent": 5}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_tipouts_is_400(self):
        status, data = self._post("/api/tipout", {
            "sales": 1000, "tip_total": 200})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_invalid_basis_is_400(self):
        status, data = self._post("/api/tipout", {
            "sales": 1000, "tip_total": 200, "basis": "nope",
            "tipouts": [{"role": "b", "percent": 1}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class CoerceTaxCategoriesTests(unittest.TestCase):
    def test_normalises_amounts_and_percents(self):
        out = _coerce_tax_categories([
            {"name": "Food", "amount": "80", "tax_percent": "8"},
            {"name": "Bar", "amount": 20, "tax_percent": 18},
        ])
        self.assertEqual(out, [("Food", 80.0, 8.0), ("Bar", 20.0, 18.0)])

    def test_missing_name_gets_default_label(self):
        out = _coerce_tax_categories([
            {"amount": 50, "tax_percent": 8},
            {"amount": 10, "tax_percent": 18},
        ])
        self.assertEqual(out[0][0], "Category 1")
        self.assertEqual(out[1][0], "Category 2")

    def test_zero_tax_allowed(self):
        out = _coerce_tax_categories([{"amount": 30, "tax_percent": 0}])
        self.assertEqual(out, [("Category 1", 30.0, 0.0)])

    def test_non_list_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_tax_categories("Food 80 8")

    def test_string_is_not_a_list(self):
        with self.assertRaises(ValueError):
            _coerce_tax_categories("nope")

    def test_empty_list_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_tax_categories([])

    def test_non_dict_entry_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_tax_categories([[80, 8]])

    def test_missing_amount_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_tax_categories([{"tax_percent": 8}])

    def test_missing_tax_percent_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_tax_categories([{"amount": 80}])

    def test_negative_amount_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_tax_categories([{"amount": -5, "tax_percent": 8}])

    def test_out_of_range_tax_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_tax_categories([{"amount": 80, "tax_percent": 150}])

    def test_boolean_amount_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_tax_categories([{"amount": True, "tax_percent": 8}])

    def test_non_numeric_amount_rejected(self):
        with self.assertRaises(ValueError):
            _coerce_tax_categories([{"amount": "lots", "tax_percent": 8}])


class MultiRateTaxBillTests(unittest.TestCase):
    def test_per_category_tax_summed(self):
        # Food 80 @ 8% -> 6.40 tax; Bar 20 @ 18% -> 3.60 tax; total tax 10.00.
        out = multi_rate_tax_bill(
            [{"name": "Food", "amount": 80, "tax_percent": 8},
             {"name": "Bar", "amount": 20, "tax_percent": 18}],
            tip_percent=20)
        self.assertEqual(out["subtotal"], 100.0)
        self.assertEqual(out["tax"], 10.0)
        self.assertEqual(out["tip"], 20.0)  # 20% of pre-tax 100
        self.assertEqual(out["total"], 130.0)

    def test_per_category_breakdown_shape(self):
        out = multi_rate_tax_bill(
            [{"name": "Food", "amount": 80, "tax_percent": 8},
             {"name": "Bar", "amount": 20, "tax_percent": 18}],
            tip_percent=20)
        self.assertEqual(out["categories"], [
            {"name": "Food", "amount": 80.0, "tax_percent": 8.0, "tax": 6.4},
            {"name": "Bar", "amount": 20.0, "tax_percent": 18.0, "tax": 3.6},
        ])

    def test_blended_tax_rate_reported(self):
        # 10.00 tax on 100.00 subtotal -> 10% effective blended rate.
        out = multi_rate_tax_bill(
            [{"name": "Food", "amount": 80, "tax_percent": 8},
             {"name": "Bar", "amount": 20, "tax_percent": 18}],
            tip_percent=20)
        self.assertEqual(out["tax_percent"], 10.0)

    def test_posttax_tip_base(self):
        # Tip on post-tax 110.00 at 20% -> 22.00 instead of 20.00.
        out = multi_rate_tax_bill(
            [{"name": "Food", "amount": 80, "tax_percent": 8},
             {"name": "Bar", "amount": 20, "tax_percent": 18}],
            tip_percent=20, tip_on="posttax")
        self.assertEqual(out["tip"], 22.0)
        self.assertEqual(out["total"], 132.0)
        self.assertEqual(out["tip_on"], "posttax")

    def test_shares_sum_back_to_total(self):
        out = multi_rate_tax_bill(
            [{"amount": 33.33, "tax_percent": 8},
             {"amount": 11.11, "tax_percent": 18}],
            tip_percent=17, people=3)
        self.assertEqual(round(sum(out["shares"]), 2), out["total"])
        self.assertEqual(len(out["shares"]), 3)

    def test_round_total_absorbs_into_tip(self):
        out = multi_rate_tax_bill(
            [{"amount": 80, "tax_percent": 8},
             {"amount": 20, "tax_percent": 18}],
            tip_percent=19, round_total=True)
        self.assertEqual(out["total"], float(int(out["total"])))
        self.assertTrue(out["rounded"])
        self.assertEqual(out["subtotal"] + out["tax"] + out["tip"], out["total"])

    def test_single_category_matches_calculate_bill(self):
        # One category at one rate must equal the flat calculate_bill result.
        flat = calculate_bill(100, 20, tax_percent=8)
        multi = multi_rate_tax_bill(
            [{"amount": 100, "tax_percent": 8}], tip_percent=20)
        self.assertEqual(multi["subtotal"], flat["subtotal"])
        self.assertEqual(multi["tax"], flat["tax"])
        self.assertEqual(multi["tip"], flat["tip"])
        self.assertEqual(multi["total"], flat["total"])

    def test_zero_tax_categories(self):
        out = multi_rate_tax_bill(
            [{"amount": 50, "tax_percent": 0},
             {"amount": 50, "tax_percent": 0}],
            tip_percent=20)
        self.assertEqual(out["tax"], 0.0)
        self.assertEqual(out["tax_percent"], 0.0)
        self.assertEqual(out["total"], 120.0)

    def test_invalid_tip_percent_raises(self):
        with self.assertRaises(ValueError):
            multi_rate_tax_bill(
                [{"amount": 80, "tax_percent": 8}], tip_percent=150)

    def test_bad_tip_on_raises(self):
        with self.assertRaises(ValueError):
            multi_rate_tax_bill(
                [{"amount": 80, "tax_percent": 8}], tip_percent=20,
                tip_on="midtax")

    def test_empty_categories_raises(self):
        with self.assertRaises(ValueError):
            multi_rate_tax_bill([], tip_percent=20)

    def test_too_many_people_raises(self):
        with self.assertRaises(ValueError):
            multi_rate_tax_bill(
                [{"amount": 80, "tax_percent": 8}], tip_percent=20,
                people=10001)


class HttpMultiTaxTests(_ServerTestBase):
    def test_basic_multitax(self):
        status, data = self._post("/api/multitax", {
            "categories": [
                {"name": "Food", "amount": 80, "tax_percent": 8},
                {"name": "Bar", "amount": 20, "tax_percent": 18},
            ],
            "tip_percent": 20,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 100.0)
        self.assertEqual(data["tax"], 10.0)
        self.assertEqual(data["total"], 130.0)
        self.assertEqual(len(data["categories"]), 2)

    def test_multitax_split_per_person(self):
        status, data = self._post("/api/multitax", {
            "categories": [
                {"amount": 80, "tax_percent": 8},
                {"amount": 20, "tax_percent": 18},
            ],
            "tip_percent": 20, "people": 4,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["people"], 4)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_multitax_missing_categories_is_400(self):
        status, data = self._post("/api/multitax", {"tip_percent": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_multitax_empty_categories_is_400(self):
        status, data = self._post("/api/multitax", {
            "categories": [], "tip_percent": 20})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_multitax_bad_tax_percent_is_400(self):
        status, data = self._post("/api/multitax", {
            "categories": [{"amount": 80, "tax_percent": 999}],
            "tip_percent": 20,
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_multitax_missing_tip_is_400(self):
        status, data = self._post("/api/multitax", {
            "categories": [{"amount": 80, "tax_percent": 8}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class SplitItemsCustomTipsTests(unittest.TestCase):
    def test_each_diner_own_items_and_own_tip(self):
        # Person A ordered $40 and tips 25%; person B ordered $60 and tips 10%.
        r = split_items_custom_tips([40, 60], [25, 10])
        self.assertEqual(r["subtotal"], 100.0)
        self.assertEqual(r["per_person"][0]["subtotal"], 40.0)
        self.assertEqual(r["per_person"][0]["tip"], 10.0)   # 25% of 40
        self.assertEqual(r["per_person"][1]["subtotal"], 60.0)
        self.assertEqual(r["per_person"][1]["tip"], 6.0)    # 10% of 60
        self.assertEqual(r["tip"], 16.0)
        self.assertEqual(r["total"], 116.0)

    def test_item_lists_are_summed_per_person(self):
        r = split_items_custom_tips([[10, 5], [20]], [20, 20])
        self.assertEqual(r["per_person"][0]["subtotal"], 15.0)
        self.assertEqual(r["per_person"][1]["subtotal"], 20.0)
        self.assertEqual(r["subtotal"], 35.0)

    def test_shares_and_tip_shares_sum_back(self):
        r = split_items_custom_tips([[12.50, 3.25], [9.99], [20.00, 5.00]],
                                    [18, 20, 15], tax_percent=13)
        self.assertEqual(round(sum(r["shares"]), 2), r["total"])
        self.assertEqual(round(sum(r["tip_shares"]), 2), r["tip"])
        for p in r["per_person"]:
            self.assertEqual(
                round(p["subtotal"] + p["tax"] + p["tip"], 2), p["total"])

    def test_tax_apportioned_by_subtotal_share(self):
        # $40 / $60 with 10% tax ($10) -> tax split 4 / 6 by what each ordered.
        r = split_items_custom_tips([40, 60], [0, 0], tax_percent=10)
        self.assertEqual(r["tax"], 10.0)
        self.assertEqual(r["per_person"][0]["tax"], 4.0)
        self.assertEqual(r["per_person"][1]["tax"], 6.0)

    def test_posttax_tip_uses_own_taxed_share(self):
        # Person A: $40 + $4 tax = $44 base; 25% tip -> $11.
        r = split_items_custom_tips([40, 60], [25, 10], tax_percent=10,
                                    tip_on="posttax")
        self.assertEqual(r["tip_on"], "posttax")
        self.assertEqual(r["per_person"][0]["tip"], 11.0)
        self.assertEqual(r["per_person"][1]["tip"], 6.6)  # 10% of (60+6)

    def test_fully_comped_table_zero_tips(self):
        r = split_items_custom_tips([0, 0], [20, 15])
        self.assertEqual(r["total"], 0.0)
        self.assertEqual(r["tip"], 0.0)
        self.assertEqual(r["shares"], [0.0, 0.0])

    def test_mismatched_lengths_raise(self):
        with self.assertRaises(ValueError):
            split_items_custom_tips([40, 60], [20])

    def test_empty_items_raise(self):
        with self.assertRaises(ValueError):
            split_items_custom_tips([], [20])

    def test_negative_item_raises(self):
        with self.assertRaises(ValueError):
            split_items_custom_tips([40, -5], [20, 20])

    def test_non_list_items_raise(self):
        with self.assertRaises(ValueError):
            split_items_custom_tips("40,60", [20, 20])

    def test_out_of_range_tip_percent_raises(self):
        with self.assertRaises(ValueError):
            split_items_custom_tips([40, 60], [20, 150])

    def test_bad_tax_raises(self):
        with self.assertRaises(ValueError):
            split_items_custom_tips([40, 60], [20, 10], tax_percent=150)

    def test_invalid_tip_on_raises(self):
        with self.assertRaises(ValueError):
            split_items_custom_tips([40, 60], [20, 10], tip_on="midtax")


class HttpItemTipsTests(_ServerTestBase):
    def test_item_tips_basic(self):
        status, data = self._post(
            "/api/itemtips", {"items": [40, 60], "tip_percents": [25, 10]})
        self.assertEqual(status, 200)
        self.assertEqual(data["subtotal"], 100.0)
        self.assertEqual(data["per_person"][0]["tip"], 10.0)
        self.assertEqual(data["per_person"][1]["tip"], 6.0)
        self.assertEqual(data["total"], 116.0)

    def test_item_tips_with_tax_sum_back(self):
        status, data = self._post(
            "/api/itemtips",
            {"items": [[12.5, 3.25], [9.99]], "tip_percents": [18, 20],
             "tax_percent": 13})
        self.assertEqual(status, 200)
        self.assertEqual(round(sum(data["shares"]), 2), data["total"])

    def test_item_tips_mismatch_is_400(self):
        status, data = self._post(
            "/api/itemtips", {"items": [40, 60], "tip_percents": [20]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_item_tips_missing_items_is_400(self):
        status, data = self._post("/api/itemtips", {"tip_percents": [20]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
