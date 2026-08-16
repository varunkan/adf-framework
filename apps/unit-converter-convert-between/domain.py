"""Conversion engine for the unit converter.

Pure functions, Python 3 standard library only. No I/O, no globals mutated.

Two families of conversion live here:

1. Temperature (Celsius / Fahrenheit / Kelvin) — these are *affine* scales
   (they have an offset, not just a multiplier), so they are converted via a
   canonical base of Celsius rather than a single factor.

2. Linear-factor categories (length, mass, volume) — every unit is expressed
   as a multiple of a category base unit (metre, kilogram, litre), so a
   conversion is value * factor[from] / factor[to].

The original temperature helpers ``c_to_f`` / ``f_to_c`` are preserved in
server.py for backwards compatibility; the richer logic here is additive.
"""

import math
import re
from decimal import Decimal, InvalidOperation

# --------------------------------------------------------------------------
# Temperature — affine scales, converted through a Celsius base.
# --------------------------------------------------------------------------

# Map of the legacy/extended direction aliases the API accepts.
TEMPERATURE_DIRECTIONS = {
    "c2f": ("C", "F"), "ctof": ("C", "F"), "celsius-to-fahrenheit": ("C", "F"),
    "f2c": ("F", "C"), "ftoc": ("F", "C"), "fahrenheit-to-celsius": ("F", "C"),
    "c2k": ("C", "K"), "ctok": ("C", "K"), "celsius-to-kelvin": ("C", "K"),
    "k2c": ("K", "C"), "ktoc": ("K", "C"), "kelvin-to-celsius": ("K", "C"),
    "f2k": ("F", "K"), "ftok": ("F", "K"), "fahrenheit-to-kelvin": ("F", "K"),
    "k2f": ("K", "F"), "ktof": ("K", "F"), "kelvin-to-fahrenheit": ("K", "F"),
}

ABSOLUTE_ZERO_C = -273.15


def to_celsius(value, scale):
    scale = scale.upper()
    if scale == "C":
        return float(value)
    if scale == "F":
        return (float(value) - 32.0) * 5.0 / 9.0
    if scale == "K":
        return float(value) - 273.15
    raise ValueError("unknown temperature scale: %r" % (scale,))


def from_celsius(celsius, scale):
    scale = scale.upper()
    if scale == "C":
        return float(celsius)
    if scale == "F":
        return float(celsius) * 9.0 / 5.0 + 32.0
    if scale == "K":
        return float(celsius) + 273.15
    raise ValueError("unknown temperature scale: %r" % (scale,))


def convert_temperature(value, from_scale, to_scale):
    """Convert ``value`` from one temperature scale to another."""
    celsius = to_celsius(value, from_scale)
    return from_celsius(celsius, to_scale)


def convert_direction(value, direction):
    """Convert using a direction alias such as ``c2f`` or ``k2f``.

    Returns ``(result, target_unit_letter)``. Raises ``KeyError`` if the
    direction is not recognised.
    """
    from_scale, to_scale = TEMPERATURE_DIRECTIONS[direction]
    return convert_temperature(value, from_scale, to_scale), to_scale


TEMPERATURE_SCALES = ("C", "F", "K")


def convert_temperature_all(value, from_scale):
    """Convert ``value`` from ``from_scale`` into every temperature scale.

    Returns a dict mapping each of ``C``/``F``/``K`` to the converted value
    (the source scale is included for symmetry, like :func:`convert_all`).
    Raises ``ValueError`` for an unknown source scale. Reuses
    :func:`convert_temperature` so the maths lives in one place.
    """
    from_scale = str(from_scale).upper()
    if from_scale not in TEMPERATURE_SCALES:
        raise ValueError("unknown temperature scale: %r" % (from_scale,))
    return {
        scale: convert_temperature(value, from_scale, scale)
        for scale in TEMPERATURE_SCALES
    }


# --------------------------------------------------------------------------
# Linear-factor categories — value expressed as a multiple of the base unit.
# --------------------------------------------------------------------------

# Each factor is "how many base units one of this unit equals".
LENGTH_UNITS = {  # base: metre
    "m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001,
    "mi": 1609.344, "yd": 0.9144, "ft": 0.3048, "in": 0.0254,
}

MASS_UNITS = {  # base: kilogram
    "kg": 1.0, "g": 0.001, "mg": 1e-6, "t": 1000.0,
    "lb": 0.45359237, "oz": 0.028349523125,
}

VOLUME_UNITS = {  # base: litre (US customary for gal/qt/pt/cup/floz)
    "l": 1.0, "ml": 0.001,
    "gal": 3.785411784, "qt": 0.946352946, "pt": 0.473176473,
    "cup": 0.2365882365, "floz": 0.0295735295625,
    # US cooking measures: a tablespoon is half a fluid ounce, a teaspoon a
    # sixth — kept exact (floz / 2 and floz / 6) so tbsp == 3 tsp by construction.
    "tbsp": 0.0295735295625 / 2.0, "tsp": 0.0295735295625 / 6.0,
}

AREA_UNITS = {  # base: square metre
    "m2": 1.0, "km2": 1_000_000.0, "cm2": 1e-4, "mm2": 1e-6,
    "ha": 10_000.0, "acre": 4046.8564224,
    "ft2": 0.09290304, "in2": 0.00064516, "yd2": 0.83612736,
    "mi2": 2_589_988.110336,
}

SPEED_UNITS = {  # base: metre per second
    "mps": 1.0,
    "kph": 1000.0 / 3600.0,
    "mph": 1609.344 / 3600.0,
    "fps": 0.3048,
    "kn": 1852.0 / 3600.0,  # knot (international nautical mile/hour)
}

TIME_UNITS = {  # base: second
    "ms": 0.001, "s": 1.0, "min": 60.0,
    "h": 3600.0, "d": 86_400.0, "wk": 604_800.0,
}

DATA_UNITS = {  # base: byte (decimal SI multiples + binary IEC multiples)
    "b": 1.0,
    "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12,
    "kib": 1024.0, "mib": 1024.0 ** 2, "gib": 1024.0 ** 3, "tib": 1024.0 ** 4,
}

PRESSURE_UNITS = {  # base: pascal
    "pa": 1.0, "kpa": 1000.0, "hpa": 100.0, "mpa": 1_000_000.0,
    "bar": 100_000.0, "mbar": 100.0,
    "atm": 101_325.0,
    "psi": 6894.757293168361,
    "mmhg": 133.322387415,
    "torr": 101_325.0 / 760.0,
}

ENERGY_UNITS = {  # base: joule
    "j": 1.0, "kj": 1000.0, "mj": 1_000_000.0,
    "cal": 4.184, "kcal": 4184.0,  # thermochemical calorie
    "wh": 3600.0, "kwh": 3_600_000.0,
    "btu": 1055.05585262,  # ISO 31-4 British thermal unit
    "ev": 1.602176634e-19,
}

# Angle — radian base. (Pure ratios, so a plain linear factor is exact.)
ANGLE_UNITS = {  # base: radian
    "rad": 1.0,
    "deg": math.pi / 180.0,
    "grad": math.pi / 200.0,
    "turn": 2.0 * math.pi,
    "arcmin": math.pi / 180.0 / 60.0,
    "arcsec": math.pi / 180.0 / 3600.0,
}

POWER_UNITS = {  # base: watt
    "w": 1.0, "kw": 1000.0, "gw": 1_000_000_000.0,
    "hp": 745.6998715822702,  # mechanical (imperial) horsepower
    "ps": 735.49875,          # metric horsepower (Pferdestärke)
}

FORCE_UNITS = {  # base: newton
    "n": 1.0, "kgf": 9.80665, "lbf": 4.4482216152605, "dyn": 1e-5,
}

FREQUENCY_UNITS = {  # base: hertz
    "hz": 1.0, "khz": 1e3, "mhz": 1e6, "ghz": 1e9, "thz": 1e12,
    "rpm": 1.0 / 60.0,  # revolutions per minute
}

ILLUMINANCE_UNITS = {  # base: lux (lumen per square metre)
    "lux": 1.0,
    "fc": 10.763910416709722,  # foot-candle (lumen per square foot)
    "ph": 10_000.0,            # phot (lumen per square centimetre)
}

BANDWIDTH_UNITS = {  # base: bit per second (decimal SI multiples)
    "bps": 1.0, "kbps": 1e3, "mbps": 1e6, "gbps": 1e9, "tbps": 1e12,
}

# Torque shares dimensions with energy (newton-metre = joule) but is a distinct
# physical quantity with its own units, so it gets its own category. The unit
# tokens are deliberately disjoint from ENERGY_UNITS so find_category stays
# unambiguous.
TORQUE_UNITS = {  # base: newton-metre
    "nm": 1.0,
    "kgfm": 9.80665,            # kilogram-force metre
    "lbft": 1.3558179483314004,  # pound-force foot
    "ozin": 1.3558179483314004 / 192.0,  # ounce-force inch (lbf·ft / 192)
}

ACCELERATION_UNITS = {  # base: metre per second squared
    "mps2": 1.0,
    "ftps2": 0.3048,          # foot per second squared
    "ips2": 0.0254,           # inch per second squared
    "g0": 9.80665,            # standard gravity
    "galileo": 0.01,          # Gal (cm per second squared), CGS acceleration
}

DENSITY_UNITS = {  # base: kilogram per cubic metre
    "kgm3": 1.0,
    "gcm3": 1000.0,           # gram per cubic centimetre (== kg/L)
    "gl": 1.0,                # gram per litre
    "lbft3": 16.018463373960138,   # pound per cubic foot
    "lbin3": 27679.904710203125,   # pound per cubic inch
}

FLOWRATE_UNITS = {  # base: cubic metre per second (volumetric flow)
    "m3s": 1.0,
    "m3h": 1.0 / 3600.0,                       # cubic metre per hour
    "ls": 0.001,                               # litre per second
    "lmin": 0.001 / 60.0,                      # litre per minute
    "gpm": 3.785411784e-3 / 60.0,              # US gallon per minute
    "cfm": 0.028316846592 / 60.0,              # cubic foot per minute
}

CHARGE_UNITS = {  # base: coulomb (battery capacity lives here as amp-hours)
    "coul": 1.0, "mcoul": 1e-3, "ucoul": 1e-6,
    "ah": 3600.0,   # ampere-hour: 1 A flowing for 1 h == 3600 C
    "mah": 3.6,     # milliampere-hour (the unit printed on every battery)
}

# Pace is the *inverse* of speed (time per distance, not distance per time), but
# between two pace units it is still a plain linear factor: min/mi == min/km
# scaled by the miles-in-a-kilometre ratio. So it rides the linear-factor path
# with a canonical base of minutes-per-kilometre rather than getting a bespoke
# engine like fuel economy (which mixes a reciprocal unit, l100km, into its set).
PACE_UNITS = {  # base: minute per kilometre
    "minkm": 1.0,
    "minmi": 1.0 / 1.609344,          # minute per mile
    "seckm": 1.0 / 60.0,              # second per kilometre
    "secmi": (1.0 / 1.609344) / 60.0,  # second per mile
}

# Electrical quantities — a cohesive linear-factor trio (the V = I * R triple).
# Each rides the same metric-prefix scaling as the physical categories above, so
# they need no bespoke engine: a millivolt is just 1e-3 volt. The unit tokens are
# disjoint from every other category (checked in find_category) AND from the
# temperature/fuel aliases, so smart_convert and the expression parser route
# them through the linear path rather than mis-firing on a stray "f"/"c"/"k".
VOLTAGE_UNITS = {  # base: volt
    "v": 1.0, "mv": 1e-3, "kv": 1e3, "uv": 1e-6,
}

CURRENT_UNITS = {  # base: ampere
    "a": 1.0, "ma": 1e-3, "ka": 1e3, "ua": 1e-6,
}

RESISTANCE_UNITS = {  # base: ohm
    "ohm": 1.0, "mohm": 1e-3, "kohm": 1e3, "megohm": 1e6,
}

# Electromagnetic quantities — the natural extension of the V/I/R trio above.
# Each is a plain metric-prefix ladder over an SI base, so they ride the same
# linear-factor path: a microfarad is just 1e-6 farad, a milligauss 1e-7 tesla.
# Their unit tokens are spelled out (farad/henry/weber/tesla rather than the
# single letters F/H/Wb/T) so they stay disjoint from every existing token AND
# from the temperature scale letters, keeping find_category and smart_convert
# unambiguous.
CAPACITANCE_UNITS = {  # base: farad
    "farad": 1.0, "mfarad": 1e-3, "ufarad": 1e-6, "nfarad": 1e-9, "pfarad": 1e-12,
}

INDUCTANCE_UNITS = {  # base: henry
    "henry": 1.0, "mhenry": 1e-3, "uhenry": 1e-6, "nhenry": 1e-9,
}

# Magnetic flux — base weber. The maxwell is the CGS unit (1 Mx == 1e-8 Wb).
MAGFLUX_UNITS = {  # base: weber
    "weber": 1.0, "mweber": 1e-3, "uweber": 1e-6, "maxwell": 1e-8,
}

# Magnetic flux density — base tesla. The gauss is the CGS unit (1 G == 1e-4 T);
# milligauss (1e-7 T) is the everyday unit for ambient/EMF measurements.
MAGFLUXDENSITY_UNITS = {  # base: tesla
    "tesla": 1.0, "mtesla": 1e-3, "utesla": 1e-6, "gauss": 1e-4, "mgauss": 1e-7,
}

# Typography — the digital-print length family. Lengths here are sub-categories
# of a metre too, but the trade speaks its own units (a point is 1/72 inch, a
# pixel the CSS reference pixel of 1/96 inch) and never mixes them with metric
# rulers, so it rides the linear-factor path as a self-contained category with a
# canonical base of the typographic point. Its tokens are spelled out (point /
# pica / px / twip) so they stay disjoint from every existing token — notably the
# volume pint "pt" — keeping find_category unambiguous.
TYPOGRAPHY_UNITS = {  # base: typographic point (1/72 inch)
    "point": 1.0,
    "pica": 12.0,    # 1 pica == 12 points
    "px": 0.75,      # CSS reference pixel: 1px == 1/96 inch == 0.75 point
    "twip": 0.05,    # twentieth of a point (the Word/RTF layout unit)
}

CATEGORIES = {
    "length": LENGTH_UNITS,
    "mass": MASS_UNITS,
    "volume": VOLUME_UNITS,
    "area": AREA_UNITS,
    "speed": SPEED_UNITS,
    "time": TIME_UNITS,
    "data": DATA_UNITS,
    "pressure": PRESSURE_UNITS,
    "energy": ENERGY_UNITS,
    "angle": ANGLE_UNITS,
    "power": POWER_UNITS,
    "force": FORCE_UNITS,
    "frequency": FREQUENCY_UNITS,
    "illuminance": ILLUMINANCE_UNITS,
    "bandwidth": BANDWIDTH_UNITS,
    "torque": TORQUE_UNITS,
    "acceleration": ACCELERATION_UNITS,
    "density": DENSITY_UNITS,
    "flowrate": FLOWRATE_UNITS,
    "charge": CHARGE_UNITS,
    "pace": PACE_UNITS,
    "voltage": VOLTAGE_UNITS,
    "current": CURRENT_UNITS,
    "resistance": RESISTANCE_UNITS,
    "capacitance": CAPACITANCE_UNITS,
    "inductance": INDUCTANCE_UNITS,
    "magflux": MAGFLUX_UNITS,
    "magfluxdensity": MAGFLUXDENSITY_UNITS,
    "typography": TYPOGRAPHY_UNITS,
}


def find_category(unit):
    """Return the category name that owns ``unit``, or None."""
    unit = unit.lower()
    for name, units in CATEGORIES.items():
        if unit in units:
            return name
    return None


def convert_units(value, from_unit, to_unit):
    """Convert a linear-factor quantity from ``from_unit`` to ``to_unit``.

    Both units must belong to the same category. Returns ``(result, category)``.
    Raises ``ValueError`` for unknown or mismatched units.
    """
    from_unit = from_unit.lower()
    to_unit = to_unit.lower()
    from_cat = find_category(from_unit)
    to_cat = find_category(to_unit)
    if from_cat is None:
        raise ValueError("unknown unit: %r" % (from_unit,))
    if to_cat is None:
        raise ValueError("unknown unit: %r" % (to_unit,))
    if from_cat != to_cat:
        raise ValueError(
            "cannot convert %s (%s) to %s (%s): different categories"
            % (from_unit, from_cat, to_unit, to_cat)
        )
    factors = CATEGORIES[from_cat]
    base = float(value) * factors[from_unit]
    return base / factors[to_unit], from_cat


def convert_all(value, from_unit):
    """Convert ``value`` from ``from_unit`` into *every* unit in its category.

    Returns ``(results, category)`` where ``results`` is a dict mapping every
    unit in the category (including ``from_unit`` itself) to the converted
    value. Raises ``ValueError`` for an unknown unit. This reuses
    :func:`convert_units` so the conversion maths lives in exactly one place.
    """
    from_unit = from_unit.lower()
    category = find_category(from_unit)
    if category is None:
        raise ValueError("unknown unit: %r" % (from_unit,))
    results = {
        unit: convert_units(value, from_unit, unit)[0]
        for unit in CATEGORIES[category]
    }
    return results, category


def convert_batch(items):
    """Convert a list of ``{"value", "from", "to"}`` requests in one call.

    Each item is converted independently: one malformed or mismatched item
    never aborts the rest. Returns a list of result dicts in the same order,
    each either ``{"ok": True, ...}`` or ``{"ok": False, "error": msg}``.
    Reuses :func:`convert_units` so the maths lives in exactly one place.
    """
    out = []
    for item in items:
        if not isinstance(item, dict):
            out.append({"ok": False, "error": "each item must be an object"})
            continue
        value = item.get("value")
        from_unit = item.get("from")
        to_unit = item.get("to")
        if value is None or from_unit is None or to_unit is None:
            out.append({"ok": False, "error": "missing 'value', 'from', or 'to'"})
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            out.append({"ok": False, "error": "'value' must be a number"})
            continue
        if numeric != numeric or numeric in (float("inf"), float("-inf")):
            out.append({"ok": False, "error": "'value' must be a finite number"})
            continue
        try:
            result, category = convert_units(numeric, str(from_unit), str(to_unit))
        except ValueError as exc:
            out.append({"ok": False, "error": str(exc)})
            continue
        if not math.isfinite(result):
            # A finite input can overflow while scaling; never hand a non-finite
            # result to json.dumps (it emits the invalid JSON literal Infinity).
            out.append({"ok": False, "error": "conversion result is out of range (overflowed)"})
            continue
        out.append({
            "ok": True,
            "input": numeric,
            "from": str(from_unit).lower(),
            "to": str(to_unit).lower(),
            "category": category,
            "result": result,
        })
    return out


# --------------------------------------------------------------------------
# Fuel economy — a *reciprocal* relationship, not a linear factor.
#
# ``l100km`` (litres per 100 km) measures consumption: smaller is better, and
# it is the inverse of an efficiency such as km/litre. Because of that inverse,
# fuel economy cannot ride the linear-factor ``convert_units`` path; it gets a
# dedicated converter that routes through a canonical *efficiency* base of
# kilometres-per-litre, exactly as temperature routes through Celsius.
# --------------------------------------------------------------------------

MILE_KM = 1.609344          # one statute mile in kilometres
GALLON_US_L = 3.785411784   # one US gallon in litres
GALLON_IMP_L = 4.54609      # one imperial gallon in litres

KMPL_PER_MPG_US = MILE_KM / GALLON_US_L
KMPL_PER_MPG_IMP = MILE_KM / GALLON_IMP_L

# The accepted fuel-economy units (kept apart from CATEGORIES on purpose so the
# linear-factor machinery never tries to resolve them).
FUEL_UNITS = ("mpg", "mpgimp", "kmpl", "l100km")


def _fuel_to_kmpl(value, unit):
    """Express a fuel-economy ``value`` as kilometres per litre (efficiency)."""
    v = float(value)
    if unit == "kmpl":
        return v
    if unit == "mpg":
        return v * KMPL_PER_MPG_US
    if unit == "mpgimp":
        return v * KMPL_PER_MPG_IMP
    if unit == "l100km":
        if v == 0:
            raise ValueError("fuel economy of 0 l100km is undefined")
        return 100.0 / v
    raise ValueError("unknown fuel unit: %r" % (unit,))


def _fuel_from_kmpl(kmpl, unit):
    """Express an efficiency in kilometres per litre as ``unit``."""
    if unit == "kmpl":
        return kmpl
    if unit == "mpg":
        return kmpl / KMPL_PER_MPG_US
    if unit == "mpgimp":
        return kmpl / KMPL_PER_MPG_IMP
    if unit == "l100km":
        if kmpl == 0:
            raise ValueError("fuel economy of 0 kmpl is undefined")
        return 100.0 / kmpl
    raise ValueError("unknown fuel unit: %r" % (unit,))


def convert_fuel(value, from_unit, to_unit):
    """Convert a fuel-economy ``value`` between consumption/efficiency units.

    Both units must be members of :data:`FUEL_UNITS`. Returns
    ``(result, "fuel")``. Raises ``ValueError`` for unknown units or for the
    undefined zero case (an infinite economy). Routing through a km/litre base
    keeps the reciprocal maths in exactly one place.
    """
    from_unit = str(from_unit).lower()
    to_unit = str(to_unit).lower()
    if from_unit not in FUEL_UNITS:
        raise ValueError("unknown fuel unit: %r" % (from_unit,))
    if to_unit not in FUEL_UNITS:
        raise ValueError("unknown fuel unit: %r" % (to_unit,))
    kmpl = _fuel_to_kmpl(value, from_unit)
    return _fuel_from_kmpl(kmpl, to_unit), "fuel"


# --------------------------------------------------------------------------
# Number bases — a *positional-notation* conversion, not a magnitude scaling.
#
# Binary/octal/decimal/hexadecimal aren't units of a physical quantity: the
# value is the same integer regardless of base, only its written form changes.
# So this family lives outside CATEGORIES (a linear factor would be nonsense)
# and converts by parsing the source string to a Python int and re-rendering it
# in the target radix, exactly as temperature/fuel get their own engines.
# --------------------------------------------------------------------------

BASES = {
    "bin": 2, "binary": 2,
    "oct": 8, "octal": 8,
    "dec": 10, "decimal": 10,
    "hex": 16, "hexadecimal": 16,
}

# Canonical short name per radix, used when rendering results back to the caller.
_BASE_NAME = {2: "bin", 8: "oct", 10: "dec", 16: "hex"}


def _render_int(number, radix):
    """Render a Python int ``number`` in ``radix`` (2/8/10/16) without a prefix.

    Negative numbers keep a leading ``-``; the digits themselves are lower-case
    for hex so the output is stable and comparable.
    """
    if radix == 10:
        return str(number)
    sign = "-" if number < 0 else ""
    magnitude = abs(number)
    digits = "0123456789abcdef"
    if magnitude == 0:
        return "0"
    out = []
    while magnitude:
        magnitude, rem = divmod(magnitude, radix)
        out.append(digits[rem])
    return sign + "".join(reversed(out))


def convert_base(value, from_base, to_base):
    """Convert an integer written in ``from_base`` into ``to_base``.

    ``value`` is a string (or int) of digits in the source radix; an optional
    ``0x``/``0o``/``0b`` prefix and surrounding whitespace are tolerated.
    Returns ``(result_string, canonical_to_base)``. Raises ``ValueError`` for an
    unknown base name or a digit that is invalid for the source radix.
    """
    f = str(from_base).strip().lower()
    t = str(to_base).strip().lower()
    if f not in BASES:
        raise ValueError("unknown base: %r" % (from_base,))
    if t not in BASES:
        raise ValueError("unknown base: %r" % (to_base,))
    from_radix = BASES[f]
    to_radix = BASES[t]

    text = str(value).strip()
    if text == "":
        raise ValueError("missing value to convert")
    # int(..., base) already strips a matching 0x/0o/0b prefix, so we let it do
    # the parsing and lean on its own error for an out-of-range digit.
    try:
        number = int(text, from_radix)
    except ValueError:
        raise ValueError(
            "%r is not a valid base-%d integer" % (text, from_radix)
        )
    return _render_int(number, to_radix), _BASE_NAME[to_radix]


# --------------------------------------------------------------------------
# Roman numerals — a *symbolic* notation, like number bases but with no radix.
#
# A Roman numeral encodes the same integer as a decimal string; only the glyphs
# differ. So, exactly like ``convert_base``, this family lives outside CATEGORIES
# (a linear factor would be meaningless) and converts by parsing to a Python int
# and re-rendering. Classical numerals address 1..3999 — there is no zero or
# negative, and 4000+ needs an overline that plain text can't represent — so the
# range is enforced rather than silently producing nonsense.
# --------------------------------------------------------------------------

ROMAN_MIN = 1
ROMAN_MAX = 3999

# Ordered high→low so greedy subtraction renders the canonical (shortest) form;
# the subtractive pairs (CM, CD, XC, XL, IX, IV) are included as their own steps.
_ROMAN_TABLE = (
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
)

# Canonical numeral for each value 1..3999, used to reject non-canonical input
# such as "IIII" or "IM" by comparing against the one true rendering.
_ROMAN_VALUE = {numeral: value for value, numeral in _ROMAN_TABLE}


def int_to_roman(number):
    """Render an integer in ``ROMAN_MIN..ROMAN_MAX`` as a Roman numeral string.

    Greedy subtraction against :data:`_ROMAN_TABLE` yields the canonical
    (shortest) form. Raises ``ValueError`` outside the representable range.
    """
    if isinstance(number, float) and not number.is_integer():
        raise ValueError("Roman numerals represent whole numbers only")
    try:
        n = int(number)
    except (TypeError, ValueError):
        raise ValueError("%r is not an integer" % (number,))
    if n < ROMAN_MIN or n > ROMAN_MAX:
        raise ValueError(
            "Roman numerals cover %d..%d only" % (ROMAN_MIN, ROMAN_MAX)
        )
    out = []
    for value, numeral in _ROMAN_TABLE:
        while n >= value:
            out.append(numeral)
            n -= value
    return "".join(out)


def roman_to_int(text):
    """Parse a Roman numeral string into its integer value.

    Only the canonical form is accepted: the input is round-tripped through
    :func:`int_to_roman` and rejected if it does not match, so malformed
    numerals such as ``"IIII"``, ``"IC"`` or ``"VV"`` raise ``ValueError``.
    """
    s = str(text).strip().upper()
    if s == "":
        raise ValueError("missing Roman numeral to convert")
    total = 0
    prev = 0
    for ch in reversed(s):
        if ch not in _ROMAN_VALUE:
            raise ValueError("%r is not a valid Roman numeral" % (text,))
        value = _ROMAN_VALUE[ch]
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    if not (ROMAN_MIN <= total <= ROMAN_MAX) or int_to_roman(total) != s:
        raise ValueError("%r is not a valid Roman numeral" % (text,))
    return total


def convert_roman(value, from_kind, to_kind):
    """Convert between an Arabic integer and a Roman numeral.

    ``from_kind``/``to_kind`` are ``"arabic"`` (decimal int) or ``"roman"``.
    Returns ``(result, "roman")`` where ``result`` is a string in the target
    notation. Routing both directions through a Python ``int`` keeps the parsing
    and rendering each in exactly one place. Raises ``ValueError`` for an unknown
    kind, an out-of-range integer, or a malformed numeral.
    """
    f = str(from_kind).strip().lower()
    t = str(to_kind).strip().lower()
    kinds = ("arabic", "roman")
    if f not in kinds:
        raise ValueError("unknown notation: %r" % (from_kind,))
    if t not in kinds:
        raise ValueError("unknown notation: %r" % (to_kind,))

    number = roman_to_int(value) if f == "roman" else None
    if number is None:
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError("%r is not an integer" % (value,))

    if t == "roman":
        return int_to_roman(number), "roman"
    return str(number), "roman"


# --------------------------------------------------------------------------
# Number words — a *lexical* notation, the closest sibling to Roman numerals.
#
# Like number bases and Roman numerals, an English number name encodes the same
# integer as a decimal string; only the glyphs change: ``42``, ``"forty-two"``
# and ``"XLII"`` all name the same value. So this family lives outside CATEGORIES
# (a linear factor would be meaningless) and converts by parsing the words to a
# Python int and re-rendering — exactly as ``convert_base`` routes through an int.
# The range spans the U.S. short scale up to (but not including) one quadrillion,
# in both signs and including zero, so the four grouping scales
# thousand/million/billion/trillion cover every representable value.
# --------------------------------------------------------------------------

WORDS_MAX = 10 ** 15 - 1            # 999,999,999,999,999 — just under a quadrillion
WORDS_MIN = -WORDS_MAX

_ONES = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
)

_TENS = (
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
)

# Grouping scales, smallest first: group index ``i`` multiplies its 3-digit
# value by ``1000 ** i``. The empty leading entry is the units group (no word).
_SCALES = ("", "thousand", "million", "billion", "trillion")

# Reverse lookup for the parser: every atomic number word -> its value, plus a
# separate scale map (hundred is handled specially because it multiplies).
_WORD_VALUE = {name: value for value, name in enumerate(_ONES)}
_WORD_VALUE.update({name: i * 10 for i, name in enumerate(_TENS) if name})
_SCALE_VALUE = {
    "thousand": 10 ** 3, "million": 10 ** 6,
    "billion": 10 ** 9, "trillion": 10 ** 12,
}


def _three_digits_to_words(n):
    """Render an integer in 1..999 as English words (no surrounding space)."""
    parts = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        parts.append(_ONES[hundreds] + " hundred")
    if rest:
        if rest < 20:
            parts.append(_ONES[rest])
        else:
            tens, ones = divmod(rest, 10)
            parts.append(_TENS[tens] + ("-" + _ONES[ones] if ones else ""))
    return " ".join(parts)


def int_to_words(number):
    """Render an integer in ``WORDS_MIN..WORDS_MAX`` as English words.

    Zero renders as ``"zero"`` and negatives gain a leading ``"negative "``.
    Uses the U.S. short scale with no ``"and"`` (so 101 is "one hundred one")
    and hyphenated compound tens ("forty-two"). Raises ``ValueError`` outside the
    representable range or for a non-integer value.
    """
    if isinstance(number, float) and not number.is_integer():
        raise ValueError("number words represent whole numbers only")
    try:
        n = int(number)
    except (TypeError, ValueError):
        raise ValueError("%r is not an integer" % (number,))
    if n < WORDS_MIN or n > WORDS_MAX:
        raise ValueError("number words cover %d..%d only" % (WORDS_MIN, WORDS_MAX))
    if n == 0:
        return "zero"
    sign = "negative " if n < 0 else ""
    magnitude = abs(n)

    # Break into 3-digit groups, least-significant first.
    groups = []
    while magnitude:
        magnitude, group = divmod(magnitude, 1000)
        groups.append(group)

    chunks = []
    for i in range(len(groups) - 1, -1, -1):
        group = groups[i]
        if group == 0:
            continue
        words = _three_digits_to_words(group)
        scale = _SCALES[i]
        chunks.append(words + (" " + scale if scale else ""))
    return sign + " ".join(chunks)


def words_to_int(text):
    """Parse English number words into their integer value.

    Accepts exactly the forms :func:`int_to_words` produces, plus a few
    everyday conveniences: a leading ``"negative"`` or ``"minus"``, hyphenated or
    space-separated tens ("forty-two" / "forty two"), and a tolerated British
    ``"and"`` ("one hundred and one"). Only canonical phrasings survive — the
    parse is round-tripped through :func:`int_to_words` and rejected on any
    mismatch, so junk such as "ten hundred", "two two" or "negative zero" raises
    ``ValueError``.
    """
    s = str(text).strip().lower()
    if s == "":
        raise ValueError("missing number words to convert")

    # Normalise to a canonical token stream: hyphens become spaces, the British
    # filler "and" is dropped, and "minus" is folded onto "negative" so the
    # round-trip comparison below has a single spelling to match against.
    norm_tokens = []
    for tok in s.replace("-", " ").split():
        if tok == "and":
            continue
        norm_tokens.append("negative" if tok == "minus" else tok)
    if not norm_tokens:
        raise ValueError("%r is not a valid number phrase" % (text,))

    sign = 1
    tokens = norm_tokens
    if tokens[0] == "negative":
        sign = -1
        tokens = tokens[1:]
    if not tokens:
        raise ValueError("%r is not a valid number phrase" % (text,))

    total = 0
    current = 0
    for tok in tokens:
        if tok == "hundred":
            current = (current or 1) * 100
        elif tok in _SCALE_VALUE:
            total += current * _SCALE_VALUE[tok]
            current = 0
        elif tok in _WORD_VALUE:
            current += _WORD_VALUE[tok]
        else:
            raise ValueError("%r is not a valid number word" % (tok,))
    value = sign * (total + current)
    if value < WORDS_MIN or value > WORDS_MAX:
        raise ValueError("number words cover %d..%d only" % (WORDS_MIN, WORDS_MAX))

    # Reject non-canonical phrasings (bare "hundred", "ten hundred", "two two",
    # trailing scale words) by comparing against the one true rendering, hyphens
    # normalised to spaces so "forty-two" and "forty two" both match.
    canonical = int_to_words(value).replace("-", " ")
    if " ".join(norm_tokens) != canonical:
        raise ValueError("%r is not a canonical number phrase" % (text,))
    return value


def convert_words(value, from_kind, to_kind):
    """Convert between an Arabic integer and its English number words.

    ``from_kind``/``to_kind`` are ``"arabic"`` (decimal int) or ``"words"``.
    Returns ``(result, "words")`` where ``result`` is a string in the target
    notation. Routing both directions through a Python ``int`` keeps the parsing
    and rendering each in exactly one place. Raises ``ValueError`` for an unknown
    kind, an out-of-range integer, or a malformed phrase.
    """
    f = str(from_kind).strip().lower()
    t = str(to_kind).strip().lower()
    kinds = ("arabic", "words")
    if f not in kinds:
        raise ValueError("unknown notation: %r" % (from_kind,))
    if t not in kinds:
        raise ValueError("unknown notation: %r" % (to_kind,))

    if f == "words":
        number = words_to_int(value)
    else:
        try:
            number = int(str(value).strip())
        except (TypeError, ValueError):
            raise ValueError("%r is not an integer" % (value,))

    if t == "words":
        return int_to_words(number), "words"
    return str(number), "words"


# --------------------------------------------------------------------------
# Colour notations — hex / rgb / hsl.
#
# Like number bases and Roman numerals, a colour is one underlying value (a
# point in RGB space) wearing different clothes: ``#ff0000``, ``rgb(255,0,0)``
# and ``hsl(0,100%,50%)`` all name the same red. So this family lives outside
# CATEGORIES (a linear factor would be meaningless) and converts by parsing the
# source notation into a canonical (r, g, b) byte triple and re-rendering it —
# exactly as ``convert_base`` routes through a Python int. The HSL maths is the
# standard bidirectional algorithm, with a single hue/RGB helper so the forward
# and inverse transforms stay in one place.
# --------------------------------------------------------------------------

COLOR_NOTATIONS = ("hex", "rgb", "hsl")


def _clamp_byte(value, label):
    """Return ``value`` as an int in 0..255 or raise for an out-of-range channel."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError("%s channel %r is not an integer" % (label, value))
    if n < 0 or n > 255:
        raise ValueError("%s channel %d is outside 0..255" % (label, n))
    return n


def parse_hex(text):
    """Parse a ``#rgb`` or ``#rrggbb`` hex colour into an ``(r, g, b)`` triple.

    A leading ``#`` is optional, case is ignored, and the 3-digit shorthand
    (``#f00`` == ``#ff0000``) is expanded. Raises ``ValueError`` for a bad length
    or a non-hex digit.
    """
    s = str(text).strip().lstrip("#").strip()
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise ValueError("%r is not a 3- or 6-digit hex colour" % (text,))
    try:
        r = int(s[0:2], 16)
        g = int(s[2:4], 16)
        b = int(s[4:6], 16)
    except ValueError:
        raise ValueError("%r contains a non-hex digit" % (text,))
    return r, g, b


def parse_rgb(text):
    """Parse ``rgb(r, g, b)`` / ``r,g,b`` / ``r g b`` into an ``(r, g, b)`` triple.

    An optional ``rgb(...)`` wrapper, commas, and surrounding whitespace are
    tolerated. Each channel must be an integer in 0..255. Raises ``ValueError``
    for the wrong number of channels or an out-of-range value.
    """
    s = str(text).strip().lower()
    if s.startswith("rgb"):
        s = s[3:].strip()
    s = s.strip("()").replace(",", " ")
    parts = s.split()
    if len(parts) != 3:
        raise ValueError("rgb colour needs exactly three channels, got %r" % (text,))
    return tuple(_clamp_byte(p, "rgb") for p in parts)


def parse_hsl(text):
    """Parse ``hsl(h, s%, l%)`` / ``h,s,l`` into an ``(r, g, b)`` triple.

    The hue is degrees in 0..360, saturation and lightness are percentages in
    0..100 (a trailing ``%`` is tolerated). The result is the equivalent RGB
    byte triple. Raises ``ValueError`` for the wrong number of components or an
    out-of-range value.
    """
    s = str(text).strip().lower()
    if s.startswith("hsl"):
        s = s[3:].strip()
    s = s.strip("()").replace("%", "").replace(",", " ")
    parts = s.split()
    if len(parts) != 3:
        raise ValueError("hsl colour needs exactly three components, got %r" % (text,))
    try:
        h = float(parts[0])
        sat = float(parts[1])
        lit = float(parts[2])
    except ValueError:
        raise ValueError("hsl components must be numbers: %r" % (text,))
    if not (0.0 <= h <= 360.0):
        raise ValueError("hue %g is outside 0..360" % (h,))
    if not (0.0 <= sat <= 100.0):
        raise ValueError("saturation %g is outside 0..100" % (sat,))
    if not (0.0 <= lit <= 100.0):
        raise ValueError("lightness %g is outside 0..100" % (lit,))
    return _hsl_to_rgb(h, sat, lit)


def _hue_to_channel(p, q, t):
    """Map a hue position ``t`` (turns) onto a single normalised RGB channel."""
    if t < 0:
        t += 1.0
    if t > 1:
        t -= 1.0
    if t < 1.0 / 6.0:
        return p + (q - p) * 6.0 * t
    if t < 1.0 / 2.0:
        return q
    if t < 2.0 / 3.0:
        return p + (q - p) * (2.0 / 3.0 - t) * 6.0
    return p


def _hsl_to_rgb(h, sat, lit):
    """Convert HSL (deg, %, %) into an ``(r, g, b)`` byte triple."""
    h_n = (h % 360.0) / 360.0
    s_n = sat / 100.0
    l_n = lit / 100.0
    if s_n == 0:
        channel = int(round(l_n * 255))
        return channel, channel, channel
    q = l_n * (1.0 + s_n) if l_n < 0.5 else l_n + s_n - l_n * s_n
    p = 2.0 * l_n - q
    r = _hue_to_channel(p, q, h_n + 1.0 / 3.0)
    g = _hue_to_channel(p, q, h_n)
    b = _hue_to_channel(p, q, h_n - 1.0 / 3.0)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


def _rgb_to_hsl(r, g, b):
    """Convert an ``(r, g, b)`` byte triple into HSL ``(h_deg, s_pct, l_pct)``.

    Hue is rounded to the nearest degree, saturation/lightness to the nearest
    percent — the canonical, display-friendly rendering used by ``rgb(..)`` CSS.
    """
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    high = max(rf, gf, bf)
    low = min(rf, gf, bf)
    lit = (high + low) / 2.0
    if high == low:
        return 0, 0, int(round(lit * 100))
    d = high - low
    sat = d / (2.0 - high - low) if lit > 0.5 else d / (high + low)
    if high == rf:
        hue = (gf - bf) / d + (6.0 if gf < bf else 0.0)
    elif high == gf:
        hue = (bf - rf) / d + 2.0
    else:
        hue = (rf - gf) / d + 4.0
    hue /= 6.0
    return int(round(hue * 360)) % 360, int(round(sat * 100)), int(round(lit * 100))


def _render_color(rgb, notation):
    """Render a canonical ``(r, g, b)`` triple in the requested notation."""
    r, g, b = rgb
    if notation == "hex":
        return "#%02x%02x%02x" % (r, g, b)
    if notation == "rgb":
        return "rgb(%d, %d, %d)" % (r, g, b)
    if notation == "hsl":
        h, s, l = _rgb_to_hsl(r, g, b)
        return "hsl(%d, %d%%, %d%%)" % (h, s, l)
    raise ValueError("unknown colour notation: %r" % (notation,))


def convert_color(value, from_notation, to_notation):
    """Convert a colour between ``hex`` / ``rgb`` / ``hsl`` notations.

    Routes every input through a canonical ``(r, g, b)`` byte triple, then
    renders it in the target notation, so the parsing and rendering each live in
    exactly one place. Returns ``(result_string, "color")``. Raises
    ``ValueError`` for an unknown notation or a malformed/out-of-range colour.
    """
    f = str(from_notation).strip().lower()
    t = str(to_notation).strip().lower()
    if f not in COLOR_NOTATIONS:
        raise ValueError("unknown colour notation: %r" % (from_notation,))
    if t not in COLOR_NOTATIONS:
        raise ValueError("unknown colour notation: %r" % (to_notation,))
    if f == "hex":
        rgb = parse_hex(value)
    elif f == "rgb":
        rgb = parse_rgb(value)
    else:
        rgb = parse_hsl(value)
    return _render_color(rgb, t), "color"


def list_units():
    """Return a JSON-serialisable description of every supported category."""
    out = {
        "temperature": sorted({a for a in ("C", "F", "K")}),
        "fuel": sorted(FUEL_UNITS),
        "base": sorted(_BASE_NAME.values()),
        "roman": ["arabic", "roman"],
        "words": ["arabic", "words"],
        "color": sorted(COLOR_NOTATIONS),
    }
    for name, units in CATEGORIES.items():
        out[name] = sorted(units.keys())
    return out


# --------------------------------------------------------------------------
# Unified dispatch + natural-language parsing.
#
# The three conversion families (temperature, fuel, and the linear-factor
# categories) each have their own correct-but-incompatible maths. ``smart_convert``
# is the single front door that routes a (value, from, to) request to the right
# family and refuses to cross between them — so callers (and an expression
# parser) never need to know which family a unit belongs to.
# --------------------------------------------------------------------------

# Temperature is an affine family that lives outside CATEGORIES, so it needs its
# own alias table. Both the single-letter scale and the spelled-out name resolve
# to the canonical scale letter understood by convert_temperature.
TEMP_ALIASES = {
    "c": "C", "celsius": "C",
    "f": "F", "fahrenheit": "F",
    "k": "K", "kelvin": "K",
}


def smart_convert(value, from_unit, to_unit):
    """Convert across *any* family, picking the right engine automatically.

    Routes to temperature, fuel, or the linear-factor categories based on the
    units involved and returns ``(result, category)``. Mixing families (e.g. a
    temperature scale with a length unit) raises ``ValueError`` with a clear
    message, exactly like a cross-category linear mismatch. Reuses
    :func:`convert_temperature`, :func:`convert_fuel`, and :func:`convert_units`
    so no conversion maths is duplicated here.
    """
    f = str(from_unit).strip().lower()
    t = str(to_unit).strip().lower()

    f_temp, t_temp = f in TEMP_ALIASES, t in TEMP_ALIASES
    if f_temp or t_temp:
        if not (f_temp and t_temp):
            raise ValueError(
                "cannot convert between a temperature scale and a non-temperature unit"
            )
        return convert_temperature(value, TEMP_ALIASES[f], TEMP_ALIASES[t]), "temperature"

    f_fuel, t_fuel = f in FUEL_UNITS, t in FUEL_UNITS
    if f_fuel or t_fuel:
        if not (f_fuel and t_fuel):
            raise ValueError(
                "cannot convert between a fuel-economy unit and another family"
            )
        return convert_fuel(value, f, t)

    return convert_units(value, f, t)


# Accepts "100 km to mi", "100km in mi", "98.6 f -> c", "5 l100km = mpg", etc.
# Arrows/equals are normalised to the word "to" first so the regex only has to
# understand the two connector words.
_EXPRESSION_RE = re.compile(
    r"^([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)\s*(\S+)\s+(?:to|in)\s+(\S+)$",
    re.IGNORECASE,
)


def parse_expression(text):
    """Parse a free-text conversion like ``"100 km to mi"``.

    Returns ``(value, from_unit, to_unit)`` with ``value`` as a float and the
    units as raw (case-preserved) strings. Raises ``ValueError`` if the text is
    not a recognised ``<number> <from> to|in <to>`` phrase.
    """
    normalised = str(text).strip()
    for arrow in ("->", "→", "=", "⇒", "➜"):
        normalised = normalised.replace(arrow, " to ")
    match = _EXPRESSION_RE.match(normalised.strip())
    if not match:
        raise ValueError(
            "could not parse expression; expected '<value> <from> to <to>'"
        )
    number, from_unit, to_unit = match.groups()
    value = float(number)
    if not math.isfinite(value):
        # e.g. "1e999 m to km": float() yields inf, which must not flow into a
        # conversion (and ultimately json.dumps as the invalid literal Infinity).
        raise ValueError("value is out of range (not a finite number)")
    return value, from_unit, to_unit


def parse_and_convert(text):
    """Parse a free-text conversion and execute it via :func:`smart_convert`.

    Returns a JSON-serialisable dict describing the conversion. Raises
    ``ValueError`` for an unparseable phrase or an invalid/cross-family
    conversion (the same exception type both failures already use, so callers
    surface a single 400 path).
    """
    value, from_unit, to_unit = parse_expression(text)
    result, category = smart_convert(value, from_unit, to_unit)
    return {
        "input": value,
        "from": str(from_unit).lower(),
        "to": str(to_unit).lower(),
        "category": category,
        "result": result,
        "expression": str(text).strip(),
    }


def conversion_table(from_unit, to_unit, values):
    """Build a conversion table: one ``{"input", "result"}`` row per value.

    A single ``from_unit``/``to_unit`` pair is applied to every entry of
    ``values`` via :func:`smart_convert`, so the table works for *any* family
    (linear, temperature, or fuel). Unlike :func:`convert_batch` this is
    all-or-nothing: an unknown unit, a cross-family pair, a non-numeric value, or
    a result that overflows raises ``ValueError`` for the whole request, because
    every row shares the same units and a printable chart with holes in it is
    worse than a clean error. Returns ``(rows, category)``.
    """
    if not isinstance(values, (list, tuple)):
        raise ValueError("'values' must be a list of numbers")
    if not values:
        raise ValueError("'values' must not be empty")

    rows = []
    category = None
    for raw in values:
        try:
            numeric = float(raw)
        except (TypeError, ValueError):
            raise ValueError("every value must be a number: %r is not" % (raw,))
        if not math.isfinite(numeric):
            raise ValueError("every value must be finite: %r is not" % (raw,))
        result, category = smart_convert(numeric, from_unit, to_unit)
        if not (isinstance(result, str) or math.isfinite(result)):
            raise ValueError("conversion result is out of range (overflowed)")
        rows.append({"input": numeric, "result": result})
    return rows, category
