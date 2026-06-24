"""tip-calculator-enter-bill-2

A tip calculator: enter a bill amount and tip percent, show the tip and total,
split by number of people. Pure Python 3 standard library only.

Run:  python3 server.py   ->  http://127.0.0.1:8000
"""

import json
import math
import os
import http.server
import socketserver


def _to_cents(amount):
    """Convert a currency amount (float/str) to integer cents, rounding to the
    nearest cent. Using integer cents avoids floating-point drift when we split
    a bill so the per-person shares always sum back to the exact total."""
    return int(round(float(amount) * 100))


def _from_cents(cents):
    """Convert integer cents back to a 2-decimal float dollar amount."""
    return round(cents / 100.0, 2)


def split_amount(total_cents, people):
    """Split an integer number of cents fairly across `people`.

    Each person gets total_cents // people, and the leftover remainder cents are
    handed out one at a time to the first `remainder` people. This guarantees
    the shares sum back exactly to total_cents and that any two shares differ by
    at most one cent (the fairest possible integer split).

    Returns a list of integer cents of length `people`.
    """
    base = total_cents // people
    remainder = total_cents % people
    return [base + (1 if i < remainder else 0) for i in range(people)]


def calculate(bill, tip_percent, people=1, round_total=False):
    """Core domain logic for the tip calculator.

    Validates inputs, computes the tip and total, and splits the total (and the
    tip) fairly across the given number of people.

    When `round_total` is truthy the grand total is rounded UP to the next whole
    dollar and the extra cents are absorbed into the tip (a common "round up the
    bill" convenience). The shares still sum back exactly to the rounded total.

    Raises ValueError on any invalid input.

    Returns a dict with: tip, total, people, per_person (the total each person
    pays), per_person_tip (the tip portion each person covers), shares (the full
    per-person breakdown so the UI can show exact, summing amounts), and
    rounded (whether the round-up adjustment was applied).
    """
    # Same bounds/coercion as every richer endpoint — reuse the one validator so
    # the two code paths can never disagree about what a valid input is.
    bill_cents, tip_percent, people = _validate_common(bill, tip_percent, people)
    tip_cents = int(round(bill_cents * tip_percent / 100.0))
    total_cents = bill_cents + tip_cents

    rounded = bool(round_total)
    if rounded:
        # Round the grand total up to the next whole dollar; the extra cents are
        # added to the tip so bill + tip == total still holds exactly.
        bumped = int(math.ceil(total_cents / 100.0)) * 100
        tip_cents += bumped - total_cents
        total_cents = bumped

    total_shares = split_amount(total_cents, people)
    tip_shares = split_amount(tip_cents, people)

    return {
        "bill": _from_cents(bill_cents),
        "tip_percent": round(tip_percent, 4),
        "tip": _from_cents(tip_cents),
        "total": _from_cents(total_cents),
        "people": people,
        "per_person": _from_cents(total_shares[0]),
        "per_person_tip": _from_cents(tip_shares[0]),
        "shares": [_from_cents(c) for c in total_shares],
        "rounded": rounded,
    }


# Common tip percentages offered as quick-pick suggestions in the UI.
DEFAULT_PRESET_PERCENTS = (15, 18, 20, 25)


def _coerce_percents(percents):
    """Validate and normalise a caller-supplied list of preset percentages.

    Accepts any non-empty iterable of numbers in the 0..100 range (the same
    bounds `calculate` enforces) and returns them as a plain list. Falls back to
    DEFAULT_PRESET_PERCENTS when `percents` is None so existing callers and the
    default UI behaviour are unchanged. Raises ValueError on anything invalid so
    the API surfaces a clean 400 rather than a 500.
    """
    if percents is None:
        return list(DEFAULT_PRESET_PERCENTS)
    if isinstance(percents, (str, bytes)) or not isinstance(percents, (list, tuple)):
        raise ValueError("percents must be a list of numbers")
    if not percents:
        raise ValueError("percents must not be empty")
    cleaned = []
    for pct in percents:
        try:
            value = float(pct)
        except (TypeError, ValueError):
            raise ValueError("percents must be a list of numbers")
        if value != value or value < 0 or value > 100:  # NaN or out of range
            raise ValueError("percents must be between 0 and 100")
        cleaned.append(value)
    return cleaned


def suggest_tips(bill, people=1, percents=DEFAULT_PRESET_PERCENTS):
    """Return a list of tip suggestions for `bill` at each preset percentage.

    Each entry reuses `calculate`, so it carries the same fair-split guarantees.
    `percents` may be the default tuple, an explicit caller-supplied list, or
    None (which falls back to the defaults). Raises ValueError on any invalid
    bill / people / percents input.
    """
    percents = _coerce_percents(percents)
    suggestions = []
    for pct in percents:
        result = calculate(bill, pct, people)
        suggestions.append({
            "tip_percent": result["tip_percent"],
            "tip": result["tip"],
            "total": result["total"],
            "per_person": result["per_person"],
        })
    return suggestions


def _validate_common(bill, tip_percent, people):
    """Validate and normalise the bill / tip_percent / people trio shared by the
    richer bill endpoints, returning (bill_cents, tip_percent_float, people_int).

    Mirrors the exact bounds and coercion rules `calculate` enforces so the two
    code paths can never disagree about what a valid input is. Raises ValueError
    on any invalid input.
    """
    if bill is None or tip_percent is None:
        raise ValueError("bill and tip_percent are required")
    try:
        bill = float(bill)
        tip_percent = float(tip_percent)
    except (TypeError, ValueError):
        raise ValueError("bill and tip_percent must be numbers")

    if people is None:
        people = 1
    try:
        people_f = float(people)
    except (TypeError, ValueError):
        raise ValueError("people must be a whole number")
    if people_f != int(people_f):
        raise ValueError("people must be a whole number")
    people = int(people_f)

    if bill != bill or tip_percent != tip_percent:  # NaN check
        raise ValueError("bill and tip_percent must be numbers")
    if bill < 0:
        raise ValueError("bill must be non-negative")
    if tip_percent < 0 or tip_percent > 100:
        raise ValueError("tip_percent must be between 0 and 100")
    if people < 1:
        raise ValueError("people must be at least 1")

    return _to_cents(bill), tip_percent, people


def _coerce_percent(value, name):
    """Validate a 0..100 percentage and return it as a float.

    The single source of truth for every percentage input (tax, service,
    surcharge, …): coerces to float, rejects NaN, and enforces the 0..100 bounds,
    naming the offending field in the error so each endpoint reports its own key.
    Raises ValueError on anything invalid so the API surfaces a clean 400 rather
    than a 500.
    """
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number" % name)
    if value != value:  # NaN
        raise ValueError("%s must be a number" % name)
    if value < 0 or value > 100:
        raise ValueError("%s must be between 0 and 100" % name)
    return value


def _coerce_tax(tax_percent):
    """Validate a sales-tax percentage (0..100) and return it as a float.

    Shared by every endpoint that adds tax so the bounds and error messages can
    never drift apart between code paths. Raises ValueError on anything invalid
    so the API surfaces a clean 400 rather than a 500.
    """
    return _coerce_percent(tax_percent, "tax_percent")


def _breakdown(bill_cents, tip_cents, tax_cents, total_cents, people,
               tip_percent, tax_percent, tip_on, extra=None):
    """Build the standard per-person bill breakdown shared by every bill endpoint.

    Splits the total, the tip, and the tax fairly across `people` with
    `split_amount` and reports both the per-person figures and the full share
    lists, so no two endpoints can disagree on the common shape or the rounding.
    `extra` merges in endpoint-specific keys (a service charge, a target total, a
    rounding mode, …). Returns the breakdown dict.
    """
    total_shares = split_amount(total_cents, people)
    tip_shares = split_amount(tip_cents, people)
    tax_shares = split_amount(tax_cents, people)
    out = {
        "subtotal": _from_cents(bill_cents),
        "tax": _from_cents(tax_cents),
        "tax_percent": round(tax_percent, 4),
        "tip": _from_cents(tip_cents),
        "tip_percent": round(tip_percent, 4),
        "total": _from_cents(total_cents),
        "people": people,
        "per_person": _from_cents(total_shares[0]),
        "per_person_tip": _from_cents(tip_shares[0]),
        "per_person_tax": _from_cents(tax_shares[0]),
        "shares": [_from_cents(c) for c in total_shares],
        "tip_on": tip_on,
    }
    if extra:
        out.update(extra)
    return out


# Where the tip is computed from: the pre-tax bill (the common etiquette) or the
# post-tax amount (tax included in the tip base).
TIP_BASES = ("pretax", "posttax")


def calculate_bill(bill, tip_percent, people=1, tax_percent=0,
                   round_total=False, tip_on="pretax"):
    """Full restaurant-bill breakdown: subtotal + sales tax + tip, split fairly.

    Extends `calculate` with a `tax_percent` so the result separates the pre-tax
    subtotal, the tax, and the tip. `tip_on` chooses whether the tip is figured
    on the pre-tax subtotal ("pretax", the default and common etiquette) or on
    the post-tax amount ("posttax").

    When `round_total` is truthy the grand total is rounded UP to the next whole
    dollar and the extra cents are absorbed into the tip, exactly as in
    `calculate`. Every per-person breakdown (total, tip, tax) is produced with
    `split_amount`, so each one sums back exactly to its whole.

    Raises ValueError on any invalid input. Returns a dict with: subtotal, tax,
    tax_percent, tip, tip_percent, total, people, per_person, per_person_tip,
    per_person_tax, shares, tip_on, and rounded.
    """
    bill_cents, tip_percent, people = _validate_common(bill, tip_percent, people)
    tax_percent = _coerce_tax(tax_percent)

    if tip_on not in TIP_BASES:
        raise ValueError("tip_on must be 'pretax' or 'posttax'")

    tax_cents = int(round(bill_cents * tax_percent / 100.0))
    tip_base = bill_cents if tip_on == "pretax" else bill_cents + tax_cents
    tip_cents = int(round(tip_base * tip_percent / 100.0))
    total_cents = bill_cents + tax_cents + tip_cents

    rounded = bool(round_total)
    if rounded:
        bumped = int(math.ceil(total_cents / 100.0)) * 100
        tip_cents += bumped - total_cents
        total_cents = bumped

    return _breakdown(bill_cents, tip_cents, tax_cents, total_cents, people,
                      tip_percent, tax_percent, tip_on,
                      extra={"rounded": rounded})


def _coerce_weights(weights):
    """Validate a caller-supplied list of split weights and return them as floats.

    Weights describe an UNEVEN split — e.g. [2, 1, 1] means the first person
    covers half. Accepts any non-empty list/tuple of non-negative numbers whose
    sum is positive. Raises ValueError on anything invalid so the API returns a
    clean 400.
    """
    if isinstance(weights, (str, bytes)) or not isinstance(weights, (list, tuple)):
        raise ValueError("weights must be a list of numbers")
    if not weights:
        raise ValueError("weights must not be empty")
    cleaned = []
    for w in weights:
        try:
            value = float(w)
        except (TypeError, ValueError):
            raise ValueError("weights must be a list of numbers")
        if value != value or value < 0:  # NaN or negative
            raise ValueError("weights must be non-negative")
        cleaned.append(value)
    if sum(cleaned) <= 0:
        raise ValueError("weights must sum to a positive amount")
    return cleaned


def split_weighted(total_cents, weights):
    """Split integer cents across people in proportion to `weights`.

    Uses the largest-remainder (Hamilton) method: each person gets the floor of
    their ideal proportional share, then the leftover cents are handed to the
    people with the largest fractional remainders. This guarantees the shares
    sum back EXACTLY to total_cents while staying as close as possible to the
    requested proportions.

    `weights` must already be validated (see `_coerce_weights`). Returns a list
    of integer cents of the same length as `weights`.
    """
    weights = _coerce_weights(weights)
    total_w = sum(weights)
    exact = [total_cents * w / total_w for w in weights]
    floors = [int(math.floor(x)) for x in exact]
    remainder = total_cents - sum(floors)
    # Hand the remaining cents to the largest fractional parts first.
    order = sorted(range(len(weights)),
                   key=lambda i: exact[i] - floors[i], reverse=True)
    for k in range(remainder):
        floors[order[k]] += 1
    return floors


def split_bill_by_weights(bill, tip_percent, weights, tax_percent=0,
                          round_total=False, tip_on="pretax"):
    """Compute a full bill (via `calculate_bill`) then split it by `weights`.

    The number of people is the number of weights. The grand total and the tip
    portion are each apportioned with `split_weighted`, so both sum back exactly
    to their whole. Raises ValueError on any invalid input.

    Returns the `calculate_bill` totals plus: weights (the normalised list),
    shares (per-person total), and tip_shares (per-person tip).
    """
    weights = _coerce_weights(weights)
    result = calculate_bill(bill, tip_percent, len(weights), tax_percent,
                            round_total, tip_on)
    total_cents = _to_cents(result["total"])
    tip_cents = _to_cents(result["tip"])
    shares = split_weighted(total_cents, weights)
    tip_shares = split_weighted(tip_cents, weights)
    result["weights"] = weights
    result["shares"] = [_from_cents(c) for c in shares]
    result["tip_shares"] = [_from_cents(c) for c in tip_shares]
    return result


# Recommended tip percentage for a given quality of service. These are the
# common US dining conventions: ~15% is the baseline for adequate service and
# climbs toward 25% for exceptional service. Keyed by a lowercase rating word so
# the UI can offer one-tap "how was the service?" suggestions.
SERVICE_RATINGS = {
    "poor": 10,
    "fair": 15,
    "good": 18,
    "great": 20,
    "exceptional": 25,
}


def recommend_tip(bill, rating, people=1, tax_percent=0,
                  round_total=False, tip_on="pretax"):
    """Recommend a full bill breakdown for a service-quality `rating`.

    Maps a rating word (see SERVICE_RATINGS) to its conventional tip percentage
    and then defers entirely to `calculate_bill`, so the result carries the same
    tax handling and fair-split guarantees. `rating` is matched case- and
    whitespace-insensitively. Raises ValueError on an unknown rating or any
    invalid bill / people / tax input.

    Returns the `calculate_bill` dict plus `rating` (the normalised word) and
    `recommended_percent` (the percentage that was applied).
    """
    if rating is None:
        raise ValueError("rating is required")
    try:
        key = str(rating).strip().lower()
    except (TypeError, ValueError):
        raise ValueError("rating must be a string")
    if key not in SERVICE_RATINGS:
        raise ValueError(
            "rating must be one of: " + ", ".join(sorted(SERVICE_RATINGS)))
    percent = SERVICE_RATINGS[key]
    result = calculate_bill(bill, percent, people, tax_percent,
                            round_total, tip_on)
    result["rating"] = key
    result["recommended_percent"] = percent
    return result


def _coerce_items(items):
    """Validate a per-person itemized order list.

    `items` has one entry per person. Each entry is either a single non-negative
    number (that person's subtotal) or a list/tuple of non-negative item amounts
    (which are summed). Returns a list of per-person item lists of floats so
    callers can report both the per-person subtotal and the raw items. Raises
    ValueError on anything invalid so the API returns a clean 400.
    """
    if isinstance(items, (str, bytes)) or not isinstance(items, (list, tuple)):
        raise ValueError("items must be a list, one entry per person")
    if not items:
        raise ValueError("items must not be empty")
    people_items = []
    for entry in items:
        if isinstance(entry, bool):
            raise ValueError("item amounts must be numbers")
        if isinstance(entry, (list, tuple)):
            amounts = entry
        elif isinstance(entry, (int, float)):
            amounts = [entry]
        else:
            raise ValueError(
                "each person's items must be a number or a list of numbers")
        cleaned = []
        for amt in amounts:
            if isinstance(amt, bool):
                raise ValueError("item amounts must be numbers")
            try:
                value = float(amt)
            except (TypeError, ValueError):
                raise ValueError("item amounts must be numbers")
            if value != value or value < 0:  # NaN or negative
                raise ValueError("item amounts must be non-negative")
            cleaned.append(value)
        people_items.append(cleaned)
    return people_items


def split_by_items(items, tip_percent, tax_percent=0, round_total=False,
                   tip_on="pretax"):
    """Split a bill by what each person actually ordered.

    `items` lists each person's order (see `_coerce_items`); the bill is the sum
    of every item across everyone. Tax and tip are computed on that bill via
    `calculate_bill` and then allocated to each person in proportion to their own
    pre-tax subtotal using `split_weighted`, so each person pays tax and tip on
    exactly their share and the per-person totals sum back to the grand total.

    When every subtotal is zero (a fully comped bill) the tax/tip fall back to an
    even split. Raises ValueError on any invalid input.

    Returns the `calculate_bill` dict plus `breakdown` (a per-person list of
    {subtotal, tax, tip, total}), `tip_shares` (per-person tip), and `shares`
    (per-person grand total).
    """
    people_items = _coerce_items(items)
    subtotals_cents = [_to_cents(sum(person)) for person in people_items]
    bill_cents = sum(subtotals_cents)

    result = calculate_bill(_from_cents(bill_cents), tip_percent,
                            len(people_items), tax_percent, round_total, tip_on)
    tax_cents = _to_cents(result["tax"])
    tip_cents = _to_cents(result["tip"])

    # Apportion tax and tip by each person's share of the pre-tax subtotal.
    weights = subtotals_cents if bill_cents > 0 else [1] * len(people_items)
    tax_shares = split_weighted(tax_cents, weights)
    tip_shares = split_weighted(tip_cents, weights)

    breakdown = []
    totals = []
    for i in range(len(people_items)):
        person_total = subtotals_cents[i] + tax_shares[i] + tip_shares[i]
        totals.append(person_total)
        breakdown.append({
            "subtotal": _from_cents(subtotals_cents[i]),
            "tax": _from_cents(tax_shares[i]),
            "tip": _from_cents(tip_shares[i]),
            "total": _from_cents(person_total),
        })

    result["breakdown"] = breakdown
    result["tip_shares"] = [_from_cents(c) for c in tip_shares]
    result["shares"] = [_from_cents(c) for c in totals]
    return result


def split_shared_items(items, shared=None, tip_percent=0, tax_percent=0,
                       round_total=False, tip_on="pretax"):
    """Split a bill of each person's OWN items plus communal SHARED items.

    Extends `split_by_items` with a `shared` list of items the whole table
    divides evenly (appetisers, a bottle of wine, a dessert to pass around).
    Each person's pre-tax subtotal becomes the sum of their own items plus an
    even share of the shared items; tax and tip are then figured on the grand
    bill and apportioned to each person in proportion to that combined subtotal,
    exactly as in `split_by_items`. The shared total is divided with
    `split_amount`, so the communal portion always sums back exactly even when it
    does not divide evenly across the table.

    `items` is the per-person order (see `_coerce_items`) and fixes the number of
    people. `shared` is a flat list of shared item amounts (see `_coerce_amounts`);
    omitting it (or passing an empty list) reduces this to `split_by_items`.

    When every combined subtotal is zero (a fully comped table) the tax/tip fall
    back to an even split. Raises ValueError on any invalid input.

    Returns the `calculate_bill` dict (whose `subtotal` is the grand pre-tax bill)
    plus: shared_total (the communal items' summed cost), shared_per_person (each
    person's even share of the shared items), breakdown (a per-person list of
    {own, shared, subtotal, tax, tip, total}), tip_shares (per-person tip), and
    shares (per-person grand total).
    """
    people_items = _coerce_items(items)
    people = len(people_items)
    own_cents = [_to_cents(sum(person)) for person in people_items]

    # `shared` is optional: None or an empty list means "no communal items" and
    # this collapses to a plain per-person item split.
    if shared is None or (isinstance(shared, (list, tuple)) and not shared):
        shared_amounts = []
    else:
        shared_amounts = _coerce_amounts(shared, "shared")
    shared_total_cents = sum(_to_cents(a) for a in shared_amounts)
    # Split the communal cost evenly and fairly; the cents sum back exactly.
    shared_shares = split_amount(shared_total_cents, people)

    subtotals_cents = [own_cents[i] + shared_shares[i] for i in range(people)]
    bill_cents = sum(subtotals_cents)

    result = calculate_bill(_from_cents(bill_cents), tip_percent, people,
                            tax_percent, round_total, tip_on)
    tax_cents = _to_cents(result["tax"])
    tip_cents = _to_cents(result["tip"])

    # Apportion tax and tip by each person's combined (own + shared) subtotal.
    weights = subtotals_cents if bill_cents > 0 else [1] * people
    tax_shares = split_weighted(tax_cents, weights)
    tip_shares = split_weighted(tip_cents, weights)

    breakdown = []
    totals = []
    for i in range(people):
        person_total = subtotals_cents[i] + tax_shares[i] + tip_shares[i]
        totals.append(person_total)
        breakdown.append({
            "own": _from_cents(own_cents[i]),
            "shared": _from_cents(shared_shares[i]),
            "subtotal": _from_cents(subtotals_cents[i]),
            "tax": _from_cents(tax_shares[i]),
            "tip": _from_cents(tip_shares[i]),
            "total": _from_cents(person_total),
        })

    result["shared_total"] = _from_cents(shared_total_cents)
    result["shared_per_person"] = [_from_cents(c) for c in shared_shares]
    result["breakdown"] = breakdown
    result["tip_shares"] = [_from_cents(c) for c in tip_shares]
    result["shares"] = [_from_cents(c) for c in totals]
    return result


def tip_for_total(bill, target_total, people=1, tax_percent=0, tip_on="pretax"):
    """Work backwards from a desired grand total to the tip needed to hit it.

    Given a `bill`, an optional `tax_percent`, and the `target_total` you want to
    pay, computes the tip amount that makes the grand total land exactly on the
    target plus the effective tip percentage that implies. The total is then
    split fairly across `people` with the same integer-cent guarantees as
    `calculate`.

    `tip_on` is accepted for symmetry with the other endpoints but does not
    affect the result here, since the tip is derived from the target rather than
    from a percentage. Raises ValueError if the target is below the bill plus tax
    (a negative tip is impossible) or on any invalid input.

    Returns a dict with: subtotal, tax, tax_percent, tip, tip_percent (the
    effective rate), target, total, people, per_person, per_person_tip,
    per_person_tax, shares, and tip_on.
    """
    bill_cents, _unused_tip, people = _validate_common(bill, 0, people)

    if target_total is None:
        raise ValueError("target_total is required")
    try:
        target = float(target_total)
    except (TypeError, ValueError):
        raise ValueError("target_total must be a number")
    if target != target:  # NaN
        raise ValueError("target_total must be a number")
    if target < 0:
        raise ValueError("target_total must be non-negative")
    target_cents = _to_cents(target)
    tax_percent = _coerce_tax(tax_percent)

    if tip_on not in TIP_BASES:
        raise ValueError("tip_on must be 'pretax' or 'posttax'")

    tax_cents = int(round(bill_cents * tax_percent / 100.0))
    base_cents = bill_cents + tax_cents
    tip_cents = target_cents - base_cents
    if tip_cents < 0:
        raise ValueError("target_total must be at least the bill plus tax")

    effective_percent = (tip_cents / bill_cents * 100.0) if bill_cents else 0.0
    total_cents = target_cents

    return _breakdown(bill_cents, tip_cents, tax_cents, total_cents, people,
                      effective_percent, tax_percent, tip_on,
                      extra={"target": _from_cents(target_cents)})


# A discount can be expressed as a percentage off the bill or a flat dollar
# amount off, mirroring how restaurant coupons / promo codes work.
DISCOUNT_KINDS = ("percent", "amount")


def _coerce_discount(discount, discount_kind, bill_cents):
    """Validate a coupon/discount and return how many cents it knocks off.

    `discount_kind` selects how `discount` is interpreted: "percent" treats it as
    a percentage off (0..100, the same bounds as the other percentage inputs) and
    "amount" treats it as a flat dollar amount off. A flat amount is capped at the
    bill so a coupon can never push the subtotal below zero. Returns the discount
    as an integer number of cents. Raises ValueError on anything invalid so the
    API returns a clean 400.
    """
    if discount_kind not in DISCOUNT_KINDS:
        raise ValueError("discount_kind must be 'percent' or 'amount'")
    try:
        discount = float(discount)
    except (TypeError, ValueError):
        raise ValueError("discount must be a number")
    if discount != discount:  # NaN
        raise ValueError("discount must be a number")
    if discount < 0:
        raise ValueError("discount must be non-negative")

    if discount_kind == "percent":
        if discount > 100:
            raise ValueError("discount percent must be between 0 and 100")
        return int(round(bill_cents * discount / 100.0))
    # flat amount: never discount more than the bill itself.
    return min(_to_cents(discount), bill_cents)


def calculate_with_discount(bill, tip_percent, discount, discount_kind="percent",
                            people=1, tax_percent=0, round_total=False,
                            tip_on="pretax"):
    """Apply a coupon/discount to the bill, then compute the full breakdown.

    The discount is taken off the pre-tax bill first (see `_coerce_discount`); tax
    and tip are then figured on the DISCOUNTED subtotal via `calculate_bill`, so a
    coupon correctly reduces both the tax and the tip. Every per-person breakdown
    keeps the same fair-split guarantees as `calculate_bill`.

    Raises ValueError on any invalid input. Returns the `calculate_bill` dict
    (whose `subtotal` is the discounted subtotal) plus: original_subtotal (the
    bill before the discount), discount (the normalised input), discount_kind, and
    discount_amount (the dollars actually knocked off).
    """
    bill_cents, tip_percent, people = _validate_common(bill, tip_percent, people)
    discount_cents = _coerce_discount(discount, discount_kind, bill_cents)
    discounted_cents = bill_cents - discount_cents

    result = calculate_bill(_from_cents(discounted_cents), tip_percent, people,
                            tax_percent, round_total, tip_on)
    result["original_subtotal"] = _from_cents(bill_cents)
    result["discount"] = round(float(discount), 4)
    result["discount_kind"] = discount_kind
    result["discount_amount"] = _from_cents(discount_cents)
    return result


def service_charge_bill(bill, service_percent, tip_percent=0, people=1,
                        tax_percent=0, round_total=False, tip_on="pretax"):
    """Full breakdown for a bill that carries a mandatory service charge.

    Large parties are commonly charged an automatic "service charge" (a.k.a.
    auto-gratuity) that the restaurant adds on top of the bill. The diner may
    then leave an *additional* voluntary tip. This separates the two so the
    receipt is unambiguous: subtotal + tax + mandatory service charge + optional
    extra tip = grand total.

    Both the service charge and the additional tip are figured on the base
    selected by `tip_on` (the pre-tax subtotal by default, the post-tax amount
    when "posttax"). `tax` is always figured on the pre-tax subtotal. When
    `round_total` is truthy the grand total is rounded UP to the next whole
    dollar and the extra cents are absorbed into the additional tip, exactly as
    in `calculate_bill`. Every per-person breakdown is produced with
    `split_amount`, so each sums back exactly to its whole.

    Raises ValueError on any invalid input. Returns a dict with: subtotal, tax,
    tax_percent, service_charge, service_percent, tip, tip_percent, total,
    people, per_person, per_person_service, per_person_tip, per_person_tax,
    shares, tip_on, and rounded.
    """
    bill_cents, tip_percent, people = _validate_common(bill, tip_percent, people)

    try:
        service_percent = float(service_percent)
    except (TypeError, ValueError):
        raise ValueError("service_percent must be a number")
    if service_percent != service_percent:  # NaN
        raise ValueError("service_percent must be a number")
    if service_percent < 0 or service_percent > 100:
        raise ValueError("service_percent must be between 0 and 100")

    try:
        tax_percent = float(tax_percent)
    except (TypeError, ValueError):
        raise ValueError("tax_percent must be a number")
    if tax_percent != tax_percent:  # NaN
        raise ValueError("tax_percent must be a number")
    if tax_percent < 0 or tax_percent > 100:
        raise ValueError("tax_percent must be between 0 and 100")

    if tip_on not in TIP_BASES:
        raise ValueError("tip_on must be 'pretax' or 'posttax'")

    tax_cents = int(round(bill_cents * tax_percent / 100.0))
    base_cents = bill_cents if tip_on == "pretax" else bill_cents + tax_cents
    service_cents = int(round(base_cents * service_percent / 100.0))
    tip_cents = int(round(base_cents * tip_percent / 100.0))
    total_cents = bill_cents + tax_cents + service_cents + tip_cents

    rounded = bool(round_total)
    if rounded:
        bumped = int(math.ceil(total_cents / 100.0)) * 100
        tip_cents += bumped - total_cents
        total_cents = bumped

    total_shares = split_amount(total_cents, people)
    service_shares = split_amount(service_cents, people)
    tip_shares = split_amount(tip_cents, people)
    tax_shares = split_amount(tax_cents, people)

    return {
        "subtotal": _from_cents(bill_cents),
        "tax": _from_cents(tax_cents),
        "tax_percent": round(tax_percent, 4),
        "service_charge": _from_cents(service_cents),
        "service_percent": round(service_percent, 4),
        "tip": _from_cents(tip_cents),
        "tip_percent": round(tip_percent, 4),
        "total": _from_cents(total_cents),
        "people": people,
        "per_person": _from_cents(total_shares[0]),
        "per_person_service": _from_cents(service_shares[0]),
        "per_person_tip": _from_cents(tip_shares[0]),
        "per_person_tax": _from_cents(tax_shares[0]),
        "shares": [_from_cents(c) for c in total_shares],
        "tip_on": tip_on,
        "rounded": rounded,
    }


def split_round_up_per_person(bill, tip_percent, people, tax_percent=0,
                              tip_on="pretax"):
    """Split a bill so every person pays a whole-dollar amount.

    Handy for cash splitting: rather than asking everyone for $23.34, each
    person's fair share is rounded UP to the next whole dollar so they can throw
    in round bills. The combined surplus from the rounding is added to the tip,
    so the diners always cover at least the real total and the restaurant simply
    receives a slightly larger gratuity.

    The bill (subtotal + tax + tip) is first computed with `calculate_bill`
    (without any total rounding), then each person's fair share from
    `split_amount` is rounded up to the next whole dollar. The grand total
    becomes the sum of those rounded shares and the tip grows by the surplus, so
    subtotal + tax + tip still equals the new total exactly.

    Raises ValueError on any invalid input. Returns a dict with: subtotal, tax,
    tax_percent, tip (the bumped tip), tip_percent (the effective rate), total
    (sum of the rounded shares), people, per_person (the largest rounded share),
    shares (each a whole dollar), surplus (the dollars added by rounding),
    original_total (before rounding), tip_on, and rounded (always True).
    """
    base = calculate_bill(bill, tip_percent, people, tax_percent,
                          round_total=False, tip_on=tip_on)
    bill_cents = _to_cents(base["subtotal"])
    tax_cents = _to_cents(base["tax"])
    tip_cents = _to_cents(base["tip"])
    original_total_cents = _to_cents(base["total"])
    people = base["people"]

    fair_shares = split_amount(original_total_cents, people)
    rounded_shares = [int(math.ceil(c / 100.0)) * 100 for c in fair_shares]
    new_total_cents = sum(rounded_shares)
    surplus_cents = new_total_cents - original_total_cents
    new_tip_cents = tip_cents + surplus_cents

    effective_percent = (new_tip_cents / bill_cents * 100.0) if bill_cents else 0.0

    return {
        "subtotal": _from_cents(bill_cents),
        "tax": _from_cents(tax_cents),
        "tax_percent": base["tax_percent"],
        "tip": _from_cents(new_tip_cents),
        "tip_percent": round(effective_percent, 4),
        "total": _from_cents(new_total_cents),
        "people": people,
        "per_person": _from_cents(max(rounded_shares)),
        "shares": [_from_cents(c) for c in rounded_shares],
        "surplus": _from_cents(surplus_cents),
        "original_total": _from_cents(original_total_cents),
        "tip_on": base["tip_on"],
        "rounded": True,
    }


def distribute_pool(pool, weights):
    """Distribute a pooled tip amount among staff in proportion to `weights`.

    A common back-of-house practice: a shift's tips are pooled and then shared
    among the workers in proportion to some weight — typically hours worked, but
    any non-negative weights are accepted. The pool is apportioned with the same
    largest-remainder method as `split_weighted`, so the individual cuts always
    sum back EXACTLY to the pool and stay as close as possible to each worker's
    fair proportion.

    Raises ValueError on a negative / NaN / non-numeric pool or invalid weights
    (see `_coerce_weights`). Returns a dict with: pool (the normalised amount),
    weights (the normalised list), people (the worker count), shares (each
    worker's cut), and per_person (the largest single cut).
    """
    if pool is None:
        raise ValueError("pool is required")
    try:
        pool = float(pool)
    except (TypeError, ValueError):
        raise ValueError("pool must be a number")
    if pool != pool:  # NaN
        raise ValueError("pool must be a number")
    if pool < 0:
        raise ValueError("pool must be non-negative")

    weights = _coerce_weights(weights)
    pool_cents = _to_cents(pool)
    shares = split_weighted(pool_cents, weights)

    return {
        "pool": _from_cents(pool_cents),
        "weights": weights,
        "people": len(weights),
        "shares": [_from_cents(c) for c in shares],
        "per_person": _from_cents(max(shares)),
    }


def split_to_denomination(bill, tip_percent, people, denomination=1.0,
                          tax_percent=0, tip_on="pretax"):
    """Split a bill so every person pays a whole multiple of a cash denomination.

    Generalises the whole-dollar `split_round_up_per_person`: instead of always
    rounding each share up to the next dollar, each person's fair share is
    rounded UP to the next multiple of `denomination` (e.g. 0.25 for quarters,
    0.05 for nickels, 5 for $5 bills). Handy when the cash on hand only comes in
    certain denominations. The combined surplus from rounding is folded into the
    tip, so the diners always cover at least the real total and the restaurant
    simply receives a slightly larger gratuity. Passing denomination=1 reproduces
    `split_round_up_per_person` exactly.

    The bill (subtotal + tax + tip) is first computed with `calculate_bill`
    (without any total rounding), then each person's fair share from
    `split_amount` is rounded up to the next multiple of the denomination. The
    grand total becomes the sum of those rounded shares and the tip grows by the
    surplus, so subtotal + tax + tip still equals the new total exactly.

    Raises ValueError on a non-positive / NaN / non-numeric denomination or any
    invalid bill / people / tax input. Returns a dict with: subtotal, tax,
    tax_percent, tip (the bumped tip), tip_percent (the effective rate), total
    (sum of the rounded shares), people, per_person (the largest rounded share),
    shares (each a whole multiple of the denomination), denomination, surplus
    (the dollars added by rounding), original_total (before rounding), tip_on,
    and rounded (always True).
    """
    try:
        denomination = float(denomination)
    except (TypeError, ValueError):
        raise ValueError("denomination must be a number")
    if denomination != denomination:  # NaN
        raise ValueError("denomination must be a number")
    denom_cents = _to_cents(denomination)
    if denom_cents <= 0:
        raise ValueError("denomination must be positive")

    base = calculate_bill(bill, tip_percent, people, tax_percent,
                          round_total=False, tip_on=tip_on)
    bill_cents = _to_cents(base["subtotal"])
    tax_cents = _to_cents(base["tax"])
    tip_cents = _to_cents(base["tip"])
    original_total_cents = _to_cents(base["total"])
    people = base["people"]

    fair_shares = split_amount(original_total_cents, people)
    rounded_shares = [int(math.ceil(c / denom_cents)) * denom_cents
                      for c in fair_shares]
    new_total_cents = sum(rounded_shares)
    surplus_cents = new_total_cents - original_total_cents
    new_tip_cents = tip_cents + surplus_cents

    effective_percent = (new_tip_cents / bill_cents * 100.0) if bill_cents else 0.0

    return {
        "subtotal": _from_cents(bill_cents),
        "tax": _from_cents(tax_cents),
        "tax_percent": base["tax_percent"],
        "tip": _from_cents(new_tip_cents),
        "tip_percent": round(effective_percent, 4),
        "total": _from_cents(new_total_cents),
        "people": people,
        "per_person": _from_cents(max(rounded_shares)),
        "shares": [_from_cents(c) for c in rounded_shares],
        "denomination": _from_cents(denom_cents),
        "surplus": _from_cents(surplus_cents),
        "original_total": _from_cents(original_total_cents),
        "tip_on": base["tip_on"],
        "rounded": True,
    }


def tip_from_per_person(bill, per_person_target, people=1, tax_percent=0,
                        tip_on="pretax"):
    """Work backwards from a desired PER-PERSON total to the tip that achieves it.

    The per-person analogue of `tip_for_total`: instead of naming the grand
    total you want to pay, each diner names what THEY want their own share to be
    (e.g. "I want to put in exactly $25"). The grand target is that per-person
    figure times the number of people; the tip is then whatever makes the bill
    (plus tax) land on that grand target, and the result is split fairly with the
    same integer-cent guarantees as `calculate`.

    `tip_on` is accepted for symmetry with the other endpoints but does not
    affect the result, since the tip is derived from the target rather than from
    a percentage. Raises ValueError if the per-person target is below each
    person's share of the bill plus tax (a negative tip is impossible) or on any
    invalid input.

    Returns the `tip_for_total` dict plus `per_person_target` (the normalised
    per-person figure that was requested).
    """
    if per_person_target is None:
        raise ValueError("per_person_target is required")
    try:
        ppt = float(per_person_target)
    except (TypeError, ValueError):
        raise ValueError("per_person_target must be a number")
    if ppt != ppt:  # NaN
        raise ValueError("per_person_target must be a number")
    if ppt < 0:
        raise ValueError("per_person_target must be non-negative")

    # _validate_common normalises people (and rejects bad bills) so we can build
    # the grand target from a whole number of people.
    _bill_cents, _unused, people = _validate_common(bill, 0, people)
    ppt_cents = _to_cents(ppt)
    target_total = _from_cents(ppt_cents * people)

    result = tip_for_total(bill, target_total, people, tax_percent, tip_on)
    result["per_person_target"] = _from_cents(ppt_cents)
    return result


# How to snap the grand total to a cash-friendly figure: always up, always down,
# or to whichever multiple is closest.
ROUNDING_MODES = ("up", "down", "nearest")


def round_total_to_nearest(bill, tip_percent, people=1, tax_percent=0,
                           round_to=1.0, mode="nearest", tip_on="pretax"):
    """Snap the GRAND TOTAL to a tidy figure, absorbing the change into the tip.

    Computes the full bill via `calculate_bill` and then rounds the grand total
    to a multiple of `round_to` (default $1). `mode` selects the direction:
    "up" always rounds up, "down" always rounds down, and "nearest" snaps to the
    closest multiple (ties round up). The difference between the rounded and the
    original total is added to (or, when rounding down, taken off) the tip, so
    subtotal + tax + tip always equals the new total exactly. The new total is
    then split fairly across `people` with the same integer-cent guarantees as
    `calculate`.

    Differs from the round-UP-only behaviour of `calculate`/`calculate_bill`
    (which only ever bumps to the next whole dollar) and from
    `split_round_up_per_person` (which rounds each PERSON'S share): this rounds
    the single grand total in any direction to any denomination.

    Raises ValueError if rounding down would drive the tip negative (i.e. below
    the bill plus tax) or on any invalid input. Returns a dict with: subtotal,
    tax, tax_percent, tip (the adjusted tip), tip_percent (the effective rate),
    total (the rounded total), people, per_person, per_person_tip,
    per_person_tax, shares, round_to, mode, original_total (before rounding),
    adjustment (cents-as-dollars moved into the tip; negative when rounding
    down), tip_on, and rounded (always True).
    """
    base = calculate_bill(bill, tip_percent, people, tax_percent,
                          round_total=False, tip_on=tip_on)
    bill_cents = _to_cents(base["subtotal"])
    tax_cents = _to_cents(base["tax"])
    total_cents = _to_cents(base["total"])
    people = base["people"]

    try:
        round_to = float(round_to)
    except (TypeError, ValueError):
        raise ValueError("round_to must be a number")
    if round_to != round_to:  # NaN
        raise ValueError("round_to must be a number")
    step = _to_cents(round_to)
    if step <= 0:
        raise ValueError("round_to must be positive")

    if mode not in ROUNDING_MODES:
        raise ValueError("mode must be 'up', 'down', or 'nearest'")

    if mode == "up":
        new_total = int(math.ceil(total_cents / step)) * step
    elif mode == "down":
        new_total = int(math.floor(total_cents / step)) * step
    else:  # nearest, ties rounding up
        new_total = int(math.floor(total_cents / step + 0.5)) * step

    new_tip_cents = new_total - bill_cents - tax_cents
    if new_tip_cents < 0:
        raise ValueError("rounding would make the tip negative")

    adjustment_cents = new_total - total_cents
    effective_percent = (new_tip_cents / bill_cents * 100.0) if bill_cents else 0.0

    total_shares = split_amount(new_total, people)
    tip_shares = split_amount(new_tip_cents, people)
    tax_shares = split_amount(tax_cents, people)

    return {
        "subtotal": _from_cents(bill_cents),
        "tax": _from_cents(tax_cents),
        "tax_percent": base["tax_percent"],
        "tip": _from_cents(new_tip_cents),
        "tip_percent": round(effective_percent, 4),
        "total": _from_cents(new_total),
        "people": people,
        "per_person": _from_cents(total_shares[0]),
        "per_person_tip": _from_cents(tip_shares[0]),
        "per_person_tax": _from_cents(tax_shares[0]),
        "shares": [_from_cents(c) for c in total_shares],
        "round_to": _from_cents(step),
        "mode": mode,
        "original_total": _from_cents(total_cents),
        "adjustment": _from_cents(adjustment_cents),
        "tip_on": base["tip_on"],
        "rounded": True,
    }


def _fmt_pct(percent):
    """Render a percentage without a trailing ``.0`` (20.0 -> "20", 12.5 -> "12.5")."""
    return ("%g" % float(percent))


def format_receipt(bill, tip_percent, people=1, tax_percent=0, round_total=False,
                   tip_on="pretax", title="Receipt"):
    """Render a plain-text, shareable receipt for a full bill breakdown.

    Computes the bill via `calculate_bill` and lays it out as a fixed-width
    receipt: the subtotal, the tax (only when non-zero), the tip, a ruled grand
    total, and — when the bill is split — one aligned line per person. Handy for
    copying into a message so everyone can see exactly what they owe.

    Raises ValueError on any invalid input (delegated to `calculate_bill`).
    Returns the `calculate_bill` dict plus `receipt` (the full multi-line
    string), `lines` (the same content as a list of lines), and `title` (the
    normalised heading).
    """
    r = calculate_bill(bill, tip_percent, people, tax_percent, round_total,
                       tip_on)
    width = 32

    def amount_line(label, amount):
        # Right-align the dollar amount within the receipt width.
        amt = "$%.2f" % amount
        pad = width - len(label) - len(amt)
        if pad < 1:
            pad = 1
        return label + (" " * pad) + amt

    title = str(title)
    lines = [title, "=" * width, amount_line("Subtotal", r["subtotal"])]
    if r["tax"] > 0:
        lines.append(amount_line("Tax (%s%%)" % _fmt_pct(r["tax_percent"]),
                                 r["tax"]))
    lines.append(amount_line("Tip (%s%%)" % _fmt_pct(r["tip_percent"]),
                             r["tip"]))
    lines.append("-" * width)
    lines.append(amount_line("Total", r["total"]))
    if r["people"] > 1:
        lines.append("Split %d ways:" % r["people"])
        for i, share in enumerate(r["shares"], 1):
            lines.append(amount_line("  Person %d" % i, share))

    r["receipt"] = "\n".join(lines)
    r["lines"] = lines
    r["title"] = title
    return r


def tip_from_amount(bill, tip_amount, people=1, tax_percent=0, tip_on="pretax"):
    """Compute a full breakdown from a FLAT tip dollar amount.

    The dollar analogue of `calculate`: instead of naming a tip percentage you
    name the exact tip dollars you want to leave (e.g. "leave $7"). The effective
    tip percentage (tip / pre-tax subtotal) is reported, the bill plus optional
    tax is added on, and the grand total is split fairly across `people` with the
    same integer-cent guarantees as `calculate`.

    This is the tip-amount sibling of `tip_for_total` (which works back from a
    grand total) and `tip_from_per_person` (from a per-person total). `tip_on` is
    accepted for symmetry with the other endpoints but does not affect the
    result, since the tip is given directly rather than derived from a base.

    Raises ValueError on a negative / NaN / non-numeric tip amount or any invalid
    bill / people / tax input. Returns a dict with: subtotal, tax, tax_percent,
    tip, tip_percent (the effective rate), total, people, per_person,
    per_person_tip, per_person_tax, shares, and tip_on.
    """
    bill_cents, _unused_tip, people = _validate_common(bill, 0, people)

    if tip_amount is None:
        raise ValueError("tip_amount is required")
    try:
        tip_amount = float(tip_amount)
    except (TypeError, ValueError):
        raise ValueError("tip_amount must be a number")
    if tip_amount != tip_amount:  # NaN
        raise ValueError("tip_amount must be a number")
    if tip_amount < 0:
        raise ValueError("tip_amount must be non-negative")

    try:
        tax_percent = float(tax_percent)
    except (TypeError, ValueError):
        raise ValueError("tax_percent must be a number")
    if tax_percent != tax_percent or tax_percent < 0 or tax_percent > 100:
        raise ValueError("tax_percent must be between 0 and 100")

    if tip_on not in TIP_BASES:
        raise ValueError("tip_on must be 'pretax' or 'posttax'")

    tax_cents = int(round(bill_cents * tax_percent / 100.0))
    tip_cents = _to_cents(tip_amount)
    total_cents = bill_cents + tax_cents + tip_cents

    effective_percent = (tip_cents / bill_cents * 100.0) if bill_cents else 0.0

    total_shares = split_amount(total_cents, people)
    tip_shares = split_amount(tip_cents, people)
    tax_shares = split_amount(tax_cents, people)

    return {
        "subtotal": _from_cents(bill_cents),
        "tax": _from_cents(tax_cents),
        "tax_percent": round(tax_percent, 4),
        "tip": _from_cents(tip_cents),
        "tip_percent": round(effective_percent, 4),
        "total": _from_cents(total_cents),
        "people": people,
        "per_person": _from_cents(total_shares[0]),
        "per_person_tip": _from_cents(tip_shares[0]),
        "per_person_tax": _from_cents(tax_shares[0]),
        "shares": [_from_cents(c) for c in total_shares],
        "tip_on": tip_on,
    }


def compare_scenarios(bill, percents=DEFAULT_PRESET_PERCENTS, people=1,
                      tax_percent=0, tip_on="pretax"):
    """Full side-by-side breakdowns for several tip percentages.

    A richer cousin of `suggest_tips`: where `suggest_tips` reports only the tip,
    total, and per-person figure for each preset, this runs every percentage
    through `calculate_bill`, so each scenario carries the full subtotal / tax /
    tip / total / per-person / per-person-tip breakdown and honours tax and the
    `tip_on` base. Handy for a "compare these tips" table.

    `percents` may be the default tuple, an explicit list, or None (which falls
    back to the defaults, exactly like `suggest_tips`). The subtotal and tax are
    identical across every scenario (tax is always figured on the pre-tax bill),
    so they are also surfaced once at the top level for convenience.

    Raises ValueError on any invalid bill / people / tax / percents input.
    Returns a dict with: subtotal, tax, people, tip_on, and scenarios (one full
    breakdown per percentage, each a dict of tip_percent, tip, total, per_person,
    and per_person_tip).
    """
    percents = _coerce_percents(percents)
    scenarios = []
    subtotal = tax = 0.0
    people_out = 1
    for pct in percents:
        r = calculate_bill(bill, pct, people, tax_percent, False, tip_on)
        subtotal = r["subtotal"]
        tax = r["tax"]
        people_out = r["people"]
        scenarios.append({
            "tip_percent": r["tip_percent"],
            "tip": r["tip"],
            "total": r["total"],
            "per_person": r["per_person"],
            "per_person_tip": r["per_person_tip"],
        })
    return {
        "subtotal": subtotal,
        "tax": tax,
        "people": people_out,
        "tip_on": tip_on,
        "scenarios": scenarios,
    }


def _coerce_amounts(amounts, label):
    """Validate a caller-supplied list of non-negative money amounts.

    Shared by the endpoints that take several separate amounts (combined bills,
    per-person custom tips). Accepts any non-empty list/tuple of non-negative
    numbers and returns them as a plain list of floats. `label` names the field
    in the error message so each endpoint reports its own key. Raises ValueError
    on anything invalid so the API surfaces a clean 400 rather than a 500.
    """
    if isinstance(amounts, (str, bytes)) or not isinstance(amounts, (list, tuple)):
        raise ValueError("%s must be a list of numbers" % label)
    if not amounts:
        raise ValueError("%s must not be empty" % label)
    cleaned = []
    for a in amounts:
        try:
            value = float(a)
        except (TypeError, ValueError):
            raise ValueError("%s must be a list of numbers" % label)
        if value != value or value < 0:  # NaN or negative
            raise ValueError("%s must be non-negative" % label)
        cleaned.append(value)
    return cleaned


def combine_bills(bills, tip_percent, people=1, tax_percent=0,
                  round_total=False, tip_on="pretax"):
    """Combine several separate bill amounts into one subtotal, then tax + tip + split.

    For a table settling several receipts at once — appetisers, mains, and drinks
    on separate checks. `bills` is a non-empty list of non-negative amounts; they
    are summed into a single subtotal which is then run through `calculate_bill`,
    so the tax / tip / fair-split semantics are identical to the single-bill
    endpoint. Raises ValueError on any invalid input.

    Returns the `calculate_bill` dict plus `bills` (the individual subtotals,
    rounded) and `bill_count`.
    """
    bills = _coerce_amounts(bills, "bills")
    combined = round(sum(bills), 2)
    result = calculate_bill(combined, tip_percent, people, tax_percent,
                            round_total, tip_on)
    result["bills"] = [round(b, 2) for b in bills]
    result["bill_count"] = len(bills)
    return result


def convert_currency(bill, tip_percent, rate, symbol="$", people=1,
                     tax_percent=0, round_total=False, tip_on="pretax"):
    """Compute the standard bill breakdown then convert every money figure to a
    second currency at `rate` (units of the target currency per 1 unit of base).

    Defers entirely to `calculate_bill` for the base-currency breakdown, so the
    tax / tip / fair-split guarantees are unchanged, then multiplies each money
    field (subtotal, tax, tip, total, the per-person figures, and every share) by
    `rate` and rounds to 2 decimals. `rate` must be a positive number; `symbol`
    is echoed back so the UI can label the converted figures. Raises ValueError
    on any invalid input.

    Returns a dict with: base (the original-currency `calculate_bill` dict),
    rate, symbol, and converted (the same shape as base with money converted).
    """
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        raise ValueError("rate must be a number")
    if rate != rate:  # NaN
        raise ValueError("rate must be a number")
    if rate <= 0:
        raise ValueError("rate must be positive")
    try:
        symbol = str(symbol)
    except (TypeError, ValueError):
        raise ValueError("symbol must be a string")

    base = calculate_bill(bill, tip_percent, people, tax_percent,
                          round_total, tip_on)

    def conv(amount):
        return round(amount * rate, 2)

    money_keys = ("subtotal", "tax", "tip", "total",
                  "per_person", "per_person_tip", "per_person_tax")
    converted = dict(base)
    for key in money_keys:
        converted[key] = conv(base[key])
    converted["shares"] = [conv(s) for s in base["shares"]]

    return {
        "base": base,
        "rate": round(rate, 6),
        "symbol": symbol,
        "converted": converted,
    }


def tip_within_budget(bill, budget, people=1, tax_percent=0,
                      max_tip_percent=100, tip_on="pretax"):
    """Find the largest tip (up to `max_tip_percent`) whose grand total stays
    within `budget` — the inverse of "how much can I afford to tip?".

    Computes the subtotal and tax exactly as `calculate_bill` does, then sizes
    the tip to the room left under `budget`, never exceeding `max_tip_percent` of
    the tip base. If even a zero tip already blows the budget the tip is 0 and
    `within_budget` is False. The resulting tip, total, and tax are split fairly
    with the shared `_breakdown` helper. Raises ValueError on any invalid input.

    Returns a `_breakdown` dict plus: budget, within_budget, max_tip_percent,
    and effective_tip_percent (the tip actually applied, as a percentage of the
    tip base).
    """
    bill_cents, _ignored, people = _validate_common(bill, 0, people)
    tax_percent = _coerce_tax(tax_percent)
    if tip_on not in TIP_BASES:
        raise ValueError("tip_on must be 'pretax' or 'posttax'")
    try:
        budget = float(budget)
    except (TypeError, ValueError):
        raise ValueError("budget must be a number")
    if budget != budget:  # NaN
        raise ValueError("budget must be a number")
    if budget < 0:
        raise ValueError("budget must be non-negative")
    try:
        max_tip_percent = float(max_tip_percent)
    except (TypeError, ValueError):
        raise ValueError("max_tip_percent must be a number")
    if max_tip_percent != max_tip_percent:  # NaN
        raise ValueError("max_tip_percent must be a number")
    if max_tip_percent < 0 or max_tip_percent > 100:
        raise ValueError("max_tip_percent must be between 0 and 100")

    budget_cents = _to_cents(budget)
    tax_cents = int(round(bill_cents * tax_percent / 100.0))
    tip_base = bill_cents if tip_on == "pretax" else bill_cents + tax_cents

    # The most the diner could tip by etiquette, and the most the budget allows.
    cap_cents = int(round(tip_base * max_tip_percent / 100.0))
    room_cents = budget_cents - bill_cents - tax_cents
    within_budget = room_cents >= 0
    tip_cents = max(0, min(cap_cents, room_cents))
    total_cents = bill_cents + tax_cents + tip_cents

    effective = (tip_cents / tip_base * 100.0) if tip_base else 0.0
    extra = {
        "budget": _from_cents(budget_cents),
        "within_budget": within_budget,
        "max_tip_percent": round(max_tip_percent, 4),
        "effective_tip_percent": round(effective, 4),
        "rounded": False,
    }
    return _breakdown(bill_cents, tip_cents, tax_cents, total_cents, people,
                      effective, tax_percent, tip_on, extra)


def split_custom_tips(bill, tip_percents, tax_percent=0, tip_on="pretax"):
    """Split a bill among diners who each choose their OWN tip percentage.

    Distinct from the weighted split: here everyone covers an equal share of the
    subtotal (and of the tax), but each person's tip is their own percentage
    applied to their own share of the tip base. So a generous diner can leave 25%
    while a frugal one leaves 10% on the same meal. The number of people is the
    length of `tip_percents`.

    The subtotal and tax are apportioned with `split_amount`, so they sum back
    exactly. Each per-person tip is rounded to the cent independently. Raises
    ValueError on any invalid input.

    Returns a dict with: subtotal, tax, tax_percent, tip (the summed tips),
    total, people, tip_on, per_person (a list, one entry per diner, each with
    share, tax, tip, tip_percent, and total), shares (per-person grand totals),
    and tip_shares (per-person tips).
    """
    percents = _coerce_percents(tip_percents)
    people = len(percents)
    # Reuse the shared bill validator with a dummy tip percent so the bill bounds
    # and coercion match every other endpoint exactly.
    bill_cents, _ignored, people = _validate_common(bill, 0, people)
    tax_percent = _coerce_tax(tax_percent)
    if tip_on not in TIP_BASES:
        raise ValueError("tip_on must be 'pretax' or 'posttax'")

    tax_cents = int(round(bill_cents * tax_percent / 100.0))
    subtotal_shares = split_amount(bill_cents, people)
    tax_shares = split_amount(tax_cents, people)

    per_person = []
    total_tip_cents = 0
    grand_shares = []
    tip_shares = []
    for i, pct in enumerate(percents):
        base_cents = subtotal_shares[i]
        if tip_on == "posttax":
            base_cents += tax_shares[i]
        tip_cents = int(round(base_cents * pct / 100.0))
        total_tip_cents += tip_cents
        person_total = subtotal_shares[i] + tax_shares[i] + tip_cents
        grand_shares.append(person_total)
        tip_shares.append(tip_cents)
        per_person.append({
            "share": _from_cents(subtotal_shares[i]),
            "tax": _from_cents(tax_shares[i]),
            "tip": _from_cents(tip_cents),
            "tip_percent": round(pct, 4),
            "total": _from_cents(person_total),
        })

    total_cents = bill_cents + tax_cents + total_tip_cents
    return {
        "subtotal": _from_cents(bill_cents),
        "tax": _from_cents(tax_cents),
        "tax_percent": round(tax_percent, 4),
        "tip": _from_cents(total_tip_cents),
        "total": _from_cents(total_cents),
        "people": people,
        "tip_on": tip_on,
        "per_person": per_person,
        "shares": [_from_cents(c) for c in grand_shares],
        "tip_shares": [_from_cents(c) for c in tip_shares],
    }


def card_surcharge_bill(bill, tip_percent, surcharge_percent, people=1,
                        tax_percent=0, round_total=False, tip_on="pretax"):
    """Full bill breakdown plus a credit-card processing surcharge.

    Some venues pass their card-processing fee on to the diner as a surcharge —
    a percentage added on top of the amount that actually goes on the card (the
    post-tax, post-tip total). This computes the ordinary bill via
    `calculate_bill` and then grosses the grand total up by `surcharge_percent`,
    reporting the surcharge separately so the receipt is unambiguous:
    subtotal + tax + tip + card surcharge = grand total.

    Differs from `service_charge_bill` (a service charge / auto-gratuity figured
    on the pre- or post-tax SUBTOTAL, before the tip) — a card surcharge is the
    very last thing added and is figured on the whole post-tip total.

    The surcharge and the new grand total are each split fairly across `people`
    with `split_amount`, so both sum back exactly. Raises ValueError on any
    invalid input. Returns the `calculate_bill` dict (whose `total` is REPLACED
    by the grossed-up grand total and whose `shares`/`per_person` are refreshed)
    plus: surcharge, surcharge_percent, pre_surcharge_total (the total before the
    fee), and per_person_surcharge.
    """
    base = calculate_bill(bill, tip_percent, people, tax_percent, round_total,
                          tip_on)

    try:
        surcharge_percent = float(surcharge_percent)
    except (TypeError, ValueError):
        raise ValueError("surcharge_percent must be a number")
    if surcharge_percent != surcharge_percent:  # NaN
        raise ValueError("surcharge_percent must be a number")
    if surcharge_percent < 0 or surcharge_percent > 100:
        raise ValueError("surcharge_percent must be between 0 and 100")

    pre_cents = _to_cents(base["total"])
    surcharge_cents = int(round(pre_cents * surcharge_percent / 100.0))
    new_total_cents = pre_cents + surcharge_cents
    people = base["people"]

    total_shares = split_amount(new_total_cents, people)
    surcharge_shares = split_amount(surcharge_cents, people)

    base["surcharge"] = _from_cents(surcharge_cents)
    base["surcharge_percent"] = round(surcharge_percent, 4)
    base["pre_surcharge_total"] = _from_cents(pre_cents)
    base["total"] = _from_cents(new_total_cents)
    base["per_person"] = _from_cents(total_shares[0])
    base["per_person_surcharge"] = _from_cents(surcharge_shares[0])
    base["shares"] = [_from_cents(c) for c in total_shares]
    return base


def _coerce_comped(comped, people):
    """Validate the list of comped (covered) diners for `comp_diner_split`.

    `comped` identifies which of the `people` diners are NOT paying — their
    share is covered by the others. Accepts either a list/tuple of 1-based diner
    positions (each a whole number in 1..people, duplicates ignored) or None for
    nobody comped. At least one diner must remain paying. Returns a sorted list
    of unique 1-based positions. Raises ValueError on anything invalid so the API
    surfaces a clean 400.
    """
    if comped is None:
        return []
    if isinstance(comped, (str, bytes)) or not isinstance(comped, (list, tuple)):
        raise ValueError("comped must be a list of diner numbers")
    seen = set()
    for c in comped:
        if isinstance(c, bool):
            raise ValueError("comped diner numbers must be whole numbers")
        try:
            cf = float(c)
        except (TypeError, ValueError):
            raise ValueError("comped diner numbers must be whole numbers")
        if cf != cf or cf != int(cf):  # NaN or non-integer
            raise ValueError("comped diner numbers must be whole numbers")
        ci = int(cf)
        if ci < 1 or ci > people:
            raise ValueError(
                "comped diner numbers must be between 1 and the number of people")
        seen.add(ci)
    if len(seen) >= people:
        raise ValueError("at least one diner must be paying")
    return sorted(seen)


def comp_diner_split(bill, tip_percent, people, comped=None, tax_percent=0,
                     round_total=False, tip_on="pretax"):
    """Split a bill where some diners are comped (their meal is covered for them).

    Computes the full bill via `calculate_bill` for `people` diners, then splits
    the WHOLE grand total fairly across only the PAYING diners — the comped ones
    pay nothing and their portion is absorbed evenly by everyone else. `comped`
    lists the 1-based diner positions being covered (see `_coerce_comped`).

    The paying shares are produced with `split_amount`, so they sum back exactly
    to the grand total and differ by at most a cent. Raises ValueError on any
    invalid input or if everyone is comped. Returns the `calculate_bill` dict
    plus: comped (the normalised list), paying (the count actually paying),
    per_person (the largest paying share), and a `shares` list of length
    `people` where comped diners appear as 0.0.
    """
    base = calculate_bill(bill, tip_percent, people, tax_percent, round_total,
                          tip_on)
    people = base["people"]
    comped = _coerce_comped(comped, people)
    paying = people - len(comped)

    total_cents = _to_cents(base["total"])
    paying_shares = split_amount(total_cents, paying)

    # Lay the paying shares back into the full roster, leaving comped seats at 0.
    comped_set = set(comped)
    shares = []
    idx = 0
    for seat in range(1, people + 1):
        if seat in comped_set:
            shares.append(0)
        else:
            shares.append(paying_shares[idx])
            idx += 1

    base["comped"] = comped
    base["paying"] = paying
    base["shares"] = [_from_cents(c) for c in shares]
    base["per_person"] = _from_cents(max(paying_shares))
    return base


def settle_up(bill, tip_percent, people, paid, tax_percent=0,
              round_total=False, tip_on="pretax"):
    """Settle a split bill where each diner has ALREADY put in some money.

    Computes the full bill via `calculate_bill` and the fair per-person share
    with `split_amount`, then nets each diner's already-paid contribution
    against their fair share. `paid` is a list with exactly one non-negative
    amount per diner (what each has handed over so far). The result reports each
    diner's BALANCE: a positive balance means they still OWE that much, a
    negative balance means they OVERPAID and are owed that much back. The
    balances always sum to `outstanding` (the grand total minus everything paid
    so far) to the cent, so the table is fully reconciled.

    The fair shares come from `split_amount`, so they sum back exactly to the
    grand total and differ by at most a cent. Raises ValueError on any invalid
    input or when the number of `paid` entries does not match `people`.

    Returns the `calculate_bill` dict plus: shares (each diner's fair share),
    paid (the normalised contributions), balances (share - paid per diner;
    positive owes, negative is owed back), paid_total (everything put in so
    far), and outstanding (total - paid_total; negative means the table
    overpaid and is owed change).
    """
    base = calculate_bill(bill, tip_percent, people, tax_percent, round_total,
                          tip_on)
    people = base["people"]
    paid = _coerce_amounts(paid, "paid")
    if len(paid) != people:
        raise ValueError("paid must have exactly one amount per person")

    total_cents = _to_cents(base["total"])
    shares = split_amount(total_cents, people)
    paid_cents = [_to_cents(p) for p in paid]
    balances = [shares[i] - paid_cents[i] for i in range(people)]
    paid_total = sum(paid_cents)

    base["shares"] = [_from_cents(c) for c in shares]
    base["paid"] = [_from_cents(c) for c in paid_cents]
    base["balances"] = [_from_cents(c) for c in balances]
    base["paid_total"] = _from_cents(paid_total)
    base["outstanding"] = _from_cents(total_cents - paid_total)
    base["per_person"] = _from_cents(max(shares))
    return base


def _coerce_percent_range(start, end, step):
    """Validate a start/end/step tip-percent range for `tip_guide`.

    Builds the inclusive list of percentages from `start` to `end` advancing by
    `step`. All three must be numbers, with 0 <= start <= end <= 100 and a
    positive step. The final endpoint is always included even when it does not
    land exactly on a step boundary, so a guide for 15..20 by 2 covers
    15, 17, 19, 20. Returns the list of percentages as floats. Raises ValueError
    on anything invalid so the API surfaces a clean 400.
    """
    try:
        start = float(start)
        end = float(end)
        step = float(step)
    except (TypeError, ValueError):
        raise ValueError("start, end, and step must be numbers")
    if start != start or end != end or step != step:  # NaN
        raise ValueError("start, end, and step must be numbers")
    if start < 0 or start > 100:
        raise ValueError("start must be between 0 and 100")
    if end < start or end > 100:
        raise ValueError("end must be between start and 100")
    if step <= 0:
        raise ValueError("step must be positive")

    percents = []
    # Work in integer hundredths of a percent so the loop can't drift on floats.
    cur = int(round(start * 100))
    stop = int(round(end * 100))
    inc = int(round(step * 100))
    while cur < stop:
        percents.append(round(cur / 100.0, 4))
        cur += inc
    # Always finish on the exact end, without duplicating it.
    if not percents or percents[-1] != round(stop / 100.0, 4):
        percents.append(round(stop / 100.0, 4))
    return percents


def tip_guide(bill, start=10, end=25, step=5, people=1, tax_percent=0,
              tip_on="pretax"):
    """A printed-receipt-style tip guide across a RANGE of tip percentages.

    The classic "tip guide" you see at the bottom of a receipt: one row per
    percentage from `start` to `end` advancing by `step`, each showing the tip,
    the grand total, and the per-person figure. The range is built by
    `_coerce_percent_range` (the end is always included) and then handed to
    `compare_scenarios`, so every row carries the same tax / `tip_on` / fair
    split semantics as the rest of the app.

    Distinct from `compare_scenarios`, which takes an explicit list of
    percentages: this GENERATES the evenly-spaced range for you. Raises
    ValueError on any invalid bill / people / tax / range input.

    Returns the `compare_scenarios` dict (subtotal, tax, people, tip_on,
    scenarios) plus the echoed `start`, `end`, and `step` of the range.
    """
    percents = _coerce_percent_range(start, end, step)
    result = compare_scenarios(bill, percents, people, tax_percent, tip_on)
    result["start"] = round(float(start), 4)
    result["end"] = round(float(end), 4)
    result["step"] = round(float(step), 4)
    return result


def extract_tax_bill(total_with_tax, tip_percent, people=1, tax_percent=0,
                     round_total=False, tip_on="pretax"):
    """Back out the pre-tax subtotal from a TAX-INCLUSIVE price, then tip + split.

    In much of the world (Canada, the UK, the EU) the price you are quoted
    already INCLUDES sales tax. This takes that tax-inclusive amount as
    `total_with_tax` plus the `tax_percent` baked into it, recovers the pre-tax
    subtotal (subtotal = total_with_tax / (1 + tax_percent/100)) and the tax
    portion, then figures the tip on the pre-tax subtotal ("pretax", the common
    etiquette so you don't tip on tax) or on the full tax-inclusive amount
    ("posttax"), and splits the grand total fairly across `people`.

    The tax portion is recovered as `total_with_tax - subtotal` in integer
    cents, so subtotal + tax always equals the tax-inclusive amount exactly with
    no rounding drift. The mirror image of `calculate_bill`, which ADDS tax on
    top of a pre-tax bill; here the tax is already inside the number you were
    given.

    When `round_total` is truthy the grand total is rounded UP to the next whole
    dollar with the extra cents absorbed into the tip, exactly as elsewhere.
    Raises ValueError on any invalid input. Returns the standard `_breakdown`
    dict (subtotal, tax, tax_percent, tip, tip_percent, total, people,
    per_person, per_person_tip, per_person_tax, shares, tip_on) plus
    `tax_inclusive` (the original amount you entered) and `rounded`.
    """
    # Reuse the shared validator: the tax-inclusive amount obeys the same
    # bounds as any bill, and tip_percent / people are validated identically.
    twt_cents, tip_percent, people = _validate_common(
        total_with_tax, tip_percent, people)
    tax_percent = _coerce_tax(tax_percent)
    if tip_on not in TIP_BASES:
        raise ValueError("tip_on must be 'pretax' or 'posttax'")

    # Recover the pre-tax subtotal; the tax is whatever is left over so the two
    # always sum back to the tax-inclusive amount to the cent.
    subtotal_cents = int(round(twt_cents / (1 + tax_percent / 100.0)))
    tax_cents = twt_cents - subtotal_cents

    tip_base = subtotal_cents if tip_on == "pretax" else twt_cents
    tip_cents = int(round(tip_base * tip_percent / 100.0))
    total_cents = twt_cents + tip_cents

    rounded = bool(round_total)
    if rounded:
        bumped = int(math.ceil(total_cents / 100.0)) * 100
        tip_cents += bumped - total_cents
        total_cents = bumped

    return _breakdown(
        subtotal_cents, tip_cents, tax_cents, total_cents, people,
        tip_percent, tax_percent, tip_on,
        extra={"tax_inclusive": _from_cents(twt_cents), "rounded": rounded},
    )


def _coerce_increment(increment):
    """Validate a charity round-up increment (a positive dollar amount) and
    return it as integer cents.

    The grand total is rounded up to the next multiple of this amount, so it
    must be strictly positive. Shared by `charity_round_up`. Raises ValueError
    on anything invalid so the API surfaces a clean 400.
    """
    try:
        increment = float(increment)
    except (TypeError, ValueError):
        raise ValueError("increment must be a number")
    if increment != increment:  # NaN
        raise ValueError("increment must be a number")
    if increment <= 0:
        raise ValueError("increment must be greater than 0")
    inc_cents = _to_cents(increment)
    if inc_cents < 1:
        raise ValueError("increment must be at least one cent")
    return inc_cents


def charity_round_up(bill, tip_percent, people=1, tax_percent=0,
                     increment=5, tip_on="pretax"):
    """Round the grand total UP to the next multiple of `increment` dollars and
    donate the difference to charity, reported as its own line, then split.

    Many checkout flows offer "round up for charity": the bill is bumped up to a
    tidy figure and the surplus is given away. This computes the ordinary bill
    via `calculate_bill`, rounds its grand total up to the next multiple of
    `increment` (default $5), and reports the rounded-up surplus as a SEPARATE
    `donation` line rather than folding it into the tip — so the receipt reads
    subtotal + tax + tip + donation = grand total.

    Distinct from the `round_total` option (which rounds to the next whole
    DOLLAR and absorbs the cents into the TIP): here the increment is
    configurable and the surplus is an explicit charitable donation. When the
    total already lands exactly on a multiple of `increment` the donation is
    zero and nothing changes.

    The new grand total and the donation are each split fairly across `people`
    with `split_amount`, so both sum back exactly. Raises ValueError on any
    invalid input. Returns the `calculate_bill` dict (whose `total`,
    `per_person`, and `shares` are refreshed) plus: donation, increment,
    pre_donation_total, and per_person_donation.
    """
    base = calculate_bill(bill, tip_percent, people, tax_percent, False, tip_on)
    inc_cents = _coerce_increment(increment)
    people = base["people"]

    pre_cents = _to_cents(base["total"])
    # Smallest multiple of inc_cents that is >= the current total.
    bumped = int(math.ceil(pre_cents / inc_cents)) * inc_cents
    donation_cents = bumped - pre_cents

    total_shares = split_amount(bumped, people)
    donation_shares = split_amount(donation_cents, people)

    base["donation"] = _from_cents(donation_cents)
    base["increment"] = _from_cents(inc_cents)
    base["pre_donation_total"] = _from_cents(pre_cents)
    base["total"] = _from_cents(bumped)
    base["per_person"] = _from_cents(total_shares[0])
    base["per_person_donation"] = _from_cents(donation_shares[0])
    base["shares"] = [_from_cents(c) for c in total_shares]
    return base


def _coerce_seat_list(seats, people, label):
    """Validate an optional list of 1-based diner positions (1..people).

    Like `_coerce_comped` but with no "someone must remain" restriction — the
    list may be empty (nobody) or name every diner. Accepts a list/tuple of
    whole numbers in 1..people (duplicates ignored) or None. Returns a sorted
    list of unique positions. Raises ValueError on anything invalid so the API
    surfaces a clean 400.
    """
    if seats is None:
        return []
    if isinstance(seats, (str, bytes)) or not isinstance(seats, (list, tuple)):
        raise ValueError("%s must be a list of diner numbers" % label)
    out = set()
    for s in seats:
        if isinstance(s, bool):
            raise ValueError("%s must be whole numbers" % label)
        try:
            sf = float(s)
        except (TypeError, ValueError):
            raise ValueError("%s must be whole numbers" % label)
        if sf != sf or sf != int(sf):  # NaN or non-integer
            raise ValueError("%s must be whole numbers" % label)
        si = int(sf)
        if si < 1 or si > people:
            raise ValueError(
                "%s must be between 1 and the number of people" % label)
        out.add(si)
    return sorted(out)


def split_mixed_payment(bill, tip_percent, people, card_payers=None,
                        surcharge_percent=0, tax_percent=0, round_total=False,
                        tip_on="pretax"):
    """Split a bill where some diners pay by card and the rest pay cash.

    The whole bill (computed via `calculate_bill`) is first split fairly across
    `people` with `split_amount`. Each diner who pays by CARD then has a
    card-processing `surcharge_percent` added to THEIR OWN share; cash-paying
    diners pay their fair share with no surcharge. `card_payers` lists the
    1-based positions paying by card (see `_coerce_seat_list`); the default is
    nobody (everyone cash, a plain fair split).

    Differs from `card_surcharge_bill`, which adds the surcharge to the WHOLE
    table's total — here only the card payers are charged the fee on their
    individual portions, which is fairer when only some of the party uses a
    card.

    Raises ValueError on any invalid input. Returns the `calculate_bill` dict
    plus: card_payers (the normalised list), surcharge_percent, shares (the fair
    pre-surcharge share per diner), surcharges (the fee added to each diner, 0
    for cash payers), payments (what each diner actually hands over = share +
    surcharge), surcharge_total (the fees collected), and collected (the grand
    total plus all surcharges).
    """
    base = calculate_bill(bill, tip_percent, people, tax_percent, round_total,
                          tip_on)
    people = base["people"]
    card_payers = _coerce_seat_list(card_payers, people, "card_payers")

    try:
        surcharge_percent = float(surcharge_percent)
    except (TypeError, ValueError):
        raise ValueError("surcharge_percent must be a number")
    if surcharge_percent != surcharge_percent:  # NaN
        raise ValueError("surcharge_percent must be a number")
    if surcharge_percent < 0 or surcharge_percent > 100:
        raise ValueError("surcharge_percent must be between 0 and 100")

    total_cents = _to_cents(base["total"])
    share_cents = split_amount(total_cents, people)

    card_set = set(card_payers)
    surcharge_cents = []
    payment_cents = []
    for seat in range(1, people + 1):
        share = share_cents[seat - 1]
        if seat in card_set:
            fee = int(round(share * surcharge_percent / 100.0))
        else:
            fee = 0
        surcharge_cents.append(fee)
        payment_cents.append(share + fee)

    base["card_payers"] = card_payers
    base["surcharge_percent"] = round(surcharge_percent, 4)
    base["shares"] = [_from_cents(c) for c in share_cents]
    base["surcharges"] = [_from_cents(c) for c in surcharge_cents]
    base["payments"] = [_from_cents(c) for c in payment_cents]
    base["surcharge_total"] = _from_cents(sum(surcharge_cents))
    base["collected"] = _from_cents(sum(payment_cents))
    base["per_person"] = _from_cents(max(payment_cents))
    return base


def _coerce_categories(categories):
    """Validate a list of spend categories, each with its own tip rate.

    Real bills are often tipped at different rates for different parts of the
    check — the common example is a generous tip on food but a lower (or no) tip
    on the bar/alcohol tab. Each entry is an object with a non-negative `amount`
    and a `tip_percent` in 0..100, plus an optional `name` for the label. A
    missing name is filled in as "Category N". Returns a list of
    (name, amount_float, tip_percent_float) tuples. Raises ValueError on anything
    invalid so the API surfaces a clean 400 rather than a 500.
    """
    if isinstance(categories, (str, bytes)) or not isinstance(categories, (list, tuple)):
        raise ValueError("categories must be a list")
    if not categories:
        raise ValueError("categories must not be empty")
    cleaned = []
    for i, c in enumerate(categories):
        if not isinstance(c, dict):
            raise ValueError(
                "each category must be an object with amount and tip_percent")
        amount = c.get("amount")
        tip_percent = c.get("tip_percent")
        if amount is None or tip_percent is None:
            raise ValueError("each category needs amount and tip_percent")
        if isinstance(amount, bool) or isinstance(tip_percent, bool):
            raise ValueError("category amount and tip_percent must be numbers")
        try:
            amount = float(amount)
            tip_percent = float(tip_percent)
        except (TypeError, ValueError):
            raise ValueError("category amount and tip_percent must be numbers")
        if amount != amount or tip_percent != tip_percent:  # NaN
            raise ValueError("category amount and tip_percent must be numbers")
        if amount < 0:
            raise ValueError("category amount must be non-negative")
        if tip_percent < 0 or tip_percent > 100:
            raise ValueError("category tip_percent must be between 0 and 100")
        name = c.get("name")
        name = str(name) if name is not None else "Category %d" % (i + 1)
        cleaned.append((name, amount, tip_percent))
    return cleaned


def tip_by_category(categories, people=1, tax_percent=0, round_total=False):
    """Tip each part of a bill at its own rate, then add tax and split fairly.

    Where `calculate` applies one tip percentage to the whole bill, this lets
    every spend category carry its own rate — e.g. 20% on food but 15% (or 0%)
    on the bar tab (see `_coerce_categories`). The category amounts sum to the
    pre-tax subtotal; each category's tip is figured on its own amount and the
    tips are summed. Tax is figured on the combined pre-tax subtotal and the
    grand total (subtotal + tax + total tip) is split fairly across `people`
    with the same integer-cent guarantees as `calculate`.

    When `round_total` is truthy the grand total is rounded UP to the next whole
    dollar and the extra cents are absorbed into the tip, exactly as in
    `calculate`. Raises ValueError on any invalid input.

    Returns a `_breakdown` dict (whose `tip_percent` is the effective blended
    rate, tip / pre-tax subtotal) plus: categories (a per-category list of
    {name, amount, tip_percent, tip}) and rounded (whether the round-up was
    applied).
    """
    cats = _coerce_categories(categories)
    # Reuse the shared validator purely to normalise/bounds-check `people`; the
    # bill and tip here come from the categories, so pass zero placeholders.
    _bill_cents, _unused, people = _validate_common(0, 0, people)
    tax_percent = _coerce_tax(tax_percent)

    subtotal_cents = 0
    tip_cents = 0
    breakdown = []
    for name, amount, pct in cats:
        amt_cents = _to_cents(amount)
        cat_tip = int(round(amt_cents * pct / 100.0))
        subtotal_cents += amt_cents
        tip_cents += cat_tip
        breakdown.append({
            "name": name,
            "amount": _from_cents(amt_cents),
            "tip_percent": round(pct, 4),
            "tip": _from_cents(cat_tip),
        })

    tax_cents = int(round(subtotal_cents * tax_percent / 100.0))
    total_cents = subtotal_cents + tax_cents + tip_cents

    rounded = bool(round_total)
    if rounded:
        bumped = int(math.ceil(total_cents / 100.0)) * 100
        tip_cents += bumped - total_cents
        total_cents = bumped

    effective = (tip_cents / subtotal_cents * 100.0) if subtotal_cents else 0.0
    return _breakdown(subtotal_cents, tip_cents, tax_cents, total_cents, people,
                      effective, tax_percent, "pretax",
                      extra={"categories": breakdown, "rounded": rounded})


def settle_payments(bill, tip_percent, people, paid, tax_percent=0,
                    round_total=False, tip_on="pretax"):
    """Work out the FEWEST diner-to-diner payments that square the table up.

    The action sequel to `settle_up`: where `settle_up` reports each diner's
    BALANCE (what they still owe or are owed after what they already put in),
    this turns those balances into a concrete, minimal list of "person X pays
    person Y $Z" transfers so the group can actually settle among themselves —
    the classic "one friend covered the whole bill, now everyone pays them
    back" case.

    The fair shares and balances come straight from `settle_up`, so the bill /
    tax / tip / fair-split semantics are identical. Diners who paid MORE than
    their share are creditors (owed money back); those who paid LESS are debtors
    (owe money). The two sides are matched greedily largest-to-largest, each
    step transferring the smaller of the outstanding debt and credit, which
    yields at most `people - 1` transfers — the minimum needed to clear a set of
    balances.

    Transfers only ever move money BETWEEN diners, so they net to zero among the
    table. When the diners collectively paid exactly the grand total
    (`outstanding` == 0) the transfers settle everyone completely. When the table
    has under- or over-paid the house, that residual cannot be settled internally
    and is surfaced unchanged as `outstanding` (positive: still owed to the
    venue; negative: the venue owes the table change) — the transfers still
    fairly reconcile the diners with each other.

    Raises ValueError on any invalid input or when the number of `paid` entries
    does not match `people` (delegated to `settle_up`). Returns the `settle_up`
    dict plus: transfers (a list of {"from": payer, "to": payee, "amount"} using
    1-based diner numbers, largest first) and transfer_count.
    """
    base = settle_up(bill, tip_percent, people, paid, tax_percent,
                     round_total, tip_on)
    # Work in integer cents so the transfers sum back exactly to the balances.
    balances = [_to_cents(b) for b in base["balances"]]

    # Debtors owe (positive balance); creditors are owed (negative balance).
    # Sort each side largest-first so the greedy match clears big imbalances
    # before small ones, keeping the number of transfers minimal.
    debtors = sorted(((i, bal) for i, bal in enumerate(balances) if bal > 0),
                     key=lambda x: x[1], reverse=True)
    creditors = sorted(((i, -bal) for i, bal in enumerate(balances) if bal < 0),
                       key=lambda x: x[1], reverse=True)

    transfers = []
    di = ci = 0
    while di < len(debtors) and ci < len(creditors):
        debtor, debt = debtors[di]
        creditor, credit = creditors[ci]
        pay = min(debt, credit)
        if pay > 0:
            transfers.append({
                "from": debtor + 1,
                "to": creditor + 1,
                "amount": _from_cents(pay),
            })
        debt -= pay
        credit -= pay
        debtors[di] = (debtor, debt)
        creditors[ci] = (creditor, credit)
        if debt == 0:
            di += 1
        if credit == 0:
            ci += 1

    base["transfers"] = transfers
    base["transfer_count"] = len(transfers)
    return base


def _coerce_brackets(brackets):
    """Validate the tip-by-bill-size bracket table for `tiered_tip`.

    A bracket table prices the tip by how big the bill is: e.g. "up to $50 tip
    18%, up to $100 tip 20%, anything above tip 22%". Each entry is an object
    with a `tip_percent` in 0..100 and an `up_to` upper bound (the largest
    pre-tax subtotal the bracket covers). The FINAL bracket is the open-ended
    "and above" tier — its `up_to` must be omitted or null. Earlier brackets
    must each have a positive `up_to`, and the bounds must be strictly
    increasing so the brackets do not overlap.

    Returns a list of (up_to_cents_or_None, tip_percent_float) tuples in order.
    Raises ValueError on anything invalid so the API surfaces a clean 400 rather
    than a 500.
    """
    if isinstance(brackets, (str, bytes)) or not isinstance(brackets, (list, tuple)):
        raise ValueError("brackets must be a list")
    if not brackets:
        raise ValueError("brackets must not be empty")
    cleaned = []
    last_bound = None
    for i, b in enumerate(brackets):
        if not isinstance(b, dict):
            raise ValueError(
                "each bracket must be an object with up_to and tip_percent")
        tip_percent = b.get("tip_percent")
        if tip_percent is None or isinstance(tip_percent, bool):
            raise ValueError("each bracket needs a tip_percent")
        try:
            tip_percent = float(tip_percent)
        except (TypeError, ValueError):
            raise ValueError("bracket tip_percent must be a number")
        if tip_percent != tip_percent or tip_percent < 0 or tip_percent > 100:
            raise ValueError("bracket tip_percent must be between 0 and 100")

        up_to = b.get("up_to")
        is_last = (i == len(brackets) - 1)
        if up_to is None:
            # Only the final bracket may be the open-ended "and above" tier.
            if not is_last:
                raise ValueError(
                    "only the last bracket may have an open-ended up_to")
            cleaned.append((None, tip_percent))
            continue
        if isinstance(up_to, bool):
            raise ValueError("bracket up_to must be a number")
        try:
            up_to = float(up_to)
        except (TypeError, ValueError):
            raise ValueError("bracket up_to must be a number")
        if up_to != up_to or up_to <= 0:  # NaN or non-positive
            raise ValueError("bracket up_to must be greater than 0")
        up_to_cents = _to_cents(up_to)
        if last_bound is not None and up_to_cents <= last_bound:
            raise ValueError("bracket up_to values must be strictly increasing")
        last_bound = up_to_cents
        cleaned.append((up_to_cents, tip_percent))
    return cleaned


def tiered_tip(bill, brackets, people=1, tax_percent=0, round_total=False,
               tip_on="pretax"):
    """Pick the tip percentage from a bill-size bracket table, then full breakdown.

    Some house policies (and personal rules of thumb) scale the tip to the size
    of the check rather than using one flat rate — a small bill gets a more
    generous percentage, a large one a slightly lower one, or vice-versa. This
    chooses the tip percentage by which bracket the pre-tax `bill` falls into
    (see `_coerce_brackets`) and then defers entirely to `calculate_bill`, so the
    tax / `tip_on` / fair-split guarantees are identical to the flat-rate path.

    The first bracket whose `up_to` is at least the bill wins; the final
    open-ended bracket catches anything larger than every finite bound. Raises
    ValueError on any invalid bill / people / tax / brackets input.

    Returns the `calculate_bill` dict plus: applied_percent (the rate that was
    chosen), matched_bracket (its 1-based position in the table), and brackets (a
    normalised echo of the table as a list of {up_to, tip_percent}, where the
    open-ended tier's up_to is null).
    """
    table = _coerce_brackets(brackets)
    # Validate/normalise the bill the same way every endpoint does so the bracket
    # match is made on the same integer-cent value the breakdown will use.
    bill_cents, _unused, _people = _validate_common(bill, 0, people)

    applied_percent = None
    matched = None
    for idx, (up_to_cents, pct) in enumerate(table):
        if up_to_cents is None or bill_cents <= up_to_cents:
            applied_percent = pct
            matched = idx + 1
            break
    if applied_percent is None:
        # No open-ended tier and the bill exceeds every finite bound: fall back
        # to the highest bracket so a valid table never fails to price a tip.
        applied_percent = table[-1][1]
        matched = len(table)

    result = calculate_bill(bill, applied_percent, people, tax_percent,
                            round_total, tip_on)
    result["applied_percent"] = round(applied_percent, 4)
    result["matched_bracket"] = matched
    result["brackets"] = [
        {"up_to": (_from_cents(c) if c is not None else None),
         "tip_percent": round(p, 4)}
        for c, p in table
    ]
    return result


def _coerce_gift_card(gift_card):
    """Validate a gift-card / store-credit dollar amount and return integer cents.

    A gift card is a flat amount of pre-paid money applied AGAINST the grand
    total. It must be a non-negative finite number (0 means no card, which is
    allowed so the UI can leave the field blank). Raises ValueError on anything
    invalid so the API returns a clean 400.
    """
    if isinstance(gift_card, bool):
        raise ValueError("gift_card must be a number")
    try:
        amount = float(gift_card)
    except (TypeError, ValueError):
        raise ValueError("gift_card must be a number")
    if amount != amount or amount in (float("inf"), float("-inf")):  # NaN / inf
        raise ValueError("gift_card must be a finite number")
    if amount < 0:
        raise ValueError("gift_card must not be negative")
    return _to_cents(amount)


def gift_card_split(bill, tip_percent, people, gift_card, tax_percent=0,
                    round_total=False, tip_on="pretax"):
    """Split a bill after a gift card / store credit is applied to the total.

    A gift card is pre-paid money redeemed against the WHOLE grand total — unlike
    a discount/coupon (see `calculate_with_discount`), it does NOT reduce the
    taxable base, so the tax and tip are still figured on the full bill. The card
    is applied last, against the post-tax, post-tip total, and only the remaining
    balance is actually owed and split fairly across the diners.

    The full bill is computed via `calculate_bill`, then the gift card is applied
    up to (but never beyond) the grand total — a card larger than the bill simply
    zeroes the balance, with the surplus reported as `unused` so nothing is silently
    lost. The remaining balance is split with `split_amount`, so the shares sum
    back exactly to it and differ by at most a cent. Raises ValueError on any
    invalid input.

    Returns the `calculate_bill` dict (whose `per_person`/`shares` are REPLACED by
    the split of the remaining balance) plus: gift_card (the amount requested),
    applied (the amount actually redeemed), unused (the surplus, if the card
    exceeded the total), full_total (the grand total before the card), remaining
    (the balance still owed), and per_person_remaining (the largest owed share).
    """
    base = calculate_bill(bill, tip_percent, people, tax_percent, round_total,
                          tip_on)
    card_cents = _coerce_gift_card(gift_card)

    total_cents = _to_cents(base["total"])
    applied_cents = min(card_cents, total_cents)
    unused_cents = card_cents - applied_cents
    remaining_cents = total_cents - applied_cents
    people = base["people"]

    shares = split_amount(remaining_cents, people)

    base["gift_card"] = _from_cents(card_cents)
    base["applied"] = _from_cents(applied_cents)
    base["unused"] = _from_cents(unused_cents)
    base["full_total"] = _from_cents(total_cents)
    base["remaining"] = _from_cents(remaining_cents)
    base["per_person"] = _from_cents(shares[0])
    base["per_person_remaining"] = _from_cents(shares[0])
    base["shares"] = [_from_cents(c) for c in shares]
    return base


def _coerce_fee(fee, name):
    """Validate a flat (dollar) fee and return integer cents.

    Shared by the flat-fee endpoints (a delivery fee, a small-order/service fee).
    A fee is a non-negative finite dollar amount; 0 means no fee, which is allowed
    so the UI can leave the field blank. Distinct from the percentage coercers
    (`_coerce_percent`/`_coerce_tax`): a fee is an absolute amount, not a rate, so
    it carries no upper bound. Raises ValueError on anything invalid so the API
    surfaces a clean 400 rather than a 500.
    """
    if isinstance(fee, bool):
        raise ValueError("%s must be a number" % name)
    try:
        amount = float(fee)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number" % name)
    if amount != amount or amount in (float("inf"), float("-inf")):  # NaN / inf
        raise ValueError("%s must be a finite number" % name)
    if amount < 0:
        raise ValueError("%s must not be negative" % name)
    return _to_cents(amount)


def delivery_order(bill, tip_percent, delivery_fee=0, service_fee=0, people=1,
                   tax_percent=0, round_total=False, tip_on="pretax"):
    """Full breakdown for a delivery / takeout order carrying flat fees.

    Food-delivery and takeout orders carry surcharges the restaurant-bill
    endpoints don't model: a fixed delivery fee and an optional small-order /
    service fee, both expressed in DOLLARS rather than as a percentage (so unlike
    `service_charge_bill`, whose service charge is a percent). Tax is figured on
    the food subtotal only — the platform's flat fees are not taxed here — and the
    tip is figured on the food subtotal (or the post-tax amount when
    tip_on="posttax"), since drivers are tipped on the food, never on the fees.
    The grand total is subtotal + tax + delivery fee + service fee + tip, split
    fairly across `people`.

    When `round_total` is truthy the grand total is rounded UP to the next whole
    dollar and the extra cents are absorbed into the tip, exactly as in
    `calculate_bill`. Every per-person breakdown is produced with `split_amount`,
    so each sums back exactly to its whole.

    Raises ValueError on any invalid input. Returns a dict with: subtotal, tax,
    tax_percent, delivery_fee, service_fee, fees (delivery + service), tip,
    tip_percent, total, people, per_person, per_person_tip, per_person_tax,
    per_person_fees, shares, tip_on, and rounded.
    """
    bill_cents, tip_percent, people = _validate_common(bill, tip_percent, people)
    tax_percent = _coerce_tax(tax_percent)
    if tip_on not in TIP_BASES:
        raise ValueError("tip_on must be 'pretax' or 'posttax'")
    delivery_cents = _coerce_fee(delivery_fee, "delivery_fee")
    service_cents = _coerce_fee(service_fee, "service_fee")

    tax_cents = int(round(bill_cents * tax_percent / 100.0))
    tip_base = bill_cents if tip_on == "pretax" else bill_cents + tax_cents
    tip_cents = int(round(tip_base * tip_percent / 100.0))
    fees_cents = delivery_cents + service_cents
    total_cents = bill_cents + tax_cents + fees_cents + tip_cents

    rounded = bool(round_total)
    if rounded:
        bumped = int(math.ceil(total_cents / 100.0)) * 100
        tip_cents += bumped - total_cents
        total_cents = bumped

    total_shares = split_amount(total_cents, people)
    tip_shares = split_amount(tip_cents, people)
    tax_shares = split_amount(tax_cents, people)
    fees_shares = split_amount(fees_cents, people)

    return {
        "subtotal": _from_cents(bill_cents),
        "tax": _from_cents(tax_cents),
        "tax_percent": round(tax_percent, 4),
        "delivery_fee": _from_cents(delivery_cents),
        "service_fee": _from_cents(service_cents),
        "fees": _from_cents(fees_cents),
        "tip": _from_cents(tip_cents),
        "tip_percent": round(tip_percent, 4),
        "total": _from_cents(total_cents),
        "people": people,
        "per_person": _from_cents(total_shares[0]),
        "per_person_tip": _from_cents(tip_shares[0]),
        "per_person_tax": _from_cents(tax_shares[0]),
        "per_person_fees": _from_cents(fees_shares[0]),
        "shares": [_from_cents(c) for c in total_shares],
        "tip_on": tip_on,
        "rounded": rounded,
    }


def _coerce_percent_shares(shares):
    """Validate explicit per-person percentage shares that must sum to 100.

    Unlike weights (which are RELATIVE proportions, see `_coerce_weights`), a
    percentage-share split assigns each person an ABSOLUTE percentage of the bill
    and the percentages must add up to 100 (e.g. [50, 30, 20]). Accepts any
    non-empty list/tuple of numbers, each in the 0..100 range, whose sum is 100
    within a small floating-point tolerance. Returns them as a plain list of
    floats. Raises ValueError on anything invalid so the API returns a clean 400.
    """
    if isinstance(shares, (str, bytes)) or not isinstance(shares, (list, tuple)):
        raise ValueError("percent_shares must be a list of numbers")
    if not shares:
        raise ValueError("percent_shares must not be empty")
    cleaned = []
    for s in shares:
        if isinstance(s, bool):
            raise ValueError("percent_shares must be a list of numbers")
        try:
            value = float(s)
        except (TypeError, ValueError):
            raise ValueError("percent_shares must be a list of numbers")
        if value != value or value < 0 or value > 100:  # NaN or out of range
            raise ValueError("each percent share must be between 0 and 100")
        cleaned.append(value)
    if abs(sum(cleaned) - 100.0) > 1e-6:
        raise ValueError("percent_shares must sum to 100")
    return cleaned


def split_by_percentage(bill, tip_percent, percent_shares, tax_percent=0,
                        round_total=False, tip_on="pretax"):
    """Split a full bill by explicit per-person percentages summing to 100.

    Where `split_bill_by_weights` takes RELATIVE weights, this takes ABSOLUTE
    percentages of the bill — one per person, validated to add up to 100 (e.g.
    [50, 30, 20] means the first person covers half). The number of people is the
    number of percentages. The full bill (subtotal + tax + tip) is computed via
    `calculate_bill`, then the grand total and the tip portion are each
    apportioned with `split_weighted` using the percentages as weights, so both
    sum back EXACTLY to their whole while landing as close as possible to the
    requested split.

    Raises ValueError on any invalid input (see `_coerce_percent_shares`).
    Returns the `calculate_bill` dict plus: percent_shares (the normalised list),
    shares (per-person grand total), and tip_shares (per-person tip).
    """
    percent_shares = _coerce_percent_shares(percent_shares)
    result = calculate_bill(bill, tip_percent, len(percent_shares), tax_percent,
                            round_total, tip_on)
    total_cents = _to_cents(result["total"])
    tip_cents = _to_cents(result["tip"])
    shares = split_weighted(total_cents, percent_shares)
    tip_shares = split_weighted(tip_cents, percent_shares)
    result["percent_shares"] = percent_shares
    result["shares"] = [_from_cents(c) for c in shares]
    result["tip_shares"] = [_from_cents(c) for c in tip_shares]
    return result


def _coerce_assignments(assignments, n_items):
    """Validate a per-item assignment list and return it normalised.

    `assignments` runs parallel to the item list: entry i names which diners
    share item i, as a list/tuple of 0-based person indices. An empty list or
    None means the item is shared by EVERYONE at the table. Returns a list of
    length `n_items` whose entries are either None (shared by all) or a non-empty
    list of de-duplicated, sorted, non-negative integer indices. Raises
    ValueError on anything invalid so the API returns a clean 400.
    """
    if isinstance(assignments, (str, bytes)) or not isinstance(assignments, (list, tuple)):
        raise ValueError("assignments must be a list, one entry per item")
    if len(assignments) != n_items:
        raise ValueError("assignments must have one entry per item")
    out = []
    for entry in assignments:
        if entry is None:
            out.append(None)
            continue
        if isinstance(entry, (str, bytes)) or not isinstance(entry, (list, tuple)):
            raise ValueError("each assignment must be a list of person indices")
        seen = set()
        for idx in entry:
            if isinstance(idx, bool):
                raise ValueError("person indices must be whole numbers")
            try:
                value = float(idx)
            except (TypeError, ValueError):
                raise ValueError("person indices must be whole numbers")
            if value != value or value != int(value):  # NaN or non-integer
                raise ValueError("person indices must be whole numbers")
            i = int(value)
            if i < 0:
                raise ValueError("person indices must be non-negative")
            seen.add(i)
        # An empty index list means the same as None: shared by the whole table.
        out.append(sorted(seen) if seen else None)
    return out


def split_by_assignment(items, assignments, tip_percent, people=None,
                        tax_percent=0, round_total=False, tip_on="pretax"):
    """Split a bill by assigning each item to the specific diners who shared it.

    The finest-grained split: where `split_by_items` gives each person their own
    order and `split_shared_items` divides communal items across the WHOLE table,
    this assigns every item to an explicit subset of diners. `items` is a flat
    list of item costs and `assignments` runs parallel to it — entry i lists the
    0-based indices of the diners who shared item i (an empty list or None means
    the item is shared by everyone). Each item's cost is divided evenly and
    fairly (via `split_amount`) among only its assignees, building each person's
    pre-tax subtotal. Tax and tip are then figured on the whole bill via
    `calculate_bill` and apportioned to each diner in proportion to that subtotal
    with `split_weighted`, so everyone pays tax and tip on exactly their share
    and the per-person totals sum back to the grand total.

    `people` is the table size; when omitted it is inferred from the largest
    index that appears (so the table is exactly big enough to cover every
    assignment, at least one person). When every subtotal is zero (a fully comped
    table) the tax/tip fall back to an even split. Raises ValueError on any
    invalid input.

    Returns the `calculate_bill` dict plus: assignments (the normalised list,
    with shared items expanded to the full table), breakdown (a per-person list
    of {subtotal, tax, tip, total}), tip_shares (per-person tip), shares
    (per-person grand total), and item_count.
    """
    amounts = _coerce_amounts(items, "items")
    norm = _coerce_assignments(assignments, len(amounts))

    # Largest diner index referenced by any assignment fixes the minimum table.
    max_idx = -1
    for entry in norm:
        if entry:
            max_idx = max(max_idx, entry[-1])

    if people is None:
        people = max_idx + 1 if max_idx >= 0 else 1
    else:
        try:
            people_f = float(people)
        except (TypeError, ValueError):
            raise ValueError("people must be a whole number")
        if people_f != people_f or people_f != int(people_f):  # NaN or non-int
            raise ValueError("people must be a whole number")
        people = int(people_f)
        if people < 1:
            raise ValueError("people must be at least 1")
    if max_idx >= people:
        raise ValueError("assignment refers to a person beyond the table size")

    everyone = list(range(people))
    subtotals_cents = [0] * people
    full_assignments = []
    for amt, entry in zip(amounts, norm):
        assignees = entry if entry else everyone
        full_assignments.append(list(assignees))
        # Divide this item evenly and fairly among only the diners who shared it.
        for share, who in zip(split_amount(_to_cents(amt), len(assignees)),
                              assignees):
            subtotals_cents[who] += share

    bill_cents = sum(subtotals_cents)
    result = calculate_bill(_from_cents(bill_cents), tip_percent, people,
                            tax_percent, round_total, tip_on)
    tax_cents = _to_cents(result["tax"])
    tip_cents = _to_cents(result["tip"])

    # Apportion tax and tip by each diner's share of the pre-tax subtotal.
    weights = subtotals_cents if bill_cents > 0 else [1] * people
    tax_shares = split_weighted(tax_cents, weights)
    tip_shares = split_weighted(tip_cents, weights)

    breakdown = []
    totals = []
    for i in range(people):
        person_total = subtotals_cents[i] + tax_shares[i] + tip_shares[i]
        totals.append(person_total)
        breakdown.append({
            "subtotal": _from_cents(subtotals_cents[i]),
            "tax": _from_cents(tax_shares[i]),
            "tip": _from_cents(tip_shares[i]),
            "total": _from_cents(person_total),
        })

    result["assignments"] = full_assignments
    result["breakdown"] = breakdown
    result["tip_shares"] = [_from_cents(c) for c in tip_shares]
    result["shares"] = [_from_cents(c) for c in totals]
    result["item_count"] = len(amounts)
    return result


class RequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_object(self):
        """Read a JSON object request body, or send a 400 and return None.

        Returns the parsed dict on success. On malformed JSON or a non-object
        body it sends the 400 itself and returns None so callers can simply
        `if data is None: return`.
        """
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "invalid JSON"})
            return None
        if not isinstance(data, dict):
            self._send_json(400, {"error": "invalid JSON"})
            return None
        return data

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            here = os.path.dirname(os.path.abspath(__file__))
            index_path = os.path.join(here, "index.html")
            try:
                with open(index_path, "rb") as f:
                    body = f.read()
            except OSError:
                self._send_json(500, {"error": "index.html not found"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/health":
            self._send_json(200, {"status": "ok"})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/tip":
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                self._send_json(400, {"error": "invalid JSON"})
                return
            if not isinstance(data, dict):
                self._send_json(400, {"error": "invalid JSON"})
                return
            try:
                result = calculate(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("round_total", False),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/presets":
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                data = json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                self._send_json(400, {"error": "invalid JSON"})
                return
            if not isinstance(data, dict):
                self._send_json(400, {"error": "invalid JSON"})
                return
            try:
                suggestions = suggest_tips(
                    data.get("bill"),
                    data.get("people", 1),
                    data.get("percents"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, {"suggestions": suggestions})
            return
        if self.path == "/api/bill":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = calculate_bill(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/split":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = split_bill_by_weights(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("weights"),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/recommend":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = recommend_tip(
                    data.get("bill"),
                    data.get("rating"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/items":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = split_by_items(
                    data.get("items"),
                    data.get("tip_percent"),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/shareditems":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = split_shared_items(
                    data.get("items"),
                    data.get("shared"),
                    data.get("tip_percent", 0),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/discount":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = calculate_with_discount(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("discount"),
                    data.get("discount_kind", "percent"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/target":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = tip_for_total(
                    data.get("bill"),
                    data.get("target_total"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/service":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = service_charge_bill(
                    data.get("bill"),
                    data.get("service_percent"),
                    data.get("tip_percent", 0),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/roundsplit":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = split_round_up_per_person(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/pool":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = distribute_pool(
                    data.get("pool"),
                    data.get("weights"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/cashsplit":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = split_to_denomination(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("denomination", 1.0),
                    data.get("tax_percent", 0),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/perperson":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = tip_from_per_person(
                    data.get("bill"),
                    data.get("per_person_target"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/round":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = round_total_to_nearest(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("round_to", 1.0),
                    data.get("mode", "nearest"),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/receipt":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = format_receipt(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                    data.get("title", "Receipt"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/tipamount":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = tip_from_amount(
                    data.get("bill"),
                    data.get("tip_amount"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/compare":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = compare_scenarios(
                    data.get("bill"),
                    data.get("percents"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/multibill":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = combine_bills(
                    data.get("bills"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/convert":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = convert_currency(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("rate"),
                    data.get("symbol", "$"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/budget":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = tip_within_budget(
                    data.get("bill"),
                    data.get("budget"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("max_tip_percent", 100),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/custom":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = split_custom_tips(
                    data.get("bill"),
                    data.get("tip_percents"),
                    data.get("tax_percent", 0),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/cardfee":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = card_surcharge_bill(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("surcharge_percent"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/comp":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = comp_diner_split(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("comped"),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/settle":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = settle_up(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("paid"),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/guide":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = tip_guide(
                    data.get("bill"),
                    data.get("start", 10),
                    data.get("end", 25),
                    data.get("step", 5),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/extracttax":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = extract_tax_bill(
                    data.get("total_with_tax"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/charity":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = charity_round_up(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("increment", 5),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/mixedpay":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = split_mixed_payment(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("card_payers"),
                    data.get("surcharge_percent", 0),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/category":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = tip_by_category(
                    data.get("categories"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/reconcile":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = settle_payments(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("paid"),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/tiered":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = tiered_tip(
                    data.get("bill"),
                    data.get("brackets"),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/giftcard":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = gift_card_split(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("gift_card"),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/delivery":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = delivery_order(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("delivery_fee", 0),
                    data.get("service_fee", 0),
                    data.get("people", 1),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/percentsplit":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = split_by_percentage(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("percent_shares"),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/assign":
            data = self._read_json_object()
            if data is None:
                return
            try:
                result = split_by_assignment(
                    data.get("items"),
                    data.get("assignments"),
                    data.get("tip_percent"),
                    data.get("people"),
                    data.get("tax_percent", 0),
                    data.get("round_total", False),
                    data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        self._send_json(404, {"error": "not found"})


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(port=0):
    return _Server(("127.0.0.1", port), RequestHandler)


if __name__ == "__main__":
    server = make_server(8000)
    print("Tip calculator (split) server ready on http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
