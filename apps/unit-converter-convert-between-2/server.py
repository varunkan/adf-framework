import json
import os
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE_DIR, "index.html")

# General multi-category conversion engine (additive; length/mass/temp/volume/time).
sys.path.insert(0, BASE_DIR)
import domain

# Exact international conversion factor: 1 foot == 0.3048 meters (definition).
FEET_PER_METER = 1.0 / 0.3048
METERS_PER_FOOT = 0.3048

# Accepted direction aliases -> canonical direction.
M2F_ALIASES = ("m2f", "mtof", "meters-to-feet", "meter-to-feet", "m_to_f")
F2M_ALIASES = ("f2m", "ftom", "feet-to-meters", "foot-to-meter", "f_to_m")


def meters_to_feet(meters):
    """Convert a length in meters to feet."""
    return meters * FEET_PER_METER


def feet_to_meters(feet):
    """Convert a length in feet to meters."""
    return feet * METERS_PER_FOOT


def convert(value, direction):
    """Pure domain conversion. Returns (result, unit) or raises ValueError.

    direction is normalized (lowercased, trimmed) by the caller.
    """
    if direction in M2F_ALIASES:
        return meters_to_feet(value), "ft"
    if direction in F2M_ALIASES:
        return feet_to_meters(value), "m"
    raise ValueError("'direction' must be 'm2f' or 'f2m'")


# Default decimal places for the general/JSON conversion responses.
DEFAULT_PRECISION = 6
MAX_PRECISION = 12


def resolve_precision(data, default=DEFAULT_PRECISION):
    """Read an optional integer ``precision`` field from a request body.

    Returns (precision, error_message). When the field is absent the default is
    used and error_message is None. The value must be an integer in
    [0, MAX_PRECISION]; anything else yields (None, <message>) so the caller can
    emit a 400 without changing the legacy default behaviour.
    """
    if "precision" not in data or data.get("precision") is None:
        return default, None
    raw = data.get("precision")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None, "'precision' must be an integer"
    if raw < 0 or raw > MAX_PRECISION:
        return None, "'precision' must be between 0 and %d" % MAX_PRECISION
    return raw, None


class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        # Silence default logging to keep test output clean.
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status, html_bytes):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html_bytes)))
        self.end_headers()
        self.wfile.write(html_bytes)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            try:
                with open(INDEX_PATH, "rb") as f:
                    html = f.read()
            except OSError:
                self._send_json(500, {"error": "index.html not found"})
                return
            self._send_html(200, html)
            return
        if self.path == "/api/health":
            self._send_json(200, {"status": "ok"})
            return
        if self.path == "/api/units":
            categories = {
                cat: domain.units_for(cat) for cat in domain.list_categories()
            }
            self._send_json(200, {"categories": categories})
            return
        if self.path == "/api/categories":
            self._send_json(200, {"categories": domain.list_categories()})
            return
        # /api/unit-info?unit=ft -> category + accepted aliases for a unit.
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/api/unit-info":
            params = urllib.parse.parse_qs(parsed.query)
            unit = (params.get("unit") or [None])[0]
            if not unit:
                self._send_json(400, {"error": "missing 'unit' query parameter"})
                return
            try:
                info = domain.unit_info(unit)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, info)
            return
        # /api/factor?from=km&to=m -> the pure multiplicative factor between two
        # linear units (value_to == value_from * factor). Affine/reciprocal
        # categories (temperature, fuel) return a 400.
        if parsed.path == "/api/factor":
            params = urllib.parse.parse_qs(parsed.query)
            from_unit = (params.get("from") or [None])[0]
            to_unit = (params.get("to") or [None])[0]
            if not from_unit or not to_unit:
                self._send_json(400, {"error": "missing 'from' or 'to' query parameter"})
                return
            try:
                factor, category = domain.conversion_factor(from_unit, to_unit)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {
                "from": domain.normalize_unit(from_unit),
                "to": domain.normalize_unit(to_unit),
                "category": category,
                "factor": factor,
            })
            return
        # /api/search?q=met -> every accepted unit token matching the query.
        if parsed.path == "/api/search":
            params = urllib.parse.parse_qs(parsed.query)
            query = (params.get("q") or [None])[0]
            if query is None:
                self._send_json(400, {"error": "missing 'q' query parameter"})
                return
            try:
                matches = domain.search_units(query)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"query": query, "matches": matches})
            return
        self._send_json(404, {"error": "not found"})

    def _read_json_body(self):
        """Read+parse a JSON request body. Returns (data, error_payload).

        On success error_payload is None; on failure data is None and the
        caller should emit a 400 with error_payload.
        """
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            return None, {"error": "invalid JSON body"}
        return data, None

    # ----- shared request-validation helpers -------------------------------
    # Every POST handler shares the same opening checks (read body -> require a
    # JSON object -> resolve precision -> pull common fields). These helpers
    # hold that logic in ONE place; each helper emits its own 400 and returns a
    # sentinel (None) so callers stay a uniform two-line guard rather than a
    # copy-pasted preamble.

    def _json_body_obj(self):
        """Read+validate a JSON *object* body. On error emit the 400 and return
        None; on success return the dict."""
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, err)
            return None
        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
            return None
        return data

    def _precision_or_400(self, data):
        """Resolve the optional ``precision`` field. On error emit the 400 and
        return None; otherwise return the integer precision (0 is valid)."""
        precision, perr = resolve_precision(data)
        if perr is not None:
            self._send_json(400, {"error": perr})
            return None
        return precision

    def _items_request(self, data):
        """Validate the shared ``{items:[...], to?}`` aggregate body. Returns
        (items, to_unit, precision) or None after emitting a 400."""
        items = data.get("items")
        if not isinstance(items, list):
            self._send_json(400, {"error": "'items' must be a list"})
            return None
        precision = self._precision_or_400(data)
        if precision is None:
            return None
        return items, data.get("to"), precision

    def _value_from_request(self, data):
        """Validate the shared ``{value, from}`` body. Returns
        (value, from_unit, precision) or None after emitting a 400."""
        value = data.get("value")
        from_unit = data.get("from")
        if value is None or from_unit is None:
            self._send_json(400, {"error": "missing 'value' or 'from'"})
            return None
        precision = self._precision_or_400(data)
        if precision is None:
            return None
        return value, from_unit, precision

    def _value_from_to_request(self, data):
        """Validate the shared ``{value, from, to}`` body. Returns
        (value, from_unit, to_unit, precision) or None after emitting a 400."""
        value = data.get("value")
        from_unit = data.get("from")
        to_unit = data.get("to")
        if value is None or from_unit is None or to_unit is None:
            self._send_json(400, {"error": "missing 'value', 'from' or 'to'"})
            return None
        precision = self._precision_or_400(data)
        if precision is None:
            return None
        return value, from_unit, to_unit, precision

    def _expression_request(self, data):
        """Validate the shared ``{expression}`` body. Returns
        (expression, precision) or None after emitting a 400."""
        expression = data.get("expression")
        if expression is None:
            self._send_json(400, {"error": "missing 'expression'"})
            return None
        precision = self._precision_or_400(data)
        if precision is None:
            return None
        return expression, precision

    def _paired_request(self, data):
        """Validate the shared bivariate ``{x:[...], y:[...], to_x?, to_y?}`` body.
        Returns (x, y, to_x, to_y, precision) or None after emitting a 400."""
        x = data.get("x")
        y = data.get("y")
        if not isinstance(x, list) or not isinstance(y, list):
            self._send_json(400, {"error": "'x' and 'y' must be lists"})
            return None
        precision = self._precision_or_400(data)
        if precision is None:
            return None
        return x, y, data.get("to_x"), data.get("to_y"), precision

    def _round_opt(self, value, places):
        """Round ``value`` to ``places``, passing ``None`` straight through.

        Bivariate stats can be genuinely undefined (e.g. Pearson r when a series
        has zero spread), reported as ``None``; ``round(None, ...)`` would raise,
        so this preserves the null instead."""
        return round(value, places) if value is not None else None

    def _conversion_payload(self, value, from_unit, to_unit, category, result,
                            places, **extra):
        """Build the shared {input, from, to, category, result} body used by the
        single-quantity convert responses. ``extra`` carries the per-endpoint
        tail (e.g. ``precision=`` or ``interval=True``)."""
        payload = {
            "input": float(value),
            "from": domain.normalize_unit(from_unit),
            "to": domain.normalize_unit(to_unit),
            "category": category,
            "result": round(result, places),
        }
        payload.update(extra)
        return payload

    def _aggregate_payload(self, result, precision, items):
        """Build the shared {category, unit, count, total, items} body used by
        the running-total style aggregate responses."""
        return {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "total": round(result["total"], precision),
            "items": items,
        }

    def do_POST(self):
        if self.path == "/api/convert-all":
            self._handle_convert_all()
            return
        if self.path == "/api/convert-batch":
            self._handle_convert_batch()
            return
        if self.path == "/api/convert-table":
            self._handle_convert_table()
            return
        if self.path == "/api/compound":
            self._handle_compound()
            return
        if self.path == "/api/parse":
            self._handle_parse()
            return
        if self.path == "/api/humanize":
            self._handle_humanize()
            return
        if self.path == "/api/compare":
            self._handle_compare()
            return
        if self.path == "/api/sum":
            self._handle_sum()
            return
        if self.path == "/api/parse-compound":
            self._handle_parse_compound()
            return
        if self.path == "/api/convert-delta":
            self._handle_convert_delta()
            return
        if self.path == "/api/stats":
            self._handle_stats()
            return
        if self.path == "/api/sort":
            self._handle_sort()
            return
        if self.path == "/api/describe":
            self._handle_describe()
            return
        if self.path == "/api/shape":
            self._handle_shape()
            return
        if self.path == "/api/cumsum":
            self._handle_cumsum()
            return
        if self.path == "/api/percentile":
            self._handle_percentile()
            return
        if self.path == "/api/proportions":
            self._handle_proportions()
            return
        if self.path == "/api/diff":
            self._handle_diff()
            return
        if self.path == "/api/zscore":
            self._handle_zscore()
            return
        if self.path == "/api/normalize":
            self._handle_normalize()
            return
        if self.path == "/api/quartiles":
            self._handle_quartiles()
            return
        if self.path == "/api/outliers":
            self._handle_outliers()
            return
        if self.path == "/api/histogram":
            self._handle_histogram()
            return
        if self.path == "/api/means":
            self._handle_means()
            return
        if self.path == "/api/mad":
            self._handle_mad()
            return
        if self.path == "/api/rank":
            self._handle_rank()
            return
        if self.path == "/api/mode":
            self._handle_mode()
            return
        if self.path == "/api/weighted-mean":
            self._handle_weighted_mean()
            return
        if self.path == "/api/moving-average":
            self._handle_moving_average()
            return
        if self.path == "/api/covariance":
            self._handle_covariance()
            return
        if self.path == "/api/correlation":
            self._handle_correlation()
            return
        if self.path == "/api/regression":
            self._handle_regression()
            return
        if self.path == "/api/gini":
            self._handle_gini()
            return
        if self.path != "/api/convert":
            self._send_json(404, {"error": "not found"})
            return

        data = self._json_body_obj()
        if data is None:
            return

        value = data.get("value")
        direction = data.get("direction")
        from_unit = data.get("from")
        to_unit = data.get("to")

        # General multi-category path: {value, from, to}. Additive — only taken
        # when no legacy 'direction' is provided.
        if direction is None and (from_unit is not None or to_unit is not None):
            parsed = self._value_from_to_request(data)
            if parsed is None:
                return
            value, from_unit, to_unit, precision = parsed
            try:
                result, category = domain.convert_units(value, from_unit, to_unit)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, self._conversion_payload(
                value, from_unit, to_unit, category, result, precision,
                precision=precision))
            return

        if value is None or direction is None:
            self._send_json(400, {"error": "missing 'value' or 'direction'"})
            return

        # Accept numbers or numeric strings.
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            self._send_json(400, {"error": "'value' must be a number"})
            return

        if numeric != numeric or numeric in (float("inf"), float("-inf")):
            self._send_json(400, {"error": "'value' must be finite"})
            return

        direction = str(direction).strip().lower()

        try:
            result, unit = convert(numeric, direction)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        rounded = round(result, 4)
        self._send_json(200, {
            "input": numeric,
            "direction": direction,
            "result": rounded,
            "unit": unit,
        })


    def _handle_convert_all(self):
        """POST /api/convert-all — {value, from} -> value in every unit of the
        category. Additive: never touches the legacy or general /api/convert."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._value_from_request(data)
        if parsed is None:
            return
        value, from_unit, precision = parsed
        try:
            results, category = domain.convert_to_all(value, from_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "input": float(value),
            "from": domain.normalize_unit(from_unit),
            "category": category,
            "results": [
                {"unit": r["unit"], "result": round(r["result"], precision)}
                for r in results
            ],
        })

    def _handle_parse(self):
        """POST /api/parse — {expression: "10 km to mi"} -> a conversion result.

        Additive natural-language entry point; delegates parsing + conversion to
        the domain layer and never touches the structured /api/convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._expression_request(data)
        if parsed is None:
            return
        expression, precision = parsed
        try:
            value, from_u, to_u, result, category = domain.convert_expression(expression)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "expression": str(expression),
            "input": value,
            "from": from_u,
            "to": to_u,
            "category": category,
            "result": round(result, precision),
        })

    def _handle_humanize(self):
        """POST /api/humanize — {value, from} -> the same quantity rescaled to
        the most readable unit on its metric ladder (e.g. 1500 m -> 1.5 km).

        Additive: a pure presentation helper that reuses ``domain.humanize`` and
        never touches the structured /api/convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._value_from_request(data)
        if parsed is None:
            return
        value, from_unit, precision = parsed
        try:
            scaled, unit, category = domain.humanize(value, from_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "input": float(value),
            "from": domain.normalize_unit(from_unit),
            "category": category,
            "value": round(scaled, precision),
            "unit": unit,
        })

    def _handle_convert_batch(self):
        """POST /api/convert-batch — {conversions: [{value, from, to}, ...]} ->
        a parallel list of results. Each entry is converted independently; a bad
        entry yields an {"error": ...} object in place rather than failing the
        whole batch."""
        data = self._json_body_obj()
        if data is None:
            return
        conversions = data.get("conversions")
        if not isinstance(conversions, list):
            self._send_json(400, {"error": "'conversions' must be a list"})
            return
        out = []
        for item in conversions:
            if not isinstance(item, dict):
                out.append({"error": "each conversion must be an object"})
                continue
            value = item.get("value")
            from_unit = item.get("from")
            to_unit = item.get("to")
            if value is None or from_unit is None or to_unit is None:
                out.append({"error": "missing 'value', 'from' or 'to'"})
                continue
            try:
                result, category = domain.convert_units(value, from_unit, to_unit)
            except ValueError as exc:
                out.append({"error": str(exc)})
                continue
            out.append({
                "input": float(value),
                "from": domain.normalize_unit(from_unit),
                "to": domain.normalize_unit(to_unit),
                "category": category,
                "result": round(result, 6),
            })
        self._send_json(200, {"results": out})

    def _handle_compound(self):
        """POST /api/compound — {value, from, units: [...]} -> a mixed-unit
        breakdown of the quantity (e.g. 3661 s -> 1 h 1 min 1 s). Additive:
        reuses ``domain.to_compound`` and never touches the other convert
        paths."""
        data = self._json_body_obj()
        if data is None:
            return
        value = data.get("value")
        from_unit = data.get("from")
        units = data.get("units")
        if value is None or from_unit is None or units is None:
            self._send_json(400, {"error": "missing 'value', 'from' or 'units'"})
            return
        precision = self._precision_or_400(data)
        if precision is None:
            return
        try:
            parts, category = domain.to_compound(value, from_unit, units)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        rounded = [
            {"unit": p["unit"], "value": round(p["value"], precision)}
            for p in parts
        ]
        self._send_json(200, {
            "input": float(value),
            "from": domain.normalize_unit(from_unit),
            "category": category,
            "parts": rounded,
            "formatted": domain.format_compound(rounded),
        })

    def _handle_compare(self):
        """POST /api/compare — {a:{value,unit}, b:{value,unit}} -> which of two
        quantities of the same category is larger, plus each restated in the
        other's unit, their ratio and difference. Additive: reuses
        ``domain.compare_quantities`` and never touches the convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        a = data.get("a")
        b = data.get("b")
        if not isinstance(a, dict) or not isinstance(b, dict):
            self._send_json(400, {"error": "'a' and 'b' must be objects with 'value' and 'unit'"})
            return
        a_value, a_unit = a.get("value"), a.get("unit")
        b_value, b_unit = b.get("value"), b.get("unit")
        if a_value is None or a_unit is None or b_value is None or b_unit is None:
            self._send_json(400, {"error": "each of 'a'/'b' needs a 'value' and a 'unit'"})
            return
        precision = self._precision_or_400(data)
        if precision is None:
            return
        try:
            cmp = domain.compare_quantities(a_value, a_unit, b_value, b_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        ratio = cmp["ratio"]
        self._send_json(200, {
            "category": cmp["category"],
            "a": cmp["a"],
            "b": cmp["b"],
            "a_in_b_unit": round(cmp["a_in_b_unit"], precision),
            "b_in_a_unit": round(cmp["b_in_a_unit"], precision),
            "difference": round(cmp["difference"], precision),
            "ratio": (round(ratio, precision) if ratio is not None else None),
            "larger": cmp["larger"],
        })

    def _handle_convert_table(self):
        """POST /api/convert-table — {from, to, start, stop, step} -> a table of
        results across the inclusive [start, stop] range. Additive: reuses
        ``domain.conversion_table`` and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        from_unit = data.get("from")
        to_unit = data.get("to")
        start = data.get("start")
        stop = data.get("stop")
        step = data.get("step")
        if (from_unit is None or to_unit is None or start is None
                or stop is None or step is None):
            self._send_json(400, {
                "error": "missing 'from', 'to', 'start', 'stop' or 'step'"})
            return
        precision = self._precision_or_400(data)
        if precision is None:
            return
        try:
            rows, category = domain.conversion_table(
                from_unit, to_unit, start, stop, step)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "from": domain.normalize_unit(from_unit),
            "to": domain.normalize_unit(to_unit),
            "category": category,
            "count": len(rows),
            "rows": [
                {"input": round(r["input"], precision),
                 "result": round(r["result"], precision)}
                for r in rows
            ],
        })


    def _handle_sum(self):
        """POST /api/sum — {items: [{value, unit}, ...], to?} -> the total of a
        list of same-category quantities, expressed in 'to' (or the first item's
        unit). Additive: reuses ``domain.sum_quantities`` and never touches the
        other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            total, unit, category = domain.sum_quantities(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "count": len(items),
            "category": category,
            "unit": unit,
            "total": round(total, precision),
        })

    def _handle_parse_compound(self):
        """POST /api/parse-compound — {expression: "6 ft 2 in", to?} -> the parsed
        parts plus their total in 'to' (or the smallest part's unit). The inverse
        of /api/compound. Additive: reuses ``domain.compound_total``."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._expression_request(data)
        if parsed is None:
            return
        expression, precision = parsed
        to_unit = data.get("to")
        try:
            if to_unit is None:
                # Default target: the smallest (last) part's unit, mirroring how
                # format_compound reads a quantity smallest-unit last.
                parts, category = domain.parse_compound(expression)
                to_unit = parts[-1]["unit"]
                total, unit, _ = domain.sum_quantities(parts, to_unit)
            else:
                total, unit, category, parts = domain.compound_total(expression, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "expression": str(expression),
            "category": category,
            "parts": parts,
            "unit": unit,
            "total": round(total, precision),
        })

    def _handle_stats(self):
        """POST /api/stats — {items: [{value, unit}, ...], to?} -> count, sum,
        mean, min, max and range of a list of same-category quantities, all
        restated in 'to' (or the first item's unit). The descriptive-statistics
        companion to /api/sum. Additive: reuses ``domain.aggregate_quantities``
        and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            stats = domain.aggregate_quantities(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": stats["category"],
            "unit": stats["unit"],
            "count": stats["count"],
            "sum": round(stats["sum"], precision),
            "mean": round(stats["mean"], precision),
            "min": {"value": round(stats["min"]["value"], precision),
                    "index": stats["min"]["index"]},
            "max": {"value": round(stats["max"]["value"], precision),
                    "index": stats["max"]["index"]},
            "range": round(stats["range"], precision),
        })

    def _handle_sort(self):
        """POST /api/sort — {items: [{value, unit}, ...], to?, descending?} ->
        the items ordered by magnitude on a common unit, each tagged with its
        original input index. The ordering companion to /api/sum and /api/stats.
        Additive: reuses ``domain.sort_quantities`` and never touches the other
        convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        descending = bool(data.get("descending", False))
        try:
            result = domain.sort_quantities(items, to_unit, descending)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "descending": result["descending"],
            "items": [
                {"index": r["index"], "value": round(r["value"], precision)}
                for r in result["items"]
            ],
        })

    def _handle_describe(self):
        """POST /api/describe — {items: [{value, unit}, ...], to?} -> the full
        descriptive statistics (count, sum, mean, median, variance, population &
        sample standard deviation, min, max, range) of a list of same-category
        quantities, all restated in 'to' (or the first item's unit). The richer
        companion to /api/stats. Additive: reuses ``domain.describe_quantities``
        and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            stats = domain.describe_quantities(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        sample_variance = stats["sample_variance"]
        sample_stdev = stats["sample_stdev"]
        self._send_json(200, {
            "category": stats["category"],
            "unit": stats["unit"],
            "count": stats["count"],
            "sum": round(stats["sum"], precision),
            "mean": round(stats["mean"], precision),
            "median": round(stats["median"], precision),
            "variance": round(stats["variance"], precision),
            "stdev": round(stats["stdev"], precision),
            "sample_variance": (round(sample_variance, precision)
                                if sample_variance is not None else None),
            "sample_stdev": (round(sample_stdev, precision)
                             if sample_stdev is not None else None),
            "min": {"value": round(stats["min"]["value"], precision),
                    "index": stats["min"]["index"]},
            "max": {"value": round(stats["max"]["value"], precision),
                    "index": stats["max"]["index"]},
            "range": round(stats["range"], precision),
        })

    def _handle_shape(self):
        """POST /api/shape — {items: [{value, unit}, ...], to?} -> the
        distribution-shape statistics (skewness and excess kurtosis, in both
        population and bias-corrected sample flavours) of a list of same-category
        quantities, restated in 'to' (or the first item's unit). The third-/
        fourth-moment companion to /api/describe (which stops at variance/stdev).
        Additive: reuses ``domain.shape_quantities`` and never touches the other
        convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.shape_quantities(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "mean": round(result["mean"], precision),
            "stdev": round(result["stdev"], precision),
            "skewness": self._round_opt(result["skewness"], precision),
            "sample_skewness": self._round_opt(result["sample_skewness"], precision),
            "kurtosis": self._round_opt(result["kurtosis"], precision),
            "sample_kurtosis": self._round_opt(result["sample_kurtosis"], precision),
        })

    def _handle_cumsum(self):
        """POST /api/cumsum — {items: [{value, unit}, ...], to?} -> the running
        (cumulative) total after each item, all restated in 'to' (or the first
        item's unit). The "how does the total build up?" companion to /api/sum.
        Additive: reuses ``domain.cumulative_quantities`` and never touches the
        other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.cumulative_quantities(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "total": round(result["total"], precision),
            "items": [
                {"index": r["index"],
                 "value": round(r["value"], precision),
                 "cumulative": round(r["cumulative"], precision)}
                for r in result["items"]
            ],
        })

    def _handle_percentile(self):
        """POST /api/percentile — {items: [{value, unit}, ...], percentile, to?}
        -> the p-th percentile of a list of same-category quantities, restated in
        'to' (or the first item's unit). The percentile companion to /api/describe
        (which already reports the median == percentile 50). Additive: reuses
        ``domain.percentile_quantities`` and never touches the convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        items = data.get("items")
        if not isinstance(items, list):
            self._send_json(400, {"error": "'items' must be a list"})
            return
        if "percentile" not in data or data.get("percentile") is None:
            self._send_json(400, {"error": "missing 'percentile'"})
            return
        to_unit = data.get("to")
        precision = self._precision_or_400(data)
        if precision is None:
            return
        try:
            result = domain.percentile_quantities(
                items, data.get("percentile"), to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "percentile": result["percentile"],
            "value": round(result["value"], precision),
        })

    def _handle_proportions(self):
        """POST /api/proportions — {items: [{value, unit}, ...], to?} -> each
        quantity's share of the group total, as a fraction and a percentage, all
        restated in 'to' (or the first item's unit). The "what slice of the whole
        is each part?" companion to /api/sum and /api/cumsum. Additive: reuses
        ``domain.proportions`` and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.proportions(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "total": round(result["total"], precision),
            "items": [
                {"index": r["index"],
                 "value": round(r["value"], precision),
                 "fraction": round(r["fraction"], precision),
                 "percent": round(r["percent"], precision)}
                for r in result["items"]
            ],
        })

    def _handle_diff(self):
        """POST /api/diff — {items: [{value, unit}, ...], to?} -> the successive
        difference between each consecutive quantity, all restated in 'to' (or the
        first item's unit). The discrete inverse of /api/cumsum (the differences
        fed back through cumsum reconstruct the series). Additive: reuses
        ``domain.differences`` and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.differences(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "total": round(result["total"], precision),
            "items": [
                {"index": r["index"],
                 "value": round(r["value"], precision),
                 "difference": round(r["difference"], precision)}
                for r in result["items"]
            ],
        })

    def _handle_zscore(self):
        """POST /api/zscore — {items: [{value, unit}, ...], to?} -> each quantity's
        z-score ((value - mean) / population stdev), all restated in 'to' (or the
        first item's unit). The "how many standard deviations from the mean is each
        measurement?" companion to /api/describe. Additive: reuses
        ``domain.zscores`` and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.zscores(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "mean": round(result["mean"], precision),
            "stdev": round(result["stdev"], precision),
            "items": [
                {"index": r["index"],
                 "value": round(r["value"], precision),
                 "zscore": round(r["zscore"], precision)}
                for r in result["items"]
            ],
        })

    def _handle_normalize(self):
        """POST /api/normalize — {items: [{value, unit}, ...], to?} -> each
        quantity min-max scaled to [0, 1] ((value - min) / (max - min)), all
        restated in 'to' (or the first item's unit). The "where does each value sit
        on the observed scale?" companion to /api/proportions. Additive: reuses
        ``domain.normalize_quantities`` and never touches the other convert
        paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.normalize_quantities(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "min": round(result["min"], precision),
            "max": round(result["max"], precision),
            "items": [
                {"index": r["index"],
                 "value": round(r["value"], precision),
                 "normalized": round(r["normalized"], precision)}
                for r in result["items"]
            ],
        })

    def _handle_quartiles(self):
        """POST /api/quartiles — {items: [{value, unit}, ...], to?} -> the
        five-number summary (min, Q1, median, Q3, max) and the interquartile
        range of a list of same-category quantities, all restated in 'to' (or the
        first item's unit). The box-plot companion to /api/describe and
        /api/percentile. Additive: reuses ``domain.quartiles`` and never touches
        the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.quartiles(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "min": round(result["min"], precision),
            "q1": round(result["q1"], precision),
            "median": round(result["median"], precision),
            "q3": round(result["q3"], precision),
            "max": round(result["max"], precision),
            "iqr": round(result["iqr"], precision),
        })

    def _handle_outliers(self):
        """POST /api/outliers — {items: [{value, unit}, ...], to?, k?} -> each
        quantity flagged as an outlier (or not) by Tukey's IQR fences
        (lower = Q1 - k*IQR, upper = Q3 + k*IQR; k defaults to 1.5), all restated
        in 'to' (or the first item's unit). The anomaly-detection companion to
        /api/quartiles and /api/zscore. Additive: reuses ``domain.outliers`` and
        never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        # k is optional; the domain layer defaults and validates it.
        k = data.get("k", 1.5)
        try:
            result = domain.outliers(items, to_unit, k)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "k": result["k"],
            "q1": round(result["q1"], precision),
            "q3": round(result["q3"], precision),
            "iqr": round(result["iqr"], precision),
            "lower_fence": round(result["lower_fence"], precision),
            "upper_fence": round(result["upper_fence"], precision),
            "outlier_count": result["outlier_count"],
            "items": [
                {"index": r["index"],
                 "value": round(r["value"], precision),
                 "is_outlier": r["is_outlier"]}
                for r in result["items"]
            ],
        })

    def _handle_histogram(self):
        """POST /api/histogram — {items: [{value, unit}, ...], bins, to?} -> the
        equal-width bin counts of a list of same-category quantities (the counts
        sum to count), all restated in 'to' (or the first item's unit). The
        distribution-shape companion to /api/describe and /api/quartiles.
        Additive: reuses ``domain.histogram`` and never touches the other convert
        paths."""
        data = self._json_body_obj()
        if data is None:
            return
        items = data.get("items")
        if not isinstance(items, list):
            self._send_json(400, {"error": "'items' must be a list"})
            return
        if "bins" not in data or data.get("bins") is None:
            self._send_json(400, {"error": "missing 'bins'"})
            return
        to_unit = data.get("to")
        precision = self._precision_or_400(data)
        if precision is None:
            return
        try:
            result = domain.histogram(items, data.get("bins"), to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "bins": result["bins"],
            "min": round(result["min"], precision),
            "max": round(result["max"], precision),
            "items": [
                {"index": r["index"],
                 "start": round(r["start"], precision),
                 "end": round(r["end"], precision),
                 "count": r["count"]}
                for r in result["items"]
            ],
        })

    def _handle_means(self):
        """POST /api/means — {items: [{value, unit}, ...], to?} -> the four
        classical means (arithmetic, geometric, harmonic, quadratic/RMS) of a
        list of same-category quantities, all restated in 'to' (or the first
        item's unit). The "which average?" companion to /api/describe. Additive:
        reuses ``domain.means`` and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.means(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "arithmetic": round(result["arithmetic"], precision),
            "geometric": round(result["geometric"], precision),
            "harmonic": round(result["harmonic"], precision),
            "quadratic": round(result["quadratic"], precision),
        })

    def _handle_mad(self):
        """POST /api/mad — {items: [{value, unit}, ...], to?} -> the
        absolute-deviation (robust dispersion) statistics: the mean and median
        centres, the mean absolute deviation about the mean, the median absolute
        deviation (the classic outlier-robust MAD) and its normal-consistent
        scaled form, plus each item's absolute deviation from the mean, all
        restated in 'to' (or the first item's unit). The outlier-robust companion
        to /api/describe (which reports variance/stdev). Additive: reuses
        ``domain.mad_quantities`` and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.mad_quantities(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "mean": round(result["mean"], precision),
            "median": round(result["median"], precision),
            "mean_abs_deviation": round(result["mean_abs_deviation"], precision),
            "median_abs_deviation": round(result["median_abs_deviation"], precision),
            "median_abs_deviation_scaled": round(
                result["median_abs_deviation_scaled"], precision),
            "items": [
                {"index": r["index"],
                 "value": round(r["value"], precision),
                 "abs_deviation": round(r["abs_deviation"], precision)}
                for r in result["items"]
            ],
        })

    def _handle_rank(self):
        """POST /api/rank — {items: [{value, unit}, ...], to?, descending?} ->
        each quantity's rank (1-based, ties share the average rank) and percentile
        rank, all restated in 'to' (or the first item's unit). The inverse view of
        /api/percentile and the per-item companion to /api/sort. Additive: reuses
        ``domain.rank_quantities`` and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        descending = bool(data.get("descending", False))
        try:
            result = domain.rank_quantities(items, to_unit, descending)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "descending": result["descending"],
            "items": [
                {"index": r["index"],
                 "value": round(r["value"], precision),
                 "rank": r["rank"],
                 "percent_rank": round(r["percent_rank"], precision)}
                for r in result["items"]
            ],
        })

    def _handle_mode(self):
        """POST /api/mode — {items: [{value, unit}, ...], to?} -> the mode(s),
        the most frequent magnitude(s) on a common unit, with the highest
        observed frequency and a multimodal flag. The frequency-based measure of
        central tendency, companion to the mean/median of /api/describe.
        Additive: reuses ``domain.mode_quantities`` and never touches the other
        convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.mode_quantities(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "frequency": result["frequency"],
            "is_multimodal": result["is_multimodal"],
            "modes": [round(m, precision) for m in result["modes"]],
        })

    def _handle_weighted_mean(self):
        """POST /api/weighted-mean — {items: [{value, unit, weight?}, ...], to?}
        -> the weighted average sum(w*v)/sum(w) on a common unit (a missing
        weight defaults to 1, reducing to the plain mean). The "some measurements
        count more" companion to /api/describe. Additive: reuses
        ``domain.weighted_mean`` and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.weighted_mean(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "total_weight": round(result["total_weight"], precision),
            "weighted_mean": round(result["weighted_mean"], precision),
        })

    def _handle_moving_average(self):
        """POST /api/moving-average — {items: [{value, unit}, ...], window, to?}
        -> the simple moving average over each contiguous window of 'window'
        consecutive items on a common unit (n items -> n-window+1 averages). The
        smoothing/trend companion to /api/cumsum and /api/diff. Additive: reuses
        ``domain.moving_average`` and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        items = data.get("items")
        if not isinstance(items, list):
            self._send_json(400, {"error": "'items' must be a list"})
            return
        if "window" not in data or data.get("window") is None:
            self._send_json(400, {"error": "missing 'window'"})
            return
        to_unit = data.get("to")
        precision = self._precision_or_400(data)
        if precision is None:
            return
        try:
            result = domain.moving_average(items, data.get("window"), to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "window": result["window"],
            "items": [
                {"start_index": r["start_index"],
                 "end_index": r["end_index"],
                 "average": round(r["average"], precision)}
                for r in result["items"]
            ],
        })

    def _handle_convert_delta(self):
        """POST /api/convert-delta — {value, from, to} -> an INTERVAL conversion
        (e.g. a 10 C change is an 18 F change, not 50 F). Additive: reuses
        ``domain.convert_delta`` and never touches the absolute convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._value_from_to_request(data)
        if parsed is None:
            return
        value, from_unit, to_unit, precision = parsed
        try:
            result, category = domain.convert_delta(value, from_unit, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "input": float(value),
            "from": domain.normalize_unit(from_unit),
            "to": domain.normalize_unit(to_unit),
            "category": category,
            "result": round(result, precision),
            "interval": True,
        })

    def _handle_covariance(self):
        """POST /api/covariance — {x:[{value,unit},...], y:[...], to_x?, to_y?}
        -> the population and sample covariance of two paired quantity series.
        The raw "do they move together?" companion to /api/correlation. Additive:
        reuses ``domain.covariance`` and never touches the convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._paired_request(data)
        if parsed is None:
            return
        x, y, to_x, to_y, precision = parsed
        try:
            result = domain.covariance(x, y, to_x, to_y)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "x_category": result["x_category"],
            "y_category": result["y_category"],
            "x_unit": result["x_unit"],
            "y_unit": result["y_unit"],
            "count": result["count"],
            "mean_x": round(result["mean_x"], precision),
            "mean_y": round(result["mean_y"], precision),
            "covariance": round(result["covariance"], precision),
            "sample_covariance": round(result["sample_covariance"], precision),
        })

    def _handle_correlation(self):
        """POST /api/correlation — {x:[{value,unit},...], y:[...], to_x?, to_y?}
        -> the (dimensionless) Pearson correlation coefficient of two paired
        quantity series, plus their covariance, means and standard deviations.
        The normalised companion to /api/covariance. Additive: reuses
        ``domain.correlation`` and never touches the convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._paired_request(data)
        if parsed is None:
            return
        x, y, to_x, to_y, precision = parsed
        try:
            result = domain.correlation(x, y, to_x, to_y)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "x_category": result["x_category"],
            "y_category": result["y_category"],
            "x_unit": result["x_unit"],
            "y_unit": result["y_unit"],
            "count": result["count"],
            "mean_x": round(result["mean_x"], precision),
            "mean_y": round(result["mean_y"], precision),
            "stdev_x": round(result["stdev_x"], precision),
            "stdev_y": round(result["stdev_y"], precision),
            "covariance": round(result["covariance"], precision),
            "sample_covariance": round(result["sample_covariance"], precision),
            "correlation": self._round_opt(result["correlation"], precision),
        })

    def _handle_regression(self):
        """POST /api/regression — {x:[{value,unit},...], y:[...], to_x?, to_y?}
        -> the ordinary least-squares linear fit y = slope*x + intercept of two
        paired quantity series, with the slope (in y_unit per x_unit), intercept,
        Pearson r and r-squared. The predictive companion to /api/correlation.
        Additive: reuses ``domain.linear_regression`` and never touches the
        convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._paired_request(data)
        if parsed is None:
            return
        x, y, to_x, to_y, precision = parsed
        try:
            result = domain.linear_regression(x, y, to_x, to_y)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "x_category": result["x_category"],
            "y_category": result["y_category"],
            "x_unit": result["x_unit"],
            "y_unit": result["y_unit"],
            "count": result["count"],
            "slope": round(result["slope"], precision),
            "intercept": round(result["intercept"], precision),
            "r": self._round_opt(result["r"], precision),
            "r_squared": self._round_opt(result["r_squared"], precision),
            "mean_x": round(result["mean_x"], precision),
            "mean_y": round(result["mean_y"], precision),
        })

    def _handle_gini(self):
        """POST /api/gini — {items: [{value, unit}, ...], to?} -> the Gini
        inequality coefficient (in [0, 1]) of a list of same-category quantities,
        plus the relative and absolute mean-difference views of the same spread,
        all restated in 'to' (or the first item's unit). The inequality/
        concentration companion to /api/proportions (which reports each item's
        share of the total). Additive: reuses ``domain.gini_quantities`` and
        never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.gini_quantities(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "total": round(result["total"], precision),
            "mean": round(result["mean"], precision),
            "gini": round(result["gini"], precision),
            "rmad": round(result["rmad"], precision),
            "mean_abs_difference": round(result["mean_abs_difference"], precision),
        })


def make_server(port=0):
    ThreadingTCPServer.allow_reuse_address = True
    server = ThreadingTCPServer(("127.0.0.1", port), RequestHandler)
    return server


if __name__ == "__main__":
    srv = make_server(8000)
    host, port = srv.server_address
    print("Multi-category unit converter ready on http://127.0.0.1:%d/" % port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
        srv.server_close()
