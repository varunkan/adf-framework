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
        if self.path != "/api/convert":
            self._send_json(404, {"error": "not found"})
            return

        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, err)
            return

        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
            return

        value = data.get("value")
        direction = data.get("direction")
        from_unit = data.get("from")
        to_unit = data.get("to")

        # General multi-category path: {value, from, to}. Additive — only taken
        # when no legacy 'direction' is provided.
        if direction is None and (from_unit is not None or to_unit is not None):
            if value is None or from_unit is None or to_unit is None:
                self._send_json(400, {"error": "missing 'value', 'from' or 'to'"})
                return
            precision, perr = resolve_precision(data)
            if perr is not None:
                self._send_json(400, {"error": perr})
                return
            try:
                result, category = domain.convert_units(value, from_unit, to_unit)
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {
                "input": float(value),
                "from": domain.normalize_unit(from_unit),
                "to": domain.normalize_unit(to_unit),
                "category": category,
                "result": round(result, precision),
                "precision": precision,
            })
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
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, err)
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
            return
        value = data.get("value")
        from_unit = data.get("from")
        if value is None or from_unit is None:
            self._send_json(400, {"error": "missing 'value' or 'from'"})
            return
        precision, perr = resolve_precision(data)
        if perr is not None:
            self._send_json(400, {"error": perr})
            return
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
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, err)
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
            return
        expression = data.get("expression")
        if expression is None:
            self._send_json(400, {"error": "missing 'expression'"})
            return
        precision, perr = resolve_precision(data)
        if perr is not None:
            self._send_json(400, {"error": perr})
            return
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
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, err)
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
            return
        value = data.get("value")
        from_unit = data.get("from")
        if value is None or from_unit is None:
            self._send_json(400, {"error": "missing 'value' or 'from'"})
            return
        precision, perr = resolve_precision(data)
        if perr is not None:
            self._send_json(400, {"error": perr})
            return
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
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, err)
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
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
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, err)
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
            return
        value = data.get("value")
        from_unit = data.get("from")
        units = data.get("units")
        if value is None or from_unit is None or units is None:
            self._send_json(400, {"error": "missing 'value', 'from' or 'units'"})
            return
        precision, perr = resolve_precision(data)
        if perr is not None:
            self._send_json(400, {"error": perr})
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
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, err)
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
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
        precision, perr = resolve_precision(data)
        if perr is not None:
            self._send_json(400, {"error": perr})
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
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, err)
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
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
        precision, perr = resolve_precision(data)
        if perr is not None:
            self._send_json(400, {"error": perr})
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
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, err)
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
            return
        items = data.get("items")
        if not isinstance(items, list):
            self._send_json(400, {"error": "'items' must be a list"})
            return
        to_unit = data.get("to")
        precision, perr = resolve_precision(data)
        if perr is not None:
            self._send_json(400, {"error": perr})
            return
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
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, err)
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
            return
        expression = data.get("expression")
        if expression is None:
            self._send_json(400, {"error": "missing 'expression'"})
            return
        precision, perr = resolve_precision(data)
        if perr is not None:
            self._send_json(400, {"error": perr})
            return
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

    def _handle_convert_delta(self):
        """POST /api/convert-delta — {value, from, to} -> an INTERVAL conversion
        (e.g. a 10 C change is an 18 F change, not 50 F). Additive: reuses
        ``domain.convert_delta`` and never touches the absolute convert paths."""
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, err)
            return
        if not isinstance(data, dict):
            self._send_json(400, {"error": "body must be a JSON object"})
            return
        value = data.get("value")
        from_unit = data.get("from")
        to_unit = data.get("to")
        if value is None or from_unit is None or to_unit is None:
            self._send_json(400, {"error": "missing 'value', 'from' or 'to'"})
            return
        precision, perr = resolve_precision(data)
        if perr is not None:
            self._send_json(400, {"error": perr})
            return
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
