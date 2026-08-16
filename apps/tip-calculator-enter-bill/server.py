import json
import math
import os
import http.server
import socketserver


def calculate_tip(bill, tip_percent):
    """Calculate tip and total. Returns (tip, total) rounded to 2 decimals.
    Raises ValueError on invalid input."""
    if bill is None or tip_percent is None:
        raise ValueError("bill and tip_percent are required")
    try:
        bill = float(bill)
        tip_percent = float(tip_percent)
    except (TypeError, ValueError):
        raise ValueError("bill and tip_percent must be numbers")
    if bill < 0:
        raise ValueError("bill must be non-negative")
    if tip_percent < 0 or tip_percent > 100:
        raise ValueError("tip_percent must be between 0 and 100")
    tip = round(bill * tip_percent / 100.0, 2)
    total = round(bill + tip, 2)
    return tip, total


MAX_PEOPLE = 1000


def _coerce_people(people):
    """Validate and coerce a head count to a whole int >= 1 (<= MAX_PEOPLE).
    Accepts 3, 3.0 or "3"; rejects fractional, zero, negative, or huge counts.
    Raises ValueError on invalid input."""
    if people is None:
        return 1
    try:
        as_float = float(people)
    except (TypeError, ValueError):
        raise ValueError("people must be a whole number")
    if math.isnan(as_float) or math.isinf(as_float):
        raise ValueError("people must be a whole number")
    if as_float != int(as_float):
        raise ValueError("people must be a whole number")
    count = int(as_float)
    if count < 1:
        raise ValueError("people must be at least 1")
    if count > MAX_PEOPLE:
        raise ValueError("people must be %d or fewer" % MAX_PEOPLE)
    return count


def round_total_to(bill, total, mode="up", increment=1.0):
    """Round a grand ``total`` to a multiple of ``increment`` and let the tip
    absorb the difference so ``bill + tip == total`` still holds.

    ``mode`` is ``"up"`` (next multiple, the polite default), ``"down"`` (previous
    multiple) or ``"nearest"`` (closest multiple, halves rounding up).
    ``increment`` is the rounding step in dollars (e.g. ``1.0`` for whole
    dollars, ``5.0`` to round to the nearest $5, ``0.25`` for quarters). The
    total is never rounded below the pre-tip bill, so the tip stays
    non-negative. Returns ``(tip, total)``. Raises ValueError on bad input."""
    bill = _coerce_finite(bill, "bill")
    total = _coerce_finite(total, "total")
    increment = _coerce_finite(increment, "increment")
    if increment <= 0:
        raise ValueError("increment must be greater than zero")
    if mode not in ("up", "down", "nearest"):
        raise ValueError("mode must be 'up', 'down', or 'nearest'")
    steps = total / increment
    if mode == "up":
        steps = math.ceil(steps - 1e-9)
    elif mode == "down":
        steps = math.floor(steps + 1e-9)
    else:
        steps = math.floor(steps + 0.5)
    new_total = round(steps * increment, 2)
    if new_total < bill:
        new_total = round(bill, 2)
    new_tip = round(new_total - bill, 2)
    return new_tip, new_total


def round_total_up(bill, total):
    """Round the total UP to the next whole dollar; the tip absorbs the
    difference so bill + tip still equals total. Returns (tip, total).

    Thin wrapper over :func:`round_total_to` with ``mode="up"`` and a $1 step,
    kept for backward compatibility."""
    return round_total_to(bill, total, mode="up", increment=1.0)


def format_money(amount, symbol="$"):
    """Format a number as a currency string with grouped thousands and two
    decimals, e.g. ``format_money(1234.5) == "$1,234.50"``.

    ``symbol`` is the currency symbol/prefix (default ``"$"``). Negative amounts
    render with a leading minus sign (``"-$5.00"``). Raises ValueError on a
    non-finite amount or an empty symbol."""
    value = _coerce_finite(amount, "amount")
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("symbol must be a non-empty string")
    value = round(value, 2)
    sign = "-" if value < 0 else ""
    return "%s%s%s" % (sign, symbol, "{:,.2f}".format(abs(value)))


def _fmt_pct(percent):
    """Render a percent without a needless trailing ``.0`` (8.0 -> "8",
    12.5 -> "12.5"). Used for human-readable receipt lines."""
    percent = round(float(percent), 2)
    if percent == int(percent):
        return str(int(percent))
    return ("%.2f" % percent).rstrip("0").rstrip(".")


def split_shares(total, count):
    """Split a money total into ``count`` shares whose values sum EXACTLY to
    the total to the cent. Leftover cents (when the total does not divide
    evenly) are handed out one at a time to the earliest payers, so the
    returned list always satisfies ``sum(shares) == round(total, 2)``.

    Returns the list of per-person amounts (floats rounded to 2 decimals)."""
    count = _coerce_people(count)
    cents = int(round(float(total) * 100))
    base, extra = divmod(cents, count)
    return [round((base + (1 if i < extra else 0)) / 100.0, 2)
            for i in range(count)]


def split_bill(bill, tip_percent, people=1, round_total=False, weights=None,
               round_mode="up", round_increment=1.0):
    """Compute tip, total and a per-person breakdown for a shared bill.

    Returns a dict with tip, total, people, per_person, per_person_tip,
    rounded, plus an exact ``shares`` list (cents sum to the total),
    ``remainder_cents`` (how many payers cover one extra cent) and
    ``per_person_max``/``per_person_min``. When ``round_total`` is truthy the
    total is rounded first via :func:`round_total_to` using ``round_mode``
    (``"up"``/``"down"``/``"nearest"``, default ``"up"``) and ``round_increment``
    (the rounding step in dollars, default ``1.0``); the response then also
    carries ``round_mode`` and ``round_increment``. When ``weights`` is given (a
    list of positive numbers), the bill is split UNEVENLY by those weights
    instead of evenly and ``people`` is taken from the weight count; the
    response also carries the ``weights`` used. Raises ValueError on any invalid
    input."""
    tip, total = calculate_tip(bill, tip_percent)
    rounded = bool(round_total)
    if rounded:
        tip, total = round_total_to(float(bill), total, mode=round_mode,
                                    increment=round_increment)
    if weights is not None:
        shares = split_weighted(total, weights)
        count = len(shares)
    else:
        count = _coerce_people(people)
        shares = split_shares(total, count)
    per_person = round(total / count, 2)
    per_person_tip = round(tip / count, 2)
    total_cents = int(round(total * 100))
    remainder_cents = total_cents % count
    result = {
        "tip": tip,
        "total": total,
        "people": count,
        "per_person": per_person,
        "per_person_tip": per_person_tip,
        "rounded": rounded,
        "shares": shares,
        "remainder_cents": remainder_cents,
        "per_person_max": max(shares),
        "per_person_min": min(shares),
    }
    if weights is not None:
        result["weights"] = [round(float(w), 4) for w in weights]
    if rounded:
        result["round_mode"] = round_mode
        result["round_increment"] = round(float(round_increment), 4)
    return result


DEFAULT_PRESETS = (10, 15, 18, 20, 25)


def tip_presets(bill, percents=None):
    """Compute tip/total for several candidate tip percentages at once so a
    diner can compare options for a single bill.

    Returns a dict with ``bill`` and an ``options`` list of
    ``{tip_percent, tip, total}`` entries. Raises ValueError on invalid
    input (bad bill, non-list percents, or any out-of-range percent)."""
    if percents is None:
        percents = list(DEFAULT_PRESETS)
    if isinstance(percents, (str, bytes)) or not isinstance(percents, (list, tuple)):
        raise ValueError("percents must be a list of numbers")
    if not percents:
        raise ValueError("percents must not be empty")
    options = []
    for p in percents:
        tip, total = calculate_tip(bill, p)
        options.append({
            "tip_percent": round(float(p), 2),
            "tip": tip,
            "total": total,
        })
    return {"bill": round(float(bill), 2), "options": options}


def reverse_tip(bill, target_total):
    """Derive the tip and tip percent needed to reach a desired grand total.

    Given a bill and the total a diner wants to pay, return the implied tip
    and tip percent so ``bill + tip == target_total``. Raises ValueError when
    inputs are missing/non-numeric, the bill is negative, the target is below
    the bill, or the bill is zero (no percent is derivable)."""
    if bill is None or target_total is None:
        raise ValueError("bill and target_total are required")
    try:
        bill = float(bill)
        target_total = float(target_total)
    except (TypeError, ValueError):
        raise ValueError("bill and target_total must be numbers")
    if math.isnan(bill) or math.isinf(bill) or math.isnan(target_total) or math.isinf(target_total):
        raise ValueError("bill and target_total must be finite numbers")
    if bill < 0:
        raise ValueError("bill must be non-negative")
    if target_total < bill:
        raise ValueError("target_total must be at least the bill")
    if bill == 0:
        raise ValueError("bill must be greater than zero to derive a tip percent")
    tip = round(target_total - bill, 2)
    tip_percent = round(tip / bill * 100.0, 2)
    return {
        "bill": round(bill, 2),
        "tip": tip,
        "total": round(target_total, 2),
        "tip_percent": tip_percent,
    }


def _coerce_finite(value, name):
    """Coerce ``value`` to a finite float or raise ValueError with ``name``."""
    if value is None:
        raise ValueError("%s is required" % name)
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise ValueError("%s must be a number" % name)
    if math.isnan(out) or math.isinf(out):
        raise ValueError("%s must be a finite number" % name)
    return out


def calculate_with_tax(bill, tip_percent, tax_percent=0, tip_on="pretax"):
    """Compute a tax-aware breakdown for a pre-tax bill.

    ``bill`` is the pre-tax subtotal. ``tax_percent`` adds sales tax. The tip
    is taken either on the pre-tax subtotal (``tip_on="pretax"``, the polite
    default) or on the post-tax amount (``tip_on="posttax"``). Returns a dict
    with subtotal, tax, tip, total, tip_percent, tax_percent and tip_on. All
    money values are rounded to two decimals. Raises ValueError on bad input."""
    subtotal = _coerce_finite(bill, "bill")
    tip_percent = _coerce_finite(tip_percent, "tip_percent")
    tax_percent = _coerce_finite(tax_percent, "tax_percent")
    if subtotal < 0:
        raise ValueError("bill must be non-negative")
    if tip_percent < 0 or tip_percent > 100:
        raise ValueError("tip_percent must be between 0 and 100")
    if tax_percent < 0 or tax_percent > 100:
        raise ValueError("tax_percent must be between 0 and 100")
    if tip_on not in ("pretax", "posttax"):
        raise ValueError("tip_on must be 'pretax' or 'posttax'")
    tax = round(subtotal * tax_percent / 100.0, 2)
    tip_base = subtotal if tip_on == "pretax" else round(subtotal + tax, 2)
    tip = round(tip_base * tip_percent / 100.0, 2)
    total = round(subtotal + tax + tip, 2)
    return {
        "subtotal": round(subtotal, 2),
        "tax": tax,
        "tip": tip,
        "total": total,
        "tip_percent": round(tip_percent, 2),
        "tax_percent": round(tax_percent, 2),
        "tip_on": tip_on,
    }


# Service rating (1 = poor … 5 = excellent) → conventional tip percent.
RATING_PERCENTS = {1: 10, 2: 15, 3: 18, 4: 20, 5: 25}
RATING_LABELS = {
    1: "poor", 2: "fair", 3: "good", 4: "great", 5: "excellent",
}


def suggest_tip_percent(rating):
    """Map a 1–5 service rating to a conventional tip percent.

    Accepts 4, 4.0 or "4"; rejects fractional, out-of-range or non-numeric
    ratings. Raises ValueError on invalid input."""
    if rating is None:
        raise ValueError("rating is required")
    try:
        as_float = float(rating)
    except (TypeError, ValueError):
        raise ValueError("rating must be a whole number from 1 to 5")
    if math.isnan(as_float) or math.isinf(as_float) or as_float != int(as_float):
        raise ValueError("rating must be a whole number from 1 to 5")
    value = int(as_float)
    if value not in RATING_PERCENTS:
        raise ValueError("rating must be a whole number from 1 to 5")
    return value


def suggest_tip(bill, rating):
    """Suggest a tip for a bill from a 1–5 service rating.

    Returns a dict with rating, label, the suggested tip_percent, tip and
    total. Raises ValueError on a bad bill or rating."""
    value = suggest_tip_percent(rating)
    percent = RATING_PERCENTS[value]
    tip, total = calculate_tip(bill, percent)
    return {
        "rating": value,
        "label": RATING_LABELS[value],
        "tip_percent": float(percent),
        "tip": tip,
        "total": total,
    }


def split_weighted(total, weights):
    """Split a money ``total`` across payers by ``weights`` so the shares sum
    EXACTLY to the total to the cent.

    ``weights`` is a list of positive numbers (e.g. how much each person ate).
    Uses the largest-remainder (Hamilton) method to distribute leftover cents
    to the payers with the biggest fractional share, so
    ``sum(shares) == round(total, 2)`` always holds. Raises ValueError on an
    empty list, a non-list, or any non-positive/non-finite weight."""
    if isinstance(weights, (str, bytes)) or not isinstance(weights, (list, tuple)):
        raise ValueError("weights must be a list of numbers")
    if not weights:
        raise ValueError("weights must not be empty")
    clean = []
    for w in weights:
        wf = _coerce_finite(w, "weight")
        if wf <= 0:
            raise ValueError("each weight must be greater than zero")
        clean.append(wf)
    cents = int(round(float(total) * 100))
    weight_sum = math.fsum(clean)
    raw = [cents * w / weight_sum for w in clean]
    floors = [int(math.floor(r)) for r in raw]
    remainder = cents - sum(floors)
    # Hand out the leftover cents to the largest fractional parts (ties: earlier).
    order = sorted(range(len(clean)), key=lambda i: (raw[i] - floors[i], -i),
                   reverse=True)
    for i in order[:remainder]:
        floors[i] += 1
    return [round(c / 100.0, 2) for c in floors]


def _largest_remainder(total_cents, weights):
    """Apportion ``total_cents`` whole cents across payers in proportion to
    ``weights`` using the largest-remainder (Hamilton) method, so the returned
    integer-cent list sums EXACTLY to ``total_cents``. Leftover cents go to the
    biggest fractional shares (ties: earlier payers). Assumes a positive weight
    sum; callers must short-circuit the all-zero case."""
    weight_sum = math.fsum(weights)
    raw = [total_cents * w / weight_sum for w in weights]
    floors = [int(math.floor(r)) for r in raw]
    remainder = total_cents - sum(floors)
    order = sorted(range(len(weights)), key=lambda i: (raw[i] - floors[i], -i),
                   reverse=True)
    for i in order[:remainder]:
        floors[i] += 1
    return floors


def split_itemized(people, tip_percent, tax_percent=0, tip_on="pretax"):
    """Split an itemized bill where each diner pays for their own items, then
    shares tip and tax in proportion to what they ordered.

    ``people`` is a list of ``{"name": str, "items": [amounts]}`` entries. Each
    person's subtotal is the sum of their item amounts. Tip and tax are computed
    on the whole bill via :func:`calculate_with_tax` and then apportioned to
    each diner by their subtotal using the largest-remainder method, so the
    per-person totals sum EXACTLY to the grand total to the cent.

    Returns a dict with the whole-bill ``subtotal``/``tax``/``tip``/``total``
    (plus ``tip_percent``/``tax_percent``/``tip_on`` and ``people`` count) and a
    ``breakdown`` list of ``{name, subtotal, tax, tip, total}`` per diner.
    Raises ValueError on any invalid input."""
    if isinstance(people, (str, bytes)) or not isinstance(people, (list, tuple)):
        raise ValueError("people must be a list")
    if not people:
        raise ValueError("people must not be empty")
    names = []
    subtotals = []
    for entry in people:
        if not isinstance(entry, dict):
            raise ValueError("each person must be an object with items")
        items = entry.get("items", [])
        if isinstance(items, (str, bytes)) or not isinstance(items, (list, tuple)):
            raise ValueError("items must be a list of numbers")
        person_subtotal = 0.0
        for item in items:
            value = _coerce_finite(item, "item")
            if value < 0:
                raise ValueError("item amounts must be non-negative")
            person_subtotal += value
        name = entry.get("name")
        names.append(name if name else "Person %d" % (len(names) + 1))
        subtotals.append(round(person_subtotal, 2))
    grand_subtotal = round(math.fsum(subtotals), 2)
    totals = calculate_with_tax(grand_subtotal, tip_percent, tax_percent, tip_on)
    tax_cents = int(round(totals["tax"] * 100))
    tip_cents = int(round(totals["tip"] * 100))
    sub_cents = [int(round(s * 100)) for s in subtotals]
    if sum(sub_cents) == 0:
        tax_alloc = [0] * len(subtotals)
        tip_alloc = [0] * len(subtotals)
    else:
        tax_alloc = _largest_remainder(tax_cents, sub_cents)
        tip_alloc = _largest_remainder(tip_cents, sub_cents)
    breakdown = []
    for i, name in enumerate(names):
        person_tax = round(tax_alloc[i] / 100.0, 2)
        person_tip = round(tip_alloc[i] / 100.0, 2)
        person_total = round(subtotals[i] + person_tax + person_tip, 2)
        breakdown.append({
            "name": name,
            "subtotal": subtotals[i],
            "tax": person_tax,
            "tip": person_tip,
            "total": person_total,
        })
    return {
        "subtotal": totals["subtotal"],
        "tax": totals["tax"],
        "tip": totals["tip"],
        "total": totals["total"],
        "tip_percent": totals["tip_percent"],
        "tax_percent": totals["tax_percent"],
        "tip_on": totals["tip_on"],
        "people": len(subtotals),
        "breakdown": breakdown,
    }


def build_receipt(bill, tip_percent, tax_percent=0, tip_on="pretax",
                  people=1, weights=None, title="Receipt", symbol="$"):
    """Build a formatted, shareable plain-text receipt for a bill.

    Computes the tax-aware totals via :func:`calculate_with_tax`, then splits the
    grand total across payers (evenly by ``people`` or unevenly by ``weights``).
    Returns a dict with the numeric ``subtotal``/``tax``/``tip``/``total`` (plus
    ``tip_percent``/``tax_percent``/``tip_on``/``people``), the exact per-person
    ``shares``, a ``lines`` list of formatted rows and a ready-to-copy ``text``
    blob joining those lines. Money is rendered with :func:`format_money` using
    ``symbol``. Raises ValueError on any invalid input."""
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a non-empty string")
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("symbol must be a non-empty string")
    totals = calculate_with_tax(bill, tip_percent, tax_percent, tip_on)
    grand_total = totals["total"]
    if weights is not None:
        shares = split_weighted(grand_total, weights)
    else:
        count = _coerce_people(people)
        shares = split_shares(grand_total, count)
    count = len(shares)
    title = title.strip()

    def money(value):
        return format_money(value, symbol)

    def row(label, value):
        return label.ljust(18) + money(value)

    lines = [title, "=" * max(len(title), 26)]
    lines.append(row("Subtotal", totals["subtotal"]))
    if totals["tax"] or totals["tax_percent"]:
        lines.append(row("Tax (%s%%)" % _fmt_pct(totals["tax_percent"]),
                         totals["tax"]))
    lines.append(row("Tip (%s%%)" % _fmt_pct(totals["tip_percent"]),
                     totals["tip"]))
    lines.append("-" * 26)
    lines.append(row("Total", grand_total))
    if count > 1:
        lines.append("-" * 26)
        for i, share in enumerate(shares):
            lines.append(row("Person %d" % (i + 1), share))
    return {
        "title": title,
        "currency": symbol,
        "subtotal": totals["subtotal"],
        "tax": totals["tax"],
        "tip": totals["tip"],
        "total": grand_total,
        "tip_percent": totals["tip_percent"],
        "tax_percent": totals["tax_percent"],
        "tip_on": totals["tip_on"],
        "people": count,
        "shares": shares,
        "lines": lines,
        "text": "\n".join(lines),
    }


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

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
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
        self._send_json(404, {"error": "not found"})

    def _read_json(self):
        """Read and parse a JSON request body. Returns (data, None) on success
        or (None, error_message) on failure."""
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return (json.loads(raw.decode("utf-8")) if raw else {}), None
        except (ValueError, UnicodeDecodeError):
            return None, "invalid JSON"

    def do_POST(self):
        if self.path in ("/api/tip", "/api/split"):
            data, err = self._read_json()
            if err:
                self._send_json(400, {"error": err})
                return
            try:
                result = split_bill(
                    data.get("bill"),
                    data.get("tip_percent"),
                    people=data.get("people"),
                    round_total=data.get("round_total", False),
                    weights=data.get("weights"),
                    round_mode=data.get("round_mode", "up"),
                    round_increment=data.get("round_increment", 1.0),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/tax":
            data, err = self._read_json()
            if err:
                self._send_json(400, {"error": err})
                return
            try:
                result = calculate_with_tax(
                    data.get("bill"),
                    data.get("tip_percent"),
                    tax_percent=data.get("tax_percent", 0),
                    tip_on=data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/suggest":
            data, err = self._read_json()
            if err:
                self._send_json(400, {"error": err})
                return
            try:
                result = suggest_tip(data.get("bill"), data.get("rating"))
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/presets":
            data, err = self._read_json()
            if err:
                self._send_json(400, {"error": err})
                return
            try:
                result = tip_presets(data.get("bill"), data.get("percents"))
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/itemize":
            data, err = self._read_json()
            if err:
                self._send_json(400, {"error": err})
                return
            try:
                result = split_itemized(
                    data.get("people"),
                    data.get("tip_percent"),
                    tax_percent=data.get("tax_percent", 0),
                    tip_on=data.get("tip_on", "pretax"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/receipt":
            data, err = self._read_json()
            if err:
                self._send_json(400, {"error": err})
                return
            try:
                result = build_receipt(
                    data.get("bill"),
                    data.get("tip_percent"),
                    tax_percent=data.get("tax_percent", 0),
                    tip_on=data.get("tip_on", "pretax"),
                    people=data.get("people", 1),
                    weights=data.get("weights"),
                    title=data.get("title", "Receipt"),
                    symbol=data.get("symbol", "$"),
                )
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/reverse":
            data, err = self._read_json()
            if err:
                self._send_json(400, {"error": err})
                return
            try:
                result = reverse_tip(data.get("bill"), data.get("total"))
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
    port = int(os.environ.get("ADF_SMOKE_PORT") or os.environ.get("PORT") or 8000)
    server = make_server(port)
    print("Tip calculator server ready on http://127.0.0.1:%d" % port)
    server.serve_forever()
