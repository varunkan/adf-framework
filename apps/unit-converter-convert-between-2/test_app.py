"""Test suite for the multi-category unit converter — stdlib unittest only.

Covers the pure domain logic (``domain.py``), the legacy meters<->feet helpers
that still live in ``server.py``, and the live HTTP API served by
``make_server``. Run with:  python3 -m unittest -v
"""

import json
import math
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import domain  # noqa: E402
import server  # noqa: E402


# --------------------------------------------------------------------------- #
# Pure domain logic
# --------------------------------------------------------------------------- #
class TestDomainLength(unittest.TestCase):
    def test_meters_to_feet(self):
        result, cat = domain.convert_units(1, "m", "ft")
        self.assertAlmostEqual(result, 3.280839895, places=6)
        self.assertEqual(cat, "length")

    def test_feet_to_meters(self):
        result, _ = domain.convert_units(3.280839895, "ft", "m")
        self.assertAlmostEqual(result, 1.0, places=6)

    def test_km_to_mile(self):
        result, _ = domain.convert_units(1, "km", "mi")
        self.assertAlmostEqual(result, 0.621371192, places=6)

    def test_inch_to_cm(self):
        result, _ = domain.convert_units(1, "in", "cm")
        self.assertAlmostEqual(result, 2.54, places=9)

    def test_identity(self):
        result, _ = domain.convert_units(42, "m", "m")
        self.assertAlmostEqual(result, 42.0, places=9)

    def test_negative_value(self):
        result, _ = domain.convert_units(-2, "m", "cm")
        self.assertAlmostEqual(result, -200.0, places=6)


class TestDomainMass(unittest.TestCase):
    def test_kg_to_lb(self):
        result, cat = domain.convert_units(1, "kg", "lb")
        self.assertAlmostEqual(result, 2.204622622, places=6)
        self.assertEqual(cat, "mass")

    def test_g_to_oz(self):
        result, _ = domain.convert_units(100, "g", "oz")
        self.assertAlmostEqual(result, 3.527396195, places=6)

    def test_tonne_to_kg(self):
        result, _ = domain.convert_units(1, "t", "kg")
        self.assertAlmostEqual(result, 1000.0, places=6)


class TestDomainTemperature(unittest.TestCase):
    def test_c_to_f_freezing(self):
        result, cat = domain.convert_units(0, "c", "f")
        self.assertAlmostEqual(result, 32.0, places=9)
        self.assertEqual(cat, "temperature")

    def test_c_to_f_boiling(self):
        result, _ = domain.convert_units(100, "c", "f")
        self.assertAlmostEqual(result, 212.0, places=9)

    def test_f_to_c(self):
        result, _ = domain.convert_units(98.6, "f", "c")
        self.assertAlmostEqual(result, 37.0, places=9)

    def test_c_to_k(self):
        result, _ = domain.convert_units(0, "c", "k")
        self.assertAlmostEqual(result, 273.15, places=9)

    def test_k_to_c(self):
        result, _ = domain.convert_units(0, "k", "c")
        self.assertAlmostEqual(result, -273.15, places=9)


class TestDomainVolumeTime(unittest.TestCase):
    def test_liter_to_gallon(self):
        result, cat = domain.convert_units(1, "l", "gal")
        self.assertAlmostEqual(result, 0.264172052, places=6)
        self.assertEqual(cat, "volume")

    def test_hour_to_minutes(self):
        result, cat = domain.convert_units(1, "h", "min")
        self.assertAlmostEqual(result, 60.0, places=6)
        self.assertEqual(cat, "time")

    def test_day_to_hours(self):
        result, _ = domain.convert_units(1, "day", "h")
        self.assertAlmostEqual(result, 24.0, places=6)


class TestDomainArea(unittest.TestCase):
    def test_category(self):
        self.assertEqual(domain.category_of("ft2"), "area")

    def test_sqm_to_sqft(self):
        result, cat = domain.convert_units(1, "m2", "ft2")
        self.assertAlmostEqual(result, 10.763910417, places=6)
        self.assertEqual(cat, "area")

    def test_hectare_to_sqm(self):
        result, _ = domain.convert_units(1, "ha", "m2")
        self.assertAlmostEqual(result, 10000.0, places=6)

    def test_acre_to_sqm(self):
        result, _ = domain.convert_units(1, "ac", "m2")
        self.assertAlmostEqual(result, 4046.8564224, places=6)


class TestDomainSpeed(unittest.TestCase):
    def test_category(self):
        self.assertEqual(domain.category_of("mph"), "speed")

    def test_mps_to_kph(self):
        result, cat = domain.convert_units(10, "mps", "kph")
        self.assertAlmostEqual(result, 36.0, places=6)
        self.assertEqual(cat, "speed")

    def test_mph_to_mps(self):
        result, _ = domain.convert_units(60, "mph", "mps")
        self.assertAlmostEqual(result, 26.8224, places=6)

    def test_knot_to_kph(self):
        result, _ = domain.convert_units(1, "kn", "kph")
        self.assertAlmostEqual(result, 1.852, places=6)


class TestDomainDigital(unittest.TestCase):
    def test_category(self):
        self.assertEqual(domain.category_of("gb"), "digital")

    def test_byte_to_bits(self):
        result, cat = domain.convert_units(1, "b", "bit")
        self.assertAlmostEqual(result, 8.0, places=9)
        self.assertEqual(cat, "digital")

    def test_kib_to_bytes(self):
        result, _ = domain.convert_units(1, "kib", "b")
        self.assertAlmostEqual(result, 1024.0, places=6)

    def test_decimal_vs_binary(self):
        result, _ = domain.convert_units(1, "gib", "gb")
        self.assertAlmostEqual(result, 1.073741824, places=6)

    def test_gb_to_mb(self):
        result, _ = domain.convert_units(1, "gb", "mb")
        self.assertAlmostEqual(result, 1000.0, places=6)


class TestDomainFuel(unittest.TestCase):
    def test_category(self):
        self.assertEqual(domain.category_of("mpg"), "fuel")
        self.assertEqual(domain.category_of("l/100km"), "fuel")
        self.assertEqual(domain.category_of("km/l"), "fuel")

    def test_mpg_us_to_l100km(self):
        # Standard reference constant: L/100km = 235.214583 / mpg(US).
        result, cat = domain.convert_units(30, "mpg", "l/100km")
        self.assertAlmostEqual(result, 235.214583 / 30.0, places=4)
        self.assertEqual(cat, "fuel")

    def test_l100km_to_mpg_us(self):
        result, _ = domain.convert_units(235.214583 / 30.0, "l/100km", "mpg")
        self.assertAlmostEqual(result, 30.0, places=4)

    def test_mpg_uk_to_l100km(self):
        # Standard reference constant: L/100km = 282.480936 / mpg(UK).
        result, _ = domain.convert_units(40, "mpguk", "l/100km")
        self.assertAlmostEqual(result, 282.480936 / 40.0, places=4)

    def test_kml_to_l100km(self):
        result, _ = domain.convert_units(20, "km/l", "l/100km")
        self.assertAlmostEqual(result, 5.0, places=9)

    def test_l100km_to_kml(self):
        result, _ = domain.convert_units(5, "l/100km", "km/l")
        self.assertAlmostEqual(result, 20.0, places=9)

    def test_us_vs_uk_mpg_differ(self):
        # A US and UK gallon differ, so the same mpg number is not the same L/100km.
        us, _ = domain.convert_units(30, "mpg", "l/100km")
        uk, _ = domain.convert_units(30, "mpguk", "l/100km")
        self.assertNotAlmostEqual(us, uk, places=3)

    def test_roundtrip_mpg(self):
        l100, _ = domain.convert_units(42.5, "mpg", "l/100km")
        back, _ = domain.convert_units(l100, "l/100km", "mpg")
        self.assertAlmostEqual(back, 42.5, places=6)

    def test_zero_value_rejected(self):
        with self.assertRaises(ValueError):
            domain.convert_units(0, "mpg", "l/100km")

    def test_negative_value_rejected(self):
        with self.assertRaises(ValueError):
            domain.convert_units(-5, "km/l", "mpg")

    def test_fuel_in_convert_to_all(self):
        results, cat = domain.convert_to_all(30, "mpg")
        self.assertEqual(cat, "fuel")
        units = [r["unit"] for r in results]
        self.assertEqual(units, ["mpg", "mpguk", "l/100km", "km/l"])

    def test_fuel_listed_as_category(self):
        self.assertIn("fuel", domain.list_categories())
        self.assertIn("mpg", domain.units_for("fuel"))


class TestDomainDataRate(unittest.TestCase):
    def test_category(self):
        self.assertEqual(domain.category_of("mbps"), "datarate")
        self.assertEqual(domain.category_of("gb/s"), "datarate")

    def test_kbps_to_bps(self):
        result, cat = domain.convert_units(1, "kbps", "bps")
        self.assertAlmostEqual(result, 1000.0, places=6)
        self.assertEqual(cat, "datarate")

    def test_mbps_to_kbps(self):
        result, _ = domain.convert_units(1, "mbps", "kbps")
        self.assertAlmostEqual(result, 1000.0, places=6)

    def test_byte_rate_is_eight_bits(self):
        # 1 MB/s == 8 Mbps (one byte is eight bits).
        result, _ = domain.convert_units(1, "mb/s", "mbps")
        self.assertAlmostEqual(result, 8.0, places=6)

    def test_gbps_to_mbps(self):
        result, _ = domain.convert_units(1, "gbps", "mbps")
        self.assertAlmostEqual(result, 1000.0, places=6)

    def test_decimal_prefixes_not_binary(self):
        # Networking uses decimal prefixes: 1 kbps is exactly 1000 bit/s.
        result, _ = domain.convert_units(2, "kbps", "bps")
        self.assertAlmostEqual(result, 2000.0, places=6)

    def test_listed_as_category(self):
        self.assertIn("datarate", domain.list_categories())
        self.assertIn("mbps", domain.units_for("datarate"))

    def test_cross_category_rejected(self):
        # A data RATE is not a storage SIZE — must not convert to bytes.
        with self.assertRaises(ValueError):
            domain.convert_units(1, "mbps", "mb")


class TestDomainConversionFactor(unittest.TestCase):
    def test_length_factor(self):
        factor, cat = domain.conversion_factor("km", "m")
        self.assertAlmostEqual(factor, 1000.0, places=9)
        self.assertEqual(cat, "length")

    def test_factor_applies_to_value(self):
        factor, _ = domain.conversion_factor("kg", "g")
        self.assertAlmostEqual(5 * factor, 5000.0, places=6)

    def test_inverse_factor(self):
        fwd, _ = domain.conversion_factor("km", "m")
        back, _ = domain.conversion_factor("m", "km")
        self.assertAlmostEqual(fwd * back, 1.0, places=12)

    def test_datarate_factor(self):
        factor, cat = domain.conversion_factor("gbps", "mbps")
        self.assertEqual(cat, "datarate")
        self.assertAlmostEqual(factor, 1000.0, places=6)

    def test_temperature_rejected(self):
        # Affine, so no single multiplicative factor exists.
        with self.assertRaises(ValueError):
            domain.conversion_factor("c", "f")

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.conversion_factor("mpg", "l/100km")

    def test_cross_category_rejected(self):
        with self.assertRaises(ValueError):
            domain.conversion_factor("m", "kg")

    def test_unknown_unit_rejected(self):
        with self.assertRaises(ValueError):
            domain.conversion_factor("zorp", "m")


class TestDomainUnitInfo(unittest.TestCase):
    def test_known_unit(self):
        info = domain.unit_info("ft")
        self.assertEqual(info["category"], "length")
        self.assertIn("foot", info["aliases"])
        self.assertIn("feet", info["aliases"])

    def test_normalizes_token(self):
        info = domain.unit_info("  FT ")
        self.assertEqual(info["unit"], "ft")

    def test_temperature_unit(self):
        info = domain.unit_info("celsius")
        self.assertEqual(info["category"], "temperature")
        self.assertIn("c", info["aliases"])

    def test_fuel_unit(self):
        info = domain.unit_info("mpg")
        self.assertEqual(info["category"], "fuel")
        self.assertIn("mpgus", info["aliases"])

    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            domain.unit_info("zorp")


class TestDomainExpressionParser(unittest.TestCase):
    def test_to_connector(self):
        self.assertEqual(domain.parse_expression("10 km to mi"), (10.0, "km", "mi"))

    def test_in_connector(self):
        self.assertEqual(domain.parse_expression("10 m in ft"), (10.0, "m", "ft"))

    def test_arrow_connector(self):
        self.assertEqual(domain.parse_expression("10km->mi"), (10.0, "km", "mi"))

    def test_no_space_number_unit(self):
        self.assertEqual(domain.parse_expression("2.5kg to lb"), (2.5, "kg", "lb"))

    def test_leading_convert_keyword(self):
        self.assertEqual(domain.parse_expression("convert 5 ft to m"), (5.0, "ft", "m"))

    def test_in_inside_min_not_split(self):
        # "min" contains "in" but must not be carved as a connector.
        self.assertEqual(domain.parse_expression("90 min to h"), (90.0, "min", "h"))

    def test_negative_value(self):
        self.assertEqual(domain.parse_expression("-40 c to f"), (-40.0, "c", "f"))

    def test_slash_unit(self):
        self.assertEqual(domain.parse_expression("100 km/h to mph"), (100.0, "km/h", "mph"))

    def test_unparseable_raises(self):
        with self.assertRaises(ValueError):
            domain.parse_expression("gibberish")

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            domain.parse_expression(None)

    def test_convert_expression_evaluates(self):
        value, frm, to, result, cat = domain.convert_expression("1 km to mi")
        self.assertEqual((frm, to, cat), ("km", "mi", "length"))
        self.assertAlmostEqual(result, 0.621371192, places=6)

    def test_convert_expression_bad_units(self):
        with self.assertRaises(ValueError):
            domain.convert_expression("1 m to kg")


class TestDomainAliasesAndNormalization(unittest.TestCase):
    def test_alias_kilometre(self):
        result, _ = domain.convert_units(1, "kilometre", "m")
        self.assertAlmostEqual(result, 1000.0, places=6)

    def test_whitespace_and_case(self):
        result, _ = domain.convert_units(1, "  KM ", "M")
        self.assertAlmostEqual(result, 1000.0, places=6)

    def test_dotted_unit(self):
        # normalise strips dots: "m.p.h" -> "mph"
        self.assertEqual(domain.normalize_unit("M.P.H"), "mph")

    def test_normalize_unit_none_raises(self):
        with self.assertRaises(ValueError):
            domain.normalize_unit(None)


class TestDomainErrors(unittest.TestCase):
    def test_unknown_from_unit(self):
        with self.assertRaises(ValueError):
            domain.convert_units(1, "bananas", "m")

    def test_unknown_to_unit(self):
        with self.assertRaises(ValueError):
            domain.convert_units(1, "m", "bananas")

    def test_cross_category(self):
        with self.assertRaises(ValueError):
            domain.convert_units(1, "m", "kg")

    def test_non_numeric_value(self):
        with self.assertRaises(ValueError):
            domain.convert_units("abc", "m", "ft")

    def test_infinite_value(self):
        with self.assertRaises(ValueError):
            domain.convert_units(float("inf"), "m", "ft")

    def test_nan_value(self):
        with self.assertRaises(ValueError):
            domain.convert_units(float("nan"), "m", "ft")


class TestDomainDiscovery(unittest.TestCase):
    def test_list_categories_includes_all(self):
        cats = domain.list_categories()
        for expected in ("length", "mass", "temperature", "volume",
                         "time", "area", "speed", "digital"):
            self.assertIn(expected, cats)

    def test_units_for_known(self):
        self.assertIn("ft", domain.units_for("length"))

    def test_units_for_unknown_raises(self):
        with self.assertRaises(ValueError):
            domain.units_for("nonsense")

    def test_category_of_unknown_returns_none(self):
        self.assertIsNone(domain.category_of("zorp"))


class TestDomainIlluminance(unittest.TestCase):
    def test_category(self):
        self.assertEqual(domain.category_of("lux"), "illuminance")
        self.assertEqual(domain.category_of("footcandle"), "illuminance")

    def test_footcandle_to_lux(self):
        # 1 foot-candle == 1 lumen/ft^2 == 10.76391041670972 lux.
        result, cat = domain.convert_units(1, "footcandle", "lux")
        self.assertAlmostEqual(result, 10.76391041670972, places=6)
        self.assertEqual(cat, "illuminance")

    def test_lux_to_footcandle(self):
        result, _ = domain.convert_units(10.76391041670972, "lux", "fc")
        self.assertAlmostEqual(result, 1.0, places=9)

    def test_klx_to_lux(self):
        result, _ = domain.convert_units(1, "klx", "lux")
        self.assertAlmostEqual(result, 1000.0, places=6)

    def test_phot_to_lux(self):
        result, _ = domain.convert_units(1, "phot", "lux")
        self.assertAlmostEqual(result, 1e4, places=3)

    def test_listed_as_category(self):
        self.assertIn("illuminance", domain.list_categories())
        self.assertIn("lux", domain.units_for("illuminance"))


class TestDomainCharge(unittest.TestCase):
    def test_category(self):
        self.assertEqual(domain.category_of("coulomb"), "charge")
        self.assertEqual(domain.category_of("ah"), "charge")

    def test_amperehour_to_coulomb(self):
        # 1 Ah == 3600 C (one ampere flowing for one hour).
        result, cat = domain.convert_units(1, "ah", "coulomb")
        self.assertAlmostEqual(result, 3600.0, places=6)
        self.assertEqual(cat, "charge")

    def test_mah_to_coulomb(self):
        result, _ = domain.convert_units(1000, "mah", "coulomb")
        self.assertAlmostEqual(result, 3600.0, places=6)

    def test_coulomb_to_kc(self):
        result, _ = domain.convert_units(1000, "coulomb", "kc")
        self.assertAlmostEqual(result, 1.0, places=9)

    def test_coulomb_not_celsius(self):
        # A bare "c" is Celsius, never coulomb — categories must not collide.
        self.assertEqual(domain.category_of("c"), "temperature")

    def test_listed_as_category(self):
        self.assertIn("charge", domain.list_categories())
        self.assertIn("coulomb", domain.units_for("charge"))


class TestDomainHumanize(unittest.TestCase):
    def test_scale_up_meters_to_km(self):
        value, unit, cat = domain.humanize(1500, "m")
        self.assertEqual((unit, cat), ("km", "length"))
        self.assertAlmostEqual(value, 1.5, places=9)

    def test_scale_down_meters_to_mm(self):
        value, unit, _ = domain.humanize(0.005, "m")
        self.assertEqual(unit, "mm")
        self.assertAlmostEqual(value, 5.0, places=9)

    def test_keeps_largest_metric_unit(self):
        # 1,500,000 m stays metric (km), never jumps to nautical miles.
        value, unit, _ = domain.humanize(1_500_000, "m")
        self.assertEqual(unit, "km")
        self.assertAlmostEqual(value, 1500.0, places=6)

    def test_time_minutes_to_hours(self):
        value, unit, cat = domain.humanize(90, "min")
        self.assertEqual((unit, cat), ("h", "time"))
        self.assertAlmostEqual(value, 1.5, places=9)

    def test_mass_grams_to_kg(self):
        value, unit, _ = domain.humanize(2500, "g")
        self.assertEqual(unit, "kg")
        self.assertAlmostEqual(value, 2.5, places=9)

    def test_digital_bytes_to_mb(self):
        value, unit, _ = domain.humanize(5_000_000, "b")
        self.assertEqual(unit, "mb")
        self.assertAlmostEqual(value, 5.0, places=6)

    def test_zero_uses_smallest_unit(self):
        value, unit, _ = domain.humanize(0, "m")
        self.assertEqual(unit, "mm")
        self.assertAlmostEqual(value, 0.0, places=9)

    def test_negative_preserved(self):
        value, unit, _ = domain.humanize(-2000, "m")
        self.assertEqual(unit, "km")
        self.assertAlmostEqual(value, -2.0, places=9)

    def test_unsupported_category_raises(self):
        # Temperature is affine — there is no metric ladder to scale on.
        with self.assertRaises(ValueError):
            domain.humanize(100, "c")

    def test_fuel_unsupported(self):
        with self.assertRaises(ValueError):
            domain.humanize(30, "mpg")

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.humanize(1, "zorp")

    def test_nonfinite_raises(self):
        with self.assertRaises(ValueError):
            domain.humanize(float("inf"), "m")


class TestDomainSearch(unittest.TestCase):
    def test_substring_match(self):
        matches = domain.search_units("met")
        tokens = {m["unit"] for m in matches}
        self.assertIn("meter", tokens)
        self.assertIn("centimeter", tokens)

    def test_results_carry_category(self):
        matches = domain.search_units("lux")
        self.assertTrue(matches)
        self.assertTrue(all(m["category"] == "illuminance" for m in matches if m["unit"] in ("lux", "klx", "kilolux")))

    def test_sorted_and_deduped(self):
        matches = domain.search_units("ft")
        pairs = [(m["category"], m["unit"]) for m in matches]
        self.assertEqual(pairs, sorted(set(pairs)))

    def test_empty_query_raises(self):
        with self.assertRaises(ValueError):
            domain.search_units("   ")

    def test_none_query_raises(self):
        with self.assertRaises(ValueError):
            domain.search_units(None)

    def test_no_matches_returns_empty(self):
        self.assertEqual(domain.search_units("zzzznotareal"), [])


class TestDomainIntegrity(unittest.TestCase):
    """Guard rails for the additive category design."""

    def test_no_cross_category_token_collisions(self):
        # Every accepted token must map to exactly one category, or category_of
        # would silently shadow units across categories.
        seen = {}
        for token, cat in domain._all_unit_tokens():
            if token in seen:
                self.assertEqual(
                    seen[token], cat,
                    "token %r maps to both %s and %s" % (token, seen[token], cat),
                )
            seen[token] = cat

    def test_canonical_units_are_real_tokens(self):
        # Every canonical/display token must actually be convertible.
        for cat in domain.list_categories():
            for unit in domain.units_for(cat):
                self.assertEqual(domain.category_of(unit), cat,
                                 "canonical unit %r not in category %s" % (unit, cat))

    def test_humanize_ladders_are_canonical(self):
        for cat, ladder in domain.HUMANIZE_LADDERS.items():
            for unit in ladder:
                self.assertEqual(domain.category_of(unit), cat)


class TestDomainConversionTable(unittest.TestCase):
    def test_basic_length_table(self):
        rows, cat = domain.conversion_table("km", "m", 0, 3, 1)
        self.assertEqual(cat, "length")
        self.assertEqual([r["input"] for r in rows], [0.0, 1.0, 2.0, 3.0])
        self.assertEqual([r["result"] for r in rows], [0.0, 1000.0, 2000.0, 3000.0])

    def test_inclusive_endpoint(self):
        # A clean 0..10 step 1 range yields exactly 11 rows (endpoint included).
        rows, _ = domain.conversion_table("m", "ft", 0, 10, 1)
        self.assertEqual(len(rows), 11)

    def test_temperature_table(self):
        rows, cat = domain.conversion_table("c", "f", 0, 100, 50)
        self.assertEqual(cat, "temperature")
        self.assertEqual([r["input"] for r in rows], [0.0, 50.0, 100.0])
        self.assertAlmostEqual(rows[0]["result"], 32.0, places=6)
        self.assertAlmostEqual(rows[2]["result"], 212.0, places=6)

    def test_fractional_step(self):
        rows, _ = domain.conversion_table("m", "cm", 0, 1, 0.5)
        self.assertEqual([r["input"] for r in rows], [0.0, 0.5, 1.0])
        self.assertEqual([r["result"] for r in rows], [0.0, 50.0, 100.0])

    def test_zero_step_rejected(self):
        with self.assertRaises(ValueError):
            domain.conversion_table("m", "ft", 0, 10, 0)

    def test_negative_step_rejected(self):
        with self.assertRaises(ValueError):
            domain.conversion_table("m", "ft", 0, 10, -1)

    def test_stop_before_start_rejected(self):
        with self.assertRaises(ValueError):
            domain.conversion_table("m", "ft", 10, 0, 1)

    def test_too_many_rows_rejected(self):
        with self.assertRaises(ValueError):
            domain.conversion_table("m", "ft", 0, 1, 1e-9)

    def test_cross_category_rejected(self):
        with self.assertRaises(ValueError):
            domain.conversion_table("m", "kg", 0, 10, 1)

    def test_unknown_unit_rejected(self):
        with self.assertRaises(ValueError):
            domain.conversion_table("zorp", "m", 0, 10, 1)


class TestDomainCompound(unittest.TestCase):
    def test_time_breakdown(self):
        parts, cat = domain.to_compound(3661, "s", ["h", "min", "s"])
        self.assertEqual(cat, "time")
        self.assertEqual([(p["unit"], p["value"]) for p in parts],
                         [("h", 1.0), ("min", 1.0), ("s", 1.0)])

    def test_length_feet_inches(self):
        # 1.855 m -> 6 ft and the remainder in inches.
        parts, cat = domain.to_compound(1.855, "m", ["ft", "in"])
        self.assertEqual(cat, "length")
        self.assertEqual(parts[0]["unit"], "ft")
        self.assertEqual(parts[0]["value"], 6.0)
        self.assertEqual(parts[1]["unit"], "in")
        # 1.855 m - 6 ft = 0.0262 m = 1.0314960629... in
        self.assertAlmostEqual(parts[1]["value"], 1.0314960629921264, places=6)

    def test_parts_sum_back_to_original(self):
        parts, _ = domain.to_compound(3661, "s", ["h", "min", "s"])
        total, _ = (0.0, None)
        for p in parts:
            v, _ = domain.convert_units(p["value"], p["unit"], "s")
            total += v
        self.assertAlmostEqual(total, 3661.0, places=6)

    def test_unordered_units_are_sorted_largest_first(self):
        # Caller passes smallest-first; output must still be h, min, s.
        parts, _ = domain.to_compound(3661, "s", ["s", "min", "h"])
        self.assertEqual([p["unit"] for p in parts], ["h", "min", "s"])

    def test_single_unit_is_plain_conversion(self):
        parts, _ = domain.to_compound(2, "h", ["min"])
        self.assertEqual(len(parts), 1)
        self.assertAlmostEqual(parts[0]["value"], 120.0, places=6)

    def test_negative_keeps_sign_on_every_part(self):
        parts, _ = domain.to_compound(-3661, "s", ["h", "min", "s"])
        self.assertEqual([(p["unit"], p["value"]) for p in parts],
                         [("h", -1.0), ("min", -1.0), ("s", -1.0)])

    def test_value_smaller_than_largest_unit(self):
        # 50 s -> 0 min, 50 s.
        parts, _ = domain.to_compound(50, "s", ["min", "s"])
        self.assertEqual(parts[0]["value"], 0.0)
        self.assertAlmostEqual(parts[1]["value"], 50.0, places=6)

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.to_compound(100, "c", ["f"])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.to_compound(30, "mpg", ["l/100km"])

    def test_empty_units_rejected(self):
        with self.assertRaises(ValueError):
            domain.to_compound(1, "m", [])

    def test_non_list_units_rejected(self):
        with self.assertRaises(ValueError):
            domain.to_compound(1, "m", "ft")

    def test_cross_category_unit_rejected(self):
        with self.assertRaises(ValueError):
            domain.to_compound(1, "m", ["ft", "kg"])

    def test_unknown_from_unit_rejected(self):
        with self.assertRaises(ValueError):
            domain.to_compound(1, "zorp", ["m"])

    def test_unknown_target_unit_rejected(self):
        with self.assertRaises(ValueError):
            domain.to_compound(1, "m", ["zorp"])

    def test_nonfinite_value_rejected(self):
        with self.assertRaises(ValueError):
            domain.to_compound(float("inf"), "m", ["m"])

    def test_format_compound_drops_leading_zero(self):
        parts = [{"unit": "ft", "value": 0}, {"unit": "in", "value": 5}]
        self.assertEqual(domain.format_compound(parts), "5 in")

    def test_format_compound_all_parts(self):
        parts = [{"unit": "h", "value": 1}, {"unit": "min", "value": 30}]
        self.assertEqual(domain.format_compound(parts), "1 h 30 min")

    def test_format_compound_all_zero_keeps_smallest(self):
        parts = [{"unit": "ft", "value": 0}, {"unit": "in", "value": 0}]
        self.assertEqual(domain.format_compound(parts), "0 in")

    def test_format_compound_renders_fraction(self):
        parts = [{"unit": "ft", "value": 6}, {"unit": "in", "value": 0.83}]
        self.assertEqual(domain.format_compound(parts), "6 ft 0.83 in")


class TestDomainCapacitance(unittest.TestCase):
    def test_category(self):
        self.assertEqual(domain.category_of("farad"), "capacitance")
        self.assertEqual(domain.category_of("uf"), "capacitance")
        self.assertEqual(domain.category_of("pF"), "capacitance")

    def test_farad_to_microfarad(self):
        result, cat = domain.convert_units(1, "farad", "uf")
        self.assertEqual(cat, "capacitance")
        self.assertAlmostEqual(result, 1_000_000.0, places=6)

    def test_nanofarad_to_picofarad(self):
        result, _ = domain.convert_units(1, "nf", "pf")
        self.assertAlmostEqual(result, 1000.0, places=6)

    def test_aliases(self):
        a, _ = domain.convert_units(2, "microfarad", "millifarad")
        b, _ = domain.convert_units(2, "uf", "mf")
        self.assertAlmostEqual(a, b, places=12)

    def test_farad_not_faraday(self):
        # CHARGE owns 'faraday' (~96485 C); capacitance must not swallow it.
        self.assertEqual(domain.category_of("faraday"), "charge")
        self.assertEqual(domain.category_of("farad"), "capacitance")


class TestDomainInductance(unittest.TestCase):
    def test_category(self):
        self.assertEqual(domain.category_of("henry"), "inductance")
        self.assertEqual(domain.category_of("mh"), "inductance")

    def test_henry_to_millihenry(self):
        result, cat = domain.convert_units(1, "henry", "mh")
        self.assertEqual(cat, "inductance")
        self.assertAlmostEqual(result, 1000.0, places=6)

    def test_microhenry_to_nanohenry(self):
        result, _ = domain.convert_units(1, "uh", "nh")
        self.assertAlmostEqual(result, 1000.0, places=6)

    def test_plural_alias(self):
        self.assertEqual(domain.category_of("henries"), "inductance")


class TestDomainConductance(unittest.TestCase):
    def test_category(self):
        self.assertEqual(domain.category_of("siemens"), "conductance")
        self.assertEqual(domain.category_of("mho"), "conductance")

    def test_siemens_equals_mho(self):
        result, cat = domain.convert_units(7, "siemens", "mho")
        self.assertEqual(cat, "conductance")
        self.assertAlmostEqual(result, 7.0, places=12)

    def test_millisiemens(self):
        result, _ = domain.convert_units(1, "siemens", "millisiemens")
        self.assertAlmostEqual(result, 1000.0, places=6)

    def test_no_short_ms_collision(self):
        # 'ms' must stay milliseconds (time), never millisiemens.
        self.assertEqual(domain.category_of("ms"), "time")


class TestDomainLuminousFlux(unittest.TestCase):
    def test_category(self):
        self.assertEqual(domain.category_of("lm"), "luminousflux")
        self.assertEqual(domain.category_of("lumen"), "luminousflux")

    def test_lumen_to_kilolumen(self):
        result, cat = domain.convert_units(2500, "lm", "klm")
        self.assertEqual(cat, "luminousflux")
        self.assertAlmostEqual(result, 2.5, places=6)

    def test_distinct_from_illuminance(self):
        # lux (lumens/m^2) is a different category than total luminous flux.
        self.assertEqual(domain.category_of("lux"), "illuminance")
        with self.assertRaises(ValueError):
            domain.convert_units(1, "lm", "lux")


class TestDomainFlow(unittest.TestCase):
    def test_category(self):
        self.assertEqual(domain.category_of("l/s"), "flow")
        self.assertEqual(domain.category_of("gpm"), "flow")
        self.assertEqual(domain.category_of("cfm"), "flow")

    def test_m3h_to_ls(self):
        # 3600 m3/h == 1000 L/s.
        result, cat = domain.convert_units(3600, "m3/h", "l/s")
        self.assertEqual(cat, "flow")
        self.assertAlmostEqual(result, 1000.0, places=6)

    def test_lpm_to_ls(self):
        result, _ = domain.convert_units(60, "l/min", "l/s")
        self.assertAlmostEqual(result, 1.0, places=9)

    def test_us_gpm_to_lpm(self):
        # 1 US gallon == 3.785411784 L, so 1 gpm == 3.785411784 L/min.
        result, _ = domain.convert_units(1, "gpm", "l/min")
        self.assertAlmostEqual(result, 3.785411784, places=9)

    def test_cfm_to_ls(self):
        # 1 ft^3 == 28.316846592 L, /60 -> 0.4719474432 L/s.
        result, _ = domain.convert_units(1, "cfm", "l/s")
        self.assertAlmostEqual(result, 0.4719474432, places=9)

    def test_m3_token_not_swallowed(self):
        # bare 'm3' stays a volume unit; only 'm3/...' forms are flow.
        self.assertEqual(domain.category_of("m3"), "volume")
        self.assertEqual(domain.category_of("m3/s"), "flow")


class TestDomainNewHumanizeLadders(unittest.TestCase):
    def test_capacitance_autoscale(self):
        value, unit, cat = domain.humanize(0.0000015, "farad")
        self.assertEqual(cat, "capacitance")
        self.assertEqual(unit, "uf")
        self.assertAlmostEqual(value, 1.5, places=9)

    def test_inductance_autoscale(self):
        value, unit, _ = domain.humanize(0.002, "henry")
        self.assertEqual(unit, "mh")
        self.assertAlmostEqual(value, 2.0, places=9)

    def test_luminousflux_autoscale(self):
        value, unit, _ = domain.humanize(5000, "lm")
        self.assertEqual(unit, "klm")
        self.assertAlmostEqual(value, 5.0, places=9)


class TestDomainCompare(unittest.TestCase):
    def test_linear_a_larger(self):
        cmp = domain.compare_quantities(1, "km", 800, "m")
        self.assertEqual(cmp["category"], "length")
        self.assertEqual(cmp["larger"], "a")
        self.assertAlmostEqual(cmp["b_in_a_unit"], 0.8, places=9)
        self.assertAlmostEqual(cmp["a_in_b_unit"], 1000.0, places=6)
        self.assertAlmostEqual(cmp["ratio"], 1.25, places=9)
        self.assertAlmostEqual(cmp["difference"], 0.2, places=9)

    def test_linear_b_larger(self):
        cmp = domain.compare_quantities(500, "m", 1, "km")
        self.assertEqual(cmp["larger"], "b")

    def test_equal(self):
        cmp = domain.compare_quantities(1000, "m", 1, "km")
        self.assertEqual(cmp["larger"], "equal")
        self.assertAlmostEqual(cmp["difference"], 0.0, places=9)
        self.assertAlmostEqual(cmp["ratio"], 1.0, places=9)

    def test_temperature_compare(self):
        # 100 C vs 200 K: 200 K == -73.15 C, so the Celsius quantity is larger.
        cmp = domain.compare_quantities(100, "c", 200, "k")
        self.assertEqual(cmp["category"], "temperature")
        self.assertEqual(cmp["larger"], "a")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.compare_quantities(1, "m", 1, "kg")

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.compare_quantities(1, "m", 1, "zorp")

    def test_zero_b_ratio_none(self):
        cmp = domain.compare_quantities(5, "m", 0, "m")
        self.assertIsNone(cmp["ratio"])
        self.assertEqual(cmp["larger"], "a")


# --------------------------------------------------------------------------- #
# Legacy helpers preserved in server.py
# --------------------------------------------------------------------------- #
class TestLegacyHelpers(unittest.TestCase):
    def test_meters_to_feet(self):
        self.assertAlmostEqual(server.meters_to_feet(1), 3.280839895, places=6)

    def test_feet_to_meters(self):
        self.assertAlmostEqual(server.feet_to_meters(1), 0.3048, places=9)

    def test_convert_m2f(self):
        result, unit = server.convert(2, "m2f")
        self.assertAlmostEqual(result, 6.56167979, places=6)
        self.assertEqual(unit, "ft")

    def test_convert_f2m(self):
        result, unit = server.convert(10, "f2m")
        self.assertAlmostEqual(result, 3.048, places=6)
        self.assertEqual(unit, "m")

    def test_convert_invalid_direction(self):
        with self.assertRaises(ValueError):
            server.convert(1, "sideways")


# --------------------------------------------------------------------------- #
# Requirements traceability — every functional REQ id from the spec is
# exercised here so the coverage gate can trace spec -> test.
#   REQ-001: convert between meters
#   REQ-002: feet, both directions
# (see specs/unit-converter-convert-between-2/spec.md)
# --------------------------------------------------------------------------- #
class TestRequirementsTraceability(unittest.TestCase):
    """Traces each EARS requirement to a concrete, executed assertion."""

    def test_req_001_meters_to_feet_happy(self):
        """REQ-001 / TC-1.1 — the system converts a length expressed in meters
        to feet (1 m == 3.280839895 ft)."""
        self.assertAlmostEqual(server.meters_to_feet(1), 3.280839895, places=6)
        result, unit = server.convert(2, "m2f")
        self.assertAlmostEqual(result, 6.56167979, places=6)
        self.assertEqual(unit, "ft")
        # General domain path agrees with the legacy meters->feet helper.
        domain_ft, _ = domain.convert_units(1, "m", "ft")
        self.assertAlmostEqual(domain_ft,
                               server.meters_to_feet(1), places=9)

    def test_req_001_meters_edge_invalid(self):
        """REQ-001 / TC-1.2 — an unknown source unit fails safe with an error."""
        with self.assertRaises(ValueError):
            domain.convert_units(1, "notaunit", "ft")

    def test_req_002_feet_to_meters_happy(self):
        """REQ-002 / TC-2.1 — feet convert back to meters (the reverse
        direction): 10 ft == 3.048 m."""
        self.assertAlmostEqual(server.feet_to_meters(10), 3.048, places=9)
        result, unit = server.convert(10, "f2m")
        self.assertAlmostEqual(result, 3.048, places=6)
        self.assertEqual(unit, "m")
        domain_m, _ = domain.convert_units(10, "ft", "m")
        self.assertAlmostEqual(domain_m,
                               server.feet_to_meters(10), places=9)

    def test_req_002_both_directions_roundtrip(self):
        """REQ-002 / TC-2.1 — both directions are supported and invert each
        other: m -> ft -> m returns the original value."""
        meters = 12.5
        feet, _ = server.convert(meters, "m2f")
        back, _ = server.convert(feet, "f2m")
        self.assertAlmostEqual(back, meters, places=9)

    def test_req_002_invalid_direction_edge(self):
        """REQ-002 / TC-2.2 — an unsupported direction fails safe."""
        with self.assertRaises(ValueError):
            server.convert(1, "sideways")


# --------------------------------------------------------------------------- #
# Live HTTP API
# --------------------------------------------------------------------------- #
class TestHttpApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def _get(self, path):
        with urllib.request.urlopen(self._url(path)) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type")

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url(path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, payload

    # --- GET routes ---
    def test_index(self):
        status, body, ctype = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"Unit Converter", body)

    def test_health(self):
        status, _, _ = self._get("/api/health")
        self.assertEqual(status, 200)

    def test_units_endpoint(self):
        with urllib.request.urlopen(self._url("/api/units")) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertIn("categories", data)
        self.assertIn("area", data["categories"])
        self.assertIn("ft", data["categories"]["length"])

    def test_categories_endpoint(self):
        with urllib.request.urlopen(self._url("/api/categories")) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertIn("speed", data["categories"])
        self.assertIn("digital", data["categories"])

    def test_get_unknown_404(self):
        try:
            self._get("/nope")
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)
            exc.close()

    # --- legacy POST path ---
    def test_convert_legacy_m2f(self):
        status, data = self._post("/api/convert", {"value": 1, "direction": "m2f"})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["result"], 3.2808, places=4)
        self.assertEqual(data["unit"], "ft")

    def test_convert_legacy_f2m(self):
        status, data = self._post("/api/convert", {"value": 10, "direction": "f2m"})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["result"], 3.048, places=4)
        self.assertEqual(data["unit"], "m")

    def test_convert_legacy_bad_direction(self):
        status, data = self._post("/api/convert", {"value": 1, "direction": "x"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- general POST path ---
    def test_convert_general_length(self):
        status, data = self._post("/api/convert", {"value": 1, "from": "km", "to": "mi"})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertAlmostEqual(data["result"], 0.621371, places=5)

    def test_convert_general_temperature(self):
        status, data = self._post("/api/convert", {"value": 100, "from": "c", "to": "f"})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "temperature")
        self.assertAlmostEqual(data["result"], 212.0, places=4)

    def test_convert_general_digital(self):
        status, data = self._post("/api/convert", {"value": 1, "from": "kib", "to": "b"})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "digital")
        self.assertAlmostEqual(data["result"], 1024.0, places=4)

    def test_convert_general_cross_category(self):
        status, data = self._post("/api/convert", {"value": 1, "from": "m", "to": "kg"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_convert_general_missing_field(self):
        status, data = self._post("/api/convert", {"value": 1, "from": "m"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_convert_general_unknown_unit(self):
        status, data = self._post("/api/convert", {"value": 1, "from": "m", "to": "xyz"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_convert_invalid_json(self):
        status, data = self._post("/api/convert", None, raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_convert_general_fuel(self):
        status, data = self._post("/api/convert", {"value": 30, "from": "mpg", "to": "l/100km"})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "fuel")
        self.assertAlmostEqual(data["result"], 235.214583 / 30.0, places=4)

    def test_post_unknown_path_404(self):
        status, data = self._post("/api/nope", {"x": 1})
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    # --- /api/unit-info (GET) ---
    def test_unit_info_known(self):
        with urllib.request.urlopen(self._url("/api/unit-info?unit=ft")) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data["category"], "length")
        self.assertIn("foot", data["aliases"])

    def test_unit_info_missing_param(self):
        try:
            self._get("/api/unit-info")
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)
            exc.close()

    def test_unit_info_unknown_unit(self):
        try:
            self._get("/api/unit-info?unit=zorp")
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)
            exc.close()

    # --- /api/factor (GET) ---
    def test_factor_ok(self):
        with urllib.request.urlopen(self._url("/api/factor?from=km&to=m")) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data["category"], "length")
        self.assertAlmostEqual(data["factor"], 1000.0, places=6)

    def test_factor_datarate(self):
        with urllib.request.urlopen(self._url("/api/factor?from=mbps&to=kbps")) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data["category"], "datarate")
        self.assertAlmostEqual(data["factor"], 1000.0, places=6)

    def test_factor_missing_param(self):
        try:
            self._get("/api/factor?from=km")
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)
            exc.close()

    def test_factor_temperature_400(self):
        try:
            self._get("/api/factor?from=c&to=f")
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)
            exc.close()

    def test_factor_cross_category_400(self):
        try:
            self._get("/api/factor?from=m&to=kg")
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)
            exc.close()

    # --- data-rate over the general convert path ---
    def test_convert_general_datarate(self):
        status, data = self._post("/api/convert", {"value": 1, "from": "gbps", "to": "mbps"})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "datarate")
        self.assertAlmostEqual(data["result"], 1000.0, places=4)

    def test_units_endpoint_has_datarate(self):
        with urllib.request.urlopen(self._url("/api/units")) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertIn("datarate", data["categories"])
        self.assertIn("mbps", data["categories"]["datarate"])

    # --- /api/parse (POST) ---
    def test_parse_endpoint_ok(self):
        status, data = self._post("/api/parse", {"expression": "10 km to mi"})
        self.assertEqual(status, 200)
        self.assertEqual(data["from"], "km")
        self.assertEqual(data["to"], "mi")
        self.assertEqual(data["category"], "length")
        self.assertAlmostEqual(data["result"], 6.213712, places=5)

    def test_parse_endpoint_fuel(self):
        status, data = self._post("/api/parse", {"expression": "30 mpg to l/100km"})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "fuel")
        self.assertAlmostEqual(data["result"], 235.214583 / 30.0, places=4)

    def test_parse_endpoint_missing_expression(self):
        status, data = self._post("/api/parse", {})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_parse_endpoint_unparseable(self):
        status, data = self._post("/api/parse", {"expression": "gibberish"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_parse_endpoint_bad_units(self):
        status, data = self._post("/api/parse", {"expression": "1 m to kg"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/humanize (POST) ---
    def test_humanize_endpoint_ok(self):
        status, data = self._post("/api/humanize", {"value": 1500, "from": "m"})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "km")
        self.assertAlmostEqual(data["value"], 1.5, places=6)

    def test_humanize_endpoint_scale_down(self):
        status, data = self._post("/api/humanize", {"value": 0.005, "from": "m"})
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "mm")
        self.assertAlmostEqual(data["value"], 5.0, places=6)

    def test_humanize_endpoint_precision(self):
        status, data = self._post("/api/humanize", {"value": 1234, "from": "g", "precision": 2})
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "kg")
        self.assertEqual(data["value"], 1.23)

    def test_humanize_endpoint_missing_field(self):
        status, data = self._post("/api/humanize", {"value": 1})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_humanize_endpoint_unsupported_category(self):
        status, data = self._post("/api/humanize", {"value": 100, "from": "c"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/search (GET) ---
    def test_search_endpoint_ok(self):
        with urllib.request.urlopen(self._url("/api/search?q=lux")) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tokens = {m["unit"] for m in data["matches"]}
        self.assertIn("lux", tokens)

    def test_search_endpoint_categories(self):
        with urllib.request.urlopen(self._url("/api/search?q=met")) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(any(m["unit"] == "meter" for m in data["matches"]))

    def test_search_endpoint_empty_query_400(self):
        try:
            self._get("/api/search?q=")
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)
            exc.close()

    def test_search_endpoint_missing_param_400(self):
        try:
            self._get("/api/search")
            self.fail("expected HTTPError")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)
            exc.close()

    # --- /api/convert-all (POST) ---
    def test_convert_all_endpoint_ok(self):
        status, data = self._post("/api/convert-all", {"value": 1, "from": "m"})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        units = {r["unit"] for r in data["results"]}
        self.assertIn("ft", units)
        self.assertIn("km", units)

    def test_convert_all_endpoint_charge(self):
        status, data = self._post("/api/convert-all", {"value": 1, "from": "ah"})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "charge")
        coulomb = next(r["result"] for r in data["results"] if r["unit"] == "coulomb")
        self.assertAlmostEqual(coulomb, 3600.0, places=4)

    def test_convert_all_endpoint_missing_field(self):
        status, data = self._post("/api/convert-all", {"value": 1})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_convert_all_endpoint_unknown_unit(self):
        status, data = self._post("/api/convert-all", {"value": 1, "from": "zorp"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/convert-batch (POST) ---
    def test_convert_batch_endpoint_ok(self):
        status, data = self._post("/api/convert-batch", {"conversions": [
            {"value": 1, "from": "km", "to": "m"},
            {"value": 100, "from": "c", "to": "f"},
        ]})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["results"]), 2)
        self.assertAlmostEqual(data["results"][0]["result"], 1000.0, places=4)
        self.assertAlmostEqual(data["results"][1]["result"], 212.0, places=4)

    def test_convert_batch_endpoint_mixed_errors(self):
        # A bad entry yields an error object in place without failing the batch.
        status, data = self._post("/api/convert-batch", {"conversions": [
            {"value": 1, "from": "m", "to": "ft"},
            {"value": 1, "from": "m", "to": "kg"},
        ]})
        self.assertEqual(status, 200)
        self.assertNotIn("error", data["results"][0])
        self.assertIn("error", data["results"][1])

    def test_convert_batch_endpoint_not_a_list(self):
        status, data = self._post("/api/convert-batch", {"conversions": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_units_endpoint_has_new_categories(self):
        with urllib.request.urlopen(self._url("/api/units")) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self.assertIn("illuminance", data["categories"])
        self.assertIn("charge", data["categories"])
        self.assertIn("lux", data["categories"]["illuminance"])

    # --- /api/convert-table (POST) ---
    def test_convert_table_endpoint_ok(self):
        status, data = self._post("/api/convert-table", {
            "from": "km", "to": "m", "start": 0, "stop": 3, "step": 1})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["count"], 4)
        self.assertEqual(data["rows"][0], {"input": 0.0, "result": 0.0})
        self.assertEqual(data["rows"][3], {"input": 3.0, "result": 3000.0})

    def test_convert_table_endpoint_temperature(self):
        status, data = self._post("/api/convert-table", {
            "from": "c", "to": "f", "start": 0, "stop": 100, "step": 50})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "temperature")
        self.assertAlmostEqual(data["rows"][0]["result"], 32.0, places=4)
        self.assertAlmostEqual(data["rows"][2]["result"], 212.0, places=4)

    def test_convert_table_endpoint_missing_field(self):
        status, data = self._post("/api/convert-table", {
            "from": "km", "to": "m", "start": 0, "stop": 3})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_convert_table_endpoint_bad_step(self):
        status, data = self._post("/api/convert-table", {
            "from": "km", "to": "m", "start": 0, "stop": 3, "step": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_convert_table_endpoint_cross_category(self):
        status, data = self._post("/api/convert-table", {
            "from": "m", "to": "kg", "start": 0, "stop": 3, "step": 1})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/compound (POST) ---
    def test_compound_endpoint_ok(self):
        status, data = self._post("/api/compound", {
            "value": 3661, "from": "s", "units": ["h", "min", "s"]})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "time")
        self.assertEqual([(p["unit"], p["value"]) for p in data["parts"]],
                         [("h", 1.0), ("min", 1.0), ("s", 1.0)])
        self.assertEqual(data["formatted"], "1 h 1 min 1 s")

    def test_compound_endpoint_feet_inches(self):
        status, data = self._post("/api/compound", {
            "value": 1.855, "from": "m", "units": ["ft", "in"], "precision": 2})
        self.assertEqual(status, 200)
        self.assertEqual(data["parts"][0], {"unit": "ft", "value": 6.0})
        self.assertEqual(data["parts"][1]["unit"], "in")
        self.assertAlmostEqual(data["parts"][1]["value"], 1.03, places=2)

    def test_compound_endpoint_missing_field(self):
        status, data = self._post("/api/compound", {"value": 1, "from": "m"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_compound_endpoint_temperature_400(self):
        status, data = self._post("/api/compound", {
            "value": 100, "from": "c", "units": ["f"]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_compound_endpoint_cross_category_400(self):
        status, data = self._post("/api/compound", {
            "value": 1, "from": "m", "units": ["ft", "kg"]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_compound_endpoint_empty_units_400(self):
        status, data = self._post("/api/compound", {
            "value": 1, "from": "m", "units": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- new categories over the general convert path ---
    def test_convert_general_capacitance(self):
        status, data = self._post("/api/convert", {"value": 1, "from": "farad", "to": "uf"})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "capacitance")
        self.assertAlmostEqual(data["result"], 1_000_000.0, places=4)

    def test_convert_general_inductance(self):
        status, data = self._post("/api/convert", {"value": 1, "from": "henry", "to": "mh"})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "inductance")
        self.assertAlmostEqual(data["result"], 1000.0, places=4)

    def test_convert_general_conductance(self):
        status, data = self._post("/api/convert", {"value": 3, "from": "siemens", "to": "mho"})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "conductance")
        self.assertAlmostEqual(data["result"], 3.0, places=6)

    def test_convert_general_luminousflux(self):
        status, data = self._post("/api/convert", {"value": 2000, "from": "lm", "to": "klm"})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "luminousflux")
        self.assertAlmostEqual(data["result"], 2.0, places=6)

    def test_convert_general_flow(self):
        status, data = self._post("/api/convert", {"value": 3600, "from": "m3/h", "to": "l/s"})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "flow")
        self.assertAlmostEqual(data["result"], 1000.0, places=4)

    def test_units_endpoint_includes_new_categories(self):
        with urllib.request.urlopen(self._url("/api/units")) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for cat in ("capacitance", "inductance", "conductance", "luminousflux", "flow"):
            self.assertIn(cat, data["categories"])
        self.assertIn("farad", data["categories"]["capacitance"])
        self.assertIn("gpm", data["categories"]["flow"])

    # --- /api/compare ---
    def test_compare_a_larger(self):
        status, data = self._post("/api/compare", {
            "a": {"value": 1, "unit": "km"}, "b": {"value": 800, "unit": "m"}})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["larger"], "a")
        self.assertAlmostEqual(data["b_in_a_unit"], 0.8, places=6)
        self.assertAlmostEqual(data["ratio"], 1.25, places=6)

    def test_compare_b_larger(self):
        status, data = self._post("/api/compare", {
            "a": {"value": 500, "unit": "m"}, "b": {"value": 1, "unit": "km"}})
        self.assertEqual(status, 200)
        self.assertEqual(data["larger"], "b")

    def test_compare_equal(self):
        status, data = self._post("/api/compare", {
            "a": {"value": 1000, "unit": "m"}, "b": {"value": 1, "unit": "km"}})
        self.assertEqual(status, 200)
        self.assertEqual(data["larger"], "equal")

    def test_compare_precision(self):
        status, data = self._post("/api/compare", {
            "a": {"value": 1, "unit": "mi"}, "b": {"value": 1, "unit": "km"},
            "precision": 2})
        self.assertEqual(status, 200)
        self.assertEqual(data["b_in_a_unit"], round(data["b_in_a_unit"], 2))

    def test_compare_cross_category_400(self):
        status, data = self._post("/api/compare", {
            "a": {"value": 1, "unit": "m"}, "b": {"value": 1, "unit": "kg"}})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_compare_missing_field_400(self):
        status, data = self._post("/api/compare", {"a": {"value": 1, "unit": "m"}})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_compare_bad_shape_400(self):
        status, data = self._post("/api/compare", {"a": 1, "b": 2})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/sum ---
    def test_sum_endpoint_ok(self):
        status, data = self._post("/api/sum", {
            "items": [{"value": 2, "unit": "ft"}, {"value": 30, "unit": "cm"},
                      {"value": 1, "unit": "m"}],
            "to": "m",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["count"], 3)
        self.assertAlmostEqual(data["total"], 2 * 0.3048 + 0.30 + 1.0, places=6)

    def test_sum_endpoint_default_unit_is_first(self):
        status, data = self._post("/api/sum", {
            "items": [{"value": 1, "unit": "kg"}, {"value": 500, "unit": "g"}],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "kg")
        self.assertAlmostEqual(data["total"], 1.5, places=9)

    def test_sum_endpoint_not_a_list_400(self):
        status, data = self._post("/api/sum", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_sum_endpoint_cross_category_400(self):
        status, data = self._post("/api/sum", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_sum_endpoint_temperature_400(self):
        status, data = self._post("/api/sum", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/parse-compound ---
    def test_parse_compound_endpoint_ok(self):
        status, data = self._post("/api/parse-compound", {
            "expression": "6 ft 2 in", "to": "in",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "in")
        self.assertEqual(len(data["parts"]), 2)
        self.assertAlmostEqual(data["total"], 74.0, places=6)

    def test_parse_compound_endpoint_default_target(self):
        status, data = self._post("/api/parse-compound", {
            "expression": "1 h 1 min 1 s",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "s")
        self.assertAlmostEqual(data["total"], 3661.0, places=6)

    def test_parse_compound_endpoint_missing_expression_400(self):
        status, data = self._post("/api/parse-compound", {"to": "m"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_parse_compound_endpoint_unparseable_400(self):
        status, data = self._post("/api/parse-compound", {"expression": "hello"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_parse_compound_roundtrips_compound(self):
        # /api/compound -> /api/parse-compound should preserve the quantity.
        status, comp = self._post("/api/compound", {
            "value": 3661, "from": "s", "units": ["h", "min", "s"],
        })
        self.assertEqual(status, 200)
        status, data = self._post("/api/parse-compound", {
            "expression": comp["formatted"], "to": "s",
        })
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["total"], 3661.0, places=6)

    # --- /api/convert-delta ---
    def test_convert_delta_endpoint_temperature(self):
        status, data = self._post("/api/convert-delta", {
            "value": 10, "from": "c", "to": "f",
        })
        self.assertEqual(status, 200)
        self.assertTrue(data["interval"])
        self.assertAlmostEqual(data["result"], 18.0, places=6)

    def test_convert_delta_endpoint_differs_from_absolute(self):
        delta = self._post("/api/convert-delta",
                           {"value": 10, "from": "c", "to": "f"})[1]["result"]
        absolute = self._post("/api/convert",
                              {"value": 10, "from": "c", "to": "f"})[1]["result"]
        self.assertNotAlmostEqual(delta, absolute, places=3)

    def test_convert_delta_endpoint_linear_matches_convert(self):
        status, data = self._post("/api/convert-delta", {
            "value": 5, "from": "km", "to": "m",
        })
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["result"], 5000.0, places=6)

    def test_convert_delta_endpoint_fuel_400(self):
        status, data = self._post("/api/convert-delta", {
            "value": 30, "from": "mpg", "to": "l/100km",
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_convert_delta_endpoint_missing_field_400(self):
        status, data = self._post("/api/convert-delta", {"value": 10, "from": "c"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/stats ---
    def test_stats_endpoint_ok(self):
        status, data = self._post("/api/stats", {
            "items": [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
                      {"value": 2, "unit": "ft"}],
            "to": "m",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["count"], 3)
        self.assertAlmostEqual(data["sum"], 8.6096, places=4)
        self.assertAlmostEqual(data["mean"], 8.6096 / 3.0, places=4)
        self.assertEqual(data["min"]["index"], 2)
        self.assertEqual(data["max"]["index"], 0)
        self.assertAlmostEqual(data["max"]["value"], 5.0, places=4)
        self.assertAlmostEqual(data["range"], 5.0 - 0.6096, places=4)

    def test_stats_endpoint_default_unit_is_first(self):
        status, data = self._post("/api/stats", {
            "items": [{"value": 1, "unit": "kg"}, {"value": 500, "unit": "g"}],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "kg")
        self.assertAlmostEqual(data["mean"], 0.75, places=6)

    def test_stats_endpoint_precision(self):
        status, data = self._post("/api/stats", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "m"}],
            "precision": 2,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["mean"], round(data["mean"], 2))

    def test_stats_endpoint_not_a_list_400(self):
        status, data = self._post("/api/stats", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_stats_endpoint_cross_category_400(self):
        status, data = self._post("/api/stats", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_stats_endpoint_temperature_400(self):
        status, data = self._post("/api/stats", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_stats_endpoint_empty_400(self):
        status, data = self._post("/api/stats", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class TestDomainSum(unittest.TestCase):
    def test_length_sum(self):
        total, unit, cat = domain.sum_quantities(
            [{"value": 1, "unit": "m"}, {"value": 100, "unit": "cm"}], "m")
        self.assertAlmostEqual(total, 2.0, places=9)
        self.assertEqual(unit, "m")
        self.assertEqual(cat, "length")

    def test_default_target_is_first_unit(self):
        total, unit, _ = domain.sum_quantities(
            [{"value": 1, "unit": "ft"}, {"value": 12, "unit": "in"}])
        self.assertEqual(unit, "ft")
        self.assertAlmostEqual(total, 2.0, places=9)

    def test_tuple_items_accepted(self):
        total, unit, _ = domain.sum_quantities([(1, "kg"), (1000, "g")], "kg")
        self.assertAlmostEqual(total, 2.0, places=9)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.sum_quantities([])

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.sum_quantities("nope")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.sum_quantities([{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}])

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.sum_quantities([{"value": 1, "unit": "frobs"}])

    def test_bad_target_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.sum_quantities([{"value": 1, "unit": "m"}], "kg")

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.sum_quantities([{"value": 1, "unit": "c"}, {"value": 2, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.sum_quantities([{"value": 30, "unit": "mpg"}])

    def test_non_finite_value_raises(self):
        with self.assertRaises(ValueError):
            domain.sum_quantities([{"value": float("inf"), "unit": "m"}])

    def test_missing_value_raises(self):
        with self.assertRaises(ValueError):
            domain.sum_quantities([{"unit": "m"}])


class TestDomainParseCompound(unittest.TestCase):
    def test_feet_inches(self):
        parts, cat = domain.parse_compound("6 ft 2 in")
        self.assertEqual(cat, "length")
        self.assertEqual(parts, [{"value": 6.0, "unit": "ft"},
                                 {"value": 2.0, "unit": "in"}])

    def test_no_spaces(self):
        parts, _ = domain.parse_compound("1h 1min 1s")
        self.assertEqual([p["unit"] for p in parts], ["h", "min", "s"])

    def test_total(self):
        total, unit, cat, parts = domain.compound_total("6 ft 2 in", "in")
        self.assertAlmostEqual(total, 74.0, places=9)
        self.assertEqual(unit, "in")
        self.assertEqual(cat, "length")

    def test_time_total(self):
        total, unit, _, _ = domain.compound_total("1 h 1 min 1 s", "s")
        self.assertAlmostEqual(total, 3661.0, places=9)

    def test_inverse_of_format_compound(self):
        parts, _ = domain.to_compound(3661, "s", ["h", "min", "s"])
        text = domain.format_compound(parts)
        total, _, _, _ = domain.compound_total(text, "s")
        self.assertAlmostEqual(total, 3661.0, places=6)

    def test_unparseable_raises(self):
        with self.assertRaises(ValueError):
            domain.parse_compound("hello world")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.parse_compound("")

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            domain.parse_compound(None)

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.parse_compound("3 frobs 2 in")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.parse_compound("6 ft 2 kg")

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.parse_compound("10 c 5 f")


class TestDomainConvertDelta(unittest.TestCase):
    def test_celsius_to_fahrenheit_interval(self):
        result, cat = domain.convert_delta(10, "c", "f")
        self.assertAlmostEqual(result, 18.0, places=9)
        self.assertEqual(cat, "temperature")

    def test_fahrenheit_to_celsius_interval(self):
        result, _ = domain.convert_delta(18, "f", "c")
        self.assertAlmostEqual(result, 10.0, places=9)

    def test_celsius_to_kelvin_interval_is_one_to_one(self):
        result, _ = domain.convert_delta(7.5, "c", "k")
        self.assertAlmostEqual(result, 7.5, places=9)

    def test_zero_interval_has_no_offset(self):
        # The key distinction: a 0-degree CHANGE is 0 in any scale (no +32).
        result, _ = domain.convert_delta(0, "c", "f")
        self.assertAlmostEqual(result, 0.0, places=9)

    def test_differs_from_absolute(self):
        delta, _ = domain.convert_delta(10, "c", "f")
        absolute, _ = domain.convert_units(10, "c", "f")
        self.assertNotAlmostEqual(delta, absolute, places=3)

    def test_linear_matches_convert_units(self):
        delta, _ = domain.convert_delta(5, "km", "m")
        absolute, _ = domain.convert_units(5, "km", "m")
        self.assertAlmostEqual(delta, absolute, places=9)

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.convert_delta(30, "mpg", "l/100km")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.convert_delta(1, "c", "m")

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.convert_delta(1, "c", "frobs")

    def test_non_finite_raises(self):
        with self.assertRaises(ValueError):
            domain.convert_delta(float("nan"), "c", "f")


class TestDomainAggregate(unittest.TestCase):
    def test_basic_length_stats(self):
        stats = domain.aggregate_quantities(
            [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
             {"value": 2, "unit": "ft"}], "m")
        self.assertEqual(stats["category"], "length")
        self.assertEqual(stats["unit"], "m")
        self.assertEqual(stats["count"], 3)
        # 5 m + 3 m + 0.6096 m
        self.assertAlmostEqual(stats["sum"], 8.6096, places=6)
        self.assertAlmostEqual(stats["mean"], 8.6096 / 3.0, places=6)

    def test_min_and_max_with_indices(self):
        stats = domain.aggregate_quantities(
            [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
             {"value": 2, "unit": "ft"}], "m")
        # smallest is 2 ft (0.6096 m) at index 2; largest is 5 m at index 0.
        self.assertEqual(stats["min"]["index"], 2)
        self.assertAlmostEqual(stats["min"]["value"], 0.6096, places=6)
        self.assertEqual(stats["max"]["index"], 0)
        self.assertAlmostEqual(stats["max"]["value"], 5.0, places=6)
        self.assertAlmostEqual(stats["range"], 5.0 - 0.6096, places=6)

    def test_default_target_is_first_unit(self):
        stats = domain.aggregate_quantities(
            [{"value": 1, "unit": "kg"}, {"value": 500, "unit": "g"}])
        self.assertEqual(stats["unit"], "kg")
        self.assertAlmostEqual(stats["sum"], 1.5, places=9)
        self.assertAlmostEqual(stats["mean"], 0.75, places=9)

    def test_tuple_items_accepted(self):
        stats = domain.aggregate_quantities([(1, "kg"), (1000, "g")], "kg")
        self.assertEqual(stats["count"], 2)
        self.assertAlmostEqual(stats["sum"], 2.0, places=9)

    def test_single_item(self):
        stats = domain.aggregate_quantities([{"value": 42, "unit": "m"}])
        self.assertEqual(stats["count"], 1)
        self.assertAlmostEqual(stats["mean"], 42.0, places=9)
        self.assertEqual(stats["min"]["index"], 0)
        self.assertEqual(stats["max"]["index"], 0)
        self.assertAlmostEqual(stats["range"], 0.0, places=9)

    def test_sum_matches_sum_quantities(self):
        items = [{"value": 2, "unit": "ft"}, {"value": 30, "unit": "cm"},
                 {"value": 1, "unit": "m"}]
        total, _, _ = domain.sum_quantities(items, "m")
        stats = domain.aggregate_quantities(items, "m")
        self.assertAlmostEqual(stats["sum"], total, places=12)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.aggregate_quantities([])

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.aggregate_quantities("nope")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.aggregate_quantities(
                [{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}])

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.aggregate_quantities([{"value": 1, "unit": "frobs"}])

    def test_bad_target_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.aggregate_quantities([{"value": 1, "unit": "m"}], "kg")

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.aggregate_quantities(
                [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.aggregate_quantities([{"value": 30, "unit": "mpg"}])

    def test_non_finite_value_raises(self):
        with self.assertRaises(ValueError):
            domain.aggregate_quantities([{"value": float("inf"), "unit": "m"}])

    def test_missing_value_raises(self):
        with self.assertRaises(ValueError):
            domain.aggregate_quantities([{"unit": "m"}])


class TestDomainSort(unittest.TestCase):
    def test_ascending_default(self):
        result = domain.sort_quantities(
            [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
             {"value": 2, "unit": "ft"}], "m")
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["count"], 3)
        self.assertFalse(result["descending"])
        # 2 ft (0.6096 m) < 300 cm (3 m) < 5 m
        self.assertEqual([r["index"] for r in result["items"]], [2, 1, 0])
        self.assertAlmostEqual(result["items"][0]["value"], 0.6096, places=6)
        self.assertAlmostEqual(result["items"][2]["value"], 5.0, places=6)

    def test_descending(self):
        result = domain.sort_quantities(
            [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
             {"value": 2, "unit": "ft"}], "m", descending=True)
        self.assertTrue(result["descending"])
        self.assertEqual([r["index"] for r in result["items"]], [0, 1, 2])

    def test_default_target_is_first_unit(self):
        result = domain.sort_quantities(
            [{"value": 1, "unit": "kg"}, {"value": 500, "unit": "g"}])
        self.assertEqual(result["unit"], "kg")
        # 500 g (0.5 kg) < 1 kg
        self.assertEqual([r["index"] for r in result["items"]], [1, 0])

    def test_stable_on_ties_ascending(self):
        # Three equal magnitudes keep their original input order.
        result = domain.sort_quantities(
            [{"value": 100, "unit": "cm"}, {"value": 1, "unit": "m"},
             {"value": 1000, "unit": "mm"}], "m")
        self.assertEqual([r["index"] for r in result["items"]], [0, 1, 2])

    def test_stable_on_ties_descending(self):
        # Stable even descending: equal magnitudes are NOT flipped.
        result = domain.sort_quantities(
            [{"value": 100, "unit": "cm"}, {"value": 1, "unit": "m"},
             {"value": 1000, "unit": "mm"}], "m", descending=True)
        self.assertEqual([r["index"] for r in result["items"]], [0, 1, 2])

    def test_tuple_items_accepted(self):
        result = domain.sort_quantities([(1, "kg"), (1000, "g")], "kg")
        self.assertEqual(result["count"], 2)

    def test_single_item(self):
        result = domain.sort_quantities([{"value": 42, "unit": "m"}])
        self.assertEqual(result["items"], [{"index": 0, "value": 42.0}])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.sort_quantities([])

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.sort_quantities("nope")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.sort_quantities(
                [{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}])

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.sort_quantities([{"value": 1, "unit": "frobs"}])

    def test_bad_target_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.sort_quantities([{"value": 1, "unit": "m"}], "kg")

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.sort_quantities(
                [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.sort_quantities([{"value": 30, "unit": "mpg"}])

    def test_non_finite_value_raises(self):
        with self.assertRaises(ValueError):
            domain.sort_quantities([{"value": float("inf"), "unit": "m"}])

    def test_missing_value_raises(self):
        with self.assertRaises(ValueError):
            domain.sort_quantities([{"unit": "m"}])


class TestDomainDescribe(unittest.TestCase):
    def test_basic_length_stats(self):
        stats = domain.describe_quantities(
            [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
             {"value": 2, "unit": "ft"}], "m")
        self.assertEqual(stats["category"], "length")
        self.assertEqual(stats["unit"], "m")
        self.assertEqual(stats["count"], 3)
        # 5 m, 3 m, 0.6096 m
        self.assertAlmostEqual(stats["sum"], 8.6096, places=6)
        self.assertAlmostEqual(stats["mean"], 8.6096 / 3.0, places=6)
        # ordered: 0.6096, 3, 5 -> median is the middle value, 3.
        self.assertAlmostEqual(stats["median"], 3.0, places=6)

    def test_median_even_count_averages_two_middle(self):
        stats = domain.describe_quantities(
            [{"value": 1, "unit": "m"}, {"value": 2, "unit": "m"},
             {"value": 3, "unit": "m"}, {"value": 6, "unit": "m"}])
        # ordered: 1, 2, 3, 6 -> median = (2 + 3) / 2 = 2.5
        self.assertAlmostEqual(stats["median"], 2.5, places=9)

    def test_median_unsorted_input(self):
        stats = domain.describe_quantities(
            [{"value": 9, "unit": "m"}, {"value": 1, "unit": "m"},
             {"value": 5, "unit": "m"}])
        self.assertAlmostEqual(stats["median"], 5.0, places=9)

    def test_population_variance_and_stdev(self):
        # Values 2, 4, 4, 4, 5, 5, 7, 9 (m): mean 5, population variance 4,
        # population stdev 2 — the classic textbook example.
        items = [{"value": v, "unit": "m"} for v in (2, 4, 4, 4, 5, 5, 7, 9)]
        stats = domain.describe_quantities(items)
        self.assertAlmostEqual(stats["mean"], 5.0, places=9)
        self.assertAlmostEqual(stats["variance"], 4.0, places=9)
        self.assertAlmostEqual(stats["stdev"], 2.0, places=9)

    def test_sample_variance_and_stdev(self):
        # Same data: sample variance is 32/7 (divides by n-1 = 7).
        items = [{"value": v, "unit": "m"} for v in (2, 4, 4, 4, 5, 5, 7, 9)]
        stats = domain.describe_quantities(items)
        self.assertAlmostEqual(stats["sample_variance"], 32.0 / 7.0, places=9)
        self.assertAlmostEqual(stats["sample_stdev"], (32.0 / 7.0) ** 0.5, places=9)

    def test_single_item_sample_stats_are_none(self):
        stats = domain.describe_quantities([{"value": 42, "unit": "m"}])
        self.assertEqual(stats["count"], 1)
        self.assertAlmostEqual(stats["median"], 42.0, places=9)
        self.assertAlmostEqual(stats["variance"], 0.0, places=9)
        self.assertAlmostEqual(stats["stdev"], 0.0, places=9)
        self.assertIsNone(stats["sample_variance"])
        self.assertIsNone(stats["sample_stdev"])

    def test_min_max_range_match_aggregate(self):
        items = [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
                 {"value": 2, "unit": "ft"}]
        agg = domain.aggregate_quantities(items, "m")
        desc = domain.describe_quantities(items, "m")
        self.assertEqual(desc["min"], agg["min"])
        self.assertEqual(desc["max"], agg["max"])
        self.assertAlmostEqual(desc["range"], agg["range"], places=12)
        self.assertAlmostEqual(desc["sum"], agg["sum"], places=12)
        self.assertAlmostEqual(desc["mean"], agg["mean"], places=12)

    def test_default_target_is_first_unit(self):
        stats = domain.describe_quantities(
            [{"value": 1, "unit": "kg"}, {"value": 500, "unit": "g"}])
        self.assertEqual(stats["unit"], "kg")
        self.assertAlmostEqual(stats["median"], 0.75, places=9)

    def test_tuple_items_accepted(self):
        stats = domain.describe_quantities([(1, "kg"), (1000, "g")], "kg")
        self.assertEqual(stats["count"], 2)
        self.assertAlmostEqual(stats["sum"], 2.0, places=9)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.describe_quantities([])

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.describe_quantities("nope")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.describe_quantities(
                [{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}])

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.describe_quantities([{"value": 1, "unit": "frobs"}])

    def test_bad_target_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.describe_quantities([{"value": 1, "unit": "m"}], "kg")

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.describe_quantities(
                [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.describe_quantities([{"value": 30, "unit": "mpg"}])

    def test_non_finite_value_raises(self):
        with self.assertRaises(ValueError):
            domain.describe_quantities([{"value": float("inf"), "unit": "m"}])

    def test_missing_value_raises(self):
        with self.assertRaises(ValueError):
            domain.describe_quantities([{"unit": "m"}])


class TestDomainShape(unittest.TestCase):
    def _items(self, values, unit="m"):
        return [{"value": v, "unit": unit} for v in values]

    def test_symmetric_skewness_zero(self):
        # A perfectly symmetric set has zero skewness.
        result = domain.shape_quantities(self._items([1, 2, 3, 4, 5]))
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["count"], 5)
        self.assertAlmostEqual(result["mean"], 3.0, places=9)
        self.assertAlmostEqual(result["skewness"], 0.0, places=9)
        self.assertAlmostEqual(result["sample_skewness"], 0.0, places=9)

    def test_symmetric_excess_kurtosis(self):
        # [1,2,3,4,5]: m2=2, m4=6.8 -> excess kurtosis 6.8/4 - 3 = -1.3.
        result = domain.shape_quantities(self._items([1, 2, 3, 4, 5]))
        self.assertAlmostEqual(result["kurtosis"], -1.3, places=9)
        self.assertAlmostEqual(result["sample_kurtosis"], -1.2, places=9)

    def test_right_skewed_positive(self):
        # [0,0,0,4]: hand-computed population skewness 2/sqrt(3).
        result = domain.shape_quantities(self._items([0, 0, 0, 4]))
        self.assertGreater(result["skewness"], 0.0)
        self.assertAlmostEqual(result["skewness"], 1.1547005383792515, places=9)
        self.assertAlmostEqual(result["kurtosis"], -2.0 / 3.0, places=9)

    def test_left_skewed_negative(self):
        # The mirror image of the right-skewed set skews negative.
        result = domain.shape_quantities(self._items([4, 4, 4, 0]))
        self.assertLess(result["skewness"], 0.0)
        self.assertAlmostEqual(result["skewness"], -1.1547005383792515, places=9)

    def test_dimensionless_under_unit_change(self):
        # Skewness/kurtosis are standardised moments -> unchanged by the unit.
        a = domain.shape_quantities(self._items([1, 2, 2, 9]))
        b = domain.shape_quantities(self._items([1, 2, 2, 9]), "cm")
        self.assertAlmostEqual(a["skewness"], b["skewness"], places=9)
        self.assertAlmostEqual(a["kurtosis"], b["kurtosis"], places=9)
        self.assertAlmostEqual(a["sample_skewness"], b["sample_skewness"], places=9)
        self.assertAlmostEqual(a["sample_kurtosis"], b["sample_kurtosis"], places=9)
        # But the mean is restated in the chosen unit (1 m -> 100 cm).
        self.assertAlmostEqual(b["mean"], a["mean"] * 100.0, places=6)

    def test_constant_series_is_undefined(self):
        # A flat series has zero spread -> shape is undefined (None), like r.
        result = domain.shape_quantities(self._items([3, 3, 3, 3]))
        self.assertEqual(result["stdev"], 0.0)
        self.assertIsNone(result["skewness"])
        self.assertIsNone(result["sample_skewness"])
        self.assertIsNone(result["kurtosis"])
        self.assertIsNone(result["sample_kurtosis"])

    def test_sample_skewness_needs_three(self):
        # Two points: population skew is defined, the sample estimator is not.
        result = domain.shape_quantities(self._items([1, 5]))
        self.assertIsNotNone(result["skewness"])
        self.assertIsNone(result["sample_skewness"])
        self.assertIsNone(result["sample_kurtosis"])

    def test_sample_kurtosis_needs_four(self):
        # Three points: sample skew is defined, sample kurtosis is not.
        result = domain.shape_quantities(self._items([1, 2, 9]))
        self.assertIsNotNone(result["sample_skewness"])
        self.assertIsNone(result["sample_kurtosis"])

    def test_mixed_units_restated(self):
        # 100 cm == 1 m, so [1 m, 100 cm, 3 m] behaves like [1, 1, 3].
        result = domain.shape_quantities(
            [{"value": 1, "unit": "m"}, {"value": 100, "unit": "cm"},
             {"value": 3, "unit": "m"}])
        plain = domain.shape_quantities(self._items([1, 1, 3]))
        self.assertAlmostEqual(result["skewness"], plain["skewness"], places=9)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.shape_quantities([])

    def test_non_list_raises(self):
        with self.assertRaises(ValueError):
            domain.shape_quantities("nope")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.shape_quantities(
                [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}])

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.shape_quantities([{"value": v, "unit": "c"} for v in (1, 2, 3)])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.shape_quantities(
                [{"value": v, "unit": "mpg"} for v in (30, 40, 50)])

    def test_nonfinite_raises(self):
        with self.assertRaises(ValueError):
            domain.shape_quantities(
                [{"value": float("inf"), "unit": "m"}, {"value": 2, "unit": "m"}])

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.shape_quantities([{"value": 1, "unit": "zorp"}])


class TestHttpSortAndDescribe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url(path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, payload

    # --- /api/sort ---
    def test_sort_endpoint_ascending(self):
        status, data = self._post("/api/sort", {
            "items": [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
                      {"value": 2, "unit": "ft"}],
            "to": "m",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["count"], 3)
        self.assertFalse(data["descending"])
        self.assertEqual([r["index"] for r in data["items"]], [2, 1, 0])

    def test_sort_endpoint_descending(self):
        status, data = self._post("/api/sort", {
            "items": [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
                      {"value": 2, "unit": "ft"}],
            "to": "m", "descending": True,
        })
        self.assertEqual(status, 200)
        self.assertTrue(data["descending"])
        self.assertEqual([r["index"] for r in data["items"]], [0, 1, 2])

    def test_sort_endpoint_default_unit_is_first(self):
        status, data = self._post("/api/sort", {
            "items": [{"value": 1, "unit": "kg"}, {"value": 500, "unit": "g"}],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "kg")
        self.assertEqual([r["index"] for r in data["items"]], [1, 0])

    def test_sort_endpoint_precision(self):
        status, data = self._post("/api/sort", {
            "items": [{"value": 1, "unit": "ft"}, {"value": 2, "unit": "ft"}],
            "to": "m", "precision": 2,
        })
        self.assertEqual(status, 200)
        for r in data["items"]:
            self.assertEqual(r["value"], round(r["value"], 2))

    def test_sort_endpoint_not_a_list_400(self):
        status, data = self._post("/api/sort", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_sort_endpoint_cross_category_400(self):
        status, data = self._post("/api/sort", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_sort_endpoint_temperature_400(self):
        status, data = self._post("/api/sort", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_sort_endpoint_empty_400(self):
        status, data = self._post("/api/sort", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/describe ---
    def test_describe_endpoint_ok(self):
        status, data = self._post("/api/describe", {
            "items": [{"value": v, "unit": "m"} for v in (2, 4, 4, 4, 5, 5, 7, 9)],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["count"], 8)
        self.assertAlmostEqual(data["mean"], 5.0, places=6)
        self.assertAlmostEqual(data["median"], 4.5, places=6)
        self.assertAlmostEqual(data["variance"], 4.0, places=6)
        self.assertAlmostEqual(data["stdev"], 2.0, places=6)
        self.assertAlmostEqual(data["sample_variance"], 32.0 / 7.0, places=6)

    def test_describe_endpoint_single_item_sample_none(self):
        status, data = self._post("/api/describe", {
            "items": [{"value": 42, "unit": "m"}],
        })
        self.assertEqual(status, 200)
        self.assertIsNone(data["sample_variance"])
        self.assertIsNone(data["sample_stdev"])
        self.assertAlmostEqual(data["stdev"], 0.0, places=9)

    def test_describe_endpoint_default_unit_is_first(self):
        status, data = self._post("/api/describe", {
            "items": [{"value": 1, "unit": "kg"}, {"value": 500, "unit": "g"}],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "kg")
        self.assertAlmostEqual(data["median"], 0.75, places=6)

    def test_describe_endpoint_precision(self):
        status, data = self._post("/api/describe", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "m"}],
            "precision": 2,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["stdev"], round(data["stdev"], 2))

    def test_describe_endpoint_matches_stats_shared_fields(self):
        # /api/describe must agree with /api/stats on every field they share.
        items = [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
                 {"value": 2, "unit": "ft"}]
        _, stats = self._post("/api/stats", {"items": items, "to": "m"})
        _, desc = self._post("/api/describe", {"items": items, "to": "m"})
        for key in ("category", "unit", "count", "sum", "mean", "min", "max", "range"):
            self.assertEqual(desc[key], stats[key], "mismatch on %r" % key)

    def test_describe_endpoint_not_a_list_400(self):
        status, data = self._post("/api/describe", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_describe_endpoint_cross_category_400(self):
        status, data = self._post("/api/describe", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_describe_endpoint_temperature_400(self):
        status, data = self._post("/api/describe", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_describe_endpoint_empty_400(self):
        status, data = self._post("/api/describe", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/shape (POST) ---
    def test_shape_endpoint_ok(self):
        status, data = self._post("/api/shape", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)]})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["count"], 5)
        self.assertAlmostEqual(data["skewness"], 0.0, places=6)
        self.assertAlmostEqual(data["kurtosis"], -1.3, places=6)

    def test_shape_endpoint_to_unit(self):
        status, data = self._post("/api/shape", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 2, 9)],
            "to": "cm"})
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "cm")
        # Standardised moments are unit-independent.
        self.assertAlmostEqual(data["skewness"], 1.097025449, places=6)

    def test_shape_endpoint_precision(self):
        status, data = self._post("/api/shape", {
            "items": [{"value": v, "unit": "m"} for v in (0, 0, 0, 4)],
            "precision": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["skewness"], 1.155)

    def test_shape_endpoint_constant_null(self):
        status, data = self._post("/api/shape", {
            "items": [{"value": 3, "unit": "m"} for _ in range(4)]})
        self.assertEqual(status, 200)
        self.assertIsNone(data["skewness"])
        self.assertIsNone(data["kurtosis"])

    def test_shape_endpoint_sample_null_small_n(self):
        status, data = self._post("/api/shape", {
            "items": [{"value": 1, "unit": "m"}, {"value": 5, "unit": "m"}]})
        self.assertEqual(status, 200)
        self.assertIsNone(data["sample_skewness"])
        self.assertIsNone(data["sample_kurtosis"])

    def test_shape_endpoint_missing_items_400(self):
        status, data = self._post("/api/shape", {})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_shape_endpoint_cross_category_400(self):
        status, data = self._post("/api/shape", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_shape_endpoint_empty_400(self):
        status, data = self._post("/api/shape", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class TestDomainCumulative(unittest.TestCase):
    def test_running_total(self):
        result = domain.cumulative_quantities(
            [{"value": 5, "unit": "km"}, {"value": 3, "unit": "km"},
             {"value": 2, "unit": "km"}], "km")
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["unit"], "km")
        self.assertEqual(result["count"], 3)
        self.assertAlmostEqual(result["total"], 10.0, places=9)
        self.assertEqual([r["cumulative"] for r in result["items"]], [5.0, 8.0, 10.0])
        self.assertEqual([r["index"] for r in result["items"]], [0, 1, 2])

    def test_mixed_units_restated(self):
        result = domain.cumulative_quantities(
            [{"value": 1, "unit": "m"}, {"value": 100, "unit": "cm"}], "m")
        self.assertEqual([r["value"] for r in result["items"]], [1.0, 1.0])
        self.assertAlmostEqual(result["items"][1]["cumulative"], 2.0, places=9)

    def test_final_cumulative_equals_total(self):
        items = [{"value": 2, "unit": "ft"}, {"value": 30, "unit": "cm"},
                 {"value": 1, "unit": "m"}]
        result = domain.cumulative_quantities(items, "m")
        total, _, _ = domain.sum_quantities(items, "m")
        self.assertAlmostEqual(result["items"][-1]["cumulative"], total, places=12)

    def test_default_target_is_first_unit(self):
        result = domain.cumulative_quantities(
            [{"value": 1, "unit": "kg"}, {"value": 500, "unit": "g"}])
        self.assertEqual(result["unit"], "kg")
        self.assertAlmostEqual(result["items"][1]["cumulative"], 1.5, places=9)

    def test_tuple_items_accepted(self):
        result = domain.cumulative_quantities([(1, "kg"), (1000, "g")], "kg")
        self.assertEqual(result["count"], 2)
        self.assertAlmostEqual(result["total"], 2.0, places=9)

    def test_single_item(self):
        result = domain.cumulative_quantities([{"value": 42, "unit": "m"}])
        self.assertEqual(result["items"],
                         [{"index": 0, "value": 42.0, "cumulative": 42.0}])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.cumulative_quantities([])

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.cumulative_quantities("nope")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.cumulative_quantities(
                [{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}])

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.cumulative_quantities([{"value": 1, "unit": "frobs"}])

    def test_bad_target_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.cumulative_quantities([{"value": 1, "unit": "m"}], "kg")

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.cumulative_quantities(
                [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.cumulative_quantities([{"value": 30, "unit": "mpg"}])

    def test_non_finite_value_raises(self):
        with self.assertRaises(ValueError):
            domain.cumulative_quantities([{"value": float("inf"), "unit": "m"}])

    def test_missing_value_raises(self):
        with self.assertRaises(ValueError):
            domain.cumulative_quantities([{"unit": "m"}])


class TestDomainPercentile(unittest.TestCase):
    def test_zeroth_is_minimum(self):
        result = domain.percentile_quantities(
            [{"value": v, "unit": "m"} for v in (9, 1, 5)], 0)
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["count"], 3)
        self.assertAlmostEqual(result["value"], 1.0, places=9)

    def test_hundredth_is_maximum(self):
        result = domain.percentile_quantities(
            [{"value": v, "unit": "m"} for v in (9, 1, 5)], 100)
        self.assertAlmostEqual(result["value"], 9.0, places=9)

    def test_fiftieth_equals_median(self):
        items = [{"value": v, "unit": "m"} for v in (2, 4, 4, 4, 5, 5, 7, 9)]
        p50 = domain.percentile_quantities(items, 50)["value"]
        median = domain.describe_quantities(items)["median"]
        self.assertAlmostEqual(p50, median, places=12)

    def test_interpolation_between_ranks(self):
        # R-7: for [1, 2, 3, 4] the 90th percentile interpolates to 3.7.
        items = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)]
        result = domain.percentile_quantities(items, 90)
        self.assertAlmostEqual(result["value"], 3.7, places=9)

    def test_mixed_units_restated(self):
        result = domain.percentile_quantities(
            [{"value": 1, "unit": "m"}, {"value": 300, "unit": "cm"}], 100, "m")
        self.assertEqual(result["unit"], "m")
        self.assertAlmostEqual(result["value"], 3.0, places=9)

    def test_default_target_is_first_unit(self):
        result = domain.percentile_quantities(
            [{"value": 1, "unit": "kg"}, {"value": 500, "unit": "g"}], 0)
        self.assertEqual(result["unit"], "kg")
        self.assertAlmostEqual(result["value"], 0.5, places=9)

    def test_percentile_echoed_back(self):
        result = domain.percentile_quantities([{"value": 5, "unit": "m"}], 42)
        self.assertAlmostEqual(result["percentile"], 42.0, places=9)

    def test_single_item(self):
        result = domain.percentile_quantities([{"value": 7, "unit": "m"}], 25)
        self.assertAlmostEqual(result["value"], 7.0, places=9)

    def test_tuple_items_accepted(self):
        result = domain.percentile_quantities([(1, "kg"), (3, "kg")], 50)
        self.assertAlmostEqual(result["value"], 2.0, places=9)

    def test_out_of_range_low_raises(self):
        with self.assertRaises(ValueError):
            domain.percentile_quantities([{"value": 1, "unit": "m"}], -1)

    def test_out_of_range_high_raises(self):
        with self.assertRaises(ValueError):
            domain.percentile_quantities([{"value": 1, "unit": "m"}], 101)

    def test_non_numeric_percentile_raises(self):
        with self.assertRaises(ValueError):
            domain.percentile_quantities([{"value": 1, "unit": "m"}], "abc")

    def test_non_finite_percentile_raises(self):
        with self.assertRaises(ValueError):
            domain.percentile_quantities([{"value": 1, "unit": "m"}], float("nan"))

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.percentile_quantities([], 50)

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.percentile_quantities("nope", 50)

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.percentile_quantities(
                [{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}], 50)

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.percentile_quantities(
                [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}], 50)

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.percentile_quantities([{"value": 30, "unit": "mpg"}], 50)


class TestDomainProportions(unittest.TestCase):
    def test_basic_shares(self):
        result = domain.proportions(
            [{"value": 2, "unit": "m"}, {"value": 4, "unit": "m"},
             {"value": 6, "unit": "m"}], "m")
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["count"], 3)
        self.assertAlmostEqual(result["total"], 12.0, places=9)
        self.assertAlmostEqual(result["items"][0]["fraction"], 2.0 / 12.0, places=9)
        self.assertAlmostEqual(result["items"][2]["percent"], 50.0, places=9)
        self.assertEqual([r["index"] for r in result["items"]], [0, 1, 2])

    def test_fractions_sum_to_one(self):
        result = domain.proportions(
            [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
             {"value": 2, "unit": "ft"}], "m")
        self.assertAlmostEqual(sum(r["fraction"] for r in result["items"]), 1.0, places=9)
        self.assertAlmostEqual(sum(r["percent"] for r in result["items"]), 100.0, places=6)

    def test_mixed_units_restated(self):
        result = domain.proportions(
            [{"value": 1, "unit": "m"}, {"value": 100, "unit": "cm"}], "m")
        # Two equal lengths -> 50% each.
        self.assertAlmostEqual(result["items"][0]["percent"], 50.0, places=9)
        self.assertAlmostEqual(result["items"][1]["percent"], 50.0, places=9)

    def test_default_target_is_first_unit(self):
        result = domain.proportions(
            [{"value": 1, "unit": "kg"}, {"value": 1000, "unit": "g"}])
        self.assertEqual(result["unit"], "kg")
        self.assertAlmostEqual(result["items"][0]["fraction"], 0.5, places=9)

    def test_tuple_items_accepted(self):
        result = domain.proportions([(1, "kg"), (3, "kg")], "kg")
        self.assertAlmostEqual(result["items"][0]["fraction"], 0.25, places=9)

    def test_single_item_is_whole(self):
        result = domain.proportions([{"value": 42, "unit": "m"}])
        self.assertAlmostEqual(result["items"][0]["fraction"], 1.0, places=9)
        self.assertAlmostEqual(result["items"][0]["percent"], 100.0, places=9)

    def test_zero_total_raises(self):
        # 1 m + (-1 m) sums to zero -> a share of nothing is undefined.
        with self.assertRaises(ValueError):
            domain.proportions([{"value": 1, "unit": "m"}, {"value": -1, "unit": "m"}])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.proportions([])

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.proportions("nope")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.proportions(
                [{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}])

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.proportions([{"value": 1, "unit": "frobs"}])

    def test_bad_target_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.proportions([{"value": 1, "unit": "m"}], "kg")

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.proportions(
                [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.proportions([{"value": 30, "unit": "mpg"}])

    def test_non_finite_value_raises(self):
        with self.assertRaises(ValueError):
            domain.proportions([{"value": float("inf"), "unit": "m"}])

    def test_missing_value_raises(self):
        with self.assertRaises(ValueError):
            domain.proportions([{"unit": "m"}])


class TestHttpCumsumPercentileProportions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url(path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, payload

    # --- /api/cumsum ---
    def test_cumsum_endpoint_ok(self):
        status, data = self._post("/api/cumsum", {
            "items": [{"value": 5, "unit": "km"}, {"value": 3, "unit": "km"},
                      {"value": 2, "unit": "km"}],
            "to": "km",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "km")
        self.assertEqual(data["count"], 3)
        self.assertAlmostEqual(data["total"], 10.0, places=6)
        self.assertEqual([r["cumulative"] for r in data["items"]], [5.0, 8.0, 10.0])
        self.assertEqual([r["index"] for r in data["items"]], [0, 1, 2])

    def test_cumsum_endpoint_default_unit_is_first(self):
        status, data = self._post("/api/cumsum", {
            "items": [{"value": 1, "unit": "kg"}, {"value": 500, "unit": "g"}],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "kg")
        self.assertAlmostEqual(data["items"][1]["cumulative"], 1.5, places=6)

    def test_cumsum_endpoint_precision(self):
        status, data = self._post("/api/cumsum", {
            "items": [{"value": 1, "unit": "ft"}, {"value": 2, "unit": "ft"}],
            "to": "m", "precision": 2,
        })
        self.assertEqual(status, 200)
        for r in data["items"]:
            self.assertEqual(r["cumulative"], round(r["cumulative"], 2))

    def test_cumsum_endpoint_not_a_list_400(self):
        status, data = self._post("/api/cumsum", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_cumsum_endpoint_cross_category_400(self):
        status, data = self._post("/api/cumsum", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_cumsum_endpoint_temperature_400(self):
        status, data = self._post("/api/cumsum", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_cumsum_endpoint_empty_400(self):
        status, data = self._post("/api/cumsum", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/percentile ---
    def test_percentile_endpoint_ok(self):
        status, data = self._post("/api/percentile", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)],
            "percentile": 90,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["count"], 4)
        self.assertAlmostEqual(data["percentile"], 90.0, places=6)
        self.assertAlmostEqual(data["value"], 3.7, places=6)

    def test_percentile_endpoint_median_agrees_with_describe(self):
        items = [{"value": v, "unit": "m"} for v in (2, 4, 4, 4, 5, 5, 7, 9)]
        _, p50 = self._post("/api/percentile", {"items": items, "percentile": 50})
        _, desc = self._post("/api/describe", {"items": items})
        self.assertAlmostEqual(p50["value"], desc["median"], places=6)

    def test_percentile_endpoint_default_unit_is_first(self):
        status, data = self._post("/api/percentile", {
            "items": [{"value": 1, "unit": "kg"}, {"value": 500, "unit": "g"}],
            "percentile": 0,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "kg")
        self.assertAlmostEqual(data["value"], 0.5, places=6)

    def test_percentile_endpoint_precision(self):
        status, data = self._post("/api/percentile", {
            "items": [{"value": 1, "unit": "ft"}, {"value": 2, "unit": "ft"}],
            "to": "m", "percentile": 50, "precision": 2,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["value"], round(data["value"], 2))

    def test_percentile_endpoint_missing_percentile_400(self):
        status, data = self._post("/api/percentile", {
            "items": [{"value": 1, "unit": "m"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_percentile_endpoint_out_of_range_400(self):
        status, data = self._post("/api/percentile", {
            "items": [{"value": 1, "unit": "m"}], "percentile": 150,
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_percentile_endpoint_not_a_list_400(self):
        status, data = self._post("/api/percentile", {"items": "nope", "percentile": 50})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_percentile_endpoint_temperature_400(self):
        status, data = self._post("/api/percentile", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}],
            "percentile": 50,
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/proportions ---
    def test_proportions_endpoint_ok(self):
        status, data = self._post("/api/proportions", {
            "items": [{"value": 2, "unit": "m"}, {"value": 4, "unit": "m"},
                      {"value": 6, "unit": "m"}],
            "to": "m",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["count"], 3)
        self.assertAlmostEqual(data["total"], 12.0, places=6)
        self.assertAlmostEqual(data["items"][2]["percent"], 50.0, places=6)
        self.assertEqual([r["index"] for r in data["items"]], [0, 1, 2])

    def test_proportions_endpoint_percentages_sum_to_100(self):
        status, data = self._post("/api/proportions", {
            "items": [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
                      {"value": 2, "unit": "ft"}],
            "to": "m",
        })
        self.assertEqual(status, 200)
        self.assertAlmostEqual(sum(r["percent"] for r in data["items"]), 100.0, places=4)

    def test_proportions_endpoint_default_unit_is_first(self):
        status, data = self._post("/api/proportions", {
            "items": [{"value": 1, "unit": "kg"}, {"value": 1000, "unit": "g"}],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "kg")
        self.assertAlmostEqual(data["items"][0]["fraction"], 0.5, places=6)

    def test_proportions_endpoint_precision(self):
        status, data = self._post("/api/proportions", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "m"}],
            "precision": 2,
        })
        self.assertEqual(status, 200)
        for r in data["items"]:
            self.assertEqual(r["fraction"], round(r["fraction"], 2))

    def test_proportions_endpoint_zero_total_400(self):
        status, data = self._post("/api/proportions", {
            "items": [{"value": 1, "unit": "m"}, {"value": -1, "unit": "m"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_proportions_endpoint_not_a_list_400(self):
        status, data = self._post("/api/proportions", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_proportions_endpoint_cross_category_400(self):
        status, data = self._post("/api/proportions", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_proportions_endpoint_temperature_400(self):
        status, data = self._post("/api/proportions", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_proportions_endpoint_empty_400(self):
        status, data = self._post("/api/proportions", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class TestDomainDifferences(unittest.TestCase):
    def test_successive_deltas(self):
        # Odometer readings -> the distance of each leg (first is the step from 0).
        result = domain.differences(
            [{"value": 10, "unit": "km"}, {"value": 25, "unit": "km"},
             {"value": 40, "unit": "km"}], "km")
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["unit"], "km")
        self.assertEqual(result["count"], 3)
        self.assertEqual([r["difference"] for r in result["items"]], [10.0, 15.0, 15.0])
        self.assertEqual([r["index"] for r in result["items"]], [0, 1, 2])

    def test_total_equals_last_value(self):
        result = domain.differences(
            [{"value": 10, "unit": "km"}, {"value": 25, "unit": "km"}], "km")
        # The differences sum back to the final restated value.
        self.assertAlmostEqual(sum(r["difference"] for r in result["items"]),
                               result["items"][-1]["value"], places=9)
        self.assertAlmostEqual(result["total"], 35.0, places=9)

    def test_inverse_of_cumulative(self):
        # differences(cumsum(series)) reconstructs the original increments.
        series = [{"value": 5, "unit": "km"}, {"value": 3, "unit": "km"},
                  {"value": 2, "unit": "km"}]
        cum = domain.cumulative_quantities(series, "km")
        cum_items = [{"value": r["cumulative"], "unit": "km"} for r in cum["items"]]
        diff = domain.differences(cum_items, "km")
        self.assertEqual([r["difference"] for r in diff["items"]], [5.0, 3.0, 2.0])

    def test_cumsum_of_differences_reconstructs_series(self):
        # And the other direction: cumsum of the differences == the values.
        series = [{"value": 10, "unit": "km"}, {"value": 25, "unit": "km"},
                  {"value": 40, "unit": "km"}]
        diff = domain.differences(series, "km")
        diff_items = [{"value": r["difference"], "unit": "km"} for r in diff["items"]]
        cum = domain.cumulative_quantities(diff_items, "km")
        self.assertEqual([r["cumulative"] for r in cum["items"]], [10.0, 25.0, 40.0])

    def test_mixed_units_restated(self):
        result = domain.differences(
            [{"value": 1, "unit": "m"}, {"value": 150, "unit": "cm"}], "m")
        self.assertAlmostEqual(result["items"][0]["difference"], 1.0, places=9)
        self.assertAlmostEqual(result["items"][1]["difference"], 0.5, places=9)

    def test_negative_difference(self):
        result = domain.differences(
            [{"value": 5, "unit": "m"}, {"value": 2, "unit": "m"}], "m")
        self.assertAlmostEqual(result["items"][1]["difference"], -3.0, places=9)

    def test_default_target_is_first_unit(self):
        result = domain.differences(
            [{"value": 1, "unit": "kg"}, {"value": 1500, "unit": "g"}])
        self.assertEqual(result["unit"], "kg")
        self.assertAlmostEqual(result["items"][1]["difference"], 0.5, places=9)

    def test_tuple_items_accepted(self):
        result = domain.differences([(1, "kg"), (3, "kg")], "kg")
        self.assertEqual(result["count"], 2)
        self.assertAlmostEqual(result["items"][1]["difference"], 2.0, places=9)

    def test_single_item(self):
        result = domain.differences([{"value": 42, "unit": "m"}])
        self.assertEqual(result["items"],
                         [{"index": 0, "value": 42.0, "difference": 42.0}])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.differences([])

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.differences("nope")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.differences(
                [{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}])

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.differences([{"value": 1, "unit": "frobs"}])

    def test_bad_target_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.differences([{"value": 1, "unit": "m"}], "kg")

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.differences(
                [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.differences([{"value": 30, "unit": "mpg"}])

    def test_non_finite_value_raises(self):
        with self.assertRaises(ValueError):
            domain.differences([{"value": float("inf"), "unit": "m"}])

    def test_missing_value_raises(self):
        with self.assertRaises(ValueError):
            domain.differences([{"unit": "m"}])


class TestDomainZScores(unittest.TestCase):
    def test_basic_scores(self):
        # Values 2, 4, 4, 4, 5, 5, 7, 9 (m): mean 5, population stdev 2.
        items = [{"value": v, "unit": "m"} for v in (2, 4, 4, 4, 5, 5, 7, 9)]
        result = domain.zscores(items, "m")
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["count"], 8)
        self.assertAlmostEqual(result["mean"], 5.0, places=9)
        self.assertAlmostEqual(result["stdev"], 2.0, places=9)
        # (2 - 5) / 2 = -1.5 ; (9 - 5) / 2 = 2.0
        self.assertAlmostEqual(result["items"][0]["zscore"], -1.5, places=9)
        self.assertAlmostEqual(result["items"][7]["zscore"], 2.0, places=9)

    def test_scores_have_zero_mean_unit_stdev(self):
        items = [{"value": v, "unit": "m"} for v in (2, 4, 4, 4, 5, 5, 7, 9)]
        result = domain.zscores(items, "m")
        zs = [r["zscore"] for r in result["items"]]
        n = len(zs)
        mean_z = sum(zs) / n
        var_z = sum((z - mean_z) ** 2 for z in zs) / n
        self.assertAlmostEqual(mean_z, 0.0, places=9)
        self.assertAlmostEqual(var_z, 1.0, places=9)

    def test_mean_and_stdev_match_describe(self):
        items = [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
                 {"value": 2, "unit": "ft"}]
        desc = domain.describe_quantities(items, "m")
        result = domain.zscores(items, "m")
        self.assertAlmostEqual(result["mean"], desc["mean"], places=12)
        self.assertAlmostEqual(result["stdev"], desc["stdev"], places=12)

    def test_mixed_units_restated(self):
        result = domain.zscores(
            [{"value": 1, "unit": "m"}, {"value": 300, "unit": "cm"}], "m")
        # Two values 1 and 3 -> mean 2, stdev 1 -> z-scores -1 and +1.
        self.assertAlmostEqual(result["items"][0]["zscore"], -1.0, places=9)
        self.assertAlmostEqual(result["items"][1]["zscore"], 1.0, places=9)

    def test_default_target_is_first_unit(self):
        result = domain.zscores(
            [{"value": 1, "unit": "kg"}, {"value": 3000, "unit": "g"}])
        self.assertEqual(result["unit"], "kg")
        self.assertAlmostEqual(result["items"][0]["zscore"], -1.0, places=9)

    def test_tuple_items_accepted(self):
        result = domain.zscores([(1, "m"), (3, "m")], "m")
        self.assertEqual(result["count"], 2)

    def test_identical_values_raise(self):
        # Zero spread -> z-score undefined.
        with self.assertRaises(ValueError):
            domain.zscores([{"value": 5, "unit": "m"}, {"value": 5, "unit": "m"}])

    def test_single_item_raises(self):
        # One observation has zero spread, so no z-score.
        with self.assertRaises(ValueError):
            domain.zscores([{"value": 42, "unit": "m"}])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.zscores([])

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.zscores("nope")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.zscores([{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}])

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.zscores([{"value": 1, "unit": "frobs"}])

    def test_bad_target_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.zscores([{"value": 1, "unit": "m"}], "kg")

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.zscores([{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.zscores([{"value": 30, "unit": "mpg"}])

    def test_non_finite_value_raises(self):
        with self.assertRaises(ValueError):
            domain.zscores([{"value": float("inf"), "unit": "m"}])

    def test_missing_value_raises(self):
        with self.assertRaises(ValueError):
            domain.zscores([{"unit": "m"}])


class TestDomainNormalize(unittest.TestCase):
    def test_basic_scaling(self):
        result = domain.normalize_quantities(
            [{"value": 2, "unit": "m"}, {"value": 4, "unit": "m"},
             {"value": 6, "unit": "m"}], "m")
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["count"], 3)
        self.assertAlmostEqual(result["min"], 2.0, places=9)
        self.assertAlmostEqual(result["max"], 6.0, places=9)
        # (2-2)/4=0, (4-2)/4=0.5, (6-2)/4=1
        self.assertEqual([r["normalized"] for r in result["items"]], [0.0, 0.5, 1.0])
        self.assertEqual([r["index"] for r in result["items"]], [0, 1, 2])

    def test_min_maps_to_zero_max_to_one(self):
        result = domain.normalize_quantities(
            [{"value": 9, "unit": "m"}, {"value": 1, "unit": "m"},
             {"value": 5, "unit": "m"}], "m")
        self.assertAlmostEqual(result["items"][1]["normalized"], 0.0, places=9)
        self.assertAlmostEqual(result["items"][0]["normalized"], 1.0, places=9)
        self.assertAlmostEqual(result["items"][2]["normalized"], 0.5, places=9)

    def test_mixed_units_restated(self):
        result = domain.normalize_quantities(
            [{"value": 1, "unit": "m"}, {"value": 300, "unit": "cm"}], "m")
        self.assertAlmostEqual(result["items"][0]["normalized"], 0.0, places=9)
        self.assertAlmostEqual(result["items"][1]["normalized"], 1.0, places=9)

    def test_default_target_is_first_unit(self):
        result = domain.normalize_quantities(
            [{"value": 1, "unit": "kg"}, {"value": 3000, "unit": "g"}])
        self.assertEqual(result["unit"], "kg")
        self.assertAlmostEqual(result["items"][0]["normalized"], 0.0, places=9)
        self.assertAlmostEqual(result["items"][1]["normalized"], 1.0, places=9)

    def test_tuple_items_accepted(self):
        result = domain.normalize_quantities([(2, "m"), (6, "m")], "m")
        self.assertEqual(result["count"], 2)
        self.assertAlmostEqual(result["items"][1]["normalized"], 1.0, places=9)

    def test_min_max_match_describe(self):
        items = [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
                 {"value": 2, "unit": "ft"}]
        desc = domain.describe_quantities(items, "m")
        result = domain.normalize_quantities(items, "m")
        self.assertAlmostEqual(result["min"], desc["min"]["value"], places=12)
        self.assertAlmostEqual(result["max"], desc["max"]["value"], places=12)

    def test_identical_values_raise(self):
        with self.assertRaises(ValueError):
            domain.normalize_quantities(
                [{"value": 5, "unit": "m"}, {"value": 5, "unit": "m"}])

    def test_single_item_raises(self):
        # One value has min == max, so a zero range.
        with self.assertRaises(ValueError):
            domain.normalize_quantities([{"value": 42, "unit": "m"}])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.normalize_quantities([])

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.normalize_quantities("nope")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.normalize_quantities(
                [{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}])

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.normalize_quantities([{"value": 1, "unit": "frobs"}])

    def test_bad_target_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.normalize_quantities([{"value": 1, "unit": "m"}], "kg")

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.normalize_quantities(
                [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.normalize_quantities([{"value": 30, "unit": "mpg"}])

    def test_non_finite_value_raises(self):
        with self.assertRaises(ValueError):
            domain.normalize_quantities([{"value": float("inf"), "unit": "m"}])

    def test_missing_value_raises(self):
        with self.assertRaises(ValueError):
            domain.normalize_quantities([{"unit": "m"}])


class TestHttpDiffZscoreNormalize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url(path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, payload

    # --- /api/diff ---
    def test_diff_endpoint_ok(self):
        status, data = self._post("/api/diff", {
            "items": [{"value": 10, "unit": "km"}, {"value": 25, "unit": "km"},
                      {"value": 40, "unit": "km"}],
            "to": "km",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "km")
        self.assertEqual(data["count"], 3)
        # total is the sum of the item values (10 + 25 + 40), as in /api/sum;
        # the sum of the *differences* telescopes to the last value (40).
        self.assertAlmostEqual(data["total"], 75.0, places=6)
        self.assertAlmostEqual(sum(r["difference"] for r in data["items"]), 40.0, places=6)
        self.assertEqual([r["difference"] for r in data["items"]], [10.0, 15.0, 15.0])
        self.assertEqual([r["index"] for r in data["items"]], [0, 1, 2])

    def test_diff_endpoint_inverts_cumsum(self):
        # /api/cumsum then /api/diff returns the original increments.
        items = [{"value": 5, "unit": "km"}, {"value": 3, "unit": "km"},
                 {"value": 2, "unit": "km"}]
        _, cum = self._post("/api/cumsum", {"items": items, "to": "km"})
        cum_items = [{"value": r["cumulative"], "unit": "km"} for r in cum["items"]]
        status, diff = self._post("/api/diff", {"items": cum_items, "to": "km"})
        self.assertEqual(status, 200)
        self.assertEqual([r["difference"] for r in diff["items"]], [5.0, 3.0, 2.0])

    def test_diff_endpoint_default_unit_is_first(self):
        status, data = self._post("/api/diff", {
            "items": [{"value": 1, "unit": "kg"}, {"value": 1500, "unit": "g"}],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "kg")
        self.assertAlmostEqual(data["items"][1]["difference"], 0.5, places=6)

    def test_diff_endpoint_precision(self):
        status, data = self._post("/api/diff", {
            "items": [{"value": 1, "unit": "ft"}, {"value": 2, "unit": "ft"}],
            "to": "m", "precision": 2,
        })
        self.assertEqual(status, 200)
        for r in data["items"]:
            self.assertEqual(r["difference"], round(r["difference"], 2))

    def test_diff_endpoint_not_a_list_400(self):
        status, data = self._post("/api/diff", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_diff_endpoint_cross_category_400(self):
        status, data = self._post("/api/diff", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_diff_endpoint_temperature_400(self):
        status, data = self._post("/api/diff", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_diff_endpoint_empty_400(self):
        status, data = self._post("/api/diff", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/zscore ---
    def test_zscore_endpoint_ok(self):
        status, data = self._post("/api/zscore", {
            "items": [{"value": v, "unit": "m"} for v in (2, 4, 4, 4, 5, 5, 7, 9)],
            "to": "m",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["count"], 8)
        self.assertAlmostEqual(data["mean"], 5.0, places=6)
        self.assertAlmostEqual(data["stdev"], 2.0, places=6)
        self.assertAlmostEqual(data["items"][0]["zscore"], -1.5, places=6)
        self.assertAlmostEqual(data["items"][7]["zscore"], 2.0, places=6)

    def test_zscore_endpoint_agrees_with_describe(self):
        items = [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
                 {"value": 2, "unit": "ft"}]
        _, desc = self._post("/api/describe", {"items": items, "to": "m"})
        _, z = self._post("/api/zscore", {"items": items, "to": "m"})
        self.assertAlmostEqual(z["mean"], desc["mean"], places=6)
        self.assertAlmostEqual(z["stdev"], desc["stdev"], places=6)

    def test_zscore_endpoint_default_unit_is_first(self):
        status, data = self._post("/api/zscore", {
            "items": [{"value": 1, "unit": "kg"}, {"value": 3000, "unit": "g"}],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "kg")
        self.assertAlmostEqual(data["items"][0]["zscore"], -1.0, places=6)

    def test_zscore_endpoint_precision(self):
        status, data = self._post("/api/zscore", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "m"},
                      {"value": 6, "unit": "m"}],
            "precision": 2,
        })
        self.assertEqual(status, 200)
        for r in data["items"]:
            self.assertEqual(r["zscore"], round(r["zscore"], 2))

    def test_zscore_endpoint_identical_values_400(self):
        status, data = self._post("/api/zscore", {
            "items": [{"value": 5, "unit": "m"}, {"value": 5, "unit": "m"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_zscore_endpoint_not_a_list_400(self):
        status, data = self._post("/api/zscore", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_zscore_endpoint_cross_category_400(self):
        status, data = self._post("/api/zscore", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_zscore_endpoint_temperature_400(self):
        status, data = self._post("/api/zscore", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_zscore_endpoint_empty_400(self):
        status, data = self._post("/api/zscore", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/normalize ---
    def test_normalize_endpoint_ok(self):
        status, data = self._post("/api/normalize", {
            "items": [{"value": 2, "unit": "m"}, {"value": 4, "unit": "m"},
                      {"value": 6, "unit": "m"}],
            "to": "m",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["count"], 3)
        self.assertAlmostEqual(data["min"], 2.0, places=6)
        self.assertAlmostEqual(data["max"], 6.0, places=6)
        self.assertEqual([r["normalized"] for r in data["items"]], [0.0, 0.5, 1.0])
        self.assertEqual([r["index"] for r in data["items"]], [0, 1, 2])

    def test_normalize_endpoint_min_max_agree_with_describe(self):
        items = [{"value": 5, "unit": "m"}, {"value": 300, "unit": "cm"},
                 {"value": 2, "unit": "ft"}]
        _, desc = self._post("/api/describe", {"items": items, "to": "m"})
        _, norm = self._post("/api/normalize", {"items": items, "to": "m"})
        self.assertAlmostEqual(norm["min"], desc["min"]["value"], places=6)
        self.assertAlmostEqual(norm["max"], desc["max"]["value"], places=6)

    def test_normalize_endpoint_default_unit_is_first(self):
        status, data = self._post("/api/normalize", {
            "items": [{"value": 1, "unit": "kg"}, {"value": 3000, "unit": "g"}],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "kg")
        self.assertAlmostEqual(data["items"][0]["normalized"], 0.0, places=6)
        self.assertAlmostEqual(data["items"][1]["normalized"], 1.0, places=6)

    def test_normalize_endpoint_precision(self):
        status, data = self._post("/api/normalize", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "m"},
                      {"value": 6, "unit": "m"}],
            "precision": 2,
        })
        self.assertEqual(status, 200)
        for r in data["items"]:
            self.assertEqual(r["normalized"], round(r["normalized"], 2))

    def test_normalize_endpoint_identical_values_400(self):
        status, data = self._post("/api/normalize", {
            "items": [{"value": 5, "unit": "m"}, {"value": 5, "unit": "m"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_normalize_endpoint_not_a_list_400(self):
        status, data = self._post("/api/normalize", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_normalize_endpoint_cross_category_400(self):
        status, data = self._post("/api/normalize", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_normalize_endpoint_temperature_400(self):
        status, data = self._post("/api/normalize", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_normalize_endpoint_empty_400(self):
        status, data = self._post("/api/normalize", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class TestDomainQuartiles(unittest.TestCase):
    def test_five_number_summary(self):
        # 1, 2, 3, 4, 5 (m): min 1, Q1 2, median 3, Q3 4, max 5, IQR 2.
        q = domain.quartiles([{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)])
        self.assertEqual(q["category"], "length")
        self.assertEqual(q["unit"], "m")
        self.assertEqual(q["count"], 5)
        self.assertAlmostEqual(q["min"], 1.0, places=9)
        self.assertAlmostEqual(q["q1"], 2.0, places=9)
        self.assertAlmostEqual(q["median"], 3.0, places=9)
        self.assertAlmostEqual(q["q3"], 4.0, places=9)
        self.assertAlmostEqual(q["max"], 5.0, places=9)
        self.assertAlmostEqual(q["iqr"], 2.0, places=9)

    def test_unsorted_input(self):
        q = domain.quartiles([{"value": v, "unit": "m"} for v in (5, 1, 3, 2, 4)])
        self.assertAlmostEqual(q["median"], 3.0, places=9)
        self.assertAlmostEqual(q["q1"], 2.0, places=9)

    def test_mixed_units_restated(self):
        # 100 cm == 1 m, 200 cm == 2 m, 3 m -> median 2 m.
        q = domain.quartiles(
            [{"value": 100, "unit": "cm"}, {"value": 200, "unit": "cm"},
             {"value": 3, "unit": "m"}], "m")
        self.assertAlmostEqual(q["median"], 2.0, places=9)

    def test_median_matches_describe(self):
        items = [{"value": v, "unit": "m"} for v in (2, 4, 4, 4, 5, 5, 7, 9)]
        q = domain.quartiles(items)
        desc = domain.describe_quantities(items)
        self.assertAlmostEqual(q["median"], desc["median"], places=12)

    def test_quartiles_match_percentile_endpoint(self):
        # Q1/Q3 must equal P25/P75 from percentile_quantities.
        items = [{"value": v, "unit": "m"} for v in (1, 2, 4, 7, 9)]
        q = domain.quartiles(items)
        p25 = domain.percentile_quantities(items, 25)["value"]
        p75 = domain.percentile_quantities(items, 75)["value"]
        self.assertAlmostEqual(q["q1"], p25, places=12)
        self.assertAlmostEqual(q["q3"], p75, places=12)

    def test_single_item(self):
        q = domain.quartiles([{"value": 42, "unit": "m"}])
        self.assertEqual(q["count"], 1)
        for key in ("min", "q1", "median", "q3", "max"):
            self.assertAlmostEqual(q[key], 42.0, places=9)
        self.assertAlmostEqual(q["iqr"], 0.0, places=9)

    def test_default_target_is_first_unit(self):
        q = domain.quartiles([{"value": 1, "unit": "kg"}, {"value": 500, "unit": "g"}])
        self.assertEqual(q["unit"], "kg")

    def test_tuple_items_accepted(self):
        q = domain.quartiles([(1, "kg"), (1000, "g")], "kg")
        self.assertEqual(q["count"], 2)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.quartiles([])

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.quartiles("nope")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.quartiles([{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}])

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.quartiles([{"value": 1, "unit": "frobs"}])

    def test_bad_target_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.quartiles([{"value": 1, "unit": "m"}], "kg")

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.quartiles([{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.quartiles([{"value": 30, "unit": "mpg"}])

    def test_non_finite_value_raises(self):
        with self.assertRaises(ValueError):
            domain.quartiles([{"value": float("inf"), "unit": "m"}])

    def test_missing_value_raises(self):
        with self.assertRaises(ValueError):
            domain.quartiles([{"unit": "m"}])


class TestDomainOutliers(unittest.TestCase):
    def test_flags_high_outlier(self):
        # 10..13 are tight; 90 is far above the upper fence.
        result = domain.outliers(
            [{"value": v, "unit": "m"} for v in (10, 11, 12, 13, 90)])
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["count"], 5)
        self.assertEqual(result["outlier_count"], 1)
        self.assertTrue(result["items"][4]["is_outlier"])
        self.assertFalse(result["items"][0]["is_outlier"])

    def test_no_outliers_in_tight_set(self):
        result = domain.outliers(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)])
        self.assertEqual(result["outlier_count"], 0)
        self.assertTrue(all(not r["is_outlier"] for r in result["items"]))

    def test_fences_from_quartiles(self):
        items = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)]
        result = domain.outliers(items, k=1.5)
        q = domain.quartiles(items)
        self.assertAlmostEqual(result["q1"], q["q1"], places=12)
        self.assertAlmostEqual(result["q3"], q["q3"], places=12)
        self.assertAlmostEqual(result["iqr"], q["iqr"], places=12)
        self.assertAlmostEqual(result["lower_fence"], q["q1"] - 1.5 * q["iqr"], places=12)
        self.assertAlmostEqual(result["upper_fence"], q["q3"] + 1.5 * q["iqr"], places=12)

    def test_k_echoed_and_default(self):
        result = domain.outliers([{"value": v, "unit": "m"} for v in (1, 2, 3)])
        self.assertAlmostEqual(result["k"], 1.5, places=9)

    def test_larger_k_flags_fewer(self):
        items = [{"value": v, "unit": "m"} for v in (10, 11, 12, 13, 40)]
        mild = domain.outliers(items, k=1.5)
        strict = domain.outliers(items, k=3.0)
        self.assertGreaterEqual(mild["outlier_count"], strict["outlier_count"])

    def test_mixed_units_restated(self):
        result = domain.outliers(
            [{"value": 100, "unit": "cm"}, {"value": 1, "unit": "m"}], "m")
        self.assertEqual(result["unit"], "m")
        self.assertAlmostEqual(result["items"][0]["value"], 1.0, places=9)

    def test_negative_k_raises(self):
        with self.assertRaises(ValueError):
            domain.outliers([{"value": 1, "unit": "m"}], k=-1)

    def test_non_finite_k_raises(self):
        with self.assertRaises(ValueError):
            domain.outliers([{"value": 1, "unit": "m"}], k=float("inf"))

    def test_non_numeric_k_raises(self):
        with self.assertRaises(ValueError):
            domain.outliers([{"value": 1, "unit": "m"}], k="big")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.outliers([])

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.outliers("nope")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.outliers([{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}])

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.outliers([{"value": 1, "unit": "frobs"}])

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.outliers([{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.outliers([{"value": 30, "unit": "mpg"}])

    def test_non_finite_value_raises(self):
        with self.assertRaises(ValueError):
            domain.outliers([{"value": float("inf"), "unit": "m"}])


class TestDomainHistogram(unittest.TestCase):
    def test_basic_binning(self):
        # 1..5 m into 4 bins (width 1): each of 1,2,3,4 lands low, 5 in last bin.
        result = domain.histogram(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)], 4)
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["count"], 5)
        self.assertEqual(result["bins"], 4)
        self.assertAlmostEqual(result["min"], 1.0, places=9)
        self.assertAlmostEqual(result["max"], 5.0, places=9)
        self.assertEqual([b["count"] for b in result["items"]], [1, 1, 1, 2])

    def test_counts_sum_to_count(self):
        items = [{"value": v, "unit": "m"} for v in (1, 3, 3, 5, 8, 9, 10)]
        result = domain.histogram(items, 5)
        self.assertEqual(sum(b["count"] for b in result["items"]), result["count"])

    def test_single_bin_holds_all(self):
        result = domain.histogram(
            [{"value": v, "unit": "m"} for v in (1, 2, 3)], 1)
        self.assertEqual(result["items"][0]["count"], 3)
        self.assertAlmostEqual(result["items"][0]["start"], 1.0, places=9)
        self.assertAlmostEqual(result["items"][0]["end"], 3.0, places=9)

    def test_last_bin_closed_on_max(self):
        result = domain.histogram(
            [{"value": v, "unit": "m"} for v in (0, 10)], 5)
        self.assertAlmostEqual(result["items"][-1]["end"], 10.0, places=9)
        # Both endpoints counted: 0 in first bin, 10 in last bin.
        self.assertEqual(result["items"][0]["count"], 1)
        self.assertEqual(result["items"][-1]["count"], 1)

    def test_edges_are_contiguous(self):
        result = domain.histogram(
            [{"value": v, "unit": "m"} for v in (0, 4)], 4)
        items = result["items"]
        for i in range(len(items) - 1):
            self.assertAlmostEqual(items[i]["end"], items[i + 1]["start"], places=9)

    def test_mixed_units_restated(self):
        result = domain.histogram(
            [{"value": 100, "unit": "cm"}, {"value": 3, "unit": "m"}], 2, "m")
        self.assertEqual(result["unit"], "m")
        self.assertAlmostEqual(result["min"], 1.0, places=9)
        self.assertAlmostEqual(result["max"], 3.0, places=9)

    def test_zero_range_rejected(self):
        with self.assertRaises(ValueError):
            domain.histogram([{"value": 5, "unit": "m"}, {"value": 5, "unit": "m"}], 3)

    def test_bins_must_be_int(self):
        with self.assertRaises(ValueError):
            domain.histogram([{"value": 1, "unit": "m"}, {"value": 2, "unit": "m"}], 2.5)

    def test_bool_bins_rejected(self):
        with self.assertRaises(ValueError):
            domain.histogram([{"value": 1, "unit": "m"}, {"value": 2, "unit": "m"}], True)

    def test_zero_bins_rejected(self):
        with self.assertRaises(ValueError):
            domain.histogram([{"value": 1, "unit": "m"}, {"value": 2, "unit": "m"}], 0)

    def test_too_many_bins_rejected(self):
        with self.assertRaises(ValueError):
            domain.histogram(
                [{"value": 1, "unit": "m"}, {"value": 2, "unit": "m"}],
                domain.MAX_HISTOGRAM_BINS + 1)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.histogram([], 3)

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.histogram("nope", 3)

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.histogram([{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}], 2)

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.histogram([{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}], 2)

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.histogram([{"value": 30, "unit": "mpg"}, {"value": 40, "unit": "mpg"}], 2)

    def test_non_finite_value_raises(self):
        with self.assertRaises(ValueError):
            domain.histogram([{"value": float("inf"), "unit": "m"}], 2)


class TestHttpQuartilesOutliersHistogram(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url(path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, payload

    # --- /api/quartiles ---
    def test_quartiles_endpoint_ok(self):
        status, data = self._post("/api/quartiles", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["count"], 5)
        self.assertAlmostEqual(data["q1"], 2.0, places=6)
        self.assertAlmostEqual(data["median"], 3.0, places=6)
        self.assertAlmostEqual(data["q3"], 4.0, places=6)
        self.assertAlmostEqual(data["iqr"], 2.0, places=6)

    def test_quartiles_endpoint_median_matches_describe(self):
        items = [{"value": v, "unit": "m"} for v in (2, 4, 4, 4, 5, 5, 7, 9)]
        _, q = self._post("/api/quartiles", {"items": items})
        _, desc = self._post("/api/describe", {"items": items})
        self.assertAlmostEqual(q["median"], desc["median"], places=6)

    def test_quartiles_endpoint_precision(self):
        status, data = self._post("/api/quartiles", {
            "items": [{"value": 1, "unit": "ft"}, {"value": 2, "unit": "ft"}],
            "to": "m", "precision": 2,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["median"], round(data["median"], 2))

    def test_quartiles_endpoint_not_a_list_400(self):
        status, data = self._post("/api/quartiles", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_quartiles_endpoint_cross_category_400(self):
        status, data = self._post("/api/quartiles", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_quartiles_endpoint_temperature_400(self):
        status, data = self._post("/api/quartiles", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_quartiles_endpoint_empty_400(self):
        status, data = self._post("/api/quartiles", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/outliers ---
    def test_outliers_endpoint_ok(self):
        status, data = self._post("/api/outliers", {
            "items": [{"value": v, "unit": "m"} for v in (10, 11, 12, 13, 90)],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["outlier_count"], 1)
        self.assertTrue(data["items"][4]["is_outlier"])
        self.assertAlmostEqual(data["k"], 1.5, places=6)

    def test_outliers_endpoint_custom_k(self):
        status, data = self._post("/api/outliers", {
            "items": [{"value": v, "unit": "m"} for v in (10, 11, 12, 13, 40)],
            "k": 3.0,
        })
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["k"], 3.0, places=6)

    def test_outliers_endpoint_negative_k_400(self):
        status, data = self._post("/api/outliers", {
            "items": [{"value": 1, "unit": "m"}], "k": -1})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_outliers_endpoint_precision(self):
        status, data = self._post("/api/outliers", {
            "items": [{"value": 1, "unit": "ft"}, {"value": 2, "unit": "ft"},
                      {"value": 9, "unit": "ft"}],
            "to": "m", "precision": 2,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["lower_fence"], round(data["lower_fence"], 2))

    def test_outliers_endpoint_not_a_list_400(self):
        status, data = self._post("/api/outliers", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_outliers_endpoint_cross_category_400(self):
        status, data = self._post("/api/outliers", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_outliers_endpoint_temperature_400(self):
        status, data = self._post("/api/outliers", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_outliers_endpoint_empty_400(self):
        status, data = self._post("/api/outliers", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/histogram ---
    def test_histogram_endpoint_ok(self):
        status, data = self._post("/api/histogram", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)],
            "bins": 4,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["bins"], 4)
        self.assertEqual(data["count"], 5)
        self.assertEqual([b["count"] for b in data["items"]], [1, 1, 1, 2])
        self.assertEqual(sum(b["count"] for b in data["items"]), 5)

    def test_histogram_endpoint_missing_bins_400(self):
        status, data = self._post("/api/histogram", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "m"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_histogram_endpoint_zero_range_400(self):
        status, data = self._post("/api/histogram", {
            "items": [{"value": 5, "unit": "m"}, {"value": 5, "unit": "m"}],
            "bins": 3,
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_histogram_endpoint_bad_bins_400(self):
        status, data = self._post("/api/histogram", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "m"}],
            "bins": 0,
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_histogram_endpoint_precision(self):
        status, data = self._post("/api/histogram", {
            "items": [{"value": 1, "unit": "ft"}, {"value": 4, "unit": "ft"}],
            "to": "m", "bins": 3, "precision": 2,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["min"], round(data["min"], 2))

    def test_histogram_endpoint_not_a_list_400(self):
        status, data = self._post("/api/histogram", {"items": "nope", "bins": 3})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_histogram_endpoint_cross_category_400(self):
        status, data = self._post("/api/histogram", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}],
            "bins": 2,
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_histogram_endpoint_temperature_400(self):
        status, data = self._post("/api/histogram", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}],
            "bins": 2,
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_histogram_endpoint_empty_400(self):
        status, data = self._post("/api/histogram", {"items": [], "bins": 3})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class TestDomainMeans(unittest.TestCase):
    def test_four_means(self):
        # 1, 2, 4, 8 (m): AM 3.75, GM 64^.25, HM 4/1.875, RMS sqrt(85/4).
        m = domain.means([{"value": v, "unit": "m"} for v in (1, 2, 4, 8)])
        self.assertEqual(m["category"], "length")
        self.assertEqual(m["unit"], "m")
        self.assertEqual(m["count"], 4)
        self.assertAlmostEqual(m["arithmetic"], 3.75, places=9)
        self.assertAlmostEqual(m["geometric"], 64 ** 0.25, places=9)
        self.assertAlmostEqual(m["harmonic"], 4 / 1.875, places=9)
        self.assertAlmostEqual(m["quadratic"], (85 / 4) ** 0.5, places=9)

    def test_inequality_chain(self):
        # For positive, non-identical values: HM <= GM <= AM <= RMS (strict here).
        m = domain.means([{"value": v, "unit": "m"} for v in (1, 2, 4, 8)])
        self.assertLess(m["harmonic"], m["geometric"])
        self.assertLess(m["geometric"], m["arithmetic"])
        self.assertLess(m["arithmetic"], m["quadratic"])

    def test_arithmetic_matches_describe(self):
        items = [{"value": v, "unit": "m"} for v in (2, 3, 5, 7, 11)]
        m = domain.means(items)
        desc = domain.describe_quantities(items)
        self.assertAlmostEqual(m["arithmetic"], desc["mean"], places=12)

    def test_identical_values_all_equal(self):
        m = domain.means([{"value": 5, "unit": "m"} for _ in range(3)])
        for key in ("arithmetic", "geometric", "harmonic", "quadratic"):
            self.assertAlmostEqual(m[key], 5.0, places=9)

    def test_single_item(self):
        m = domain.means([{"value": 42, "unit": "m"}])
        self.assertEqual(m["count"], 1)
        for key in ("arithmetic", "geometric", "harmonic", "quadratic"):
            self.assertAlmostEqual(m[key], 42.0, places=9)

    def test_mixed_units_restated(self):
        # 100 cm == 1 m, 400 cm == 4 m, 2 m -> AM (1+4+2)/3.
        m = domain.means(
            [{"value": 100, "unit": "cm"}, {"value": 400, "unit": "cm"},
             {"value": 2, "unit": "m"}], "m")
        self.assertEqual(m["unit"], "m")
        self.assertAlmostEqual(m["arithmetic"], 7 / 3, places=9)

    def test_default_target_is_first_unit(self):
        m = domain.means([{"value": 1, "unit": "kg"}, {"value": 500, "unit": "g"}])
        self.assertEqual(m["unit"], "kg")

    def test_tuple_items_accepted(self):
        m = domain.means([(1, "kg"), (1000, "g")], "kg")
        self.assertEqual(m["count"], 2)

    def test_zero_value_rejected(self):
        with self.assertRaises(ValueError):
            domain.means([{"value": 0, "unit": "m"}, {"value": 2, "unit": "m"}])

    def test_negative_value_rejected(self):
        with self.assertRaises(ValueError):
            domain.means([{"value": -1, "unit": "m"}, {"value": 2, "unit": "m"}])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.means([])

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.means("nope")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.means([{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}])

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.means([{"value": 1, "unit": "frobs"}])

    def test_bad_target_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.means([{"value": 1, "unit": "m"}], "kg")

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.means([{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.means([{"value": 30, "unit": "mpg"}])

    def test_non_finite_value_raises(self):
        with self.assertRaises(ValueError):
            domain.means([{"value": float("inf"), "unit": "m"}])

    def test_missing_value_raises(self):
        with self.assertRaises(ValueError):
            domain.means([{"unit": "m"}])


class TestDomainRank(unittest.TestCase):
    def test_ascending_ranks(self):
        # input order 5,1,3,2,4 (m) -> ranks 5,1,3,2,4 by ascending magnitude.
        r = domain.rank_quantities(
            [{"value": v, "unit": "m"} for v in (5, 1, 3, 2, 4)])
        self.assertEqual(r["category"], "length")
        self.assertEqual(r["count"], 5)
        self.assertFalse(r["descending"])
        ranks = [it["rank"] for it in r["items"]]
        self.assertEqual(ranks, [5.0, 1.0, 3.0, 2.0, 4.0])

    def test_ranks_sum_invariant(self):
        # Average ranking: ranks always sum to n(n+1)/2, ties or not.
        r = domain.rank_quantities(
            [{"value": v, "unit": "m"} for v in (10, 10, 20, 5, 5, 5)])
        n = r["count"]
        self.assertAlmostEqual(
            sum(it["rank"] for it in r["items"]), n * (n + 1) / 2.0, places=9)

    def test_ties_share_average_rank(self):
        # 10, 10, 20 -> the two 10s share ranks 1 and 2 -> 1.5 each; 20 -> 3.
        r = domain.rank_quantities(
            [{"value": v, "unit": "m"} for v in (10, 10, 20)])
        ranks = [it["rank"] for it in r["items"]]
        self.assertEqual(ranks, [1.5, 1.5, 3.0])

    def test_descending_flips(self):
        r = domain.rank_quantities(
            [{"value": v, "unit": "m"} for v in (5, 1, 3, 2, 4)], descending=True)
        self.assertTrue(r["descending"])
        ranks = [it["rank"] for it in r["items"]]
        self.assertEqual(ranks, [1.0, 5.0, 3.0, 4.0, 2.0])

    def test_percent_rank_inverts_percentile(self):
        # For distinct ascending values, feeding an item's percent_rank back to
        # percentile_quantities returns that item's value (both are R-7).
        items = [{"value": v, "unit": "m"} for v in (3, 1, 9, 4, 7)]
        r = domain.rank_quantities(items)
        for it in r["items"]:
            p = domain.percentile_quantities(items, it["percent_rank"])
            self.assertAlmostEqual(p["value"], it["value"], places=9)

    def test_percent_rank_endpoints(self):
        r = domain.rank_quantities(
            [{"value": v, "unit": "m"} for v in (10, 20, 30)])
        by_index = {it["index"]: it for it in r["items"]}
        self.assertAlmostEqual(by_index[0]["percent_rank"], 0.0, places=9)
        self.assertAlmostEqual(by_index[2]["percent_rank"], 100.0, places=9)

    def test_single_item(self):
        r = domain.rank_quantities([{"value": 42, "unit": "m"}])
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["items"][0]["rank"], 1.0)
        self.assertAlmostEqual(r["items"][0]["percent_rank"], 0.0, places=9)

    def test_mixed_units_restated(self):
        r = domain.rank_quantities(
            [{"value": 100, "unit": "cm"}, {"value": 3, "unit": "m"}], "m")
        self.assertEqual(r["unit"], "m")
        self.assertAlmostEqual(r["items"][0]["value"], 1.0, places=9)
        self.assertEqual(r["items"][0]["rank"], 1.0)
        self.assertEqual(r["items"][1]["rank"], 2.0)

    def test_default_target_is_first_unit(self):
        r = domain.rank_quantities(
            [{"value": 1, "unit": "kg"}, {"value": 500, "unit": "g"}])
        self.assertEqual(r["unit"], "kg")

    def test_tuple_items_accepted(self):
        r = domain.rank_quantities([(1, "kg"), (1000, "g")], "kg")
        self.assertEqual(r["count"], 2)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.rank_quantities([])

    def test_not_a_list_raises(self):
        with self.assertRaises(ValueError):
            domain.rank_quantities("nope")

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.rank_quantities([{"value": 1, "unit": "m"}, {"value": 1, "unit": "s"}])

    def test_unknown_unit_raises(self):
        with self.assertRaises(ValueError):
            domain.rank_quantities([{"value": 1, "unit": "frobs"}])

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.rank_quantities([{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.rank_quantities([{"value": 30, "unit": "mpg"}])

    def test_non_finite_value_raises(self):
        with self.assertRaises(ValueError):
            domain.rank_quantities([{"value": float("inf"), "unit": "m"}])


class TestHttpMeansRank(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url(path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, payload

    # --- /api/means ---
    def test_means_endpoint_ok(self):
        status, data = self._post("/api/means", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 4, 8)],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["count"], 4)
        self.assertAlmostEqual(data["arithmetic"], 3.75, places=6)
        self.assertAlmostEqual(data["harmonic"], 4 / 1.875, places=6)

    def test_means_endpoint_inequality(self):
        status, data = self._post("/api/means", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 4, 8)]})
        self.assertEqual(status, 200)
        self.assertLessEqual(data["harmonic"], data["geometric"])
        self.assertLessEqual(data["geometric"], data["arithmetic"])
        self.assertLessEqual(data["arithmetic"], data["quadratic"])

    def test_means_endpoint_matches_describe(self):
        items = [{"value": v, "unit": "m"} for v in (2, 3, 5, 7, 11)]
        _, m = self._post("/api/means", {"items": items})
        _, desc = self._post("/api/describe", {"items": items})
        self.assertAlmostEqual(m["arithmetic"], desc["mean"], places=6)

    def test_means_endpoint_precision(self):
        status, data = self._post("/api/means", {
            "items": [{"value": 1, "unit": "ft"}, {"value": 2, "unit": "ft"}],
            "to": "m", "precision": 2,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["geometric"], round(data["geometric"], 2))

    def test_means_endpoint_non_positive_400(self):
        status, data = self._post("/api/means", {
            "items": [{"value": 0, "unit": "m"}, {"value": 2, "unit": "m"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_means_endpoint_not_a_list_400(self):
        status, data = self._post("/api/means", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_means_endpoint_cross_category_400(self):
        status, data = self._post("/api/means", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_means_endpoint_temperature_400(self):
        status, data = self._post("/api/means", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_means_endpoint_empty_400(self):
        status, data = self._post("/api/means", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/rank ---
    def test_rank_endpoint_ok(self):
        status, data = self._post("/api/rank", {
            "items": [{"value": v, "unit": "m"} for v in (5, 1, 3, 2, 4)],
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["count"], 5)
        self.assertFalse(data["descending"])
        self.assertEqual([it["rank"] for it in data["items"]],
                         [5.0, 1.0, 3.0, 2.0, 4.0])

    def test_rank_endpoint_descending(self):
        status, data = self._post("/api/rank", {
            "items": [{"value": v, "unit": "m"} for v in (5, 1, 3, 2, 4)],
            "descending": True,
        })
        self.assertEqual(status, 200)
        self.assertTrue(data["descending"])
        self.assertEqual([it["rank"] for it in data["items"]],
                         [1.0, 5.0, 3.0, 4.0, 2.0])

    def test_rank_endpoint_ties(self):
        status, data = self._post("/api/rank", {
            "items": [{"value": v, "unit": "m"} for v in (10, 10, 20)]})
        self.assertEqual(status, 200)
        self.assertEqual([it["rank"] for it in data["items"]], [1.5, 1.5, 3.0])

    def test_rank_endpoint_percent_rank_endpoints(self):
        status, data = self._post("/api/rank", {
            "items": [{"value": v, "unit": "m"} for v in (10, 20, 30)]})
        self.assertEqual(status, 200)
        by_index = {it["index"]: it for it in data["items"]}
        self.assertAlmostEqual(by_index[0]["percent_rank"], 0.0, places=6)
        self.assertAlmostEqual(by_index[2]["percent_rank"], 100.0, places=6)

    def test_rank_endpoint_precision(self):
        status, data = self._post("/api/rank", {
            "items": [{"value": 1, "unit": "ft"}, {"value": 2, "unit": "ft"},
                      {"value": 9, "unit": "ft"}],
            "to": "m", "precision": 2,
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["items"][0]["value"],
                         round(data["items"][0]["value"], 2))

    def test_rank_endpoint_not_a_list_400(self):
        status, data = self._post("/api/rank", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_rank_endpoint_cross_category_400(self):
        status, data = self._post("/api/rank", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_rank_endpoint_temperature_400(self):
        status, data = self._post("/api/rank", {
            "items": [{"value": 10, "unit": "c"}, {"value": 5, "unit": "c"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_rank_endpoint_empty_400(self):
        status, data = self._post("/api/rank", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class TestDomainMode(unittest.TestCase):
    def test_single_mode(self):
        result = domain.mode_quantities(
            [{"value": v, "unit": "m"} for v in (1, 2, 2, 3)])
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["count"], 4)
        self.assertEqual(result["frequency"], 2)
        self.assertFalse(result["is_multimodal"])
        self.assertEqual(result["modes"], [2.0])

    def test_multimodal_sorted(self):
        result = domain.mode_quantities(
            [{"value": v, "unit": "m"} for v in (3, 3, 1, 1, 2)])
        self.assertTrue(result["is_multimodal"])
        self.assertEqual(result["frequency"], 2)
        self.assertEqual(result["modes"], [1.0, 3.0])

    def test_all_unique_every_value_is_mode(self):
        # No repeats -> frequency 1 -> every value ties (fully multimodal).
        result = domain.mode_quantities(
            [{"value": v, "unit": "m"} for v in (5, 1, 3)])
        self.assertEqual(result["frequency"], 1)
        self.assertTrue(result["is_multimodal"])
        self.assertEqual(result["modes"], [1.0, 3.0, 5.0])

    def test_single_item(self):
        result = domain.mode_quantities([{"value": 7, "unit": "m"}])
        self.assertEqual(result["frequency"], 1)
        self.assertFalse(result["is_multimodal"])
        self.assertEqual(result["modes"], [7.0])

    def test_mode_after_unit_conversion(self):
        # 100 cm == 1 m, so they count as the same magnitude in the target unit.
        result = domain.mode_quantities(
            [{"value": 100, "unit": "cm"}, {"value": 1, "unit": "m"},
             {"value": 2, "unit": "m"}], "m")
        self.assertEqual(result["frequency"], 2)
        self.assertEqual(result["modes"], [1.0])

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            domain.mode_quantities([])

    def test_cross_category_rejected(self):
        with self.assertRaises(ValueError):
            domain.mode_quantities(
                [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}])

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.mode_quantities(
                [{"value": 1, "unit": "c"}, {"value": 2, "unit": "c"}])

    def test_unknown_unit_rejected(self):
        with self.assertRaises(ValueError):
            domain.mode_quantities([{"value": 1, "unit": "zorp"}])


class TestDomainWeightedMean(unittest.TestCase):
    def test_basic_weighting(self):
        # (1*1 + 3*3) / (1 + 3) = 10/4 = 2.5
        result = domain.weighted_mean([
            {"value": 1, "unit": "m", "weight": 1},
            {"value": 3, "unit": "m", "weight": 3},
        ])
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["count"], 2)
        self.assertAlmostEqual(result["total_weight"], 4.0, places=9)
        self.assertAlmostEqual(result["weighted_mean"], 2.5, places=9)

    def test_missing_weight_defaults_to_one(self):
        # No weights -> reduces to the plain arithmetic mean.
        result = domain.weighted_mean(
            [{"value": v, "unit": "m"} for v in (2, 4, 6)])
        self.assertAlmostEqual(result["weighted_mean"], 4.0, places=9)
        self.assertAlmostEqual(result["total_weight"], 3.0, places=9)

    def test_matches_arithmetic_mean_when_equal_weights(self):
        items = [{"value": v, "unit": "m", "weight": 2} for v in (2, 3, 5, 7)]
        result = domain.weighted_mean(items)
        self.assertAlmostEqual(result["weighted_mean"], (2 + 3 + 5 + 7) / 4.0,
                               places=9)

    def test_unit_conversion(self):
        # 1 ft and 2 ft converted to m, equal weights -> mean of 1.5 ft in m.
        result = domain.weighted_mean(
            [{"value": 1, "unit": "ft"}, {"value": 2, "unit": "ft"}], "m")
        self.assertEqual(result["unit"], "m")
        self.assertAlmostEqual(result["weighted_mean"], 1.5 * 0.3048, places=9)

    def test_zero_weight_item_ignored(self):
        # A zero-weight item contributes nothing but is still valid.
        result = domain.weighted_mean([
            {"value": 100, "unit": "m", "weight": 0},
            {"value": 5, "unit": "m", "weight": 1},
        ])
        self.assertAlmostEqual(result["weighted_mean"], 5.0, places=9)

    def test_all_zero_weights_rejected(self):
        with self.assertRaises(ValueError):
            domain.weighted_mean([
                {"value": 1, "unit": "m", "weight": 0},
                {"value": 2, "unit": "m", "weight": 0},
            ])

    def test_negative_weight_rejected(self):
        with self.assertRaises(ValueError):
            domain.weighted_mean([
                {"value": 1, "unit": "m", "weight": -1},
                {"value": 2, "unit": "m", "weight": 1},
            ])

    def test_non_numeric_weight_rejected(self):
        with self.assertRaises(ValueError):
            domain.weighted_mean([{"value": 1, "unit": "m", "weight": "heavy"}])

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            domain.weighted_mean([])

    def test_cross_category_rejected(self):
        with self.assertRaises(ValueError):
            domain.weighted_mean(
                [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}])

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.weighted_mean(
                [{"value": 1, "unit": "c"}, {"value": 2, "unit": "c"}])


class TestDomainMovingAverage(unittest.TestCase):
    def test_basic_window(self):
        result = domain.moving_average(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)], 2)
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["count"], 4)
        self.assertEqual(result["window"], 2)
        averages = [it["average"] for it in result["items"]]
        self.assertEqual(averages, [1.5, 2.5, 3.5])
        self.assertEqual(result["items"][0]["start_index"], 0)
        self.assertEqual(result["items"][0]["end_index"], 1)
        self.assertEqual(result["items"][-1]["end_index"], 3)

    def test_window_of_one_echoes_values(self):
        result = domain.moving_average(
            [{"value": v, "unit": "m"} for v in (5, 7, 9)], 1)
        self.assertEqual([it["average"] for it in result["items"]],
                         [5.0, 7.0, 9.0])

    def test_window_equals_count_is_overall_mean(self):
        result = domain.moving_average(
            [{"value": v, "unit": "m"} for v in (2, 4, 6)], 3)
        self.assertEqual(len(result["items"]), 1)
        self.assertAlmostEqual(result["items"][0]["average"], 4.0, places=9)

    def test_count_of_windows(self):
        result = domain.moving_average(
            [{"value": v, "unit": "m"} for v in range(10)], 3)
        self.assertEqual(len(result["items"]), 8)  # 10 - 3 + 1

    def test_unit_conversion(self):
        result = domain.moving_average(
            [{"value": 100, "unit": "cm"}, {"value": 300, "unit": "cm"}], 2, "m")
        self.assertEqual(result["unit"], "m")
        self.assertAlmostEqual(result["items"][0]["average"], 2.0, places=9)

    def test_window_too_large_rejected(self):
        with self.assertRaises(ValueError):
            domain.moving_average([{"value": 1, "unit": "m"}], 2)

    def test_window_zero_rejected(self):
        with self.assertRaises(ValueError):
            domain.moving_average([{"value": 1, "unit": "m"}], 0)

    def test_window_non_integer_rejected(self):
        with self.assertRaises(ValueError):
            domain.moving_average([{"value": 1, "unit": "m"}], 1.5)

    def test_window_bool_rejected(self):
        with self.assertRaises(ValueError):
            domain.moving_average(
                [{"value": 1, "unit": "m"}, {"value": 2, "unit": "m"}], True)

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            domain.moving_average([], 1)

    def test_cross_category_rejected(self):
        with self.assertRaises(ValueError):
            domain.moving_average(
                [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}], 2)

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.moving_average(
                [{"value": 1, "unit": "c"}, {"value": 2, "unit": "c"}], 2)


class TestHttpModeWeightedMovingAverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._url(path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, payload

    # --- /api/mode ---
    def test_mode_endpoint_ok(self):
        status, data = self._post("/api/mode", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 2, 3)]})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["frequency"], 2)
        self.assertFalse(data["is_multimodal"])
        self.assertEqual(data["modes"], [2.0])

    def test_mode_endpoint_multimodal(self):
        status, data = self._post("/api/mode", {
            "items": [{"value": v, "unit": "m"} for v in (3, 3, 1, 1, 2)]})
        self.assertEqual(status, 200)
        self.assertTrue(data["is_multimodal"])
        self.assertEqual(data["modes"], [1.0, 3.0])

    def test_mode_endpoint_precision(self):
        status, data = self._post("/api/mode", {
            "items": [{"value": 1, "unit": "ft"}, {"value": 1, "unit": "ft"}],
            "to": "m", "precision": 2})
        self.assertEqual(status, 200)
        self.assertEqual(data["modes"], [round(0.3048, 2)])

    def test_mode_endpoint_not_a_list_400(self):
        status, data = self._post("/api/mode", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_mode_endpoint_cross_category_400(self):
        status, data = self._post("/api/mode", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_mode_endpoint_empty_400(self):
        status, data = self._post("/api/mode", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/weighted-mean ---
    def test_weighted_mean_endpoint_ok(self):
        status, data = self._post("/api/weighted-mean", {
            "items": [{"value": 1, "unit": "m", "weight": 1},
                      {"value": 3, "unit": "m", "weight": 3}]})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertAlmostEqual(data["weighted_mean"], 2.5, places=6)
        self.assertAlmostEqual(data["total_weight"], 4.0, places=6)

    def test_weighted_mean_endpoint_default_weight(self):
        status, data = self._post("/api/weighted-mean", {
            "items": [{"value": v, "unit": "m"} for v in (2, 4, 6)]})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["weighted_mean"], 4.0, places=6)

    def test_weighted_mean_endpoint_matches_describe_when_unweighted(self):
        items = [{"value": v, "unit": "m"} for v in (2, 3, 5, 7, 11)]
        _, w = self._post("/api/weighted-mean", {"items": items})
        _, desc = self._post("/api/describe", {"items": items})
        self.assertAlmostEqual(w["weighted_mean"], desc["mean"], places=6)

    def test_weighted_mean_endpoint_precision(self):
        status, data = self._post("/api/weighted-mean", {
            "items": [{"value": 1, "unit": "ft"}, {"value": 2, "unit": "ft"}],
            "to": "m", "precision": 2})
        self.assertEqual(status, 200)
        self.assertEqual(data["weighted_mean"],
                         round(data["weighted_mean"], 2))

    def test_weighted_mean_endpoint_all_zero_weight_400(self):
        status, data = self._post("/api/weighted-mean", {
            "items": [{"value": 1, "unit": "m", "weight": 0}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_weighted_mean_endpoint_negative_weight_400(self):
        status, data = self._post("/api/weighted-mean", {
            "items": [{"value": 1, "unit": "m", "weight": -1}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_weighted_mean_endpoint_not_a_list_400(self):
        status, data = self._post("/api/weighted-mean", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_weighted_mean_endpoint_cross_category_400(self):
        status, data = self._post("/api/weighted-mean", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_weighted_mean_endpoint_empty_400(self):
        status, data = self._post("/api/weighted-mean", {"items": []})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    # --- /api/moving-average ---
    def test_moving_average_endpoint_ok(self):
        status, data = self._post("/api/moving-average", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)],
            "window": 2})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["window"], 2)
        self.assertEqual(data["count"], 4)
        self.assertEqual([it["average"] for it in data["items"]],
                         [1.5, 2.5, 3.5])
        self.assertEqual(data["items"][0]["start_index"], 0)
        self.assertEqual(data["items"][0]["end_index"], 1)

    def test_moving_average_endpoint_window_equals_count(self):
        status, data = self._post("/api/moving-average", {
            "items": [{"value": v, "unit": "m"} for v in (2, 4, 6)],
            "window": 3})
        self.assertEqual(status, 200)
        self.assertEqual(len(data["items"]), 1)
        self.assertAlmostEqual(data["items"][0]["average"], 4.0, places=6)

    def test_moving_average_endpoint_precision(self):
        status, data = self._post("/api/moving-average", {
            "items": [{"value": 1, "unit": "ft"}, {"value": 2, "unit": "ft"}],
            "window": 2, "to": "m", "precision": 2})
        self.assertEqual(status, 200)
        self.assertEqual(data["items"][0]["average"],
                         round(data["items"][0]["average"], 2))

    def test_moving_average_endpoint_missing_window_400(self):
        status, data = self._post("/api/moving-average", {
            "items": [{"value": 1, "unit": "m"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_moving_average_endpoint_window_too_large_400(self):
        status, data = self._post("/api/moving-average", {
            "items": [{"value": 1, "unit": "m"}], "window": 5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_moving_average_endpoint_not_a_list_400(self):
        status, data = self._post("/api/moving-average", {
            "items": "nope", "window": 1})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_moving_average_endpoint_cross_category_400(self):
        status, data = self._post("/api/moving-average", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}],
            "window": 2})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_moving_average_endpoint_temperature_400(self):
        status, data = self._post("/api/moving-average", {
            "items": [{"value": 1, "unit": "c"}, {"value": 2, "unit": "c"}],
            "window": 2})
        self.assertEqual(status, 400)
        self.assertIn("error", data)


# --------------------------------------------------------------------------- #
# Bivariate statistics — two paired series of quantities
# --------------------------------------------------------------------------- #
class TestDomainCovariance(unittest.TestCase):
    # x = [1,2,3,4,5] m, y = [2,4,6,8,10] s (a perfect y = 2x line):
    #   mean_x = 3, mean_y = 6, Sxy = 20, so cov(pop) = 4, cov(sample) = 5.
    X = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)]
    Y = [{"value": v, "unit": "s"} for v in (2, 4, 6, 8, 10)]

    def test_population_and_sample(self):
        r = domain.covariance(self.X, self.Y)
        self.assertEqual(r["count"], 5)
        self.assertEqual((r["x_category"], r["y_category"]), ("length", "time"))
        self.assertEqual((r["x_unit"], r["y_unit"]), ("m", "s"))
        self.assertAlmostEqual(r["mean_x"], 3.0, places=9)
        self.assertAlmostEqual(r["mean_y"], 6.0, places=9)
        self.assertAlmostEqual(r["covariance"], 4.0, places=9)
        self.assertAlmostEqual(r["sample_covariance"], 5.0, places=9)

    def test_negative_covariance(self):
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3)]
        y = [{"value": v, "unit": "s"} for v in (3, 2, 1)]
        r = domain.covariance(x, y)
        self.assertLess(r["covariance"], 0.0)

    def test_restates_to_common_unit(self):
        # x given in km but resolved to m must match the all-metres dataset.
        x_km = [{"value": v / 1000.0, "unit": "km"} for v in (1, 2, 3, 4, 5)]
        r = domain.covariance(x_km, self.Y, to_x="m")
        self.assertEqual(r["x_unit"], "m")
        self.assertAlmostEqual(r["covariance"], 4.0, places=9)

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            domain.covariance(self.X, self.Y[:3])

    def test_single_point_raises(self):
        with self.assertRaises(ValueError):
            domain.covariance(self.X[:1], self.Y[:1])

    def test_cross_category_within_series_raises(self):
        bad = [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]
        with self.assertRaises(ValueError):
            domain.covariance(bad, self.Y[:2])


class TestDomainCorrelation(unittest.TestCase):
    X = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)]
    Y = [{"value": v, "unit": "s"} for v in (2, 4, 6, 8, 10)]

    def test_perfect_positive(self):
        r = domain.correlation(self.X, self.Y)
        self.assertAlmostEqual(r["correlation"], 1.0, places=9)
        self.assertAlmostEqual(r["covariance"], 4.0, places=9)
        self.assertAlmostEqual(r["stdev_x"], math.sqrt(2.0), places=9)
        self.assertAlmostEqual(r["stdev_y"], math.sqrt(8.0), places=9)

    def test_perfect_negative(self):
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3)]
        y = [{"value": v, "unit": "s"} for v in (3, 2, 1)]
        r = domain.correlation(x, y)
        self.assertAlmostEqual(r["correlation"], -1.0, places=9)

    def test_dimensionless_invariant_to_unit(self):
        # r is unitless: scaling x into km must not change it.
        x_km = [{"value": v / 1000.0, "unit": "km"} for v in (1, 2, 3, 4, 5)]
        r1 = domain.correlation(self.X, self.Y)
        r2 = domain.correlation(x_km, self.Y, to_x="km")
        self.assertAlmostEqual(r1["correlation"], r2["correlation"], places=12)

    def test_constant_series_is_none(self):
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3)]
        y = [{"value": 5, "unit": "s"} for _ in range(3)]
        r = domain.correlation(x, y)
        self.assertIsNone(r["correlation"])

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            domain.correlation(self.X, self.Y[:2])


class TestDomainLinearRegression(unittest.TestCase):
    X = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)]
    Y = [{"value": v, "unit": "s"} for v in (2, 4, 6, 8, 10)]

    def test_perfect_line(self):
        r = domain.linear_regression(self.X, self.Y)
        self.assertAlmostEqual(r["slope"], 2.0, places=9)
        self.assertAlmostEqual(r["intercept"], 0.0, places=9)
        self.assertAlmostEqual(r["r"], 1.0, places=9)
        self.assertAlmostEqual(r["r_squared"], 1.0, places=9)
        self.assertEqual((r["x_unit"], r["y_unit"]), ("m", "s"))

    def test_intercept_and_slope(self):
        # y = 3x + 1 over x = 0..3.
        x = [{"value": v, "unit": "m"} for v in (0, 1, 2, 3)]
        y = [{"value": 3 * v + 1, "unit": "s"} for v in (0, 1, 2, 3)]
        r = domain.linear_regression(x, y)
        self.assertAlmostEqual(r["slope"], 3.0, places=9)
        self.assertAlmostEqual(r["intercept"], 1.0, places=9)
        self.assertAlmostEqual(r["r_squared"], 1.0, places=9)

    def test_noisy_fit_r_squared_between_zero_and_one(self):
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)]
        y = [{"value": v, "unit": "s"} for v in (2, 4, 5, 4, 5)]
        r = domain.linear_regression(x, y)
        self.assertTrue(0.0 < r["r_squared"] < 1.0)

    def test_zero_variance_x_raises(self):
        x = [{"value": 2, "unit": "m"} for _ in range(3)]
        y = [{"value": v, "unit": "s"} for v in (1, 2, 3)]
        with self.assertRaises(ValueError):
            domain.linear_regression(x, y)

    def test_constant_y_flat_line_r_none(self):
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3)]
        y = [{"value": 5, "unit": "s"} for _ in range(3)]
        r = domain.linear_regression(x, y)
        self.assertAlmostEqual(r["slope"], 0.0, places=9)
        self.assertAlmostEqual(r["intercept"], 5.0, places=9)
        self.assertIsNone(r["r"])
        self.assertIsNone(r["r_squared"])


class TestDomainTheilSen(unittest.TestCase):
    X = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)]
    Y = [{"value": v, "unit": "s"} for v in (2, 4, 6, 8, 10)]

    def test_perfect_line(self):
        r = domain.theil_sen(self.X, self.Y)
        self.assertAlmostEqual(r["slope"], 2.0, places=9)
        self.assertAlmostEqual(r["intercept"], 0.0, places=9)
        self.assertEqual((r["x_unit"], r["y_unit"]), ("m", "s"))
        self.assertEqual(r["count"], 5)

    def test_intercept_and_slope(self):
        # y = 3x + 1 over x = 0..3.
        x = [{"value": v, "unit": "m"} for v in (0, 1, 2, 3)]
        y = [{"value": 3 * v + 1, "unit": "s"} for v in (0, 1, 2, 3)]
        r = domain.theil_sen(x, y)
        self.assertAlmostEqual(r["slope"], 3.0, places=9)
        self.assertAlmostEqual(r["intercept"], 1.0, places=9)

    def test_pair_counts(self):
        # n=5 -> 10 candidate pairs, all with distinct x (no ties).
        r = domain.theil_sen(self.X, self.Y)
        self.assertEqual(r["pairs"], 10)
        self.assertEqual(r["used_pairs"], 10)
        self.assertEqual(r["tied_pairs"], 0)

    def test_robust_to_outlier(self):
        # An OLS fit is dragged by a wild final point; Theil--Sen ignores it.
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)]
        y = [{"value": v, "unit": "s"} for v in (2, 4, 6, 8, 100)]
        ts = domain.theil_sen(x, y)
        ols = domain.linear_regression(x, y)
        # The median pairwise slope stays near the clean slope of 2 ...
        self.assertAlmostEqual(ts["slope"], 2.0, places=6)
        # ... while least squares is pulled far above it by the outlier.
        self.assertGreater(ols["slope"], ts["slope"] + 1.0)

    def test_tied_x_pairs_skipped(self):
        # Two points share x=1 (a vertical pair) -> one tied pair, still fits.
        x = [{"value": v, "unit": "m"} for v in (1, 1, 2, 3)]
        y = [{"value": v, "unit": "s"} for v in (1, 3, 4, 6)]
        r = domain.theil_sen(x, y)
        self.assertEqual(r["pairs"], 6)
        self.assertEqual(r["tied_pairs"], 1)
        self.assertEqual(r["used_pairs"], 5)

    def test_medians_reported(self):
        r = domain.theil_sen(self.X, self.Y)
        self.assertAlmostEqual(r["median_x"], 3.0, places=9)
        self.assertAlmostEqual(r["median_y"], 6.0, places=9)

    def test_negative_slope(self):
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)]
        y = [{"value": v, "unit": "s"} for v in (8, 6, 4, 2)]
        r = domain.theil_sen(x, y)
        self.assertAlmostEqual(r["slope"], -2.0, places=9)

    def test_unit_restatement_changes_slope_scale(self):
        # Restating x in cm (100x smaller numbers) scales the slope by 100.
        r_m = domain.theil_sen(self.X, self.Y)
        r_cm = domain.theil_sen(self.X, self.Y, to_x="cm")
        self.assertAlmostEqual(r_cm["slope"] * 100.0, r_m["slope"], places=9)
        self.assertEqual(r_cm["x_unit"], "cm")

    def test_zero_variance_x_raises(self):
        x = [{"value": 2, "unit": "m"} for _ in range(3)]
        y = [{"value": v, "unit": "s"} for v in (1, 2, 3)]
        with self.assertRaises(ValueError):
            domain.theil_sen(x, y)

    def test_mismatched_lengths_raise(self):
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3)]
        y = [{"value": v, "unit": "s"} for v in (1, 2)]
        with self.assertRaises(ValueError):
            domain.theil_sen(x, y)

    def test_single_point_raises(self):
        with self.assertRaises(ValueError):
            domain.theil_sen([{"value": 1, "unit": "m"}],
                             [{"value": 2, "unit": "s"}])

    def test_cross_category_series_allowed(self):
        # x and y may be different categories (length vs time), like regression.
        r = domain.theil_sen(self.X, self.Y)
        self.assertEqual((r["x_category"], r["y_category"]), ("length", "time"))


class TestDomainSpearman(unittest.TestCase):
    X = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)]
    Y = [{"value": v, "unit": "s"} for v in (2, 4, 6, 8, 10)]

    def test_perfect_positive(self):
        r = domain.spearman(self.X, self.Y)
        self.assertAlmostEqual(r["spearman"], 1.0, places=9)
        self.assertEqual((r["x_category"], r["y_category"]), ("length", "time"))
        self.assertFalse(r["has_ties"])

    def test_perfect_negative(self):
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)]
        y = [{"value": v, "unit": "s"} for v in (4, 3, 2, 1)]
        r = domain.spearman(x, y)
        self.assertAlmostEqual(r["spearman"], -1.0, places=9)

    def test_monotonic_nonlinear_is_one(self):
        # A strictly monotonic (but non-linear) relation: Spearman == 1 even
        # though Pearson r < 1, which is the whole point of the rank measure.
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)]
        y = [{"value": v, "unit": "s"} for v in (1, 4, 9, 16, 25)]
        sp = domain.spearman(x, y)
        pe = domain.correlation(x, y)
        self.assertAlmostEqual(sp["spearman"], 1.0, places=9)
        self.assertLess(pe["correlation"], 1.0)

    def test_invariant_to_monotonic_rescale(self):
        # Ranks ignore the unit, so restating x into km cannot change rho.
        x_km = [{"value": v / 1000.0, "unit": "km"} for v in (1, 2, 3, 4, 5)]
        r1 = domain.spearman(self.X, self.Y)
        r2 = domain.spearman(x_km, self.Y, to_x="km")
        self.assertAlmostEqual(r1["spearman"], r2["spearman"], places=12)

    def test_ties_flagged_and_handled(self):
        # Tied x values -> average ranks; has_ties is set and rho is still finite.
        x = [{"value": v, "unit": "m"} for v in (1, 2, 2, 3)]
        y = [{"value": v, "unit": "s"} for v in (1, 2, 3, 4)]
        r = domain.spearman(x, y)
        self.assertTrue(r["has_ties"])
        self.assertIsNotNone(r["spearman"])
        self.assertTrue(-1.0 <= r["spearman"] <= 1.0)

    def test_mean_ranks_are_midpoint(self):
        # The mean rank is always (n+1)/2 regardless of ties.
        r = domain.spearman(self.X, self.Y)
        self.assertAlmostEqual(r["mean_rank_x"], 3.0, places=9)
        self.assertAlmostEqual(r["mean_rank_y"], 3.0, places=9)

    def test_matches_pearson_on_ranks(self):
        # By definition Spearman rho is Pearson r computed on the ranks.
        x = [{"value": v, "unit": "m"} for v in (10, 30, 20, 50, 40)]
        y = [{"value": v, "unit": "s"} for v in (7, 9, 6, 12, 11)]
        rho = domain.spearman(x, y)["spearman"]
        ranks_x = domain._average_ranks([10, 30, 20, 50, 40])
        ranks_y = domain._average_ranks([7, 9, 6, 12, 11])
        pearson = domain.correlation(
            [{"value": v, "unit": "m"} for v in ranks_x],
            [{"value": v, "unit": "s"} for v in ranks_y],
        )["correlation"]
        self.assertAlmostEqual(rho, pearson, places=12)

    def test_constant_series_is_none(self):
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3)]
        y = [{"value": 5, "unit": "s"} for _ in range(3)]
        r = domain.spearman(x, y)
        self.assertIsNone(r["spearman"])

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            domain.spearman(self.X, self.Y[:2])

    def test_single_point_raises(self):
        with self.assertRaises(ValueError):
            domain.spearman(self.X[:1], self.Y[:1])

    def test_cross_category_within_series_raises(self):
        bad = [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]
        with self.assertRaises(ValueError):
            domain.spearman(bad, self.Y[:2])


class TestDomainKendall(unittest.TestCase):
    X = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)]
    Y = [{"value": v, "unit": "s"} for v in (2, 4, 6, 8, 10)]

    def test_perfect_positive(self):
        r = domain.kendall(self.X, self.Y)
        self.assertAlmostEqual(r["tau"], 1.0, places=9)
        self.assertAlmostEqual(r["tau_a"], 1.0, places=9)
        self.assertEqual((r["x_category"], r["y_category"]), ("length", "time"))
        self.assertEqual(r["pairs"], 10)
        self.assertEqual(r["concordant"], 10)
        self.assertEqual(r["discordant"], 0)
        self.assertFalse(r["has_ties"])

    def test_perfect_negative(self):
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)]
        y = [{"value": v, "unit": "s"} for v in (4, 3, 2, 1)]
        r = domain.kendall(x, y)
        self.assertAlmostEqual(r["tau"], -1.0, places=9)
        self.assertEqual(r["concordant"], 0)
        self.assertEqual(r["discordant"], 6)

    def test_monotonic_nonlinear_is_one(self):
        # A strictly monotonic (non-linear) relation: tau == 1 even though the
        # Pearson r < 1, the whole point of the rank measure.
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)]
        y = [{"value": v, "unit": "s"} for v in (1, 4, 9, 16, 25)]
        tau = domain.kendall(x, y)["tau"]
        pe = domain.correlation(x, y)["correlation"]
        self.assertAlmostEqual(tau, 1.0, places=9)
        self.assertLess(pe, 1.0)

    def test_invariant_to_monotonic_rescale(self):
        # Concordance ignores the unit, so restating x into km cannot change tau.
        x_km = [{"value": v / 1000.0, "unit": "km"} for v in (1, 2, 3, 4, 5)]
        r1 = domain.kendall(self.X, self.Y)
        r2 = domain.kendall(x_km, self.Y, to_x="km")
        self.assertAlmostEqual(r1["tau"], r2["tau"], places=12)

    def test_known_value_with_one_discordant_pair(self):
        # x=1..4, y swaps the last two -> one discordant pair out of six:
        # tau = (5 - 1) / 6 = 0.666...
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)]
        y = [{"value": v, "unit": "s"} for v in (1, 2, 4, 3)]
        r = domain.kendall(x, y)
        self.assertEqual(r["concordant"], 5)
        self.assertEqual(r["discordant"], 1)
        self.assertAlmostEqual(r["tau"], 4.0 / 6.0, places=9)
        self.assertAlmostEqual(r["tau_a"], 4.0 / 6.0, places=9)

    def test_ties_flagged_and_tau_b_corrects(self):
        # A tie on x: that pair is excluded from C/D and feeds the tau-b
        # denominator, so tau_b != tau_a and has_ties is set.
        x = [{"value": v, "unit": "m"} for v in (1, 2, 2, 3)]
        y = [{"value": v, "unit": "s"} for v in (1, 2, 3, 4)]
        r = domain.kendall(x, y)
        self.assertTrue(r["has_ties"])
        self.assertEqual(r["ties_x"], 1)
        self.assertEqual(r["ties_y"], 0)
        self.assertIsNotNone(r["tau"])
        self.assertTrue(-1.0 <= r["tau"] <= 1.0)
        self.assertNotAlmostEqual(r["tau"], r["tau_a"], places=9)

    def test_tau_a_equals_tau_b_without_ties(self):
        x = [{"value": v, "unit": "m"} for v in (10, 30, 20, 50, 40)]
        y = [{"value": v, "unit": "s"} for v in (7, 9, 6, 12, 11)]
        r = domain.kendall(x, y)
        self.assertFalse(r["has_ties"])
        self.assertAlmostEqual(r["tau"], r["tau_a"], places=12)

    def test_constant_series_is_none(self):
        x = [{"value": v, "unit": "m"} for v in (1, 2, 3)]
        y = [{"value": 5, "unit": "s"} for _ in range(3)]
        r = domain.kendall(x, y)
        self.assertIsNone(r["tau"])
        self.assertTrue(r["has_ties"])

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            domain.kendall(self.X, self.Y[:2])

    def test_single_point_raises(self):
        with self.assertRaises(ValueError):
            domain.kendall(self.X[:1], self.Y[:1])

    def test_cross_category_within_series_raises(self):
        bad = [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]
        with self.assertRaises(ValueError):
            domain.kendall(bad, self.Y[:2])


class TestDomainAverageRanks(unittest.TestCase):
    def test_distinct_ascending(self):
        self.assertEqual(domain._average_ranks([10, 20, 30]), [1.0, 2.0, 3.0])

    def test_input_order_preserved(self):
        # rank[i] is the rank of values[i], in the original order.
        self.assertEqual(domain._average_ranks([30, 10, 20]), [3.0, 1.0, 2.0])

    def test_ties_share_average_rank(self):
        # Two values tie for ordinal ranks 2 and 3 -> both get 2.5.
        self.assertEqual(domain._average_ranks([1, 2, 2, 4]), [1.0, 2.5, 2.5, 4.0])

    def test_ranks_sum_to_triangular_number(self):
        ranks = domain._average_ranks([5, 5, 5, 1, 9])
        self.assertAlmostEqual(sum(ranks), 5 * 6 / 2.0, places=9)


class TestHttpBivariate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            data = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, data

    X = [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)]
    Y = [{"value": v, "unit": "s"} for v in (2, 4, 6, 8, 10)]

    def test_covariance_ok(self):
        status, data = self._post("/api/covariance", {"x": self.X, "y": self.Y})
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 5)
        self.assertAlmostEqual(data["covariance"], 4.0, places=6)
        self.assertAlmostEqual(data["sample_covariance"], 5.0, places=6)

    def test_correlation_ok(self):
        status, data = self._post("/api/correlation", {"x": self.X, "y": self.Y})
        self.assertEqual(status, 200)
        self.assertEqual((data["x_category"], data["y_category"]), ("length", "time"))
        self.assertAlmostEqual(data["correlation"], 1.0, places=6)

    def test_correlation_constant_series_null(self):
        status, data = self._post("/api/correlation", {
            "x": self.X[:3],
            "y": [{"value": 5, "unit": "s"} for _ in range(3)],
        })
        self.assertEqual(status, 200)
        self.assertIsNone(data["correlation"])

    def test_regression_ok(self):
        status, data = self._post("/api/regression", {"x": self.X, "y": self.Y})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["slope"], 2.0, places=6)
        self.assertAlmostEqual(data["intercept"], 0.0, places=6)
        self.assertAlmostEqual(data["r_squared"], 1.0, places=6)

    def test_regression_precision(self):
        status, data = self._post("/api/regression", {
            "x": self.X, "y": [{"value": v, "unit": "s"} for v in (2, 4, 5, 4, 5)],
            "precision": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["slope"], round(data["slope"], 3))

    def test_regression_zero_variance_x_400(self):
        status, data = self._post("/api/regression", {
            "x": [{"value": 2, "unit": "m"} for _ in range(3)],
            "y": [{"value": v, "unit": "s"} for v in (1, 2, 3)]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_theil_sen_ok(self):
        status, data = self._post("/api/theil-sen", {"x": self.X, "y": self.Y})
        self.assertEqual(status, 200)
        self.assertEqual((data["x_category"], data["y_category"]), ("length", "time"))
        self.assertAlmostEqual(data["slope"], 2.0, places=6)
        self.assertAlmostEqual(data["intercept"], 0.0, places=6)
        self.assertEqual(data["pairs"], 10)
        self.assertEqual(data["used_pairs"], 10)
        self.assertEqual(data["tied_pairs"], 0)

    def test_theil_sen_robust_beats_ols(self):
        # A wild final point drags OLS far above the robust median slope.
        y = [{"value": v, "unit": "s"} for v in (2, 4, 6, 8, 100)]
        _, ts = self._post("/api/theil-sen", {"x": self.X, "y": y})
        _, ols = self._post("/api/regression", {"x": self.X, "y": y})
        self.assertAlmostEqual(ts["slope"], 2.0, places=6)
        self.assertGreater(ols["slope"], ts["slope"] + 1.0)

    def test_theil_sen_precision(self):
        status, data = self._post("/api/theil-sen", {
            "x": self.X, "y": [{"value": v, "unit": "s"} for v in (2, 4, 5, 4, 5)],
            "precision": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["slope"], round(data["slope"], 3))

    def test_theil_sen_zero_variance_x_400(self):
        status, data = self._post("/api/theil-sen", {
            "x": [{"value": 2, "unit": "m"} for _ in range(3)],
            "y": [{"value": v, "unit": "s"} for v in (1, 2, 3)]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_spearman_ok(self):
        status, data = self._post("/api/spearman", {"x": self.X, "y": self.Y})
        self.assertEqual(status, 200)
        self.assertEqual((data["x_category"], data["y_category"]), ("length", "time"))
        self.assertAlmostEqual(data["spearman"], 1.0, places=6)
        self.assertFalse(data["has_ties"])
        self.assertAlmostEqual(data["mean_rank_x"], 3.0, places=6)

    def test_spearman_monotonic_beats_pearson(self):
        y = [{"value": v, "unit": "s"} for v in (1, 4, 9, 16, 25)]
        _, sp = self._post("/api/spearman", {"x": self.X, "y": y})
        _, pe = self._post("/api/correlation", {"x": self.X, "y": y})
        self.assertAlmostEqual(sp["spearman"], 1.0, places=6)
        self.assertLess(pe["correlation"], 1.0)

    def test_spearman_constant_series_null(self):
        status, data = self._post("/api/spearman", {
            "x": self.X[:3],
            "y": [{"value": 5, "unit": "s"} for _ in range(3)],
        })
        self.assertEqual(status, 200)
        self.assertIsNone(data["spearman"])

    def test_spearman_ties_flagged(self):
        status, data = self._post("/api/spearman", {
            "x": [{"value": v, "unit": "m"} for v in (1, 2, 2, 3)],
            "y": [{"value": v, "unit": "s"} for v in (1, 2, 3, 4)],
        })
        self.assertEqual(status, 200)
        self.assertTrue(data["has_ties"])

    def test_spearman_length_mismatch_400(self):
        status, data = self._post("/api/spearman", {"x": self.X, "y": self.Y[:2]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_spearman_missing_series_400(self):
        status, data = self._post("/api/spearman", {"x": self.X})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_kendall_ok(self):
        status, data = self._post("/api/kendall", {"x": self.X, "y": self.Y})
        self.assertEqual(status, 200)
        self.assertEqual((data["x_category"], data["y_category"]), ("length", "time"))
        self.assertAlmostEqual(data["tau"], 1.0, places=6)
        self.assertAlmostEqual(data["tau_a"], 1.0, places=6)
        self.assertEqual(data["count"], 5)
        self.assertEqual(data["pairs"], 10)
        self.assertEqual(data["concordant"], 10)
        self.assertEqual(data["discordant"], 0)
        self.assertFalse(data["has_ties"])

    def test_kendall_monotonic_beats_pearson(self):
        y = [{"value": v, "unit": "s"} for v in (1, 4, 9, 16, 25)]
        _, kt = self._post("/api/kendall", {"x": self.X, "y": y})
        _, pe = self._post("/api/correlation", {"x": self.X, "y": y})
        self.assertAlmostEqual(kt["tau"], 1.0, places=6)
        self.assertLess(pe["correlation"], 1.0)

    def test_kendall_constant_series_null(self):
        status, data = self._post("/api/kendall", {
            "x": self.X[:3],
            "y": [{"value": 5, "unit": "s"} for _ in range(3)],
        })
        self.assertEqual(status, 200)
        self.assertIsNone(data["tau"])

    def test_kendall_ties_flagged(self):
        status, data = self._post("/api/kendall", {
            "x": [{"value": v, "unit": "m"} for v in (1, 2, 2, 3)],
            "y": [{"value": v, "unit": "s"} for v in (1, 2, 3, 4)],
        })
        self.assertEqual(status, 200)
        self.assertTrue(data["has_ties"])
        self.assertEqual(data["ties_x"], 1)

    def test_kendall_precision(self):
        status, data = self._post("/api/kendall", {
            "x": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)],
            "y": [{"value": v, "unit": "s"} for v in (1, 2, 4, 3)],
            "precision": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["tau"], round(data["tau"], 3))

    def test_kendall_length_mismatch_400(self):
        status, data = self._post("/api/kendall", {"x": self.X, "y": self.Y[:2]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_kendall_missing_series_400(self):
        status, data = self._post("/api/kendall", {"x": self.X})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_missing_series_400(self):
        status, data = self._post("/api/correlation", {"x": self.X})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_non_list_series_400(self):
        status, data = self._post("/api/covariance", {"x": "nope", "y": self.Y})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_length_mismatch_400(self):
        status, data = self._post("/api/correlation", {"x": self.X, "y": self.Y[:2]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_single_point_400(self):
        status, data = self._post("/api/covariance", {
            "x": self.X[:1], "y": self.Y[:1]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_invalid_json_400(self):
        status, data = self._post("/api/correlation", None, raw=b"{bad")
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class TestDomainGini(unittest.TestCase):
    def test_known_coefficient(self):
        # The Gini of [1, 2, 3, 4] is exactly 0.25 (textbook value).
        result = domain.gini_quantities(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)])
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["count"], 4)
        self.assertAlmostEqual(result["gini"], 0.25, places=9)
        self.assertAlmostEqual(result["mean"], 2.5, places=9)

    def test_perfect_equality_is_zero(self):
        result = domain.gini_quantities(
            [{"value": 5, "unit": "m"} for _ in range(4)])
        self.assertAlmostEqual(result["gini"], 0.0, places=12)
        self.assertAlmostEqual(result["rmad"], 0.0, places=12)
        self.assertAlmostEqual(result["mean_abs_difference"], 0.0, places=12)

    def test_single_item_is_zero(self):
        result = domain.gini_quantities([{"value": 42, "unit": "kg"}])
        self.assertEqual(result["count"], 1)
        self.assertAlmostEqual(result["gini"], 0.0, places=12)

    def test_all_zero_is_zero(self):
        # A zero total is perfectly equal, not a division-by-zero error.
        result = domain.gini_quantities(
            [{"value": 0, "unit": "m"} for _ in range(3)])
        self.assertEqual(result["total"], 0.0)
        self.assertAlmostEqual(result["gini"], 0.0, places=12)

    def test_rmad_is_twice_gini(self):
        result = domain.gini_quantities(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)])
        self.assertAlmostEqual(result["rmad"], 2.0 * result["gini"], places=12)

    def test_mean_abs_difference(self):
        # For [1,2,3,4]: mean |xi-xj| over all ordered pairs == 1.25.
        result = domain.gini_quantities(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)])
        self.assertAlmostEqual(result["mean_abs_difference"], 1.25, places=9)
        # ... and it equals rmad * mean by construction.
        self.assertAlmostEqual(
            result["mean_abs_difference"], result["rmad"] * result["mean"],
            places=12)

    def test_unit_independent(self):
        # The coefficient is dimensionless: restating into another unit of the
        # same category must not change it.
        a = domain.gini_quantities(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)])
        b = domain.gini_quantities(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)], "cm")
        self.assertAlmostEqual(a["gini"], b["gini"], places=12)

    def test_mixed_units_restated(self):
        # 1 m + 100 cm == two equal quantities -> perfect equality.
        result = domain.gini_quantities(
            [{"value": 1, "unit": "m"}, {"value": 100, "unit": "cm"}])
        self.assertAlmostEqual(result["gini"], 0.0, places=12)

    def test_max_inequality_approaches_one(self):
        # One large value among many zeros: G -> (n-1)/n.
        items = [{"value": 0, "unit": "m"} for _ in range(9)]
        items.append({"value": 100, "unit": "m"})
        result = domain.gini_quantities(items)
        self.assertAlmostEqual(result["gini"], 0.9, places=9)

    def test_negative_value_rejected(self):
        with self.assertRaises(ValueError):
            domain.gini_quantities(
                [{"value": 1, "unit": "m"}, {"value": -2, "unit": "m"}])

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            domain.gini_quantities([])

    def test_cross_category_rejected(self):
        with self.assertRaises(ValueError):
            domain.gini_quantities(
                [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}])

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.gini_quantities([{"value": 10, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.gini_quantities([{"value": 30, "unit": "mpg"}])

    def test_unknown_unit_rejected(self):
        with self.assertRaises(ValueError):
            domain.gini_quantities([{"value": 1, "unit": "zorp"}])

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            domain.gini_quantities([{"value": float("inf"), "unit": "m"}])


class TestHttpGini(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            data = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, data

    def test_gini_ok(self):
        status, data = self._post("/api/gini", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)]})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["count"], 4)
        self.assertAlmostEqual(data["gini"], 0.25, places=6)
        self.assertAlmostEqual(data["mean"], 2.5, places=6)

    def test_gini_perfect_equality(self):
        status, data = self._post("/api/gini", {
            "items": [{"value": 5, "unit": "m"} for _ in range(3)]})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["gini"], 0.0, places=9)
        self.assertAlmostEqual(data["mean_abs_difference"], 0.0, places=9)

    def test_gini_to_unit(self):
        status, data = self._post("/api/gini", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)],
            "to": "cm"})
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "cm")
        self.assertAlmostEqual(data["gini"], 0.25, places=6)

    def test_gini_precision(self):
        status, data = self._post("/api/gini", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 5)],
            "precision": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["gini"], round(data["gini"], 3))

    def test_gini_negative_400(self):
        status, data = self._post("/api/gini", {
            "items": [{"value": 1, "unit": "m"}, {"value": -1, "unit": "m"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_gini_cross_category_400(self):
        status, data = self._post("/api/gini", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_gini_items_not_list_400(self):
        status, data = self._post("/api/gini", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_gini_invalid_json_400(self):
        status, data = self._post("/api/gini", None, raw=b"{bad")
        self.assertEqual(status, 400)
        self.assertIn("error", data)


# --------------------------------------------------------------------------- #
# Trimmed / winsorized mean (domain)
# --------------------------------------------------------------------------- #
class TestDomainTrimmedMean(unittest.TestCase):
    def _items(self, values, unit="m"):
        return [{"value": v, "unit": unit} for v in values]

    def test_no_trim_equals_arithmetic_mean(self):
        # proportion 0 trims nothing, so every reported centre is the plain mean.
        result = domain.trimmed_mean(self._items([1, 2, 3, 4, 5]), 0.0)
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["count"], 5)
        self.assertEqual(result["trimmed_each_side"], 0)
        self.assertEqual(result["kept"], 5)
        self.assertAlmostEqual(result["mean"], 3.0, places=9)
        self.assertAlmostEqual(result["trimmed_mean"], 3.0, places=9)
        self.assertAlmostEqual(result["winsorized_mean"], 3.0, places=9)

    def test_trims_one_each_side(self):
        # 10 points, p=0.1 -> floor(10*0.1)=1 dropped from each tail.
        result = domain.trimmed_mean(
            self._items([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]), 0.1)
        self.assertEqual(result["trimmed_each_side"], 1)
        self.assertEqual(result["kept"], 8)
        # mean of 2..9 == 5.5.
        self.assertAlmostEqual(result["trimmed_mean"], 5.5, places=9)
        self.assertAlmostEqual(result["lower"], 2.0, places=9)
        self.assertAlmostEqual(result["upper"], 9.0, places=9)

    def test_resists_outlier(self):
        # A wild value drags the plain mean far above the trimmed/winsorized one.
        values = [10, 11, 12, 13, 1000]
        result = domain.trimmed_mean(self._items(values), 0.2)
        self.assertEqual(result["trimmed_each_side"], 1)
        # mean of the middle three 11,12,13 == 12.
        self.assertAlmostEqual(result["trimmed_mean"], 12.0, places=9)
        self.assertGreater(result["mean"], result["trimmed_mean"])

    def test_winsorized_clamps_not_drops(self):
        # 5 values, p=0.2 -> drop/clamp 1 each side. Winsor replaces the extremes
        # with the kept bounds (lower=2, upper=4): mean of [2,2,3,4,4] == 3.0.
        result = domain.trimmed_mean(self._items([1, 2, 3, 4, 5]), 0.2)
        self.assertEqual(result["trimmed_each_side"], 1)
        self.assertAlmostEqual(result["lower"], 2.0, places=9)
        self.assertAlmostEqual(result["upper"], 4.0, places=9)
        self.assertAlmostEqual(result["trimmed_mean"], 3.0, places=9)
        self.assertAlmostEqual(result["winsorized_mean"], 3.0, places=9)

    def test_unordered_input_is_sorted(self):
        # Trimming must not depend on the order the caller supplied the items.
        a = domain.trimmed_mean(self._items([5, 1, 3, 2, 4]), 0.2)
        b = domain.trimmed_mean(self._items([1, 2, 3, 4, 5]), 0.2)
        self.assertAlmostEqual(a["trimmed_mean"], b["trimmed_mean"], places=9)
        self.assertAlmostEqual(a["winsorized_mean"], b["winsorized_mean"], places=9)

    def test_to_unit_restates(self):
        result = domain.trimmed_mean(self._items([1, 2, 3]), 0.0, "cm")
        self.assertEqual(result["unit"], "cm")
        self.assertAlmostEqual(result["trimmed_mean"], 200.0, places=6)

    def test_default_proportion_is_point_one(self):
        # Calling without a proportion uses 0.1.
        result = domain.trimmed_mean(self._items(range(1, 11)))
        self.assertAlmostEqual(result["proportion"], 0.1, places=9)
        self.assertEqual(result["trimmed_each_side"], 1)

    def test_negative_values_allowed(self):
        # Unlike the geometric/harmonic means, trimming has no positivity rule.
        result = domain.trimmed_mean(self._items([-5, -1, 0, 1, 5]), 0.2)
        self.assertAlmostEqual(result["trimmed_mean"], 0.0, places=9)

    def test_proportion_too_large_rejected(self):
        with self.assertRaises(ValueError):
            domain.trimmed_mean(self._items([1, 2, 3]), 0.5)

    def test_proportion_negative_rejected(self):
        with self.assertRaises(ValueError):
            domain.trimmed_mean(self._items([1, 2, 3]), -0.1)

    def test_proportion_non_numeric_rejected(self):
        with self.assertRaises(ValueError):
            domain.trimmed_mean(self._items([1, 2, 3]), "lots")

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            domain.trimmed_mean([], 0.1)

    def test_cross_category_rejected(self):
        with self.assertRaises(ValueError):
            domain.trimmed_mean(
                [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}], 0.1)

    def test_temperature_rejected(self):
        # Affine category: averaging on a single common unit is not meaningful.
        with self.assertRaises(ValueError):
            domain.trimmed_mean([{"value": 10, "unit": "c"}], 0.1)

    def test_unknown_unit_rejected(self):
        with self.assertRaises(ValueError):
            domain.trimmed_mean([{"value": 1, "unit": "zorp"}], 0.1)

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            domain.trimmed_mean([{"value": float("inf"), "unit": "m"}], 0.1)


class TestHttpTrimmedMean(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            data = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, data

    def test_trimmed_mean_ok(self):
        status, data = self._post("/api/trimmed-mean", {
            "items": [{"value": v, "unit": "m"} for v in range(1, 11)],
            "proportion": 0.1})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["count"], 10)
        self.assertEqual(data["trimmed_each_side"], 1)
        self.assertEqual(data["kept"], 8)
        self.assertAlmostEqual(data["trimmed_mean"], 5.5, places=6)

    def test_trimmed_mean_default_proportion(self):
        status, data = self._post("/api/trimmed-mean", {
            "items": [{"value": v, "unit": "m"} for v in range(1, 11)]})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["proportion"], 0.1, places=9)
        self.assertEqual(data["trimmed_each_side"], 1)

    def test_trimmed_mean_outlier_resistance(self):
        status, data = self._post("/api/trimmed-mean", {
            "items": [{"value": v, "unit": "m"} for v in (10, 11, 12, 13, 1000)],
            "proportion": 0.2})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["trimmed_mean"], 12.0, places=6)
        self.assertGreater(data["mean"], data["trimmed_mean"])

    def test_trimmed_mean_winsorized(self):
        status, data = self._post("/api/trimmed-mean", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)],
            "proportion": 0.2})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["winsorized_mean"], 3.0, places=6)
        self.assertAlmostEqual(data["lower"], 2.0, places=6)
        self.assertAlmostEqual(data["upper"], 4.0, places=6)

    def test_trimmed_mean_to_unit(self):
        status, data = self._post("/api/trimmed-mean", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3)],
            "to": "cm"})
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "cm")
        self.assertAlmostEqual(data["trimmed_mean"], 200.0, places=4)

    def test_trimmed_mean_precision(self):
        status, data = self._post("/api/trimmed-mean", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 4)],
            "proportion": 0.0, "precision": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["trimmed_mean"], round(data["trimmed_mean"], 3))

    def test_trimmed_mean_proportion_too_large_400(self):
        status, data = self._post("/api/trimmed-mean", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3)],
            "proportion": 0.5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_trimmed_mean_cross_category_400(self):
        status, data = self._post("/api/trimmed-mean", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_trimmed_mean_items_not_list_400(self):
        status, data = self._post("/api/trimmed-mean", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_trimmed_mean_invalid_json_400(self):
        status, data = self._post("/api/trimmed-mean", None, raw=b"{bad")
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class TestDomainWinsorize(unittest.TestCase):
    def _items(self, values, unit="m"):
        return [{"value": v, "unit": unit} for v in values]

    def test_no_clamp_equals_input(self):
        # proportion 0 clamps nothing, so the series is the restated input.
        result = domain.winsorize_quantities(self._items([1, 2, 3, 4, 5]), 0.0)
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["count"], 5)
        self.assertEqual(result["clamped_each_side"], 0)
        self.assertEqual([r["winsorized"] for r in result["items"]],
                         [1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertFalse(any(r["clamped"] for r in result["items"]))
        self.assertAlmostEqual(result["winsorized_mean"], 3.0, places=9)

    def test_clamps_extremes_to_bounds(self):
        # 5 values, p=0.2 -> clamp 1 each side. lower=2, upper=4:
        # [1,2,3,4,5] -> [2,2,3,4,4].
        result = domain.winsorize_quantities(self._items([1, 2, 3, 4, 5]), 0.2)
        self.assertEqual(result["clamped_each_side"], 1)
        self.assertAlmostEqual(result["lower"], 2.0, places=9)
        self.assertAlmostEqual(result["upper"], 4.0, places=9)
        self.assertEqual([r["winsorized"] for r in result["items"]],
                         [2.0, 2.0, 3.0, 4.0, 4.0])
        self.assertEqual([r["clamped"] for r in result["items"]],
                         [True, False, False, False, True])
        self.assertAlmostEqual(result["winsorized_mean"], 3.0, places=9)

    def test_preserves_input_order(self):
        # The series is reported in input order, not sorted order.
        result = domain.winsorize_quantities(self._items([5, 1, 3, 2, 4]), 0.2)
        self.assertEqual([r["value"] for r in result["items"]],
                         [5.0, 1.0, 3.0, 2.0, 4.0])
        # 5 -> upper(4); 1 -> lower(2); the rest unchanged.
        self.assertEqual([r["winsorized"] for r in result["items"]],
                         [4.0, 2.0, 3.0, 2.0, 4.0])

    def test_winsorized_mean_matches_trimmed_mean(self):
        # By construction the winsorized mean equals the one trimmed_mean reports.
        values = [10, 11, 12, 13, 1000]
        w = domain.winsorize_quantities(self._items(values), 0.2)
        t = domain.trimmed_mean(self._items(values), 0.2)
        self.assertAlmostEqual(w["winsorized_mean"], t["winsorized_mean"], places=9)
        self.assertAlmostEqual(w["lower"], t["lower"], places=9)
        self.assertAlmostEqual(w["upper"], t["upper"], places=9)

    def test_outlier_pulled_to_boundary(self):
        # The wild 1000 is pulled down to the upper bound (13), so the winsorized
        # mean sits far below the raw mean.
        result = domain.winsorize_quantities(
            self._items([10, 11, 12, 13, 1000]), 0.2)
        last = result["items"][-1]
        self.assertEqual(last["value"], 1000.0)
        self.assertAlmostEqual(last["winsorized"], 13.0, places=9)
        self.assertTrue(last["clamped"])
        self.assertGreater(result["mean"], result["winsorized_mean"])

    def test_winsorized_stdev_below_raw(self):
        # Clamping the tails shrinks the spread.
        result = domain.winsorize_quantities(
            self._items([1, 2, 3, 4, 100]), 0.2)
        raw = domain.describe_quantities(self._items([1, 2, 3, 4, 100]))
        self.assertLess(result["winsorized_stdev"], raw["stdev"])

    def test_to_unit_restates(self):
        result = domain.winsorize_quantities(self._items([1, 2, 3]), 0.0, "cm")
        self.assertEqual(result["unit"], "cm")
        self.assertEqual([r["winsorized"] for r in result["items"]],
                         [100.0, 200.0, 300.0])

    def test_default_proportion_is_point_one(self):
        result = domain.winsorize_quantities(self._items(range(1, 11)))
        self.assertAlmostEqual(result["proportion"], 0.1, places=9)
        self.assertEqual(result["clamped_each_side"], 1)
        # 1 -> lower(2), 10 -> upper(9).
        self.assertAlmostEqual(result["items"][0]["winsorized"], 2.0, places=9)
        self.assertAlmostEqual(result["items"][-1]["winsorized"], 9.0, places=9)

    def test_negative_values_allowed(self):
        result = domain.winsorize_quantities(self._items([-5, -1, 0, 1, 5]), 0.2)
        self.assertAlmostEqual(result["winsorized_mean"], 0.0, places=9)

    def test_proportion_too_large_rejected(self):
        with self.assertRaises(ValueError):
            domain.winsorize_quantities(self._items([1, 2, 3]), 0.5)

    def test_proportion_negative_rejected(self):
        with self.assertRaises(ValueError):
            domain.winsorize_quantities(self._items([1, 2, 3]), -0.1)

    def test_proportion_non_numeric_rejected(self):
        with self.assertRaises(ValueError):
            domain.winsorize_quantities(self._items([1, 2, 3]), "lots")

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            domain.winsorize_quantities([], 0.1)

    def test_cross_category_rejected(self):
        with self.assertRaises(ValueError):
            domain.winsorize_quantities(
                [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}], 0.1)

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.winsorize_quantities([{"value": 10, "unit": "c"}], 0.1)

    def test_unknown_unit_rejected(self):
        with self.assertRaises(ValueError):
            domain.winsorize_quantities([{"value": 1, "unit": "zorp"}], 0.1)

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            domain.winsorize_quantities([{"value": float("inf"), "unit": "m"}], 0.1)


class TestHttpWinsorize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            data = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, data

    def test_winsorize_ok(self):
        status, data = self._post("/api/winsorize", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)],
            "proportion": 0.2})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["count"], 5)
        self.assertEqual(data["clamped_each_side"], 1)
        self.assertAlmostEqual(data["lower"], 2.0, places=6)
        self.assertAlmostEqual(data["upper"], 4.0, places=6)
        self.assertEqual([r["winsorized"] for r in data["items"]],
                         [2.0, 2.0, 3.0, 4.0, 4.0])
        self.assertEqual([r["clamped"] for r in data["items"]],
                         [True, False, False, False, True])
        self.assertAlmostEqual(data["winsorized_mean"], 3.0, places=6)

    def test_winsorize_default_proportion(self):
        status, data = self._post("/api/winsorize", {
            "items": [{"value": v, "unit": "m"} for v in range(1, 11)]})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["proportion"], 0.1, places=9)
        self.assertEqual(data["clamped_each_side"], 1)

    def test_winsorize_preserves_order(self):
        status, data = self._post("/api/winsorize", {
            "items": [{"value": v, "unit": "m"} for v in (5, 1, 3, 2, 4)],
            "proportion": 0.2})
        self.assertEqual(status, 200)
        self.assertEqual([r["index"] for r in data["items"]], [0, 1, 2, 3, 4])
        self.assertEqual([r["value"] for r in data["items"]],
                         [5.0, 1.0, 3.0, 2.0, 4.0])
        self.assertEqual([r["winsorized"] for r in data["items"]],
                         [4.0, 2.0, 3.0, 2.0, 4.0])

    def test_winsorize_outlier_resistance(self):
        status, data = self._post("/api/winsorize", {
            "items": [{"value": v, "unit": "m"} for v in (10, 11, 12, 13, 1000)],
            "proportion": 0.2})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["items"][-1]["winsorized"], 13.0, places=6)
        self.assertGreater(data["mean"], data["winsorized_mean"])

    def test_winsorize_to_unit(self):
        status, data = self._post("/api/winsorize", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3)],
            "to": "cm"})
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "cm")
        self.assertEqual([r["winsorized"] for r in data["items"]],
                         [100.0, 200.0, 300.0])

    def test_winsorize_precision(self):
        status, data = self._post("/api/winsorize", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 4)],
            "proportion": 0.0, "precision": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["winsorized_mean"],
                         round(data["winsorized_mean"], 3))

    def test_winsorize_proportion_too_large_400(self):
        status, data = self._post("/api/winsorize", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3)],
            "proportion": 0.5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_winsorize_cross_category_400(self):
        status, data = self._post("/api/winsorize", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_winsorize_items_not_list_400(self):
        status, data = self._post("/api/winsorize", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_winsorize_invalid_json_400(self):
        status, data = self._post("/api/winsorize", None, raw=b"{bad")
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class TestDomainEma(unittest.TestCase):
    def test_basic_alpha_half(self):
        result = domain.ema(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)], 0.5)
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["count"], 4)
        self.assertEqual(result["alpha"], 0.5)
        self.assertIsNone(result["span"])
        emas = [it["ema"] for it in result["items"]]
        # ema0=1; ema1=.5*2+.5*1=1.5; ema2=.5*3+.5*1.5=2.25; ema3=.5*4+.5*2.25=3.125
        self.assertEqual(emas, [1.0, 1.5, 2.25, 3.125])

    def test_default_alpha_is_half(self):
        result = domain.ema([{"value": v, "unit": "m"} for v in (1, 2, 3, 4)])
        self.assertEqual(result["alpha"], 0.5)
        self.assertEqual([it["ema"] for it in result["items"]],
                         [1.0, 1.5, 2.25, 3.125])

    def test_first_ema_equals_first_value(self):
        result = domain.ema([{"value": 7, "unit": "m"}], 0.3)
        self.assertEqual(result["items"][0]["ema"], 7.0)
        self.assertEqual(result["items"][0]["value"], 7.0)

    def test_alpha_one_echoes_values(self):
        result = domain.ema(
            [{"value": v, "unit": "m"} for v in (5, 7, 9)], 1.0)
        self.assertEqual([it["ema"] for it in result["items"]], [5.0, 7.0, 9.0])

    def test_span_maps_to_alpha(self):
        # span 3 -> alpha = 2/(3+1) = 0.5, so it matches the alpha=0.5 result.
        result = domain.ema(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)], span=3)
        self.assertAlmostEqual(result["alpha"], 0.5, places=12)
        self.assertEqual(result["span"], 3.0)
        self.assertEqual([it["ema"] for it in result["items"]],
                         [1.0, 1.5, 2.25, 3.125])

    def test_span_of_one_is_alpha_one(self):
        result = domain.ema(
            [{"value": v, "unit": "m"} for v in (5, 7, 9)], span=1)
        self.assertAlmostEqual(result["alpha"], 1.0, places=12)
        self.assertEqual([it["ema"] for it in result["items"]], [5.0, 7.0, 9.0])

    def test_unit_conversion(self):
        result = domain.ema(
            [{"value": 100, "unit": "cm"}, {"value": 300, "unit": "cm"}], 0.5, to_unit="m")
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["items"][0]["ema"], 1.0)
        self.assertEqual(result["items"][1]["ema"], 2.0)

    def test_both_alpha_and_span_rejected(self):
        with self.assertRaises(ValueError):
            domain.ema([{"value": 1, "unit": "m"}], 0.5, span=3)

    def test_alpha_zero_rejected(self):
        with self.assertRaises(ValueError):
            domain.ema([{"value": 1, "unit": "m"}], 0.0)

    def test_alpha_above_one_rejected(self):
        with self.assertRaises(ValueError):
            domain.ema([{"value": 1, "unit": "m"}], 1.5)

    def test_alpha_non_numeric_rejected(self):
        with self.assertRaises(ValueError):
            domain.ema([{"value": 1, "unit": "m"}], "x")

    def test_span_below_one_rejected(self):
        with self.assertRaises(ValueError):
            domain.ema([{"value": 1, "unit": "m"}], span=0.5)

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            domain.ema([], 0.5)

    def test_cross_category_rejected(self):
        with self.assertRaises(ValueError):
            domain.ema([{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}], 0.5)

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.ema([{"value": 1, "unit": "c"}, {"value": 2, "unit": "c"}], 0.5)

    def test_nonfinite_value_rejected(self):
        with self.assertRaises(ValueError):
            domain.ema([{"value": float("inf"), "unit": "m"}], 0.5)


class TestHttpEma(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            data = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, data

    def test_ema_endpoint_ok(self):
        status, data = self._post("/api/ema", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)],
            "alpha": 0.5})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["alpha"], 0.5)
        self.assertIsNone(data["span"])
        self.assertEqual(data["count"], 4)
        self.assertEqual([it["ema"] for it in data["items"]],
                         [1.0, 1.5, 2.25, 3.125])
        self.assertEqual(data["items"][0]["index"], 0)

    def test_ema_endpoint_default_alpha(self):
        status, data = self._post("/api/ema", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)]})
        self.assertEqual(status, 200)
        self.assertEqual(data["alpha"], 0.5)
        self.assertEqual([it["ema"] for it in data["items"]],
                         [1.0, 1.5, 2.25, 3.125])

    def test_ema_endpoint_span(self):
        status, data = self._post("/api/ema", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)],
            "span": 3})
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["alpha"], 0.5, places=6)
        self.assertEqual(data["span"], 3.0)

    def test_ema_endpoint_precision(self):
        status, data = self._post("/api/ema", {
            "items": [{"value": 1, "unit": "ft"}, {"value": 2, "unit": "ft"}],
            "alpha": 0.3, "to": "m", "precision": 2})
        self.assertEqual(status, 200)
        self.assertEqual(data["items"][1]["ema"],
                         round(data["items"][1]["ema"], 2))

    def test_ema_endpoint_both_params_400(self):
        status, data = self._post("/api/ema", {
            "items": [{"value": 1, "unit": "m"}], "alpha": 0.5, "span": 3})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_ema_endpoint_bad_alpha_400(self):
        status, data = self._post("/api/ema", {
            "items": [{"value": 1, "unit": "m"}], "alpha": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_ema_endpoint_not_a_list_400(self):
        status, data = self._post("/api/ema", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_ema_endpoint_cross_category_400(self):
        status, data = self._post("/api/ema", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_ema_endpoint_temperature_400(self):
        status, data = self._post("/api/ema", {
            "items": [{"value": 1, "unit": "c"}, {"value": 2, "unit": "c"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_ema_endpoint_invalid_json_400(self):
        status, data = self._post("/api/ema", None, raw=b"{bad")
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class TestDomainAutocorrelation(unittest.TestCase):
    def test_basic_acf_known_series(self):
        # x = [1,2,3,4,5], mean 3, deviations [-2,-1,0,1,2], denom = 10.
        # r0 = 1, r1 = 4/10, r2 = -1/10, r3 = -4/10, r4 = -4/10.
        result = domain.autocorrelation(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)])
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["count"], 5)
        self.assertEqual(result["maxlag"], 4)  # defaults to count-1
        self.assertAlmostEqual(result["mean"], 3.0, places=9)
        self.assertAlmostEqual(result["variance"], 2.0, places=9)
        acf = [it["autocorrelation"] for it in result["items"]]
        self.assertEqual([it["lag"] for it in result["items"]], [0, 1, 2, 3, 4])
        self.assertAlmostEqual(acf[0], 1.0, places=9)
        self.assertAlmostEqual(acf[1], 0.4, places=9)
        self.assertAlmostEqual(acf[2], -0.1, places=9)
        self.assertAlmostEqual(acf[3], -0.4, places=9)
        self.assertAlmostEqual(acf[4], -0.4, places=9)

    def test_lag_zero_is_always_one(self):
        result = domain.autocorrelation(
            [{"value": v, "unit": "kg"} for v in (3, 1, 4, 1, 5, 9, 2)])
        self.assertAlmostEqual(result["items"][0]["autocorrelation"], 1.0, places=12)

    def test_all_coefficients_within_unit_interval(self):
        result = domain.autocorrelation(
            [{"value": v, "unit": "s"} for v in (10, 4, 7, 2, 9, 5, 6, 1)])
        for it in result["items"]:
            self.assertGreaterEqual(it["autocorrelation"], -1.0 - 1e-9)
            self.assertLessEqual(it["autocorrelation"], 1.0 + 1e-9)

    def test_explicit_maxlag_limits_output(self):
        result = domain.autocorrelation(
            [{"value": v, "unit": "m"} for v in range(6)], 2)
        self.assertEqual(result["maxlag"], 2)
        self.assertEqual([it["lag"] for it in result["items"]], [0, 1, 2])

    def test_maxlag_zero_only_r0(self):
        result = domain.autocorrelation(
            [{"value": v, "unit": "m"} for v in (1, 2, 3)], 0)
        self.assertEqual(len(result["items"]), 1)
        self.assertAlmostEqual(result["items"][0]["autocorrelation"], 1.0, places=12)

    def test_dimensionless_invariant_under_unit(self):
        # The same physical series in cm vs m yields identical coefficients.
        in_m = domain.autocorrelation(
            [{"value": v, "unit": "m"} for v in (1, 2, 4, 8)])
        in_cm = domain.autocorrelation(
            [{"value": v * 100, "unit": "cm"} for v in (1, 2, 4, 8)], to_unit="m")
        a = [it["autocorrelation"] for it in in_m["items"]]
        b = [it["autocorrelation"] for it in in_cm["items"]]
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, places=9)

    def test_unit_conversion_reports_target_unit(self):
        result = domain.autocorrelation(
            [{"value": 100, "unit": "cm"}, {"value": 300, "unit": "cm"}], to_unit="m")
        self.assertEqual(result["unit"], "m")
        self.assertAlmostEqual(result["mean"], 2.0, places=9)

    def test_tuple_items_accepted(self):
        result = domain.autocorrelation([(1, "m"), (2, "m"), (3, "m")])
        self.assertEqual(result["count"], 3)

    def test_single_item_rejected(self):
        with self.assertRaises(ValueError):
            domain.autocorrelation([{"value": 1, "unit": "m"}])

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            domain.autocorrelation([])

    def test_zero_variance_rejected(self):
        with self.assertRaises(ValueError):
            domain.autocorrelation([{"value": 5, "unit": "m"} for _ in range(4)])

    def test_maxlag_too_large_rejected(self):
        with self.assertRaises(ValueError):
            domain.autocorrelation(
                [{"value": v, "unit": "m"} for v in (1, 2, 3)], 3)

    def test_maxlag_negative_rejected(self):
        with self.assertRaises(ValueError):
            domain.autocorrelation(
                [{"value": v, "unit": "m"} for v in (1, 2, 3)], -1)

    def test_maxlag_non_integer_rejected(self):
        with self.assertRaises(ValueError):
            domain.autocorrelation(
                [{"value": v, "unit": "m"} for v in (1, 2, 3)], 1.5)

    def test_maxlag_bool_rejected(self):
        with self.assertRaises(ValueError):
            domain.autocorrelation(
                [{"value": v, "unit": "m"} for v in (1, 2, 3)], True)

    def test_cross_category_rejected(self):
        with self.assertRaises(ValueError):
            domain.autocorrelation(
                [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}])

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.autocorrelation(
                [{"value": 1, "unit": "c"}, {"value": 2, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.autocorrelation(
                [{"value": 30, "unit": "mpg"}, {"value": 40, "unit": "mpg"}])


class TestHttpAutocorrelation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            data = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, data

    def test_endpoint_ok(self):
        status, data = self._post("/api/autocorrelation", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5)]})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["count"], 5)
        self.assertEqual(data["maxlag"], 4)
        acf = [it["autocorrelation"] for it in data["items"]]
        self.assertEqual(acf[0], 1.0)
        self.assertAlmostEqual(acf[1], 0.4, places=6)
        self.assertAlmostEqual(acf[2], -0.1, places=6)

    def test_endpoint_explicit_maxlag(self):
        status, data = self._post("/api/autocorrelation", {
            "items": [{"value": v, "unit": "m"} for v in range(6)], "maxlag": 2})
        self.assertEqual(status, 200)
        self.assertEqual(data["maxlag"], 2)
        self.assertEqual([it["lag"] for it in data["items"]], [0, 1, 2])

    def test_endpoint_precision_and_unit(self):
        status, data = self._post("/api/autocorrelation", {
            "items": [{"value": v, "unit": "cm"} for v in (100, 200, 400)],
            "to": "m", "precision": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["items"][1]["autocorrelation"],
                         round(data["items"][1]["autocorrelation"], 3))

    def test_endpoint_not_a_list_400(self):
        status, data = self._post("/api/autocorrelation", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_single_item_400(self):
        status, data = self._post("/api/autocorrelation", {
            "items": [{"value": 1, "unit": "m"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_zero_variance_400(self):
        status, data = self._post("/api/autocorrelation", {
            "items": [{"value": 5, "unit": "m"} for _ in range(3)]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_maxlag_too_large_400(self):
        status, data = self._post("/api/autocorrelation", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3)], "maxlag": 9})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_cross_category_400(self):
        status, data = self._post("/api/autocorrelation", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_temperature_400(self):
        status, data = self._post("/api/autocorrelation", {
            "items": [{"value": 1, "unit": "c"}, {"value": 2, "unit": "c"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_invalid_json_400(self):
        status, data = self._post("/api/autocorrelation", None, raw=b"{bad")
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class TestDomainRobustZscore(unittest.TestCase):
    """Modified (Iglewicz-Hoaglin) z-score: median/MAD-standardised scores."""

    def test_basic_scores_and_centres(self):
        result = domain.robust_zscores(
            [{"value": v, "unit": "m"} for v in (10, 12, 14, 16, 18)])
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["count"], 5)
        self.assertEqual(result["median"], 14.0)
        self.assertEqual(result["mad"], 2.0)
        self.assertEqual(result["method"], "mad")
        self.assertEqual(result["threshold"], 3.5)
        # 0.6745 * (10 - 14) / 2 == -1.349
        self.assertAlmostEqual(result["items"][0]["robust_zscore"], -1.349, places=3)
        self.assertEqual(result["items"][2]["robust_zscore"], 0.0)
        self.assertEqual(result["outlier_count"], 0)

    def test_outlier_flagged(self):
        result = domain.robust_zscores(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5, 100)])
        self.assertEqual(result["median"], 3.5)
        self.assertEqual(result["mad"], 1.5)
        self.assertEqual(result["outlier_count"], 1)
        last = result["items"][-1]
        self.assertTrue(last["is_outlier"])
        self.assertGreater(abs(last["robust_zscore"]), 3.5)
        self.assertFalse(result["items"][0]["is_outlier"])

    def test_formula_matches_definition(self):
        values = (4.0, 7.0, 9.0, 11.0, 40.0)
        result = domain.robust_zscores([{"value": v, "unit": "m"} for v in values])
        median = result["median"]
        mad = result["mad"]
        for item, v in zip(result["items"], values):
            expected = domain.ROBUST_Z_CONSTANT * (v - median) / mad
            self.assertAlmostEqual(item["robust_zscore"], expected, places=9)

    def test_meanad_fallback_when_mad_zero(self):
        # Four values equal the median, so MAD collapses to 0 but the mean
        # absolute deviation still has spread -> the meanAD fallback kicks in.
        result = domain.robust_zscores(
            [{"value": v, "unit": "m"} for v in (5, 5, 5, 5, 9)])
        self.assertEqual(result["method"], "meanad")
        self.assertEqual(result["mad"], 0.0)
        self.assertAlmostEqual(result["mean_abs_deviation"], 0.8, places=9)
        expected = (9 - 5) / (domain.ROBUST_Z_MEANAD_CONSTANT * 0.8)
        self.assertAlmostEqual(result["items"][-1]["robust_zscore"], expected, places=9)

    def test_custom_threshold_changes_flags(self):
        loose = domain.robust_zscores(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5, 100)], threshold=50)
        self.assertEqual(loose["threshold"], 50.0)
        self.assertEqual(loose["outlier_count"], 0)

    def test_dimensionless_invariant_under_unit(self):
        in_m = domain.robust_zscores(
            [{"value": v, "unit": "m"} for v in (1, 2, 4, 8, 30)])
        in_cm = domain.robust_zscores(
            [{"value": v * 100, "unit": "cm"} for v in (1, 2, 4, 8, 30)], to_unit="m")
        a = [it["robust_zscore"] for it in in_m["items"]]
        b = [it["robust_zscore"] for it in in_cm["items"]]
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, places=9)

    def test_unit_conversion_reports_target_unit(self):
        result = domain.robust_zscores(
            [{"value": v, "unit": "cm"} for v in (100, 300, 500)], to_unit="m")
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["median"], 3.0)

    def test_tuple_items_accepted(self):
        result = domain.robust_zscores([(1, "m"), (2, "m"), (3, "m")])
        self.assertEqual(result["count"], 3)

    def test_single_item_meanad_zero_rejected(self):
        # One item: median == value, MAD == meanAD == 0 -> no spread.
        with self.assertRaises(ValueError):
            domain.robust_zscores([{"value": 7, "unit": "m"}])

    def test_all_identical_rejected(self):
        with self.assertRaises(ValueError):
            domain.robust_zscores([{"value": 5, "unit": "m"} for _ in range(4)])

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            domain.robust_zscores([])

    def test_threshold_zero_rejected(self):
        with self.assertRaises(ValueError):
            domain.robust_zscores(
                [{"value": v, "unit": "m"} for v in (1, 2, 3)], threshold=0)

    def test_threshold_negative_rejected(self):
        with self.assertRaises(ValueError):
            domain.robust_zscores(
                [{"value": v, "unit": "m"} for v in (1, 2, 3)], threshold=-1)

    def test_threshold_non_number_rejected(self):
        with self.assertRaises(ValueError):
            domain.robust_zscores(
                [{"value": v, "unit": "m"} for v in (1, 2, 3)], threshold="big")

    def test_threshold_bool_rejected(self):
        with self.assertRaises(ValueError):
            domain.robust_zscores(
                [{"value": v, "unit": "m"} for v in (1, 2, 3)], threshold=True)

    def test_cross_category_rejected(self):
        with self.assertRaises(ValueError):
            domain.robust_zscores(
                [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}])

    def test_temperature_rejected(self):
        with self.assertRaises(ValueError):
            domain.robust_zscores(
                [{"value": 1, "unit": "c"}, {"value": 2, "unit": "c"}])

    def test_fuel_rejected(self):
        with self.assertRaises(ValueError):
            domain.robust_zscores(
                [{"value": 30, "unit": "mpg"}, {"value": 40, "unit": "mpg"}])


class TestHttpRobustZscore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            data = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, data

    def test_endpoint_ok(self):
        status, data = self._post("/api/robust-zscore", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5, 100)]})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["count"], 6)
        self.assertEqual(data["median"], 3.5)
        self.assertEqual(data["mad"], 1.5)
        self.assertEqual(data["method"], "mad")
        self.assertEqual(data["threshold"], 3.5)
        self.assertEqual(data["outlier_count"], 1)
        self.assertTrue(data["items"][-1]["is_outlier"])
        self.assertFalse(data["items"][0]["is_outlier"])

    def test_endpoint_custom_threshold(self):
        status, data = self._post("/api/robust-zscore", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3, 4, 5, 100)],
            "threshold": 50})
        self.assertEqual(status, 200)
        self.assertEqual(data["threshold"], 50)
        self.assertEqual(data["outlier_count"], 0)

    def test_endpoint_precision_and_unit(self):
        status, data = self._post("/api/robust-zscore", {
            "items": [{"value": v, "unit": "cm"} for v in (100, 200, 400, 5000)],
            "to": "m", "precision": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "m")
        z = data["items"][0]["robust_zscore"]
        self.assertEqual(z, round(z, 3))

    def test_endpoint_meanad_fallback(self):
        status, data = self._post("/api/robust-zscore", {
            "items": [{"value": v, "unit": "m"} for v in (5, 5, 5, 5, 9)]})
        self.assertEqual(status, 200)
        self.assertEqual(data["method"], "meanad")
        self.assertEqual(data["mad"], 0.0)

    def test_endpoint_not_a_list_400(self):
        status, data = self._post("/api/robust-zscore", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_all_identical_400(self):
        status, data = self._post("/api/robust-zscore", {
            "items": [{"value": 5, "unit": "m"} for _ in range(3)]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_threshold_zero_400(self):
        status, data = self._post("/api/robust-zscore", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3)], "threshold": 0})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_cross_category_400(self):
        status, data = self._post("/api/robust-zscore", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_temperature_400(self):
        status, data = self._post("/api/robust-zscore", {
            "items": [{"value": 1, "unit": "c"}, {"value": 2, "unit": "c"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_invalid_json_400(self):
        status, data = self._post("/api/robust-zscore", None, raw=b"{bad")
        self.assertEqual(status, 400)
        self.assertIn("error", data)


class TestDomainInvNormalCdf(unittest.TestCase):
    """The probit helper underpinning the confidence interval."""

    def test_median_is_zero(self):
        self.assertAlmostEqual(domain._inv_normal_cdf(0.5), 0.0, places=12)

    def test_standard_two_sided_quantiles(self):
        # The textbook critical values (two-sided 90/95/99% -> p 0.95/0.975/0.995).
        self.assertAlmostEqual(domain._inv_normal_cdf(0.95), 1.6448536269514722, places=10)
        self.assertAlmostEqual(domain._inv_normal_cdf(0.975), 1.959963984540054, places=10)
        self.assertAlmostEqual(domain._inv_normal_cdf(0.995), 2.5758293035489004, places=10)

    def test_one_sigma_round_trips(self):
        # Phi(1) == 0.8413447460685429, so the probit of that is exactly 1.
        self.assertAlmostEqual(domain._inv_normal_cdf(0.8413447460685429), 1.0, places=10)

    def test_inverse_of_erf_cdf(self):
        # Round-trip against the true normal CDF built from math.erf.
        for z in (-2.3, -0.7, 0.4, 1.1, 2.8):
            p = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
            self.assertAlmostEqual(domain._inv_normal_cdf(p), z, places=9)

    def test_symmetry(self):
        self.assertAlmostEqual(
            domain._inv_normal_cdf(0.3), -domain._inv_normal_cdf(0.7), places=12)

    def test_out_of_range_raises(self):
        for bad in (0.0, 1.0, -0.1, 1.5):
            with self.assertRaises(ValueError):
                domain._inv_normal_cdf(bad)


class TestDomainConfidenceInterval(unittest.TestCase):
    """Normal-approximation confidence interval for the population mean."""

    def test_basic_interval(self):
        result = domain.confidence_interval(
            [{"value": v, "unit": "m"} for v in (10, 12, 14, 16, 18)])
        self.assertEqual(result["category"], "length")
        self.assertEqual(result["unit"], "m")
        self.assertEqual(result["count"], 5)
        self.assertEqual(result["confidence"], 0.95)
        self.assertAlmostEqual(result["mean"], 14.0, places=12)
        # sample stdev == sqrt(40/4) == sqrt(10); SE == sqrt(10)/sqrt(5) == sqrt(2).
        self.assertAlmostEqual(result["sample_stdev"], math.sqrt(10.0), places=12)
        self.assertAlmostEqual(result["standard_error"], math.sqrt(2.0), places=12)
        self.assertAlmostEqual(result["critical_value"], 1.959963984540054, places=10)
        expected_margin = 1.959963984540054 * math.sqrt(2.0)
        self.assertAlmostEqual(result["margin_of_error"], expected_margin, places=10)
        self.assertAlmostEqual(result["lower"], 14.0 - expected_margin, places=10)
        self.assertAlmostEqual(result["upper"], 14.0 + expected_margin, places=10)

    def test_interval_is_symmetric_about_the_mean(self):
        result = domain.confidence_interval(
            [{"value": v, "unit": "m"} for v in (3, 7, 11, 19)])
        self.assertAlmostEqual(
            (result["lower"] + result["upper"]) / 2.0, result["mean"], places=12)
        self.assertAlmostEqual(
            result["upper"] - result["mean"], result["margin_of_error"], places=12)

    def test_default_confidence_is_95_percent(self):
        explicit = domain.confidence_interval(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)], confidence=0.95)
        default = domain.confidence_interval(
            [{"value": v, "unit": "m"} for v in (1, 2, 3, 4)])
        self.assertEqual(default["confidence"], 0.95)
        self.assertAlmostEqual(
            default["margin_of_error"], explicit["margin_of_error"], places=12)

    def test_higher_confidence_widens_the_interval(self):
        data = [{"value": v, "unit": "m"} for v in (5, 10, 15, 20, 25)]
        narrow = domain.confidence_interval(data, confidence=0.90)
        wide = domain.confidence_interval(data, confidence=0.99)
        self.assertGreater(wide["critical_value"], narrow["critical_value"])
        self.assertGreater(wide["margin_of_error"], narrow["margin_of_error"])
        # The two intervals share the same point estimate and standard error.
        self.assertAlmostEqual(narrow["mean"], wide["mean"], places=12)
        self.assertAlmostEqual(
            narrow["standard_error"], wide["standard_error"], places=12)

    def test_unit_conversion_scales_the_interval(self):
        # The same physical sample expressed in cm but reported in m: the critical
        # value is dimensionless, while the mean / SE / bounds carry the unit.
        in_m = domain.confidence_interval(
            [{"value": v, "unit": "m"} for v in (1, 2, 3)])
        in_cm = domain.confidence_interval(
            [{"value": v * 100, "unit": "cm"} for v in (1, 2, 3)], to_unit="m")
        self.assertEqual(in_cm["unit"], "m")
        self.assertAlmostEqual(
            in_cm["critical_value"], in_m["critical_value"], places=12)
        self.assertAlmostEqual(in_cm["mean"], in_m["mean"], places=10)
        self.assertAlmostEqual(in_cm["lower"], in_m["lower"], places=10)
        self.assertAlmostEqual(in_cm["upper"], in_m["upper"], places=10)

    def test_one_sigma_confidence(self):
        # A confidence equal to the 1-sigma mass gives a critical value of exactly 1,
        # so the margin equals the standard error.
        result = domain.confidence_interval(
            [{"value": v, "unit": "m"} for v in (10, 20, 30, 40)],
            confidence=0.6826894921370859)
        self.assertAlmostEqual(result["critical_value"], 1.0, places=9)
        self.assertAlmostEqual(
            result["margin_of_error"], result["standard_error"], places=9)

    def test_tuple_items_accepted(self):
        result = domain.confidence_interval([(2, "kg"), (4, "kg"), (6, "kg")])
        self.assertEqual(result["category"], "mass")
        self.assertAlmostEqual(result["mean"], 4.0, places=12)

    def test_single_value_raises(self):
        with self.assertRaises(ValueError):
            domain.confidence_interval([{"value": 5, "unit": "m"}])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            domain.confidence_interval([])

    def test_confidence_out_of_range_raises(self):
        data = [{"value": v, "unit": "m"} for v in (1, 2, 3)]
        for bad in (0.0, 1.0, -0.5, 1.5):
            with self.assertRaises(ValueError):
                domain.confidence_interval(data, confidence=bad)

    def test_non_numeric_confidence_raises(self):
        data = [{"value": v, "unit": "m"} for v in (1, 2, 3)]
        with self.assertRaises(ValueError):
            domain.confidence_interval(data, confidence="lots")
        # Booleans are not accepted as a numeric confidence either.
        with self.assertRaises(ValueError):
            domain.confidence_interval(data, confidence=True)

    def test_cross_category_raises(self):
        with self.assertRaises(ValueError):
            domain.confidence_interval(
                [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}])

    def test_temperature_raises(self):
        with self.assertRaises(ValueError):
            domain.confidence_interval(
                [{"value": 1, "unit": "c"}, {"value": 2, "unit": "c"}])

    def test_fuel_raises(self):
        with self.assertRaises(ValueError):
            domain.confidence_interval(
                [{"value": 30, "unit": "mpg"}, {"value": 40, "unit": "mpg"}])


class TestHttpConfidenceInterval(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = server.make_server(0)
        cls.host, cls.port = cls.server.server_address
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def _post(self, path, payload, raw=None):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path), data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            data = json.loads(exc.read().decode("utf-8"))
            exc.close()
            return exc.code, data

    def test_endpoint_ok(self):
        status, data = self._post("/api/confidence-interval", {
            "items": [{"value": v, "unit": "m"} for v in (10, 12, 14, 16, 18)]})
        self.assertEqual(status, 200)
        self.assertEqual(data["category"], "length")
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["count"], 5)
        self.assertEqual(data["confidence"], 0.95)
        self.assertAlmostEqual(data["mean"], 14.0, places=6)
        self.assertAlmostEqual(data["critical_value"], 1.959964, places=5)
        self.assertLess(data["lower"], data["mean"])
        self.assertGreater(data["upper"], data["mean"])
        # mean is the midpoint of the interval.
        self.assertAlmostEqual(
            (data["lower"] + data["upper"]) / 2.0, data["mean"], places=6)

    def test_endpoint_custom_confidence(self):
        status, data = self._post("/api/confidence-interval", {
            "items": [{"value": v, "unit": "m"} for v in (5, 10, 15, 20, 25)],
            "confidence": 0.99})
        self.assertEqual(status, 200)
        self.assertEqual(data["confidence"], 0.99)
        self.assertAlmostEqual(data["critical_value"], 2.575829, places=5)

    def test_endpoint_precision_and_unit(self):
        status, data = self._post("/api/confidence-interval", {
            "items": [{"value": v, "unit": "cm"} for v in (100, 200, 300)],
            "to": "m", "precision": 3})
        self.assertEqual(status, 200)
        self.assertEqual(data["unit"], "m")
        self.assertEqual(data["mean"], round(data["mean"], 3))
        self.assertEqual(data["margin_of_error"], round(data["margin_of_error"], 3))

    def test_endpoint_not_a_list_400(self):
        status, data = self._post("/api/confidence-interval", {"items": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_single_value_400(self):
        status, data = self._post("/api/confidence-interval", {
            "items": [{"value": 5, "unit": "m"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_bad_confidence_400(self):
        status, data = self._post("/api/confidence-interval", {
            "items": [{"value": v, "unit": "m"} for v in (1, 2, 3)],
            "confidence": 1.5})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_cross_category_400(self):
        status, data = self._post("/api/confidence-interval", {
            "items": [{"value": 1, "unit": "m"}, {"value": 2, "unit": "kg"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_temperature_400(self):
        status, data = self._post("/api/confidence-interval", {
            "items": [{"value": 1, "unit": "c"}, {"value": 2, "unit": "c"}]})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_endpoint_invalid_json_400(self):
        status, data = self._post("/api/confidence-interval", None, raw=b"{bad")
        self.assertEqual(status, 400)
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()
