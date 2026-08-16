import json
import threading
import unittest
import http.client

import domain
from server import make_server, RequestHandler


class TemperatureConverterTest(unittest.TestCase):
    def setUp(self):
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _post(self, path, payload):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        body = json.dumps(payload)
        conn.request("POST", path, body=body,
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        status = resp.status
        conn.close()
        return status, data

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", path)
        resp = conn.getresponse()
        data = resp.read()
        status = resp.status
        conn.close()
        return status, data

    def test_handler_class_exists(self):
        self.assertTrue(issubclass(RequestHandler, object))

    def test_index_served(self):
        status, data = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Temperature Converter", data)

    def test_celsius_to_fahrenheit(self):
        status, data = self._post("/api/convert", {"value": 100, "direction": "c2f"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 212.0)
        self.assertEqual(payload["unit"], "F")

    def test_fahrenheit_to_celsius(self):
        status, data = self._post("/api/convert", {"value": 32, "direction": "f2c"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 0.0)
        self.assertEqual(payload["unit"], "C")

    def test_negative_celsius(self):
        status, data = self._post("/api/convert", {"value": -40, "direction": "c2f"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], -40.0)

    def test_string_numeric_value_accepted(self):
        status, data = self._post("/api/convert", {"value": "37", "direction": "c2f"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 98.6)

    def test_invalid_value_returns_400(self):
        status, data = self._post("/api/convert", {"value": "abc", "direction": "c2f"})
        self.assertEqual(status, 400)

    def test_missing_fields_returns_400(self):
        status, data = self._post("/api/convert", {"value": 10})
        self.assertEqual(status, 400)

    def test_invalid_direction_returns_400(self):
        status, data = self._post("/api/convert", {"value": 10, "direction": "x2y"})
        self.assertEqual(status, 400)

    def test_unknown_path_returns_404(self):
        status, data = self._get("/nope")
        self.assertEqual(status, 404)

    def test_result_region_is_live_for_screen_readers(self):
        # The result updates dynamically; it must be an ARIA live region so
        # screen-reader users hear the conversion outcome.
        status, data = self._get("/")
        self.assertEqual(status, 200)
        html = data.decode("utf-8")
        self.assertIn('id="result"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('role="status"', html)

    # ------------------------------------------------------------------
    # New linear-factor categories: area, speed, time, data.
    # ------------------------------------------------------------------

    def test_area_km2_to_m2(self):
        status, data = self._post("/api/units", {"value": 1, "from": "km2", "to": "m2"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000000.0)
        self.assertEqual(payload["category"], "area")

    def test_area_hectare_to_acre(self):
        status, data = self._post("/api/units", {"value": 1, "from": "ha", "to": "acre"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 2.471054, places=5)

    def test_speed_mph_to_kph(self):
        status, data = self._post("/api/units", {"value": 60, "from": "mph", "to": "kph"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 96.56064, places=4)
        self.assertEqual(payload["category"], "speed")

    def test_speed_knot_to_mps(self):
        status, data = self._post("/api/units", {"value": 1, "from": "kn", "to": "mps"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 0.514444, places=5)

    def test_time_hours_to_minutes(self):
        status, data = self._post("/api/units", {"value": 2, "from": "h", "to": "min"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 120.0)
        self.assertEqual(payload["category"], "time")

    def test_time_week_to_days(self):
        status, data = self._post("/api/units", {"value": 1, "from": "wk", "to": "d"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 7.0)

    def test_data_gib_to_mib(self):
        status, data = self._post("/api/units", {"value": 1, "from": "gib", "to": "mib"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1024.0)
        self.assertEqual(payload["category"], "data")

    def test_data_kb_decimal_vs_kib_binary(self):
        # 1 kB (decimal) = 1000 bytes; 1 KiB (binary) = 1024 bytes.
        status, data = self._post("/api/units", {"value": 1, "from": "kib", "to": "kb"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1.024)

    def test_cross_category_mismatch_rejected(self):
        # A metre is length, a second is time — incompatible.
        status, data = self._post("/api/units", {"value": 1, "from": "m", "to": "s"})
        self.assertEqual(status, 400)
        payload = json.loads(data)
        self.assertIn("different categories", payload["error"])

    def test_units_listing_includes_new_categories(self):
        status, data = self._get("/api/units")
        self.assertEqual(status, 200)
        payload = json.loads(data)
        cats = payload["categories"]
        for name in ("area", "speed", "time", "data"):
            self.assertIn(name, cats)
        self.assertIn("acre", cats["area"])
        self.assertIn("kn", cats["speed"])
        self.assertIn("wk", cats["time"])
        self.assertIn("gib", cats["data"])

    # ------------------------------------------------------------------
    # New endpoint: POST /api/units/all — convert into every unit at once.
    # ------------------------------------------------------------------

    def test_convert_all_returns_full_category(self):
        status, data = self._post("/api/units/all", {"value": 1000, "from": "m"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "length")
        results = payload["results"]
        self.assertEqual(results["km"], 1.0)
        self.assertEqual(results["m"], 1000.0)
        self.assertEqual(results["cm"], 100000.0)
        # Every unit in the category is present.
        self.assertEqual(set(results.keys()), set(domain.LENGTH_UNITS.keys()))

    def test_convert_all_unknown_unit_returns_400(self):
        status, data = self._post("/api/units/all", {"value": 5, "from": "bogus"})
        self.assertEqual(status, 400)

    def test_convert_all_missing_fields_returns_400(self):
        status, data = self._post("/api/units/all", {"value": 5})
        self.assertEqual(status, 400)

    def test_convert_all_invalid_value_returns_400(self):
        status, data = self._post("/api/units/all", {"value": "abc", "from": "m"})
        self.assertEqual(status, 400)

    # ------------------------------------------------------------------
    # Previously-implemented but untested categories: pressure, energy,
    # angle. These exercise the generic /api/units route end-to-end.
    # ------------------------------------------------------------------

    def test_pressure_atm_to_pa(self):
        status, data = self._post("/api/units", {"value": 1, "from": "atm", "to": "pa"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 101325.0)
        self.assertEqual(payload["category"], "pressure")

    def test_pressure_bar_to_psi(self):
        status, data = self._post("/api/units", {"value": 1, "from": "bar", "to": "psi"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 14.503774, places=5)

    def test_energy_kwh_to_joule(self):
        status, data = self._post("/api/units", {"value": 1, "from": "kwh", "to": "j"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 3600000.0)
        self.assertEqual(payload["category"], "energy")

    def test_energy_kcal_to_kj(self):
        status, data = self._post("/api/units", {"value": 1, "from": "kcal", "to": "kj"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 4.184, places=6)

    def test_angle_degrees_to_radians(self):
        status, data = self._post("/api/units", {"value": 180, "from": "deg", "to": "rad"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 3.141593, places=5)
        self.assertEqual(payload["category"], "angle")

    def test_angle_turn_to_degrees(self):
        status, data = self._post("/api/units", {"value": 1, "from": "turn", "to": "deg"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 360.0, places=6)

    # ------------------------------------------------------------------
    # New physics categories: power, force, frequency.
    # ------------------------------------------------------------------

    def test_power_kw_to_w(self):
        status, data = self._post("/api/units", {"value": 1, "from": "kw", "to": "w"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000.0)
        self.assertEqual(payload["category"], "power")

    def test_power_hp_to_w(self):
        status, data = self._post("/api/units", {"value": 1, "from": "hp", "to": "w"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 745.699872, places=5)

    def test_force_kgf_to_n(self):
        status, data = self._post("/api/units", {"value": 1, "from": "kgf", "to": "n"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 9.80665)
        self.assertEqual(payload["category"], "force")

    def test_force_lbf_to_n(self):
        status, data = self._post("/api/units", {"value": 1, "from": "lbf", "to": "n"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 4.448222, places=5)

    def test_frequency_khz_to_hz(self):
        status, data = self._post("/api/units", {"value": 1, "from": "khz", "to": "hz"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000.0)
        self.assertEqual(payload["category"], "frequency")

    def test_frequency_rpm_to_hz(self):
        status, data = self._post("/api/units", {"value": 60, "from": "rpm", "to": "hz"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 1.0, places=9)

    def test_units_listing_includes_physics_categories(self):
        status, data = self._get("/api/units")
        self.assertEqual(status, 200)
        cats = json.loads(data)["categories"]
        for name in ("pressure", "energy", "angle", "power", "force", "frequency"):
            self.assertIn(name, cats)
        self.assertIn("hp", cats["power"])
        self.assertIn("kgf", cats["force"])
        self.assertIn("rpm", cats["frequency"])

    # ------------------------------------------------------------------
    # Previously-untested endpoint: POST /api/units/batch.
    # ------------------------------------------------------------------

    def test_batch_converts_independent_items(self):
        status, data = self._post("/api/units/batch", {"conversions": [
            {"value": 1, "from": "km", "to": "m"},
            {"value": 1, "from": "kw", "to": "w"},
            {"value": 1, "from": "m", "to": "s"},  # cross-category: should fail
        ]})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["ok_count"], 2)
        results = payload["results"]
        self.assertEqual(results[0]["result"], 1000.0)
        self.assertEqual(results[1]["result"], 1000.0)
        self.assertFalse(results[2]["ok"])
        self.assertIn("different categories", results[2]["error"])

    def test_batch_empty_list_returns_400(self):
        status, data = self._post("/api/units/batch", {"conversions": []})
        self.assertEqual(status, 400)

    def test_batch_non_list_returns_400(self):
        status, data = self._post("/api/units/batch", {"conversions": "nope"})
        self.assertEqual(status, 400)

    # ------------------------------------------------------------------
    # Previously-routed-but-unhandled endpoint: POST /api/temperature/all.
    # do_POST routed to it, but the handler did not exist — exercise it now.
    # ------------------------------------------------------------------

    def test_temperature_all_from_celsius(self):
        status, data = self._post("/api/temperature/all", {"value": 100, "from": "C"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "temperature")
        self.assertEqual(payload["from"], "C")
        results = payload["results"]
        self.assertEqual(results["C"], 100.0)
        self.assertEqual(results["F"], 212.0)
        self.assertEqual(results["K"], 373.15)

    def test_temperature_all_from_kelvin(self):
        status, data = self._post("/api/temperature/all", {"value": 0, "from": "k"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["results"]["C"], -273.15)
        self.assertEqual(payload["results"]["K"], 0.0)

    def test_temperature_all_unknown_scale_returns_400(self):
        status, data = self._post("/api/temperature/all", {"value": 1, "from": "X"})
        self.assertEqual(status, 400)

    def test_temperature_all_missing_fields_returns_400(self):
        status, data = self._post("/api/temperature/all", {"value": 1})
        self.assertEqual(status, 400)

    def test_temperature_all_invalid_value_returns_400(self):
        status, data = self._post("/api/temperature/all", {"value": "abc", "from": "C"})
        self.assertEqual(status, 400)

    # ------------------------------------------------------------------
    # Previously-routed-but-unhandled endpoint: POST /api/fuel.
    # ------------------------------------------------------------------

    def test_fuel_mpg_to_l100km(self):
        # ~30 US mpg is roughly 7.84 L/100km.
        status, data = self._post("/api/fuel", {"value": 30, "from": "mpg", "to": "l100km"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "fuel")
        self.assertAlmostEqual(payload["result"], 7.840486, places=4)

    def test_fuel_l100km_to_kmpl_reciprocal(self):
        # 5 L/100km == 20 km/L (a true reciprocal, not a linear factor).
        status, data = self._post("/api/fuel", {"value": 5, "from": "l100km", "to": "kmpl"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 20.0, places=9)

    def test_fuel_zero_l100km_returns_400(self):
        status, data = self._post("/api/fuel", {"value": 0, "from": "l100km", "to": "mpg"})
        self.assertEqual(status, 400)

    def test_fuel_unknown_unit_returns_400(self):
        status, data = self._post("/api/fuel", {"value": 1, "from": "mpg", "to": "kph"})
        self.assertEqual(status, 400)

    def test_fuel_missing_fields_returns_400(self):
        status, data = self._post("/api/fuel", {"value": 1, "from": "mpg"})
        self.assertEqual(status, 400)

    # ------------------------------------------------------------------
    # Previously-untested category: illuminance (already in domain).
    # ------------------------------------------------------------------

    def test_illuminance_fc_to_lux(self):
        status, data = self._post("/api/units", {"value": 1, "from": "fc", "to": "lux"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 10.76391, places=4)
        self.assertEqual(payload["category"], "illuminance")

    def test_illuminance_phot_to_lux(self):
        status, data = self._post("/api/units", {"value": 1, "from": "ph", "to": "lux"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 10000.0)

    def test_units_listing_includes_temperature_fuel_illuminance(self):
        status, data = self._get("/api/units")
        self.assertEqual(status, 200)
        cats = json.loads(data)["categories"]
        for name in ("temperature", "fuel", "illuminance"):
            self.assertIn(name, cats)
        self.assertIn("lux", cats["illuminance"])
        self.assertIn("l100km", cats["fuel"])

    # ------------------------------------------------------------------
    # New linear categories: bandwidth (bit/s) and torque (newton-metre).
    # ------------------------------------------------------------------

    def test_bandwidth_mbps_to_kbps(self):
        status, data = self._post("/api/units", {"value": 1, "from": "mbps", "to": "kbps"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000.0)
        self.assertEqual(payload["category"], "bandwidth")

    def test_bandwidth_gbps_to_mbps(self):
        status, data = self._post("/api/units", {"value": 1, "from": "gbps", "to": "mbps"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000.0)

    def test_torque_lbft_to_nm(self):
        status, data = self._post("/api/units", {"value": 1, "from": "lbft", "to": "nm"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 1.355818, places=5)
        self.assertEqual(payload["category"], "torque")

    def test_torque_kgfm_to_nm(self):
        status, data = self._post("/api/units", {"value": 1, "from": "kgfm", "to": "nm"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 9.80665)

    def test_convert_all_bandwidth(self):
        status, data = self._post("/api/units/all", {"value": 1, "from": "mbps"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "bandwidth")
        results = payload["results"]
        self.assertEqual(results["bps"], 1000000.0)
        self.assertEqual(results["kbps"], 1000.0)
        self.assertEqual(results["mbps"], 1.0)

    def test_units_listing_includes_bandwidth_torque(self):
        status, data = self._get("/api/units")
        self.assertEqual(status, 200)
        cats = json.loads(data)["categories"]
        for name in ("bandwidth", "torque"):
            self.assertIn(name, cats)
        self.assertIn("mbps", cats["bandwidth"])
        self.assertIn("lbft", cats["torque"])

    # ------------------------------------------------------------------
    # New endpoint: POST /api/parse — natural-language one-shot conversion
    # that routes across every family (linear / temperature / fuel).
    # ------------------------------------------------------------------

    def test_parse_length_expression(self):
        status, data = self._post("/api/parse", {"expression": "100 km to mi"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "length")
        self.assertEqual(payload["from"], "km")
        self.assertEqual(payload["to"], "mi")
        self.assertAlmostEqual(payload["result"], 62.137119, places=5)

    def test_parse_temperature_expression(self):
        status, data = self._post("/api/parse", {"expression": "212 f to c"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "temperature")
        self.assertEqual(payload["result"], 100.0)

    def test_parse_temperature_full_words(self):
        status, data = self._post("/api/parse", {"expression": "100 celsius to fahrenheit"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "temperature")
        self.assertEqual(payload["result"], 212.0)

    def test_parse_fuel_expression(self):
        status, data = self._post("/api/parse", {"expression": "30 mpg to l100km"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "fuel")
        self.assertAlmostEqual(payload["result"], 7.840486, places=4)

    def test_parse_no_space_between_value_and_unit(self):
        status, data = self._post("/api/parse", {"expression": "1000m to km"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1.0)
        self.assertEqual(payload["from"], "m")

    def test_parse_in_connector(self):
        status, data = self._post("/api/parse", {"expression": "2 h in min"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 120.0)
        self.assertEqual(payload["category"], "time")

    def test_parse_arrow_connector(self):
        status, data = self._post("/api/parse", {"expression": "1 kw -> w"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000.0)
        self.assertEqual(payload["category"], "power")

    def test_parse_cross_family_returns_400(self):
        status, data = self._post("/api/parse", {"expression": "100 c to km"})
        self.assertEqual(status, 400)
        payload = json.loads(data)
        self.assertIn("temperature", payload["error"])

    def test_parse_cross_category_returns_400(self):
        status, data = self._post("/api/parse", {"expression": "1 m to s"})
        self.assertEqual(status, 400)
        payload = json.loads(data)
        self.assertIn("different categories", payload["error"])

    def test_parse_unparseable_returns_400(self):
        status, data = self._post("/api/parse", {"expression": "hello world"})
        self.assertEqual(status, 400)

    def test_parse_missing_expression_returns_400(self):
        status, data = self._post("/api/parse", {})
        self.assertEqual(status, 400)

    def test_parse_blank_expression_returns_400(self):
        status, data = self._post("/api/parse", {"expression": "   "})
        self.assertEqual(status, 400)

    # ------------------------------------------------------------------
    # Previously-untested categories: acceleration, density, flowrate.
    # All three are registered in domain + exposed in the UI but had no
    # end-to-end coverage through /api/units.
    # ------------------------------------------------------------------

    def test_acceleration_g0_to_mps2(self):
        status, data = self._post("/api/units", {"value": 1, "from": "g0", "to": "mps2"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 9.80665)
        self.assertEqual(payload["category"], "acceleration")

    def test_acceleration_ftps2_to_mps2(self):
        status, data = self._post("/api/units", {"value": 1, "from": "ftps2", "to": "mps2"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 0.3048, places=6)

    def test_density_gcm3_to_kgm3(self):
        status, data = self._post("/api/units", {"value": 1, "from": "gcm3", "to": "kgm3"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000.0)
        self.assertEqual(payload["category"], "density")

    def test_density_lbft3_to_kgm3(self):
        status, data = self._post("/api/units", {"value": 1, "from": "lbft3", "to": "kgm3"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 16.018463, places=5)

    def test_flowrate_m3h_to_m3s(self):
        status, data = self._post("/api/units", {"value": 3600, "from": "m3h", "to": "m3s"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 1.0, places=9)
        self.assertEqual(payload["category"], "flowrate")

    def test_flowrate_ls_to_lmin(self):
        status, data = self._post("/api/units", {"value": 1, "from": "ls", "to": "lmin"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 60.0, places=6)

    def test_units_listing_includes_acceleration_density_flowrate(self):
        status, data = self._get("/api/units")
        self.assertEqual(status, 200)
        cats = json.loads(data)["categories"]
        for name in ("acceleration", "density", "flowrate"):
            self.assertIn(name, cats)
        self.assertIn("g0", cats["acceleration"])
        self.assertIn("gcm3", cats["density"])
        self.assertIn("gpm", cats["flowrate"])

    # ------------------------------------------------------------------
    # Previously-untested endpoint: POST /api/base (number-base notation).
    # ------------------------------------------------------------------

    def test_base_hex_to_dec(self):
        status, data = self._post("/api/base", {"value": "ff", "from": "hex", "to": "dec"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], "255")
        self.assertEqual(payload["category"], "base")
        self.assertEqual(payload["to"], "dec")

    def test_base_dec_to_bin(self):
        status, data = self._post("/api/base", {"value": "10", "from": "dec", "to": "bin"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], "1010")

    def test_base_prefixed_value_accepted(self):
        status, data = self._post("/api/base", {"value": "0b1010", "from": "bin", "to": "hex"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], "a")

    def test_base_invalid_digit_returns_400(self):
        status, data = self._post("/api/base", {"value": "9", "from": "bin", "to": "dec"})
        self.assertEqual(status, 400)

    def test_base_unknown_base_returns_400(self):
        status, data = self._post("/api/base", {"value": "1", "from": "dec", "to": "base64"})
        self.assertEqual(status, 400)

    def test_base_missing_fields_returns_400(self):
        status, data = self._post("/api/base", {"value": "1", "from": "dec"})
        self.assertEqual(status, 400)

    # ------------------------------------------------------------------
    # New endpoint: POST /api/roman — Arabic <-> Roman numeral notation.
    # ------------------------------------------------------------------

    def test_roman_arabic_to_roman(self):
        status, data = self._post("/api/roman", {"value": 2024, "from": "arabic", "to": "roman"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], "MMXXIV")
        self.assertEqual(payload["category"], "roman")

    def test_roman_roman_to_arabic(self):
        status, data = self._post("/api/roman", {"value": "MCMLXXXIV", "from": "roman", "to": "arabic"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], "1984")

    def test_roman_lowercase_numeral_accepted(self):
        status, data = self._post("/api/roman", {"value": "xlii", "from": "roman", "to": "arabic"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], "42")

    def test_roman_out_of_range_returns_400(self):
        status, data = self._post("/api/roman", {"value": 4000, "from": "arabic", "to": "roman"})
        self.assertEqual(status, 400)

    def test_roman_zero_returns_400(self):
        status, data = self._post("/api/roman", {"value": 0, "from": "arabic", "to": "roman"})
        self.assertEqual(status, 400)

    def test_roman_malformed_numeral_returns_400(self):
        # "IIII" is not canonical (the canonical form of 4 is "IV").
        status, data = self._post("/api/roman", {"value": "IIII", "from": "roman", "to": "arabic"})
        self.assertEqual(status, 400)

    def test_roman_unknown_notation_returns_400(self):
        status, data = self._post("/api/roman", {"value": 5, "from": "arabic", "to": "greek"})
        self.assertEqual(status, 400)

    def test_roman_missing_fields_returns_400(self):
        status, data = self._post("/api/roman", {"value": 5, "from": "arabic"})
        self.assertEqual(status, 400)

    def test_units_listing_includes_base_and_roman(self):
        status, data = self._get("/api/units")
        self.assertEqual(status, 200)
        cats = json.loads(data)["categories"]
        self.assertIn("base", cats)
        self.assertIn("roman", cats)
        self.assertIn("hex", cats["base"])
        self.assertIn("roman", cats["roman"])

    # ------------------------------------------------------------------
    # New volume cooking measures + new categories: charge, pace.
    # ------------------------------------------------------------------

    def test_volume_tbsp_to_ml(self):
        status, data = self._post("/api/units", {"value": 1, "from": "tbsp", "to": "ml"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 14.786765, places=4)
        self.assertEqual(payload["category"], "volume")

    def test_volume_tbsp_is_three_tsp(self):
        status, data = self._post("/api/units", {"value": 1, "from": "tbsp", "to": "tsp"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 3.0, places=9)

    def test_charge_ah_to_coulomb(self):
        status, data = self._post("/api/units", {"value": 1, "from": "ah", "to": "coul"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 3600.0)
        self.assertEqual(payload["category"], "charge")

    def test_charge_ah_to_mah(self):
        status, data = self._post("/api/units", {"value": 1, "from": "ah", "to": "mah"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000.0)

    def test_pace_minkm_to_minmi(self):
        # 5 min/km is ~8.047 min/mile (a mile is longer, so it takes longer).
        status, data = self._post("/api/units", {"value": 5, "from": "minkm", "to": "minmi"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 8.04672, places=4)
        self.assertEqual(payload["category"], "pace")

    def test_pace_seckm_to_minkm(self):
        status, data = self._post("/api/units", {"value": 300, "from": "seckm", "to": "minkm"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertAlmostEqual(payload["result"], 5.0, places=9)

    def test_units_listing_includes_charge_pace_and_cooking(self):
        status, data = self._get("/api/units")
        self.assertEqual(status, 200)
        cats = json.loads(data)["categories"]
        for name in ("charge", "pace"):
            self.assertIn(name, cats)
        self.assertIn("ah", cats["charge"])
        self.assertIn("minkm", cats["pace"])
        # The cooking measures are exposed inside the volume category.
        self.assertIn("tbsp", cats["volume"])
        self.assertIn("tsp", cats["volume"])

    # ------------------------------------------------------------------
    # New endpoint: POST /api/smart — one {value, from, to} across families.
    # ------------------------------------------------------------------

    def test_smart_temperature_c_to_f(self):
        status, data = self._post("/api/smart", {"value": 100, "from": "c", "to": "f"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 212.0)
        self.assertEqual(payload["category"], "temperature")

    def test_smart_temperature_full_words(self):
        status, data = self._post("/api/smart", {"value": 0, "from": "celsius", "to": "kelvin"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 273.15)

    def test_smart_fuel_mpg_to_l100km(self):
        status, data = self._post("/api/smart", {"value": 30, "from": "mpg", "to": "l100km"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "fuel")
        self.assertAlmostEqual(payload["result"], 7.840486, places=4)

    def test_smart_linear_km_to_mi(self):
        status, data = self._post("/api/smart", {"value": 100, "from": "km", "to": "mi"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "length")
        self.assertAlmostEqual(payload["result"], 62.137119, places=5)

    def test_smart_new_charge_category(self):
        status, data = self._post("/api/smart", {"value": 2, "from": "ah", "to": "mah"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "charge")
        self.assertEqual(payload["result"], 2000.0)

    def test_smart_cross_family_returns_400(self):
        status, data = self._post("/api/smart", {"value": 1, "from": "c", "to": "km"})
        self.assertEqual(status, 400)
        payload = json.loads(data)
        self.assertIn("temperature", payload["error"])

    def test_smart_cross_category_returns_400(self):
        status, data = self._post("/api/smart", {"value": 1, "from": "m", "to": "s"})
        self.assertEqual(status, 400)
        payload = json.loads(data)
        self.assertIn("different categories", payload["error"])

    def test_smart_unknown_unit_returns_400(self):
        status, data = self._post("/api/smart", {"value": 1, "from": "bogus", "to": "m"})
        self.assertEqual(status, 400)

    def test_smart_missing_fields_returns_400(self):
        status, data = self._post("/api/smart", {"value": 1, "from": "c"})
        self.assertEqual(status, 400)

    def test_smart_invalid_value_returns_400(self):
        status, data = self._post("/api/smart", {"value": "abc", "from": "c", "to": "f"})
        self.assertEqual(status, 400)

    # ------------------------------------------------------------------
    # New endpoint: POST /api/units/table — many values, one unit pair.
    # ------------------------------------------------------------------

    def test_table_basic_length(self):
        status, data = self._post("/api/units/table",
                                  {"from": "km", "to": "m", "values": [1, 5, 10]})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "length")
        self.assertEqual(payload["count"], 3)
        rows = payload["rows"]
        self.assertEqual(rows[0], {"input": 1.0, "result": 1000.0})
        self.assertEqual(rows[1], {"input": 5.0, "result": 5000.0})
        self.assertEqual(rows[2], {"input": 10.0, "result": 10000.0})

    def test_table_works_across_families_temperature(self):
        status, data = self._post("/api/units/table",
                                  {"from": "c", "to": "f", "values": [0, 100]})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "temperature")
        self.assertEqual(payload["rows"][0]["result"], 32.0)
        self.assertEqual(payload["rows"][1]["result"], 212.0)

    def test_table_cross_category_returns_400(self):
        status, data = self._post("/api/units/table",
                                  {"from": "m", "to": "s", "values": [1, 2]})
        self.assertEqual(status, 400)
        payload = json.loads(data)
        self.assertIn("different categories", payload["error"])

    def test_table_unknown_unit_returns_400(self):
        status, data = self._post("/api/units/table",
                                  {"from": "bogus", "to": "m", "values": [1]})
        self.assertEqual(status, 400)

    def test_table_bad_value_returns_400(self):
        status, data = self._post("/api/units/table",
                                  {"from": "km", "to": "m", "values": [1, "abc"]})
        self.assertEqual(status, 400)

    def test_table_empty_values_returns_400(self):
        status, data = self._post("/api/units/table",
                                  {"from": "km", "to": "m", "values": []})
        self.assertEqual(status, 400)

    def test_table_non_list_values_returns_400(self):
        status, data = self._post("/api/units/table",
                                  {"from": "km", "to": "m", "values": "nope"})
        self.assertEqual(status, 400)

    def test_table_missing_fields_returns_400(self):
        status, data = self._post("/api/units/table", {"from": "km", "to": "m"})
        self.assertEqual(status, 400)

    # ------------------------------------------------------------------
    # New endpoint: POST /api/color — hex / rgb / hsl notation conversion.
    # ------------------------------------------------------------------

    def test_color_hex_to_rgb(self):
        status, data = self._post("/api/color", {"value": "#ff0000", "from": "hex", "to": "rgb"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], "rgb(255, 0, 0)")
        self.assertEqual(payload["category"], "color")

    def test_color_rgb_to_hex(self):
        status, data = self._post("/api/color", {"value": "rgb(0, 128, 255)", "from": "rgb", "to": "hex"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], "#0080ff")

    def test_color_hex_shorthand_expands(self):
        status, data = self._post("/api/color", {"value": "#f00", "from": "hex", "to": "rgb"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], "rgb(255, 0, 0)")

    def test_color_hex_to_hsl(self):
        status, data = self._post("/api/color", {"value": "#ff0000", "from": "hex", "to": "hsl"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], "hsl(0, 100%, 50%)")

    def test_color_hsl_to_hex(self):
        status, data = self._post("/api/color", {"value": "hsl(120, 100%, 50%)", "from": "hsl", "to": "hex"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], "#00ff00")

    def test_color_rgb_bare_triple_accepted(self):
        status, data = self._post("/api/color", {"value": "255,255,255", "from": "rgb", "to": "hsl"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], "hsl(0, 0%, 100%)")

    def test_color_rgb_out_of_range_returns_400(self):
        status, data = self._post("/api/color", {"value": "rgb(256, 0, 0)", "from": "rgb", "to": "hex"})
        self.assertEqual(status, 400)

    def test_color_bad_hex_returns_400(self):
        status, data = self._post("/api/color", {"value": "#gggggg", "from": "hex", "to": "rgb"})
        self.assertEqual(status, 400)

    def test_color_unknown_notation_returns_400(self):
        status, data = self._post("/api/color", {"value": "#ff0000", "from": "hex", "to": "cmyk"})
        self.assertEqual(status, 400)

    def test_color_missing_fields_returns_400(self):
        status, data = self._post("/api/color", {"value": "#ff0000", "from": "hex"})
        self.assertEqual(status, 400)

    def test_units_listing_includes_color(self):
        status, data = self._get("/api/units")
        self.assertEqual(status, 200)
        cats = json.loads(data)["categories"]
        self.assertIn("color", cats)
        self.assertEqual(cats["color"], ["hex", "hsl", "rgb"])

    # ------------------------------------------------------------------
    # Previously-built-but-unexposed electrical & electromagnetic families.
    # These categories live in domain (and so already route through
    # /api/units) but had no UI exposure and no end-to-end coverage. Drive
    # each one through the live /api/units endpoint so the trade-standard
    # metric-prefix ladders are proven, not just present.
    # ------------------------------------------------------------------

    def test_voltage_kv_to_v(self):
        status, data = self._post("/api/units", {"value": 1, "from": "kv", "to": "v"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000.0)
        self.assertEqual(payload["category"], "voltage")

    def test_voltage_v_to_mv(self):
        status, data = self._post("/api/units", {"value": 1, "from": "v", "to": "mv"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000.0)

    def test_current_a_to_ma(self):
        status, data = self._post("/api/units", {"value": 1, "from": "a", "to": "ma"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000.0)
        self.assertEqual(payload["category"], "current")

    def test_resistance_kohm_to_ohm(self):
        status, data = self._post("/api/units", {"value": 1, "from": "kohm", "to": "ohm"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000.0)
        self.assertEqual(payload["category"], "resistance")

    def test_resistance_megohm_to_kohm(self):
        status, data = self._post("/api/units", {"value": 1, "from": "megohm", "to": "kohm"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000.0)

    def test_capacitance_ufarad_to_pfarad(self):
        # 1 microfarad == 1,000,000 picofarads.
        status, data = self._post("/api/units", {"value": 1, "from": "ufarad", "to": "pfarad"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000000.0)
        self.assertEqual(payload["category"], "capacitance")

    def test_inductance_mhenry_to_uhenry(self):
        status, data = self._post("/api/units", {"value": 1, "from": "mhenry", "to": "uhenry"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 1000.0)
        self.assertEqual(payload["category"], "inductance")

    def test_magflux_weber_to_maxwell(self):
        # 1 weber == 1e8 maxwell (the CGS unit, 1 Mx == 1e-8 Wb).
        status, data = self._post("/api/units", {"value": 1, "from": "weber", "to": "maxwell"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 100000000.0)
        self.assertEqual(payload["category"], "magflux")

    def test_magfluxdensity_tesla_to_gauss(self):
        # 1 tesla == 10,000 gauss.
        status, data = self._post("/api/units", {"value": 1, "from": "tesla", "to": "gauss"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 10000.0)
        self.assertEqual(payload["category"], "magfluxdensity")

    def test_electrical_cross_category_rejected(self):
        # A volt is voltage, an ampere is current — incompatible families.
        status, data = self._post("/api/units", {"value": 1, "from": "v", "to": "a"})
        self.assertEqual(status, 400)
        payload = json.loads(data)
        self.assertIn("different categories", payload["error"])

    def test_smart_convert_voltage(self):
        # smart_convert must route the electrical ladder, not mis-fire on a
        # stray temperature/fuel alias.
        status, data = self._post("/api/smart", {"value": 2, "from": "kv", "to": "v"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "voltage")
        self.assertEqual(payload["result"], 2000.0)

    def test_convert_all_resistance(self):
        status, data = self._post("/api/units/all", {"value": 1, "from": "kohm"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["category"], "resistance")
        results = payload["results"]
        self.assertEqual(results["ohm"], 1000.0)
        self.assertEqual(results["kohm"], 1.0)

    def test_units_listing_includes_electrical_and_electromagnetic(self):
        status, data = self._get("/api/units")
        self.assertEqual(status, 200)
        cats = json.loads(data)["categories"]
        for name in ("voltage", "current", "resistance", "capacitance",
                     "inductance", "magflux", "magfluxdensity"):
            self.assertIn(name, cats)
        self.assertIn("kv", cats["voltage"])
        self.assertIn("ma", cats["current"])
        self.assertIn("megohm", cats["resistance"])
        self.assertIn("ufarad", cats["capacitance"])
        self.assertIn("uhenry", cats["inductance"])
        self.assertIn("maxwell", cats["magflux"])
        self.assertIn("gauss", cats["magfluxdensity"])

    # ------------------------------------------------------------------
    # New category: typography (point / pica / px / twip).
    # ------------------------------------------------------------------

    def test_typography_pica_to_point(self):
        status, data = self._post("/api/units", {"value": 1, "from": "pica", "to": "point"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 12.0)
        self.assertEqual(payload["category"], "typography")

    def test_typography_px_to_point(self):
        # A CSS reference pixel is 1/96 inch; a point is 1/72 inch -> 0.75 pt.
        status, data = self._post("/api/units", {"value": 1, "from": "px", "to": "point"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 0.75)

    def test_typography_point_to_twip(self):
        # A twip is a twentieth of a point.
        status, data = self._post("/api/units", {"value": 1, "from": "point", "to": "twip"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 20.0)

    def test_typography_pica_to_px(self):
        # 1 pica == 12 pt == 16 px (12 / 0.75).
        status, data = self._post("/api/units", {"value": 1, "from": "pica", "to": "px"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 16.0)

    def test_units_listing_includes_typography(self):
        status, data = self._get("/api/units")
        self.assertEqual(status, 200)
        cats = json.loads(data)["categories"]
        self.assertIn("typography", cats)
        for unit in ("point", "pica", "px", "twip"):
            self.assertIn(unit, cats["typography"])


class DomainUnitTest(unittest.TestCase):
    """Direct unit tests of the pure conversion functions."""

    def test_convert_units_roundtrip_speed(self):
        kph, _ = domain.convert_units(100, "kph", "mph")
        back, _ = domain.convert_units(kph, "mph", "kph")
        self.assertAlmostEqual(back, 100.0, places=9)

    def test_convert_all_identity_present(self):
        results, category = domain.convert_all(5, "gb")
        self.assertEqual(category, "data")
        self.assertEqual(results["gb"], 5.0)

    def test_convert_all_unknown_raises(self):
        with self.assertRaises(ValueError):
            domain.convert_all(1, "nope")

    def test_find_category_area(self):
        self.assertEqual(domain.find_category("acre"), "area")
        self.assertEqual(domain.find_category("MI2"), "area")

    def test_new_categories_registered(self):
        for name in ("area", "speed", "time", "data"):
            self.assertIn(name, domain.CATEGORIES)

    def test_physics_categories_registered(self):
        for name in ("power", "force", "frequency"):
            self.assertIn(name, domain.CATEGORIES)

    def test_find_category_physics(self):
        self.assertEqual(domain.find_category("hp"), "power")
        self.assertEqual(domain.find_category("KGF"), "force")
        self.assertEqual(domain.find_category("rpm"), "frequency")

    def test_units_are_globally_unique(self):
        # find_category resolves a unit to the FIRST owning category, so a unit
        # token appearing in two categories would be silently ambiguous.
        seen = {}
        for cat, units in domain.CATEGORIES.items():
            for unit in units:
                self.assertNotIn(
                    unit, seen,
                    "unit %r is in both %s and %s" % (unit, seen.get(unit), cat),
                )
                seen[unit] = cat

    def test_convert_all_power(self):
        results, category = domain.convert_all(2, "kw")
        self.assertEqual(category, "power")
        self.assertEqual(results["w"], 2000.0)
        self.assertEqual(results["kw"], 2.0)

    def test_convert_batch_independent_failures(self):
        results = domain.convert_batch([
            {"value": 1, "from": "n", "to": "kgf"},
            {"value": 1, "from": "n", "to": "hz"},  # cross-category
            {"value": "x", "from": "n", "to": "kgf"},  # bad value
        ])
        self.assertTrue(results[0]["ok"])
        self.assertFalse(results[1]["ok"])
        self.assertFalse(results[2]["ok"])

    def test_convert_temperature_all_from_fahrenheit(self):
        results = domain.convert_temperature_all(32, "F")
        self.assertEqual(results["C"], 0.0)
        self.assertEqual(results["F"], 32.0)
        self.assertEqual(results["K"], 273.15)

    def test_convert_temperature_all_unknown_raises(self):
        with self.assertRaises(ValueError):
            domain.convert_temperature_all(1, "X")

    def test_convert_fuel_roundtrip(self):
        kmpl, cat = domain.convert_fuel(35, "mpg", "kmpl")
        self.assertEqual(cat, "fuel")
        back, _ = domain.convert_fuel(kmpl, "kmpl", "mpg")
        self.assertAlmostEqual(back, 35.0, places=9)

    def test_convert_fuel_l100km_is_reciprocal(self):
        # 10 L/100km == 10 km/L; halving consumption doubles efficiency.
        kmpl, _ = domain.convert_fuel(10, "l100km", "kmpl")
        self.assertAlmostEqual(kmpl, 10.0, places=9)
        kmpl2, _ = domain.convert_fuel(5, "l100km", "kmpl")
        self.assertAlmostEqual(kmpl2, 20.0, places=9)

    def test_convert_fuel_zero_raises(self):
        with self.assertRaises(ValueError):
            domain.convert_fuel(0, "l100km", "mpg")

    def test_illuminance_category_registered(self):
        self.assertIn("illuminance", domain.CATEGORIES)
        self.assertEqual(domain.find_category("lux"), "illuminance")

    def test_convert_all_illuminance(self):
        results, category = domain.convert_all(2, "lux")
        self.assertEqual(category, "illuminance")
        self.assertEqual(results["lux"], 2.0)

    def test_list_units_includes_temperature_and_fuel(self):
        catalogue = domain.list_units()
        self.assertEqual(catalogue["temperature"], ["C", "F", "K"])
        self.assertIn("mpg", catalogue["fuel"])
        self.assertIn("l100km", catalogue["fuel"])

    # ------------------------------------------------------------------
    # New categories: bandwidth, torque.
    # ------------------------------------------------------------------

    def test_bandwidth_torque_categories_registered(self):
        for name in ("bandwidth", "torque"):
            self.assertIn(name, domain.CATEGORIES)
        self.assertEqual(domain.find_category("mbps"), "bandwidth")
        self.assertEqual(domain.find_category("LBFT"), "torque")

    def test_torque_roundtrip(self):
        nm, cat = domain.convert_units(100, "lbft", "nm")
        self.assertEqual(cat, "torque")
        back, _ = domain.convert_units(nm, "nm", "lbft")
        self.assertAlmostEqual(back, 100.0, places=9)

    def test_torque_distinct_from_energy(self):
        # Newton-metre and joule share dimensions but must stay distinct units
        # so a torque conversion never silently resolves to energy.
        self.assertNotEqual(domain.find_category("nm"), "energy")
        self.assertEqual(domain.find_category("nm"), "torque")

    def test_convert_all_bandwidth(self):
        results, category = domain.convert_all(2, "gbps")
        self.assertEqual(category, "bandwidth")
        self.assertEqual(results["mbps"], 2000.0)
        self.assertEqual(results["gbps"], 2.0)

    # ------------------------------------------------------------------
    # Unified dispatch: smart_convert across every family.
    # ------------------------------------------------------------------

    def test_smart_convert_temperature(self):
        result, category = domain.smart_convert(100, "C", "F")
        self.assertEqual(category, "temperature")
        self.assertEqual(result, 212.0)

    def test_smart_convert_temperature_full_words(self):
        result, category = domain.smart_convert(0, "celsius", "kelvin")
        self.assertEqual(category, "temperature")
        self.assertEqual(result, 273.15)

    def test_smart_convert_fuel(self):
        result, category = domain.smart_convert(5, "l100km", "kmpl")
        self.assertEqual(category, "fuel")
        self.assertAlmostEqual(result, 20.0, places=9)

    def test_smart_convert_linear(self):
        result, category = domain.smart_convert(1, "km", "m")
        self.assertEqual(category, "length")
        self.assertEqual(result, 1000.0)

    def test_smart_convert_temperature_cross_family_raises(self):
        with self.assertRaises(ValueError):
            domain.smart_convert(1, "c", "m")

    def test_smart_convert_fuel_cross_family_raises(self):
        with self.assertRaises(ValueError):
            domain.smart_convert(1, "mpg", "kph")

    def test_smart_convert_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.smart_convert(1, "bogus", "m")

    # ------------------------------------------------------------------
    # Expression parsing.
    # ------------------------------------------------------------------

    def test_parse_expression_basic(self):
        value, from_unit, to_unit = domain.parse_expression("100 km to mi")
        self.assertEqual(value, 100.0)
        self.assertEqual(from_unit, "km")
        self.assertEqual(to_unit, "mi")

    def test_parse_expression_arrow_and_no_space(self):
        value, from_unit, to_unit = domain.parse_expression("98.6f -> c")
        self.assertEqual(value, 98.6)
        self.assertEqual(from_unit, "f")
        self.assertEqual(to_unit, "c")

    def test_parse_expression_negative_and_scientific(self):
        value, from_unit, to_unit = domain.parse_expression("-1.5e3 g in kg")
        self.assertEqual(value, -1500.0)
        self.assertEqual(from_unit, "g")
        self.assertEqual(to_unit, "kg")

    def test_parse_expression_invalid_raises(self):
        with self.assertRaises(ValueError):
            domain.parse_expression("not an expression")

    def test_parse_and_convert_roundtrips_through_smart_convert(self):
        out = domain.parse_and_convert("2 h in min")
        self.assertEqual(out["category"], "time")
        self.assertEqual(out["result"], 120.0)
        self.assertEqual(out["from"], "h")
        self.assertEqual(out["to"], "min")
        self.assertEqual(out["expression"], "2 h in min")

    # ------------------------------------------------------------------
    # Previously-untested categories: acceleration, density, flowrate.
    # ------------------------------------------------------------------

    def test_acceleration_density_flowrate_registered(self):
        for name in ("acceleration", "density", "flowrate"):
            self.assertIn(name, domain.CATEGORIES)
        self.assertEqual(domain.find_category("g0"), "acceleration")
        self.assertEqual(domain.find_category("GCM3"), "density")
        self.assertEqual(domain.find_category("cfm"), "flowrate")

    def test_acceleration_roundtrip(self):
        v, cat = domain.convert_units(9.80665, "mps2", "g0")
        self.assertEqual(cat, "acceleration")
        self.assertAlmostEqual(v, 1.0, places=9)

    def test_density_kgL_equivalence(self):
        # 1 g/cm^3 == 1000 kg/m^3 == 1 kg/L by construction.
        v, _ = domain.convert_units(1, "gcm3", "kgm3")
        self.assertEqual(v, 1000.0)

    def test_convert_all_flowrate(self):
        results, category = domain.convert_all(1, "m3s")
        self.assertEqual(category, "flowrate")
        self.assertEqual(results["m3s"], 1.0)
        self.assertAlmostEqual(results["ls"], 1000.0, places=6)

    # ------------------------------------------------------------------
    # Number bases (convert_base) — previously only covered indirectly.
    # ------------------------------------------------------------------

    def test_convert_base_roundtrip(self):
        hexed, name = domain.convert_base("255", "dec", "hex")
        self.assertEqual(hexed, "ff")
        self.assertEqual(name, "hex")
        back, _ = domain.convert_base(hexed, "hex", "dec")
        self.assertEqual(back, "255")

    def test_convert_base_negative_preserved(self):
        out, _ = domain.convert_base("-10", "dec", "bin")
        self.assertEqual(out, "-1010")

    def test_convert_base_invalid_digit_raises(self):
        with self.assertRaises(ValueError):
            domain.convert_base("2", "bin", "dec")

    # ------------------------------------------------------------------
    # Roman numerals (int_to_roman / roman_to_int / convert_roman).
    # ------------------------------------------------------------------

    def test_int_to_roman_canonical(self):
        self.assertEqual(domain.int_to_roman(4), "IV")
        self.assertEqual(domain.int_to_roman(9), "IX")
        self.assertEqual(domain.int_to_roman(2024), "MMXXIV")
        self.assertEqual(domain.int_to_roman(3999), "MMMCMXCIX")

    def test_roman_to_int_canonical(self):
        self.assertEqual(domain.roman_to_int("IV"), 4)
        self.assertEqual(domain.roman_to_int("MMXXIV"), 2024)
        self.assertEqual(domain.roman_to_int("mcmlxxxiv"), 1984)

    def test_roman_roundtrip_full_range_sample(self):
        for n in (1, 14, 40, 90, 400, 944, 1666, 3888, 3999):
            self.assertEqual(domain.roman_to_int(domain.int_to_roman(n)), n)

    def test_int_to_roman_out_of_range_raises(self):
        for bad in (0, -1, 4000):
            with self.assertRaises(ValueError):
                domain.int_to_roman(bad)

    def test_int_to_roman_non_integer_raises(self):
        with self.assertRaises(ValueError):
            domain.int_to_roman(3.5)

    def test_roman_to_int_rejects_noncanonical(self):
        for bad in ("IIII", "VV", "IC", "XXXX", "MMMM"):
            with self.assertRaises(ValueError):
                domain.roman_to_int(bad)

    def test_roman_to_int_rejects_garbage(self):
        with self.assertRaises(ValueError):
            domain.roman_to_int("ABC")

    def test_convert_roman_both_directions(self):
        roman, cat = domain.convert_roman(49, "arabic", "roman")
        self.assertEqual(roman, "XLIX")
        self.assertEqual(cat, "roman")
        arabic, _ = domain.convert_roman("XLIX", "roman", "arabic")
        self.assertEqual(arabic, "49")

    def test_convert_roman_unknown_notation_raises(self):
        with self.assertRaises(ValueError):
            domain.convert_roman(5, "arabic", "greek")

    def test_list_units_includes_base_and_roman(self):
        catalogue = domain.list_units()
        self.assertIn("hex", catalogue["base"])
        self.assertEqual(catalogue["roman"], ["arabic", "roman"])

    # ------------------------------------------------------------------
    # Colour notations (parse_hex / parse_rgb / parse_hsl / convert_color).
    # ------------------------------------------------------------------

    def test_parse_hex_full_and_shorthand(self):
        self.assertEqual(domain.parse_hex("#ff8800"), (255, 136, 0))
        self.assertEqual(domain.parse_hex("f80"), (255, 136, 0))
        self.assertEqual(domain.parse_hex("#FFFFFF"), (255, 255, 255))

    def test_parse_hex_invalid_raises(self):
        for bad in ("#gg0000", "#12345", "ZZZ", ""):
            with self.assertRaises(ValueError):
                domain.parse_hex(bad)

    def test_parse_rgb_accepts_several_shapes(self):
        self.assertEqual(domain.parse_rgb("rgb(1, 2, 3)"), (1, 2, 3))
        self.assertEqual(domain.parse_rgb("1,2,3"), (1, 2, 3))
        self.assertEqual(domain.parse_rgb("10 20 30"), (10, 20, 30))

    def test_parse_rgb_out_of_range_raises(self):
        for bad in ("rgb(256, 0, 0)", "0, -1, 0", "1, 2"):
            with self.assertRaises(ValueError):
                domain.parse_rgb(bad)

    def test_parse_hsl_to_rgb(self):
        self.assertEqual(domain.parse_hsl("hsl(0, 100%, 50%)"), (255, 0, 0))
        self.assertEqual(domain.parse_hsl("240, 100, 50"), (0, 0, 255))
        self.assertEqual(domain.parse_hsl("hsl(0, 0%, 0%)"), (0, 0, 0))

    def test_parse_hsl_out_of_range_raises(self):
        for bad in ("hsl(400, 0%, 0%)", "0, 101%, 0%", "0, 0%, 200%"):
            with self.assertRaises(ValueError):
                domain.parse_hsl(bad)

    def test_rgb_hsl_known_vectors(self):
        # Primary colours round-trip through the canonical HSL rendering.
        self.assertEqual(domain._rgb_to_hsl(255, 0, 0), (0, 100, 50))
        self.assertEqual(domain._rgb_to_hsl(0, 255, 0), (120, 100, 50))
        self.assertEqual(domain._rgb_to_hsl(0, 0, 255), (240, 100, 50))
        self.assertEqual(domain._rgb_to_hsl(0, 0, 0), (0, 0, 0))
        self.assertEqual(domain._rgb_to_hsl(255, 255, 255), (0, 0, 100))

    def test_convert_color_roundtrip_hex_rgb(self):
        rgb, cat = domain.convert_color("#1e293b", "hex", "rgb")
        self.assertEqual(cat, "color")
        self.assertEqual(rgb, "rgb(30, 41, 59)")
        back, _ = domain.convert_color(rgb, "rgb", "hex")
        self.assertEqual(back, "#1e293b")

    def test_convert_color_hsl_roundtrip_primary(self):
        hsl, _ = domain.convert_color("#0000ff", "hex", "hsl")
        self.assertEqual(hsl, "hsl(240, 100%, 50%)")
        back, _ = domain.convert_color(hsl, "hsl", "hex")
        self.assertEqual(back, "#0000ff")

    def test_convert_color_unknown_notation_raises(self):
        with self.assertRaises(ValueError):
            domain.convert_color("#ff0000", "hex", "cmyk")
        with self.assertRaises(ValueError):
            domain.convert_color("#ff0000", "xyz", "rgb")

    def test_list_units_includes_color(self):
        catalogue = domain.list_units()
        self.assertEqual(catalogue["color"], ["hex", "hsl", "rgb"])

    # ------------------------------------------------------------------
    # Electrical & electromagnetic families (pure-function level).
    # ------------------------------------------------------------------

    def test_electrical_categories_registered(self):
        for name in ("voltage", "current", "resistance"):
            self.assertIn(name, domain.CATEGORIES)
        self.assertEqual(domain.find_category("kv"), "voltage")
        self.assertEqual(domain.find_category("MA"), "current")
        self.assertEqual(domain.find_category("megohm"), "resistance")

    def test_electromagnetic_categories_registered(self):
        for name in ("capacitance", "inductance", "magflux", "magfluxdensity"):
            self.assertIn(name, domain.CATEGORIES)
        self.assertEqual(domain.find_category("ufarad"), "capacitance")
        self.assertEqual(domain.find_category("henry"), "inductance")
        self.assertEqual(domain.find_category("maxwell"), "magflux")
        self.assertEqual(domain.find_category("GAUSS"), "magfluxdensity")

    def test_voltage_roundtrip(self):
        mv, cat = domain.convert_units(2, "kv", "mv")
        self.assertEqual(cat, "voltage")
        self.assertEqual(mv, 2_000_000.0)
        back, _ = domain.convert_units(mv, "mv", "kv")
        self.assertAlmostEqual(back, 2.0, places=9)

    def test_magfluxdensity_gauss_is_cgs(self):
        # 1 gauss == 1e-4 tesla by definition.
        v, _ = domain.convert_units(1, "gauss", "tesla")
        self.assertAlmostEqual(v, 1e-4, places=12)

    def test_smart_convert_resistance(self):
        result, category = domain.smart_convert(1, "megohm", "ohm")
        self.assertEqual(category, "resistance")
        self.assertEqual(result, 1_000_000.0)

    def test_convert_all_capacitance(self):
        results, category = domain.convert_all(1, "farad")
        self.assertEqual(category, "capacitance")
        self.assertEqual(results["farad"], 1.0)
        self.assertEqual(results["mfarad"], 1000.0)

    # ------------------------------------------------------------------
    # Typography (point / pica / px / twip).
    # ------------------------------------------------------------------

    def test_typography_registered_and_disjoint_from_volume_pint(self):
        self.assertIn("typography", domain.CATEGORIES)
        self.assertEqual(domain.find_category("point"), "typography")
        # The volume pint "pt" must NOT be confused with a typographic point.
        self.assertEqual(domain.find_category("pt"), "volume")

    def test_typography_roundtrip(self):
        px, cat = domain.convert_units(36, "point", "px")
        self.assertEqual(cat, "typography")
        self.assertEqual(px, 48.0)  # 36 pt / 0.75 == 48 px
        back, _ = domain.convert_units(px, "px", "point")
        self.assertAlmostEqual(back, 36.0, places=9)

    def test_typography_pica_point_twip_relations(self):
        # 1 pica == 12 point == 240 twip.
        v, _ = domain.convert_units(1, "pica", "twip")
        self.assertEqual(v, 240.0)

    def test_list_units_includes_typography(self):
        catalogue = domain.list_units()
        self.assertIn("typography", catalogue)
        self.assertEqual(catalogue["typography"], ["pica", "point", "px", "twip"])


class _ServerTestBase(unittest.TestCase):
    """Boot the real HTTP server on an ephemeral port for end-to-end tests."""

    def setUp(self):
        self.server = make_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _post(self, path, payload):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("POST", path, body=json.dumps(payload),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read()
        status = resp.status
        conn.close()
        return status, data


class Req001TraceabilityTest(_ServerTestBase):
    """Trace REQ-001 ("convert between celsius and fahrenheit") to live tests.

    Spec: specs/unit-converter-convert-between/spec.md (REQ-001), exercised by
    TC-1.1 (happy path) and TC-1.2 (edge/failure) from test-cases.md. These
    tests reference the requirement ID explicitly so the functional-coverage
    tracer can prove the suite is tracing the spec, not just covering code.
    """

    def test_req_001_tc_1_1_celsius_to_fahrenheit_happy_path(self):
        # REQ-001 / TC-1.1: boiling water 100 C is exactly 212 F.
        status, data = self._post("/api/convert", {"value": 100, "direction": "c2f"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 212.0)
        self.assertEqual(payload["unit"], "F")

    def test_req_001_fahrenheit_to_celsius_roundtrip(self):
        # REQ-001: the inverse direction round-trips 32 F back to 0 C.
        status, data = self._post("/api/convert", {"value": 32, "direction": "f2c"})
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload["result"], 0.0)
        self.assertEqual(payload["unit"], "C")

    def test_req_001_tc_1_2_invalid_input_fails_safe(self):
        # REQ-001 / TC-1.2: a non-numeric value fails safe with a clear 400.
        status, _ = self._post("/api/convert", {"value": "abc", "direction": "c2f"})
        self.assertEqual(status, 400)


class OverflowFinitenessTest(_ServerTestBase):
    """A finite input that overflows must never emit the invalid JSON token
    ``Infinity`` (RFC 8259) — every endpoint fails safe with a 400 instead."""

    def _assert_no_infinity_literal(self, raw):
        # The bare `Infinity`/`NaN` tokens are what break strict JSON.parse.
        self.assertNotIn(b"Infinity", raw)
        self.assertNotIn(b"NaN", raw)

    def test_units_overflow_returns_400_not_infinity(self):
        status, raw = self._post("/api/units", {"value": 1e308, "from": "tb", "to": "b"})
        self.assertEqual(status, 400)
        self._assert_no_infinity_literal(raw)

    def test_convert_temperature_overflow_returns_400(self):
        status, raw = self._post("/api/convert", {"value": 1e308, "direction": "c2f"})
        self.assertEqual(status, 400)
        self._assert_no_infinity_literal(raw)

    def test_units_all_overflow_returns_400(self):
        status, raw = self._post("/api/units/all", {"value": 1e308, "from": "tb"})
        self.assertEqual(status, 400)
        self._assert_no_infinity_literal(raw)

    def test_temperature_all_overflow_returns_400(self):
        status, raw = self._post("/api/temperature/all", {"value": 1e308, "from": "C"})
        self.assertEqual(status, 400)
        self._assert_no_infinity_literal(raw)

    def test_parse_overflow_returns_400(self):
        status, raw = self._post("/api/parse", {"expression": "1e999 m to km"})
        self.assertEqual(status, 400)
        self._assert_no_infinity_literal(raw)

    def test_batch_overflow_marks_item_not_ok_not_infinity(self):
        # Batch is independent-per-item: the overflow item fails, others survive.
        status, raw = self._post("/api/units/batch", {"conversions": [
            {"value": 1e308, "from": "tb", "to": "b"},
            {"value": 1, "from": "km", "to": "m"},
        ]})
        self.assertEqual(status, 200)
        self._assert_no_infinity_literal(raw)
        payload = json.loads(raw)
        self.assertFalse(payload["results"][0]["ok"])
        self.assertTrue(payload["results"][1]["ok"])
        self.assertEqual(payload["results"][1]["result"], 1000.0)

    def test_parse_expression_rejects_non_finite_value(self):
        with self.assertRaises(ValueError):
            domain.parse_expression("1e999 m to km")

    def test_normal_conversion_still_succeeds(self):
        # The guard must not regress an ordinary in-range conversion.
        status, raw = self._post("/api/units", {"value": 1, "from": "km", "to": "m"})
        self.assertEqual(status, 200)
        self._assert_no_infinity_literal(raw)
        self.assertEqual(json.loads(raw)["result"], 1000.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
