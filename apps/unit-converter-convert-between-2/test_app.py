"""Test suite for the multi-category unit converter — stdlib unittest only.

Covers the pure domain logic (``domain.py``), the legacy meters<->feet helpers
that still live in ``server.py``, and the live HTTP API served by
``make_server``. Run with:  python3 -m unittest -v
"""

import json
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


if __name__ == "__main__":
    unittest.main()
