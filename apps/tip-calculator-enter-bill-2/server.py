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
    a bill so the per-person shares always sum back to the exact total.

    Rejects non-finite values (+/-inf, NaN) and amounts so large that scaling to
    cents would overflow to infinity, raising ValueError so every money endpoint
    surfaces a clean 400 rather than dying with a 500 (OverflowError) inside
    int(round(inf)). This is the single chokepoint every monetary input passes
    through, so guarding it here protects bill/tip/target/budget/pool/item/…
    amounts uniformly."""
    value = float(amount)
    if not math.isfinite(value):
        raise ValueError("amount must be a finite number")
    scaled = value * 100
    if not math.isfinite(scaled):
        raise ValueError("amount is too large")
    return int(round(scaled))


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


# A sane upper bound on how many ways a single bill can be split. Splitting
# beyond this is never a real use case, and the cap is what stops a hostile
# `people` value (e.g. 1_000_000_000) from driving an unbounded
# range(people)/[0]*people allocation that would exhaust memory and hang the
# single process (a memory-exhaustion DoS) instead of returning a clean 400.
MAX_PEOPLE = 10000


def _coerce_people(people):
    """Validate `people` as a whole number in 1..MAX_PEOPLE; return it as int.

    The single source of truth for the people bound, shared by `_validate_common`
    and the item-assignment split so neither path can allocate an unbounded list
    from a hostile request. `None` defaults to 1. Raises ValueError on anything
    invalid so the API surfaces a clean 400 rather than a 500/MemoryError.
    """
    if people is None:
        people = 1
    try:
        people_f = float(people)
    except (TypeError, ValueError):
        raise ValueError("people must be a whole number")
    if people_f != people_f or people_f != int(people_f):  # NaN or non-integer
        raise ValueError("people must be a whole number")
    people = int(people_f)
    if people < 1:
        raise ValueError("people must be at least 1")
    if people > MAX_PEOPLE:
        raise ValueError("people must be at most %d" % MAX_PEOPLE)
    return people


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

    people = _coerce_people(people)

    if bill != bill or tip_percent != tip_percent:  # NaN check
        raise ValueError("bill and tip_percent must be numbers")
    if bill < 0:
        raise ValueError("bill must be non-negative")
    if tip_percent < 0 or tip_percent > 100:
        raise ValueError("tip_percent must be between 0 and 100")

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


def _coerce_happy_hour_items(items):
    """Validate a list of line items, each carrying its OWN optional discount.

    The mirror of the whole-bill coupon: where `/api/discount` knocks a single
    percentage or flat amount off the entire check, this lets every line carry
    its own markdown — the classic "happy hour" bill where the drinks are half
    price while the food stays full price, which one whole-bill discount can
    never express. Each entry is an object with a non-negative `price`, an
    optional `name` label (filled in as "Item N" when missing), an optional
    `discount` (default 0), and an optional `discount_kind` ("percent" off this
    item's price, the default, or "amount" for a flat dollar amount). The
    per-item discount is interpreted by the SAME `_coerce_discount` the
    whole-bill coupon uses, so a flat amount is capped at the item's own price
    and a line can never go negative, and the bounds/messages can never drift.

    Returns a list of (name, price_cents, discount_cents) tuples. Raises
    ValueError on anything invalid so the API surfaces a clean 400.
    """
    if isinstance(items, (str, bytes)) or not isinstance(items, (list, tuple)):
        raise ValueError("items must be a list of line items")
    if not items:
        raise ValueError("items must not be empty")
    cleaned = []
    for i, entry in enumerate(items):
        if not isinstance(entry, dict):
            raise ValueError("each item must be an object with a price")
        price = entry.get("price")
        if isinstance(price, bool) or price is None:
            raise ValueError("each item needs a price")
        try:
            price = float(price)
        except (TypeError, ValueError):
            raise ValueError("item price must be a number")
        if price != price or price < 0:  # NaN or negative
            raise ValueError("item price must be non-negative")
        price_cents = _to_cents(price)
        # Reuse the whole-bill coupon validator: it enforces the kind, rejects a
        # NaN/negative discount, and caps a flat amount at this item's price.
        discount = entry.get("discount", 0)
        kind = entry.get("discount_kind", "percent")
        discount_cents = _coerce_discount(discount, kind, price_cents)
        name = entry.get("name")
        if name is None:
            name = "Item %d" % (i + 1)
        else:
            name = str(name).strip() or ("Item %d" % (i + 1))
        cleaned.append((name, price_cents, discount_cents))
    return cleaned


def happy_hour_bill(items, tip_percent, people=1, tax_percent=0,
                    round_total=False, tip_on="pretax"):
    """A bill with per-item ("happy hour") discounts, then tax + tip + fair split.

    Unlike the whole-bill `/api/discount` and `/api/coupons`, every line item
    can carry its OWN discount (see `_coerce_happy_hour_items`) — the classic
    happy-hour check where the drinks are half price while the food stays full
    price. Each item's discounted price is summed into the subtotal, and tax,
    tip and the fair per-person split are then figured on that DISCOUNTED
    subtotal via `calculate_bill`, so the savings correctly reduce both the tax
    and the tip exactly as a whole-bill coupon does.

    Raises ValueError on any invalid input. Returns the `calculate_bill` dict
    (whose `subtotal` is the discounted subtotal) plus: original_subtotal (the
    bill before any item discounts), total_savings (the dollars knocked off
    across all items), and items (a per-line breakdown of
    {name, price, discount, final}).
    """
    rows = _coerce_happy_hour_items(items)
    original_cents = sum(price for _, price, _ in rows)
    discount_cents = sum(disc for _, _, disc in rows)
    discounted_cents = original_cents - discount_cents

    result = calculate_bill(_from_cents(discounted_cents), tip_percent, people,
                            tax_percent, round_total, tip_on)
    result["original_subtotal"] = _from_cents(original_cents)
    result["total_savings"] = _from_cents(discount_cents)
    result["items"] = [
        {"name": name, "price": _from_cents(price),
         "discount": _from_cents(disc), "final": _from_cents(price - disc)}
        for name, price, disc in rows
    ]
    return result


def _coerce_coupons(coupons, bill_cents):
    """Validate a STACK of coupons and apply them in order to a running subtotal.

    Where `_coerce_discount` handles a single coupon, this handles a sequence:
    `coupons` is a non-empty list of {"kind": "percent"|"amount", "value": number}
    dicts that are applied one after another, exactly like a real register rings
    up several coupons in turn. A "percent" coupon takes that percentage off
    whatever subtotal is left at that point (so two stacked 50%-off coupons leave
    25%, not 0%); an "amount" coupon takes a flat dollar amount off, capped so the
    running subtotal can never drop below zero.

    Returns (applied, final_cents) where `applied` is a list — one entry per
    coupon, in order — of {"kind", "value", "discount" (cents knocked off by that
    coupon), "subtotal_after" (cents remaining after it)}, and `final_cents` is
    the fully discounted subtotal. Raises ValueError on anything invalid so the
    API returns a clean 400.
    """
    if isinstance(coupons, (str, bytes)) or not isinstance(coupons, (list, tuple)):
        raise ValueError("coupons must be a list of coupons")
    if not coupons:
        raise ValueError("coupons must not be empty")

    running = bill_cents
    applied = []
    for coupon in coupons:
        if not isinstance(coupon, dict):
            raise ValueError("each coupon must be an object")
        kind = coupon.get("kind", "percent")
        # Reuse the single-coupon validator against the CURRENT running subtotal so
        # percentages compound and flat amounts are capped at whatever is left.
        discount_cents = _coerce_discount(coupon.get("value"), kind, running)
        running -= discount_cents
        applied.append({
            "kind": kind,
            "value": round(float(coupon.get("value")), 4),
            "discount": _from_cents(discount_cents),
            "subtotal_after": _from_cents(running),
        })
    return applied, running


def apply_coupons(bill, tip_percent, coupons, people=1, tax_percent=0,
                  round_total=False, tip_on="pretax"):
    """Stack a sequence of coupons on the bill, then compute the full breakdown.

    Unlike `/api/discount` (a single coupon), this applies a LIST of coupons in
    order via `_coerce_coupons`: each one reduces the running subtotal, so percent
    coupons compound and flat-amount coupons are capped at whatever is left. Tax
    and tip are then figured on the FINAL discounted subtotal through
    `calculate_bill`, so the whole stack correctly reduces both the tax and the
    tip, and every per-person breakdown keeps the same fair-split guarantees.

    Raises ValueError on any invalid input. Returns the `calculate_bill` dict
    (whose `subtotal` is the fully discounted subtotal) plus: original_subtotal
    (the bill before any coupon), total_discount (dollars knocked off across all
    coupons), and coupons_applied (the per-coupon list from `_coerce_coupons`).
    """
    bill_cents, tip_percent, people = _validate_common(bill, tip_percent, people)
    applied, discounted_cents = _coerce_coupons(coupons, bill_cents)

    result = calculate_bill(_from_cents(discounted_cents), tip_percent, people,
                            tax_percent, round_total, tip_on)
    result["original_subtotal"] = _from_cents(bill_cents)
    result["total_discount"] = _from_cents(bill_cents - discounted_cents)
    result["coupons_applied"] = applied
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


def _coerce_threshold(value):
    """Validate a party-size threshold as a whole number >= 1; return it as int.

    The auto-gratuity rule turns on when the party reaches this size, so the
    threshold must be a positive whole number. Bounded by MAX_PEOPLE for the same
    reason `_coerce_people` is — a hostile value can never drive an unbounded
    allocation downstream. Raises ValueError on anything invalid so the API
    surfaces a clean 400 rather than a 500.
    """
    try:
        value_f = float(value)
    except (TypeError, ValueError):
        raise ValueError("party_threshold must be a whole number")
    if value_f != value_f or value_f != int(value_f):  # NaN or non-integer
        raise ValueError("party_threshold must be a whole number")
    threshold = int(value_f)
    if threshold < 1:
        raise ValueError("party_threshold must be at least 1")
    if threshold > MAX_PEOPLE:
        raise ValueError("party_threshold must be at most %d" % MAX_PEOPLE)
    return threshold


def auto_gratuity_bill(bill, people, party_threshold=6, auto_percent=18,
                       extra_tip_percent=0, tax_percent=0, round_total=False,
                       tip_on="pretax"):
    """Full breakdown for the large-party automatic-gratuity rule.

    Many restaurants add a *mandatory* gratuity (commonly 18%) automatically once
    a party reaches a size threshold (commonly 6 or more), and the guests may
    still leave an *additional* voluntary tip on top. This models exactly that
    rule, which is what makes it distinct from `service_charge_bill`: the auto
    gratuity is applied ONLY when `people >= party_threshold`. Below the
    threshold no auto gratuity is charged and the guests simply leave
    `extra_tip_percent` as their ordinary tip.

    Both the auto gratuity and the extra tip are figured on the base selected by
    `tip_on` (the pre-tax subtotal by default, the post-tax amount when
    "posttax"); `tax` is always figured on the pre-tax subtotal. When
    `round_total` is truthy the grand total is rounded UP to the next whole
    dollar and the extra cents are absorbed into the extra tip, exactly as in
    `service_charge_bill`. Every per-person breakdown is produced with
    `split_amount`, so each sums back exactly to its whole.

    Raises ValueError on any invalid input. Returns a dict with: subtotal, tax,
    tax_percent, auto_gratuity, auto_percent, auto_gratuity_applied,
    party_threshold, tip (the extra voluntary tip), tip_percent, total, people,
    per_person, per_person_gratuity, per_person_tip, per_person_tax, shares,
    tip_on, and rounded.
    """
    # Reuse the shared validator for bill/people; the voluntary extra tip rides
    # the same 0..100 bound as every other tip percent.
    bill_cents, extra_tip_percent, people = _validate_common(
        bill, extra_tip_percent, people)
    auto_percent = _coerce_percent(auto_percent, "auto_percent")
    party_threshold = _coerce_threshold(party_threshold)
    tax_percent = _coerce_tax(tax_percent)

    if tip_on not in TIP_BASES:
        raise ValueError("tip_on must be 'pretax' or 'posttax'")

    tax_cents = int(round(bill_cents * tax_percent / 100.0))
    base_cents = bill_cents if tip_on == "pretax" else bill_cents + tax_cents

    applied = people >= party_threshold
    gratuity_cents = int(round(base_cents * auto_percent / 100.0)) if applied else 0
    tip_cents = int(round(base_cents * extra_tip_percent / 100.0))
    total_cents = bill_cents + tax_cents + gratuity_cents + tip_cents

    rounded = bool(round_total)
    if rounded:
        bumped = int(math.ceil(total_cents / 100.0)) * 100
        tip_cents += bumped - total_cents
        total_cents = bumped

    total_shares = split_amount(total_cents, people)
    gratuity_shares = split_amount(gratuity_cents, people)
    tip_shares = split_amount(tip_cents, people)
    tax_shares = split_amount(tax_cents, people)

    return {
        "subtotal": _from_cents(bill_cents),
        "tax": _from_cents(tax_cents),
        "tax_percent": round(tax_percent, 4),
        "auto_gratuity": _from_cents(gratuity_cents),
        "auto_percent": round(auto_percent, 4),
        "auto_gratuity_applied": applied,
        "party_threshold": party_threshold,
        "tip": _from_cents(tip_cents),
        "tip_percent": round(extra_tip_percent, 4),
        "total": _from_cents(total_cents),
        "people": people,
        "per_person": _from_cents(total_shares[0]),
        "per_person_gratuity": _from_cents(gratuity_shares[0]),
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


def split_items_custom_tips(items, tip_percents, tax_percent=0, tip_on="pretax"):
    """Split a bill where each diner ordered their OWN items AND tips their OWN way.

    The genuine combination of `split_by_items` (each person pays for exactly what
    they ordered) and `split_custom_tips` (each person picks their own tip
    percentage): here every diner has their own itemised subtotal *and* their own
    tip rate. So the diner who ordered the $60 steak and tips 25% covers a very
    different amount from the one who had a $12 salad and tips 10% — on the same
    check.

    `items` is the per-person order (see `_coerce_items`) and fixes the number of
    people; `tip_percents` must carry exactly one rate per person (it cannot fall
    back to the defaults here, since each rate is tied to a specific diner). The
    single `tax_percent` is figured on the whole bill and apportioned to each
    person in proportion to their own pre-tax subtotal with `split_weighted`, so
    the tax shares sum back exactly to the tax. Each person's tip is their own
    percentage applied to their own tip base — their subtotal ("pretax", the
    default) or their subtotal plus their share of the tax ("posttax").

    When every subtotal is zero (a fully comped table) the tax falls back to an
    even split and every tip is zero. Raises ValueError on any invalid input,
    including a `tip_percents` whose length does not match the number of diners.

    Returns a dict with: subtotal, tax, tax_percent, tip (the summed tips), total,
    people, tip_on, per_person (a list, one entry per diner, each with subtotal,
    tax, tip, tip_percent, and total), shares (per-person grand totals), and
    tip_shares (per-person tips).
    """
    people_items = _coerce_items(items)
    percents = _coerce_percents(tip_percents)
    if len(percents) != len(people_items):
        raise ValueError("tip_percents must have one entry per person")
    people = len(people_items)
    tax_percent = _coerce_tax(tax_percent)
    if tip_on not in TIP_BASES:
        raise ValueError("tip_on must be 'pretax' or 'posttax'")

    subtotals_cents = [_to_cents(sum(person)) for person in people_items]
    bill_cents = sum(subtotals_cents)
    tax_cents = int(round(bill_cents * tax_percent / 100.0))

    # Apportion the tax by each person's share of the pre-tax subtotal, falling
    # back to an even split when the whole table is comped (no positive weights).
    weights = subtotals_cents if bill_cents > 0 else [1] * people
    tax_shares = split_weighted(tax_cents, weights)

    per_person = []
    tip_shares = []
    grand_shares = []
    total_tip_cents = 0
    for i, pct in enumerate(percents):
        base_cents = subtotals_cents[i]
        if tip_on == "posttax":
            base_cents += tax_shares[i]
        tip_cents = int(round(base_cents * pct / 100.0))
        total_tip_cents += tip_cents
        person_total = subtotals_cents[i] + tax_shares[i] + tip_cents
        tip_shares.append(tip_cents)
        grand_shares.append(person_total)
        per_person.append({
            "subtotal": _from_cents(subtotals_cents[i]),
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


def _coerce_caps(caps, people):
    """Validate the per-diner contribution caps for `cap_split`.

    `caps` is a list with exactly one entry per diner: the maximum that diner is
    willing/able to put toward the grand total. Each entry is a non-negative
    amount, or null/None to mean that diner has NO cap (they absorb whatever is
    left over). Returns a list of length `people` of integer-cent caps, with None
    preserved for the uncapped diners. Raises ValueError on anything invalid so
    the API surfaces a clean 400 rather than a 500.
    """
    if caps is None:
        raise ValueError("caps are required")
    if isinstance(caps, (str, bytes)) or not isinstance(caps, (list, tuple)):
        raise ValueError("caps must be a list of amounts")
    if len(caps) != people:
        raise ValueError("caps must have exactly one amount per person")
    out = []
    for c in caps:
        if c is None:
            out.append(None)
            continue
        if isinstance(c, bool):
            raise ValueError("caps must be non-negative numbers or null")
        try:
            cv = float(c)
        except (TypeError, ValueError):
            raise ValueError("caps must be non-negative numbers or null")
        if cv != cv or cv < 0:  # NaN or negative
            raise ValueError("caps must be non-negative numbers or null")
        out.append(_to_cents(cv))
    return out


def _cap_fill(total_cents, caps_cents):
    """Water-fill `total_cents` across diners without exceeding any diner's cap.

    Splits the total as evenly as possible with `split_amount`; whenever a
    diner's even share would exceed their (finite) cap, that diner is pinned at
    their cap and the remaining cents are re-split across the diners who still
    have room, repeated until every free diner fits under their cap. `caps_cents`
    is a list of integer-cent caps with None for uncapped diners (who never pin
    and so always absorb whatever is left).

    Assumes the split is feasible (the caller has already rejected the case where
    every diner is capped and the caps fall short of the total). Returns a list
    of integer-cent shares of the same length that sums back exactly to
    `total_cents`.
    """
    n = len(caps_cents)
    shares = [None] * n
    remaining = total_cents
    while True:
        free = [i for i in range(n) if shares[i] is None]
        if not free:
            break
        portions = split_amount(remaining, len(free))
        newly_capped = [
            i for k, i in enumerate(free)
            if caps_cents[i] is not None and portions[k] > caps_cents[i]
        ]
        if not newly_capped:
            for k, i in enumerate(free):
                shares[i] = portions[k]
            break
        for i in newly_capped:
            shares[i] = caps_cents[i]
            remaining -= caps_cents[i]
    return shares


def cap_split(bill, tip_percent, people, caps, tax_percent=0,
              round_total=False, tip_on="pretax"):
    """Split a bill where each diner has a maximum they can contribute.

    Computes the full grand total via `calculate_bill`, then splits it as evenly
    as possible across the `people` diners WITHOUT anyone paying more than their
    own cap. `caps` is a list with exactly one entry per diner: the most that
    diner will put in (a non-negative amount), or null for a diner with no cap
    who simply absorbs whatever is left. Whenever an even share would push a
    diner past their cap they pay only their cap and the shortfall is spread
    across the diners who still have room (a "water-filling" split), repeated
    until everyone fits. The resulting shares always sum back exactly to the
    grand total and differ by at most a cent among the un-capped diners.

    Raises ValueError on any invalid input, or when every diner is capped and the
    caps together fall short of the grand total (nobody can cover the rest).

    Returns the `calculate_bill` dict plus: caps (the normalised caps, null for
    uncapped), shares (each diner's contribution, summing to the total), capped
    (the 1-based positions that were pinned at their cap), and per_person (the
    largest share).
    """
    base = calculate_bill(bill, tip_percent, people, tax_percent, round_total,
                          tip_on)
    people = base["people"]
    caps_cents = _coerce_caps(caps, people)
    total_cents = _to_cents(base["total"])

    finite = [c for c in caps_cents if c is not None]
    if len(finite) == people and sum(finite) < total_cents:
        raise ValueError(
            "the caps total less than the bill; the diners cannot cover it")

    shares = _cap_fill(total_cents, caps_cents)
    capped = [i + 1 for i in range(people)
              if caps_cents[i] is not None and shares[i] >= caps_cents[i]]

    base["caps"] = [None if c is None else _from_cents(c) for c in caps_cents]
    base["shares"] = [_from_cents(c) for c in shares]
    base["capped"] = capped
    base["per_person"] = _from_cents(max(shares)) if shares else 0.0
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
    # A step below ~0.005 rounds to 0 hundredths-of-a-percent; without this guard
    # the loop below never advances and spins forever, hanging the whole server.
    if inc <= 0:
        raise ValueError("step is too small; use at least 0.01")
    # Cap the number of generated rows so a tiny step over a wide range can't
    # amplify into an unbounded number of scenario computations.
    if (stop - cur) // inc > 1000:
        raise ValueError("step is too small for this range; use a larger step")
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
    people = _coerce_people(people)
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


def _coerce_bill_entries(bills):
    """Validate a list of past-bill entries for the multi-visit summary.

    Each entry is an object describing one settled bill: a required `bill` (the
    pre-tax subtotal) and `tip_percent`, plus optional `tax_percent`, `people`,
    `tip_on`, `round_total`, and a free-text `label` for the report row. The
    field values themselves are NOT bounds-checked here — they are validated by
    `calculate_bill` when each entry is computed, so the rules can never drift
    apart between the two code paths. This validator only enforces the shape:
    a non-empty list of objects. Returns a list of normalised dicts (the same
    keys, with defaults filled in and a label of "Bill N" when none is given).
    Raises ValueError on anything invalid so the API surfaces a clean 400.
    """
    if isinstance(bills, (str, bytes)) or not isinstance(bills, (list, tuple)):
        raise ValueError("bills must be a list of bill objects")
    if not bills:
        raise ValueError("bills must not be empty")
    cleaned = []
    for i, b in enumerate(bills):
        if not isinstance(b, dict):
            raise ValueError(
                "each bill must be an object with bill and tip_percent")
        label = b.get("label")
        label = str(label) if label is not None else "Bill %d" % (i + 1)
        cleaned.append({
            "label": label,
            "bill": b.get("bill"),
            "tip_percent": b.get("tip_percent"),
            "tax_percent": b.get("tax_percent", 0),
            "people": b.get("people", 1),
            "tip_on": b.get("tip_on", "pretax"),
            "round_total": b.get("round_total", False),
        })
    return cleaned


def summarize_bills(bills):
    """Aggregate several settled bills into one spending-and-tip report.

    Each entry in `bills` describes one past visit (see `_coerce_bill_entries`)
    and is run through `calculate_bill`, so every figure carries the same tax
    and fair-split semantics as the single-bill endpoint. The per-bill results
    are then summed in integer cents (so no floating-point drift creeps into the
    totals) into the grand totals and averages, plus the blended effective tip
    rate (total tip / total pre-tax subtotal) and the spread of the individual
    tip percentages — a handy "how much did I spend and tip this month?" report.

    Raises ValueError on any invalid input (delegated to `calculate_bill`).
    Returns a dict with: count, total_subtotal, total_tax, total_tip, total (the
    grand total across every bill), average_subtotal, average_tip, average_total,
    average_tip_percent (the blended effective rate), min_tip_percent,
    max_tip_percent, largest_bill / smallest_bill (by pre-tax subtotal), and
    bills (the per-bill list of {label, subtotal, tax, tip, tip_percent, total,
    people}).
    """
    entries = _coerce_bill_entries(bills)
    total_subtotal = total_tax = total_tip = total_total = 0
    per_bill = []
    tip_percents = []
    for e in entries:
        r = calculate_bill(e["bill"], e["tip_percent"], e["people"],
                           e["tax_percent"], e["round_total"], e["tip_on"])
        total_subtotal += _to_cents(r["subtotal"])
        total_tax += _to_cents(r["tax"])
        total_tip += _to_cents(r["tip"])
        total_total += _to_cents(r["total"])
        tip_percents.append(r["tip_percent"])
        per_bill.append({
            "label": e["label"],
            "subtotal": r["subtotal"],
            "tax": r["tax"],
            "tip": r["tip"],
            "tip_percent": r["tip_percent"],
            "total": r["total"],
            "people": r["people"],
        })

    count = len(entries)
    # The blended rate is the only honest "average tip %": a simple mean of the
    # per-bill rates would over-weight tiny bills. Min/max still report the
    # spread of the individual rates.
    blended = (total_tip / total_subtotal * 100.0) if total_subtotal else 0.0
    # Averages are computed on the integer-cent totals and rounded to the cent,
    # so they stay tidy and the per-bill figures still drive the grand totals.
    avg_subtotal = int(round(total_subtotal / count))
    avg_tip = int(round(total_tip / count))
    avg_total = int(round(total_total / count))

    subtotals = [b["subtotal"] for b in per_bill]
    return {
        "count": count,
        "total_subtotal": _from_cents(total_subtotal),
        "total_tax": _from_cents(total_tax),
        "total_tip": _from_cents(total_tip),
        "total": _from_cents(total_total),
        "average_subtotal": _from_cents(avg_subtotal),
        "average_tip": _from_cents(avg_tip),
        "average_total": _from_cents(avg_total),
        "average_tip_percent": round(blended, 4),
        "min_tip_percent": round(min(tip_percents), 4),
        "max_tip_percent": round(max(tip_percents), 4),
        "largest_bill": max(subtotals),
        "smallest_bill": min(subtotals),
        "bills": per_bill,
    }


def _coerce_checks(checks):
    """Validate a list of separate-check entries for `separate_checks`.

    Each entry is an object describing one party at the table that wants its own
    check: a required `bill` (that party's pre-tax subtotal) and `tip_percent`,
    plus optional `tax_percent`, `people`, `tip_on`, `round_total`, and a
    free-text `label` for the row. As with `_coerce_bill_entries`, the field
    values themselves are NOT bounds-checked here — they are validated by
    `calculate_bill` when each check is computed, so the rules can never drift
    between the two code paths. This validator only enforces the shape: a
    non-empty list of objects. Returns a list of normalised dicts (a label of
    "Check N" is filled in when none is given). Raises ValueError on anything
    invalid so the API surfaces a clean 400.
    """
    if isinstance(checks, (str, bytes)) or not isinstance(checks, (list, tuple)):
        raise ValueError("checks must be a list of check objects")
    if not checks:
        raise ValueError("checks must not be empty")
    cleaned = []
    for i, c in enumerate(checks):
        if not isinstance(c, dict):
            raise ValueError(
                "each check must be an object with bill and tip_percent")
        label = c.get("label")
        label = str(label) if label is not None else "Check %d" % (i + 1)
        cleaned.append({
            "label": label,
            "bill": c.get("bill"),
            "tip_percent": c.get("tip_percent"),
            "tax_percent": c.get("tax_percent", 0),
            "people": c.get("people", 1),
            "tip_on": c.get("tip_on", "pretax"),
            "round_total": c.get("round_total", False),
        })
    return cleaned


def separate_checks(checks):
    """Split one table into several SEPARATE checks ("can we get separate checks?").

    Where every other endpoint computes ONE shared check, here each entry in
    `checks` is its own independent bill: each party gets its own pre-tax
    subtotal, sales tax, tip and fair split among that party's own people,
    computed by `calculate_bill` so the tax, tip and rounding semantics are
    identical to the single-check endpoint and can never drift. The per-check
    results are then summed in integer cents (so no floating-point drift creeps
    into the totals) into one table-level aggregate — the whole party's subtotal,
    tax, tip and grand total, the combined head count, and the blended effective
    tip rate (total tip / total pre-tax subtotal) — so the restaurant still sees
    one table total while each party pays its own check.

    Raises ValueError on any invalid input (the shape here, the field values
    delegated to `calculate_bill`). Returns a dict with: count (number of
    checks), people (combined head count across every check), total_subtotal,
    total_tax, total_tip, total (the grand total across every check),
    average_tip_percent (the blended effective rate), and checks (the per-check
    list, each a full `calculate_bill` breakdown — including its own per-person
    shares — with its `label` prepended).
    """
    entries = _coerce_checks(checks)
    total_subtotal = total_tax = total_tip = total_total = 0
    total_people = 0
    per_check = []
    for e in entries:
        r = calculate_bill(e["bill"], e["tip_percent"], e["people"],
                           e["tax_percent"], e["round_total"], e["tip_on"])
        total_subtotal += _to_cents(r["subtotal"])
        total_tax += _to_cents(r["tax"])
        total_tip += _to_cents(r["tip"])
        total_total += _to_cents(r["total"])
        total_people += r["people"]
        check = {"label": e["label"]}
        check.update(r)
        per_check.append(check)

    # The blended rate is the only honest table-wide tip %: a simple mean of the
    # per-check rates would over-weight a tiny check.
    blended = (total_tip / total_subtotal * 100.0) if total_subtotal else 0.0
    return {
        "count": len(entries),
        "people": total_people,
        "total_subtotal": _from_cents(total_subtotal),
        "total_tax": _from_cents(total_tax),
        "total_tip": _from_cents(total_tip),
        "total": _from_cents(total_total),
        "average_tip_percent": round(blended, 4),
        "checks": per_check,
    }


# A server's tip-out can be figured on their net sales (the common practice —
# "tip out 3% of sales to the busser") or on the tips they actually collected.
TIPOUT_BASES = ("sales", "tips")


def _coerce_tipouts(tipouts):
    """Validate a list of support-staff tip-out rules and return it normalised.

    Each entry is a {"role": str, "percent": number} mapping naming a support
    role (busser, bartender, runner, …) and the percentage that role is tipped
    out. The role label is optional and defaults to "support N"; the percent is
    required and validated against the shared 0..100 bounds via `_coerce_percent`
    so the rule can never drift from every other percentage field. Returns a list
    of {"role", "percent"} dicts. Raises ValueError on anything invalid so the
    API surfaces a clean 400 rather than a 500.
    """
    if isinstance(tipouts, (str, bytes)) or not isinstance(tipouts, (list, tuple)):
        raise ValueError("tipouts must be a list of {role, percent} entries")
    if not tipouts:
        raise ValueError("tipouts must not be empty")
    out = []
    for i, entry in enumerate(tipouts):
        if not isinstance(entry, dict):
            raise ValueError("each tipout must be an object with a percent")
        if entry.get("percent") is None:
            raise ValueError("each tipout needs a percent")
        percent = _coerce_percent(entry.get("percent"), "tipout percent")
        role = entry.get("role")
        if role is None:
            role = "support %d" % (i + 1)
        else:
            role = str(role).strip() or ("support %d" % (i + 1))
        out.append({"role": role, "percent": percent})
    return out


def distribute_tipout(sales, tip_total, tipouts, basis="sales"):
    """A server's tip-out: hand part of the collected tips to support staff.

    At close, a server tips out support roles (busser, bartender, runner, …) and
    keeps the rest. Each rule in `tipouts` names a role and a percentage; the
    amount that role receives is `percent` of the chosen `basis`:

      - basis="sales" (default): percent of the server's net `sales`, the common
        restaurant practice ("tip out 3% of sales to the busser");
      - basis="tips":            percent of the `tip_total` the server collected.

    Every amount is computed in integer cents (so the payouts and the server's
    take-home sum back exactly to the tips collected), summed, and subtracted
    from `tip_total`; the server keeps the remainder. Raises ValueError if the
    inputs are invalid or the tip-outs exceed the tips collected — a server
    cannot pay out more than they earned.

    Returns a dict with: sales, tip_total, basis, tipouts (the per-role list of
    {role, percent, amount}), total_tipout, server_keep, and
    server_keep_percent (the share of the tips the server keeps).
    """
    try:
        sales = float(sales)
        tip_total = float(tip_total)
    except (TypeError, ValueError):
        raise ValueError("sales and tip_total must be numbers")
    if sales != sales or tip_total != tip_total:  # NaN check
        raise ValueError("sales and tip_total must be numbers")
    if sales < 0:
        raise ValueError("sales must be non-negative")
    if tip_total < 0:
        raise ValueError("tip_total must be non-negative")
    if basis not in TIPOUT_BASES:
        raise ValueError("basis must be 'sales' or 'tips'")

    rules = _coerce_tipouts(tipouts)
    sales_cents = _to_cents(sales)
    tip_cents = _to_cents(tip_total)
    basis_cents = sales_cents if basis == "sales" else tip_cents

    breakdown = []
    total_tipout = 0
    for rule in rules:
        amount = int(round(basis_cents * rule["percent"] / 100.0))
        total_tipout += amount
        breakdown.append({
            "role": rule["role"],
            "percent": round(rule["percent"], 4),
            "amount": _from_cents(amount),
        })

    if total_tipout > tip_cents:
        raise ValueError("tip-outs exceed the tips collected")

    server_keep = tip_cents - total_tipout
    keep_percent = (server_keep / tip_cents * 100.0) if tip_cents else 0.0
    return {
        "sales": _from_cents(sales_cents),
        "tip_total": _from_cents(tip_cents),
        "basis": basis,
        "tipouts": breakdown,
        "total_tipout": _from_cents(total_tipout),
        "server_keep": _from_cents(server_keep),
        "server_keep_percent": round(keep_percent, 4),
    }


def _coerce_tax_categories(categories):
    """Validate a list of spend categories, each with its own TAX rate.

    The mirror of `_coerce_categories`: where that lets every part of the check
    carry its own *tip* rate, this lets every part carry its own *tax* rate. The
    common example is alcohol being taxed higher than food (many jurisdictions
    levy a separate, steeper liquor/prepared-drink tax), so a single
    `tax_percent` cannot describe the real bill. Each entry is an object with a
    non-negative `amount` and a `tax_percent` in 0..100, plus an optional `name`
    for the label. A missing name is filled in as "Category N". Returns a list of
    (name, amount_float, tax_percent_float) tuples. Raises ValueError on anything
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
                "each category must be an object with amount and tax_percent")
        amount = c.get("amount")
        tax_percent = c.get("tax_percent")
        if amount is None or tax_percent is None:
            raise ValueError("each category needs amount and tax_percent")
        if isinstance(amount, bool) or isinstance(tax_percent, bool):
            raise ValueError("category amount and tax_percent must be numbers")
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise ValueError("category amount and tax_percent must be numbers")
        if amount != amount:  # NaN
            raise ValueError("category amount and tax_percent must be numbers")
        if amount < 0:
            raise ValueError("category amount must be non-negative")
        # Reuse the shared 0..100 percentage validator so per-category tax can
        # never drift from every other percentage field in the app.
        tax_percent = _coerce_percent(tax_percent, "category tax_percent")
        name = c.get("name")
        name = str(name) if name is not None else "Category %d" % (i + 1)
        cleaned.append((name, amount, tax_percent))
    return cleaned


def multi_rate_tax_bill(categories, tip_percent, people=1, round_total=False,
                        tip_on="pretax"):
    """Tax each part of a bill at its own rate, then tip and split fairly.

    The mirror of `tip_by_category`: where that applies a different *tip* rate to
    each spend category under one tax rate, this applies a different *tax* rate to
    each category under one tip. Real checks need this when, say, the bar tab is
    taxed at a higher liquor rate than the food. The category amounts sum to the
    pre-tax subtotal; each category's tax is figured on its own amount at its own
    rate and the taxes are summed.

    `tip_on` chooses whether the single `tip_percent` is figured on the pre-tax
    subtotal ("pretax", the default and common etiquette) or on the post-tax
    amount ("posttax"), exactly as in `calculate_bill`. The grand total
    (subtotal + total tax + tip) is split fairly across `people` with the same
    integer-cent guarantees as `calculate`.

    When `round_total` is truthy the grand total is rounded UP to the next whole
    dollar and the extra cents are absorbed into the tip, exactly as in
    `calculate`. Raises ValueError on any invalid input.

    Returns a `_breakdown` dict (whose `tax_percent` is the effective blended
    rate, total tax / pre-tax subtotal) plus: categories (a per-category list of
    {name, amount, tax_percent, tax}) and rounded (whether the round-up was
    applied).
    """
    cats = _coerce_tax_categories(categories)
    # Reuse the shared validator to normalise/bounds-check tip_percent and
    # people; the bill comes from the categories, so pass a zero placeholder.
    _bill_cents, tip_percent, people = _validate_common(0, tip_percent, people)
    if tip_on not in TIP_BASES:
        raise ValueError("tip_on must be 'pretax' or 'posttax'")

    subtotal_cents = 0
    tax_cents = 0
    breakdown = []
    for name, amount, pct in cats:
        amt_cents = _to_cents(amount)
        cat_tax = int(round(amt_cents * pct / 100.0))
        subtotal_cents += amt_cents
        tax_cents += cat_tax
        breakdown.append({
            "name": name,
            "amount": _from_cents(amt_cents),
            "tax_percent": round(pct, 4),
            "tax": _from_cents(cat_tax),
        })

    tip_base = subtotal_cents if tip_on == "pretax" else subtotal_cents + tax_cents
    tip_cents = int(round(tip_base * tip_percent / 100.0))
    total_cents = subtotal_cents + tax_cents + tip_cents

    rounded = bool(round_total)
    if rounded:
        bumped = int(math.ceil(total_cents / 100.0)) * 100
        tip_cents += bumped - total_cents
        total_cents = bumped

    effective_tax = (tax_cents / subtotal_cents * 100.0) if subtotal_cents else 0.0
    return _breakdown(subtotal_cents, tip_cents, tax_cents, total_cents, people,
                      tip_percent, effective_tax, tip_on,
                      extra={"categories": breakdown, "rounded": rounded})


def _coerce_rate(value, name):
    """Validate a non-negative finite rate and return it as a float.

    Shared by the loyalty endpoint for the two conversion rates it carries: the
    points-earned-per-dollar `earn_rate` and the dollars-per-point `point_value`.
    Unlike `_coerce_percent`/`_coerce_tax` a rate is not a percentage, so it
    carries no 0–100 ceiling; it must simply be a non-negative finite number
    (0 is allowed so a program can disable earning or redemption). Raises
    ValueError on anything invalid so the API surfaces a clean 400.
    """
    if isinstance(value, bool):
        raise ValueError("%s must be a number" % name)
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number" % name)
    if num != num or num in (float("inf"), float("-inf")):  # NaN / inf
        raise ValueError("%s must be a finite number" % name)
    if num < 0:
        raise ValueError("%s must not be negative" % name)
    return num


def _coerce_points(value, name):
    """Validate a whole, non-negative points quantity and return an int.

    Loyalty points are counted in whole units — you cannot earn, hold, or redeem
    a fraction of a point — so the value must be a non-negative finite WHOLE
    number (0 is allowed so the UI can leave the field blank). Distinct from
    `_coerce_rate` (a continuous rate) and `_coerce_people` (which has a sane
    upper cap): a points balance has no natural ceiling. Raises ValueError on
    anything invalid so the API surfaces a clean 400.
    """
    if isinstance(value, bool):
        raise ValueError("%s must be a number" % name)
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number" % name)
    if num != num or num in (float("inf"), float("-inf")):  # NaN / inf
        raise ValueError("%s must be a finite number" % name)
    if num < 0:
        raise ValueError("%s must not be negative" % name)
    if num != int(num):
        raise ValueError("%s must be a whole number of points" % name)
    return int(num)


def loyalty_rewards(bill, tip_percent, people=1, earn_rate=1.0, point_value=0.01,
                    redeem_points=0, balance=0, tax_percent=0, round_total=False,
                    tip_on="pretax"):
    """Full bill plus a loyalty-points accrual and redemption.

    Models a restaurant rewards program layered on the standard bill. Two things
    happen at the register:

    * EARN — the diner earns `earn_rate` points per pre-tax dollar of subtotal
      (net food sales, the common practice; tax and tip never earn points),
      truncated to a whole number of points.
    * REDEEM — up to `redeem_points` already-banked points (never more than the
      starting `balance`) are spent at `point_value` dollars each against the
      grand total, exactly like store credit. The cash value applied is capped at
      the grand total so the bill never goes negative, and only whole points whose
      value actually fits are spent; any points left unspent are reported as
      `unused_points` and stay in the balance.

    The grand total, tax and tip come straight from `calculate_bill` — redemption
    does NOT shrink the taxable base, so points behave like a gift card (see
    `gift_card_split`), not a discount. Only the balance remaining after
    redemption is owed and split fairly across `people` with `split_amount`. The
    new points balance is the starting balance minus the points actually redeemed
    plus the points just earned.

    Returns the `calculate_bill` dict (whose `per_person`/`shares` are REPLACED by
    the split of the remaining balance) plus: earn_rate, point_value,
    points_earned, points_redeemed, redemption_value, unused_points, balance (the
    starting balance), new_balance, full_total, remaining, and
    per_person_remaining. Raises ValueError on any invalid input.
    """
    base = calculate_bill(bill, tip_percent, people, tax_percent, round_total,
                          tip_on)
    earn_rate = _coerce_rate(earn_rate, "earn_rate")
    point_value = _coerce_rate(point_value, "point_value")
    redeem_points = _coerce_points(redeem_points, "redeem_points")
    balance = _coerce_points(balance, "balance")

    if redeem_points > balance:
        raise ValueError("cannot redeem more points than the balance")

    people = base["people"]
    subtotal_cents = _to_cents(base["subtotal"])
    total_cents = _to_cents(base["total"])

    # EARN on the pre-tax subtotal only; whole points, truncated down.
    points_earned = int(subtotal_cents / 100.0 * earn_rate)

    # REDEEM: each point is worth `point_value` dollars. The cash applied is
    # capped at the grand total, and only whole points whose value fits are spent.
    point_value_cents = point_value * 100.0
    if point_value_cents <= 0 or redeem_points == 0:
        points_redeemed = 0
        applied_cents = 0
    else:
        desired_cents = int(round(redeem_points * point_value_cents))
        if desired_cents <= total_cents:
            points_redeemed = redeem_points
            applied_cents = desired_cents
        else:
            # The total can't absorb the full redemption; spend only the whole
            # points that fit, leaving the rest banked.
            points_redeemed = int(total_cents // point_value_cents)
            applied_cents = int(round(points_redeemed * point_value_cents))
            if applied_cents > total_cents:  # float-rounding guard
                applied_cents = total_cents

    unused_points = redeem_points - points_redeemed
    remaining_cents = total_cents - applied_cents
    new_balance = balance - points_redeemed + points_earned

    shares = split_amount(remaining_cents, people)

    base["earn_rate"] = round(earn_rate, 4)
    base["point_value"] = round(point_value, 4)
    base["points_earned"] = points_earned
    base["points_redeemed"] = points_redeemed
    base["redemption_value"] = _from_cents(applied_cents)
    base["unused_points"] = unused_points
    base["balance"] = balance
    base["new_balance"] = new_balance
    base["full_total"] = _from_cents(total_cents)
    base["remaining"] = _from_cents(remaining_cents)
    base["per_person"] = _from_cents(shares[0])
    base["per_person_remaining"] = _from_cents(shares[0])
    base["shares"] = [_from_cents(c) for c in shares]
    return base


# Conventional restaurant-tipping norms by country/region. Tipping etiquette
# varies enormously around the world — what is generous in one place can be
# unheard of (or even mildly insulting) in another — so a tool used by
# travellers should map a destination to its LOCAL custom rather than blindly
# applying a US-style 18-20% everywhere. Each entry records the conventional tip
# PERCENTAGE for decent sit-down service, a `custom` level describing the social
# expectation, and a short human-readable note. Distinct from SERVICE_RATINGS /
# recommend_tip, which varies the tip by how GOOD the service was; this varies
# it by WHERE you are dining.
COUNTRY_TIP_NORMS = {
    "united states": {"percent": 18, "custom": "customary",
                      "note": "15-20% expected; servers rely on tips."},
    "canada": {"percent": 15, "custom": "customary",
               "note": "15-20% expected for table service."},
    "united kingdom": {"percent": 12.5, "custom": "optional",
                       "note": "10-15% when service isn't already included."},
    "france": {"percent": 5, "custom": "optional",
               "note": "Service compris by law; round up or leave a little."},
    "germany": {"percent": 10, "custom": "customary",
                "note": "Round up or add ~5-10%, handed to the server directly."},
    "italy": {"percent": 10, "custom": "optional",
              "note": "Coperto often covers service; a small extra is welcome."},
    "spain": {"percent": 7, "custom": "optional",
              "note": "Not expected; rounding up or 5-10% is generous."},
    "japan": {"percent": 0, "custom": "not expected",
              "note": "Tipping is not customary and can cause confusion."},
    "china": {"percent": 0, "custom": "not expected",
              "note": "Tipping is not traditional in most restaurants."},
    "australia": {"percent": 10, "custom": "optional",
                  "note": "Not expected; 10% for good service is appreciated."},
    "mexico": {"percent": 12, "custom": "customary",
               "note": "10-15% expected for table service."},
    "india": {"percent": 10, "custom": "customary",
              "note": "10% is standard if no service charge is added."},
    "brazil": {"percent": 10, "custom": "customary",
               "note": "A 10% service charge is usually added to the bill."},
}

# Common short names / abbreviations mapped to their canonical COUNTRY_TIP_NORMS
# key, so a caller can pass "usa", "uk", "us", "britain", … and still resolve to
# the right norm. Keys here are matched case- and whitespace-insensitively.
COUNTRY_ALIASES = {
    "usa": "united states",
    "us": "united states",
    "u.s.": "united states",
    "u.s.a.": "united states",
    "america": "united states",
    "uk": "united kingdom",
    "u.k.": "united kingdom",
    "britain": "united kingdom",
    "great britain": "united kingdom",
    "england": "united kingdom",
}


def _resolve_country(country):
    """Normalise a caller-supplied country name to a canonical COUNTRY_TIP_NORMS key.

    Matches case- and whitespace-insensitively and accepts the common
    abbreviations in COUNTRY_ALIASES ("usa", "uk", …). Raises ValueError on a
    missing or unknown country so the API surfaces a clean 400.
    """
    if country is None:
        raise ValueError("country is required")
    try:
        key = str(country).strip().lower()
    except (TypeError, ValueError):
        raise ValueError("country must be a string")
    key = COUNTRY_ALIASES.get(key, key)
    if key not in COUNTRY_TIP_NORMS:
        raise ValueError(
            "country must be one of: " + ", ".join(sorted(COUNTRY_TIP_NORMS)))
    return key


def tip_by_country(bill, country, people=1, tax_percent=0, round_total=False,
                   tip_on="pretax"):
    """Recommend a full bill breakdown using a country's local tipping custom.

    Maps a `country` name (see COUNTRY_TIP_NORMS, plus the abbreviations in
    COUNTRY_ALIASES) to the tip percentage conventional there for decent
    sit-down service, then defers entirely to `calculate_bill`, so the result
    carries the same tax handling and fair-split guarantees. Built for travellers
    who want to tip like a local rather than apply one rate everywhere.

    `country` is matched case- and whitespace-insensitively. Raises ValueError on
    an unknown country or any invalid bill / people / tax input.

    Returns the `calculate_bill` dict plus `country` (the normalised key),
    `recommended_percent` (the percentage applied), `custom` (the social
    expectation: "customary", "optional", or "not expected"), and `note` (a short
    human-readable etiquette tip).
    """
    key = _resolve_country(country)
    norm = COUNTRY_TIP_NORMS[key]
    percent = norm["percent"]
    result = calculate_bill(bill, percent, people, tax_percent, round_total,
                            tip_on)
    result["country"] = key
    result["recommended_percent"] = percent
    result["custom"] = norm["custom"]
    result["note"] = norm["note"]
    return result


def _coerce_round_index(value, name):
    """Validate a 0-based diner index (a whole number >= 0) used by a round.

    Shared by the participant and buyer fields of `_coerce_rounds` so the two
    can never disagree about what a valid seat reference is. Rejects booleans
    (so True/False can't masquerade as 1/0), NaN, and non-integers. Raises
    ValueError on anything invalid so the API surfaces a clean 400.
    """
    if isinstance(value, bool):
        raise ValueError("%s must be a whole number" % name)
    try:
        idx_f = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a whole number" % name)
    if idx_f != idx_f or idx_f != int(idx_f):  # NaN or non-integer
        raise ValueError("%s must be a whole number" % name)
    idx = int(idx_f)
    if idx < 0:
        raise ValueError("%s must be 0 or greater" % name)
    return idx


def _coerce_rounds(rounds):
    """Validate a list of drink "rounds" for `buy_rounds`.

    `rounds` is a non-empty list of round objects. Each round has:
      - `amount`       (required) the round's pre-tax cost, a non-negative number;
      - `participants` (optional) a list of 0-based diner indices who shared that
        round — omitted/empty means the whole table split it;
      - `buyer`        (optional) the 0-based index of the diner who fronted the
        round at the bar — omitted means no one has paid it yet;
      - `label`        (optional) a name for the round, defaulting to "Round N".

    A round may not list the same diner twice. Returns (rows, max_index) where
    `rows` is a list of normalised dicts {label, amount_cents, participants (a
    list of indices or None for "everyone"), buyer (an index or None)} and
    `max_index` is the largest diner index any round references (or -1 if none),
    which is used to size the table. Raises ValueError on anything invalid so the
    API surfaces a clean 400.
    """
    if isinstance(rounds, (str, bytes)) or not isinstance(rounds, (list, tuple)):
        raise ValueError("rounds must be a list of round objects")
    if not rounds:
        raise ValueError("rounds must not be empty")
    rows = []
    max_index = -1
    for i, entry in enumerate(rounds):
        if not isinstance(entry, dict):
            raise ValueError("each round must be an object with an amount")
        amount = entry.get("amount")
        if isinstance(amount, bool) or amount is None:
            raise ValueError("each round needs an amount")
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            raise ValueError("round amount must be a number")
        if amount != amount or amount < 0:  # NaN or negative
            raise ValueError("round amount must be non-negative")
        amount_cents = _to_cents(amount)

        participants = entry.get("participants")
        if participants is None or (
                isinstance(participants, (list, tuple)) and not participants):
            participants = None  # "everyone" — resolved against the table later
        elif isinstance(participants, (list, tuple)):
            seen = set()
            cleaned = []
            for p in participants:
                idx = _coerce_round_index(p, "participant")
                if idx in seen:
                    raise ValueError("a round must not list a diner twice")
                seen.add(idx)
                cleaned.append(idx)
                max_index = max(max_index, idx)
            participants = cleaned
        else:
            raise ValueError("participants must be a list of diner indices")

        buyer = entry.get("buyer")
        if buyer is not None:
            buyer = _coerce_round_index(buyer, "buyer")
            max_index = max(max_index, buyer)

        label = entry.get("label")
        if label is None:
            label = "Round %d" % (i + 1)
        else:
            label = str(label).strip() or ("Round %d" % (i + 1))

        rows.append({
            "label": label,
            "amount_cents": amount_cents,
            "participants": participants,
            "buyer": buyer,
        })
    return rows, max_index


def buy_rounds(rounds, tip_percent, people=None, tax_percent=0,
               round_total=False, tip_on="pretax"):
    """Split a night of drinks bought in ROUNDS, then settle who owes whom.

    Models a bar tab built up over a sequence of rounds where both who is
    drinking and who is paying change from round to round — the classic "we took
    turns buying rounds, now sort out the damage" night that none of the other
    splitters capture. `rounds` is a list of round objects (see `_coerce_rounds`):
    each carries an `amount`, the subset of diners who shared it (`participants`,
    defaulting to the whole table) and, optionally, the diner who fronted it at
    the bar (`buyer`).

    Each round's cost is divided evenly and fairly among only its participants
    (via `split_amount`), building every diner's pre-tax CONSUMPTION. Tax and tip
    are then figured on the whole tab via `calculate_bill` and apportioned to each
    diner in proportion to their consumption with `split_weighted`, so everyone
    pays tax and tip on exactly what they drank — the same apportionment as
    `split_by_items`. What each diner OWES is their consumption plus their tax and
    tip share; what they have already PAID is the sum of the rounds they bought.

    The balances (owed - paid) are then squared up into the fewest diner-to-diner
    transfers using the same greedy largest-first matching as `settle_payments`.
    Buyers front the pre-tax round amounts, so the table still owes the house the
    tax and tip; that residual cannot be settled internally and is surfaced as
    `outstanding` (positive: still owed to the venue), exactly as in
    `settle_payments`.

    `people` is the table size; when omitted it is inferred from the largest diner
    index any round references (at least one person). When nobody drank anything
    (a fully comped tab) the tax/tip fall back to an even split. Raises ValueError
    on any invalid input or when a round references a diner beyond the table size.

    Returns the `calculate_bill` dict (whose `subtotal` is the whole tab) plus:
    rounds (a per-round breakdown of {label, amount, participants, buyer,
    per_participant}), breakdown (a per-diner list of {consumption, tax, tip,
    owed, paid, balance}), consumption / owed / paid / balances (per-diner lists),
    transfers ({from, to, amount} using 1-based diner numbers, largest first),
    transfer_count, total_paid, and outstanding.
    """
    rows, max_index = _coerce_rounds(rounds)

    if people is None:
        people = max_index + 1 if max_index >= 0 else 1
    people = _coerce_people(people)
    if max_index >= people:
        raise ValueError("a round refers to a diner beyond the table size")

    everyone = list(range(people))
    consumption_cents = [0] * people
    paid_cents = [0] * people
    rounds_out = []
    for row in rows:
        participants = row["participants"] if row["participants"] else everyone
        shares = split_amount(row["amount_cents"], len(participants))
        for share, who in zip(shares, participants):
            consumption_cents[who] += share
        if row["buyer"] is not None:
            paid_cents[row["buyer"]] += row["amount_cents"]
        rounds_out.append({
            "label": row["label"],
            "amount": _from_cents(row["amount_cents"]),
            "participants": list(participants),
            "buyer": (row["buyer"] + 1) if row["buyer"] is not None else None,
            "per_participant": _from_cents(shares[0]),
        })

    bill_cents = sum(consumption_cents)
    result = calculate_bill(_from_cents(bill_cents), tip_percent, people,
                            tax_percent, round_total, tip_on)
    tax_cents = _to_cents(result["tax"])
    tip_cents = _to_cents(result["tip"])

    # Apportion tax and tip by each diner's share of the pre-tax consumption.
    weights = consumption_cents if bill_cents > 0 else [1] * people
    tax_shares = split_weighted(tax_cents, weights)
    tip_shares = split_weighted(tip_cents, weights)

    owed_cents = [consumption_cents[i] + tax_shares[i] + tip_shares[i]
                  for i in range(people)]
    balances = [owed_cents[i] - paid_cents[i] for i in range(people)]

    breakdown = []
    for i in range(people):
        breakdown.append({
            "consumption": _from_cents(consumption_cents[i]),
            "tax": _from_cents(tax_shares[i]),
            "tip": _from_cents(tip_shares[i]),
            "owed": _from_cents(owed_cents[i]),
            "paid": _from_cents(paid_cents[i]),
            "balance": _from_cents(balances[i]),
        })

    # Square the diners up with the fewest transfers — identical greedy
    # largest-first matching as settle_payments: match the biggest debtor against
    # the biggest creditor, transfer the smaller of the two, and advance whichever
    # side is now clear. Yields at most people-1 transfers.
    debtors = sorted(((i, b) for i, b in enumerate(balances) if b > 0),
                     key=lambda x: x[1], reverse=True)
    creditors = sorted(((i, -b) for i, b in enumerate(balances) if b < 0),
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

    total_paid_cents = sum(paid_cents)
    result["rounds"] = rounds_out
    result["breakdown"] = breakdown
    result["consumption"] = [_from_cents(c) for c in consumption_cents]
    result["owed"] = [_from_cents(c) for c in owed_cents]
    result["paid"] = [_from_cents(c) for c in paid_cents]
    result["balances"] = [_from_cents(b) for b in balances]
    result["transfers"] = transfers
    result["transfer_count"] = len(transfers)
    result["total_paid"] = _from_cents(total_paid_cents)
    result["outstanding"] = _from_cents(sum(balances))
    result["round_count"] = len(rows)
    return result


def _coerce_intervals(intervals):
    """Validate per-person presence intervals for `split_by_time`.

    `intervals` has one entry per person describing when they were present for a
    rolling tab (a bar session, a shared cab meter, …). Each entry is either:
      - a single ``[start, end]`` pair (two numbers), or
      - a list of ``[start, end]`` pairs, for someone who came and went more than
        once.

    Starts/ends are plain numbers in whatever unit the caller uses (minutes,
    hours, clock offsets); each pair must have ``end`` strictly after ``start``.
    The shape is disambiguated by the first element of an entry: a number means
    the whole entry is one ``[start, end]`` pair, a list/tuple means the entry is
    a list of such pairs.

    Returns a list (one per person) of lists of ``(start, end)`` float tuples.
    Raises ValueError on anything invalid so the API returns a clean 400.
    """
    if isinstance(intervals, (str, bytes)) or not isinstance(
            intervals, (list, tuple)):
        raise ValueError("intervals must be a list, one entry per person")
    if not intervals:
        raise ValueError("intervals must not be empty")

    def _point(value, name):
        if isinstance(value, bool):
            raise ValueError(name + " must be a number")
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError(name + " must be a number")
        if not math.isfinite(v):
            raise ValueError(name + " must be a finite number")
        return v

    def _pair(pair):
        if isinstance(pair, (str, bytes)) or not isinstance(pair, (list, tuple)):
            raise ValueError("each interval must be a [start, end] pair")
        if len(pair) != 2:
            raise ValueError("each interval must be a [start, end] pair")
        start = _point(pair[0], "interval start")
        end = _point(pair[1], "interval end")
        if end <= start:
            raise ValueError("interval end must be after its start")
        return (start, end)

    people_intervals = []
    for entry in intervals:
        if isinstance(entry, (str, bytes)) or not isinstance(
                entry, (list, tuple)):
            raise ValueError(
                "each person's intervals must be a [start, end] pair "
                "or a list of pairs")
        if not entry:
            raise ValueError("each person needs at least one interval")
        # A flat [start, end] (first element is a number) is a single interval;
        # a list/tuple first element means the entry is already a list of pairs.
        if isinstance(entry[0], (list, tuple)):
            pairs = [_pair(p) for p in entry]
        else:
            pairs = [_pair(entry)]
        people_intervals.append(pairs)
    return people_intervals


def split_by_time(bill, tip_percent, intervals, tax_percent=0,
                  round_total=False, tip_on="pretax"):
    """Split a rolling tab by HOW LONG each person was actually there.

    Models the "we kept a shared tab open and people drifted in and out" night
    that none of the other splitters capture: a bar tab, a karaoke room booked by
    the hour, a metered cab. The bill is assumed to accrue uniformly over the
    session, and at any instant its running cost is shared equally among only the
    people present right then — so someone who showed up for the last half hour
    pays for that half hour, split with whoever else was around, and nothing else.

    `intervals` gives each person's presence (see `_coerce_intervals`) and fixes
    the number of people. Every interval endpoint becomes a boundary; between two
    adjacent boundaries the present set is constant, so that slice's cost is split
    evenly among them. Summing each person's slice shares gives their pre-tax
    consumption, which is apportioned exactly with `split_weighted` so the
    per-person subtotals sum back to the bill. Tax and tip are then figured on the
    whole bill via `calculate_bill` and apportioned by that same consumption,
    exactly as in `split_by_items`, so everyone pays tax and tip on just their
    time. Stretches when nobody was present accrue nothing and are skipped.

    When the bill is zero (a fully comped tab) the tax/tip fall back to an even
    split. Raises ValueError on any invalid input.

    Returns the `calculate_bill` dict (whose `subtotal` is the whole tab) plus:
    intervals (the normalised per-person pairs), minutes (each person's raw time
    present), billed_minutes (their time weighted by how many shared each slice —
    the basis for their share), covered_duration (total time anyone was present),
    breakdown (a per-person list of {minutes, billed_minutes, subtotal, tax, tip,
    total}), tip_shares, and shares (per-person grand total).
    """
    people_intervals = _coerce_intervals(intervals)
    people = len(people_intervals)

    # Every endpoint is a boundary; between two adjacent boundaries the set of
    # people present is constant, so each such slice accrues cost at a constant
    # per-head rate.
    boundaries = sorted({pt for pairs in people_intervals
                         for (s, e) in pairs for pt in (s, e)})

    # `billed` is each person's time weighted by how many people shared each
    # slice (their dollar basis); `present` is their raw time on the clock.
    billed = [0.0] * people
    present = [0.0] * people
    covered = 0.0
    for a, b in zip(boundaries, boundaries[1:]):
        d = b - a
        if d <= 0:
            continue
        here = [i for i in range(people)
                if any(s <= a and e >= b for (s, e) in people_intervals[i])]
        if not here:
            continue
        covered += d
        share = d / len(here)
        for i in here:
            billed[i] += share
            present[i] += d

    result = calculate_bill(bill, tip_percent, people, tax_percent,
                            round_total, tip_on)
    bill_cents = _to_cents(result["subtotal"])
    tax_cents = _to_cents(result["tax"])
    tip_cents = _to_cents(result["tip"])

    # The billed weights sum to `covered`, so split_weighted apportions the bill
    # exactly in proportion to each person's shared time on the tab.
    subtotals_cents = split_weighted(bill_cents, billed)

    # Apportion tax and tip by each person's consumption, falling back to an even
    # split only for a wholly comped (zero) bill.
    apportion = subtotals_cents if bill_cents > 0 else [1] * people
    tax_shares = split_weighted(tax_cents, apportion)
    tip_shares = split_weighted(tip_cents, apportion)

    breakdown = []
    totals = []
    for i in range(people):
        person_total = subtotals_cents[i] + tax_shares[i] + tip_shares[i]
        totals.append(person_total)
        breakdown.append({
            "minutes": round(present[i], 4),
            "billed_minutes": round(billed[i], 4),
            "subtotal": _from_cents(subtotals_cents[i]),
            "tax": _from_cents(tax_shares[i]),
            "tip": _from_cents(tip_shares[i]),
            "total": _from_cents(person_total),
        })

    result["intervals"] = [[[s, e] for (s, e) in pairs]
                           for pairs in people_intervals]
    result["minutes"] = [round(m, 4) for m in present]
    result["billed_minutes"] = [round(w, 4) for w in billed]
    result["covered_duration"] = round(covered, 4)
    result["breakdown"] = breakdown
    result["tip_shares"] = [_from_cents(c) for c in tip_shares]
    result["shares"] = [_from_cents(c) for c in totals]
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
        if self.path == "/favicon.ico":
            # Serve an empty 204 so browsers stop logging a 404 for the favicon
            # they auto-request on every page load.
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._send_json(404, {"error": "not found"})

    # Route table: path -> handler(data) -> JSON payload. One declarative entry
    # per endpoint; the shared do_POST wrapper below reads the body, dispatches,
    # and uniformly maps a ValueError to a 400. This replaces ~40 copy-pasted
    # read/try/except/respond blocks with a single reusable code path.
    _POST_ROUTES = {
        "/api/tip": lambda d: calculate(
            d.get("bill"), d.get("tip_percent"), d.get("people", 1),
            d.get("round_total", False)),
        "/api/presets": lambda d: {"suggestions": suggest_tips(
            d.get("bill"), d.get("people", 1), d.get("percents"))},
        "/api/bill": lambda d: calculate_bill(
            d.get("bill"), d.get("tip_percent"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/split": lambda d: split_bill_by_weights(
            d.get("bill"), d.get("tip_percent"), d.get("weights"),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/recommend": lambda d: recommend_tip(
            d.get("bill"), d.get("rating"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/items": lambda d: split_by_items(
            d.get("items"), d.get("tip_percent"), d.get("tax_percent", 0),
            d.get("round_total", False), d.get("tip_on", "pretax")),
        "/api/shareditems": lambda d: split_shared_items(
            d.get("items"), d.get("shared"), d.get("tip_percent", 0),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/discount": lambda d: calculate_with_discount(
            d.get("bill"), d.get("tip_percent"), d.get("discount"),
            d.get("discount_kind", "percent"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/target": lambda d: tip_for_total(
            d.get("bill"), d.get("target_total"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("tip_on", "pretax")),
        "/api/service": lambda d: service_charge_bill(
            d.get("bill"), d.get("service_percent"), d.get("tip_percent", 0),
            d.get("people", 1), d.get("tax_percent", 0),
            d.get("round_total", False), d.get("tip_on", "pretax")),
        "/api/roundsplit": lambda d: split_round_up_per_person(
            d.get("bill"), d.get("tip_percent"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("tip_on", "pretax")),
        "/api/pool": lambda d: distribute_pool(
            d.get("pool"), d.get("weights")),
        "/api/cashsplit": lambda d: split_to_denomination(
            d.get("bill"), d.get("tip_percent"), d.get("people", 1),
            d.get("denomination", 1.0), d.get("tax_percent", 0),
            d.get("tip_on", "pretax")),
        "/api/perperson": lambda d: tip_from_per_person(
            d.get("bill"), d.get("per_person_target"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("tip_on", "pretax")),
        "/api/round": lambda d: round_total_to_nearest(
            d.get("bill"), d.get("tip_percent"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("round_to", 1.0),
            d.get("mode", "nearest"), d.get("tip_on", "pretax")),
        "/api/receipt": lambda d: format_receipt(
            d.get("bill"), d.get("tip_percent"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax"), d.get("title", "Receipt")),
        "/api/tipamount": lambda d: tip_from_amount(
            d.get("bill"), d.get("tip_amount"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("tip_on", "pretax")),
        "/api/compare": lambda d: compare_scenarios(
            d.get("bill"), d.get("percents"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("tip_on", "pretax")),
        "/api/multibill": lambda d: combine_bills(
            d.get("bills"), d.get("tip_percent"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/convert": lambda d: convert_currency(
            d.get("bill"), d.get("tip_percent"), d.get("rate"),
            d.get("symbol", "$"), d.get("people", 1), d.get("tax_percent", 0),
            d.get("round_total", False), d.get("tip_on", "pretax")),
        "/api/budget": lambda d: tip_within_budget(
            d.get("bill"), d.get("budget"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("max_tip_percent", 100),
            d.get("tip_on", "pretax")),
        "/api/custom": lambda d: split_custom_tips(
            d.get("bill"), d.get("tip_percents"), d.get("tax_percent", 0),
            d.get("tip_on", "pretax")),
        "/api/cardfee": lambda d: card_surcharge_bill(
            d.get("bill"), d.get("tip_percent"), d.get("surcharge_percent"),
            d.get("people", 1), d.get("tax_percent", 0),
            d.get("round_total", False), d.get("tip_on", "pretax")),
        "/api/comp": lambda d: comp_diner_split(
            d.get("bill"), d.get("tip_percent"), d.get("people", 1),
            d.get("comped"), d.get("tax_percent", 0),
            d.get("round_total", False), d.get("tip_on", "pretax")),
        "/api/settle": lambda d: settle_up(
            d.get("bill"), d.get("tip_percent"), d.get("people", 1),
            d.get("paid"), d.get("tax_percent", 0),
            d.get("round_total", False), d.get("tip_on", "pretax")),
        "/api/caps": lambda d: cap_split(
            d.get("bill"), d.get("tip_percent"), d.get("people", 1),
            d.get("caps"), d.get("tax_percent", 0),
            d.get("round_total", False), d.get("tip_on", "pretax")),
        "/api/guide": lambda d: tip_guide(
            d.get("bill"), d.get("start", 10), d.get("end", 25),
            d.get("step", 5), d.get("people", 1), d.get("tax_percent", 0),
            d.get("tip_on", "pretax")),
        "/api/extracttax": lambda d: extract_tax_bill(
            d.get("total_with_tax"), d.get("tip_percent"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/charity": lambda d: charity_round_up(
            d.get("bill"), d.get("tip_percent"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("increment", 5),
            d.get("tip_on", "pretax")),
        "/api/mixedpay": lambda d: split_mixed_payment(
            d.get("bill"), d.get("tip_percent"), d.get("people", 1),
            d.get("card_payers"), d.get("surcharge_percent", 0),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/category": lambda d: tip_by_category(
            d.get("categories"), d.get("people", 1), d.get("tax_percent", 0),
            d.get("round_total", False)),
        "/api/reconcile": lambda d: settle_payments(
            d.get("bill"), d.get("tip_percent"), d.get("people", 1),
            d.get("paid"), d.get("tax_percent", 0),
            d.get("round_total", False), d.get("tip_on", "pretax")),
        "/api/tiered": lambda d: tiered_tip(
            d.get("bill"), d.get("brackets"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/giftcard": lambda d: gift_card_split(
            d.get("bill"), d.get("tip_percent"), d.get("people", 1),
            d.get("gift_card"), d.get("tax_percent", 0),
            d.get("round_total", False), d.get("tip_on", "pretax")),
        "/api/delivery": lambda d: delivery_order(
            d.get("bill"), d.get("tip_percent"), d.get("delivery_fee", 0),
            d.get("service_fee", 0), d.get("people", 1),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/percentsplit": lambda d: split_by_percentage(
            d.get("bill"), d.get("tip_percent"), d.get("percent_shares"),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/assign": lambda d: split_by_assignment(
            d.get("items"), d.get("assignments"), d.get("tip_percent"),
            d.get("people"), d.get("tax_percent", 0),
            d.get("round_total", False), d.get("tip_on", "pretax")),
        "/api/summary": lambda d: summarize_bills(d.get("bills")),
        "/api/separate": lambda d: separate_checks(d.get("checks")),
        "/api/tipout": lambda d: distribute_tipout(
            d.get("sales"), d.get("tip_total"), d.get("tipouts"),
            d.get("basis", "sales")),
        "/api/coupons": lambda d: apply_coupons(
            d.get("bill"), d.get("tip_percent"), d.get("coupons"),
            d.get("people", 1), d.get("tax_percent", 0),
            d.get("round_total", False), d.get("tip_on", "pretax")),
        "/api/multitax": lambda d: multi_rate_tax_bill(
            d.get("categories"), d.get("tip_percent"), d.get("people", 1),
            d.get("round_total", False), d.get("tip_on", "pretax")),
        "/api/itemtips": lambda d: split_items_custom_tips(
            d.get("items"), d.get("tip_percents"), d.get("tax_percent", 0),
            d.get("tip_on", "pretax")),
        "/api/loyalty": lambda d: loyalty_rewards(
            d.get("bill"), d.get("tip_percent"), d.get("people", 1),
            d.get("earn_rate", 1.0), d.get("point_value", 0.01),
            d.get("redeem_points", 0), d.get("balance", 0),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/country": lambda d: tip_by_country(
            d.get("bill"), d.get("country"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/autograt": lambda d: auto_gratuity_bill(
            d.get("bill"), d.get("people", 1), d.get("party_threshold", 6),
            d.get("auto_percent", 18), d.get("extra_tip_percent", 0),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/happyhour": lambda d: happy_hour_bill(
            d.get("items"), d.get("tip_percent"), d.get("people", 1),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/rounds": lambda d: buy_rounds(
            d.get("rounds"), d.get("tip_percent"), d.get("people"),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
        "/api/timeshare": lambda d: split_by_time(
            d.get("bill"), d.get("tip_percent"), d.get("intervals"),
            d.get("tax_percent", 0), d.get("round_total", False),
            d.get("tip_on", "pretax")),
    }

    def do_POST(self):
        handler = self._POST_ROUTES.get(self.path)
        if handler is None:
            self._send_json(404, {"error": "not found"})
            return
        data = self._read_json_object()
        if data is None:
            return
        try:
            result = handler(data)
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
            return
        self._send_json(200, result)


class _Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(port=0):
    return _Server(("127.0.0.1", port), RequestHandler)


if __name__ == "__main__":
    port = int(os.environ.get("ADF_SMOKE_PORT") or os.environ.get("PORT") or 8000)
    server = make_server(port)
    print("Tip calculator (split) server ready on http://127.0.0.1:%d" % port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
