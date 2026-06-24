#!/usr/bin/env python3
"""Tip calculator — Python 3 standard library only.

Domain: given a bill amount and tip percent, compute the tip and total, and
split the total across a number of people (REQ-001, REQ-002).

Run:  python3 server.py   (serves http://localhost:8000)
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import html
import math

# ---------------------------------------------------------------------------
# Core domain logic
# ---------------------------------------------------------------------------


class TipError(ValueError):
    """Raised when tip-calculator inputs fail validation (fail-safe path)."""


def _to_number(value, field):
    """Coerce JSON/string input to float, rejecting junk and non-finite values."""
    if isinstance(value, bool):  # bool is an int subclass — disallow explicitly
        raise TipError("%s must be a number" % field)
    if value is None or value == "":
        raise TipError("%s is required" % field)
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise TipError("%s must be a number" % field)
    if num != num or num in (float("inf"), float("-inf")):
        raise TipError("%s must be a finite number" % field)
    return num


def _round2(num):
    """Round to cents using banker's-free half-up-ish round() then 2dp."""
    return round(num + 0.0, 2)


def _validate_people(people):
    """Validate/normalise a people count: a whole number >= 1 (default 1)."""
    if isinstance(people, bool):
        raise TipError("people must be a whole number")
    if people is None or people == "":
        people = 1
    try:
        people_int = int(people)
    except (TypeError, ValueError):
        raise TipError("people must be a whole number")
    if float(people) != people_int:
        raise TipError("people must be a whole number")
    if people_int < 1:
        raise TipError("people must be at least 1")
    return people_int


def _validate_bill_tip_people(bill, tip_percent, people):
    """Validate the common (bill, tip_percent, people) trio: coerce bill/tip to
    numbers, reject negatives, and resolve the people count. Returns the parsed
    ``(bill, tip_percent, people_int)`` trio so callers don't repeat the block."""
    bill = _to_number(bill, "bill")
    tip_percent = _to_number(tip_percent, "tip_percent")
    people_int = _validate_people(people)
    if bill < 0:
        raise TipError("bill must not be negative")
    if tip_percent < 0:
        raise TipError("tip_percent must not be negative")
    return bill, tip_percent, people_int


_TIP_ON_TOTAL = ("total", "posttax", "post-tax", "gross")
_TIP_ON_SUBTOTAL = ("subtotal", "pretax", "pre-tax", "net")


def _normalise_tip_on(tip_on):
    """Resolve the tip-base mode to ``"total"`` or ``"subtotal"`` (REQ-001 extn)."""
    if tip_on is None or tip_on == "":
        return "total"
    if not isinstance(tip_on, str):
        raise TipError("tip_on must be 'total' or 'subtotal'")
    key = tip_on.strip().lower()
    if key in _TIP_ON_TOTAL:
        return "total"
    if key in _TIP_ON_SUBTOTAL:
        return "subtotal"
    raise TipError("tip_on must be 'total' or 'subtotal'")


def calculate_tip(bill, tip_percent, people=1, round_total=False, tax=0, tip_on="total"):
    """Compute the tip, total and per-person split for a bill.

    REQ-001: from bill amount and tip percent, show tip and total.
    REQ-002: split the total across ``people``.

    ``bill`` is the amount printed on the cheque (it already includes any
    ``tax``). When ``tip_on`` is ``"subtotal"`` (aliases: ``pretax``/``net``)
    the gratuity is computed on the pre-tax subtotal ``bill - tax`` rather than
    on the full, tax-inclusive amount — many diners prefer to tip on the food,
    not the tax. ``tip_on`` defaults to ``"total"`` and ``tax`` to ``0`` so the
    historical behaviour is unchanged.

    When ``round_total`` is truthy the grand total is rounded UP to the next
    whole currency unit and the extra is folded into the tip; the resulting
    ``effective_tip_percent`` reflects what was actually tipped.

    Returns a dict with rounded, JSON-friendly values. Raises ``TipError`` on
    invalid input so callers can fail safe with a clear message.
    """
    bill = _to_number(bill, "bill")
    tip_percent = _to_number(tip_percent, "tip_percent")
    people_int = _validate_people(people)
    tax = _to_number(tax, "tax") if tax not in (None, "") else 0.0
    mode = _normalise_tip_on(tip_on)

    if bill < 0:
        raise TipError("bill must not be negative")
    if tip_percent < 0:
        raise TipError("tip_percent must not be negative")
    if tax < 0:
        raise TipError("tax must not be negative")
    if tax > bill:
        raise TipError("tax must not exceed the bill")

    subtotal = bill - tax
    tip_base = subtotal if mode == "subtotal" else bill
    tip = tip_base * tip_percent / 100.0
    total = bill + tip

    round_total = bool(round_total)
    if round_total:
        total = float(math.ceil(round(total, 2)))
        tip = total - bill

    if bill > 0:
        effective = tip / bill * 100.0
    else:
        effective = tip_percent

    tip_per_person = tip / people_int
    total_per_person = total / people_int

    return {
        "bill": _round2(bill),
        "tip_percent": _round2(tip_percent),
        "people": people_int,
        "round_total": round_total,
        "tax": _round2(tax),
        "subtotal": _round2(subtotal),
        "tip_on": mode,
        "tip": _round2(tip),
        "total": _round2(total),
        "effective_tip_percent": _round2(effective),
        "tip_per_person": _round2(tip_per_person),
        "total_per_person": _round2(total_per_person),
    }


def reverse_tip(bill, target_total, people=1):
    """Work backwards from a target grand total to the tip required (REQ-001 extn).

    Answers "I want the bill to come to exactly ``target_total`` — how much do I
    tip, and what percentage is that?". ``target_total`` must be at least the
    ``bill`` (the tip cannot be negative). Returns the tip, the effective tip
    percent and the per-person split so the result can be shared like every
    other view (REQ-002).
    """
    bill = _to_number(bill, "bill")
    target_total = _to_number(target_total, "target_total")
    people_int = _validate_people(people)

    if bill < 0:
        raise TipError("bill must not be negative")
    if target_total < 0:
        raise TipError("target_total must not be negative")
    if target_total < bill:
        raise TipError("target_total must be at least the bill")

    tip = target_total - bill
    if bill > 0:
        effective = tip / bill * 100.0
    else:
        effective = 0.0

    return {
        "bill": _round2(bill),
        "target_total": _round2(target_total),
        "people": people_int,
        "tip": _round2(tip),
        "total": _round2(target_total),
        "effective_tip_percent": _round2(effective),
        "tip_per_person": _round2(tip / people_int),
        "total_per_person": _round2(target_total / people_int),
    }


def round_up_split(bill, tip_percent, people=1, nearest=1.0):
    """Split the total, rounding each diner's share UP to a clean increment.

    Real-world diners like to chip in round numbers. This rounds every
    per-person share up to the next multiple of ``nearest`` (e.g. ``1`` for whole
    dollars, ``0.05`` for nickels). The amount collected therefore meets or
    exceeds the true total; the difference is reported as ``surplus`` (bonus
    tip) and the gratuity actually paid is reflected in
    ``effective_tip_percent`` (REQ-002 extn).
    """
    base = calculate_tip(bill, tip_percent, people)
    nearest = _to_number(nearest, "nearest") if nearest not in (None, "") else 1.0
    if nearest <= 0:
        raise TipError("nearest must be a positive number")

    people_int = base["people"]
    total = base["total"]
    bill_amt = base["bill"]

    # Work in integer cents to avoid binary-float drift in the ceil step.
    step_cents = int(round(nearest * 100))
    if step_cents <= 0:
        raise TipError("nearest must be a positive number")
    raw_cents = total * 100.0 / people_int
    per_person_cents = int(math.ceil(round(raw_cents, 6) / step_cents)) * step_cents

    per_person = per_person_cents / 100.0
    collected = per_person * people_int
    surplus = collected - total
    if bill_amt > 0:
        effective = (collected - bill_amt) / bill_amt * 100.0
    else:
        effective = base["tip_percent"]

    return {
        "bill": bill_amt,
        "tip_percent": base["tip_percent"],
        "people": people_int,
        "nearest": _round2(nearest),
        "total": total,
        "per_person": _round2(per_person),
        "collected": _round2(collected),
        "surplus": _round2(surplus),
        "effective_tip_percent": _round2(effective),
    }


def suggest_tips(bill, people=1, percents=(10, 15, 18, 20, 25)):
    """Return tip/total suggestions for a bill across several tip tiers.

    Useful for one-tap selection. Each tier reuses :func:`calculate_tip` so the
    rounding and split rules stay identical. ``percents`` may be overridden with
    any list of non-negative numbers.
    """
    bill = _to_number(bill, "bill")
    if bill < 0:
        raise TipError("bill must not be negative")
    people_int = _validate_people(people)

    if percents is None or percents == "":
        percents = (10, 15, 18, 20, 25)
    if isinstance(percents, (str, bytes)) or not hasattr(percents, "__iter__"):
        raise TipError("percents must be a list of numbers")

    tiers = []
    for p in percents:
        r = calculate_tip(bill, p, people_int)
        tiers.append({
            "tip_percent": r["tip_percent"],
            "tip": r["tip"],
            "total": r["total"],
            "tip_per_person": r["tip_per_person"],
            "total_per_person": r["total_per_person"],
        })
    return {"bill": _round2(bill), "people": people_int, "tiers": tiers}


def split_by_shares(bill, tip_percent, shares):
    """Split the grand total unevenly across diners by weight (REQ-002 extn).

    ``shares`` is a non-empty list of positive weights (e.g. ``[1, 1, 2]`` for
    three diners where the third pays double). The returned ``amounts`` always
    sum exactly to ``total`` — leftover cents are distributed by the
    largest-remainder method so nobody is over/under charged.
    """
    bill = _to_number(bill, "bill")
    tip_percent = _to_number(tip_percent, "tip_percent")
    if bill < 0:
        raise TipError("bill must not be negative")
    if tip_percent < 0:
        raise TipError("tip_percent must not be negative")

    if isinstance(shares, (str, bytes)) or not hasattr(shares, "__iter__"):
        raise TipError("shares must be a list of numbers")
    shares = list(shares)
    if not shares:
        raise TipError("shares must not be empty")
    weights = [_to_number(s, "share") for s in shares]
    for w in weights:
        if w <= 0:
            raise TipError("each share must be a positive number")

    tip = bill * tip_percent / 100.0
    total = bill + tip
    total_cents = int(round(total * 100))
    sw = sum(weights)

    raw = [total_cents * w / sw for w in weights]
    cents = [int(math.floor(x)) for x in raw]
    remainder = total_cents - sum(cents)
    # hand out the leftover cents to the largest fractional remainders first
    order = sorted(range(len(weights)), key=lambda i: raw[i] - cents[i], reverse=True)
    for i in range(remainder):
        cents[order[i]] += 1

    amounts = [c / 100.0 for c in cents]
    return {
        "bill": _round2(bill),
        "tip_percent": _round2(tip_percent),
        "tip": _round2(tip),
        "total": _round2(total),
        "shares": weights,
        "amounts": amounts,
    }


def _largest_remainder(target_cents, weights):
    """Split ``target_cents`` across ``weights`` so the parts sum EXACTLY.

    Floors each proportional share, then hands the leftover cents to the
    largest fractional remainders first. Returns a list of integer cents the
    same length as ``weights`` whose sum equals ``target_cents``.
    """
    sw = sum(weights)
    if sw <= 0:
        # Nothing to weight by — spread evenly over the diners instead.
        n = len(weights)
        base = target_cents // n
        cents = [base] * n
        for i in range(target_cents - base * n):
            cents[i] += 1
        return cents
    raw = [target_cents * w / sw for w in weights]
    cents = [int(math.floor(x)) for x in raw]
    leftover = target_cents - sum(cents)
    order = sorted(range(len(weights)), key=lambda i: raw[i] - cents[i], reverse=True)
    for i in range(leftover):
        cents[order[i]] += 1
    return cents


def split_by_items(people_items, tip_percent, tax=0, tip_on="subtotal"):
    """Itemised bill split: each diner pays their own items + a fair share of
    tax and tip (REQ-002 extension).

    ``people_items`` is a non-empty list, one entry per diner, where each entry
    is that diner's list of item prices (an empty list means they ordered
    nothing). The food subtotal is the sum of every item. Tip is computed on
    the food subtotal (``tip_on="subtotal"``) or on the tax-inclusive amount
    (``tip_on="total"``). Tax and tip are then apportioned across diners in
    proportion to what each one ordered, using the largest-remainder method so
    the per-diner ``amounts`` always sum EXACTLY to the grand ``total`` — nobody
    is over- or under-charged by a stray cent.

    Returns a dict whose ``people`` list carries each diner's ``subtotal``,
    apportioned ``tax``, ``tip`` and final ``amount``.
    """
    tip_percent = _to_number(tip_percent, "tip_percent")
    tax = _to_number(tax, "tax") if tax not in (None, "") else 0.0
    mode = _normalise_tip_on(tip_on)

    if tip_percent < 0:
        raise TipError("tip_percent must not be negative")
    if tax < 0:
        raise TipError("tax must not be negative")

    if isinstance(people_items, (str, bytes)) or not hasattr(people_items, "__iter__"):
        raise TipError("people_items must be a list of item lists")
    people_items = list(people_items)
    if not people_items:
        raise TipError("people_items must not be empty")

    subtotals = []
    for entry in people_items:
        if isinstance(entry, (str, bytes)) or not hasattr(entry, "__iter__"):
            raise TipError("each diner's items must be a list of numbers")
        s = 0.0
        for price in list(entry):
            p = _to_number(price, "item price")
            if p < 0:
                raise TipError("item prices must not be negative")
            s += p
        subtotals.append(s)

    food_total = sum(subtotals)
    tip_base = food_total if mode == "subtotal" else food_total + tax
    tip = tip_base * tip_percent / 100.0
    total = food_total + tax + tip

    # Apportion tax and tip in proportion to each diner's food subtotal. When
    # nobody ordered anything (food_total == 0) the weights are all zero and the
    # helper spreads any tax/tip evenly so the totals still reconcile.
    weights = subtotals
    sub_cents = [int(round(s * 100)) for s in subtotals]
    tax_cents = _largest_remainder(int(round(tax * 100)), weights)
    tip_cents = _largest_remainder(int(round(tip * 100)), weights)

    people = []
    total_check = 0
    for i in range(len(subtotals)):
        amount_cents = sub_cents[i] + tax_cents[i] + tip_cents[i]
        total_check += amount_cents
        people.append({
            "subtotal": _round2(sub_cents[i] / 100.0),
            "tax": _round2(tax_cents[i] / 100.0),
            "tip": _round2(tip_cents[i] / 100.0),
            "amount": _round2(amount_cents / 100.0),
        })

    return {
        "people": people,
        "tip_percent": _round2(tip_percent),
        "tip_on": mode,
        "subtotal": _round2(food_total),
        "tax": _round2(tax),
        "tip": _round2(tip),
        "total": _round2(total_check / 100.0),
    }


def settle_up(bill, tip_percent, paid, shares=None):
    """Settle a shared bill — work out who owes whom (REQ-002 extension).

    After a meal the table owes the grand total (``bill`` plus a ``tip_percent``
    gratuity), but the money rarely lands fairly: one diner puts down a card,
    another throws in cash, a third forgets their wallet. ``paid`` is what each
    diner has ALREADY contributed (one entry per diner, same order). Their fair
    share of the total is split evenly, or by ``shares`` weights when supplied
    (e.g. ``[1, 1, 2]`` so the third diner owes double).

    The contributions must add up to the grand total in cents — the table has to
    cover the cheque before it can be squared up internally. The result reports,
    per diner, what they ``paid``, what they ``owed`` and their ``balance``
    (positive = overpaid and owed money back, negative = still owes), plus a
    minimal list of ``transfers`` (``from``/``to`` diner index and ``amount``)
    that leaves everyone settled. The transfer amounts always sum to the total
    that the under-payers owe, so nobody ends up off by a cent.
    """
    bill = _to_number(bill, "bill")
    tip_percent = _to_number(tip_percent, "tip_percent")
    if bill < 0:
        raise TipError("bill must not be negative")
    if tip_percent < 0:
        raise TipError("tip_percent must not be negative")

    if isinstance(paid, (str, bytes)) or not hasattr(paid, "__iter__"):
        raise TipError("paid must be a list of numbers")
    paid = list(paid)
    if not paid:
        raise TipError("paid must not be empty")
    paid_amounts = []
    for p in paid:
        amt = _to_number(p, "payment")
        if amt < 0:
            raise TipError("payments must not be negative")
        paid_amounts.append(amt)

    n = len(paid_amounts)
    if shares is None or shares == "":
        weights = [1] * n
    else:
        if isinstance(shares, (str, bytes)) or not hasattr(shares, "__iter__"):
            raise TipError("shares must be a list of numbers")
        weights = [_to_number(s, "share") for s in list(shares)]
        if len(weights) != n:
            raise TipError("shares must have one weight per diner")
        for w in weights:
            if w <= 0:
                raise TipError("each share must be a positive number")

    tip = bill * tip_percent / 100.0
    total = bill + tip
    total_cents = int(round(total * 100))

    paid_cents = [int(round(a * 100)) for a in paid_amounts]
    if sum(paid_cents) != total_cents:
        raise TipError(
            "payments must add up to the total of %.2f" % (total_cents / 100.0))

    owed_cents = _largest_remainder(total_cents, weights)
    balance_cents = [paid_cents[i] - owed_cents[i] for i in range(n)]

    # Greedy minimal settlement: largest creditor is repaid by largest debtor.
    creditors = sorted(
        ([i, b] for i, b in enumerate(balance_cents) if b > 0),
        key=lambda x: x[1], reverse=True)
    debtors = sorted(
        ([i, -b] for i, b in enumerate(balance_cents) if b < 0),
        key=lambda x: x[1], reverse=True)

    transfers = []
    ci = di = 0
    while ci < len(creditors) and di < len(debtors):
        cred = creditors[ci]
        deb = debtors[di]
        pay = min(cred[1], deb[1])
        transfers.append({
            "from": deb[0],
            "to": cred[0],
            "amount": _round2(pay / 100.0),
        })
        cred[1] -= pay
        deb[1] -= pay
        if cred[1] == 0:
            ci += 1
        if deb[1] == 0:
            di += 1

    people = [{
        "paid": _round2(paid_cents[i] / 100.0),
        "owed": _round2(owed_cents[i] / 100.0),
        "balance": _round2(balance_cents[i] / 100.0),
    } for i in range(n)]

    return {
        "bill": _round2(bill),
        "tip_percent": _round2(tip_percent),
        "tip": _round2(tip),
        "total": _round2(total_cents / 100.0),
        "people": people,
        "transfers": transfers,
    }


# A conventional service-quality → tip-percent scale (REQ-001 extension). Each
# whole star maps to a customary US gratuity; fractional ratings interpolate
# linearly between the neighbouring stars so a 4.5★ meal tips halfway between
# the 4★ and 5★ tiers.
_RATING_SCALE = {1: 10.0, 2: 12.0, 3: 15.0, 4: 18.0, 5: 20.0}


def tip_for_rating(bill, rating, people=1):
    """Suggest a tip from a 1–5 star service rating, then calculate it.

    Diners often think in terms of "how good was the service" rather than a
    raw percentage. ``rating`` is a number in ``[1, 5]`` (halves allowed); it is
    mapped to a customary gratuity via :data:`_RATING_SCALE`, interpolating
    linearly for fractional stars. The chosen ``tip_percent`` is then run through
    :func:`calculate_tip` so the rounding and per-person split rules stay
    identical (REQ-001/REQ-002). The resolved ``rating`` and ``tip_percent`` are
    echoed back alongside the usual tip/total fields.
    """
    rating = _to_number(rating, "rating")
    if rating < 1 or rating > 5:
        raise TipError("rating must be between 1 and 5")

    low = int(math.floor(rating))
    high = int(math.ceil(rating))
    if low == high:
        percent = _RATING_SCALE[low]
    else:
        frac = rating - low
        percent = _RATING_SCALE[low] + frac * (_RATING_SCALE[high] - _RATING_SCALE[low])

    result = calculate_tip(bill, percent, people)
    result["rating"] = _round2(rating)
    result["tip_percent"] = _round2(percent)
    return result


# Standard US denominations in cents, largest first: $100/$50/$20/$10/$5/$1
# bills and quarter/dime/nickel/penny coins. Used to make change.
_DENOMINATIONS = (
    (10000, "$100"), (5000, "$50"), (2000, "$20"), (1000, "$10"),
    (500, "$5"), (100, "$1"), (25, "25c"), (10, "10c"), (5, "5c"), (1, "1c"),
)


def change_due(total, paid):
    """Compute the change owed when a diner pays cash, broken into denominations.

    ``total`` is the amount due (e.g. the grand total from :func:`calculate_tip`)
    and ``paid`` is the cash tendered. The cash must at least cover the total —
    paying short fails safe with a clear error. Returns the ``change`` owed,
    whether it was an ``exact`` payment, and a ``breakdown`` listing the fewest
    standard US bills/coins that make up the change (greedy, which is optimal for
    this canonical denomination set).
    """
    total = _to_number(total, "total")
    paid = _to_number(paid, "paid")
    if total < 0:
        raise TipError("total must not be negative")
    if paid < 0:
        raise TipError("paid must not be negative")
    if paid < total:
        raise TipError("paid must be at least the total")

    change_cents = int(round((paid - total) * 100))
    breakdown = []
    remaining = change_cents
    for value, label in _DENOMINATIONS:
        count = remaining // value
        if count:
            breakdown.append({"denom": label, "value": _round2(value / 100.0),
                              "count": count})
            remaining -= count * value

    return {
        "total": _round2(total),
        "paid": _round2(paid),
        "change": _round2(change_cents / 100.0),
        "exact": change_cents == 0,
        "breakdown": breakdown,
    }


def combine_checks(checks, people=1):
    """Combine several separate checks into one grand total and split (REQ-002 extn).

    A night out often spans multiple cheques — a bar tab, then dinner, then
    dessert — each with its own tip rate (and possibly tax). ``checks`` is a
    non-empty list, one dict per cheque, accepting the same fields as
    :func:`calculate_tip` (``bill`` required; ``tip_percent`` default 0, plus
    optional ``tax``/``tip_on``/``round_total``). Each cheque is calculated
    independently and reported under ``checks``; the bills, tips and totals are
    summed into a grand total which is then split evenly across ``people`` using
    the largest-remainder method so the per-person ``amounts`` sum EXACTLY to the
    grand total.
    """
    if isinstance(checks, (str, bytes)) or not hasattr(checks, "__iter__"):
        raise TipError("checks must be a list of objects")
    checks = list(checks)
    if not checks:
        raise TipError("checks must not be empty")
    people_int = _validate_people(people)

    breakdown = []
    bill_sum = tip_sum = 0.0
    total_cents = 0
    for entry in checks:
        if not isinstance(entry, dict):
            raise TipError("each check must be an object")
        r = calculate_tip(
            entry.get("bill"),
            entry.get("tip_percent", 0),
            1,
            entry.get("round_total", False),
            entry.get("tax", 0),
            entry.get("tip_on", "total"),
        )
        bill_sum += r["bill"]
        tip_sum += r["tip"]
        total_cents += int(round(r["total"] * 100))
        breakdown.append({
            "bill": r["bill"],
            "tip_percent": r["tip_percent"],
            "tip": r["tip"],
            "total": r["total"],
        })

    per_person_cents = _largest_remainder(total_cents, [1] * people_int)
    amounts = [_round2(c / 100.0) for c in per_person_cents]

    return {
        "checks": breakdown,
        "count": len(breakdown),
        "people": people_int,
        "bill": _round2(bill_sum),
        "tip": _round2(tip_sum),
        "total": _round2(total_cents / 100.0),
        "amounts": amounts,
        "total_per_person": amounts[0] if people_int == 1 else _round2(total_cents / 100.0 / people_int),
    }


_DISCOUNT_AMOUNT = ("amount", "fixed", "flat", "$")
_DISCOUNT_PERCENT = ("percent", "percentage", "%", "off")


def _normalise_discount_type(discount_type):
    """Resolve a discount mode to ``"amount"`` or ``"percent"`` (REQ-001 extn)."""
    if discount_type is None or discount_type == "":
        return "amount"
    if not isinstance(discount_type, str):
        raise TipError("discount_type must be 'amount' or 'percent'")
    key = discount_type.strip().lower()
    if key in _DISCOUNT_AMOUNT:
        return "amount"
    if key in _DISCOUNT_PERCENT:
        return "percent"
    raise TipError("discount_type must be 'amount' or 'percent'")


def apply_discount(bill, tip_percent, discount, discount_type="amount",
                   tip_on_discounted=True, people=1):
    """Apply a coupon/discount to the bill, then tip and split (REQ-001 extn).

    Diners frequently arrive with a coupon — "$10 off" or "20% off". The
    ``discount`` is applied to ``bill`` first: when ``discount_type`` is
    ``"amount"`` (aliases: ``fixed``/``flat``) it is a flat currency amount,
    and when ``"percent"`` (aliases: ``percentage``/``off``) it is a percentage
    of the bill. The discount may not exceed the bill (a percent discount may
    not exceed 100). ``tip_on_discounted`` controls etiquette: by default the
    gratuity is computed on the post-discount amount, but many diners prefer to
    tip on the original, pre-discount value so the server is not penalised for
    the coupon — pass ``False`` for that. The discounted total is then split
    across ``people`` (REQ-002).

    Returns the original ``bill``, the resolved ``savings`` and
    ``discounted_bill``, plus the usual tip/total/per-person fields. Raises
    ``TipError`` on invalid input so callers can fail safe.
    """
    bill = _to_number(bill, "bill")
    tip_percent = _to_number(tip_percent, "tip_percent")
    discount = _to_number(discount, "discount") if discount not in (None, "") else 0.0
    mode = _normalise_discount_type(discount_type)
    people_int = _validate_people(people)

    if bill < 0:
        raise TipError("bill must not be negative")
    if tip_percent < 0:
        raise TipError("tip_percent must not be negative")
    if discount < 0:
        raise TipError("discount must not be negative")

    if mode == "percent":
        if discount > 100:
            raise TipError("a percent discount must not exceed 100")
        savings = bill * discount / 100.0
    else:
        savings = discount
        if savings > bill:
            raise TipError("discount must not exceed the bill")

    discounted_bill = bill - savings
    tip_base = discounted_bill if tip_on_discounted else bill
    tip = tip_base * tip_percent / 100.0
    total = discounted_bill + tip

    return {
        "bill": _round2(bill),
        "tip_percent": _round2(tip_percent),
        "discount": _round2(discount),
        "discount_type": mode,
        "tip_on_discounted": bool(tip_on_discounted),
        "savings": _round2(savings),
        "discounted_bill": _round2(discounted_bill),
        "people": people_int,
        "tip": _round2(tip),
        "total": _round2(total),
        "tip_per_person": _round2(tip / people_int),
        "total_per_person": _round2(total / people_int),
    }


def tip_pool(pool, weights):
    """Distribute a collected tip pool among staff by weight (REQ-002 extn).

    At the end of a shift the gratuities are pooled and shared among the staff
    in proportion to the hours each worked (or any other weighting, e.g. role
    points). ``pool`` is the total tip money collected and ``weights`` is a
    non-empty list of positive numbers, one per staff member. The pool is
    divided using the largest-remainder method on integer cents so the
    per-person ``shares`` always sum EXACTLY to ``pool`` — no money is created
    or lost to rounding.

    Returns the ``pool``, the normalised ``weights`` and the ``shares`` list,
    with ``total`` echoing the reconciled sum. Raises ``TipError`` on invalid
    input so callers can fail safe.
    """
    pool = _to_number(pool, "pool")
    if pool < 0:
        raise TipError("pool must not be negative")

    if isinstance(weights, (str, bytes)) or not hasattr(weights, "__iter__"):
        raise TipError("weights must be a list of numbers")
    weights = list(weights)
    if not weights:
        raise TipError("weights must not be empty")
    norm = [_to_number(w, "weight") for w in weights]
    for w in norm:
        if w <= 0:
            raise TipError("each weight must be a positive number")

    pool_cents = int(round(pool * 100))
    share_cents = _largest_remainder(pool_cents, norm)
    shares = [_round2(c / 100.0) for c in share_cents]

    return {
        "pool": _round2(pool),
        "weights": norm,
        "people": len(norm),
        "shares": shares,
        "total": _round2(sum(share_cents) / 100.0),
    }


def split_with_caps(bill, tip_percent, people, caps):
    """Even split where some diners have a spending cap (REQ-002 extension).

    The table splits the grand total (``bill`` plus a ``tip_percent`` gratuity)
    evenly, BUT some diners can only chip in up to a maximum — a student who can
    do at most $15, say. ``caps`` is a list, one entry per diner (so its length
    must equal ``people``), where each entry is that diner's maximum contribution
    or ``None``/``""`` for "no cap" (willing to cover the overflow). Anyone whose
    fair even share would exceed their cap pays exactly their cap, and the
    shortfall is redistributed across the remaining uncapped diners — repeating
    until everyone is settled (a water-filling allocation). All maths is done in
    integer cents with the largest-remainder method so the per-diner ``amounts``
    always sum EXACTLY to the grand ``total``.

    Fails safe with ``TipError`` when every diner is capped and the caps together
    cannot cover the total. Returns each diner's ``amount`` and whether they were
    ``capped``, plus the ``fair_share`` (uncapped even split) for reference.
    """
    bill, tip_percent, people_int = _validate_bill_tip_people(bill, tip_percent, people)

    if isinstance(caps, (str, bytes)) or not hasattr(caps, "__iter__"):
        raise TipError("caps must be a list")
    caps = list(caps)
    if len(caps) != people_int:
        raise TipError("caps must have one entry per person")

    cap_cents = []
    for c in caps:
        if c is None or c == "":
            cap_cents.append(None)  # uncapped
            continue
        amt = _to_number(c, "cap")
        if amt < 0:
            raise TipError("caps must not be negative")
        cap_cents.append(int(round(amt * 100)))

    tip = bill * tip_percent / 100.0
    total = bill + tip
    total_cents = int(round(total * 100))

    # Water-filling: repeatedly hand the active diners an even slice; anyone
    # whose cap falls below that slice is fixed at their cap and the rest of the
    # bill is shared out among those still able to absorb more.
    fixed = {}
    active = list(range(people_int))
    remaining = total_cents
    while active:
        share = remaining / len(active)
        newly = [i for i in active if cap_cents[i] is not None and cap_cents[i] < share]
        if not newly:
            slices = _largest_remainder(remaining, [1] * len(active))
            for pos, i in enumerate(active):
                fixed[i] = slices[pos]
            remaining = 0
            active = []
            break
        for i in newly:
            fixed[i] = cap_cents[i]
            remaining -= cap_cents[i]
        active = [i for i in active if i not in newly]

    if remaining != 0:
        # Every diner hit their cap yet the bill is not covered.
        raise TipError(
            "caps cannot cover the total of %.2f" % (total_cents / 100.0))

    people_out = []
    for i in range(people_int):
        amt_cents = fixed[i]
        people_out.append({
            "amount": _round2(amt_cents / 100.0),
            "cap": None if cap_cents[i] is None else _round2(cap_cents[i] / 100.0),
            "capped": cap_cents[i] is not None and amt_cents >= cap_cents[i],
        })

    return {
        "bill": _round2(bill),
        "tip_percent": _round2(tip_percent),
        "people": people_int,
        "tip": _round2(tip),
        "total": _round2(total_cents / 100.0),
        "fair_share": _round2(total_cents / 100.0 / people_int),
        "people_detail": people_out,
        "amounts": [p["amount"] for p in people_out],
    }


def _parse_line_item(entry, index):
    """Normalise one menu line into ``(name, price, qty)`` (REQ-001 extn helper).

    An entry may be a bare price (number/numeric string), a 1- or 2-element list
    ``[price]`` / ``[price, qty]``, or a mapping with ``price`` and optional
    ``qty``/``name`` keys. ``qty`` defaults to 1 and must be a positive number;
    ``price`` must be a non-negative number. Raises ``TipError`` on junk.
    """
    name = None
    qty = 1
    if isinstance(entry, dict):
        if "price" not in entry:
            raise TipError("line %d is missing a price" % (index + 1))
        price = entry.get("price")
        if entry.get("qty") not in (None, ""):
            qty = entry.get("qty")
        raw_name = entry.get("name")
        if raw_name not in (None, ""):
            name = str(raw_name)
    elif isinstance(entry, (list, tuple)):
        if not entry or len(entry) > 2:
            raise TipError("line %d must be [price] or [price, qty]" % (index + 1))
        price = entry[0]
        if len(entry) == 2 and entry[1] not in (None, ""):
            qty = entry[1]
    else:
        price = entry

    price = _to_number(price, "line %d price" % (index + 1))
    if price < 0:
        raise TipError("line %d price must not be negative" % (index + 1))
    qty = _to_number(qty, "line %d qty" % (index + 1))
    if qty <= 0:
        raise TipError("line %d qty must be a positive number" % (index + 1))
    if name is None:
        name = "Item %d" % (index + 1)
    return name, price, qty


def build_bill(items, tax_percent=0, tip_percent=0, people=1):
    """Assemble a bill from menu line items, then tax, tip and split (REQ-001/002).

    Where :func:`split_by_items` takes already-priced items and assigns each to a
    specific diner, ``build_bill`` *constructs* one shared cheque from a menu:
    each entry in ``items`` is a line (see :func:`_parse_line_item`) contributing
    ``price * qty`` to the subtotal. A ``tax_percent`` sales tax is then applied
    to the subtotal, a ``tip_percent`` gratuity is computed on the pre-tax
    subtotal (the common convention), and the grand total is split evenly across
    ``people``.

    All money is reconciled in integer cents so the per-line amounts sum exactly
    to the subtotal. Returns the resolved ``line_items`` plus the usual bill
    breakdown. Raises ``TipError`` on invalid input so callers can fail safe.
    """
    if isinstance(items, (str, bytes)) or not hasattr(items, "__iter__"):
        raise TipError("items must be a list of menu lines")
    items = list(items)
    if not items:
        raise TipError("items must not be empty")

    tax_percent = _to_number(tax_percent, "tax_percent") if tax_percent not in (None, "") else 0.0
    tip_percent = _to_number(tip_percent, "tip_percent") if tip_percent not in (None, "") else 0.0
    people_int = _validate_people(people)
    if tax_percent < 0:
        raise TipError("tax_percent must not be negative")
    if tip_percent < 0:
        raise TipError("tip_percent must not be negative")

    line_items = []
    subtotal = 0.0
    for i, entry in enumerate(items):
        name, price, qty = _parse_line_item(entry, i)
        amount = price * qty
        subtotal += amount
        line_items.append({
            "name": name,
            "price": _round2(price),
            "qty": _round2(qty) if qty != int(qty) else int(qty),
            "amount": _round2(amount),
        })

    tax = subtotal * tax_percent / 100.0
    tip = subtotal * tip_percent / 100.0
    total = subtotal + tax + tip

    return {
        "line_items": line_items,
        "people": people_int,
        "tax_percent": _round2(tax_percent),
        "tip_percent": _round2(tip_percent),
        "subtotal": _round2(subtotal),
        "tax": _round2(tax),
        "tip": _round2(tip),
        "total": _round2(total),
        "tip_per_person": _round2(tip / people_int),
        "total_per_person": _round2(total / people_int),
    }


def service_charge(bill, service_percent, desired_percent=None, people=1):
    """Account for a restaurant-applied mandatory service charge (REQ-001 extn).

    Many venues add a compulsory service charge of ``service_percent`` to the
    food ``bill`` (subtotal) — this gratuity is already paid, so it counts toward
    what you tip. When you want your *overall* gratuity to reach a higher
    ``desired_percent``, this works out the additional voluntary ``top_up`` on
    top of the mandatory charge (never negative — if the service charge already
    meets or beats your target, the top-up is zero). The grand ``total`` is then
    split evenly across ``people``.

    Returns the ``service`` charge, any ``top_up``, the ``effective_tip_percent``
    actually paid, and the per-person split. Raises ``TipError`` on bad input.
    """
    bill = _to_number(bill, "bill")
    service_percent = _to_number(service_percent, "service_percent")
    people_int = _validate_people(people)
    if bill < 0:
        raise TipError("bill must not be negative")
    if service_percent < 0:
        raise TipError("service_percent must not be negative")

    service = bill * service_percent / 100.0

    if desired_percent in (None, ""):
        top_up = 0.0
        effective = service_percent
    else:
        desired_percent = _to_number(desired_percent, "desired_percent")
        if desired_percent < 0:
            raise TipError("desired_percent must not be negative")
        desired_tip = bill * desired_percent / 100.0
        top_up = max(0.0, desired_tip - service)
        effective = desired_percent if top_up > 0 else service_percent

    gratuity = service + top_up
    total = bill + gratuity

    return {
        "bill": _round2(bill),
        "service_percent": _round2(service_percent),
        "people": people_int,
        "service": _round2(service),
        "top_up": _round2(top_up),
        "gratuity": _round2(gratuity),
        "effective_tip_percent": _round2(effective),
        "total": _round2(total),
        "tip_per_person": _round2(gratuity / people_int),
        "total_per_person": _round2(total / people_int),
    }


def _normalise_currency(currency):
    """Resolve a target-currency label to a short upper-case code (REQ extn)."""
    if currency in (None, ""):
        return "USD"
    if not isinstance(currency, str):
        raise TipError("currency must be a short code like 'EUR'")
    code = currency.strip().upper()
    if not (1 <= len(code) <= 5) or not code.isalpha():
        raise TipError("currency must be 1-5 letters like 'EUR'")
    return code


def convert_currency(bill, tip_percent, rate, people=1, currency="USD"):
    """Compute the tip/total then convert it to another currency (REQ-001/002).

    For travellers: tip and total are figured in the bill's own currency, then
    multiplied by ``rate`` (units of the target ``currency`` per 1 unit of the
    bill currency) to show what each diner will actually be charged abroad. The
    base breakdown is reused verbatim from :func:`calculate_tip`, so every
    existing rule (validation, per-person split) applies unchanged.

    Returns the base figures plus a ``converted`` block (tip/total and per-person
    in the target currency) and the ``rate``/``currency`` echoed back. Raises
    ``TipError`` on invalid input — notably a non-positive exchange rate.
    """
    base = calculate_tip(bill, tip_percent, people)
    rate = _to_number(rate, "rate")
    if rate <= 0:
        raise TipError("rate must be a positive number")
    code = _normalise_currency(currency)

    return {
        "bill": base["bill"],
        "tip_percent": base["tip_percent"],
        "people": base["people"],
        "tip": base["tip"],
        "total": base["total"],
        "tip_per_person": base["tip_per_person"],
        "total_per_person": base["total_per_person"],
        "rate": _round2(rate),
        "currency": code,
        "converted": {
            "tip": _round2(base["tip"] * rate),
            "total": _round2(base["total"] * rate),
            "tip_per_person": _round2(base["tip_per_person"] * rate),
            "total_per_person": _round2(base["total_per_person"] * rate),
        },
    }


def auto_gratuity(bill, people, threshold=6, auto_percent=18, chosen_percent=None):
    """Apply a large-party automatic gratuity, then tip and split (REQ-001/002).

    Many restaurants add a MANDATORY gratuity of ``auto_percent`` once a party
    reaches ``threshold`` diners (a "parties of 6 or more" policy). When the
    party is that large the gratuity is compulsory and the diner may not tip
    BELOW it — a ``chosen_percent`` under the mandatory rate is bumped up to it,
    while a more generous choice is honoured. For smaller parties no gratuity is
    forced: the ``chosen_percent`` (or 0 if none) is applied voluntarily.

    The resolved tip is run through :func:`calculate_tip` so the rounding and
    per-person split rules stay identical. Returns whether the auto-gratuity
    ``applied``, the ``threshold``/``auto_percent`` echoed back, and the usual
    tip/total/per-person fields. Raises ``TipError`` on invalid input.
    """
    bill = _to_number(bill, "bill")
    people_int = _validate_people(people)
    threshold_int = _validate_people(threshold) if threshold not in (None, "") else 6
    auto_percent = _to_number(auto_percent, "auto_percent") if auto_percent not in (None, "") else 0.0
    if bill < 0:
        raise TipError("bill must not be negative")
    if auto_percent < 0:
        raise TipError("auto_percent must not be negative")

    if chosen_percent in (None, ""):
        chosen = None
    else:
        chosen = _to_number(chosen_percent, "chosen_percent")
        if chosen < 0:
            raise TipError("chosen_percent must not be negative")

    applied = people_int >= threshold_int
    if applied:
        # Mandatory: the party may tip more, never less, than the auto rate.
        tip_percent = auto_percent if chosen is None else max(auto_percent, chosen)
    else:
        tip_percent = 0.0 if chosen is None else chosen

    result = calculate_tip(bill, tip_percent, people_int)
    result["threshold"] = threshold_int
    result["auto_percent"] = _round2(auto_percent)
    result["applied"] = applied
    result["chosen_percent"] = None if chosen is None else _round2(chosen)
    return result


def split_by_percentage(bill, tip_percent, percentages):
    """Split the grand total by explicit percentage allocations (REQ-002 extn).

    Where :func:`split_by_shares` takes arbitrary weights, ``percentages`` is a
    non-empty list of non-negative percentages — one per diner — that must add
    up to 100 (a small rounding tolerance of half a percent is allowed so
    ``[33.33, 33.33, 33.33]`` is accepted). Each diner pays their stated percentage of the grand
    total (``bill`` plus a ``tip_percent`` gratuity). Leftover cents are handed
    out by the largest-remainder method so the per-diner ``amounts`` always sum
    EXACTLY to ``total``. Raises ``TipError`` on invalid input.
    """
    bill = _to_number(bill, "bill")
    tip_percent = _to_number(tip_percent, "tip_percent")
    if bill < 0:
        raise TipError("bill must not be negative")
    if tip_percent < 0:
        raise TipError("tip_percent must not be negative")

    if isinstance(percentages, (str, bytes)) or not hasattr(percentages, "__iter__"):
        raise TipError("percentages must be a list of numbers")
    percentages = list(percentages)
    if not percentages:
        raise TipError("percentages must not be empty")
    pcts = [_to_number(p, "percentage") for p in percentages]
    for p in pcts:
        if p < 0:
            raise TipError("each percentage must not be negative")
    if sum(pcts) <= 0:
        raise TipError("percentages must add up to 100")
    if abs(sum(pcts) - 100.0) > 0.5:
        raise TipError("percentages must add up to 100 (got %.2f)" % sum(pcts))

    tip = bill * tip_percent / 100.0
    total = bill + tip
    total_cents = int(round(total * 100))
    cents = _largest_remainder(total_cents, pcts)
    amounts = [_round2(c / 100.0) for c in cents]

    return {
        "bill": _round2(bill),
        "tip_percent": _round2(tip_percent),
        "tip": _round2(tip),
        "total": _round2(total_cents / 100.0),
        "percentages": [_round2(p) for p in pcts],
        "amounts": amounts,
    }


def tip_for_target_per_person(bill, target_per_person, people=1):
    """Find the tip needed so each diner pays a clean per-person amount (REQ-001/002).

    Diners often want a tidy split — "let's make it $25 each". Given the ``bill``,
    a ``target_per_person`` amount and the number of ``people``, this works out
    the grand total that lands on that per-person figure (``target_per_person``
    times ``people``), the tip that implies, and the effective tip percent. The
    target total must be at least the ``bill`` (the tip cannot be negative).

    Returns the resolved ``total``, ``tip``, ``effective_tip_percent`` and the
    per-person split. Raises ``TipError`` on invalid input so callers can fail
    safe with a clear message.
    """
    bill = _to_number(bill, "bill")
    target_per_person = _to_number(target_per_person, "target_per_person")
    people_int = _validate_people(people)
    if bill < 0:
        raise TipError("bill must not be negative")
    if target_per_person < 0:
        raise TipError("target_per_person must not be negative")

    total = target_per_person * people_int
    if total < bill:
        raise TipError("target_per_person is too low to cover the bill")

    tip = total - bill
    if bill > 0:
        effective = tip / bill * 100.0
    else:
        effective = 0.0

    return {
        "bill": _round2(bill),
        "people": people_int,
        "target_per_person": _round2(target_per_person),
        "tip": _round2(tip),
        "total": _round2(total),
        "effective_tip_percent": _round2(effective),
        "tip_per_person": _round2(tip / people_int),
        "total_per_person": _round2(target_per_person),
    }


def _normalise_direction(direction):
    """Validate the rounding direction for :func:`round_total_to`."""
    if direction in (None, ""):
        return "up"
    if not isinstance(direction, str):
        raise TipError("direction must be one of: up, nearest, down")
    d = direction.strip().lower()
    aliases = {
        "up": "up", "ceil": "up", "ceiling": "up",
        "nearest": "nearest", "round": "nearest", "closest": "nearest",
        "down": "down", "floor": "down",
    }
    if d not in aliases:
        raise TipError("direction must be one of: up, nearest, down")
    return aliases[d]


def round_total_to(bill, base_percent=0, nearest=5.0, direction="up",
                   people=1, tax=0, tip_on="total"):
    """Round the grand total to a clean increment, folding the change into tip.

    REQ-001/002 extension. Beyond the whole-dollar round offered by
    :func:`calculate_tip`, diners often want to land the *grand total* on a tidy
    multiple — "just make it come to a round $120". Starting from a base tip of
    ``base_percent`` (computed with the same tax / ``tip_on`` rules as
    :func:`calculate_tip`), this rounds the resulting total to the next multiple
    of ``nearest``:

    - ``direction="up"`` (default) always rounds the total UP, so the tip only
      ever grows — the safe choice that never short-changes the server.
    - ``direction="nearest"`` rounds to the closest multiple (ties round up).
    - ``direction="down"`` rounds the total DOWN, trimming the tip.

    The amount the rounding adds to (or removes from) the base total is reported
    as ``bonus``; the gratuity actually paid drives ``effective_tip_percent``.
    The rounded total is split across ``people`` so the shares sum EXACTLY to it
    (leftover cents handed out by the largest-remainder method). The final tip is
    never allowed to go negative — rounding ``down`` below the bill raises a clear
    error rather than billing the diner less than they owe.

    Returns a JSON-friendly dict; raises ``TipError`` on invalid input.
    """
    bill = _to_number(bill, "bill")
    base_percent = _to_number(base_percent, "base_percent") \
        if base_percent not in (None, "") else 0.0
    nearest = _to_number(nearest, "nearest") if nearest not in (None, "") else 5.0
    people_int = _validate_people(people)
    tax = _to_number(tax, "tax") if tax not in (None, "") else 0.0
    mode = _normalise_tip_on(tip_on)
    direction = _normalise_direction(direction)

    if bill < 0:
        raise TipError("bill must not be negative")
    if base_percent < 0:
        raise TipError("base_percent must not be negative")
    if tax < 0:
        raise TipError("tax must not be negative")
    if tax > bill:
        raise TipError("tax must not exceed the bill")
    if nearest <= 0:
        raise TipError("nearest must be a positive number")

    # Base tip and total before any rounding, honouring pre/post-tax tipping.
    subtotal = bill - tax
    tip_base = subtotal if mode == "subtotal" else bill
    base_tip = tip_base * base_percent / 100.0
    base_total = bill + base_tip

    # Round the grand total to a multiple of ``nearest``, in integer cents to
    # avoid binary-float drift in the ceil/floor step.
    step_cents = int(round(nearest * 100))
    if step_cents <= 0:
        raise TipError("nearest must be a positive number")
    base_cents = int(round(base_total * 100))
    units = base_cents / step_cents
    if direction == "up":
        rounded_units = math.ceil(round(units, 9))
    elif direction == "down":
        rounded_units = math.floor(round(units, 9))
    else:  # nearest — ties round up via floor(x + 0.5)
        rounded_units = math.floor(round(units, 9) + 0.5)
    total_cents = rounded_units * step_cents

    bill_cents = int(round(bill * 100))
    if total_cents < bill_cents:
        raise TipError(
            "rounding down would make the tip negative — "
            "raise nearest or use direction='up'")

    total = total_cents / 100.0
    tip = (total_cents - bill_cents) / 100.0
    bonus = (total_cents - base_cents) / 100.0
    if bill > 0:
        effective = tip / bill * 100.0
    else:
        effective = base_percent

    share_cents = _largest_remainder(total_cents, [1] * people_int)
    per_person_amounts = [c / 100.0 for c in share_cents]

    return {
        "bill": _round2(bill),
        "base_percent": _round2(base_percent),
        "tax": _round2(tax),
        "tip_on": mode,
        "nearest": _round2(nearest),
        "direction": direction,
        "people": people_int,
        "base_total": _round2(base_total),
        "total": _round2(total),
        "tip": _round2(tip),
        "bonus": _round2(bonus),
        "effective_tip_percent": _round2(effective),
        "tip_per_person": _round2(tip / people_int),
        "total_per_person": _round2(total / people_int),
        "per_person_amounts": per_person_amounts,
    }


def split_comped(bill, tip_percent, people, comped):
    """Even split where some diners are treated (comped) and pay nothing.

    REQ-002 extension. It is someone's birthday — the table wants to cover that
    diner's share between everyone else. ``people`` is the table size and
    ``comped`` is the list of 0-based diner indices being treated (e.g. ``[2]``
    to comp the third diner). The comped diners pay ``0``; the grand total
    (``bill`` plus a ``tip_percent`` gratuity) is split evenly across the
    remaining payers. At least one diner must still be paying.

    All maths is done in integer cents with the largest-remainder method so the
    per-diner ``amounts`` always sum EXACTLY to the grand ``total`` — no cent is
    created or lost when the comped shares are redistributed. Returns each
    diner's ``amount`` and whether they were ``comped``, plus the
    ``payers`` count and the ``fair_share`` (the even split among the payers).
    Raises ``TipError`` on invalid input so callers can fail safe.
    """
    bill, tip_percent, people_int = _validate_bill_tip_people(bill, tip_percent, people)

    if comped is None or comped == "":
        comped = []
    if isinstance(comped, (str, bytes)) or not hasattr(comped, "__iter__"):
        raise TipError("comped must be a list of diner indices")
    comped = list(comped)

    comped_set = set()
    for idx in comped:
        if isinstance(idx, bool):
            raise TipError("comped indices must be whole numbers")
        try:
            i = int(idx)
        except (TypeError, ValueError):
            raise TipError("comped indices must be whole numbers")
        if float(idx) != i:
            raise TipError("comped indices must be whole numbers")
        if i < 0 or i >= people_int:
            raise TipError("comped index %d is out of range" % i)
        comped_set.add(i)

    payer_indices = [i for i in range(people_int) if i not in comped_set]
    if not payer_indices:
        raise TipError("at least one diner must pay (cannot comp everyone)")

    tip = bill * tip_percent / 100.0
    total = bill + tip
    total_cents = int(round(total * 100))

    payer_cents = _largest_remainder(total_cents, [1] * len(payer_indices))
    amounts_cents = [0] * people_int
    for pos, i in enumerate(payer_indices):
        amounts_cents[i] = payer_cents[pos]

    people_out = [{
        "amount": _round2(amounts_cents[i] / 100.0),
        "comped": i in comped_set,
    } for i in range(people_int)]

    return {
        "bill": _round2(bill),
        "tip_percent": _round2(tip_percent),
        "people": people_int,
        "tip": _round2(tip),
        "total": _round2(total_cents / 100.0),
        "comped": sorted(comped_set),
        "payers": len(payer_indices),
        "fair_share": _round2(total_cents / 100.0 / len(payer_indices)),
        "people_detail": people_out,
        "amounts": [p["amount"] for p in people_out],
    }


def gross_up_tip(bill, tip_percent, fee_percent, people=1):
    """Gross up a card tip so the server NETS the intended gratuity (REQ-001 extn).

    When a tip is paid by card the payment processor skims ``fee_percent`` off
    the gratuity, so a server tipped "20%" actually pockets less. This works out
    the larger tip you must put on the card so that, after the processor's cut,
    the server still nets the intended ``tip_percent`` of the ``bill``.

    The intended (net) tip is ``bill * tip_percent / 100``. To net that after a
    ``fee_percent`` cut you must charge ``intended / (1 - fee_percent/100)`` — the
    ``gross_tip``. The processor keeps the difference (``fee``). The grand
    ``total`` is ``bill + gross_tip``, and ``effective_tip_percent`` reflects what
    was actually charged. The total is split evenly across ``people`` (REQ-002).

    ``fee_percent`` must be in ``[0, 100)`` — a 100% fee would consume the entire
    tip. Returns the ``intended_tip`` (net to server), ``gross_tip`` (charged),
    the processor's ``fee``, the ``total`` and the per-person split. Raises
    ``TipError`` on invalid input so callers can fail safe.
    """
    bill = _to_number(bill, "bill")
    tip_percent = _to_number(tip_percent, "tip_percent")
    fee_percent = _to_number(fee_percent, "fee_percent") \
        if fee_percent not in (None, "") else 0.0
    people_int = _validate_people(people)
    if bill < 0:
        raise TipError("bill must not be negative")
    if tip_percent < 0:
        raise TipError("tip_percent must not be negative")
    if fee_percent < 0:
        raise TipError("fee_percent must not be negative")
    if fee_percent >= 100:
        raise TipError("fee_percent must be less than 100")

    intended_tip = bill * tip_percent / 100.0
    gross_tip = intended_tip / (1.0 - fee_percent / 100.0)
    fee = gross_tip - intended_tip
    total = bill + gross_tip
    if bill > 0:
        effective = gross_tip / bill * 100.0
    else:
        effective = tip_percent

    return {
        "bill": _round2(bill),
        "tip_percent": _round2(tip_percent),
        "fee_percent": _round2(fee_percent),
        "people": people_int,
        "intended_tip": _round2(intended_tip),
        "gross_tip": _round2(gross_tip),
        "fee": _round2(fee),
        "total": _round2(total),
        "effective_tip_percent": _round2(effective),
        "tip_per_person": _round2(gross_tip / people_int),
        "total_per_person": _round2(total / people_int),
    }


def _parse_shared_item(entry, index, n):
    """Normalise one shared-item entry into ``(price, sharers)`` (REQ-002 helper).

    An entry may be a bare price (number/numeric string — shared by EVERYONE),
    a 1- or 2-element list ``[price]`` / ``[price, sharers]``, or a mapping with
    a ``price`` and optional ``sharers`` (a list of 0-based diner indices). When
    ``sharers`` is omitted the item is split across all ``n`` diners. ``sharers``
    must be a non-empty list of distinct whole numbers in ``[0, n)``. Raises
    ``TipError`` on junk so callers can fail safe.
    """
    sharers = None
    if isinstance(entry, dict):
        if "price" not in entry:
            raise TipError("shared item %d is missing a price" % (index + 1))
        price = entry.get("price")
        if entry.get("sharers") not in (None, ""):
            sharers = entry.get("sharers")
    elif isinstance(entry, (list, tuple)):
        if not entry or len(entry) > 2:
            raise TipError(
                "shared item %d must be [price] or [price, sharers]" % (index + 1))
        price = entry[0]
        if len(entry) == 2 and entry[1] not in (None, ""):
            sharers = entry[1]
    else:
        price = entry

    price = _to_number(price, "shared item %d price" % (index + 1))
    if price < 0:
        raise TipError("shared item %d price must not be negative" % (index + 1))

    if sharers is None:
        resolved = list(range(n))
    else:
        if isinstance(sharers, (str, bytes)) or not hasattr(sharers, "__iter__"):
            raise TipError(
                "shared item %d sharers must be a list of diner numbers" % (index + 1))
        resolved = []
        seen = set()
        for s in list(sharers):
            if isinstance(s, bool):
                raise TipError(
                    "shared item %d sharers must be whole numbers" % (index + 1))
            try:
                i = int(s)
            except (TypeError, ValueError):
                raise TipError(
                    "shared item %d sharers must be whole numbers" % (index + 1))
            if float(s) != i:
                raise TipError(
                    "shared item %d sharers must be whole numbers" % (index + 1))
            if i < 0 or i >= n:
                raise TipError(
                    "shared item %d references diner %d out of range" % (index + 1, i))
            if i not in seen:
                seen.add(i)
                resolved.append(i)
        if not resolved:
            raise TipError(
                "shared item %d must have at least one sharer" % (index + 1))
    return price, resolved


def split_shared_items(diners, shared_items=None, tip_percent=0, tax=0,
                       tip_on="subtotal"):
    """Itemised split that also handles SHARED items (REQ-002 extension).

    Where :func:`split_by_items` assumes every item belongs to exactly one
    diner, real tables also order things to share — a $30 appetiser platter
    split between three of the four diners, a bottle of wine for the whole
    table. This builds each diner's subtotal from their OWN personal items PLUS
    their fair portion of every shared item, then apportions tax and tip across
    diners in proportion to what each one consumed so the per-diner ``amounts``
    always sum EXACTLY to the grand ``total`` — nobody is over- or under-charged
    by a stray cent.

    ``diners`` is a non-empty list, one entry per diner, where each entry is
    that diner's personal item prices (an empty list means they only shared).
    ``shared_items`` is an optional list of shared items; each entry is either a
    bare price (shared equally by EVERYONE) or a mapping/list pairing a
    ``price`` with the 0-based ``sharers`` indices splitting it (e.g.
    ``{"price": 30, "sharers": [0, 1, 2]}`` or ``[30, [0, 1, 2]]``). Each shared
    item's price is divided among its sharers with the largest-remainder method
    so the split is exact to the cent. Tip is computed on the food subtotal
    (``tip_on="subtotal"``, the default) or the tax-inclusive amount
    (``tip_on="total"``).

    Returns a dict whose ``people`` list carries each diner's ``personal``,
    ``shared``, ``subtotal``, apportioned ``tax`` and ``tip`` and final
    ``amount``. Raises ``TipError`` on invalid input so callers can fail safe.
    """
    tip_percent = _to_number(tip_percent, "tip_percent")
    tax = _to_number(tax, "tax") if tax not in (None, "") else 0.0
    mode = _normalise_tip_on(tip_on)

    if tip_percent < 0:
        raise TipError("tip_percent must not be negative")
    if tax < 0:
        raise TipError("tax must not be negative")

    if isinstance(diners, (str, bytes)) or not hasattr(diners, "__iter__"):
        raise TipError("diners must be a list of item lists")
    diners = list(diners)
    if not diners:
        raise TipError("diners must not be empty")
    n = len(diners)

    # Each diner's personal spend, in integer cents to keep the totals exact.
    personal_cents = []
    for entry in diners:
        if isinstance(entry, (str, bytes)) or not hasattr(entry, "__iter__"):
            raise TipError("each diner's items must be a list of numbers")
        c = 0
        for price in list(entry):
            p = _to_number(price, "item price")
            if p < 0:
                raise TipError("item prices must not be negative")
            c += int(round(p * 100))
        personal_cents.append(c)

    # Distribute each shared item across its sharers, exact to the cent.
    if shared_items in (None, ""):
        shared_items = []
    if isinstance(shared_items, (str, bytes)) or not hasattr(shared_items, "__iter__"):
        raise TipError("shared_items must be a list")
    shared_items = list(shared_items)

    shared_cents = [0] * n
    for idx, entry in enumerate(shared_items):
        price, sharers = _parse_shared_item(entry, idx, n)
        price_cents = int(round(price * 100))
        parts = _largest_remainder(price_cents, [1] * len(sharers))
        for pos, diner in enumerate(sharers):
            shared_cents[diner] += parts[pos]

    subtotal_cents = [personal_cents[i] + shared_cents[i] for i in range(n)]
    food_cents = sum(subtotal_cents)
    food_total = food_cents / 100.0

    tip_base = food_total if mode == "subtotal" else food_total + tax
    tip = tip_base * tip_percent / 100.0
    tip_cents_total = int(round(tip * 100))
    tax_cents_total = int(round(tax * 100))

    # Apportion tax and tip by each diner's subtotal. When nobody ordered
    # anything the weights are all zero and the helper spreads evenly.
    weights = subtotal_cents
    tax_cents = _largest_remainder(tax_cents_total, weights)
    tip_cents = _largest_remainder(tip_cents_total, weights)

    people = []
    total_check = 0
    for i in range(n):
        amount_cents = subtotal_cents[i] + tax_cents[i] + tip_cents[i]
        total_check += amount_cents
        people.append({
            "personal": _round2(personal_cents[i] / 100.0),
            "shared": _round2(shared_cents[i] / 100.0),
            "subtotal": _round2(subtotal_cents[i] / 100.0),
            "tax": _round2(tax_cents[i] / 100.0),
            "tip": _round2(tip_cents[i] / 100.0),
            "amount": _round2(amount_cents / 100.0),
        })

    return {
        "people": people,
        "tip_percent": _round2(tip_percent),
        "tip_on": mode,
        "subtotal": _round2(food_total),
        "tax": _round2(tax),
        "tip": _round2(tip_cents_total / 100.0),
        "total": _round2(total_check / 100.0),
        "amounts": [p["amount"] for p in people],
    }


# Customary restaurant gratuity norms by country/region (REQ-001 extension).
# ``customary`` is the typical tip a local would leave; ``low``/``high`` bound
# the usual range. These are rough cultural conventions for traveller guidance,
# not legal/financial advice. Codes resolve via :data:`_REGION_ALIASES`.
_REGIONAL_TIP_NORMS = {
    "US": {"name": "United States", "customary": 18.0, "low": 15.0, "high": 20.0},
    "CA": {"name": "Canada", "customary": 15.0, "low": 15.0, "high": 20.0},
    "UK": {"name": "United Kingdom", "customary": 12.5, "low": 10.0, "high": 15.0},
    "EU": {"name": "Europe (general)", "customary": 10.0, "low": 5.0, "high": 10.0},
    "FR": {"name": "France", "customary": 5.0, "low": 0.0, "high": 10.0},
    "DE": {"name": "Germany", "customary": 10.0, "low": 5.0, "high": 10.0},
    "IT": {"name": "Italy", "customary": 10.0, "low": 5.0, "high": 10.0},
    "JP": {"name": "Japan", "customary": 0.0, "low": 0.0, "high": 0.0},
    "CN": {"name": "China", "customary": 0.0, "low": 0.0, "high": 0.0},
    "AU": {"name": "Australia", "customary": 10.0, "low": 0.0, "high": 10.0},
    "IN": {"name": "India", "customary": 10.0, "low": 5.0, "high": 10.0},
    "MX": {"name": "Mexico", "customary": 12.5, "low": 10.0, "high": 15.0},
    "BR": {"name": "Brazil", "customary": 10.0, "low": 10.0, "high": 10.0},
}

_REGION_ALIASES = {
    "USA": "US", "AMERICA": "US", "UNITED STATES": "US",
    "CANADA": "CA",
    "GB": "UK", "BRITAIN": "UK", "ENGLAND": "UK", "UNITED KINGDOM": "UK",
    "EUROPE": "EU",
    "FRANCE": "FR", "GERMANY": "DE", "ITALY": "IT",
    "JAPAN": "JP", "CHINA": "CN", "AUSTRALIA": "AU",
    "INDIA": "IN", "MEXICO": "MX", "BRAZIL": "BR",
}


def _normalise_region(region):
    """Resolve a country/region name or code to a key in :data:`_REGIONAL_TIP_NORMS`."""
    if region in (None, ""):
        raise TipError("region is required")
    if not isinstance(region, str):
        raise TipError("region must be a country name or code")
    key = region.strip().upper()
    key = _REGION_ALIASES.get(key, key)
    if key not in _REGIONAL_TIP_NORMS:
        valid = ", ".join(sorted(_REGIONAL_TIP_NORMS))
        raise TipError("unknown region %r (try one of: %s)" % (region, valid))
    return key


def recommend_regional_tip(bill, region, people=1):
    """Suggest a customary tip for a country/region, then calculate it (REQ-001/002).

    A companion to :func:`convert_currency` for travellers: tipping etiquette
    varies wildly by country — 18% is expected in the United States, ~10% across
    much of Europe, and tipping is famously absent in Japan. Given the ``bill``
    and a ``region`` (a country name or code such as ``"US"``, ``"Japan"`` or
    ``"uk"``), this looks up the customary gratuity from
    :data:`_REGIONAL_TIP_NORMS` and runs it through :func:`calculate_tip` so the
    rounding and per-person split rules stay identical.

    Returns the resolved ``region``/``region_name``, the ``customary`` percent
    actually applied and the typical ``low``/``high`` range for context, plus the
    usual tip/total/per-person fields. Raises ``TipError`` on an unknown region
    so callers can fail safe with the list of supported regions.
    """
    key = _normalise_region(region)
    norms = _REGIONAL_TIP_NORMS[key]

    result = calculate_tip(bill, norms["customary"], people)
    result["region"] = key
    result["region_name"] = norms["name"]
    result["customary"] = _round2(norms["customary"])
    result["low"] = _round2(norms["low"])
    result["high"] = _round2(norms["high"])
    return result


def charity_round_up(bill, tip_percent, people=1, round_to=1.0, donation=None,
                     tax=0, tip_on="total"):
    """Round the checkout total up for a charity donation (REQ-001/002 extension).

    The ubiquitous point-of-sale prompt — "round up for charity?". The tip is
    computed normally (honouring ``tax`` and pre/post-tax ``tip_on`` exactly like
    :func:`calculate_tip`), and then the grand total is bumped up so the spare
    change goes to a good cause. This is deliberately DISTINCT from
    :func:`round_total_to`: there the rounding surplus is folded into the
    server's tip, whereas here it is a SEPARATE ``donation`` line — the server's
    gratuity is untouched.

    Two ways to set the donation:

    - leave ``donation`` unset and the bill+tip total is rounded UP to the next
      multiple of ``round_to`` (default ``1.0`` — the next whole dollar); the
      difference is the donation. A total already on a clean multiple donates 0.
    - pass an explicit ``donation`` amount to add a fixed gift instead; in that
      case ``round_to`` is ignored.

    The grand ``total`` (bill + tip + donation) is split evenly across ``people``
    using the largest-remainder method so the per-person ``amounts`` always sum
    EXACTLY to the total. Returns the ``base_total`` (before the round-up), the
    resolved ``donation``, the usual tip/total fields and the per-person split.
    Raises ``TipError`` on invalid input so callers can fail safe.
    """
    base = calculate_tip(bill, tip_percent, people, tax=tax, tip_on=tip_on)
    base_total_cents = int(round(base["total"] * 100))
    people_int = base["people"]

    if donation not in (None, ""):
        donation_amt = _to_number(donation, "donation")
        if donation_amt < 0:
            raise TipError("donation must not be negative")
        donation_cents = int(round(donation_amt * 100))
    else:
        round_to = _to_number(round_to, "round_to") if round_to not in (None, "") else 1.0
        if round_to <= 0:
            raise TipError("round_to must be a positive number")
        step_cents = int(round(round_to * 100))
        if step_cents <= 0:
            raise TipError("round_to must be a positive number")
        units = math.ceil(round(base_total_cents / step_cents, 9))
        donation_cents = units * step_cents - base_total_cents

    total_cents = base_total_cents + donation_cents
    share_cents = _largest_remainder(total_cents, [1] * people_int)
    per_person_amounts = [c / 100.0 for c in share_cents]

    return {
        "bill": base["bill"],
        "tip_percent": base["tip_percent"],
        "people": people_int,
        "tax": base["tax"],
        "subtotal": base["subtotal"],
        "tip_on": base["tip_on"],
        "tip": base["tip"],
        "base_total": _round2(base_total_cents / 100.0),
        "donation": _round2(donation_cents / 100.0),
        "total": _round2(total_cents / 100.0),
        "tip_per_person": base["tip_per_person"],
        "donation_per_person": _round2(donation_cents / 100.0 / people_int),
        "total_per_person": _round2(total_cents / 100.0 / people_int),
        "per_person_amounts": per_person_amounts,
    }


def tip_excluding(bill, tip_percent, excluded=0, people=1):
    """Tip on the eligible amount, leaving non-tippable charges out (REQ-001/002).

    Restaurants routinely print charges on the cheque that diners do not tip on:
    the bar tab / alcohol, a redeemed gift card, a packaged retail item. This is
    deliberately DISTINCT from the pre-tax ``tip_on="subtotal"`` mode of
    :func:`calculate_tip` — there the only thing removed from the tip base is the
    *tax*, whereas here an arbitrary ``excluded`` amount of the food/drink itself
    is held back.

    ``bill`` is the full pre-tip amount on the cheque. ``excluded`` is the slice
    of that bill NOT subject to gratuity — either a single number or a list of
    charges (which are summed, e.g. ``[40, 12.50]`` for a bar tab plus a gift
    card). The gratuity is computed on the ``eligible`` base ``bill - excluded``;
    the grand ``total`` is still ``bill + tip`` (you pay for the excluded items,
    you just do not tip on them) and is split evenly across ``people`` using the
    largest-remainder method so the per-person ``amounts`` sum EXACTLY to it.

    Returns the resolved ``excluded``/``eligible`` figures, the ``tip``/``total``,
    the ``effective_tip_percent`` actually paid against the whole bill, and the
    per-person split. Raises ``TipError`` on invalid input so callers fail safe.
    """
    bill = _to_number(bill, "bill")
    tip_percent = _to_number(tip_percent, "tip_percent")
    people_int = _validate_people(people)

    # ``excluded`` may be a single amount or a list of charges to sum.
    if excluded in (None, ""):
        excluded_total = 0.0
    elif isinstance(excluded, (str, bytes)):
        excluded_total = _to_number(excluded, "excluded")
    elif hasattr(excluded, "__iter__"):
        excluded_total = 0.0
        for charge in list(excluded):
            c = _to_number(charge, "excluded charge")
            if c < 0:
                raise TipError("excluded charges must not be negative")
            excluded_total += c
    else:
        excluded_total = _to_number(excluded, "excluded")

    if bill < 0:
        raise TipError("bill must not be negative")
    if tip_percent < 0:
        raise TipError("tip_percent must not be negative")
    if excluded_total < 0:
        raise TipError("excluded must not be negative")
    if excluded_total > bill:
        raise TipError("excluded must not exceed the bill")

    eligible = bill - excluded_total
    tip = eligible * tip_percent / 100.0
    total = bill + tip
    total_cents = int(round(total * 100))

    if bill > 0:
        effective = tip / bill * 100.0
    else:
        effective = tip_percent

    share_cents = _largest_remainder(total_cents, [1] * people_int)
    per_person_amounts = [c / 100.0 for c in share_cents]

    return {
        "bill": _round2(bill),
        "tip_percent": _round2(tip_percent),
        "people": people_int,
        "excluded": _round2(excluded_total),
        "eligible": _round2(eligible),
        "tip": _round2(tip),
        "total": _round2(total_cents / 100.0),
        "effective_tip_percent": _round2(effective),
        "tip_per_person": _round2(tip / people_int),
        "total_per_person": _round2(total_cents / 100.0 / people_int),
        "per_person_amounts": per_person_amounts,
    }


def tip_by_diner(diners, tax=0):
    """Per-diner INDIVIDUAL tip rates on each diner's own portion (REQ-001/002).

    Friends rarely agree on a tip. This models "I'll tip 25%, you tip 15%": each
    diner brings their own pre-tax portion of the bill (``amount``) AND their own
    chosen ``tip_percent``, so every person's gratuity is computed against only
    what *they* ate. This is deliberately DISTINCT from the single-rate splitters:
    :func:`split_by_items` and :func:`split_by_shares` apply ONE tip rate to the
    whole table, and :func:`split_by_percentage` divides one grand total by fixed
    shares — none let each diner pick a different rate.

    ``diners`` is a list of objects, one per person, each with an ``amount`` (their
    pre-tax food/drink portion) and a ``tip_percent`` (their own rate); an optional
    ``name`` defaults to ``"Diner N"``. ``tax`` is the total tax on the whole
    cheque and is apportioned across diners in proportion to their ``amount`` using
    the largest-remainder method, so the per-diner tax shares sum EXACTLY to it.
    Each diner pays ``amount + tax share + tip`` (tip is taken on the pre-tax
    amount, matching the pre-tax convention used elsewhere).

    Returns the per-diner breakdown (``name``/``amount``/``tip_percent``/``tax``/
    ``tip``/``total``) plus the table-wide ``subtotal``, ``tax``, total ``tip``,
    grand ``total``, ``people`` count and the ``effective_tip_percent`` actually
    paid against the subtotal. Per-diner totals always reconcile to the grand
    total to the cent. Raises ``TipError`` on invalid input so callers fail safe.
    """
    if diners in (None, ""):
        raise TipError("diners is required")
    if isinstance(diners, (str, bytes, dict)) or not hasattr(diners, "__iter__"):
        raise TipError("diners must be a list of diners")
    diners = list(diners)
    if not diners:
        raise TipError("at least one diner is required")

    names = []
    amount_cents = []
    percents = []
    for index, entry in enumerate(diners):
        if not isinstance(entry, dict):
            raise TipError("diner %d must be an object" % (index + 1))
        name = entry.get("name")
        if name in (None, ""):
            name = "Diner %d" % (index + 1)
        else:
            name = str(name)
        amount = _to_number(entry.get("amount"), "diner %d amount" % (index + 1))
        if amount < 0:
            raise TipError("diner %d amount must not be negative" % (index + 1))
        pct = _to_number(entry.get("tip_percent"), "diner %d tip_percent" % (index + 1))
        if pct < 0:
            raise TipError("diner %d tip_percent must not be negative" % (index + 1))
        names.append(name)
        amount_cents.append(int(round(amount * 100)))
        percents.append(pct)

    tax_amount = _to_number(tax, "tax") if tax not in (None, "") else 0.0
    if tax_amount < 0:
        raise TipError("tax must not be negative")
    tax_cents_total = int(round(tax_amount * 100))
    tax_shares = _largest_remainder(tax_cents_total, list(amount_cents))

    rows = []
    subtotal_cents = 0
    tip_cents_total = 0
    total_cents = 0
    for i, name in enumerate(names):
        a_cents = amount_cents[i]
        t_cents = int(round(a_cents / 100.0 * percents[i]))
        tax_share = tax_shares[i]
        row_total = a_cents + tax_share + t_cents
        subtotal_cents += a_cents
        tip_cents_total += t_cents
        total_cents += row_total
        rows.append({
            "name": name,
            "amount": _round2(a_cents / 100.0),
            "tip_percent": _round2(percents[i]),
            "tax": _round2(tax_share / 100.0),
            "tip": _round2(t_cents / 100.0),
            "total": _round2(row_total / 100.0),
        })

    if subtotal_cents > 0:
        effective = tip_cents_total / subtotal_cents * 100.0
    else:
        effective = 0.0

    return {
        "diners": rows,
        "people": len(rows),
        "subtotal": _round2(subtotal_cents / 100.0),
        "tax": _round2(tax_cents_total / 100.0),
        "tip": _round2(tip_cents_total / 100.0),
        "total": _round2(total_cents / 100.0),
        "effective_tip_percent": _round2(effective),
    }


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tip Calculator</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         margin: 0; padding: 2rem; background: #0f172a; color: #e2e8f0; }
  .card { max-width: 420px; margin: 0 auto; background: #1e293b;
          border-radius: 16px; padding: 1.75rem; box-shadow: 0 10px 30px rgba(0,0,0,.35); }
  h1 { margin: 0 0 1.25rem; font-size: 1.5rem; }
  label { display: block; margin: .9rem 0 .3rem; font-size: .85rem; color: #94a3b8; }
  input { width: 100%; padding: .6rem .7rem; font-size: 1rem; border-radius: 8px;
          border: 1px solid #334155; background: #0f172a; color: #e2e8f0; }
  .chips { display: flex; gap: .5rem; margin-top: .5rem; flex-wrap: wrap; }
  .chip { flex: 1; padding: .5rem; text-align: center; border-radius: 8px; cursor: pointer;
          background: #334155; color: #e2e8f0; border: none; font-size: .9rem; }
  .chip:hover { background: #475569; }
  .out { margin-top: 1.5rem; border-top: 1px solid #334155; padding-top: 1rem; }
  .row { display: flex; justify-content: space-between; padding: .35rem 0; }
  .row .k { color: #94a3b8; }
  .row .v { font-variant-numeric: tabular-nums; font-weight: 600; }
  .grand { font-size: 1.25rem; }
  .err { color: #f87171; margin-top: 1rem; min-height: 1.2em; font-size: .9rem; }
  .toggle { display: flex; align-items: center; gap: .5rem; margin-top: 1rem;
            font-size: .85rem; color: #94a3b8; }
  .toggle input { width: auto; }
</style>
</head>
<body>
  <div class="card">
    <h1>Tip Calculator</h1>
    <label for="bill">Bill amount</label>
    <input id="bill" type="number" min="0" step="0.01" value="100" inputmode="decimal">

    <label for="tip">Tip percent</label>
    <input id="tip" type="number" min="0" step="1" value="15" inputmode="decimal">
    <div class="chips">
      <button class="chip" data-tip="10">10%</button>
      <button class="chip" data-tip="15">15%</button>
      <button class="chip" data-tip="18">18%</button>
      <button class="chip" data-tip="20">20%</button>
      <button class="chip" data-tip="25">25%</button>
    </div>

    <label for="people">Split between (people)</label>
    <input id="people" type="number" min="1" step="1" value="1" inputmode="numeric">

    <label for="tax">Tax included in bill</label>
    <input id="tax" type="number" min="0" step="0.01" value="0" inputmode="decimal">

    <label class="toggle"><input id="pretax" type="checkbox"> Tip on pre-tax subtotal (exclude tax)</label>
    <label class="toggle"><input id="roundup" type="checkbox"> Round total up to the nearest dollar</label>

    <div class="out" id="out" hidden>
      <div class="row"><span class="k">Tip</span><span class="v" id="o-tip"></span></div>
      <div class="row grand"><span class="k">Total</span><span class="v" id="o-total"></span></div>
      <div class="row"><span class="k">Effective tip</span><span class="v" id="o-eff"></span></div>
      <div class="row"><span class="k">Tip / person</span><span class="v" id="o-tpp"></span></div>
      <div class="row grand"><span class="k">Total / person</span><span class="v" id="o-pp"></span></div>
    </div>
    <div class="err" id="err"></div>

    <div class="out" id="sug" hidden>
      <div class="row"><span class="k">Quick tip tiers</span><span class="v">total / person</span></div>
      <div id="sug-rows"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Itemized split</span><span class="v">each pays their own</span></div>
      <label for="items">One diner per line, comma-separated item prices</label>
      <textarea id="items" rows="3" style="width:100%;padding:.6rem .7rem;font-size:1rem;
        border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;
        font-family:inherit;">12.50, 4
9
20, 5.25</textarea>
      <button class="chip" id="items-go" style="margin-top:.6rem;flex:initial;width:100%;">Split by items</button>
      <div id="items-rows"></div>
      <div class="err" id="items-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Settle up</span><span class="v">who owes whom</span></div>
      <label for="paid">What each diner already paid, one per line</label>
      <textarea id="paid" rows="3" style="width:100%;padding:.6rem .7rem;font-size:1rem;
        border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;
        font-family:inherit;">115
0
0</textarea>
      <button class="chip" id="settle-go" style="margin-top:.6rem;flex:initial;width:100%;">Settle up</button>
      <div id="settle-rows"></div>
      <div class="err" id="settle-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Tip by service rating</span><span class="v">1&ndash;5 stars</span></div>
      <label for="rating">Service rating (1&ndash;5, halves ok)</label>
      <input id="rating" type="number" min="1" max="5" step="0.5" value="4" inputmode="decimal">
      <button class="chip" id="rating-go" style="margin-top:.6rem;flex:initial;width:100%;">Tip for rating</button>
      <div id="rating-rows"></div>
      <div class="err" id="rating-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Cash change</span><span class="v">make change</span></div>
      <label for="paid-cash">Cash paid (against the total above)</label>
      <input id="paid-cash" type="number" min="0" step="0.01" value="120" inputmode="decimal">
      <button class="chip" id="change-go" style="margin-top:.6rem;flex:initial;width:100%;">Make change</button>
      <div id="change-rows"></div>
      <div class="err" id="change-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Combine checks</span><span class="v">bill, tip% per line</span></div>
      <label for="combine">One cheque per line: bill, tip%</label>
      <textarea id="combine" rows="3" style="width:100%;padding:.6rem .7rem;font-size:1rem;
        border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;
        font-family:inherit;">40, 18
60, 20
15, 15</textarea>
      <button class="chip" id="combine-go" style="margin-top:.6rem;flex:initial;width:100%;">Combine</button>
      <div id="combine-rows"></div>
      <div class="err" id="combine-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Coupon / discount</span><span class="v">apply then tip</span></div>
      <label for="discount">Discount value</label>
      <input id="discount" type="number" min="0" step="0.01" value="10" inputmode="decimal">
      <label class="toggle"><input id="disc-pct" type="checkbox"> Discount is a percentage (not a flat amount)</label>
      <label class="toggle"><input id="disc-orig" type="checkbox"> Tip on the original (pre-discount) amount</label>
      <button class="chip" id="discount-go" style="margin-top:.6rem;flex:initial;width:100%;">Apply discount</button>
      <div id="discount-rows"></div>
      <div class="err" id="discount-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Tip pool</span><span class="v">share by hours</span></div>
      <label for="pool">Total tip pool collected</label>
      <input id="pool" type="number" min="0" step="0.01" value="100" inputmode="decimal">
      <label for="weights">Each staff member's hours, one per line</label>
      <textarea id="weights" rows="3" style="width:100%;padding:.6rem .7rem;font-size:1rem;
        border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;
        font-family:inherit;">8
6
4</textarea>
      <button class="chip" id="pool-go" style="margin-top:.6rem;flex:initial;width:100%;">Share pool</button>
      <div id="pool-rows"></div>
      <div class="err" id="pool-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Split with caps</span><span class="v">even, but with limits</span></div>
      <label for="caps">Each diner's max, one per line (blank = no cap)</label>
      <textarea id="caps" rows="3" style="width:100%;padding:.6rem .7rem;font-size:1rem;
        border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;
        font-family:inherit;">15

</textarea>
      <button class="chip" id="caps-go" style="margin-top:.6rem;flex:initial;width:100%;">Split with caps</button>
      <div id="caps-rows"></div>
      <div class="err" id="caps-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Build a bill</span><span class="v">price, qty per line</span></div>
      <label for="menu">Menu lines: price, qty (qty optional, defaults to 1)</label>
      <textarea id="menu" rows="3" style="width:100%;padding:.6rem .7rem;font-size:1rem;
        border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;
        font-family:inherit;">12.50, 2
9
20, 1</textarea>
      <label for="menu-tax">Sales tax percent</label>
      <input id="menu-tax" type="number" min="0" step="0.01" value="8" inputmode="decimal">
      <button class="chip" id="menu-go" style="margin-top:.6rem;flex:initial;width:100%;">Build bill</button>
      <div id="menu-rows"></div>
      <div class="err" id="menu-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Service charge</span><span class="v">mandatory + top-up</span></div>
      <label for="svc">Mandatory service charge percent</label>
      <input id="svc" type="number" min="0" step="0.01" value="12.5" inputmode="decimal">
      <label for="svc-desired">Desired total gratuity percent (blank = none)</label>
      <input id="svc-desired" type="number" min="0" step="0.01" value="18" inputmode="decimal">
      <button class="chip" id="svc-go" style="margin-top:.6rem;flex:initial;width:100%;">Apply service charge</button>
      <div id="svc-rows"></div>
      <div class="err" id="svc-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Convert currency</span><span class="v">total abroad</span></div>
      <label for="cur-rate">Exchange rate (target units per 1 of bill currency)</label>
      <input id="cur-rate" type="number" min="0" step="0.0001" value="0.92" inputmode="decimal">
      <label for="cur-code">Target currency code</label>
      <input id="cur-code" type="text" maxlength="5" value="EUR">
      <button class="chip" id="cur-go" style="margin-top:.6rem;flex:initial;width:100%;">Convert total</button>
      <div id="cur-rows"></div>
      <div class="err" id="cur-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Large-party gratuity</span><span class="v">auto over N diners</span></div>
      <label for="ag-threshold">Auto-gratuity applies for parties of this size or more</label>
      <input id="ag-threshold" type="number" min="1" step="1" value="6" inputmode="numeric">
      <label for="ag-auto">Mandatory gratuity percent</label>
      <input id="ag-auto" type="number" min="0" step="0.01" value="18" inputmode="decimal">
      <button class="chip" id="ag-go" style="margin-top:.6rem;flex:initial;width:100%;">Apply party gratuity</button>
      <div id="ag-rows"></div>
      <div class="err" id="ag-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Split by percentage</span><span class="v">each pays a %</span></div>
      <label for="pct">Each diner's percentage, one per line (must total 100)</label>
      <textarea id="pct" rows="3" style="width:100%;padding:.6rem .7rem;font-size:1rem;
        border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;
        font-family:inherit;">50
30
20</textarea>
      <button class="chip" id="pct-go" style="margin-top:.6rem;flex:initial;width:100%;">Split by percentage</button>
      <div id="pct-rows"></div>
      <div class="err" id="pct-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Target per person</span><span class="v">clean split</span></div>
      <label for="tpp-target">Desired amount each diner pays</label>
      <input id="tpp-target" type="number" min="0" step="0.01" value="40" inputmode="decimal">
      <button class="chip" id="tpp-go" style="margin-top:.6rem;flex:initial;width:100%;">Find the tip</button>
      <div id="tpp-rows"></div>
      <div class="err" id="tpp-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Round the total</span><span class="v">to a clean number</span></div>
      <label for="rt-nearest">Round grand total to the nearest</label>
      <input id="rt-nearest" type="number" min="0" step="0.01" value="5" inputmode="decimal">
      <label for="rt-dir">Direction</label>
      <select id="rt-dir" style="width:100%;padding:.6rem .7rem;font-size:1rem;border-radius:8px;
        border:1px solid #334155;background:#0f172a;color:#e2e8f0;">
        <option value="up">Up (tip only grows)</option>
        <option value="nearest">Nearest (ties up)</option>
        <option value="down">Down (trim the tip)</option>
      </select>
      <button class="chip" id="rt-go" style="margin-top:.6rem;flex:initial;width:100%;">Round total</button>
      <div id="rt-rows"></div>
      <div class="err" id="rt-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Comp a diner</span><span class="v">birthday treat</span></div>
      <label for="comped">Diner numbers to treat (1-based), comma-separated</label>
      <input id="comped" type="text" value="3" placeholder="e.g. 3">
      <button class="chip" id="comped-go" style="margin-top:.6rem;flex:initial;width:100%;">Comp &amp; split</button>
      <div id="comped-rows"></div>
      <div class="err" id="comped-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Card-fee gross-up</span><span class="v">server nets the full tip</span></div>
      <label for="fee">Card processing fee percent</label>
      <input id="fee" type="number" min="0" max="99.99" step="0.01" value="3" inputmode="decimal">
      <button class="chip" id="fee-go" style="margin-top:.6rem;flex:initial;width:100%;">Gross up tip</button>
      <div id="fee-rows"></div>
      <div class="err" id="fee-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Shared items split</span><span class="v">personal + shared</span></div>
      <label for="shared-diners">Each diner's PERSONAL item prices, one diner per line</label>
      <textarea id="shared-diners" rows="3" style="width:100%;padding:.6rem .7rem;font-size:1rem;
        border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;
        font-family:inherit;">12
8
0</textarea>
      <label for="shared-items">SHARED items: price, then diner numbers (blank = everyone), per line</label>
      <textarea id="shared-items" rows="2" style="width:100%;padding:.6rem .7rem;font-size:1rem;
        border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;
        font-family:inherit;">30, 1 2 3
18, 1 2</textarea>
      <button class="chip" id="shared-go" style="margin-top:.6rem;flex:initial;width:100%;">Split shared items</button>
      <div id="shared-rows"></div>
      <div class="err" id="shared-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Regional tip</span><span class="v">customary by country</span></div>
      <label for="region">Country or region (e.g. US, Japan, uk)</label>
      <input id="region" type="text" value="US" placeholder="e.g. Japan">
      <button class="chip" id="region-go" style="margin-top:.6rem;flex:initial;width:100%;">Customary tip</button>
      <div id="region-rows"></div>
      <div class="err" id="region-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Round up for charity</span><span class="v">donate the change</span></div>
      <label for="charity-round">Round the total up to the nearest</label>
      <input id="charity-round" type="number" min="0" step="0.01" value="1" inputmode="decimal">
      <button class="chip" id="charity-go" style="margin-top:.6rem;flex:initial;width:100%;">Round up &amp; donate</button>
      <div id="charity-rows"></div>
      <div class="err" id="charity-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Tip on food only</span><span class="v">exclude the bar tab</span></div>
      <label for="excluded">Non-tippable charges (e.g. alcohol, gift card), comma-separated</label>
      <input id="excluded" type="text" value="40" placeholder="e.g. 40, 12.50">
      <button class="chip" id="excl-go" style="margin-top:.6rem;flex:initial;width:100%;">Tip on eligible</button>
      <div id="excl-rows"></div>
      <div class="err" id="excl-err"></div>
    </div>

    <div class="out">
      <div class="row"><span class="k">Everyone tips their own rate</span><span class="v">amount @ percent</span></div>
      <label for="diner-tips">One diner per line: amount @ tip%, e.g. "Sam 30 @ 20"</label>
      <textarea id="diner-tips" rows="3" style="width:100%;padding:.6rem .7rem;font-size:1rem;
        border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;
        font-family:inherit;">Sam 30 @ 20
Alex 45 @ 15
Jo 25 @ 25</textarea>
      <button class="chip" id="diner-tips-go" style="margin-top:.6rem;flex:initial;width:100%;">Split by individual tips</button>
      <div id="diner-tips-rows"></div>
      <div class="err" id="diner-tips-err"></div>
    </div>
  </div>

<script>
const $ = (id) => document.getElementById(id);
const money = (n) => "$" + Number(n).toFixed(2);
// Shared key/value row renderer — appends one ".row" div per [key, value] pair.
const renderRows = (id, rows) => {
  rows.forEach(([k, v]) => {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = '<span class="k">' + k + '</span><span class="v">' + v + '</span>';
    $(id).appendChild(row);
  });
};

async function calc() {
  const body = {
    bill: $("bill").value,
    tip_percent: $("tip").value,
    people: $("people").value,
    tax: $("tax").value,
    tip_on: $("pretax").checked ? "subtotal" : "total",
    round_total: $("roundup").checked,
  };
  try {
    const res = await fetch("/api/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) {
      $("out").hidden = true;
      $("err").textContent = data.error || "Invalid input";
      return;
    }
    $("err").textContent = "";
    $("o-tip").textContent = money(data.tip);
    $("o-total").textContent = money(data.total);
    $("o-tpp").textContent = money(data.tip_per_person);
    $("o-pp").textContent = money(data.total_per_person);
    $("out").hidden = false;
  } catch (e) {
    $("err").textContent = "Network error";
  }
}

document.querySelectorAll(".chip").forEach((c) =>
  c.addEventListener("click", () => { $("tip").value = c.dataset.tip; calc(); }));
["bill", "tip", "people", "tax"].forEach((id) => $(id).addEventListener("input", calc));
["pretax", "roundup"].forEach((id) => $(id).addEventListener("change", calc));
calc();

async function splitItems() {
  const lines = $("items").value.split("\n").map((l) => l.trim()).filter((l) => l.length);
  const people_items = lines.map((l) =>
    l.split(",").map((s) => s.trim()).filter((s) => s.length).map(Number));
  const body = {
    people_items,
    tip_percent: $("tip").value,
    tax: $("tax").value,
    tip_on: $("pretax").checked ? "subtotal" : "total",
  };
  $("items-rows").innerHTML = "";
  try {
    const res = await fetch("/api/items-split", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("items-err").textContent = data.error || "Invalid input"; return; }
    $("items-err").textContent = "";
    data.people.forEach((p, i) => {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<span class="k">Diner ' + (i + 1) + '</span><span class="v">' +
        money(p.amount) + '</span>';
      $("items-rows").appendChild(row);
    });
    const grand = document.createElement("div");
    grand.className = "row grand";
    grand.innerHTML = '<span class="k">Total</span><span class="v">' + money(data.total) + '</span>';
    $("items-rows").appendChild(grand);
  } catch (e) {
    $("items-err").textContent = "Network error";
  }
}
$("items-go").addEventListener("click", splitItems);

async function settleUp() {
  const paid = $("paid").value.split("\n").map((l) => l.trim())
    .filter((l) => l.length).map(Number);
  const body = {
    bill: $("bill").value,
    tip_percent: $("tip").value,
    paid,
  };
  $("settle-rows").innerHTML = "";
  try {
    const res = await fetch("/api/settle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("settle-err").textContent = data.error || "Invalid input"; return; }
    $("settle-err").textContent = "";
    if (!data.transfers.length) {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<span class="k">All settled</span><span class="v">nobody owes</span>';
      $("settle-rows").appendChild(row);
    }
    data.transfers.forEach((t) => {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<span class="k">Diner ' + (t.from + 1) + ' &rarr; Diner ' +
        (t.to + 1) + '</span><span class="v">' + money(t.amount) + '</span>';
      $("settle-rows").appendChild(row);
    });
  } catch (e) {
    $("settle-err").textContent = "Network error";
  }
}
$("settle-go").addEventListener("click", settleUp);

async function tipForRating() {
  const body = {
    bill: $("bill").value,
    rating: $("rating").value,
    people: $("people").value,
  };
  $("rating-rows").innerHTML = "";
  try {
    const res = await fetch("/api/rating", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("rating-err").textContent = data.error || "Invalid input"; return; }
    $("rating-err").textContent = "";
    const rows = [
      ["Suggested tip", data.tip_percent + "%"],
      ["Tip", money(data.tip)],
      ["Total", money(data.total)],
      ["Total / person", money(data.total_per_person)],
    ];
    renderRows("rating-rows", rows);
  } catch (e) {
    $("rating-err").textContent = "Network error";
  }
}
$("rating-go").addEventListener("click", tipForRating);

async function makeChange() {
  const body = { total: $("o-total").textContent.replace("$", "") || $("bill").value,
                 paid: $("paid-cash").value };
  $("change-rows").innerHTML = "";
  try {
    const res = await fetch("/api/change", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("change-err").textContent = data.error || "Invalid input"; return; }
    $("change-err").textContent = "";
    const head = document.createElement("div");
    head.className = "row grand";
    head.innerHTML = '<span class="k">Change</span><span class="v">' + money(data.change) + '</span>';
    $("change-rows").appendChild(head);
    data.breakdown.forEach((b) => {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<span class="k">' + b.denom + ' &times; ' + b.count +
        '</span><span class="v">' + money(b.value * b.count) + '</span>';
      $("change-rows").appendChild(row);
    });
  } catch (e) {
    $("change-err").textContent = "Network error";
  }
}
$("change-go").addEventListener("click", makeChange);

async function combineChecks() {
  const lines = $("combine").value.split("\n").map((l) => l.trim()).filter((l) => l.length);
  const checks = lines.map((l) => {
    const parts = l.split(",").map((s) => s.trim());
    return { bill: parts[0], tip_percent: parts[1] || 0 };
  });
  const body = { checks, people: $("people").value };
  $("combine-rows").innerHTML = "";
  try {
    const res = await fetch("/api/combine", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("combine-err").textContent = data.error || "Invalid input"; return; }
    $("combine-err").textContent = "";
    const rows = [
      ["Combined bill", money(data.bill)],
      ["Combined tip", money(data.tip)],
      ["Grand total", money(data.total)],
      ["Total / person", money(data.total_per_person)],
    ];
    renderRows("combine-rows", rows);
  } catch (e) {
    $("combine-err").textContent = "Network error";
  }
}
$("combine-go").addEventListener("click", combineChecks);

async function applyDiscount() {
  const body = {
    bill: $("bill").value,
    tip_percent: $("tip").value,
    people: $("people").value,
    discount: $("discount").value,
    discount_type: $("disc-pct").checked ? "percent" : "amount",
    tip_on_discounted: !$("disc-orig").checked,
  };
  $("discount-rows").innerHTML = "";
  try {
    const res = await fetch("/api/discount", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("discount-err").textContent = data.error || "Invalid input"; return; }
    $("discount-err").textContent = "";
    const rows = [
      ["You save", money(data.savings)],
      ["Discounted bill", money(data.discounted_bill)],
      ["Tip", money(data.tip)],
      ["Total", money(data.total)],
      ["Total / person", money(data.total_per_person)],
    ];
    renderRows("discount-rows", rows);
  } catch (e) {
    $("discount-err").textContent = "Network error";
  }
}
$("discount-go").addEventListener("click", applyDiscount);

async function sharePool() {
  const weights = $("weights").value.split("\n").map((l) => l.trim())
    .filter((l) => l.length).map(Number);
  const body = { pool: $("pool").value, weights };
  $("pool-rows").innerHTML = "";
  try {
    const res = await fetch("/api/tip-pool", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("pool-err").textContent = data.error || "Invalid input"; return; }
    $("pool-err").textContent = "";
    data.shares.forEach((s, i) => {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<span class="k">Staff ' + (i + 1) + '</span><span class="v">' +
        money(s) + '</span>';
      $("pool-rows").appendChild(row);
    });
    const grand = document.createElement("div");
    grand.className = "row grand";
    grand.innerHTML = '<span class="k">Pool</span><span class="v">' + money(data.total) + '</span>';
    $("pool-rows").appendChild(grand);
  } catch (e) {
    $("pool-err").textContent = "Network error";
  }
}
$("pool-go").addEventListener("click", sharePool);

async function splitCaps() {
  let lines = $("caps").value.split("\n");
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop();  // drop trailing blanks
  const caps = lines.map((l) => (l.trim() === "" ? null : Number(l.trim())));
  const body = {
    bill: $("bill").value,
    tip_percent: $("tip").value,
    people: caps.length,
    caps,
  };
  $("caps-rows").innerHTML = "";
  try {
    const res = await fetch("/api/split-caps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("caps-err").textContent = data.error || "Invalid input"; return; }
    $("caps-err").textContent = "";
    data.people_detail.forEach((p, i) => {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<span class="k">Diner ' + (i + 1) + (p.capped ? ' (capped)' : '') +
        '</span><span class="v">' + money(p.amount) + '</span>';
      $("caps-rows").appendChild(row);
    });
    const grand = document.createElement("div");
    grand.className = "row grand";
    grand.innerHTML = '<span class="k">Total</span><span class="v">' + money(data.total) + '</span>';
    $("caps-rows").appendChild(grand);
  } catch (e) {
    $("caps-err").textContent = "Network error";
  }
}
$("caps-go").addEventListener("click", splitCaps);

async function buildBill() {
  const lines = $("menu").value.split("\n").map((l) => l.trim()).filter((l) => l.length);
  const items = lines.map((l) => l.split(",").map((s) => s.trim()).filter((s) => s.length).map(Number));
  const body = {
    items,
    tax_percent: $("menu-tax").value,
    tip_percent: $("tip").value,
    people: $("people").value,
  };
  $("menu-rows").innerHTML = "";
  try {
    const res = await fetch("/api/build-bill", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("menu-err").textContent = data.error || "Invalid input"; return; }
    $("menu-err").textContent = "";
    data.line_items.forEach((it) => {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<span class="k">' + it.name + ' &times;' + it.qty +
        '</span><span class="v">' + money(it.amount) + '</span>';
      $("menu-rows").appendChild(row);
    });
    [["Subtotal", data.subtotal], ["Tax", data.tax], ["Tip", data.tip]].forEach(([k, v]) => {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<span class="k">' + k + '</span><span class="v">' + money(v) + '</span>';
      $("menu-rows").appendChild(row);
    });
    const grand = document.createElement("div");
    grand.className = "row grand";
    grand.innerHTML = '<span class="k">Total / person</span><span class="v">' +
      money(data.total_per_person) + '</span>';
    $("menu-rows").appendChild(grand);
  } catch (e) {
    $("menu-err").textContent = "Network error";
  }
}
$("menu-go").addEventListener("click", buildBill);

async function applyServiceCharge() {
  const desired = $("svc-desired").value.trim();
  const body = {
    bill: $("bill").value,
    service_percent: $("svc").value,
    desired_percent: desired === "" ? null : desired,
    people: $("people").value,
  };
  $("svc-rows").innerHTML = "";
  try {
    const res = await fetch("/api/service-charge", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("svc-err").textContent = data.error || "Invalid input"; return; }
    $("svc-err").textContent = "";
    [["Service charge", data.service], ["Voluntary top-up", data.top_up],
     ["Total gratuity", data.gratuity]].forEach(([k, v]) => {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<span class="k">' + k + '</span><span class="v">' + money(v) + '</span>';
      $("svc-rows").appendChild(row);
    });
    const grand = document.createElement("div");
    grand.className = "row grand";
    grand.innerHTML = '<span class="k">Total / person</span><span class="v">' +
      money(data.total_per_person) + '</span>';
    $("svc-rows").appendChild(grand);
  } catch (e) {
    $("svc-err").textContent = "Network error";
  }
}
$("svc-go").addEventListener("click", applyServiceCharge);

async function convertCurrency() {
  const body = {
    bill: $("bill").value,
    tip_percent: $("tip").value,
    people: $("people").value,
    rate: $("cur-rate").value,
    currency: $("cur-code").value,
  };
  $("cur-rows").innerHTML = "";
  try {
    const res = await fetch("/api/convert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("cur-err").textContent = data.error || "Invalid input"; return; }
    $("cur-err").textContent = "";
    const c = (n) => Number(n).toFixed(2) + " " + data.currency;
    [["Total (home)", money(data.total)], ["Total (" + data.currency + ")", c(data.converted.total)],
     ["Per person (" + data.currency + ")", c(data.converted.total_per_person)]].forEach(([k, v]) => {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<span class="k">' + k + '</span><span class="v">' + v + '</span>';
      $("cur-rows").appendChild(row);
    });
  } catch (e) {
    $("cur-err").textContent = "Network error";
  }
}
$("cur-go").addEventListener("click", convertCurrency);

async function autoGratuity() {
  const body = {
    bill: $("bill").value,
    people: $("people").value,
    threshold: $("ag-threshold").value,
    auto_percent: $("ag-auto").value,
    chosen_percent: $("tip").value,
  };
  $("ag-rows").innerHTML = "";
  try {
    const res = await fetch("/api/auto-gratuity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("ag-err").textContent = data.error || "Invalid input"; return; }
    $("ag-err").textContent = "";
    const rows = [
      [data.applied ? "Auto-gratuity applied" : "Voluntary tip", data.tip_percent + "%"],
      ["Tip", money(data.tip)],
      ["Total", money(data.total)],
      ["Total / person", money(data.total_per_person)],
    ];
    renderRows("ag-rows", rows);
  } catch (e) {
    $("ag-err").textContent = "Network error";
  }
}
$("ag-go").addEventListener("click", autoGratuity);

async function splitPercentage() {
  const percentages = $("pct").value.split("\n").map((l) => l.trim())
    .filter((l) => l.length).map(Number);
  const body = { bill: $("bill").value, tip_percent: $("tip").value, percentages };
  $("pct-rows").innerHTML = "";
  try {
    const res = await fetch("/api/split-percentage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("pct-err").textContent = data.error || "Invalid input"; return; }
    $("pct-err").textContent = "";
    data.amounts.forEach((a, i) => {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<span class="k">Diner ' + (i + 1) + ' (' + data.percentages[i] +
        '%)</span><span class="v">' + money(a) + '</span>';
      $("pct-rows").appendChild(row);
    });
    const grand = document.createElement("div");
    grand.className = "row grand";
    grand.innerHTML = '<span class="k">Total</span><span class="v">' + money(data.total) + '</span>';
    $("pct-rows").appendChild(grand);
  } catch (e) {
    $("pct-err").textContent = "Network error";
  }
}
$("pct-go").addEventListener("click", splitPercentage);

async function targetPerPerson() {
  const body = {
    bill: $("bill").value,
    target_per_person: $("tpp-target").value,
    people: $("people").value,
  };
  $("tpp-rows").innerHTML = "";
  try {
    const res = await fetch("/api/target-per-person", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("tpp-err").textContent = data.error || "Invalid input"; return; }
    $("tpp-err").textContent = "";
    const rows = [
      ["Required tip", money(data.tip)],
      ["Effective tip", data.effective_tip_percent + "%"],
      ["Total", money(data.total)],
      ["Each pays", money(data.total_per_person)],
    ];
    renderRows("tpp-rows", rows);
  } catch (e) {
    $("tpp-err").textContent = "Network error";
  }
}
$("tpp-go").addEventListener("click", targetPerPerson);

async function roundTotal() {
  const body = {
    bill: $("bill").value,
    base_percent: $("tip").value,
    nearest: $("rt-nearest").value,
    direction: $("rt-dir").value,
    people: $("people").value,
    tax: $("tax").value,
    tip_on: $("pretax").checked ? "subtotal" : "total",
  };
  $("rt-rows").innerHTML = "";
  try {
    const res = await fetch("/api/round-total", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("rt-err").textContent = data.error || "Invalid input"; return; }
    $("rt-err").textContent = "";
    const rows = [
      ["Base total", money(data.base_total)],
      ["Rounded total", money(data.total)],
      ["Rounding bonus", money(data.bonus)],
      ["Tip", money(data.tip)],
      ["Effective tip", data.effective_tip_percent + "%"],
      ["Total / person", money(data.total_per_person)],
    ];
    renderRows("rt-rows", rows);
  } catch (e) {
    $("rt-err").textContent = "Network error";
  }
}
$("rt-go").addEventListener("click", roundTotal);

async function compDiner() {
  const comped = $("comped").value.split(",").map((s) => s.trim())
    .filter((s) => s.length).map((s) => Number(s) - 1);  // 1-based UI -> 0-based
  const body = {
    bill: $("bill").value,
    tip_percent: $("tip").value,
    people: $("people").value,
    comped,
  };
  $("comped-rows").innerHTML = "";
  try {
    const res = await fetch("/api/split-comped", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("comped-err").textContent = data.error || "Invalid input"; return; }
    $("comped-err").textContent = "";
    data.people_detail.forEach((p, i) => {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<span class="k">Diner ' + (i + 1) + (p.comped ? ' (treated)' : '') +
        '</span><span class="v">' + money(p.amount) + '</span>';
      $("comped-rows").appendChild(row);
    });
    const grand = document.createElement("div");
    grand.className = "row grand";
    grand.innerHTML = '<span class="k">Total</span><span class="v">' + money(data.total) + '</span>';
    $("comped-rows").appendChild(grand);
  } catch (e) {
    $("comped-err").textContent = "Network error";
  }
}
$("comped-go").addEventListener("click", compDiner);

async function grossUpTip() {
  const body = {
    bill: $("bill").value,
    tip_percent: $("tip").value,
    fee_percent: $("fee").value,
    people: $("people").value,
  };
  $("fee-rows").innerHTML = "";
  try {
    const res = await fetch("/api/gross-up-tip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("fee-err").textContent = data.error || "Invalid input"; return; }
    $("fee-err").textContent = "";
    const rows = [
      ["Intended tip (net)", money(data.intended_tip)],
      ["Charge on card", money(data.gross_tip)],
      ["Processor fee", money(data.fee)],
      ["Total", money(data.total)],
      ["Total / person", money(data.total_per_person)],
    ];
    renderRows("fee-rows", rows);
  } catch (e) {
    $("fee-err").textContent = "Network error";
  }
}
$("fee-go").addEventListener("click", grossUpTip);

async function splitSharedItems() {
  const diners = $("shared-diners").value.split("\n").map((l) => l.trim())
    .filter((l) => l.length)
    .map((l) => l.split(",").map((s) => s.trim()).filter((s) => s.length).map(Number));
  const shared_items = $("shared-items").value.split("\n").map((l) => l.trim())
    .filter((l) => l.length).map((l) => {
      const parts = l.split(",").map((s) => s.trim());
      const price = Number(parts[0]);
      if (parts.length < 2 || parts[1] === "") return price;  // shared by everyone
      const sharers = parts[1].split(/\\s+/).filter((s) => s.length).map((s) => Number(s) - 1);
      return { price, sharers };
    });
  const body = {
    diners,
    shared_items,
    tip_percent: $("tip").value,
    tax: $("tax").value,
    tip_on: $("pretax").checked ? "subtotal" : "total",
  };
  $("shared-rows").innerHTML = "";
  try {
    const res = await fetch("/api/shared-items", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("shared-err").textContent = data.error || "Invalid input"; return; }
    $("shared-err").textContent = "";
    data.people.forEach((p, i) => {
      const row = document.createElement("div");
      row.className = "row";
      row.innerHTML = '<span class="k">Diner ' + (i + 1) + '</span><span class="v">' +
        money(p.amount) + '</span>';
      $("shared-rows").appendChild(row);
    });
    const grand = document.createElement("div");
    grand.className = "row grand";
    grand.innerHTML = '<span class="k">Total</span><span class="v">' + money(data.total) + '</span>';
    $("shared-rows").appendChild(grand);
  } catch (e) {
    $("shared-err").textContent = "Network error";
  }
}
$("shared-go").addEventListener("click", splitSharedItems);

async function regionalTip() {
  const body = {
    bill: $("bill").value,
    region: $("region").value,
    people: $("people").value,
  };
  $("region-rows").innerHTML = "";
  try {
    const res = await fetch("/api/regional-tip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("region-err").textContent = data.error || "Invalid input"; return; }
    $("region-err").textContent = "";
    const rows = [
      [data.region_name, data.customary + "% (" + data.low + "–" + data.high + "%)"],
      ["Tip", money(data.tip)],
      ["Total", money(data.total)],
      ["Total / person", money(data.total_per_person)],
    ];
    renderRows("region-rows", rows);
  } catch (e) {
    $("region-err").textContent = "Network error";
  }
}
$("region-go").addEventListener("click", regionalTip);

async function charityRoundUp() {
  const body = {
    bill: $("bill").value,
    tip_percent: $("tip").value,
    people: $("people").value,
    round_to: $("charity-round").value,
    tax: $("tax").value,
    tip_on: $("pretax").checked ? "subtotal" : "total",
  };
  $("charity-rows").innerHTML = "";
  try {
    const res = await fetch("/api/charity", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("charity-err").textContent = data.error || "Invalid input"; return; }
    $("charity-err").textContent = "";
    const rows = [
      ["Bill + tip", money(data.base_total)],
      ["Charity donation", money(data.donation)],
      ["Total", money(data.total)],
      ["Total / person", money(data.total_per_person)],
    ];
    renderRows("charity-rows", rows);
  } catch (e) {
    $("charity-err").textContent = "Network error";
  }
}
$("charity-go").addEventListener("click", charityRoundUp);

async function tipExcluding() {
  const excluded = $("excluded").value.split(",").map((s) => s.trim())
    .filter((s) => s.length).map(Number);
  const body = {
    bill: $("bill").value,
    tip_percent: $("tip").value,
    people: $("people").value,
    excluded,
  };
  $("excl-rows").innerHTML = "";
  try {
    const res = await fetch("/api/tip-excluding", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("excl-err").textContent = data.error || "Invalid input"; return; }
    $("excl-err").textContent = "";
    const rows = [
      ["Excluded", money(data.excluded)],
      ["Tippable base", money(data.eligible)],
      ["Tip", money(data.tip)],
      ["Effective tip", data.effective_tip_percent + "%"],
      ["Total", money(data.total)],
      ["Total / person", money(data.total_per_person)],
    ];
    renderRows("excl-rows", rows);
  } catch (e) {
    $("excl-err").textContent = "Network error";
  }
}
$("excl-go").addEventListener("click", tipExcluding);

// Parse "Name 30 @ 20" / "30 @ 20" lines into {name, amount, tip_percent} diners.
function parseDinerTips(text) {
  return text.split("\n").map((s) => s.trim()).filter((s) => s.length).map((line) => {
    const [left, right] = line.split("@");
    const tip_percent = Number((right || "").trim());
    const tokens = (left || "").trim().split(/\s+/);
    const amount = Number(tokens.pop());
    const name = tokens.join(" ");
    const diner = { amount, tip_percent };
    if (name) diner.name = name;
    return diner;
  });
}

async function dinerTips() {
  const body = { diners: parseDinerTips($("diner-tips").value), tax: $("tax").value };
  $("diner-tips-rows").innerHTML = "";
  try {
    const res = await fetch("/api/diner-tips", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) { $("diner-tips-err").textContent = data.error || "Invalid input"; return; }
    $("diner-tips-err").textContent = "";
    const rows = data.diners.map((d) => [
      d.name + " (" + d.tip_percent + "%)", money(d.total),
    ]);
    rows.push(["Tip total", money(data.tip)]);
    rows.push(["Grand total", money(data.total)]);
    renderRows("diner-tips-rows", rows);
  } catch (e) {
    $("diner-tips-err").textContent = "Network error";
  }
}
$("diner-tips-go").addEventListener("click", dinerTips);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "TipCalc/1.0"

    def _send(self, code, body, content_type="application/json"):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json")

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, INDEX_HTML, "text/html; charset=utf-8")
        elif self.path == "/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path not in ("/api/calculate", "/api/suggestions", "/api/split",
                             "/api/reverse", "/api/round-split", "/api/items-split",
                             "/api/settle", "/api/rating", "/api/change",
                             "/api/combine", "/api/discount", "/api/tip-pool",
                             "/api/split-caps", "/api/build-bill",
                             "/api/service-charge", "/api/convert",
                             "/api/auto-gratuity", "/api/split-percentage",
                             "/api/target-per-person", "/api/round-total",
                             "/api/split-comped", "/api/gross-up-tip",
                             "/api/shared-items", "/api/regional-tip",
                             "/api/charity", "/api/tip-excluding",
                             "/api/diner-tips"):
            self._send_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON body"})
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
            return
        try:
            if self.path == "/api/calculate":
                result = calculate_tip(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("round_total", False),
                    data.get("tax", 0),
                    data.get("tip_on", "total"),
                )
            elif self.path == "/api/suggestions":
                result = suggest_tips(
                    data.get("bill"),
                    data.get("people", 1),
                    data.get("percents", (10, 15, 18, 20, 25)),
                )
            elif self.path == "/api/reverse":
                result = reverse_tip(
                    data.get("bill"),
                    data.get("target_total"),
                    data.get("people", 1),
                )
            elif self.path == "/api/round-split":
                result = round_up_split(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("nearest", 1.0),
                )
            elif self.path == "/api/items-split":
                result = split_by_items(
                    data.get("people_items"),
                    data.get("tip_percent"),
                    data.get("tax", 0),
                    data.get("tip_on", "subtotal"),
                )
            elif self.path == "/api/settle":
                result = settle_up(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("paid"),
                    data.get("shares"),
                )
            elif self.path == "/api/rating":
                result = tip_for_rating(
                    data.get("bill"),
                    data.get("rating"),
                    data.get("people", 1),
                )
            elif self.path == "/api/change":
                result = change_due(
                    data.get("total"),
                    data.get("paid"),
                )
            elif self.path == "/api/combine":
                result = combine_checks(
                    data.get("checks"),
                    data.get("people", 1),
                )
            elif self.path == "/api/discount":
                result = apply_discount(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("discount", 0),
                    data.get("discount_type", "amount"),
                    data.get("tip_on_discounted", True),
                    data.get("people", 1),
                )
            elif self.path == "/api/tip-pool":
                result = tip_pool(
                    data.get("pool"),
                    data.get("weights"),
                )
            elif self.path == "/api/split-caps":
                result = split_with_caps(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("caps"),
                )
            elif self.path == "/api/build-bill":
                result = build_bill(
                    data.get("items"),
                    data.get("tax_percent", 0),
                    data.get("tip_percent", 0),
                    data.get("people", 1),
                )
            elif self.path == "/api/service-charge":
                result = service_charge(
                    data.get("bill"),
                    data.get("service_percent"),
                    data.get("desired_percent"),
                    data.get("people", 1),
                )
            elif self.path == "/api/convert":
                result = convert_currency(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("rate"),
                    data.get("people", 1),
                    data.get("currency", "USD"),
                )
            elif self.path == "/api/auto-gratuity":
                result = auto_gratuity(
                    data.get("bill"),
                    data.get("people", 1),
                    data.get("threshold", 6),
                    data.get("auto_percent", 18),
                    data.get("chosen_percent"),
                )
            elif self.path == "/api/split-percentage":
                result = split_by_percentage(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("percentages"),
                )
            elif self.path == "/api/target-per-person":
                result = tip_for_target_per_person(
                    data.get("bill"),
                    data.get("target_per_person"),
                    data.get("people", 1),
                )
            elif self.path == "/api/round-total":
                result = round_total_to(
                    data.get("bill"),
                    data.get("base_percent", 0),
                    data.get("nearest", 5.0),
                    data.get("direction", "up"),
                    data.get("people", 1),
                    data.get("tax", 0),
                    data.get("tip_on", "total"),
                )
            elif self.path == "/api/split-comped":
                result = split_comped(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("comped"),
                )
            elif self.path == "/api/gross-up-tip":
                result = gross_up_tip(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("fee_percent", 0),
                    data.get("people", 1),
                )
            elif self.path == "/api/shared-items":
                result = split_shared_items(
                    data.get("diners"),
                    data.get("shared_items"),
                    data.get("tip_percent", 0),
                    data.get("tax", 0),
                    data.get("tip_on", "subtotal"),
                )
            elif self.path == "/api/regional-tip":
                result = recommend_regional_tip(
                    data.get("bill"),
                    data.get("region"),
                    data.get("people", 1),
                )
            elif self.path == "/api/charity":
                result = charity_round_up(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("people", 1),
                    data.get("round_to", 1.0),
                    data.get("donation"),
                    data.get("tax", 0),
                    data.get("tip_on", "total"),
                )
            elif self.path == "/api/tip-excluding":
                result = tip_excluding(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("excluded", 0),
                    data.get("people", 1),
                )
            elif self.path == "/api/diner-tips":
                result = tip_by_diner(
                    data.get("diners"),
                    data.get("tax", 0),
                )
            else:  # /api/split
                result = split_by_shares(
                    data.get("bill"),
                    data.get("tip_percent"),
                    data.get("shares"),
                )
        except TipError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, result)

    def log_message(self, *args):  # keep test/runner output quiet
        pass


def run(host="0.0.0.0", port=8000):
    httpd = ThreadingHTTPServer((host, port), Handler)
    print("Tip calculator serving on http://localhost:%d" % port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run()
