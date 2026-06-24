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


# Minimal SVG favicon (a "⇄" conversion glyph) served at /favicon.ico so the
# browser's implicit request doesn't 404.
FAVICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    b'<rect width="32" height="32" rx="6" fill="#2563eb"/>'
    b'<text x="16" y="22" font-size="18" text-anchor="middle" '
    b'fill="#fff" font-family="sans-serif">\xe2\x87\x84</text></svg>'
)

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

    def _send_favicon(self):
        # A tiny inline SVG so the browser's automatic /favicon.ico request
        # resolves with 200 instead of a 404 console error.
        body = FAVICON_SVG
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Cache-Control", "max-age=86400")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        if self.path == "/favicon.ico" or self.path == "/favicon.svg":
            self._send_favicon()
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

    def _two_sample_request(self, data):
        """Validate the shared two-independent-sample ``{a:[...], b:[...], to?}``
        body. Returns (a, b, to_unit, precision) or None after emitting a 400.

        Distinct from :meth:`_paired_request`: the two samples are *independent*
        (they may have different lengths), not paired point-for-point, so they are
        named ``a`` / ``b`` rather than ``x`` / ``y`` and share one target unit."""
        a = data.get("a")
        b = data.get("b")
        if not isinstance(a, list) or not isinstance(b, list):
            self._send_json(400, {"error": "'a' and 'b' must be lists"})
            return None
        precision = self._precision_or_400(data)
        if precision is None:
            return None
        return a, b, data.get("to"), precision

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
        if self.path == "/api/cv":
            self._handle_cv()
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
        if self.path == "/api/ema":
            self._handle_ema()
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
        if self.path == "/api/theil-sen":
            self._handle_theil_sen()
            return
        if self.path == "/api/residuals":
            self._handle_residuals()
            return
        if self.path == "/api/spearman":
            self._handle_spearman()
            return
        if self.path == "/api/kendall":
            self._handle_kendall()
            return
        if self.path == "/api/gini":
            self._handle_gini()
            return
        if self.path == "/api/lorenz":
            self._handle_lorenz()
            return
        if self.path == "/api/entropy":
            self._handle_entropy()
            return
        if self.path == "/api/trimmed-mean":
            self._handle_trimmed_mean()
            return
        if self.path == "/api/winsorize":
            self._handle_winsorize()
            return
        if self.path == "/api/autocorrelation":
            self._handle_autocorrelation()
            return
        if self.path == "/api/robust-zscore":
            self._handle_robust_zscore()
            return
        if self.path == "/api/confidence-interval":
            self._handle_confidence_interval()
            return
        if self.path == "/api/jarque-bera":
            self._handle_jarque_bera()
            return
        if self.path == "/api/t-interval":
            self._handle_t_interval()
            return
        if self.path == "/api/t-test":
            self._handle_t_test()
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

    def _handle_cv(self):
        """POST /api/cv — {items: [{value, unit}, ...], to?} -> the relative
        (scale-free) dispersion statistics: the coefficient of variation
        (population and sample, as a ratio and a percentage), the variance-to-mean
        index of dispersion (Fano factor) and the signal-to-noise ratio, plus the
        mean, variance and standard deviations they are built from, all restated
        in 'to' (or the first item's unit). The relative-spread companion to
        /api/describe (absolute spread) and /api/mad (robust spread). Additive:
        reuses ``domain.cv_quantities`` and never touches the other convert
        paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.cv_quantities(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "mean": round(result["mean"], precision),
            "variance": round(result["variance"], precision),
            "stdev": round(result["stdev"], precision),
            "sample_stdev": self._round_opt(result["sample_stdev"], precision),
            "cv": self._round_opt(result["cv"], precision),
            "sample_cv": self._round_opt(result["sample_cv"], precision),
            "cv_percent": self._round_opt(result["cv_percent"], precision),
            "sample_cv_percent": self._round_opt(
                result["sample_cv_percent"], precision),
            "index_of_dispersion": self._round_opt(
                result["index_of_dispersion"], precision),
            "signal_to_noise": self._round_opt(
                result["signal_to_noise"], precision),
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

    def _handle_ema(self):
        """POST /api/ema — {items: [{value, unit}, ...], alpha?, span?, to?} ->
        the exponential moving average (exponential smoothing) over each item on a
        common unit. The smoothing factor is given as 'alpha' (in (0, 1]) OR as a
        'span' (>= 1, mapped to alpha = 2/(span+1)); supply at most one, defaulting
        to alpha 0.5. The exponentially-weighted, reactive companion to the simple
        /api/moving-average. Additive: reuses ``domain.ema`` and never touches the
        other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        # alpha and span are optional; the domain layer defaults/validates them
        # and rejects supplying both.
        try:
            result = domain.ema(items, data.get("alpha"), data.get("span"), to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "alpha": round(result["alpha"], precision),
            "span": self._round_opt(result["span"], precision),
            "items": [
                {"index": r["index"],
                 "value": round(r["value"], precision),
                 "ema": round(r["ema"], precision)}
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

    def _handle_residuals(self):
        """POST /api/residuals — {x:[{value,unit},...], y:[...], to_x?, to_y?}
        -> the ordinary least-squares fit evaluated at every paired point: the
        fitted value and residual (y - fitted) per point, the variance
        decomposition (sst, ssr, sse), r-squared and the residual standard error.
        The per-point diagnostic companion to /api/regression. Additive: reuses
        ``domain.residuals`` and never touches the convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._paired_request(data)
        if parsed is None:
            return
        x, y, to_x, to_y, precision = parsed
        try:
            result = domain.residuals(x, y, to_x, to_y)
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
            "sst": round(result["sst"], precision),
            "ssr": round(result["ssr"], precision),
            "sse": round(result["sse"], precision),
            "r_squared": self._round_opt(result["r_squared"], precision),
            "residual_std_error": self._round_opt(
                result["residual_std_error"], precision),
            "mean_x": round(result["mean_x"], precision),
            "mean_y": round(result["mean_y"], precision),
            "items": [
                {"index": r["index"],
                 "x": round(r["x"], precision),
                 "y": round(r["y"], precision),
                 "fitted": round(r["fitted"], precision),
                 "residual": round(r["residual"], precision)}
                for r in result["items"]
            ],
        })

    def _handle_theil_sen(self):
        """POST /api/theil-sen — {x:[{value,unit},...], y:[...], to_x?, to_y?}
        -> the Theil--Sen robust linear fit y = slope*x + intercept of two paired
        quantity series. The outlier-resistant companion to /api/regression
        (ordinary least squares): the slope is the median of every pairwise slope
        and the intercept the median of (y - slope*x), so up to ~29% of the data
        can be corrupted without swinging the line. Additive: reuses
        ``domain.theil_sen`` and never touches the convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._paired_request(data)
        if parsed is None:
            return
        x, y, to_x, to_y, precision = parsed
        try:
            result = domain.theil_sen(x, y, to_x, to_y)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "x_category": result["x_category"],
            "y_category": result["y_category"],
            "x_unit": result["x_unit"],
            "y_unit": result["y_unit"],
            "count": result["count"],
            "pairs": result["pairs"],
            "used_pairs": result["used_pairs"],
            "tied_pairs": result["tied_pairs"],
            "slope": round(result["slope"], precision),
            "intercept": round(result["intercept"], precision),
            "median_x": round(result["median_x"], precision),
            "median_y": round(result["median_y"], precision),
            "mean_x": round(result["mean_x"], precision),
            "mean_y": round(result["mean_y"], precision),
        })

    def _handle_spearman(self):
        """POST /api/spearman — {x:[{value,unit},...], y:[...], to_x?, to_y?}
        -> the (dimensionless) Spearman rank correlation coefficient of two
        paired quantity series. The rank-based, monotonic-association companion
        to /api/correlation (which reports the linear Pearson r): Spearman is
        robust to outliers and invariant under any monotonic rescaling of either
        series. Additive: reuses ``domain.spearman`` and never touches the
        convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._paired_request(data)
        if parsed is None:
            return
        x, y, to_x, to_y, precision = parsed
        try:
            result = domain.spearman(x, y, to_x, to_y)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "x_category": result["x_category"],
            "y_category": result["y_category"],
            "x_unit": result["x_unit"],
            "y_unit": result["y_unit"],
            "count": result["count"],
            "mean_rank_x": round(result["mean_rank_x"], precision),
            "mean_rank_y": round(result["mean_rank_y"], precision),
            "has_ties": result["has_ties"],
            "spearman": self._round_opt(result["spearman"], precision),
        })

    def _handle_kendall(self):
        """POST /api/kendall — {x:[{value,unit},...], y:[...], to_x?, to_y?}
        -> Kendall's tau-b rank correlation of two paired quantity series. The
        third member of the paired-series correlation family alongside
        /api/correlation (linear Pearson r) and /api/spearman (Pearson-on-ranks):
        Kendall's tau is built from the concordant/discordant agreement of every
        pair of observations, so like Spearman it is dimensionless, monotonic and
        outlier-robust, but interpreted as a probability of concordance. Additive:
        reuses ``domain.kendall`` and never touches the convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._paired_request(data)
        if parsed is None:
            return
        x, y, to_x, to_y, precision = parsed
        try:
            result = domain.kendall(x, y, to_x, to_y)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "x_category": result["x_category"],
            "y_category": result["y_category"],
            "x_unit": result["x_unit"],
            "y_unit": result["y_unit"],
            "count": result["count"],
            "pairs": result["pairs"],
            "concordant": result["concordant"],
            "discordant": result["discordant"],
            "ties_x": result["ties_x"],
            "ties_y": result["ties_y"],
            "has_ties": result["has_ties"],
            "tau_a": self._round_opt(result["tau_a"], precision),
            "tau": self._round_opt(result["tau"], precision),
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

    def _handle_lorenz(self):
        """POST /api/lorenz — {items: [{value, unit}, ...], to?} -> the Lorenz
        curve (cumulative population share vs cumulative value share, smallest
        first) of a list of same-category quantities, plus the geometric Gini
        recovered from it, all restated in 'to' (or the first item's unit). The
        per-point dataset companion to the scalar /api/gini (just as
        /api/winsorize is the per-item companion to /api/trimmed-mean). Additive:
        reuses ``domain.lorenz_quantities`` and never touches the other convert
        paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.lorenz_quantities(items, to_unit)
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
            "area_under_curve": round(result["area_under_curve"], precision),
            "points": [
                {"count": p["count"],
                 "population_fraction": round(p["population_fraction"], precision),
                 "cumulative_value": round(p["cumulative_value"], precision),
                 "value_fraction": round(p["value_fraction"], precision)}
                for p in result["points"]
            ],
        })

    def _handle_entropy(self):
        """POST /api/entropy — {items: [{value, unit}, ...], to?} -> the Shannon
        entropy (in nats and bits), the Pielou evenness (normalised entropy), the
        Simpson concentration and Gini-Simpson diversity indices, and the
        effective number of categories (Hill number) of a list of same-category
        quantities treated as a distribution, restated in 'to' (or the first
        item's unit). The information-theoretic diversity companion to /api/gini
        (inequality) and /api/proportions (per-item share). Additive: reuses
        ``domain.entropy_quantities`` and never touches the other convert
        paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.entropy_quantities(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "total": round(result["total"], precision),
            "mean": round(result["mean"], precision),
            "shannon": round(result["shannon"], precision),
            "shannon_bits": round(result["shannon_bits"], precision),
            "normalized_entropy": self._round_opt(
                result["normalized_entropy"], precision),
            "simpson": round(result["simpson"], precision),
            "gini_simpson": round(result["gini_simpson"], precision),
            "effective_count": round(result["effective_count"], precision),
        })

    def _handle_trimmed_mean(self):
        """POST /api/trimmed-mean — {items: [{value, unit}, ...], proportion?, to?}
        -> the robust trimmed and winsorized means of a list of same-category
        quantities, restated in 'to' (or the first item's unit). 'proportion' is
        the fraction trimmed from each tail (default 0.1, in [0, 0.5)). The
        outlier-resistant location companion to /api/means (the classical means)
        and /api/mad (robust spread). Additive: reuses ``domain.trimmed_mean`` and
        never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        # proportion is optional; the domain layer defaults and validates it.
        proportion = data.get("proportion", 0.1)
        try:
            result = domain.trimmed_mean(items, proportion, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "proportion": result["proportion"],
            "trimmed_each_side": result["trimmed_each_side"],
            "kept": result["kept"],
            "mean": round(result["mean"], precision),
            "trimmed_mean": round(result["trimmed_mean"], precision),
            "winsorized_mean": round(result["winsorized_mean"], precision),
            "lower": round(result["lower"], precision),
            "upper": round(result["upper"], precision),
        })

    def _handle_winsorize(self):
        """POST /api/winsorize — {items: [{value, unit}, ...], proportion?, to?}
        -> the winsorized SERIES of a list of same-category quantities, one entry
        per input in original order, each clamped to the trim bounds and flagged,
        all restated in 'to' (or the first item's unit). 'proportion' is the
        fraction clamped at each tail (default 0.1, in [0, 0.5)). The per-item
        transformation companion to /api/trimmed-mean (which reports only the
        scalar winsorized mean), alongside /api/zscore, /api/normalize and
        /api/outliers. Additive: reuses ``domain.winsorize_quantities`` and never
        touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        # proportion is optional; the domain layer defaults and validates it.
        proportion = data.get("proportion", 0.1)
        try:
            result = domain.winsorize_quantities(items, proportion, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "proportion": result["proportion"],
            "clamped_each_side": result["clamped_each_side"],
            "lower": round(result["lower"], precision),
            "upper": round(result["upper"], precision),
            "mean": round(result["mean"], precision),
            "winsorized_mean": round(result["winsorized_mean"], precision),
            "winsorized_stdev": round(result["winsorized_stdev"], precision),
            "items": [
                {"index": r["index"],
                 "value": round(r["value"], precision),
                 "winsorized": round(r["winsorized"], precision),
                 "clamped": r["clamped"]}
                for r in result["items"]
            ],
        })

    def _handle_autocorrelation(self):
        """POST /api/autocorrelation — {items: [{value, unit}, ...], maxlag?, to?}
        -> the serial (auto)correlation of a single series of same-category
        quantities at lags 0..maxlag, on a common unit. Where /api/correlation &
        friends relate two different series, this correlates one series with a
        delayed copy of itself (the standard trend/seasonality diagnostic) — the
        serial-dependence companion to /api/moving-average, /api/ema and /api/diff.
        'maxlag' is optional and defaults to count-1. The coefficients are
        dimensionless; r0 is always 1. Additive: reuses ``domain.autocorrelation``
        and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        items = data.get("items")
        if not isinstance(items, list):
            self._send_json(400, {"error": "'items' must be a list"})
            return
        to_unit = data.get("to")
        precision = self._precision_or_400(data)
        if precision is None:
            return
        # maxlag is optional; the domain layer defaults it to count-1 and
        # validates it.
        try:
            result = domain.autocorrelation(items, data.get("maxlag"), to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "maxlag": result["maxlag"],
            "mean": round(result["mean"], precision),
            "variance": round(result["variance"], precision),
            "stdev": round(result["stdev"], precision),
            "items": [
                {"lag": r["lag"],
                 "autocorrelation": round(r["autocorrelation"], precision)}
                for r in result["items"]
            ],
        })

    def _handle_robust_zscore(self):
        """POST /api/robust-zscore — {items: [{value, unit}, ...], threshold?, to?}
        -> each quantity's modified (robust) z-score, the Iglewicz-Hoaglin score
        standardised against the median and the median absolute deviation (MAD)
        instead of the mean and stdev. The outlier-robust companion to /api/zscore
        (mean/stdev), /api/mad (median/MAD) and /api/outliers (IQR fences). Each
        item is flagged is_outlier when |score| exceeds 'threshold' (default 3.5).
        The score is dimensionless; only median/mad carry the unit. 'threshold' is
        optional and validated by the domain layer. Additive: reuses
        ``domain.robust_zscores`` and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        # threshold is optional; the domain layer defaults it to 3.5 and validates.
        try:
            result = domain.robust_zscores(items, data.get("threshold"), to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "median": round(result["median"], precision),
            "mad": round(result["mad"], precision),
            "mean_abs_deviation": round(result["mean_abs_deviation"], precision),
            "method": result["method"],
            "threshold": result["threshold"],
            "outlier_count": result["outlier_count"],
            "items": [
                {"index": r["index"],
                 "value": round(r["value"], precision),
                 "robust_zscore": round(r["robust_zscore"], precision),
                 "is_outlier": r["is_outlier"]}
                for r in result["items"]
            ],
        })

    def _handle_confidence_interval(self):
        """POST /api/confidence-interval — {items: [{value, unit}, ...], confidence?,
        to?} -> a two-sided confidence interval for the population MEAN, using the
        large-sample normal (z) approximation: mean +/- z * (sample_stdev /
        sqrt(n)). The inferential companion to /api/describe (which reports the
        sample mean/spread as fixed descriptions); this reports the standard error
        of the mean, the two-sided critical z value, the margin of error and the
        lower/upper bounds. 'confidence' is optional (default 0.95, strictly in
        (0, 1)) and validated by the domain layer, which also requires at least two
        values. Additive: reuses ``domain.confidence_interval`` and never touches
        the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        # confidence is optional; the domain layer defaults it to 0.95 and validates.
        try:
            result = domain.confidence_interval(items, data.get("confidence"), to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "confidence": result["confidence"],
            "mean": round(result["mean"], precision),
            "sample_stdev": round(result["sample_stdev"], precision),
            "standard_error": round(result["standard_error"], precision),
            "critical_value": round(result["critical_value"], precision),
            "margin_of_error": round(result["margin_of_error"], precision),
            "lower": round(result["lower"], precision),
            "upper": round(result["upper"], precision),
        })

    def _handle_jarque_bera(self):
        """POST /api/jarque-bera — {items: [{value, unit}, ...], to?} -> the
        Jarque-Bera normality-test statistic (built from the sample skewness and
        excess kurtosis), its chi-square(2) p-value and a 5%-level verdict, all on
        a common unit. The inferential, normality-testing companion to /api/shape
        (just as /api/confidence-interval is to /api/describe). Additive: reuses
        ``domain.jarque_bera`` and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        try:
            result = domain.jarque_bera(items, to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "mean": round(result["mean"], precision),
            "stdev": round(result["stdev"], precision),
            "skewness": round(result["skewness"], precision),
            "kurtosis": round(result["kurtosis"], precision),
            "statistic": round(result["statistic"], precision),
            "df": result["df"],
            "p_value": round(result["p_value"], precision),
            "is_normal": result["is_normal"],
        })

    def _handle_t_interval(self):
        """POST /api/t-interval — {items: [{value, unit}, ...], confidence?, to?} ->
        a two-sided confidence interval for the population MEAN using the exact
        Student's t critical value with df = n - 1 degrees of freedom. The
        small-sample companion to /api/confidence-interval (which uses the
        large-sample normal z approximation): for small n the t interval is
        correctly wider, converging to the z interval as n grows. Reports the
        standard error of the mean, the two-sided critical t value, df, the margin
        of error and the lower/upper bounds. 'confidence' is optional (default
        0.95, strictly in (0, 1)) and validated by the domain layer, which also
        requires at least two values. Additive: reuses ``domain.t_interval`` and
        never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._items_request(data)
        if parsed is None:
            return
        items, to_unit, precision = parsed
        # confidence is optional; the domain layer defaults it to 0.95 and validates.
        try:
            result = domain.t_interval(items, data.get("confidence"), to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "count": result["count"],
            "df": result["df"],
            "confidence": result["confidence"],
            "mean": round(result["mean"], precision),
            "sample_stdev": round(result["sample_stdev"], precision),
            "standard_error": round(result["standard_error"], precision),
            "critical_value": round(result["critical_value"], precision),
            "margin_of_error": round(result["margin_of_error"], precision),
            "lower": round(result["lower"], precision),
            "upper": round(result["upper"], precision),
        })

    def _handle_t_test(self):
        """POST /api/t-test — {a:[{value,unit},...], b:[...], equal_var?, alpha?,
        to?} -> a two-sample t-test for the difference between two population
        MEANS. The two-group companion to /api/t-interval and /api/confidence-
        interval (which bound a single mean): the two samples are independent and
        may differ in length. Defaults to Welch's t-test (unequal variances);
        pass equal_var=true for Student's pooled t-test. Reports both sample
        means/variances, the difference, the standard error, the t-statistic,
        the (possibly fractional) degrees of freedom, the two-sided p-value and a
        verdict at the 'alpha' level (default 0.05). 'equal_var' and 'alpha' are
        optional and validated by the domain layer, which also requires at least
        two values per sample and a common category. Additive: reuses
        ``domain.two_sample_t_test`` and never touches the other convert paths."""
        data = self._json_body_obj()
        if data is None:
            return
        parsed = self._two_sample_request(data)
        if parsed is None:
            return
        a, b, to_unit, precision = parsed
        # equal_var and alpha are optional; the domain layer defaults and validates.
        try:
            result = domain.two_sample_t_test(
                a, b, data.get("equal_var"), data.get("alpha"), to_unit)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, {
            "category": result["category"],
            "unit": result["unit"],
            "n_a": result["n_a"],
            "n_b": result["n_b"],
            "mean_a": round(result["mean_a"], precision),
            "mean_b": round(result["mean_b"], precision),
            "var_a": round(result["var_a"], precision),
            "var_b": round(result["var_b"], precision),
            "stdev_a": round(result["stdev_a"], precision),
            "stdev_b": round(result["stdev_b"], precision),
            "difference": round(result["difference"], precision),
            "equal_var": result["equal_var"],
            "method": result["method"],
            "standard_error": round(result["standard_error"], precision),
            "statistic": round(result["statistic"], precision),
            "df": round(result["df"], precision),
            "alpha": result["alpha"],
            "p_value": round(result["p_value"], precision),
            "significant": result["significant"],
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
