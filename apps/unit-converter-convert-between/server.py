import json
import math
import os
import threading
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingTCPServer

import domain

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(BASE_DIR, "index.html")


def c_to_f(celsius):
    return celsius * 9.0 / 5.0 + 32.0


def f_to_c(fahrenheit):
    return (fahrenheit - 32.0) * 5.0 / 9.0


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
        if self.path == "/favicon.ico":
            # Browsers auto-request /favicon.ico; answer it explicitly so the
            # console isn't polluted with a 404 network error on every page load.
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/api/units":
            self._send_json(200, {"categories": domain.list_units()})
            return
        self._send_json(404, {"error": "not found"})

    def _read_json_body(self):
        """Read and parse the request body as a JSON object.

        Returns ``(data, None)`` on success or ``(None, error_message)`` on
        failure so the caller can emit a 400.
        """
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except (TypeError, ValueError):
            # A non-numeric Content-Length (e.g. "abc" or "10.5") must not crash
            # the handler with an uncaught ValueError; fail safe with a 400.
            return None, "invalid Content-Length header"
        if length < 0:
            return None, "invalid Content-Length header"
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            return None, "invalid JSON body"
        if not isinstance(data, dict):
            return None, "body must be a JSON object"
        return data, None

    @staticmethod
    def _coerce_finite(value):
        """Coerce ``value`` to a finite float or raise ValueError."""
        numeric = float(value)
        if numeric != numeric or numeric in (float("inf"), float("-inf")):
            raise ValueError("not finite")
        return numeric

    @staticmethod
    def _check_finite(value):
        """Reject a conversion RESULT that overflowed to inf/nan.

        A finite *input* can still overflow to +/-inf while being scaled — e.g.
        ``1e308`` tebibytes in bytes (1e308 * 2**40). ``json.dumps`` would then
        emit the bare literal ``Infinity``/``NaN``, which is NOT valid JSON
        (RFC 8259): strict parsers such as JavaScript's ``JSON.parse`` throw, and
        the documented numeric ``result`` contract is silently violated. We fail
        safe by raising ``ValueError`` so the caller surfaces the same clean 400
        it already uses for domain errors.
        """
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("conversion result is out of range (overflowed to a non-finite value)")
        return value

    @classmethod
    def _round_result(cls, value):
        """Round a conversion result without collapsing small magnitudes.

        A flat ``round(x, 6)`` zeroes any value below 5e-7 — e.g. 1 eV in joules
        (1.6e-19) or 1 byte in tebibytes (~9e-13) — silently destroying a
        mathematically correct conversion. We instead keep 6 significant figures
        for sub-unit magnitudes while preserving the historical 6-decimal-place
        rounding for normal-magnitude values (so existing outputs are unchanged).

        A non-finite (overflowed) result is rejected up front via
        :meth:`_check_finite` rather than passed through to ``json.dumps``.
        """
        cls._check_finite(value)
        if value == 0:
            return value
        sig_digits = 6 - int(math.floor(math.log10(abs(value)))) - 1
        return round(value, max(6, sig_digits))

    def _parse_conversion(self, *names):
        """Read the JSON body and pull out a finite ``value`` plus ``names``.

        On any problem it emits the appropriate 400 and returns ``None``;
        otherwise it returns ``(numeric_value, [field, ...])`` in the order the
        names were given. Centralising this kills the body-parse / missing-field
        / finite-coercion boilerplate that was copy-pasted across every handler.
        """
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, {"error": err})
            return None

        value = data.get("value")
        fields = [data.get(name) for name in names]
        if value is None or any(field is None for field in fields):
            wanted = ", ".join("'%s'" % n for n in ("value",) + names)
            self._send_json(400, {"error": "missing one of %s" % wanted})
            return None

        try:
            numeric = self._coerce_finite(value)
        except (TypeError, ValueError):
            self._send_json(400, {"error": "'value' must be a finite number"})
            return None

        return numeric, fields

    def _send_unit_result(self, numeric, from_unit, to_unit, category, result):
        """Emit the shared 200 payload used by /api/units and /api/fuel.

        ``result`` must already be rounded and finite-checked by the caller (so
        an overflow surfaces as a 400 inside the caller's try, never as an
        ``Infinity`` token here).
        """
        self._send_json(200, {
            "input": numeric,
            "from": str(from_unit).lower(),
            "to": str(to_unit).lower(),
            "category": category,
            "result": result,
        })

    def do_POST(self):
        if self.path == "/api/convert":
            self._handle_temperature()
            return
        if self.path == "/api/temperature/all":
            self._handle_temperature_all()
            return
        if self.path == "/api/fuel":
            self._handle_fuel()
            return
        if self.path == "/api/units":
            self._handle_units()
            return
        if self.path == "/api/units/all":
            self._handle_units_all()
            return
        if self.path == "/api/units/batch":
            self._handle_units_batch()
            return
        if self.path == "/api/units/table":
            self._handle_units_table()
            return
        if self.path == "/api/smart":
            self._handle_smart()
            return
        if self.path == "/api/parse":
            self._handle_parse()
            return
        if self.path == "/api/base":
            self._handle_base()
            return
        if self.path == "/api/roman":
            self._handle_roman()
            return
        if self.path == "/api/words":
            self._handle_words()
            return
        if self.path == "/api/color":
            self._handle_color()
            return
        self._send_json(404, {"error": "not found"})

    def _handle_temperature(self):
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, {"error": err})
            return

        value = data.get("value")
        direction = data.get("direction")

        if value is None or direction is None:
            self._send_json(400, {"error": "missing 'value' or 'direction'"})
            return

        # Accept numbers or numeric strings.
        try:
            numeric = self._coerce_finite(value)
        except (TypeError, ValueError):
            self._send_json(400, {"error": "'value' must be a finite number"})
            return

        direction = str(direction).strip().lower()

        try:
            result, unit = domain.convert_direction(numeric, direction)
        except KeyError:
            self._send_json(
                400,
                {"error": "'direction' must be one of c2f, f2c, c2k, k2c, f2k, k2f"},
            )
            return

        # A finite input can still overflow while scaling (e.g. 1e308 C -> F);
        # never let a non-finite result reach json.dumps as a bare `Infinity`.
        try:
            self._check_finite(result)
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

    def _handle_temperature_all(self):
        """Convert one temperature into every scale (C/F/K) at once."""
        parsed = self._parse_conversion("from")
        if parsed is None:
            return
        numeric, (from_scale,) = parsed

        try:
            results = domain.convert_temperature_all(numeric, str(from_scale))
            for val in results.values():
                self._check_finite(val)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        rounded = {scale: round(val, 4) for scale, val in results.items()}
        self._send_json(200, {
            "input": numeric,
            "from": str(from_scale).upper(),
            "category": "temperature",
            "results": rounded,
        })

    def _handle_fuel(self):
        """Convert a fuel-economy value between consumption/efficiency units."""
        parsed = self._parse_conversion("from", "to")
        if parsed is None:
            return
        numeric, (from_unit, to_unit) = parsed

        try:
            result, category = domain.convert_fuel(
                numeric, str(from_unit), str(to_unit)
            )
            result = self._round_result(result)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._send_unit_result(numeric, from_unit, to_unit, category, result)

    def _handle_units(self):
        parsed = self._parse_conversion("from", "to")
        if parsed is None:
            return
        numeric, (from_unit, to_unit) = parsed

        try:
            result, category = domain.convert_units(
                numeric, str(from_unit), str(to_unit)
            )
            result = self._round_result(result)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._send_unit_result(numeric, from_unit, to_unit, category, result)


    def _handle_units_all(self):
        """Convert one value into every unit of its category at once."""
        parsed = self._parse_conversion("from")
        if parsed is None:
            return
        numeric, (from_unit,) = parsed

        try:
            results, category = domain.convert_all(numeric, str(from_unit))
            rounded = {unit: self._round_result(val) for unit, val in results.items()}
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._send_json(200, {
            "input": numeric,
            "from": str(from_unit).lower(),
            "category": category,
            "results": rounded,
        })


    def _handle_units_batch(self):
        """Convert a list of conversions in a single request.

        Body: ``{"conversions": [{"value", "from", "to"}, ...]}``. Each item is
        converted independently so a single bad item never fails the batch.
        """
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, {"error": err})
            return

        conversions = data.get("conversions")
        if not isinstance(conversions, list):
            self._send_json(400, {"error": "'conversions' must be a list"})
            return
        if not conversions:
            self._send_json(400, {"error": "'conversions' must not be empty"})
            return

        results = domain.convert_batch(conversions)
        rounded = []
        for item in results:
            if item.get("ok") and "result" in item:
                item = dict(item)
                item["result"] = self._round_result(item["result"])
            rounded.append(item)
        ok_count = sum(1 for item in rounded if item.get("ok"))
        self._send_json(200, {
            "count": len(rounded),
            "ok_count": ok_count,
            "results": rounded,
        })

    def _handle_smart(self):
        """Convert a single ``{value, from, to}`` across *any* family.

        Where ``/api/units`` only resolves the linear-factor categories and
        ``/api/convert`` only speaks temperature direction aliases, this routes a
        plain ``{value, from, to}`` request through :func:`domain.smart_convert`
        so one endpoint covers temperature (``c``/``f``/``k`` or the spelled-out
        names), fuel economy, and every linear category alike. Mixing families
        (e.g. a temperature scale with a length unit) returns 400, exactly like a
        cross-category mismatch.
        """
        parsed = self._parse_conversion("from", "to")
        if parsed is None:
            return
        numeric, (from_unit, to_unit) = parsed

        try:
            result, category = domain.smart_convert(
                numeric, str(from_unit), str(to_unit)
            )
            result = self._round_result(result)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._send_unit_result(numeric, from_unit, to_unit, category, result)

    def _handle_units_table(self):
        """Build a conversion table for a list of values in one request.

        Body: ``{"from": "km", "to": "mi", "values": [1, 5, 10]}``. The same
        unit pair is applied to every value via :func:`domain.conversion_table`,
        so it works for any family. It is all-or-nothing (unlike the batch
        endpoint): an unknown unit, a cross-family pair, or a bad value fails the
        whole table with a 400, because a printable chart with holes is worse
        than a clean error.
        """
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, {"error": err})
            return

        from_unit = data.get("from")
        to_unit = data.get("to")
        values = data.get("values")
        if from_unit is None or to_unit is None or values is None:
            self._send_json(400, {"error": "missing 'from', 'to', or 'values'"})
            return

        try:
            rows, category = domain.conversion_table(
                str(from_unit), str(to_unit), values
            )
            rows = [
                {"input": row["input"], "result": self._round_result(row["result"])}
                for row in rows
            ]
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._send_json(200, {
            "from": str(from_unit).lower(),
            "to": str(to_unit).lower(),
            "category": category,
            "count": len(rows),
            "rows": rows,
        })

    def _handle_parse(self):
        """Convert a free-text expression such as ``"100 km to mi"``.

        Body: ``{"expression": "<value> <from> to <to>"}``. The phrase routes to
        whichever family (temperature/fuel/linear) owns the units, so one box can
        drive every converter. An unparseable phrase or a cross-family mismatch
        returns 400.
        """
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, {"error": err})
            return

        expression = data.get("expression")
        if expression is None or not str(expression).strip():
            self._send_json(400, {"error": "missing 'expression'"})
            return

        try:
            parsed = domain.parse_and_convert(str(expression))
            parsed["result"] = self._round_result(parsed["result"])
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._send_json(200, parsed)

    def _handle_base(self):
        """Convert an integer between number bases (bin/oct/dec/hex).

        Body: ``{"value": "ff", "from": "hex", "to": "dec"}``. The value is a
        string of digits in the source radix (a ``0x``/``0o``/``0b`` prefix is
        tolerated); the result is the same integer rendered in the target radix.
        A non-string value is accepted too — it is stringified first. An unknown
        base or an invalid digit for the source radix returns 400.
        """
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, {"error": err})
            return

        value = data.get("value")
        from_base = data.get("from")
        to_base = data.get("to")
        if value is None or from_base is None or to_base is None:
            self._send_json(400, {"error": "missing 'value', 'from', or 'to'"})
            return

        try:
            result, category = domain.convert_base(value, from_base, to_base)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._send_json(200, {
            "input": str(value).strip(),
            "from": str(from_base).strip().lower(),
            "to": category,
            "category": "base",
            "result": result,
        })

    def _handle_roman(self):
        """Convert between an Arabic integer and a Roman numeral.

        Body: ``{"value": 2024, "from": "arabic", "to": "roman"}`` (or the
        reverse with ``{"value": "MMXXIV", "from": "roman", "to": "arabic"}``).
        Classical numerals cover 1..3999 only; an out-of-range integer, a
        malformed numeral, or an unknown notation returns 400.
        """
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, {"error": err})
            return

        value = data.get("value")
        from_kind = data.get("from")
        to_kind = data.get("to")
        if value is None or from_kind is None or to_kind is None:
            self._send_json(400, {"error": "missing 'value', 'from', or 'to'"})
            return

        try:
            result, category = domain.convert_roman(value, from_kind, to_kind)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._send_json(200, {
            "input": str(value).strip(),
            "from": str(from_kind).strip().lower(),
            "to": str(to_kind).strip().lower(),
            "category": category,
            "result": result,
        })

    def _handle_words(self):
        """Convert between an Arabic integer and its English number words.

        Body: ``{"value": 2024, "from": "arabic", "to": "words"}`` (or the
        reverse with ``{"value": "two thousand twenty-four", "from": "words",
        "to": "arabic"}``). The short scale covers roughly +/-10^15; an
        out-of-range integer, a malformed/non-canonical phrase, or an unknown
        notation returns 400.
        """
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, {"error": err})
            return

        value = data.get("value")
        from_kind = data.get("from")
        to_kind = data.get("to")
        if value is None or from_kind is None or to_kind is None:
            self._send_json(400, {"error": "missing 'value', 'from', or 'to'"})
            return

        try:
            result, category = domain.convert_words(value, from_kind, to_kind)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._send_json(200, {
            "input": str(value).strip(),
            "from": str(from_kind).strip().lower(),
            "to": str(to_kind).strip().lower(),
            "category": category,
            "result": result,
        })

    def _handle_color(self):
        """Convert a colour between hex / rgb / hsl notations.

        Body: ``{"value": "#ff0000", "from": "hex", "to": "rgb"}`` (or the
        reverse with ``{"value": "rgb(255,0,0)", "from": "rgb", "to": "hsl"}``).
        Every notation routes through a canonical RGB triple, so the same value
        is re-rendered in the target notation. An unknown notation or a
        malformed/out-of-range colour returns 400.
        """
        data, err = self._read_json_body()
        if err is not None:
            self._send_json(400, {"error": err})
            return

        value = data.get("value")
        from_notation = data.get("from")
        to_notation = data.get("to")
        if value is None or from_notation is None or to_notation is None:
            self._send_json(400, {"error": "missing 'value', 'from', or 'to'"})
            return

        try:
            result, category = domain.convert_color(value, from_notation, to_notation)
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        self._send_json(200, {
            "input": str(value).strip(),
            "from": str(from_notation).strip().lower(),
            "to": str(to_notation).strip().lower(),
            "category": category,
            "result": result,
        })


def make_server(port=0):
    ThreadingTCPServer.allow_reuse_address = True
    server = ThreadingTCPServer(("127.0.0.1", port), RequestHandler)
    return server


if __name__ == "__main__":
    srv = make_server(int(os.environ.get("ADF_SMOKE_PORT") or os.environ.get("PORT") or 8000))
    host, port = srv.server_address
    print("Unit converter ready on http://127.0.0.1:%d/" % port)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
        srv.server_close()
