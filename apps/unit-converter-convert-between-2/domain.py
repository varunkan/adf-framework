"""Pure unit-conversion domain logic — Python 3 standard library only.

This module EXTENDS the original meters<->feet converter into a general,
multi-category unit converter (length, mass, temperature, volume, time).

Design:
- Each linear category maps every accepted unit token (canonical + aliases)
  to a factor relative to that category's BASE unit, so
      result = value * factor[from] / factor[to].
- Temperature is affine (offset + scale), handled separately via Celsius base.
- ``convert_units`` is the single entry point used by the HTTP layer.

The original module-level helpers in ``server.py`` (meters_to_feet,
feet_to_meters, convert) are deliberately left untouched; this file is purely
additive so existing behaviour and tests keep working.
"""

import math
import re

# --- Linear categories: unit token -> factor relative to the category base ---

# Length, base = meter. Conversion factors are exact international definitions.
LENGTH = {
    "m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0,
    "km": 1000.0, "kilometer": 1000.0, "kilometre": 1000.0, "kilometers": 1000.0,
    "cm": 0.01, "centimeter": 0.01, "centimeters": 0.01,
    "mm": 0.001, "millimeter": 0.001, "millimeters": 0.001,
    "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
    "in": 0.0254, "inch": 0.0254, "inches": 0.0254,
    "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
    "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
    "nmi": 1852.0, "nauticalmile": 1852.0,
}

# Mass, base = kilogram.
MASS = {
    "kg": 1.0, "kilogram": 1.0, "kilograms": 1.0,
    "g": 0.001, "gram": 0.001, "grams": 0.001,
    "mg": 1e-6, "milligram": 1e-6, "milligrams": 1e-6,
    "t": 1000.0, "tonne": 1000.0, "tonnes": 1000.0, "metricton": 1000.0,
    "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237, "pounds": 0.45359237,
    "oz": 0.028349523125, "ounce": 0.028349523125, "ounces": 0.028349523125,
    "st": 6.35029318, "stone": 6.35029318,
}

# Volume, base = liter.
VOLUME = {
    "l": 1.0, "liter": 1.0, "litre": 1.0, "liters": 1.0, "litres": 1.0,
    "ml": 0.001, "milliliter": 0.001, "millilitre": 0.001,
    "m3": 1000.0, "cubicmeter": 1000.0,
    "gal": 3.785411784, "gallon": 3.785411784, "gallons": 3.785411784,
    "qt": 0.946352946, "quart": 0.946352946, "quarts": 0.946352946,
    "pt": 0.473176473, "pint": 0.473176473, "pints": 0.473176473,
    "cup": 0.2365882365, "cups": 0.2365882365,
    "floz": 0.0295735295625, "fluidounce": 0.0295735295625,
}

# Time, base = second.
TIME = {
    "s": 1.0, "sec": 1.0, "second": 1.0, "seconds": 1.0,
    "ms": 0.001, "millisecond": 0.001, "milliseconds": 0.001,
    "min": 60.0, "minute": 60.0, "minutes": 60.0,
    "h": 3600.0, "hr": 3600.0, "hour": 3600.0, "hours": 3600.0,
    "day": 86400.0, "days": 86400.0,
    "week": 604800.0, "weeks": 604800.0,
}

# Area, base = square meter. Imperial factors are exact (derived from the exact
# length definitions squared, e.g. 1 ft == 0.3048 m -> 1 ft2 == 0.09290304 m2).
AREA = {
    "m2": 1.0, "sqm": 1.0, "squaremeter": 1.0, "squaremeters": 1.0,
    "cm2": 1e-4, "sqcm": 1e-4, "squarecentimeter": 1e-4,
    "mm2": 1e-6, "sqmm": 1e-6,
    "km2": 1e6, "sqkm": 1e6, "squarekilometer": 1e6,
    "ha": 10000.0, "hectare": 10000.0, "hectares": 10000.0,
    "in2": 0.00064516, "sqin": 0.00064516, "squareinch": 0.00064516,
    "ft2": 0.09290304, "sqft": 0.09290304, "squarefoot": 0.09290304, "squarefeet": 0.09290304,
    "yd2": 0.83612736, "sqyd": 0.83612736, "squareyard": 0.83612736,
    "ac": 4046.8564224, "acre": 4046.8564224, "acres": 4046.8564224,
    "mi2": 2589988.110336, "sqmi": 2589988.110336, "squaremile": 2589988.110336,
}

# Speed, base = meter per second. mph and ft/s are exact; kph and knot are
# rational fractions stored as their nearest float.
SPEED = {
    "mps": 1.0, "m/s": 1.0, "meterspersecond": 1.0,
    "kph": 1000.0 / 3600.0, "km/h": 1000.0 / 3600.0, "kmph": 1000.0 / 3600.0,
    "mph": 1609.344 / 3600.0, "mi/h": 1609.344 / 3600.0,
    "fps": 0.3048, "ft/s": 0.3048, "feetpersecond": 0.3048,
    "kn": 1852.0 / 3600.0, "knot": 1852.0 / 3600.0, "knots": 1852.0 / 3600.0,
}

# Digital storage, base = byte. Decimal (kB=1000) and binary (KiB=1024) prefixes
# are both supported, plus the sub-byte bit (1 byte == 8 bits).
DIGITAL = {
    "bit": 0.125, "bits": 0.125,
    "b": 1.0, "byte": 1.0, "bytes": 1.0,
    "kb": 1000.0, "kilobyte": 1000.0, "kilobytes": 1000.0,
    "mb": 1e6, "megabyte": 1e6, "megabytes": 1e6,
    "gb": 1e9, "gigabyte": 1e9, "gigabytes": 1e9,
    "tb": 1e12, "terabyte": 1e12, "terabytes": 1e12,
    "kib": 1024.0, "kibibyte": 1024.0, "kibibytes": 1024.0,
    "mib": 1024.0 ** 2, "mebibyte": 1024.0 ** 2,
    "gib": 1024.0 ** 3, "gibibyte": 1024.0 ** 3,
    "tib": 1024.0 ** 4, "tebibyte": 1024.0 ** 4,
}

# Pressure, base = pascal. atm and bar are exact definitions; psi and torr are
# the standard exact/rational values.
PRESSURE = {
    "pa": 1.0, "pascal": 1.0, "pascals": 1.0,
    "hpa": 100.0, "hectopascal": 100.0,
    "kpa": 1000.0, "kilopascal": 1000.0, "kilopascals": 1000.0,
    "mpa": 1e6, "megapascal": 1e6,
    "bar": 100000.0, "bars": 100000.0,
    "mbar": 100.0, "millibar": 100.0, "millibars": 100.0,
    "atm": 101325.0, "atmosphere": 101325.0, "atmospheres": 101325.0,
    "psi": 6894.757293168361, "poundspersquareinch": 6894.757293168361,
    "torr": 101325.0 / 760.0,
    "mmhg": 133.322387415, "millimeterofmercury": 133.322387415,
}

# Energy, base = joule. cal is the thermochemical calorie (exact 4.184 J).
ENERGY = {
    "j": 1.0, "joule": 1.0, "joules": 1.0,
    "kj": 1000.0, "kilojoule": 1000.0, "kilojoules": 1000.0,
    "mj": 1e6, "megajoule": 1e6,
    "cal": 4.184, "calorie": 4.184, "calories": 4.184,
    "kcal": 4184.0, "kilocalorie": 4184.0, "kilocalories": 4184.0,
    "wh": 3600.0, "watthour": 3600.0, "watthours": 3600.0,
    "kwh": 3.6e6, "kilowatthour": 3.6e6, "kilowatthours": 3.6e6,
    "btu": 1055.05585262, "btus": 1055.05585262,
    "ftlb": 1.3558179483314004, "footpound": 1.3558179483314004,
    "ev": 1.602176634e-19, "electronvolt": 1.602176634e-19,
}

# Power, base = watt. hp is mechanical (imperial) horsepower; ps/metrichp is the
# metric horsepower.
POWER = {
    "w": 1.0, "watt": 1.0, "watts": 1.0,
    "kw": 1000.0, "kilowatt": 1000.0, "kilowatts": 1000.0,
    "mw": 1e6, "megawatt": 1e6, "megawatts": 1e6,
    "gw": 1e9, "gigawatt": 1e9,
    "mwatt": 0.001, "milliwatt": 0.001, "milliwatts": 0.001,
    "hp": 745.6998715822702, "horsepower": 745.6998715822702,
    "ps": 735.49875, "metrichp": 735.49875,
}

# Plane angle, base = radian.
ANGLE = {
    "rad": 1.0, "radian": 1.0, "radians": 1.0,
    "deg": math.pi / 180.0, "degree": math.pi / 180.0, "degrees": math.pi / 180.0,
    "grad": math.pi / 200.0, "gradian": math.pi / 200.0, "gon": math.pi / 200.0,
    "arcmin": math.pi / 10800.0, "arcminute": math.pi / 10800.0,
    "arcsec": math.pi / 648000.0, "arcsecond": math.pi / 648000.0,
    "turn": 2.0 * math.pi, "turns": 2.0 * math.pi,
    "rev": 2.0 * math.pi, "revolution": 2.0 * math.pi, "revolutions": 2.0 * math.pi,
}

# Frequency, base = hertz.
FREQUENCY = {
    "hz": 1.0, "hertz": 1.0,
    "khz": 1000.0, "kilohertz": 1000.0,
    "mhz": 1e6, "megahertz": 1e6,
    "ghz": 1e9, "gigahertz": 1e9,
    "rpm": 1.0 / 60.0, "revolutionsperminute": 1.0 / 60.0,
}

# Force, base = newton. lbf/kgf/ozf are the standard exact gravitational
# definitions (kgf uses standard gravity g0 = 9.80665 m/s^2). The kilo/mega
# prefixes are spelled out because the short "kn" token is already claimed by
# the speed category (knots) and "n" alone is the newton.
FORCE = {
    "n": 1.0, "newton": 1.0, "newtons": 1.0,
    "kilonewton": 1000.0, "kilonewtons": 1000.0,
    "meganewton": 1e6, "meganewtons": 1e6,
    "dyn": 1e-5, "dyne": 1e-5, "dynes": 1e-5,
    "kgf": 9.80665, "kilogramforce": 9.80665, "kp": 9.80665, "kilopond": 9.80665,
    "lbf": 4.4482216152605, "poundforce": 4.4482216152605,
    "ozf": 4.4482216152605 / 16.0, "ounceforce": 4.4482216152605 / 16.0,
}

# Data transfer rate, base = bit per second. Networking conventionally uses
# DECIMAL prefixes (kbps == 1000 bit/s, not 1024). Byte-per-second tokens carry
# a "/s" so they stay distinct from the storage tokens in DIGITAL after
# normalisation ("kb/s" != "kb"); one byte == 8 bits, hence the x8 factors.
DATARATE = {
    "bps": 1.0, "bitps": 1.0, "bit/s": 1.0, "bitpersecond": 1.0, "bitspersecond": 1.0,
    "kbps": 1e3, "kbit/s": 1e3, "kilobitpersecond": 1e3,
    "mbps": 1e6, "mbit/s": 1e6, "megabitpersecond": 1e6,
    "gbps": 1e9, "gbit/s": 1e9, "gigabitpersecond": 1e9,
    "tbps": 1e12, "tbit/s": 1e12, "terabitpersecond": 1e12,
    "b/s": 8.0, "byteps": 8.0, "bytepersecond": 8.0, "bytespersecond": 8.0,
    "kb/s": 8e3, "kbyteps": 8e3, "kilobytepersecond": 8e3,
    "mb/s": 8e6, "mbyteps": 8e6, "megabytepersecond": 8e6,
    "gb/s": 8e9, "gbyteps": 8e9, "gigabytepersecond": 8e9,
}

# Acceleration, base = meter per second squared. Standard gravity g0 is the
# exact CODATA/SI conventional value (9.80665 m/s^2); the "Gal" (galileo) is the
# CGS unit, exactly 1 cm/s^2. Tokens carry "/s2" or a distinct suffix so they
# never collide with the bare mass "g" / volume "gal" tokens already in use.
ACCELERATION = {
    "m/s2": 1.0, "mps2": 1.0, "meterspersecondsquared": 1.0,
    "cm/s2": 0.01, "galileo": 0.01, "gals": 0.01,
    "ft/s2": 0.3048, "ftps2": 0.3048, "feetpersecondsquared": 0.3048,
    "g0": 9.80665, "gn": 9.80665, "standardgravity": 9.80665, "gforce": 9.80665,
    "mph/s": 1609.344 / 3600.0, "mphps": 1609.344 / 3600.0,
    "km/h/s": 1000.0 / 3600.0, "kmphs": 1000.0 / 3600.0,
}

# Torque, base = newton-metre. Imperial factors derive from the exact force and
# length definitions (lbf*ft == 4.4482216152605 N * 0.3048 m). Deliberately
# spelled distinctly from the ENERGY "footpound"/"ftlb" tokens: torque and energy
# share a dimension but are physically different quantities, so they stay split.
TORQUE = {
    "nm": 1.0, "n*m": 1.0, "newtonmeter": 1.0, "newtonmetre": 1.0, "newtonmeters": 1.0,
    "knm": 1000.0, "kilonewtonmeter": 1000.0,
    "kgfm": 9.80665, "kgf*m": 9.80665, "kilogramforcemeter": 9.80665,
    "lbfft": 1.3558179483314004, "lbf*ft": 1.3558179483314004, "poundforcefoot": 1.3558179483314004,
    "lbfin": 1.3558179483314004 / 12.0, "lbf*in": 1.3558179483314004 / 12.0,
    "poundforceinch": 1.3558179483314004 / 12.0,
    "ozfin": (4.4482216152605 / 16.0) / 12.0, "ounceforceinch": (4.4482216152605 / 16.0) / 12.0,
    "dyncm": 1e-7, "dyne*cm": 1e-7, "dynecentimeter": 1e-7,
}

# Density, base = kilogram per cubic metre. 1 g/cm^3 == 1 g/mL == 1 kg/L ==
# 1000 kg/m^3 (water's ~reference density). Imperial factors come from the exact
# mass/length definitions (lb/ft^3 == 0.45359237 kg / 0.3048^3 m^3).
DENSITY = {
    "kg/m3": 1.0, "kgperm3": 1.0, "kilogrampercubicmeter": 1.0,
    "g/m3": 0.001, "gperm3": 0.001,
    "g/l": 1.0, "gperl": 1.0, "grampliter": 1.0,
    "kg/l": 1000.0, "kgperl": 1000.0, "kilogramperliter": 1000.0,
    "g/cm3": 1000.0, "gpercm3": 1000.0, "gramspercubiccentimeter": 1000.0,
    "g/ml": 1000.0, "gperml": 1000.0,
    "lb/ft3": 16.018463373960146, "poundspercubicfoot": 16.018463373960146,
    "lb/in3": 27679.904710203125, "poundspercubicinch": 27679.904710203125,
    "oz/ft3": 16.018463373960146 / 16.0, "ouncepercubicfoot": 16.018463373960146 / 16.0,
}

# Illuminance, base = lux (lumen per square metre). 1 foot-candle is one lumen
# per square foot, so it equals 1 / 0.09290304 == 10.76391041670972 lux (the
# exact reciprocal of the square-foot area factor). 1 phot == 1 lm/cm^2 == 1e4
# lux; 1 nox == 1e-3 lux. Tokens are multi-char (lux/lx) so they never collide
# with the bare single-letter tokens already claimed by other categories.
ILLUMINANCE = {
    "lux": 1.0, "lx": 1.0, "lumenspersquaremeter": 1.0,
    "klx": 1000.0, "kilolux": 1000.0,
    "footcandle": 1.0 / 0.09290304, "fc": 1.0 / 0.09290304,
    "lumenspersquarefoot": 1.0 / 0.09290304,
    "phot": 1e4, "phots": 1e4,
    "nox": 1e-3,
}

# Electric charge, base = coulomb. The amp-hour family is exact (1 Ah == 3600 C).
# The SI symbol for the coulomb is an upper-case "C", but the normaliser lower-
# cases everything and a bare "c" is already the Celsius token, so coulomb is
# spelled out and only prefixed short tokens (mc/uc/kc) are offered.
CHARGE = {
    "coulomb": 1.0, "coulombs": 1.0,
    "mc": 1e-3, "millicoulomb": 1e-3, "millicoulombs": 1e-3,
    "uc": 1e-6, "microcoulomb": 1e-6, "microcoulombs": 1e-6,
    "kc": 1000.0, "kilocoulomb": 1000.0, "kilocoulombs": 1000.0,
    "ah": 3600.0, "amperehour": 3600.0, "amperehours": 3600.0,
    "mah": 3.6, "milliamperehour": 3.6, "milliamperehours": 3.6,
    "faraday": 96485.33212,
}

# Electric potential, base = volt. Pure SI-prefix ladder. The bare "v" token is
# unclaimed by any other category, so the short symbols are safe to offer.
VOLTAGE = {
    "v": 1.0, "volt": 1.0, "volts": 1.0,
    "mv": 1e-3, "millivolt": 1e-3, "millivolts": 1e-3,
    "uv": 1e-6, "microvolt": 1e-6, "microvolts": 1e-6,
    "kv": 1e3, "kilovolt": 1e3, "kilovolts": 1e3,
    "megavolt": 1e6, "megavolts": 1e6,
}

# Electric current, base = ampere. The bare "a" and prefixed "ma"/"ua"/"ka"
# tokens are unclaimed elsewhere (charge uses "mah"/"mc", never "ma").
CURRENT = {
    "a": 1.0, "amp": 1.0, "amps": 1.0, "ampere": 1.0, "amperes": 1.0,
    "ma": 1e-3, "milliamp": 1e-3, "milliamps": 1e-3,
    "milliampere": 1e-3, "milliamperes": 1e-3,
    "ua": 1e-6, "microamp": 1e-6, "microampere": 1e-6, "microamperes": 1e-6,
    "ka": 1e3, "kiloamp": 1e3, "kiloampere": 1e3, "kiloamperes": 1e3,
}

# Electric resistance, base = ohm. The ambiguous "mohm" (milli- vs mega-) is
# deliberately omitted; milli/mega are spelled out, and "kohm"/"megohm" are the
# only short prefixed forms offered.
RESISTANCE = {
    "ohm": 1.0, "ohms": 1.0,
    "milliohm": 1e-3, "milliohms": 1e-3,
    "kohm": 1e3, "kiloohm": 1e3, "kiloohms": 1e3,
    "megohm": 1e6, "megaohm": 1e6, "megaohms": 1e6,
}

# Magnetic flux density, base = tesla. The gauss (CGS) is exactly 1e-4 T, so the
# whole gauss family derives from that exact decimal; gamma is the geophysics
# unit equal to one nanotesla. Tokens are multi-char or carry a "t"/"gauss"
# suffix so they never collide with the bare mass "t" (tonne) or other symbols.
MAGNETIC = {
    "tesla": 1.0, "teslas": 1.0,
    "mt": 1e-3, "millitesla": 1e-3, "milliteslas": 1e-3,
    "ut": 1e-6, "microtesla": 1e-6, "microteslas": 1e-6,
    "nt": 1e-9, "nanotesla": 1e-9, "gamma": 1e-9,
    "gauss": 1e-4,
    "milligauss": 1e-7, "mgauss": 1e-7,
    "kilogauss": 0.1,
}

# Radioactivity (decay rate), base = becquerel (one decay per second). The curie
# is the historical unit, defined as exactly 3.7e10 Bq; the rutherford is exactly
# 1e6 Bq. The metric-prefixed becquerel ladder is exact decimal scaling.
RADIOACTIVITY = {
    "bq": 1.0, "becquerel": 1.0, "becquerels": 1.0,
    "kbq": 1e3, "kilobecquerel": 1e3,
    "mbq": 1e6, "megabecquerel": 1e6,
    "gbq": 1e9, "gigabecquerel": 1e9,
    "tbq": 1e12, "terabecquerel": 1e12,
    "ci": 3.7e10, "curie": 3.7e10, "curies": 3.7e10,
    "mci": 3.7e7, "millicurie": 3.7e7, "millicuries": 3.7e7,
    "uci": 3.7e4, "microcurie": 3.7e4, "microcuries": 3.7e4,
    "rd": 1e6, "rutherford": 1e6,
}

# Dynamic viscosity, base = pascal-second (Pa*s). The poise (CGS) is exactly 0.1
# Pa*s and the centipoise (water at ~20 C) is exactly 1e-3 Pa*s; the reyn is the
# imperial unit, one psi-second, so it reuses the exact psi pressure factor.
VISCOSITY = {
    "pas": 1.0, "pa*s": 1.0, "pascalsecond": 1.0, "pascalseconds": 1.0,
    "mpas": 1e-3, "millipascalsecond": 1e-3,
    "poise": 0.1,
    "cp": 1e-3, "centipoise": 1e-3,
    "micropoise": 1e-7,
    "reyn": 6894.757293168361, "reyns": 6894.757293168361,
}

# Electric capacitance, base = farad. Real-world capacitors live in the sub-farad
# range, so the prefixed ladder runs millifarad -> picofarad. The bare SI symbol
# "F" is already the Fahrenheit token (and CHARGE owns "faraday", the ~96485 C
# constant — a different quantity), so capacitance spells the unit out as
# "farad" and offers only the unambiguous prefixed short forms (mf/uf/nf/pf).
CAPACITANCE = {
    "farad": 1.0, "farads": 1.0,
    "mf": 1e-3, "millifarad": 1e-3, "millifarads": 1e-3,
    "uf": 1e-6, "microfarad": 1e-6, "microfarads": 1e-6,
    "nf": 1e-9, "nanofarad": 1e-9, "nanofarads": 1e-9,
    "pf": 1e-12, "picofarad": 1e-12, "picofarads": 1e-12,
}

# Electric inductance, base = henry. The bare SI symbol "H" is already the hour
# token, so the unit is spelled out and only the prefixed short forms
# (mh/uh/nh) are offered — none of which collide with an existing token.
INDUCTANCE = {
    "henry": 1.0, "henries": 1.0, "henrys": 1.0,
    "mh": 1e-3, "millihenry": 1e-3, "millihenries": 1e-3,
    "uh": 1e-6, "microhenry": 1e-6, "microhenries": 1e-6,
    "nh": 1e-9, "nanohenry": 1e-9, "nanohenries": 1e-9,
}

# Electric conductance, base = siemens (the reciprocal of the ohm). The bare SI
# symbol "S" is the seconds token and the prefixed "ms"/"us" forms collide with
# the time category, so the prefixes are spelled out. "mho" is the historical
# name for the siemens and is offered as an exact synonym.
CONDUCTANCE = {
    "siemens": 1.0, "mho": 1.0, "mhos": 1.0,
    "millisiemens": 1e-3, "millimho": 1e-3, "millimhos": 1e-3,
    "microsiemens": 1e-6, "micromho": 1e-6, "micromhos": 1e-6,
    "kilosiemens": 1e3,
}

# Luminous flux, base = lumen. Distinct from the ILLUMINANCE category (lux =
# lumens per square metre): luminous flux is total emitted light, illuminance is
# light per unit area. The bare "lm" token is unclaimed elsewhere.
LUMINOUS_FLUX = {
    "lm": 1.0, "lumen": 1.0, "lumens": 1.0,
    "klm": 1e3, "kilolumen": 1e3, "kilolumens": 1e3,
    "mlm": 1e-3, "millilumen": 1e-3, "millilumens": 1e-3,
}

# Volumetric flow rate, base = litre per second. Mixes metric (L/s, m3/h) and
# imperial (US gpm, cfm) conventions. Imperial factors derive from the exact
# volume definitions: 1 US gallon == 3.785411784 L and 1 cubic foot ==
# 0.3048**3 m3 == 28.316846592 L. Every token carries a "/" or a distinct
# multi-char suffix so it never collides with the bare volume/time tokens.
_L_PER_CUBIC_FOOT = 0.3048 ** 3 * 1000.0  # 28.316846592 L (exact)
FLOW = {
    "l/s": 1.0, "lps": 1.0, "literpersecond": 1.0, "literspersecond": 1.0,
    "l/min": 1.0 / 60.0, "lpm": 1.0 / 60.0, "literperminute": 1.0 / 60.0,
    "l/h": 1.0 / 3600.0, "lph": 1.0 / 3600.0, "literperhour": 1.0 / 3600.0,
    "m3/s": 1000.0, "m3ps": 1000.0, "cubicmeterpersecond": 1000.0,
    "m3/min": 1000.0 / 60.0, "m3pm": 1000.0 / 60.0, "cubicmeterperminute": 1000.0 / 60.0,
    "m3/h": 1000.0 / 3600.0, "m3ph": 1000.0 / 3600.0, "cubicmeterperhour": 1000.0 / 3600.0,
    "gpm": 3.785411784 / 60.0, "gallonperminute": 3.785411784 / 60.0,
    "gallonsperminute": 3.785411784 / 60.0,
    "gph": 3.785411784 / 3600.0, "gallonperhour": 3.785411784 / 3600.0,
    "gallonsperhour": 3.785411784 / 3600.0,
    "cfm": _L_PER_CUBIC_FOOT / 60.0, "cubicfootperminute": _L_PER_CUBIC_FOOT / 60.0,
    "cubicfeetperminute": _L_PER_CUBIC_FOOT / 60.0,
    "cfs": _L_PER_CUBIC_FOOT, "cubicfootpersecond": _L_PER_CUBIC_FOOT,
    "cubicfeetpersecond": _L_PER_CUBIC_FOOT,
}

# Luminous intensity, base = candela (an SI base quantity). Pure decimal ladder;
# the bare "cd" token is unclaimed by any other category. Distinct from
# LUMINOUS_FLUX (lumen = candela*steradian) and ILLUMINANCE (lux = lumen/m^2):
# intensity is light emitted per unit solid angle in a given direction.
LUMINOUS_INTENSITY = {
    "cd": 1.0, "candela": 1.0, "candelas": 1.0,
    "mcd": 1e-3, "millicandela": 1e-3, "millicandelas": 1e-3,
    "kcd": 1e3, "kilocandela": 1e3, "kilocandelas": 1e3,
}

# Amount of substance, base = mole (an SI base quantity). Pure decimal ladder;
# the "mol"/"mmol"/"umol"/"kmol" tokens are unclaimed elsewhere.
SUBSTANCE = {
    "mol": 1.0, "mole": 1.0, "moles": 1.0,
    "mmol": 1e-3, "millimole": 1e-3, "millimoles": 1e-3,
    "umol": 1e-6, "micromole": 1e-6, "micromoles": 1e-6,
    "kmol": 1e3, "kilomole": 1e3, "kilomoles": 1e3,
}

# Catalytic activity, base = katal (one mole of substance converted per second).
# Pure decimal ladder; "kat" and its prefixed forms are unclaimed elsewhere.
CATALYSIS = {
    "kat": 1.0, "katal": 1.0, "katals": 1.0,
    "mkat": 1e-3, "millikatal": 1e-3, "millikatals": 1e-3,
    "ukat": 1e-6, "microkatal": 1e-6, "microkatals": 1e-6,
    "nkat": 1e-9, "nanokatal": 1e-9, "nanokatals": 1e-9,
}

# Solid angle, base = steradian. A full sphere subtends exactly 4*pi sr (the
# "sphere"/"spat" tokens), and one square degree is (pi/180)^2 sr. Distinct from
# the plane ANGLE category (radian/degree): a solid angle measures a 2-D cone of
# directions, not a 1-D rotation. Tokens are multi-char ("sr"/"sterad"/...) so
# they never collide with the bare angle symbols already in use.
SOLID_ANGLE = {
    "sr": 1.0, "steradian": 1.0, "steradians": 1.0, "sterad": 1.0,
    "sphere": 4.0 * math.pi, "spat": 4.0 * math.pi,
    "squaredegree": (math.pi / 180.0) ** 2, "squaredegrees": (math.pi / 180.0) ** 2,
    "sqdeg": (math.pi / 180.0) ** 2, "deg2": (math.pi / 180.0) ** 2,
}

# Registry of linear categories.
_LINEAR = {
    "length": LENGTH,
    "mass": MASS,
    "volume": VOLUME,
    "time": TIME,
    "area": AREA,
    "speed": SPEED,
    "digital": DIGITAL,
    "pressure": PRESSURE,
    "energy": ENERGY,
    "power": POWER,
    "angle": ANGLE,
    "frequency": FREQUENCY,
    "force": FORCE,
    "datarate": DATARATE,
    "acceleration": ACCELERATION,
    "torque": TORQUE,
    "density": DENSITY,
    "illuminance": ILLUMINANCE,
    "charge": CHARGE,
    "voltage": VOLTAGE,
    "current": CURRENT,
    "resistance": RESISTANCE,
    "magnetic": MAGNETIC,
    "radioactivity": RADIOACTIVITY,
    "viscosity": VISCOSITY,
    "capacitance": CAPACITANCE,
    "inductance": INDUCTANCE,
    "conductance": CONDUCTANCE,
    "luminousflux": LUMINOUS_FLUX,
    "flow": FLOW,
    "luminousintensity": LUMINOUS_INTENSITY,
    "substance": SUBSTANCE,
    "catalysis": CATALYSIS,
    "solidangle": SOLID_ANGLE,
}

# Temperature units (affine, handled specially).
_TEMP_UNITS = {
    "c": "c", "celsius": "c", "centigrade": "c",
    "f": "f", "fahrenheit": "f",
    "k": "k", "kelvin": "k",
}

# Fuel economy units (NON-LINEAR / reciprocal, handled specially).
#
# Fuel economy mixes two opposite conventions: "distance per fuel" (mpg, km/L —
# bigger is better) and "fuel per distance" (L/100km — smaller is better). These
# are reciprocals of one another, so a single linear factor table cannot model
# them. We pick L/100km as the base and convert via explicit formulas. Each raw
# token maps to a canonical fuel "kind".
_FUEL_UNITS = {
    "mpg": "mpg_us", "mpgus": "mpg_us", "milespergallon": "mpg_us",
    "mpguk": "mpg_uk", "mpgimp": "mpg_uk", "mpgimperial": "mpg_uk",
    "l/100km": "l100km", "l100km": "l100km", "lper100km": "l100km",
    "litresper100km": "l100km", "litersper100km": "l100km",
    "km/l": "km_l", "kml": "km_l", "kmpl": "km_l", "kmperl": "km_l",
}

# Exact reference constants for fuel-economy conversions.
_L_PER_US_GAL = 3.785411784   # 1 US gallon in litres (exact)
_L_PER_UK_GAL = 4.54609       # 1 imperial gallon in litres (exact)
_KM_PER_MILE = 1.609344       # 1 mile in kilometres (exact)

# Canonical display units per category, for the UI / discovery endpoint.
CANONICAL_UNITS = {
    "length": ["mm", "cm", "m", "km", "in", "ft", "yd", "mi", "nmi"],
    "mass": ["mg", "g", "kg", "t", "oz", "lb", "st"],
    "temperature": ["c", "f", "k"],
    "volume": ["ml", "l", "m3", "floz", "cup", "pt", "qt", "gal"],
    "time": ["ms", "s", "min", "h", "day", "week"],
    "area": ["mm2", "cm2", "m2", "ha", "km2", "in2", "ft2", "yd2", "ac", "mi2"],
    "speed": ["mps", "kph", "mph", "fps", "kn"],
    "digital": ["bit", "b", "kb", "mb", "gb", "tb", "kib", "mib", "gib", "tib"],
    "pressure": ["pa", "hpa", "kpa", "mpa", "bar", "mbar", "atm", "psi", "torr", "mmhg"],
    "energy": ["j", "kj", "mj", "cal", "kcal", "wh", "kwh", "btu", "ftlb", "ev"],
    "power": ["mwatt", "w", "kw", "mw", "gw", "hp", "ps"],
    "angle": ["rad", "deg", "grad", "arcmin", "arcsec", "turn"],
    "frequency": ["hz", "khz", "mhz", "ghz", "rpm"],
    "force": ["dyn", "n", "kgf", "lbf", "ozf", "kilonewton", "meganewton"],
    "datarate": ["bps", "kbps", "mbps", "gbps", "tbps", "b/s", "kb/s", "mb/s", "gb/s"],
    "acceleration": ["m/s2", "cm/s2", "ft/s2", "g0", "km/h/s", "mph/s"],
    "torque": ["nm", "knm", "kgfm", "lbfft", "lbfin", "ozfin", "dyncm"],
    "density": ["kg/m3", "g/m3", "g/l", "kg/l", "g/cm3", "g/ml", "lb/ft3", "lb/in3", "oz/ft3"],
    "illuminance": ["nox", "lux", "footcandle", "klx", "phot"],
    "charge": ["mc", "coulomb", "kc", "mah", "ah", "faraday"],
    "voltage": ["uv", "mv", "v", "kv", "megavolt"],
    "current": ["ua", "ma", "a", "ka"],
    "resistance": ["milliohm", "ohm", "kohm", "megohm"],
    "magnetic": ["nt", "ut", "milligauss", "mt", "gauss", "kilogauss", "tesla"],
    "radioactivity": ["bq", "kbq", "uci", "mci", "mbq", "ci", "gbq", "tbq"],
    "viscosity": ["mpas", "cp", "poise", "pas", "reyn"],
    "capacitance": ["pf", "nf", "uf", "mf", "farad"],
    "inductance": ["nh", "uh", "mh", "henry"],
    "conductance": ["microsiemens", "millisiemens", "siemens", "kilosiemens", "mho"],
    "luminousflux": ["mlm", "lm", "klm"],
    "flow": ["l/h", "l/min", "l/s", "m3/h", "m3/min", "m3/s", "gpm", "gph", "cfm", "cfs"],
    "luminousintensity": ["mcd", "cd", "kcd"],
    "substance": ["umol", "mmol", "mol", "kmol"],
    "catalysis": ["nkat", "ukat", "mkat", "kat"],
    "solidangle": ["sqdeg", "sr", "sphere"],
    "fuel": ["mpg", "mpguk", "l/100km", "km/l"],
}

# Metric "ladders" for ``humanize`` — an ordered, single-system set of canonical
# units per linear category, smallest factor first. Auto-scaling stays *within*
# one coherent system (metric/SI or the networking decimal ladder) so the result
# is never a surprising cross-system unit (e.g. a road distance never lands on
# nautical miles). Categories absent here do not support humanising.
HUMANIZE_LADDERS = {
    "length": ["mm", "cm", "m", "km"],
    "mass": ["mg", "g", "kg", "t"],
    "volume": ["ml", "l", "m3"],
    "time": ["ms", "s", "min", "h", "day"],
    "area": ["mm2", "cm2", "m2", "km2"],
    "digital": ["b", "kb", "mb", "gb", "tb"],
    "datarate": ["bps", "kbps", "mbps", "gbps", "tbps"],
    "charge": ["mc", "coulomb", "kc"],
    "voltage": ["uv", "mv", "v", "kv", "megavolt"],
    "current": ["ua", "ma", "a", "ka"],
    "resistance": ["milliohm", "ohm", "kohm", "megohm"],
    "capacitance": ["pf", "nf", "uf", "mf", "farad"],
    "inductance": ["nh", "uh", "mh", "henry"],
    "conductance": ["microsiemens", "millisiemens", "siemens", "kilosiemens"],
    "luminousflux": ["mlm", "lm", "klm"],
    "luminousintensity": ["mcd", "cd", "kcd"],
    "substance": ["umol", "mmol", "mol", "kmol"],
    "catalysis": ["nkat", "ukat", "mkat", "kat"],
}


def normalize_unit(unit):
    """Normalise a raw unit token: trim, lowercase, drop spaces/dots."""
    if unit is None:
        raise ValueError("unit is required")
    return str(unit).strip().lower().replace(" ", "").replace(".", "")


def category_of(unit):
    """Return the category name for a (raw) unit token, or None if unknown."""
    u = normalize_unit(unit)
    if u in _TEMP_UNITS:
        return "temperature"
    if u in _FUEL_UNITS:
        return "fuel"
    for name, table in _LINEAR.items():
        if u in table:
            return name
    return None


def list_categories():
    """Return the ordered list of supported category names."""
    return list(CANONICAL_UNITS.keys())


def units_for(category):
    """Return the canonical display units for a category, or raise ValueError."""
    cat = str(category).strip().lower()
    if cat not in CANONICAL_UNITS:
        raise ValueError("unknown category: %r" % category)
    return list(CANONICAL_UNITS[cat])


def _temp_to_celsius(value, unit):
    if unit == "c":
        return value
    if unit == "f":
        return (value - 32.0) * 5.0 / 9.0
    if unit == "k":
        return value - 273.15
    raise ValueError("unknown temperature unit: %r" % unit)


def _celsius_to(value_c, unit):
    if unit == "c":
        return value_c
    if unit == "f":
        return value_c * 9.0 / 5.0 + 32.0
    if unit == "k":
        return value_c + 273.15
    raise ValueError("unknown temperature unit: %r" % unit)


def _fuel_to_l100km(value, kind):
    """Convert a fuel-economy ``value`` of canonical ``kind`` to L/100km."""
    if kind == "l100km":
        return value
    if kind == "km_l":
        return 100.0 / value
    if kind == "mpg_us":
        # miles/US-gal -> km/L -> L/100km
        return 100.0 * _L_PER_US_GAL / (value * _KM_PER_MILE)
    if kind == "mpg_uk":
        return 100.0 * _L_PER_UK_GAL / (value * _KM_PER_MILE)
    raise ValueError("unknown fuel unit: %r" % kind)


def _l100km_to_fuel(value_l100, kind):
    """Convert an L/100km ``value_l100`` to canonical fuel ``kind``."""
    if kind == "l100km":
        return value_l100
    if kind == "km_l":
        return 100.0 / value_l100
    if kind == "mpg_us":
        return 100.0 * _L_PER_US_GAL / (value_l100 * _KM_PER_MILE)
    if kind == "mpg_uk":
        return 100.0 * _L_PER_UK_GAL / (value_l100 * _KM_PER_MILE)
    raise ValueError("unknown fuel unit: %r" % kind)


def _coerce_finite(value):
    """Parse ``value`` as a finite float, raising the canonical ValueErrors.

    Shared by every entry point that accepts a numeric quantity so the accepted
    inputs and error messages stay identical in one place.
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise ValueError("'value' must be a number")
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        raise ValueError("'value' must be finite")
    return numeric


def _resolve_category_pair(from_unit, to_unit):
    """Normalize a unit pair and return ``(f, t, category)``.

    Raises the canonical ValueErrors for an unknown unit or a cross-category
    pair. Shared by :func:`convert_units`, :func:`conversion_factor` and
    :func:`convert_delta` so the validation lives in exactly one place.
    """
    f = normalize_unit(from_unit)
    t = normalize_unit(to_unit)
    from_cat = category_of(f)
    to_cat = category_of(t)
    if from_cat is None:
        raise ValueError("unknown unit: %r" % from_unit)
    if to_cat is None:
        raise ValueError("unknown unit: %r" % to_unit)
    if from_cat != to_cat:
        raise ValueError(
            "cannot convert between %s (%s) and %s (%s)"
            % (from_unit, from_cat, to_unit, to_cat)
        )
    return f, t, from_cat


def convert_units(value, from_unit, to_unit):
    """Convert ``value`` from ``from_unit`` to ``to_unit``.

    Returns (result, category). Raises ValueError for unknown units,
    cross-category mismatches, or non-finite values.
    """
    numeric = _coerce_finite(value)
    f, t, from_cat = _resolve_category_pair(from_unit, to_unit)

    if from_cat == "temperature":
        celsius = _temp_to_celsius(numeric, _TEMP_UNITS[f])
        result = _celsius_to(celsius, _TEMP_UNITS[t])
        return result, "temperature"

    if from_cat == "fuel":
        if numeric <= 0.0:
            raise ValueError("fuel economy value must be positive")
        l100 = _fuel_to_l100km(numeric, _FUEL_UNITS[f])
        result = _l100km_to_fuel(l100, _FUEL_UNITS[t])
        return result, "fuel"

    table = _LINEAR[from_cat]
    result = numeric * table[f] / table[t]
    return result, from_cat


def convert_to_all(value, from_unit):
    """Convert ``value`` from ``from_unit`` into every canonical unit of its
    category.

    Returns (results, category) where ``results`` is an ordered list of
    {"unit": <canonical token>, "result": <float>} dicts (in the same order as
    CANONICAL_UNITS). Raises ValueError for unknown units or bad values — the
    validation is delegated to ``convert_units`` so behaviour stays identical.
    """
    cat = category_of(from_unit)
    if cat is None:
        raise ValueError("unknown unit: %r" % from_unit)
    results = []
    for unit in CANONICAL_UNITS[cat]:
        result, _ = convert_units(value, from_unit, unit)
        results.append({"unit": unit, "result": result})
    return results, cat


def humanize(value, from_unit):
    """Auto-scale ``value`` to the most readable unit on its metric ladder.

    Picks, from the category's HUMANIZE_LADDERS, the *largest* unit whose
    displayed magnitude is still >= 1 (so 1500 m -> 1.5 km, 0.005 m -> 5 mm).
    When the value is smaller than the smallest ladder unit (or is zero) the
    smallest unit is used. Scaling stays within a single coherent unit system,
    so the chosen unit is never a surprising cross-system one.

    Returns (scaled_value, unit, category). Raises ValueError for an unknown
    unit, a non-finite value, or a category with no humanise ladder (e.g.
    temperature, fuel, pressure).
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise ValueError("'value' must be a number")
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        raise ValueError("'value' must be finite")

    cat = category_of(from_unit)
    if cat is None:
        raise ValueError("unknown unit: %r" % from_unit)
    if cat not in HUMANIZE_LADDERS:
        raise ValueError("humanize is not supported for the %s category" % cat)

    table = _LINEAR[cat]
    ladder = HUMANIZE_LADDERS[cat]
    base = numeric * table[normalize_unit(from_unit)]

    chosen = None
    # Largest unit first; take the first whose magnitude is still >= 1.
    for unit in sorted(ladder, key=lambda u: table[u], reverse=True):
        if abs(base / table[unit]) >= 1.0:
            chosen = unit
            break
    if chosen is None:
        chosen = min(ladder, key=lambda u: table[u])
    return base / table[chosen], chosen, cat


def unit_info(unit):
    """Describe a single unit token.

    Returns {"unit": <normalized token>, "category": <name>, "aliases":
    [<every accepted token that means the same unit>]}. Raises ValueError for an
    unknown unit. Aliases are the other spellings the converter will accept for
    the same physical quantity (e.g. ``ft`` <- foot, feet).
    """
    u = normalize_unit(unit)
    cat = category_of(u)
    if cat is None:
        raise ValueError("unknown unit: %r" % unit)
    if cat == "temperature":
        kind = _TEMP_UNITS[u]
        aliases = [tok for tok, k in _TEMP_UNITS.items() if k == kind]
    elif cat == "fuel":
        kind = _FUEL_UNITS[u]
        aliases = [tok for tok, k in _FUEL_UNITS.items() if k == kind]
    else:
        table = _LINEAR[cat]
        factor = table[u]
        aliases = [tok for tok, fac in table.items() if fac == factor]
    return {"unit": u, "category": cat, "aliases": sorted(aliases)}


def _all_unit_tokens():
    """Yield (token, category) for every accepted unit token in every category.

    Used by ``search_units`` to scan the full alias space. Temperature and fuel
    live outside ``_LINEAR`` so they are folded in explicitly.
    """
    for token in _TEMP_UNITS:
        yield token, "temperature"
    for token in _FUEL_UNITS:
        yield token, "fuel"
    for cat, table in _LINEAR.items():
        for token in table:
            yield token, cat


def search_units(query):
    """Find every accepted unit token (canonical or alias) matching ``query``.

    The match is a case-insensitive substring test over the normalised token
    space, so ``"met"`` finds ``meter``/``metre``/``centimeter``..., and ``"ft"``
    finds ``ft``/``sqft``/``ftlb``. Returns an ordered list of
    {"unit": <token>, "category": <name>} dicts sorted by (category, unit).
    Raises ValueError when the query is empty.
    """
    if query is None:
        raise ValueError("query is required")
    q = str(query).strip().lower().replace(" ", "").replace(".", "")
    if not q:
        raise ValueError("query is empty")
    matches = []
    for token, cat in _all_unit_tokens():
        if q in token:
            matches.append((cat, token))
    matches = sorted(set(matches))
    return [{"unit": token, "category": cat} for cat, token in matches]


# Matches a leading signed number (incl. decimals / scientific notation),
# capturing the number and the trailing unit token.
_NUM_UNIT_RE = re.compile(
    r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(.+?)\s*$"
)
# Whitespace-delimited connector words ("to" / "in" / "as"). Spaces are required
# on BOTH sides so a connector cannot be carved out of a real unit token such as
# "min" (which contains "in") or " as ..." inside a longer word.
_CONNECTOR_RE = re.compile(r"\s+(?:to|in|as)\s+", re.IGNORECASE)


def parse_expression(text):
    """Parse a free-text conversion like ``"10 km to mi"``.

    Accepted shapes (case-insensitive, optional space between number and unit):
      - "10 km to mi"      (word connectors: to / in / as)
      - "10 km in mi"
      - "10km -> mi"       (arrow connectors: -> => > =)
      - "convert 10 km to mi"  (a leading "convert" keyword is ignored)

    Returns (value, from_unit, to_unit) as raw strings/number. Raises ValueError
    when the text cannot be parsed; the units themselves are validated later by
    ``convert_units``.
    """
    if text is None:
        raise ValueError("expression is required")
    s = str(text).strip()
    if not s:
        raise ValueError("expression is empty")
    # Drop an optional leading "convert" keyword.
    low = s.lower()
    if low.startswith("convert "):
        s = s[len("convert "):].strip()

    left = right = None
    # Prefer arrow connectors, which need no surrounding spaces.
    for arrow in ("->", "=>", ">", "="):
        if arrow in s:
            left, _, right = s.partition(arrow)
            break
    else:
        m = _CONNECTOR_RE.search(s)
        if m:
            left, right = s[:m.start()], s[m.end():]

    if left is None or right is None:
        raise ValueError("could not parse expression: %r" % text)

    nm = _NUM_UNIT_RE.match(left)
    to_unit = right.strip()
    if not nm or not to_unit:
        raise ValueError("could not parse expression: %r" % text)

    value = float(nm.group(1))
    from_unit = nm.group(2).strip()
    return value, from_unit, to_unit


def convert_expression(text):
    """Parse and evaluate a free-text conversion in one step.

    Returns (value, from_unit, to_unit, result, category). Raises ValueError on
    either a parse failure or an invalid conversion.
    """
    value, from_unit, to_unit = parse_expression(text)
    result, category = convert_units(value, from_unit, to_unit)
    return value, normalize_unit(from_unit), normalize_unit(to_unit), result, category


def conversion_factor(from_unit, to_unit):
    """Return the pure multiplicative factor ``k`` such that
    ``value_in_to == value_in_from * k`` for two units of the same LINEAR
    category.

    Returns (factor, category). Raises ValueError for unknown units, a
    cross-category pair, or a category whose conversion is not purely
    multiplicative (temperature is affine; fuel economy is reciprocal), since no
    single factor can describe those.
    """
    f, t, from_cat = _resolve_category_pair(from_unit, to_unit)
    if from_cat not in _LINEAR:
        raise ValueError(
            "%s conversions are not a single multiplicative factor" % from_cat
        )
    table = _LINEAR[from_cat]
    return table[f] / table[t], from_cat


# Hard ceiling on generated table rows, so a tiny step over a huge span cannot
# produce an unbounded response.
MAX_TABLE_ROWS = 1000


def conversion_table(from_unit, to_unit, start, stop, step):
    """Build a conversion table over the inclusive range ``[start, stop]``.

    Converts every value ``start, start+step, ... <= stop`` from ``from_unit``
    to ``to_unit``. Works for every category (linear, temperature, fuel), since
    each row delegates to ``convert_units``.

    Returns (rows, category) where ``rows`` is an ordered list of
    {"input": <float>, "result": <float>} dicts. Raises ValueError for unknown
    or cross-category units, non-finite bounds, a non-positive step, a stop that
    precedes start, or a range that would exceed ``MAX_TABLE_ROWS``.
    """
    try:
        start_f = float(start)
        stop_f = float(stop)
        step_f = float(step)
    except (TypeError, ValueError):
        raise ValueError("'start', 'stop' and 'step' must be numbers")
    for label, val in (("start", start_f), ("stop", stop_f), ("step", step_f)):
        if val != val or val in (float("inf"), float("-inf")):
            raise ValueError("'%s' must be finite" % label)
    if step_f <= 0.0:
        raise ValueError("'step' must be positive")
    if stop_f < start_f:
        raise ValueError("'stop' must be greater than or equal to 'start'")

    # +1 for the inclusive endpoint; the epsilon absorbs float drift so a clean
    # range like 0..10 step 1 yields exactly 11 rows, not 10.
    count = int(math.floor((stop_f - start_f) / step_f + 1e-9)) + 1
    if count > MAX_TABLE_ROWS:
        raise ValueError("too many rows (%d); max is %d" % (count, MAX_TABLE_ROWS))

    rows = []
    category = None
    for i in range(count):
        value = start_f + i * step_f
        result, category = convert_units(value, from_unit, to_unit)
        rows.append({"input": value, "result": result})
    return rows, category


def to_compound(value, from_unit, units):
    """Express a single quantity as a compound (mixed-unit) breakdown.

    Decomposes ``value`` (given in ``from_unit``) into an additive sum across an
    ordered set of ``units`` from the SAME linear category — the classic
    "3661 s -> 1 h 1 min 1 s" or "1.855 m -> 6 ft 0.83 in" presentation.

    Every unit except the smallest carries a whole (floored) amount; the
    smallest unit absorbs the fractional remainder, so the parts sum back to the
    original quantity exactly (modulo float precision). The target units are
    sorted largest-first internally, so the caller need not order them. A
    negative input keeps its sign on every part (-3661 s -> -1 h -1 min -1 s).

    Returns (parts, category) where ``parts`` is a list of
    {"unit": <token>, "value": <float>} in largest-to-smallest order. Raises
    ValueError for a non-finite value, an empty/non-list unit set, an unknown or
    cross-category unit, or a non-linear category (temperature is affine and
    fuel economy is reciprocal — neither decomposes into an additive sum).
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise ValueError("'value' must be a number")
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        raise ValueError("'value' must be finite")

    if not isinstance(units, (list, tuple)):
        raise ValueError("'units' must be a list of unit tokens")
    if len(units) == 0:
        raise ValueError("'units' must not be empty")

    f = normalize_unit(from_unit)
    cat = category_of(f)
    if cat is None:
        raise ValueError("unknown unit: %r" % from_unit)
    if cat not in _LINEAR:
        raise ValueError(
            "compound breakdown is not supported for the %s category" % cat
        )
    table = _LINEAR[cat]

    norm_units = []
    for u in units:
        nu = normalize_unit(u)
        ucat = category_of(nu)
        if ucat is None:
            raise ValueError("unknown unit: %r" % u)
        if ucat != cat:
            raise ValueError(
                "cannot mix %s (%s) with %s (%s)" % (u, ucat, from_unit, cat)
            )
        norm_units.append(nu)

    # Largest unit first so the greedy decomposition is correct regardless of
    # the order the caller passed the units in.
    order = sorted(norm_units, key=lambda x: table[x], reverse=True)

    base = numeric * table[f]
    sign = -1.0 if base < 0 else 1.0
    remaining = abs(base)

    parts = []
    last = len(order) - 1
    for i, unit in enumerate(order):
        factor = table[unit]
        if i == last:
            amount = remaining / factor
        else:
            amount = math.floor(remaining / factor)
            remaining -= amount * factor
        parts.append({"unit": unit, "value": sign * amount})
    return parts, cat


def format_compound(parts):
    """Render compound ``parts`` (from :func:`to_compound`) as a string.

    Produces e.g. ``"6 ft 0.83 in"``. Leading zero-valued parts are dropped so a
    short quantity reads cleanly (``0 ft 5 in`` -> ``"5 in"``), but the result is
    never empty — an all-zero breakdown keeps its smallest part (``"0 in"``).
    Whole numbers render without a trailing ``.0``.
    """
    nonzero = [p for p in parts if p["value"] != 0]
    use = nonzero if nonzero else parts[-1:]
    chunks = []
    for p in use:
        v = p["value"]
        if v == int(v):
            v = int(v)
        chunks.append("%s %s" % (v, p["unit"]))
    return " ".join(chunks)


def compare_quantities(a_value, a_unit, b_value, b_unit):
    """Compare two quantities of the SAME category and report their relation.

    Restates both quantities in each other's units (so they can be read side by
    side), then says which is larger and by how much. The numeric comparison is
    done on a single common scale — quantity ``b`` is expressed in ``a``'s unit —
    so it is exact for every category, including the affine temperature scale and
    the reciprocal fuel-economy scale. ``larger`` is purely the numeric ordering
    of the two magnitudes; it does not encode any "better/worse" judgement (a
    smaller L/100km is more economical, but the larger *number* is still
    reported as the larger quantity).

    Returns a dict::

        {
            "category": <name>,
            "a": {"value": <float>, "unit": <token>},
            "b": {"value": <float>, "unit": <token>},
            "a_in_b_unit": <a restated in b's unit>,
            "b_in_a_unit": <b restated in a's unit>,
            "difference": <a_value - b_in_a_unit, in a's unit>,
            "ratio": <a_value / b_in_a_unit, or None when b is zero>,
            "larger": "a" | "b" | "equal",
        }

    Raises ValueError for unknown units, a cross-category pair, or non-finite
    values — the validation is delegated to ``convert_units``.
    """
    # convert_units validates both numbers, both units, and that they share a
    # category; it raises ValueError otherwise. Doing both conversions up front
    # means a bad input fails before we try to compare.
    b_in_a, category = convert_units(b_value, b_unit, a_unit)
    a_in_b, _ = convert_units(a_value, a_unit, b_unit)

    a_num = float(a_value)
    if a_num > b_in_a:
        larger = "a"
    elif a_num < b_in_a:
        larger = "b"
    else:
        larger = "equal"

    ratio = (a_num / b_in_a) if b_in_a != 0 else None
    return {
        "category": category,
        "a": {"value": a_num, "unit": normalize_unit(a_unit)},
        "b": {"value": float(b_value), "unit": normalize_unit(b_unit)},
        "a_in_b_unit": a_in_b,
        "b_in_a_unit": b_in_a,
        "difference": a_num - b_in_a,
        "ratio": ratio,
        "larger": larger,
    }


def sum_quantities(items, to_unit=None):
    """Add a list of quantities of the SAME linear category into one total.

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted). Every quantity is converted to a
    common base, summed, then expressed in ``to_unit`` — or, when ``to_unit`` is
    omitted, in the first item's unit. This is the natural aggregate of the
    converter: "2 ft + 30 cm + 1 m == how many metres?".

    Returns (total, unit, category) where ``unit`` is the normalised target unit.
    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, or a non-linear category
    (temperature is affine and fuel economy is reciprocal — neither sums
    meaningfully, just as they have no single conversion factor).
    """
    if not isinstance(items, (list, tuple)):
        raise ValueError("'items' must be a list of {value, unit} entries")
    if len(items) == 0:
        raise ValueError("'items' must not be empty")

    parsed = []
    for item in items:
        if isinstance(item, dict):
            value, unit = item.get("value"), item.get("unit")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            value, unit = item
        else:
            raise ValueError("each item must be a {value, unit} entry")
        if value is None or unit is None:
            raise ValueError("each item needs a 'value' and a 'unit'")
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            raise ValueError("'value' must be a number")
        if numeric != numeric or numeric in (float("inf"), float("-inf")):
            raise ValueError("'value' must be finite")
        parsed.append((numeric, normalize_unit(unit)))

    category = category_of(parsed[0][1])
    if category is None:
        raise ValueError("unknown unit: %r" % parsed[0][1])
    if category not in _LINEAR:
        raise ValueError("summing is not supported for the %s category" % category)
    table = _LINEAR[category]

    base_total = 0.0
    for numeric, unit in parsed:
        cat = category_of(unit)
        if cat is None:
            raise ValueError("unknown unit: %r" % unit)
        if cat != category:
            raise ValueError(
                "cannot sum %s (%s) with %s (%s)" % (unit, cat, parsed[0][1], category)
            )
        base_total += numeric * table[unit]

    target = normalize_unit(to_unit) if to_unit is not None else parsed[0][1]
    tcat = category_of(target)
    if tcat is None:
        raise ValueError("unknown unit: %r" % to_unit)
    if tcat != category:
        raise ValueError(
            "cannot total into %s (%s); items are %s" % (target, tcat, category)
        )
    return base_total / table[target], target, category


# Matches one signed number immediately followed by its unit token inside a
# compound string like "6 ft 2 in" or "1h 1min 1s". The unit token is letters/
# digits with optional internal slashes (so "km/h" survives), and must start
# with a letter so it is never confused with the next number.
_COMPOUND_PART_RE = re.compile(
    r"([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z][A-Za-z0-9/]*)"
)


def parse_compound(text):
    """Parse a compound (mixed-unit) string into its individual parts.

    The exact inverse of :func:`format_compound`: ``"6 ft 2 in"`` ->
    ``[{"value": 6.0, "unit": "ft"}, {"value": 2.0, "unit": "in"}]``. Accepts any
    spacing (``"1h 1min 1s"`` works too). Every part must belong to the SAME
    linear category.

    Returns (parts, category). Raises ValueError when nothing parses, a token is
    an unknown unit, the parts span more than one category, or the category is
    non-linear (temperature/fuel never decompose into additive parts).
    """
    if text is None:
        raise ValueError("expression is required")
    s = str(text).strip()
    if not s:
        raise ValueError("expression is empty")

    matches = _COMPOUND_PART_RE.findall(s)
    if not matches:
        raise ValueError("could not parse compound expression: %r" % text)

    parts = []
    category = None
    for raw_value, raw_unit in matches:
        unit = normalize_unit(raw_unit)
        cat = category_of(unit)
        if cat is None:
            raise ValueError("unknown unit: %r" % raw_unit)
        if category is None:
            category = cat
            if category not in _LINEAR:
                raise ValueError(
                    "compound parsing is not supported for the %s category" % category
                )
        elif cat != category:
            raise ValueError(
                "cannot mix %s (%s) with the %s parts" % (raw_unit, cat, category)
            )
        parts.append({"value": float(raw_value), "unit": unit})
    return parts, category


def compound_total(text, to_unit):
    """Parse a compound string and total it into a single ``to_unit``.

    Combines :func:`parse_compound` with :func:`sum_quantities`, so
    ``compound_total("6 ft 2 in", "cm")`` returns the height as one number of
    centimetres. Returns (total, unit, category, parts). Raises ValueError for an
    unparseable string, unknown/cross-category units, or a non-linear category.
    """
    parts, category = parse_compound(text)
    total, unit, _ = sum_quantities(parts, to_unit)
    return total, unit, category, parts


# Temperature INTERVAL (delta) scale, in units of one Celsius-degree. A change of
# 1 C equals a change of 1 K (identical step size) but only 9/5 of a Fahrenheit
# degree — so an interval conversion uses the scale alone, with NO 32-degree /
# 273.15 offset. This is why a "10 C rise" is an "18 F rise", not "50 F".
_TEMP_DELTA_SCALE = {"c": 1.0, "k": 1.0, "f": 5.0 / 9.0}


def convert_delta(value, from_unit, to_unit):
    """Convert a DIFFERENCE/interval between two units of the same category.

    For every linear category this is identical to :func:`convert_units` (the
    conversion is already purely multiplicative). The distinction matters only
    for temperature: an absolute conversion applies the affine offset
    (``0 C -> 32 F``) whereas an interval conversion applies the scale alone
    (``10 C-change -> 18 F-change``).

    Returns (result, category). Raises ValueError for unknown units, a
    cross-category pair, a non-finite value, or the fuel-economy category (a
    reciprocal scale has no meaningful linear interval).
    """
    numeric = _coerce_finite(value)
    f, t, from_cat = _resolve_category_pair(from_unit, to_unit)

    if from_cat == "temperature":
        return numeric * _TEMP_DELTA_SCALE[_TEMP_UNITS[f]] / _TEMP_DELTA_SCALE[_TEMP_UNITS[t]], from_cat
    if from_cat == "fuel":
        raise ValueError("interval conversion is not defined for the fuel category")
    table = _LINEAR[from_cat]
    return numeric * table[f] / table[t], from_cat


def aggregate_quantities(items, to_unit=None):
    """Summarise a list of quantities of the SAME linear category.

    Like :func:`sum_quantities`, every quantity is restated in a single common
    ``to_unit`` (or, when omitted, the first item's unit) so the statistics are
    apples-to-apples. Beyond the running total this also reports the count, the
    arithmetic mean, the smallest and largest quantity (each with the index of
    the item it came from), and the range (max - min) — the natural "describe
    this set of measurements" companion to the plain sum.

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "sum": <float>,
            "mean": <float>,
            "min": {"value": <float>, "index": <int>},
            "max": {"value": <float>, "index": <int>},
            "range": <float>,            # max - min, in the target unit
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, or a non-linear category
    (temperature is affine and fuel economy is reciprocal — neither aggregates
    meaningfully, exactly as neither sums). Validation is delegated to
    ``sum_quantities`` so the accepted inputs stay identical.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and returns the total in the
    # resolved target unit, so a bad input fails here before any statistics run.
    total, unit, category = sum_quantities(items, to_unit)

    # Re-express every item in the resolved target unit (shared helper). The
    # category/units were already proven valid above, so it cannot fail here.
    converted = _restate_items(items, unit)

    count = len(converted)
    min_index = min(range(count), key=lambda i: converted[i])
    max_index = max(range(count), key=lambda i: converted[i])
    minimum = converted[min_index]
    maximum = converted[max_index]
    return {
        "category": category,
        "unit": unit,
        "count": count,
        "sum": total,
        "mean": total / count,
        "min": {"value": minimum, "index": min_index},
        "max": {"value": maximum, "index": max_index},
        "range": maximum - minimum,
    }


def sort_quantities(items, to_unit=None, descending=False):
    """Order a list of quantities of the SAME linear category by magnitude.

    Every quantity is restated in a single common ``to_unit`` (or, when omitted,
    the first item's unit) — exactly like :func:`sum_quantities` and
    :func:`aggregate_quantities` — then ordered ascending (the default) or
    descending. The sort is *stable*: items that compare equal keep their
    original input order, so the returned ``index`` of equal quantities is itself
    ascending. This is the natural "rank these measurements" companion to the
    plain sum and the descriptive statistics.

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "descending": <bool>,
            "items": [{"index": <original position>, "value": <float>}, ...],
        }

    where ``items`` is the ordered list and each ``index`` points back to the
    item's position in the input. Raises ValueError for an empty/non-list input,
    a malformed item, an unknown or cross-category unit, a non-finite value, or a
    non-linear category (temperature is affine and fuel economy is reciprocal —
    neither orders meaningfully on a single common unit, exactly as neither
    sums). Validation is delegated to ``sum_quantities`` so the accepted inputs
    stay identical.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves the common
    # target unit, so a bad input fails here before any ordering runs.
    _, unit, category = sum_quantities(items, to_unit)

    # Re-express every item in the resolved target unit (shared helper), tagged
    # with its original input position.
    ranked = [{"index": index, "value": value}
              for index, value in enumerate(_restate_items(items, unit))]

    # ``sorted`` is stable, so equal magnitudes preserve their input order; for a
    # descending sort we negate the key (rather than reverse=True) to keep that
    # same stable ordering among ties instead of flipping it.
    sign = -1.0 if descending else 1.0
    ranked.sort(key=lambda r: sign * r["value"])
    return {
        "category": category,
        "unit": unit,
        "count": len(ranked),
        "descending": bool(descending),
        "items": ranked,
    }


def describe_quantities(items, to_unit=None):
    """Full descriptive statistics for a list of SAME-category quantities.

    The richer companion to :func:`aggregate_quantities`: on top of the count,
    sum, mean, min, max and range it also reports the **median** (the middle
    value, or the mean of the two middle values for an even count), the
    population **variance** / standard deviation (dividing by N), and the sample
    variance / standard deviation (dividing by N-1, the unbiased estimator). The
    sample figures are ``None`` for a single item, since a sample standard
    deviation is undefined for one observation.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the statistics are apples-to-apples —
    exactly like :func:`sum_quantities`, :func:`aggregate_quantities` and
    :func:`sort_quantities`.

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "sum": <float>,
            "mean": <float>,
            "median": <float>,
            "variance": <float>,            # population (/ N)
            "stdev": <float>,               # population (/ N)
            "sample_variance": <float|None>,  # sample (/ N-1), None for n == 1
            "sample_stdev": <float|None>,     # sample (/ N-1), None for n == 1
            "min": {"value": <float>, "index": <int>},
            "max": {"value": <float>, "index": <int>},
            "range": <float>,               # max - min, in the target unit
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, or a non-linear category
    (temperature is affine and fuel economy is reciprocal — neither aggregates
    meaningfully, exactly as neither sums). Validation is delegated to
    ``sum_quantities`` so the accepted inputs stay identical.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves both the running
    # total and the common target unit, so a bad input fails here before any
    # statistics run.
    total, unit, category = sum_quantities(items, to_unit)

    # Re-express every item in the resolved target unit (shared helper). The
    # category/units were already proven valid above, so it cannot fail here.
    converted = _restate_items(items, unit)

    count = len(converted)
    mean = total / count

    # Median on a sorted copy (the original order is preserved for min/max
    # indices below). Even counts average the two central values.
    ordered = sorted(converted)
    mid = count // 2
    if count % 2 == 1:
        median = ordered[mid]
    else:
        median = (ordered[mid - 1] + ordered[mid]) / 2.0

    squared_deviations = sum((x - mean) ** 2 for x in converted)
    variance = squared_deviations / count
    stdev = math.sqrt(variance)
    if count > 1:
        sample_variance = squared_deviations / (count - 1)
        sample_stdev = math.sqrt(sample_variance)
    else:
        sample_variance = None
        sample_stdev = None

    min_index = min(range(count), key=lambda i: converted[i])
    max_index = max(range(count), key=lambda i: converted[i])
    minimum = converted[min_index]
    maximum = converted[max_index]
    return {
        "category": category,
        "unit": unit,
        "count": count,
        "sum": total,
        "mean": mean,
        "median": median,
        "variance": variance,
        "stdev": stdev,
        "sample_variance": sample_variance,
        "sample_stdev": sample_stdev,
        "min": {"value": minimum, "index": min_index},
        "max": {"value": maximum, "index": max_index},
        "range": maximum - minimum,
    }


def shape_quantities(items, to_unit=None):
    """Distribution-shape statistics for a list of SAME-category quantities.

    The third-/fourth-moment companion to :func:`describe_quantities` (which
    stops at the mean, variance and standard deviation): this reports the
    **skewness** (how lopsided the distribution is — positive means a longer
    right tail, negative a longer left tail, zero a symmetric spread) and the
    **excess kurtosis** (how heavy-tailed/peaked it is relative to a normal
    distribution — positive means heavier tails, negative lighter tails).

    Both are dimensionless standardised moments, so — like the Pearson ``r`` of
    :func:`correlation` — their value does not depend on the chosen ``to_unit``;
    the unit only affects the reported ``mean`` and ``stdev``. Two flavours of
    each are returned:

    - the **population** statistics (the biased moment estimators ``g1``/``g2``,
      computed by dividing the moments by N), always defined for two or more
      points; and
    - the **sample** statistics (the bias-corrected estimators ``G1``/``G2``,
      matching Excel's ``SKEW``/``KURT``), which need at least three points for
      skewness and four for kurtosis and are otherwise ``None``.

    When the values have zero spread (a constant series, so the standard
    deviation is zero) the shape is undefined and every skewness/kurtosis figure
    is ``None`` — exactly as ``correlation`` reports ``None`` for a flat series.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit), identical to the rest of the aggregate
    family. ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted).

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "mean": <float>,
            "stdev": <float>,                 # population (/ N)
            "skewness": <float|None>,         # population g1, None if flat
            "sample_skewness": <float|None>,  # bias-corrected G1, None if n<3 or flat
            "kurtosis": <float|None>,         # population EXCESS kurtosis g2
            "sample_kurtosis": <float|None>,  # bias-corrected G2, None if n<4 or flat
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, or a non-linear category
    (temperature is affine and fuel economy is reciprocal — neither aggregates
    meaningfully, exactly as neither sums). Validation is delegated to
    ``sum_quantities`` so the accepted inputs stay identical.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves the common
    # target unit, so a bad input fails here before any statistics run.
    _, unit, category = sum_quantities(items, to_unit)
    values = _restate_items(items, unit)

    n = len(values)
    mean = sum(values) / n
    # Central moments m2 (variance), m3 and m4, each divided by N (population).
    m2 = sum((x - mean) ** 2 for x in values) / n
    m3 = sum((x - mean) ** 3 for x in values) / n
    m4 = sum((x - mean) ** 4 for x in values) / n
    stdev = math.sqrt(m2)

    if m2 == 0:
        # A constant series has no shape — skewness and kurtosis are undefined.
        return {
            "category": category,
            "unit": unit,
            "count": n,
            "mean": mean,
            "stdev": stdev,
            "skewness": None,
            "sample_skewness": None,
            "kurtosis": None,
            "sample_kurtosis": None,
        }

    # Population (biased) Fisher-Pearson moments.
    g1 = m3 / (m2 ** 1.5)
    g2 = m4 / (m2 ** 2) - 3.0  # EXCESS kurtosis (normal distribution -> 0)

    # Sample (bias-corrected) estimators, matching Excel SKEW / KURT. Skewness
    # needs n >= 3 and kurtosis n >= 4 (the correction factors divide by n-2 /
    # n-3); below those counts the unbiased estimate is undefined.
    if n >= 3:
        sample_skewness = math.sqrt(n * (n - 1)) / (n - 2) * g1
    else:
        sample_skewness = None
    if n >= 4:
        sample_kurtosis = (
            (n - 1) / ((n - 2) * (n - 3)) * ((n + 1) * g2 + 6.0)
        )
    else:
        sample_kurtosis = None

    return {
        "category": category,
        "unit": unit,
        "count": n,
        "mean": mean,
        "stdev": stdev,
        "skewness": g1,
        "sample_skewness": sample_skewness,
        "kurtosis": g2,
        "sample_kurtosis": sample_kurtosis,
    }


def cumulative_quantities(items, to_unit=None):
    """Running (cumulative) totals over a list of SAME-category quantities.

    Like :func:`sum_quantities`, every quantity is restated in a single common
    ``to_unit`` (or, when omitted, the first item's unit) so the partial sums are
    apples-to-apples. Then it walks the list *in input order* and reports the
    running total after each item — the natural "how does the total build up?"
    companion to the plain sum (e.g. the cumulative distance after each leg of a
    journey). The final cumulative value equals the plain ``total`` (modulo float
    precision).

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "total": <float>,            # == the last cumulative value
            "items": [{"index": <int>, "value": <float>, "cumulative": <float>}, ...],
        }

    where ``items`` is in the original input order, ``value`` is that item
    restated in the target unit, and ``cumulative`` is the running total up to and
    including it. Raises ValueError for an empty/non-list input, a malformed item,
    an unknown or cross-category unit, a non-finite value, or a non-linear
    category (temperature is affine and fuel economy is reciprocal — neither sums
    meaningfully, exactly as neither sums). Validation is delegated to
    ``sum_quantities`` so the accepted inputs stay identical.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves both the running
    # total and the common target unit, so a bad input fails here before any
    # accumulation runs.
    total, unit, category = sum_quantities(items, to_unit)

    # Re-express every item in the resolved target unit, accumulating as we go.
    # The category/units were already proven valid above, so convert_units cannot
    # fail here.
    running = 0.0
    out = []
    for index, item in enumerate(items):
        if isinstance(item, dict):
            value, item_unit = item.get("value"), item.get("unit")
        else:
            value, item_unit = item
        restated, _ = convert_units(value, item_unit, unit)
        running += restated
        out.append({"index": index, "value": restated, "cumulative": running})
    return {
        "category": category,
        "unit": unit,
        "count": len(out),
        "total": total,
        "items": out,
    }


def percentile_quantities(items, percentile, to_unit=None):
    """The ``percentile``-th percentile of a list of SAME-category quantities.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the ordering is apples-to-apples — exactly
    like :func:`sum_quantities` and the rest of the aggregate family. The
    percentile is computed by **linear interpolation between the closest ranks**
    (the R-7 / Excel ``PERCENTILE.INC`` method): the 0th percentile is the
    minimum, the 100th is the maximum, and the 50th equals the **median** reported
    by :func:`describe_quantities`.

    ``percentile`` must be a number in ``[0, 100]``. ``items`` is a list of
    {"value": <number>, "unit": <token>} dicts (a ``(value, unit)`` tuple is also
    accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "percentile": <float>,       # the requested p, echoed back
            "value": <float>,            # the p-th percentile, in the target unit
        }

    Raises ValueError for a non-finite or out-of-range ``percentile``, an
    empty/non-list input, a malformed item, an unknown or cross-category unit, a
    non-finite value, or a non-linear category (temperature is affine and fuel
    economy is reciprocal — neither orders meaningfully on a single common unit).
    The item validation is delegated to ``sum_quantities`` so the accepted inputs
    stay identical to the rest of the aggregate family.
    """
    try:
        p = float(percentile)
    except (TypeError, ValueError):
        raise ValueError("'percentile' must be a number")
    if p != p or p in (float("inf"), float("-inf")):
        raise ValueError("'percentile' must be finite")
    if p < 0.0 or p > 100.0:
        raise ValueError("'percentile' must be between 0 and 100")

    # sum_quantities does the full item validation and resolves the common target
    # unit, so a bad input fails here before any ordering runs.
    _, unit, category = sum_quantities(items, to_unit)

    converted = []
    for item in items:
        if isinstance(item, dict):
            value, item_unit = item.get("value"), item.get("unit")
        else:
            value, item_unit = item
        restated, _ = convert_units(value, item_unit, unit)
        converted.append(restated)

    ordered = sorted(converted)
    n = len(ordered)
    if n == 1:
        value = ordered[0]
    else:
        # Fractional rank in [0, n-1]; interpolate between its neighbours.
        rank = (p / 100.0) * (n - 1)
        lower = int(math.floor(rank))
        upper = int(math.ceil(rank))
        frac = rank - lower
        value = ordered[lower] + (ordered[upper] - ordered[lower]) * frac
    return {
        "category": category,
        "unit": unit,
        "count": n,
        "percentile": p,
        "value": value,
    }


def proportions(items, to_unit=None):
    """Each quantity's share of the group total, as a fraction and a percentage.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the shares are apples-to-apples — exactly
    like :func:`sum_quantities` and the rest of the aggregate family. Then each
    item's ``fraction`` is its restated value divided by the total, and
    ``percent`` is that fraction times 100. By construction the fractions sum to
    1 and the percentages to 100 (modulo float precision) — the natural "what
    slice of the whole is each part?" companion to the plain sum and the
    cumulative total (e.g. each expense as a share of the budget).

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "total": <float>,            # the group total, in the target unit
            "items": [{"index": <int>, "value": <float>,
                       "fraction": <float>, "percent": <float>}, ...],
        }

    where ``items`` is in the original input order, ``value`` is that item
    restated in the target unit, ``fraction`` is value/total and ``percent`` is
    fraction*100. Raises ValueError for an empty/non-list input, a malformed
    item, an unknown or cross-category unit, a non-finite value, a non-linear
    category (temperature is affine and fuel economy is reciprocal — neither sums
    meaningfully, so neither has shares), or a zero total (a share of nothing is
    undefined). Item validation is delegated to ``sum_quantities`` so the
    accepted inputs stay identical to the rest of the aggregate family.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves both the group
    # total and the common target unit, so a bad input fails here before any
    # share is computed.
    total, unit, category = sum_quantities(items, to_unit)
    if total == 0:
        raise ValueError("cannot compute proportions when the total is zero")

    # Re-express every item in the resolved target unit, tagged with its original
    # input position. The category/units were already proven valid above, so
    # convert_units cannot fail here.
    out = []
    for index, item in enumerate(items):
        if isinstance(item, dict):
            value, item_unit = item.get("value"), item.get("unit")
        else:
            value, item_unit = item
        restated, _ = convert_units(value, item_unit, unit)
        fraction = restated / total
        out.append({
            "index": index,
            "value": restated,
            "fraction": fraction,
            "percent": fraction * 100.0,
        })
    return {
        "category": category,
        "unit": unit,
        "count": len(out),
        "total": total,
        "items": out,
    }


def _restate_items(items, unit):
    """Re-express every entry of an already-validated ``items`` list in ``unit``.

    The whole aggregate family (sum, stats, sort, ...) first calls
    ``sum_quantities`` to validate the input and resolve the common target unit,
    then walks ``items`` a second time to restate each value in that unit. This
    helper holds that second walk in ONE place. It assumes the list/items/units
    were already proven valid by ``sum_quantities``, so ``convert_units`` cannot
    fail here. Returns a plain list of floats in the original input order.
    """
    converted = []
    for item in items:
        if isinstance(item, dict):
            value, item_unit = item.get("value"), item.get("unit")
        else:
            value, item_unit = item
        restated, _ = convert_units(value, item_unit, unit)
        converted.append(restated)
    return converted


def differences(items, to_unit=None):
    """Successive differences between consecutive quantities — the discrete
    inverse of :func:`cumulative_quantities`.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the deltas are apples-to-apples — exactly
    like :func:`sum_quantities` and the rest of the aggregate family. Then it
    walks the list *in input order* and reports, for each item, the change from
    the previous one: the first item's ``difference`` is the value itself (the
    step up from zero), and every later ``difference`` is ``value[i] -
    value[i-1]``. This is the exact inverse of the cumulative sum: feeding these
    differences back through :func:`cumulative_quantities` reconstructs the
    original restated series, and the final running total equals the plain sum
    (e.g. odometer readings -> the distance of each individual leg).

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "total": <float>,            # sum of the item values (as in /api/sum)
            "items": [{"index": <int>, "value": <float>, "difference": <float>}, ...],
        }

    where ``items`` is in the original input order, ``value`` is that item
    restated in the target unit, and ``difference`` is its change from the
    previous item. Raises ValueError for an empty/non-list input, a malformed
    item, an unknown or cross-category unit, a non-finite value, or a non-linear
    category (temperature is affine and fuel economy is reciprocal — neither sums
    meaningfully, so neither has differences). Validation is delegated to
    ``sum_quantities`` so the accepted inputs stay identical to the rest of the
    aggregate family.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves both the running
    # total and the common target unit, so a bad input fails here before any
    # difference runs.
    total, unit, category = sum_quantities(items, to_unit)

    converted = _restate_items(items, unit)
    out = []
    previous = 0.0
    for index, value in enumerate(converted):
        out.append({"index": index, "value": value, "difference": value - previous})
        previous = value
    return {
        "category": category,
        "unit": unit,
        "count": len(out),
        "total": total,
        "items": out,
    }


def zscores(items, to_unit=None):
    """Standardise each quantity into a z-score (standard score).

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the scores are apples-to-apples — exactly
    like :func:`sum_quantities` and the rest of the aggregate family. Each item's
    ``zscore`` is ``(value - mean) / stdev`` using the **population** mean and
    standard deviation (dividing by N), matching the ``mean``/``stdev`` reported
    by :func:`describe_quantities`. By construction the z-scores have a mean of 0
    and a population standard deviation of 1 — the natural "how many standard
    deviations from the average is each measurement?" companion to the
    descriptive statistics (e.g. flagging outliers in a set of readings).

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "mean": <float>,             # population mean, in the target unit
            "stdev": <float>,            # population stdev, in the target unit
            "items": [{"index": <int>, "value": <float>, "zscore": <float>}, ...],
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, a non-linear category
    (temperature is affine and fuel economy is reciprocal), or a **zero standard
    deviation** (every quantity is identical, so a z-score is undefined — there is
    no spread to divide by). Item validation is delegated to ``sum_quantities`` so
    the accepted inputs stay identical to the rest of the aggregate family.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves both the running
    # total and the common target unit, so a bad input fails here before any
    # score runs.
    total, unit, category = sum_quantities(items, to_unit)

    converted = _restate_items(items, unit)
    count = len(converted)
    mean = total / count
    variance = sum((x - mean) ** 2 for x in converted) / count
    stdev = math.sqrt(variance)
    if stdev == 0:
        raise ValueError(
            "cannot compute z-scores when every quantity is identical "
            "(standard deviation is zero)"
        )

    out = [
        {"index": index, "value": value, "zscore": (value - mean) / stdev}
        for index, value in enumerate(converted)
    ]
    return {
        "category": category,
        "unit": unit,
        "count": count,
        "mean": mean,
        "stdev": stdev,
        "items": out,
    }


def normalize_quantities(items, to_unit=None):
    """Min-max scale each quantity to the unit interval ``[0, 1]``.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the scaling is apples-to-apples — exactly
    like :func:`sum_quantities` and the rest of the aggregate family. Each item's
    ``normalized`` value is ``(value - min) / (max - min)``, so the smallest
    quantity maps to 0, the largest to 1, and everything else falls in between —
    the natural "where does each measurement sit on the observed scale?" companion
    to :func:`proportions` (which instead reports each value's share of the
    total).

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "min": <float>,              # smallest quantity, in the target unit
            "max": <float>,              # largest quantity, in the target unit
            "items": [{"index": <int>, "value": <float>, "normalized": <float>}, ...],
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, a non-linear category
    (temperature is affine and fuel economy is reciprocal), or a **zero range**
    (every quantity is identical, so min == max and the scaling would divide by
    zero). Item validation is delegated to ``sum_quantities`` so the accepted
    inputs stay identical to the rest of the aggregate family.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves the common
    # target unit, so a bad input fails here before any scaling runs.
    _, unit, category = sum_quantities(items, to_unit)

    converted = _restate_items(items, unit)
    minimum = min(converted)
    maximum = max(converted)
    span = maximum - minimum
    if span == 0:
        raise ValueError(
            "cannot normalize when every quantity is identical "
            "(min equals max, so the range is zero)"
        )

    out = [
        {"index": index, "value": value, "normalized": (value - minimum) / span}
        for index, value in enumerate(converted)
    ]
    return {
        "category": category,
        "unit": unit,
        "count": len(out),
        "min": minimum,
        "max": maximum,
        "items": out,
    }


def _percentile_of_sorted(ordered, p):
    """Return the ``p``-th percentile of an already-sorted list of floats.

    Uses the same linear interpolation between closest ranks (R-7 / Excel
    ``PERCENTILE.INC``) as :func:`percentile_quantities`, so P0 is the minimum,
    P100 the maximum and P50 the median. Factored out so the quartile / outlier
    helpers compute exactly the same percentiles the ``/api/percentile`` endpoint
    reports. ``ordered`` must be non-empty (callers validate via
    ``sum_quantities`` first).
    """
    n = len(ordered)
    if n == 1:
        return ordered[0]
    rank = (p / 100.0) * (n - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    frac = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * frac


def quartiles(items, to_unit=None):
    """Five-number summary (min, Q1, median, Q3, max) plus the IQR.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the order statistics are apples-to-apples
    — exactly like :func:`sum_quantities` and the rest of the aggregate family.
    The quartiles use the same R-7 / Excel ``PERCENTILE.INC`` interpolation as
    :func:`percentile_quantities`, so Q1 == P25, the median == P50 (matching
    :func:`describe_quantities`) and Q3 == P75. The **interquartile range**
    ``iqr`` is ``Q3 - Q1``, the spread of the middle half of the data — the box
    of a box-and-whisker plot and the basis for :func:`outliers`.

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "min": <float>, "q1": <float>, "median": <float>,
            "q3": <float>, "max": <float>,
            "iqr": <float>,              # q3 - q1
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, or a non-linear category
    (temperature is affine and fuel economy is reciprocal — neither orders
    meaningfully on a single common unit). Item validation is delegated to
    ``sum_quantities`` so the accepted inputs stay identical to the rest of the
    aggregate family.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves the common
    # target unit, so a bad input fails here before any ordering runs.
    _, unit, category = sum_quantities(items, to_unit)

    ordered = sorted(_restate_items(items, unit))
    q1 = _percentile_of_sorted(ordered, 25)
    median = _percentile_of_sorted(ordered, 50)
    q3 = _percentile_of_sorted(ordered, 75)
    return {
        "category": category,
        "unit": unit,
        "count": len(ordered),
        "min": ordered[0],
        "q1": q1,
        "median": median,
        "q3": q3,
        "max": ordered[-1],
        "iqr": q3 - q1,
    }


def outliers(items, to_unit=None, k=1.5):
    """Flag outliers by Tukey's interquartile-range fences.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the fences are apples-to-apples — exactly
    like :func:`sum_quantities` and the rest of the aggregate family. Using the
    quartiles from :func:`quartiles` it builds the classic Tukey fences
    ``lower = Q1 - k*IQR`` and ``upper = Q3 + k*IQR`` (``k`` defaults to 1.5, the
    standard "mild outlier" multiplier; ``k = 3`` marks the far/extreme
    outliers), then flags every quantity falling strictly outside ``[lower,
    upper]`` — the natural "which of these readings are anomalous?" companion to
    :func:`describe_quantities` and :func:`zscores`.

    ``k`` must be a finite, non-negative number. ``items`` is a list of
    {"value": <number>, "unit": <token>} dicts (a ``(value, unit)`` tuple is also
    accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "k": <float>,                # the multiplier used, echoed back
            "q1": <float>, "q3": <float>, "iqr": <float>,
            "lower_fence": <float>, "upper_fence": <float>,
            "outlier_count": <int>,
            "items": [{"index": <int>, "value": <float>, "is_outlier": <bool>}, ...],
        }

    Raises ValueError for a non-finite or negative ``k``, an empty/non-list
    input, a malformed item, an unknown or cross-category unit, a non-finite
    value, or a non-linear category (temperature is affine and fuel economy is
    reciprocal). Item validation is delegated to ``sum_quantities`` so the
    accepted inputs stay identical to the rest of the aggregate family.
    """
    try:
        multiplier = float(k)
    except (TypeError, ValueError):
        raise ValueError("'k' must be a number")
    if multiplier != multiplier or multiplier in (float("inf"), float("-inf")):
        raise ValueError("'k' must be finite")
    if multiplier < 0.0:
        raise ValueError("'k' must be non-negative")

    # sum_quantities does the full validation and resolves the common target
    # unit, so a bad input fails here before any fence is computed.
    _, unit, category = sum_quantities(items, to_unit)

    converted = _restate_items(items, unit)
    ordered = sorted(converted)
    q1 = _percentile_of_sorted(ordered, 25)
    q3 = _percentile_of_sorted(ordered, 75)
    iqr = q3 - q1
    lower_fence = q1 - multiplier * iqr
    upper_fence = q3 + multiplier * iqr

    out = []
    outlier_count = 0
    for index, value in enumerate(converted):
        is_outlier = value < lower_fence or value > upper_fence
        if is_outlier:
            outlier_count += 1
        out.append({"index": index, "value": value, "is_outlier": is_outlier})
    return {
        "category": category,
        "unit": unit,
        "count": len(converted),
        "k": multiplier,
        "q1": q1,
        "q3": q3,
        "iqr": iqr,
        "lower_fence": lower_fence,
        "upper_fence": upper_fence,
        "outlier_count": outlier_count,
        "items": out,
    }


# Hard ceiling on histogram bins, so a single request cannot ask for an
# unbounded number of buckets.
MAX_HISTOGRAM_BINS = 1000


def histogram(items, bins, to_unit=None):
    """Bucket a list of SAME-category quantities into equal-width bins.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the binning is apples-to-apples — exactly
    like :func:`sum_quantities` and the rest of the aggregate family. The
    observed range ``[min, max]`` is split into ``bins`` equal-width buckets and
    each quantity is tallied into the bucket it lands in. Buckets are
    half-open ``[start, end)`` so a value sits in exactly one, except the final
    bucket, which is closed ``[start, max]`` so the maximum is counted. By
    construction the bucket counts sum to ``count`` — the natural "how are these
    measurements distributed?" companion to :func:`describe_quantities` and
    :func:`quartiles`.

    ``bins`` must be an integer in ``[1, MAX_HISTOGRAM_BINS]``. ``items`` is a
    list of {"value": <number>, "unit": <token>} dicts (a ``(value, unit)``
    tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "bins": <int>,
            "min": <float>, "max": <float>,
            "items": [{"index": <int>, "start": <float>, "end": <float>,
                       "count": <int>}, ...],
        }

    Raises ValueError for a non-integer / out-of-range ``bins``, an empty/non-list
    input, a malformed item, an unknown or cross-category unit, a non-finite
    value, a non-linear category (temperature is affine and fuel economy is
    reciprocal), or a **zero range** (every quantity is identical, so min == max
    and there is no span to divide into bins). Item validation is delegated to
    ``sum_quantities`` so the accepted inputs stay identical to the rest of the
    aggregate family.
    """
    # bool is an int subclass; reject it so True/False can't masquerade as a
    # bin count.
    if isinstance(bins, bool) or not isinstance(bins, int):
        raise ValueError("'bins' must be an integer")
    if bins < 1:
        raise ValueError("'bins' must be at least 1")
    if bins > MAX_HISTOGRAM_BINS:
        raise ValueError("too many bins (%d); max is %d" % (bins, MAX_HISTOGRAM_BINS))

    # sum_quantities does the full validation and resolves the common target
    # unit, so a bad input fails here before any binning runs.
    _, unit, category = sum_quantities(items, to_unit)

    converted = _restate_items(items, unit)
    minimum = min(converted)
    maximum = max(converted)
    span = maximum - minimum
    if span == 0:
        raise ValueError(
            "cannot build a histogram when every quantity is identical "
            "(min equals max, so the range is zero)"
        )

    width = span / bins
    counts = [0] * bins
    for value in converted:
        # Floor into a bucket; the maximum (and any float drift past it) lands in
        # the final closed bucket rather than overflowing the list.
        index = int(math.floor((value - minimum) / width))
        if index >= bins:
            index = bins - 1
        counts[index] += 1

    out = []
    for i in range(bins):
        start = minimum + i * width
        # The last bucket closes exactly on the observed maximum so the printed
        # edge matches ``max`` rather than drifting by float accumulation.
        end = maximum if i == bins - 1 else minimum + (i + 1) * width
        out.append({"index": i, "start": start, "end": end, "count": counts[i]})
    return {
        "category": category,
        "unit": unit,
        "count": len(converted),
        "bins": bins,
        "min": minimum,
        "max": maximum,
        "items": out,
    }


def means(items, to_unit=None):
    """The four classical means of a list of SAME-category quantities.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the means are apples-to-apples — exactly
    like :func:`sum_quantities` and the rest of the aggregate family. It then
    reports the three **Pythagorean means** plus the **quadratic mean**:

    * ``arithmetic`` — the ordinary average ``sum / n`` (matching the ``mean``
      reported by :func:`aggregate_quantities` / :func:`describe_quantities`);
    * ``geometric`` — the n-th root of the product, ``exp(mean(ln value))``, the
      right average for ratios and growth rates;
    * ``harmonic`` — ``n / sum(1 / value)``, the right average for rates defined
      per unit (e.g. speeds over equal distances);
    * ``quadratic`` — the root-mean-square ``sqrt(mean(value^2))``.

    For any set of positive quantities these obey the classic inequality chain
    ``harmonic <= geometric <= arithmetic <= quadratic`` (with equality only when
    every quantity is identical) — the natural "which average?" companion to
    :func:`describe_quantities`. Because the geometric and harmonic means are
    only defined for **positive** values, this rejects any quantity that is zero
    or negative once restated in the target unit (a linear restating scales every
    value by a positive factor, so positivity does not depend on the chosen
    unit).

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "arithmetic": <float>,
            "geometric": <float>,
            "harmonic": <float>,
            "quadratic": <float>,
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, a non-linear category
    (temperature is affine and fuel economy is reciprocal — neither averages
    meaningfully on a single common unit), or a **non-positive** quantity. Item
    validation is delegated to ``sum_quantities`` so the accepted inputs stay
    identical to the rest of the aggregate family.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves both the
    # arithmetic total and the common target unit, so a bad input fails here
    # before any mean is computed.
    total, unit, category = sum_quantities(items, to_unit)

    converted = _restate_items(items, unit)
    count = len(converted)
    for value in converted:
        if value <= 0:
            raise ValueError(
                "geometric and harmonic means require every quantity to be "
                "positive (got %r in the target unit)" % value
            )

    arithmetic = total / count
    geometric = math.exp(sum(math.log(v) for v in converted) / count)
    harmonic = count / sum(1.0 / v for v in converted)
    quadratic = math.sqrt(sum(v * v for v in converted) / count)
    return {
        "category": category,
        "unit": unit,
        "count": count,
        "arithmetic": arithmetic,
        "geometric": geometric,
        "harmonic": harmonic,
        "quadratic": quadratic,
    }


# The normal-consistency scale factor for the median absolute deviation: for a
# normal distribution E[MAD] == sigma / 1.4826..., so multiplying the MAD by
# this constant yields an estimator of the standard deviation that is robust to
# outliers. The exact value is 1 / Phi^-1(3/4) (the reciprocal of the 0.75
# quantile of the standard normal), which to the precision we report is 1.4826.
MAD_SCALE = 1.4826

# Iglewicz & Hoaglin (1993) modified z-score constants. 0.6745 == Phi^-1(3/4),
# the 0.75 quantile of the standard normal, so 0.6745/MAD is a consistent
# estimator of 1/sigma for normally distributed data (it is exactly the
# reciprocal of MAD_SCALE to four places). 1.253314 == sqrt(pi/2) is the
# corresponding consistency factor for the *mean* absolute deviation, used only
# as the fallback scale when the MAD is zero. The recommended outlier cut-off is
# a modified z-score whose magnitude exceeds 3.5.
ROBUST_Z_CONSTANT = 0.6745
ROBUST_Z_MEANAD_CONSTANT = 1.253314
ROBUST_Z_DEFAULT_THRESHOLD = 3.5


def mad_quantities(items, to_unit=None):
    """Absolute-deviation (robust dispersion) statistics for SAME-category items.

    The robust companion to :func:`describe_quantities` (which reports the
    variance- and standard-deviation-based spread, both of which square the
    deviations and so are sensitive to outliers). Every quantity is first
    restated in a single common ``to_unit`` (or, when omitted, the first item's
    unit) so the deviations are apples-to-apples — exactly like
    :func:`sum_quantities` and the rest of the aggregate family. It then reports:

    * ``mean`` / ``median`` — the two centres (matching
      :func:`describe_quantities`), so the deviations can be read against the
      centre they are measured from;
    * ``mean_abs_deviation`` — the mean absolute deviation about the mean,
      ``mean(|x - mean|)`` (a linear-deviation analogue of the standard
      deviation; never larger than the population stdev);
    * ``median_abs_deviation`` — the classic MAD, ``median(|x - median|)``, the
      most outlier-robust spread measure here; and
    * ``median_abs_deviation_scaled`` — that MAD multiplied by :data:`MAD_SCALE`
      (1.4826), a robust estimate of the population standard deviation that
      agrees with it for normally distributed data.

    The per-item ``abs_deviation`` is ``|value - mean|``, so the mean of the
    per-item absolute deviations equals ``mean_abs_deviation`` exactly. Both the
    median and the scaled MAD use the same R-7 / Excel ``PERCENTILE.INC`` median
    as :func:`describe_quantities` and :func:`quartiles`.

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "mean": <float>,
            "median": <float>,
            "mean_abs_deviation": <float>,           # mean(|x - mean|)
            "median_abs_deviation": <float>,         # median(|x - median|)
            "median_abs_deviation_scaled": <float>,  # 1.4826 * the MAD
            "items": [{"index": <int>, "value": <float>,
                       "abs_deviation": <float>}, ...],   # |value - mean|
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, or a non-linear category
    (temperature is affine and fuel economy is reciprocal — neither has a
    meaningful spread on a single common unit). Item validation is delegated to
    ``sum_quantities`` so the accepted inputs stay identical to the rest of the
    aggregate family.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves both the running
    # total and the common target unit, so a bad input fails here before any
    # deviation runs.
    total, unit, category = sum_quantities(items, to_unit)

    converted = _restate_items(items, unit)
    count = len(converted)
    mean = total / count
    median = _percentile_of_sorted(sorted(converted), 50)

    mean_abs_deviation = sum(abs(x - mean) for x in converted) / count
    median_abs_deviation = _percentile_of_sorted(
        sorted(abs(x - median) for x in converted), 50)

    out = [
        {"index": index, "value": value, "abs_deviation": abs(value - mean)}
        for index, value in enumerate(converted)
    ]
    return {
        "category": category,
        "unit": unit,
        "count": count,
        "mean": mean,
        "median": median,
        "mean_abs_deviation": mean_abs_deviation,
        "median_abs_deviation": median_abs_deviation,
        "median_abs_deviation_scaled": MAD_SCALE * median_abs_deviation,
        "items": out,
    }


def cv_quantities(items, to_unit=None):
    """Relative-dispersion statistics for a list of SAME-category quantities.

    The *relative* (scale-free) companion to :func:`describe_quantities` (which
    reports the absolute variance/standard deviation) and :func:`mad_quantities`
    (robust absolute spread). Where the standard deviation answers "how spread
    out, in the unit?", these answer "how spread out *relative to the mean*?",
    so two series on different scales can be compared directly. Every quantity is
    first restated in a single common ``to_unit`` (or, when omitted, the first
    item's unit) so the statistics are apples-to-apples — exactly like
    :func:`sum_quantities` and the rest of the aggregate family. It reports:

    * ``mean`` / ``variance`` / ``stdev`` — the population centre and spread
      (matching :func:`describe_quantities`), so the ratios can be read against
      the figures they are built from; ``sample_stdev`` divides by ``N-1`` and is
      ``None`` for a single item (undefined, exactly as in
      :func:`describe_quantities`);
    * ``cv`` — the **coefficient of variation**, ``stdev / |mean|``, the
      dimensionless population relative standard deviation; ``sample_cv`` is the
      same ratio built from the sample stdev. ``cv_percent`` /
      ``sample_cv_percent`` are those ratios as percentages;
    * ``index_of_dispersion`` — the variance-to-mean ratio ``variance / mean``
      (a.k.a. the Fano factor; ``1`` for a Poisson process, ``< 1`` under-
      dispersed, ``> 1`` over-dispersed); and
    * ``signal_to_noise`` — the reciprocal of the CV, ``mean / stdev``.

    The CV and the index of dispersion are undefined when the mean is zero, and
    the signal-to-noise ratio is undefined when the standard deviation is zero;
    each is reported as ``None`` in that case rather than raising. The CV uses
    ``|mean|`` so it stays a non-negative magnitude, while the (signed) index of
    dispersion and signal-to-noise keep the mean's sign.

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "mean": <float>,
            "variance": <float>,            # population (/ N)
            "stdev": <float>,               # population (/ N)
            "sample_stdev": <float|None>,   # sample (/ N-1), None for n == 1
            "cv": <float|None>,             # stdev / |mean|, None when mean == 0
            "sample_cv": <float|None>,      # sample_stdev / |mean|
            "cv_percent": <float|None>,         # 100 * cv
            "sample_cv_percent": <float|None>,  # 100 * sample_cv
            "index_of_dispersion": <float|None>,  # variance / mean
            "signal_to_noise": <float|None>,      # mean / stdev, None when stdev == 0
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, or a non-linear category
    (temperature is affine and fuel economy is reciprocal — neither has a
    meaningful spread on a single common unit). Item validation is delegated to
    ``sum_quantities`` so the accepted inputs stay identical to the rest of the
    aggregate family.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves both the running
    # total and the common target unit, so a bad input fails here before any
    # statistics run.
    total, unit, category = sum_quantities(items, to_unit)

    converted = _restate_items(items, unit)
    count = len(converted)
    mean = total / count

    squared_deviations = sum((x - mean) ** 2 for x in converted)
    variance = squared_deviations / count
    stdev = math.sqrt(variance)
    sample_stdev = math.sqrt(squared_deviations / (count - 1)) if count > 1 else None

    # The CV uses |mean| so it stays a non-negative relative magnitude; it (and
    # the index of dispersion) are undefined at a zero mean, and the SNR is
    # undefined at a zero spread. Report None there rather than dividing by zero.
    cv = (stdev / abs(mean)) if mean != 0 else None
    sample_cv = (sample_stdev / abs(mean)) if (mean != 0 and sample_stdev is not None) else None
    index_of_dispersion = (variance / mean) if mean != 0 else None
    signal_to_noise = (mean / stdev) if stdev != 0 else None

    return {
        "category": category,
        "unit": unit,
        "count": count,
        "mean": mean,
        "variance": variance,
        "stdev": stdev,
        "sample_stdev": sample_stdev,
        "cv": cv,
        "sample_cv": sample_cv,
        "cv_percent": (100.0 * cv) if cv is not None else None,
        "sample_cv_percent": (100.0 * sample_cv) if sample_cv is not None else None,
        "index_of_dispersion": index_of_dispersion,
        "signal_to_noise": signal_to_noise,
    }


def rank_quantities(items, to_unit=None, descending=False):
    """Rank a list of SAME-category quantities by magnitude.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the ordering is apples-to-apples — exactly
    like :func:`sum_quantities` and the rest of the aggregate family. Each item,
    *in its original input order*, is tagged with:

    * ``rank`` — its 1-based rank by ascending magnitude (or descending, when
      ``descending`` is set). Ties share the **average** of the ordinal ranks
      they span (fractional / "average" ranking), so the ranks always sum to
      ``n*(n+1)/2`` regardless of ties.
    * ``percent_rank`` — the rank rescaled to ``[0, 100]`` as
      ``(rank - 1) / (n - 1) * 100``. For an ascending ranking of distinct
      values this is the exact inverse of :func:`percentile_quantities` (R-7):
      feeding an item's ``percent_rank`` back to ``percentile_quantities``
      returns that item's value. For a single item ``percent_rank`` is 0.

    This is the "where does each measurement place in the set?" companion to
    :func:`sort_quantities` (which reorders the list) and the inverse view of
    :func:`percentile_quantities` (which maps a percentile to a value).

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "descending": <bool>,
            "items": [{"index": <int>, "value": <float>,
                       "rank": <float>, "percent_rank": <float>}, ...],
        }

    where ``items`` is in the original input order. Raises ValueError for an
    empty/non-list input, a malformed item, an unknown or cross-category unit, a
    non-finite value, or a non-linear category (temperature is affine and fuel
    economy is reciprocal — neither orders meaningfully on a single common unit).
    Item validation is delegated to ``sum_quantities`` so the accepted inputs
    stay identical to the rest of the aggregate family.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves the common
    # target unit, so a bad input fails here before any ranking runs.
    _, unit, category = sum_quantities(items, to_unit)

    converted = _restate_items(items, unit)
    n = len(converted)

    # Order the original positions by magnitude. ``sorted`` is stable, so equal
    # magnitudes keep their input order; for a descending rank we negate the key
    # (rather than reverse=True) to keep that same stable order among ties.
    sign = -1.0 if descending else 1.0
    order = sorted(range(n), key=lambda i: sign * converted[i])

    # Walk runs of equal values in the ordered list and assign every member the
    # average of the ordinal ranks the run spans (fractional ranking).
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and converted[order[j + 1]] == converted[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # ordinal positions i..j -> 1-based mean
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1

    out = []
    for index in range(n):
        rank = ranks[index]
        percent_rank = 0.0 if n == 1 else (rank - 1.0) / (n - 1.0) * 100.0
        out.append({
            "index": index,
            "value": converted[index],
            "rank": rank,
            "percent_rank": percent_rank,
        })
    return {
        "category": category,
        "unit": unit,
        "count": n,
        "descending": bool(descending),
        "items": out,
    }


def mode_quantities(items, to_unit=None):
    """The mode(s) — most frequent magnitude(s) — of SAME-category quantities.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the frequency count is apples-to-apples —
    exactly like :func:`sum_quantities` and the rest of the aggregate family.
    Frequencies are counted by **exact equality** of the restated values (a
    linear restating scales every value by the same positive factor, so two
    quantities are equal in the target unit iff they were equal originally). The
    ``modes`` are every value sharing the highest frequency, returned ascending;
    when more than one value ties for that frequency the data is
    ``is_multimodal``. This is the frequency-based "what is the typical value?"
    companion to the mean/median reported by :func:`describe_quantities` (the
    third classic measure of central tendency).

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "frequency": <int>,          # the highest observed frequency
            "is_multimodal": <bool>,     # True when more than one value ties
            "modes": [<float>, ...],     # every value at that frequency, ascending
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, or a non-linear category
    (temperature is affine and fuel economy is reciprocal — neither restates onto
    a single common unit). Item validation is delegated to ``sum_quantities`` so
    the accepted inputs stay identical to the rest of the aggregate family.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves the common
    # target unit, so a bad input fails here before any counting runs.
    _, unit, category = sum_quantities(items, to_unit)

    converted = _restate_items(items, unit)
    # Count frequencies, remembering first-seen order so the eventual ascending
    # sort is the only ordering applied (not dict-insertion happenstance).
    counts = {}
    for value in converted:
        counts[value] = counts.get(value, 0) + 1

    frequency = max(counts.values())
    modes = sorted(value for value, freq in counts.items() if freq == frequency)
    return {
        "category": category,
        "unit": unit,
        "count": len(converted),
        "frequency": frequency,
        "is_multimodal": len(modes) > 1,
        "modes": modes,
    }


def weighted_mean(items, to_unit=None):
    """The weighted arithmetic mean of a list of SAME-category quantities.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the average is apples-to-apples — exactly
    like :func:`sum_quantities` and the rest of the aggregate family. Each item
    may carry a ``weight`` (a non-negative number); the result is
    ``sum(weight * value) / sum(weight)``. A missing weight defaults to ``1.0``,
    so an unweighted list reduces exactly to the arithmetic ``mean`` reported by
    :func:`describe_quantities`. This is the "average where some measurements
    count more than others" companion to the plain mean (e.g. a grade-weighted
    average, or a price averaged by quantity sold).

    ``items`` is a list of {"value": <number>, "unit": <token>, "weight"?:
    <number>} dicts (a ``(value, unit)`` tuple is also accepted and is treated as
    weight 1). The value/unit validation is delegated to ``sum_quantities`` so
    the accepted inputs stay identical to the rest of the aggregate family.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "total_weight": <float>,     # sum of the weights
            "weighted_mean": <float>,    # the weighted average, in the target unit
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, a non-linear category
    (temperature is affine and fuel economy is reciprocal), a non-numeric /
    non-finite / negative ``weight``, or a **zero total weight** (every weight is
    zero, so the average would divide by zero).
    """
    # sum_quantities does the full value/unit validation and resolves the common
    # target unit, so a bad item fails here before any weighting runs. It reads
    # only 'value'/'unit' from each dict, so the extra 'weight' key is ignored.
    _, unit, category = sum_quantities(items, to_unit)

    converted = _restate_items(items, unit)
    weights = []
    for item in items:
        if isinstance(item, dict):
            raw_weight = item.get("weight", 1.0)
            if raw_weight is None:
                raw_weight = 1.0
        else:
            raw_weight = 1.0
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            raise ValueError("'weight' must be a number")
        if weight != weight or weight in (float("inf"), float("-inf")):
            raise ValueError("'weight' must be finite")
        if weight < 0.0:
            raise ValueError("'weight' must be non-negative")
        weights.append(weight)

    total_weight = sum(weights)
    if total_weight == 0:
        raise ValueError(
            "cannot compute a weighted mean when every weight is zero"
        )
    weighted_sum = sum(w * v for w, v in zip(weights, converted))
    return {
        "category": category,
        "unit": unit,
        "count": len(converted),
        "total_weight": total_weight,
        "weighted_mean": weighted_sum / total_weight,
    }


def moving_average(items, window, to_unit=None):
    """Simple moving (rolling) average over a list of SAME-category quantities.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the windows are apples-to-apples — exactly
    like :func:`sum_quantities` and the rest of the aggregate family. Walking the
    list *in input order*, it reports the mean of every contiguous window of
    ``window`` consecutive items: one entry per fully-populated window, so a list
    of ``n`` items yields ``n - window + 1`` averages (a ``window`` of 1 simply
    echoes each value, and a ``window`` equal to ``n`` yields the single overall
    mean). This is the smoothing / trend companion to :func:`cumulative_quantities`
    and :func:`differences` (e.g. a 7-day moving average of daily readings).

    ``window`` must be an integer in ``[1, len(items)]``. ``items`` is a list of
    {"value": <number>, "unit": <token>} dicts (a ``(value, unit)`` tuple is also
    accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,              # number of input items
            "window": <int>,
            "items": [{"start_index": <int>, "end_index": <int>,
                       "average": <float>}, ...],
        }

    where each entry's ``start_index``/``end_index`` are the inclusive input
    positions the window spans and ``average`` is their mean in the target unit.
    Raises ValueError for a non-integer ``window``, a ``window`` below 1 or
    larger than the number of items, an empty/non-list input, a malformed item,
    an unknown or cross-category unit, a non-finite value, or a non-linear
    category (temperature is affine and fuel economy is reciprocal). Item
    validation is delegated to ``sum_quantities`` so the accepted inputs stay
    identical to the rest of the aggregate family.
    """
    # bool is an int subclass; reject it so True/False can't masquerade as a
    # window length.
    if isinstance(window, bool) or not isinstance(window, int):
        raise ValueError("'window' must be an integer")
    if window < 1:
        raise ValueError("'window' must be at least 1")

    # sum_quantities does the full validation and resolves the common target
    # unit, so a bad input fails here before any averaging runs.
    _, unit, category = sum_quantities(items, to_unit)

    converted = _restate_items(items, unit)
    n = len(converted)
    if window > n:
        raise ValueError(
            "'window' (%d) cannot exceed the number of items (%d)" % (window, n)
        )

    out = []
    running = sum(converted[:window])
    for start in range(n - window + 1):
        if start > 0:
            # Slide the window: drop the element leaving, add the one entering.
            running += converted[start + window - 1] - converted[start - 1]
        out.append({
            "start_index": start,
            "end_index": start + window - 1,
            "average": running / window,
        })
    return {
        "category": category,
        "unit": unit,
        "count": n,
        "window": window,
        "items": out,
    }


def ema(items, alpha=None, span=None, to_unit=None):
    """Exponential moving average (exponential smoothing) over SAME-category
    quantities.

    The exponentially-weighted companion to :func:`moving_average` (a *simple*
    moving average, which weights every item in its window equally and only
    starts once a full window exists). An EMA instead produces one smoothed value
    per item — over the *whole* history so far — but weights recent items more
    heavily, with the influence of older items decaying geometrically. Walking the
    list *in input order* it applies the standard recurrence

        ema[0] = value[0]
        ema[i] = alpha * value[i] + (1 - alpha) * ema[i - 1]   (i > 0)

    so a larger ``alpha`` (nearer 1) tracks the latest value closely while a
    smaller ``alpha`` (nearer 0) smooths more heavily. This is the
    reactive/trend-following companion to :func:`cumulative_quantities`,
    :func:`differences` and :func:`moving_average` (e.g. an exponentially-smoothed
    series of daily readings).

    The smoothing factor can be given **either** directly as ``alpha`` (a number
    in ``(0, 1]``) **or** as a ``span`` ``s`` (a number ``>= 1``, the common
    "N-period EMA" parameter), which maps to ``alpha = 2 / (s + 1)`` — so a span
    of 1 is ``alpha = 1`` (no smoothing) and larger spans smooth more. Exactly one
    of ``alpha``/``span`` may be supplied; when neither is given ``alpha`` defaults
    to 0.5. Supplying both is an error.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the smoothing is apples-to-apples — exactly
    like :func:`sum_quantities` and the rest of the aggregate family. ``items`` is
    a list of {"value": <number>, "unit": <token>} dicts (a ``(value, unit)``
    tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "alpha": <float>,            # the smoothing factor actually used
            "span": <float|None>,        # the span, when given (else None)
            "items": [{"index": <int>, "value": <float>, "ema": <float>}, ...],
        }

    where ``items`` is in the original input order, ``value`` is that item restated
    in the target unit and ``ema`` is the smoothed value up to and including it.
    Raises ValueError for supplying both ``alpha`` and ``span``, a non-finite or
    out-of-range ``alpha`` (must be in ``(0, 1]``) / ``span`` (must be ``>= 1``),
    an empty/non-list input, a malformed item, an unknown or cross-category unit, a
    non-finite value, or a non-linear category (temperature is affine and fuel
    economy is reciprocal). Item validation is delegated to :func:`_series_values`
    so the accepted inputs stay identical to the rest of the aggregate family.
    """
    if alpha is not None and span is not None:
        raise ValueError("supply only one of 'alpha' or 'span', not both")

    span_value = None
    if span is not None:
        try:
            span_value = float(span)
        except (TypeError, ValueError):
            raise ValueError("'span' must be a number")
        if span_value != span_value or span_value in (float("inf"), float("-inf")):
            raise ValueError("'span' must be finite")
        if span_value < 1.0:
            raise ValueError("'span' must be at least 1")
        a = 2.0 / (span_value + 1.0)
    elif alpha is not None:
        try:
            a = float(alpha)
        except (TypeError, ValueError):
            raise ValueError("'alpha' must be a number")
        if a != a or a in (float("inf"), float("-inf")):
            raise ValueError("'alpha' must be finite")
        if a <= 0.0 or a > 1.0:
            raise ValueError("'alpha' must be in (0, 1]")
    else:
        a = 0.5

    # _series_values does the full validation and resolves the common target
    # unit, so a bad input fails here before any smoothing runs.
    converted, unit, category = _series_values(items, to_unit)

    out = []
    current = None
    for index, value in enumerate(converted):
        if index == 0:
            current = value
        else:
            current = a * value + (1.0 - a) * current
        out.append({"index": index, "value": value, "ema": current})
    return {
        "category": category,
        "unit": unit,
        "count": len(converted),
        "alpha": a,
        "span": span_value,
        "items": out,
    }


# --------------------------------------------------------------------------- #
# Bivariate statistics — two paired series of quantities
# --------------------------------------------------------------------------- #
# The whole aggregate family above is *univariate*: it summarises one list of
# same-category quantities. The functions below are *bivariate* — they relate
# two parallel series ``x`` and ``y`` (e.g. distance vs time, mass vs volume) and
# ask how they co-vary. Each series is validated and restated on its own common
# unit independently (so x can be a length while y is a time); only the pairing
# (equal length, point i of x with point i of y) ties them together.


def _series_values(items, to_unit):
    """Validate one series of SAME-category quantities and restate it.

    Reuses :func:`sum_quantities` for the full validation (list shape, item
    shape, finite values, single linear category, valid target) and
    :func:`_restate_items` to express every value in the resolved common unit.
    Returns (values, unit, category) where ``values`` is a list of floats in the
    original input order.
    """
    _, unit, category = sum_quantities(items, to_unit)
    return _restate_items(items, unit), unit, category


def _paired_series(x_items, y_items, to_x=None, to_y=None):
    """Validate and restate two paired series ``x`` and ``y``.

    Each series is validated/restated independently via :func:`_series_values`,
    so the two may belong to different categories (length vs time, etc.). The
    pairing requires the two series to have the SAME number of points and at
    least two of them (a single point has no spread to co-vary).

    Returns a dict with the two value lists, their resolved units and
    categories, and the shared point count ``n``. Raises ValueError when the
    lengths differ or there are fewer than two paired points (the underlying
    per-series validation raises first for any malformed/cross-category input).
    """
    xs, x_unit, x_cat = _series_values(x_items, to_x)
    ys, y_unit, y_cat = _series_values(y_items, to_y)
    if len(xs) != len(ys):
        raise ValueError(
            "'x' and 'y' must have the same number of items (%d vs %d)"
            % (len(xs), len(ys))
        )
    n = len(xs)
    if n < 2:
        raise ValueError("at least two paired points are required")
    return {
        "x": xs, "y": ys,
        "x_unit": x_unit, "y_unit": y_unit,
        "x_category": x_cat, "y_category": y_cat,
        "n": n,
    }


def _co_moments(xs, ys):
    """Return the means and the raw (un-normalised) sums of squares/products.

    Computes ``mean_x``, ``mean_y`` and the three sums
    ``Sxy = Σ(x-mx)(y-my)``, ``Sxx = Σ(x-mx)²`` and ``Syy = Σ(y-my)²`` shared by
    every bivariate statistic below (covariance divides them by n or n-1;
    correlation and regression take their ratios).
    """
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    sxx = sum((x - mean_x) ** 2 for x in xs)
    syy = sum((y - mean_y) ** 2 for y in ys)
    return mean_x, mean_y, sxy, sxx, syy


def covariance(x_items, y_items, to_x=None, to_y=None):
    """Covariance of two paired series of quantities.

    Each series is restated on its own common unit (``to_x`` / ``to_y``, or each
    series' first unit when omitted). Reports both the **population** covariance
    (dividing the co-moment ``Σ(x-mx)(y-my)`` by N) and the **sample** covariance
    (dividing by N-1, the unbiased estimator). The covariance carries the product
    unit ``x_unit*y_unit``; a positive value means the two move together, a
    negative value means they move oppositely.

    Returns a dict::

        {
            "x_category", "y_category",
            "x_unit", "y_unit",
            "count",
            "mean_x", "mean_y",
            "covariance",          # population (/ N)
            "sample_covariance",   # sample (/ N-1)
        }

    Raises ValueError for mismatched lengths, fewer than two paired points, or
    any malformed/cross-category series (delegated to ``sum_quantities``).
    """
    s = _paired_series(x_items, y_items, to_x, to_y)
    xs, ys, n = s["x"], s["y"], s["n"]
    mean_x, mean_y, sxy, _, _ = _co_moments(xs, ys)
    return {
        "x_category": s["x_category"], "y_category": s["y_category"],
        "x_unit": s["x_unit"], "y_unit": s["y_unit"],
        "count": n,
        "mean_x": mean_x, "mean_y": mean_y,
        "covariance": sxy / n,
        "sample_covariance": sxy / (n - 1),
    }


def correlation(x_items, y_items, to_x=None, to_y=None):
    """Pearson correlation coefficient of two paired series of quantities.

    Each series is restated on its own common unit (``to_x`` / ``to_y``, or each
    series' first unit when omitted), then the Pearson product-moment correlation
    ``r = Σ(x-mx)(y-my) / √(Σ(x-mx)² · Σ(y-my)²)`` is computed. ``r`` lies in
    ``[-1, 1]``: +1 is a perfect increasing linear relation, -1 a perfect
    decreasing one, 0 no linear relation. ``r`` is dimensionless (the units
    cancel), so it is unchanged by the choice of ``to_x``/``to_y``. When either
    series has zero spread (a constant series) the correlation is undefined and
    reported as ``None``. The (population and sample) covariance and each series'
    mean and population standard deviation are reported alongside.

    Returns a dict::

        {
            "x_category", "y_category",
            "x_unit", "y_unit",
            "count",
            "mean_x", "mean_y",
            "stdev_x", "stdev_y",        # population (/ N)
            "covariance", "sample_covariance",
            "correlation",               # Pearson r, or None when undefined
        }

    Raises ValueError for mismatched lengths, fewer than two paired points, or
    any malformed/cross-category series (delegated to ``sum_quantities``).
    """
    s = _paired_series(x_items, y_items, to_x, to_y)
    xs, ys, n = s["x"], s["y"], s["n"]
    mean_x, mean_y, sxy, sxx, syy = _co_moments(xs, ys)
    denom = math.sqrt(sxx * syy)
    pearson = (sxy / denom) if denom != 0 else None
    return {
        "x_category": s["x_category"], "y_category": s["y_category"],
        "x_unit": s["x_unit"], "y_unit": s["y_unit"],
        "count": n,
        "mean_x": mean_x, "mean_y": mean_y,
        "stdev_x": math.sqrt(sxx / n), "stdev_y": math.sqrt(syy / n),
        "covariance": sxy / n,
        "sample_covariance": sxy / (n - 1),
        "correlation": pearson,
    }


def linear_regression(x_items, y_items, to_x=None, to_y=None):
    """Ordinary least-squares linear fit ``y = slope·x + intercept``.

    Each series is restated on its own common unit (``to_x`` / ``to_y``, or each
    series' first unit when omitted), then the best-fit line of ``y`` on ``x`` is
    found by minimising the squared residuals: ``slope = Σ(x-mx)(y-my)/Σ(x-mx)²``
    and ``intercept = my - slope·mx``. The slope carries the unit
    ``y_unit/x_unit``; the intercept carries ``y_unit``. ``r`` is the Pearson
    correlation and ``r_squared`` (the coefficient of determination) is the share
    of the variance in ``y`` explained by the fit. ``r`` / ``r_squared`` are
    ``None`` when ``y`` has zero spread (no variance to explain).

    Returns a dict::

        {
            "x_category", "y_category",
            "x_unit", "y_unit",
            "count",
            "slope",          # in y_unit per x_unit
            "intercept",      # in y_unit
            "r",              # Pearson correlation, or None
            "r_squared",      # coefficient of determination, or None
            "mean_x", "mean_y",
        }

    Raises ValueError for mismatched lengths, fewer than two paired points, any
    malformed/cross-category series (delegated to ``sum_quantities``), or an
    ``x`` series with zero spread (a vertical line has no finite slope).
    """
    s = _paired_series(x_items, y_items, to_x, to_y)
    xs, ys, n = s["x"], s["y"], s["n"]
    mean_x, mean_y, sxy, sxx, syy = _co_moments(xs, ys)
    if sxx == 0:
        raise ValueError("'x' values have zero spread; the slope is undefined")
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    denom = math.sqrt(sxx * syy)
    r = (sxy / denom) if denom != 0 else None
    r_squared = (r * r) if r is not None else None
    return {
        "x_category": s["x_category"], "y_category": s["y_category"],
        "x_unit": s["x_unit"], "y_unit": s["y_unit"],
        "count": n,
        "slope": slope,
        "intercept": intercept,
        "r": r,
        "r_squared": r_squared,
        "mean_x": mean_x, "mean_y": mean_y,
    }


def gini_quantities(items, to_unit=None):
    """The Gini inequality coefficient of a list of SAME-category quantities.

    The natural inequality/concentration companion to :func:`proportions`
    (which reports each quantity's *share* of the total): where proportions
    answers "what slice is each part?", the Gini answers "how *evenly* is the
    whole shared out?" — 0 means perfect equality (every quantity identical),
    approaching 1 means one quantity holds almost everything (e.g. how unevenly
    a budget, a set of file sizes, or a stretch of leg distances is distributed).

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the comparison is apples-to-apples —
    exactly like :func:`sum_quantities` and the rest of the aggregate family.
    The coefficient is then computed from the values sorted ascending,

        G = Σ (2·i − n − 1)·x⟮i⟯ / (n · Σ x)          (i = 1..n, x⟮i⟯ ascending),

    which is algebraically the *relative mean absolute difference* halved: the
    mean over every ordered pair of the absolute gap ``|xᵢ − xⱼ|``, divided by
    twice the mean. So ``rmad == 2·gini`` and ``mean_abs_difference ==
    rmad·mean`` are reported alongside as the un-normalised views of the same
    spread. A single item (or any all-equal list) is perfectly equal, G = 0;
    an all-zero list is likewise G = 0 (nothing to share unevenly).

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "total": <float>,                  # the group total, in the target unit
            "mean": <float>,                   # the arithmetic mean
            "gini": <float>,                   # Gini coefficient in [0, 1]
            "rmad": <float>,                   # relative mean absolute difference (2·gini)
            "mean_abs_difference": <float>,    # mean |xᵢ − xⱼ| over all ordered pairs
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, a non-linear category
    (temperature is affine and fuel economy is reciprocal — neither sums, so
    neither has a Gini), or any negative restated value (the Gini coefficient is
    only defined for a non-negative distribution). Validation is delegated to
    ``sum_quantities`` so the accepted inputs stay identical to the rest of the
    aggregate family.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves both the group
    # total and the common target unit, so a bad input fails here first.
    total, unit, category = sum_quantities(items, to_unit)
    values = _restate_items(items, unit)

    if any(v < 0 for v in values):
        raise ValueError(
            "the Gini coefficient is only defined for non-negative quantities")

    n = len(values)
    mean = total / n
    # An all-zero (zero-total) distribution is perfectly equal: G = 0. Guard the
    # division before applying the sorted-values formula.
    if total == 0:
        gini = 0.0
    else:
        ordered = sorted(values)
        weighted = sum((2 * (i + 1) - n - 1) * x for i, x in enumerate(ordered))
        gini = weighted / (n * total)
    rmad = 2.0 * gini
    return {
        "category": category,
        "unit": unit,
        "count": n,
        "total": total,
        "mean": mean,
        "gini": gini,
        "rmad": rmad,
        "mean_abs_difference": rmad * mean,
    }


def entropy_quantities(items, to_unit=None):
    """The Shannon entropy and diversity/concentration indices of a list of
    SAME-category quantities, treated as a distribution.

    The information-theoretic companion to :func:`gini_quantities` and
    :func:`proportions`. Where the Gini coefficient measures inequality and
    ``proportions`` reports each quantity's *share* of the total, the entropy
    answers "how *spread out* (diverse) versus *concentrated* is the whole?" —
    maximal when every quantity is identical, falling towards zero as one
    quantity dominates (e.g. how diversified a portfolio, a set of file sizes,
    or a budget is across its parts).

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the shares are apples-to-apples — exactly
    like :func:`proportions` and the rest of the aggregate family. Each item's
    share ``pᵢ = xᵢ / Σx`` then drives:

        shannon       = −Σ pᵢ·ln pᵢ                (nats; a zero share adds 0)
        shannon_bits  = shannon / ln 2             (the same entropy in bits)
        simpson       = Σ pᵢ²                       (concentration; == the HHI)
        gini_simpson  = 1 − Σ pᵢ²                   (Simpson diversity index)
        effective_count = exp(shannon)             (Hill number / perplexity —
                                                     the equivalent count of
                                                     equal-sized parts)
        normalized_entropy = shannon / ln n        (Pielou evenness in [0, 1];
                                                     None for a single item,
                                                     where ln n == 0)

    For a single item (or any all-equal list of n) the distribution is one of
    perfect evenness: ``simpson == 1/n``, ``gini_simpson == 1 − 1/n``,
    ``effective_count == n`` and ``normalized_entropy == 1`` (or None when
    n == 1, since evenness is undefined for one category).

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "total": <float>,               # the group total, in the target unit
            "mean": <float>,                # the arithmetic mean
            "shannon": <float>,             # Shannon entropy in nats
            "shannon_bits": <float>,        # Shannon entropy in bits
            "normalized_entropy": <float>,  # Pielou evenness in [0, 1], or None
            "simpson": <float>,             # Σ pᵢ² concentration (HHI)
            "gini_simpson": <float>,        # 1 − Σ pᵢ² diversity
            "effective_count": <float>,     # exp(shannon) Hill number / perplexity
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, a non-linear category
    (temperature is affine and fuel economy is reciprocal — neither sums, so
    neither has shares), any negative restated value (a probability share is
    only defined for a non-negative distribution), or a zero total (the shares —
    and so the entropy — are undefined when there is nothing to distribute, just
    as in :func:`proportions`). Validation is delegated to ``sum_quantities`` so
    the accepted inputs stay identical to the rest of the aggregate family.
    """
    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves both the group
    # total and the common target unit, so a bad input fails here first.
    total, unit, category = sum_quantities(items, to_unit)
    values = _restate_items(items, unit)

    if any(v < 0 for v in values):
        raise ValueError(
            "entropy is only defined for non-negative quantities")
    if total == 0:
        raise ValueError("cannot compute entropy when the total is zero")

    n = len(values)
    mean = total / n

    shannon = 0.0
    simpson = 0.0
    for v in values:
        p = v / total
        if p > 0.0:
            shannon -= p * math.log(p)
        simpson += p * p

    return {
        "category": category,
        "unit": unit,
        "count": n,
        "total": total,
        "mean": mean,
        "shannon": shannon,
        "shannon_bits": shannon / math.log(2.0),
        # Pielou evenness needs ln(n); a single category has no spread to
        # normalise against, so evenness is reported as undefined (None).
        "normalized_entropy": (shannon / math.log(n)) if n > 1 else None,
        "simpson": simpson,
        "gini_simpson": 1.0 - simpson,
        "effective_count": math.exp(shannon),
    }


def _average_ranks(values):
    """Return fractional (average-tie) ascending ranks for a list of floats.

    Ties share the average of the ordinal ranks they span, so the ranks always
    sum to ``n*(n+1)/2`` regardless of ties — the same fractional-ranking rule
    used by :func:`rank_quantities`. Ranks are returned in the original input
    order (rank[i] is the rank of values[i]).
    """
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # ordinal positions i..j -> 1-based mean
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1
    return ranks


def spearman(x_items, y_items, to_x=None, to_y=None):
    """Spearman rank correlation coefficient (rho) of two paired series.

    The rank-based, monotonic companion to the Pearson :func:`correlation`:
    where Pearson measures *linear* association on the raw values, Spearman
    measures *monotonic* association — it is Pearson's r computed on the
    fractional ranks of each series rather than on the values themselves. Each
    series is independently restated on its own common unit (``to_x`` / ``to_y``,
    or each series' first unit when omitted), then converted to average-tie
    ranks (the same fractional ranking as :func:`rank_quantities`), and the
    Pearson correlation of those rank vectors is returned.

    ``rho`` lies in ``[-1, 1]``: +1 a perfectly increasing monotonic relation,
    -1 a perfectly decreasing one, 0 no monotonic relation. Because it works on
    ranks it is invariant under any monotonic re-scaling of either series (so the
    choice of ``to_x``/``to_y`` never changes it) and is robust to outliers.
    Computing rho as Pearson-on-ranks (rather than the ``1 - 6Σd²/(n(n²-1))``
    shortcut) keeps it correct in the presence of tied ranks; ``has_ties`` flags
    whether either series contained ties. When either series has zero rank spread
    (every value identical) rho is undefined and reported as ``None``.

    Returns a dict::

        {
            "x_category", "y_category",
            "x_unit", "y_unit",
            "count",
            "mean_rank_x", "mean_rank_y",   # always (n+1)/2 for both
            "has_ties",                      # True if either series had ties
            "spearman",                      # rho, or None when undefined
        }

    Raises ValueError for mismatched lengths, fewer than two paired points, or
    any malformed/cross-category series (delegated to ``sum_quantities``).
    """
    s = _paired_series(x_items, y_items, to_x, to_y)
    xs, ys, n = s["x"], s["y"], s["n"]
    rx = _average_ranks(xs)
    ry = _average_ranks(ys)
    mean_rx, mean_ry, sxy, sxx, syy = _co_moments(rx, ry)
    denom = math.sqrt(sxx * syy)
    rho = (sxy / denom) if denom != 0 else None
    has_ties = (len(set(xs)) != n) or (len(set(ys)) != n)
    return {
        "x_category": s["x_category"], "y_category": s["y_category"],
        "x_unit": s["x_unit"], "y_unit": s["y_unit"],
        "count": n,
        "mean_rank_x": mean_rx, "mean_rank_y": mean_ry,
        "has_ties": has_ties,
        "spearman": rho,
    }


def kendall(x_items, y_items, to_x=None, to_y=None):
    """Kendall's tau-b rank correlation coefficient of two paired series.

    The third member of the paired-series correlation family, alongside the
    linear Pearson :func:`correlation` and the rank-based Spearman
    :func:`spearman`. Like Spearman it measures *monotonic* association on the
    ordering of the two series rather than their raw magnitudes, so it is
    dimensionless, invariant under any monotonic rescaling of either series (the
    choice of ``to_x``/``to_y`` never changes it) and robust to outliers. Where
    Spearman is Pearson-r-on-ranks, Kendall's tau is built directly from the
    agreement of *every pair* of observations: a pair ``(i, j)`` is
    **concordant** when the two series order it the same way (``xᵢ<xⱼ`` and
    ``yᵢ<yⱼ``, or both reversed) and **discordant** when they order it oppositely;
    pairs tied on x or on y count toward neither.

    With ``C`` concordant and ``D`` discordant pairs out of the
    ``n0 = n(n-1)/2`` total, the **tau-b** coefficient (which corrects for ties)
    is

        tau_b = (C − D) / √((n0 − Tx)·(n0 − Ty)),

    where ``Tx = Σ tₖ(tₖ−1)/2`` over each group of ``tₖ`` equal x values (and
    ``Ty`` likewise for y; a pair tied in *both* counts toward both). The simpler
    **tau-a** ``(C − D)/n0`` is reported alongside and agrees with tau-b when
    there are no ties. ``tau_b`` lies in ``[-1, 1]``: +1 a perfectly increasing
    monotonic relation, -1 a perfectly decreasing one, 0 no monotonic
    association. When either series has no spread (every value identical, so
    ``n0 − Tx`` or ``n0 − Ty`` is zero) tau-b is undefined and reported as
    ``None``. ``has_ties`` flags whether either series contained ties.

    Returns a dict::

        {
            "x_category", "y_category",
            "x_unit", "y_unit",
            "count",
            "pairs",             # n0 = n(n-1)/2, the unordered pair count
            "concordant",        # C
            "discordant",        # D
            "ties_x", "ties_y",  # pairs tied on x / on y (Tx / Ty)
            "has_ties",
            "tau_a",             # (C - D) / n0
            "tau",               # tau-b, or None when undefined
        }

    Raises ValueError for mismatched lengths, fewer than two paired points, or
    any malformed/cross-category series (delegated to ``sum_quantities``).
    """
    s = _paired_series(x_items, y_items, to_x, to_y)
    xs, ys, n = s["x"], s["y"], s["n"]
    concordant = discordant = ties_x = ties_y = 0
    for i in range(n):
        xi, yi = xs[i], ys[i]
        for j in range(i + 1, n):
            dx = xi - xs[j]
            dy = yi - ys[j]
            tx = (dx == 0)
            ty = (dy == 0)
            if tx or ty:
                # A pair tied on either axis is excluded from C/D and counts
                # toward that axis' tie correction (both, when tied on both).
                if tx:
                    ties_x += 1
                if ty:
                    ties_y += 1
            elif (dx > 0) == (dy > 0):
                concordant += 1
            else:
                discordant += 1
    n0 = n * (n - 1) // 2
    tau_a = (concordant - discordant) / n0
    denom = math.sqrt((n0 - ties_x) * (n0 - ties_y))
    tau_b = ((concordant - discordant) / denom) if denom != 0 else None
    has_ties = (len(set(xs)) != n) or (len(set(ys)) != n)
    return {
        "x_category": s["x_category"], "y_category": s["y_category"],
        "x_unit": s["x_unit"], "y_unit": s["y_unit"],
        "count": n,
        "pairs": n0,
        "concordant": concordant,
        "discordant": discordant,
        "ties_x": ties_x,
        "ties_y": ties_y,
        "has_ties": has_ties,
        "tau_a": tau_a,
        "tau": tau_b,
    }


def trimmed_mean(items, proportion=0.1, to_unit=None):
    """Robust trimmed and winsorized means of SAME-category quantities.

    The outlier-resistant location companion to :func:`means` (the four classical
    means) and :func:`mad_quantities` (robust spread): both the trimmed and the
    winsorized mean damp the influence of extreme values, so a single wild
    measurement cannot drag the centre the way it drags the plain arithmetic
    ``mean`` reported by :func:`describe_quantities`. Every quantity is first
    restated in a single common ``to_unit`` (or, when omitted, the first item's
    unit) so the result is apples-to-apples — exactly like :func:`sum_quantities`
    and the rest of the aggregate family.

    ``proportion`` is the fraction trimmed from EACH tail, so a proportion ``p``
    discards a total of ``2p`` of the data. The count removed from each end is
    ``g = floor(n * p)`` (the standard floor convention), which is symmetric, so
    the two tails always lose the same number of points. With the values sorted
    ascending:

    * ``trimmed_mean`` — the arithmetic mean of the ``n - 2g`` values that remain
      after dropping the ``g`` smallest and ``g`` largest. With ``p == 0`` nothing
      is trimmed and this equals the plain arithmetic mean; as ``p`` approaches
      ``0.5`` it approaches the median.
    * ``winsorized_mean`` — instead of *dropping* the ``g`` extreme values on each
      side they are *clamped* to the nearest kept value (the ``g`` smallest become
      the smallest kept value ``lower``, the ``g`` largest become the largest kept
      value ``upper``); the mean is then taken over all ``n`` points. Winsorizing
      keeps the full sample size while still limiting the leverage of the tails.

    ``lower`` / ``upper`` are the smallest and largest values that survive the
    trim (the clamp bounds used by the winsorized mean), and ``trimmed_each_side``
    / ``kept`` are ``g`` and ``n - 2g``. ``mean`` is the untrimmed arithmetic mean,
    reported alongside so the robust centres can be read against it.

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int n>,
            "proportion": <float p>,
            "trimmed_each_side": <int g>,
            "kept": <int n - 2g>,
            "mean": <float>,
            "trimmed_mean": <float>,
            "winsorized_mean": <float>,
            "lower": <float>,
            "upper": <float>,
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, a non-linear category
    (temperature is affine and fuel economy is reciprocal — neither averages
    meaningfully on a single common unit), or a ``proportion`` that is not a
    finite number in ``[0, 0.5)``. Item validation is delegated to
    :func:`_series_values` so the accepted inputs stay identical to the rest of
    the aggregate family.
    """
    try:
        p = float(proportion)
    except (TypeError, ValueError):
        raise ValueError("'proportion' must be a number")
    if p != p or p in (float("inf"), float("-inf")):
        raise ValueError("'proportion' must be finite")
    if p < 0.0 or p >= 0.5:
        raise ValueError("'proportion' must be in [0, 0.5)")

    values, unit, category = _series_values(items, to_unit)
    n = len(values)
    ordered = sorted(values)

    # Symmetric floor trim: drop g from each tail. p < 0.5 guarantees 2g < n, so
    # at least one value always survives the trim.
    g = int(math.floor(n * p))
    kept = ordered[g:n - g] if g else ordered
    lower = kept[0]
    upper = kept[-1]

    mean = sum(ordered) / n
    trimmed = sum(kept) / len(kept)
    # Winsorize: clamp the g extreme values on each side to the kept bounds,
    # then average over all n points (the middle block is unchanged).
    winsorized = (g * lower + sum(kept) + g * upper) / n
    return {
        "category": category,
        "unit": unit,
        "count": n,
        "proportion": p,
        "trimmed_each_side": g,
        "kept": len(kept),
        "mean": mean,
        "trimmed_mean": trimmed,
        "winsorized_mean": winsorized,
        "lower": lower,
        "upper": upper,
    }


def winsorize_quantities(items, proportion=0.1, to_unit=None):
    """Winsorize a series of SAME-category quantities — return the clamped data.

    The per-item transformation companion to :func:`trimmed_mean` (which reports
    only the scalar winsorized *mean*): where ``trimmed_mean`` collapses the
    dataset to a single robust centre, this returns the full winsorized SERIES,
    one entry per input in the original order, exactly like :func:`zscores`,
    :func:`normalize_quantities` and :func:`outliers` do for their own
    transforms. Winsorizing replaces the most extreme values — rather than
    dropping them, as a trim would — with the nearest value that survives the
    trim, so a single wild measurement is pulled in to the boundary instead of
    distorting the spread. Every quantity is first restated in a single common
    ``to_unit`` (or, when omitted, the first item's unit) so the clamp is
    apples-to-apples, identical to :func:`sum_quantities` and the rest of the
    aggregate family.

    ``proportion`` is the fraction winsorized at EACH tail, so a proportion ``p``
    clamps a total of ``2p`` of the data. The count clamped on each side is
    ``g = floor(n * p)`` (the same symmetric floor convention as
    :func:`trimmed_mean`). With the values sorted ascending, ``lower`` is the
    ``g``-th smallest survivor (``ordered[g]``) and ``upper`` is the ``g``-th
    largest survivor (``ordered[n-1-g]``); every value below ``lower`` is raised
    to ``lower`` and every value above ``upper`` is lowered to ``upper``, while
    the middle block is left untouched. With ``p == 0`` nothing is clamped and
    the winsorized series equals the restated input.

    For each item ``winsorized`` is the clamped value and ``clamped`` is whether
    that value actually changed (strictly outside ``[lower, upper]``; a value
    sitting exactly on a bound is unchanged and so is not flagged).
    ``winsorized_mean`` and ``winsorized_stdev`` are the population mean and
    population standard deviation of the clamped series, reported against the
    untouched ``mean`` so the robust shift can be read directly; the
    ``winsorized_mean`` here is by construction identical to the one
    :func:`trimmed_mean` returns for the same ``proportion``.

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int n>,
            "proportion": <float p>,
            "clamped_each_side": <int g>,
            "lower": <float>,
            "upper": <float>,
            "mean": <float>,                 # untouched arithmetic mean
            "winsorized_mean": <float>,
            "winsorized_stdev": <float>,     # population stdev of clamped series
            "items": [
                {"index": <int>, "value": <float>,
                 "winsorized": <float>, "clamped": <bool>}, ...
            ],
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, a non-linear category
    (temperature is affine and fuel economy is reciprocal — neither averages
    meaningfully on a single common unit), or a ``proportion`` that is not a
    finite number in ``[0, 0.5)``. Item validation is delegated to
    :func:`_series_values` so the accepted inputs stay identical to the rest of
    the aggregate family.
    """
    try:
        p = float(proportion)
    except (TypeError, ValueError):
        raise ValueError("'proportion' must be a number")
    if p != p or p in (float("inf"), float("-inf")):
        raise ValueError("'proportion' must be finite")
    if p < 0.0 or p >= 0.5:
        raise ValueError("'proportion' must be in [0, 0.5)")

    values, unit, category = _series_values(items, to_unit)
    n = len(values)
    ordered = sorted(values)

    # Symmetric floor winsorize: clamp g from each tail. p < 0.5 guarantees
    # 2g < n, so the clamp bounds always straddle at least one untouched value.
    g = int(math.floor(n * p))
    lower = ordered[g]
    upper = ordered[n - 1 - g]

    mean = sum(values) / n
    out = []
    clamped_total = 0.0
    for index, value in enumerate(values):
        if value < lower:
            w = lower
            clamped = True
        elif value > upper:
            w = upper
            clamped = True
        else:
            w = value
            clamped = False
        clamped_total += w
        out.append({"index": index, "value": value,
                    "winsorized": w, "clamped": clamped})

    winsorized_mean = clamped_total / n
    var = sum((row["winsorized"] - winsorized_mean) ** 2 for row in out) / n
    winsorized_stdev = math.sqrt(var)
    return {
        "category": category,
        "unit": unit,
        "count": n,
        "proportion": p,
        "clamped_each_side": g,
        "lower": lower,
        "upper": upper,
        "mean": mean,
        "winsorized_mean": winsorized_mean,
        "winsorized_stdev": winsorized_stdev,
        "items": out,
    }


def _median_sorted(ordered):
    """Median of an already-ascending list (length >= 1)."""
    m = len(ordered)
    mid = m // 2
    if m % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def theil_sen(x_items, y_items, to_x=None, to_y=None):
    """Theil--Sen robust linear fit ``y = slope·x + intercept`` of two paired
    series of quantities.

    The outlier-resistant companion to :func:`linear_regression` (ordinary least
    squares), mirroring how :func:`spearman` / :func:`kendall` are the robust
    companions to :func:`correlation` and :func:`trimmed_mean` is to
    :func:`means`. Where OLS minimises squared residuals — so a single wild point
    can swing the line — Theil--Sen takes the **median of the pairwise slopes**
    ``(y_j - y_i)/(x_j - x_i)`` over every pair of points with distinct ``x``,
    then sets ``intercept = median(y_i - slope·x_i)`` over all points. The median
    has a ~29% breakdown point, so up to roughly a quarter of the data can be
    arbitrarily corrupted without dragging the fit.

    Each series is restated on its own common unit (``to_x`` / ``to_y``, or each
    series' first unit when omitted), exactly like the rest of the paired-series
    family, so the slope carries ``y_unit/x_unit`` and the intercept ``y_unit``.

    Pairs that share an ``x`` value (a vertical connecting line, an infinite
    slope) are skipped and counted in ``tied_pairs``; ``used_pairs`` is the
    number of finite-slope pairs the median is taken over and ``pairs`` is the
    total ``n·(n-1)/2`` candidate pairs.

    Returns a dict::

        {
            "x_category", "y_category",
            "x_unit", "y_unit",
            "count",
            "pairs",        # total candidate pairs n(n-1)/2
            "used_pairs",   # pairs with distinct x (finite slope)
            "tied_pairs",   # pairs skipped for sharing an x value
            "slope",        # median pairwise slope, in y_unit per x_unit
            "intercept",    # median(y - slope·x), in y_unit
            "median_x", "median_y",
            "mean_x", "mean_y",
        }

    Raises ValueError for mismatched lengths, fewer than two paired points, any
    malformed/cross-category series (delegated to ``sum_quantities``), or an
    ``x`` series in which every pair shares its ``x`` value (all x equal — a
    vertical line has no finite slope), matching the OLS guard in
    :func:`linear_regression`.
    """
    s = _paired_series(x_items, y_items, to_x, to_y)
    xs, ys, n = s["x"], s["y"], s["n"]

    slopes = []
    tied = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx = xs[j] - xs[i]
            if dx == 0:
                tied += 1
                continue
            slopes.append((ys[j] - ys[i]) / dx)
    if not slopes:
        raise ValueError("'x' values have zero spread; the slope is undefined")

    slope = _median_sorted(sorted(slopes))
    intercept = _median_sorted(sorted(y - slope * x for x, y in zip(xs, ys)))
    total_pairs = n * (n - 1) // 2
    return {
        "x_category": s["x_category"], "y_category": s["y_category"],
        "x_unit": s["x_unit"], "y_unit": s["y_unit"],
        "count": n,
        "pairs": total_pairs,
        "used_pairs": len(slopes),
        "tied_pairs": tied,
        "slope": slope,
        "intercept": intercept,
        "median_x": _median_sorted(sorted(xs)),
        "median_y": _median_sorted(sorted(ys)),
        "mean_x": sum(xs) / n,
        "mean_y": sum(ys) / n,
    }


def autocorrelation(items, maxlag=None, to_unit=None):
    """Serial (auto)correlation of ONE series of same-category quantities at a
    range of lags.

    Where the bivariate :func:`correlation` family relates two *different* series
    ``x`` and ``y``, the autocorrelation correlates a single series *with a
    delayed copy of itself* — the standard time-series diagnostic for asking "does
    each reading resemble the one ``k`` steps earlier?" (trend, seasonality,
    momentum). It is the serial-dependence companion to the smoothing family
    (:func:`moving_average`, :func:`ema`) and the step-to-step :func:`differences`.

    Every quantity is first restated in a single common ``to_unit`` (or, when
    omitted, the first item's unit) so the series is apples-to-apples — exactly
    like :func:`sum_quantities` and the rest of the aggregate family. Using the
    population mean ``m`` (matching :func:`zscores` / :func:`describe_quantities`),
    the autocorrelation at lag ``k`` is the standard biased estimator

        r_k = sum_{t=k}^{n-1} (x_t - m)(x_{t-k} - m) / sum_{t=0}^{n-1} (x_t - m)^2

    so ``r_0`` is always ``1`` and every ``r_k`` lies in ``[-1, 1]``. Because both
    sums scale with the unit squared, the coefficient is **dimensionless** — it is
    invariant under the choice of ``to_unit`` (only the reported ``mean``/``stdev``
    carry the unit).

    ``maxlag`` is the largest lag to report (lags ``0..maxlag`` are returned). It
    is optional: when omitted it defaults to ``n - 1`` (every computable lag). It
    must be an integer in ``[0, n - 1]``. ``items`` is a list of
    {"value": <number>, "unit": <token>} dicts (a ``(value, unit)`` tuple is also
    accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "maxlag": <int>,
            "mean": <float>,             # population mean, in the target unit
            "variance": <float>,         # population variance, in unit^2
            "stdev": <float>,            # population stdev, in the target unit
            "items": [{"lag": <int>, "autocorrelation": <float>}, ...],
        }

    Raises ValueError for a non-integer / out-of-range ``maxlag``, fewer than two
    items, an empty/non-list input, a malformed item, an unknown or cross-category
    unit, a non-finite value, a non-linear category (temperature is affine and
    fuel economy is reciprocal), or a **zero variance** (every quantity is
    identical, so the lag-0 normaliser vanishes and the correlation is undefined —
    matching the guard in :func:`zscores`). Item validation is delegated to
    :func:`_series_values` so the accepted inputs stay identical to the rest of the
    aggregate family.
    """
    # _series_values does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves the common
    # target unit, so a bad input fails here before any lag runs.
    converted, unit, category = _series_values(items, to_unit)
    n = len(converted)
    if n < 2:
        raise ValueError("autocorrelation needs at least two items")

    if maxlag is None:
        maxlag = n - 1
    # bool is an int subclass; reject it so True/False can't masquerade as a lag.
    if isinstance(maxlag, bool) or not isinstance(maxlag, int):
        raise ValueError("'maxlag' must be an integer")
    if maxlag < 0:
        raise ValueError("'maxlag' must be at least 0")
    if maxlag > n - 1:
        raise ValueError(
            "'maxlag' (%d) cannot exceed the number of items minus one (%d)"
            % (maxlag, n - 1)
        )

    mean = sum(converted) / n
    deviations = [x - mean for x in converted]
    denom = sum(d * d for d in deviations)
    if denom == 0:
        raise ValueError(
            "cannot compute autocorrelation when every quantity is identical "
            "(variance is zero)"
        )

    out = []
    for lag in range(maxlag + 1):
        numer = sum(
            deviations[t] * deviations[t - lag] for t in range(lag, n)
        )
        out.append({"lag": lag, "autocorrelation": numer / denom})

    variance = denom / n
    return {
        "category": category,
        "unit": unit,
        "count": n,
        "maxlag": maxlag,
        "mean": mean,
        "variance": variance,
        "stdev": math.sqrt(variance),
        "items": out,
    }


def robust_zscores(items, threshold=None, to_unit=None):
    """Modified (robust) z-score of each quantity — the Iglewicz & Hoaglin score.

    The outlier-robust companion to :func:`zscores`. Where the classic z-score
    standardises against the **mean** and **population standard deviation** — both
    of which are themselves pulled by the very outliers one is hunting for — the
    modified z-score standardises against the **median** and the **median absolute
    deviation (MAD)**, neither of which a few extreme points can budge. Every
    quantity is first restated in a single common ``to_unit`` (or, when omitted,
    the first item's unit) so the scores are apples-to-apples — exactly like
    :func:`sum_quantities` and the rest of the aggregate family.

    With the median ``M`` and ``MAD = median(|x - M|)`` (the same robust spread
    :func:`mad_quantities` reports), each item's ``robust_zscore`` is

        Mi = 0.6745 * (x - M) / MAD

    The 0.6745 factor (``Phi^-1(3/4)``) makes ``0.6745 / MAD`` a consistent
    estimator of ``1 / sigma`` for normal data, so the modified z-score is on the
    same scale as the ordinary z-score and, being a ratio of like units, is
    **dimensionless** (invariant under ``to_unit`` — only the reported
    ``median``/``mad`` carry the unit). An item is flagged ``is_outlier`` when its
    magnitude exceeds ``threshold`` (default 3.5, the value Iglewicz & Hoaglin
    recommend).

    When the MAD is zero (more than half the values share the median, yet some
    differ) the score falls back to the **mean** absolute deviation about the
    median, ``meanAD = mean(|x - M|)``, with its own consistency factor
    ``Mi = (x - M) / (1.253314 * meanAD)``; the ``method`` field reports which
    scale was used (``"mad"`` or ``"meanad"``).

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "median": <float>,                # in the target unit
            "mad": <float>,                    # median(|x - median|), target unit
            "mean_abs_deviation": <float>,     # mean(|x - median|), target unit
            "method": "mad" | "meanad",        # which scale standardised the score
            "threshold": <float>,
            "outlier_count": <int>,
            "items": [{"index": <int>, "value": <float>,
                       "robust_zscore": <float>, "is_outlier": <bool>}, ...],
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown or
    cross-category unit, a non-finite value, a non-linear category (temperature is
    affine and fuel economy is reciprocal), a non-positive / non-finite
    ``threshold``, or a series in which **every quantity is identical** (both the
    MAD and the mean absolute deviation vanish, so there is no spread to divide by
    — matching the guard in :func:`zscores`). Item validation is delegated to
    ``sum_quantities`` so the accepted inputs stay identical to the rest of the
    aggregate family.
    """
    if threshold is None:
        threshold = ROBUST_Z_DEFAULT_THRESHOLD
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("'threshold' must be a number")
    threshold = float(threshold)
    if threshold != threshold or threshold in (float("inf"), float("-inf")):
        raise ValueError("'threshold' must be finite")
    if threshold <= 0:
        raise ValueError("'threshold' must be positive")

    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves both the running
    # total and the common target unit, so a bad input fails here before any
    # score runs.
    _total, unit, category = sum_quantities(items, to_unit)

    converted = _restate_items(items, unit)
    count = len(converted)
    median = _percentile_of_sorted(sorted(converted), 50)

    abs_devs = [abs(x - median) for x in converted]
    mad = _percentile_of_sorted(sorted(abs_devs), 50)
    mean_abs_deviation = sum(abs_devs) / count

    if mad != 0:
        method = "mad"
        scale = mad / ROBUST_Z_CONSTANT
    elif mean_abs_deviation != 0:
        # All-but-some values equal the median: MAD collapses to 0 but the mean
        # absolute deviation still has spread, so fall back to it.
        method = "meanad"
        scale = ROBUST_Z_MEANAD_CONSTANT * mean_abs_deviation
    else:
        raise ValueError(
            "cannot compute robust z-scores when every quantity is identical "
            "(both the MAD and the mean absolute deviation are zero)"
        )

    out = []
    outlier_count = 0
    for index, value in enumerate(converted):
        score = (value - median) / scale
        is_outlier = abs(score) > threshold
        if is_outlier:
            outlier_count += 1
        out.append({
            "index": index,
            "value": value,
            "robust_zscore": score,
            "is_outlier": is_outlier,
        })
    return {
        "category": category,
        "unit": unit,
        "count": count,
        "median": median,
        "mad": mad,
        "mean_abs_deviation": mean_abs_deviation,
        "method": method,
        "threshold": threshold,
        "outlier_count": outlier_count,
        "items": out,
    }


# Default confidence level for :func:`confidence_interval` — the conventional
# 95% interval.
CI_DEFAULT_CONFIDENCE = 0.95


def _inv_normal_cdf(p):
    """Inverse of the standard-normal CDF (the *probit* function).

    Returns the ``z`` such that ``Phi(z) == p`` for ``0 < p < 1``, using Peter
    Acklam's rational approximation followed by one Halley refinement step
    against :func:`math.erfc`. The refinement pins the result to full double
    precision (relative error ~1e-15), so ``_inv_normal_cdf(0.975)`` returns the
    familiar ``1.959963985...`` and ``_inv_normal_cdf(0.995)`` returns
    ``2.575829303...``. Standard-library only — no statistics/scipy dependency.

    Raises ValueError when ``p`` is not strictly inside ``(0, 1)``.
    """
    if not (0.0 < p < 1.0):
        raise ValueError("probability must be strictly between 0 and 1")

    # Coefficients for Acklam's rational approximation.
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)

    # One Halley step: e == Phi(x) - p, refined against the exact erfc.
    e = 0.5 * math.erfc(-x / math.sqrt(2.0)) - p
    u = e * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    x = x - u / (1.0 + x * u / 2.0)
    return x


def confidence_interval(items, confidence=None, to_unit=None):
    """Confidence interval for the population MEAN of a list of quantities.

    The inferential companion to :func:`describe_quantities`: where ``describe``
    reports the sample mean and spread as fixed descriptions of the data at hand,
    this asks *how precisely that sample pins down the true population mean* and
    answers with a two-sided interval ``mean +/- margin``. Every quantity is
    first restated in a single common ``to_unit`` (or, when omitted, the first
    item's unit) so the interval is apples-to-apples — exactly like
    :func:`sum_quantities` and the rest of the aggregate family.

    The interval is the large-sample **normal (z) approximation**: with the
    sample mean ``xbar``, the sample standard deviation ``s`` (the unbiased
    ``/(n-1)`` estimator) and ``n`` observations, the **standard error of the
    mean** is ``SE = s / sqrt(n)``, the two-sided critical value is the normal
    quantile ``z = Phi^-1((1 + confidence) / 2)`` (see :func:`_inv_normal_cdf`),
    the **margin of error** is ``z * SE`` and the interval is
    ``[xbar - margin, xbar + margin]``. ``confidence`` defaults to 0.95 and must
    lie strictly inside ``(0, 1)``; e.g. 0.95 gives ``z ~ 1.96`` and 0.99 gives
    ``z ~ 2.576``.

    ``items`` is a list of {"value": <number>, "unit": <token>} dicts (a
    ``(value, unit)`` tuple is also accepted), identical to ``sum_quantities``.

    Returns a dict::

        {
            "category": <name>,
            "unit": <normalised target unit>,
            "count": <int>,
            "confidence": <float>,            # the requested level, e.g. 0.95
            "mean": <float>,                  # sample mean, in the target unit
            "sample_stdev": <float>,          # unbiased (/(n-1)) stdev
            "standard_error": <float>,        # s / sqrt(n)
            "critical_value": <float>,        # the two-sided z quantile
            "margin_of_error": <float>,       # z * standard_error
            "lower": <float>,                 # mean - margin_of_error
            "upper": <float>,                 # mean + margin_of_error
        }

    Raises ValueError for an empty/non-list input, a malformed item, an unknown
    or cross-category unit, a non-finite value, a non-linear category
    (temperature is affine and fuel economy is reciprocal — neither has a
    meaningful mean to bound), a ``confidence`` that is not a number strictly in
    ``(0, 1)``, or a series of fewer than two values (the sample standard
    deviation — and hence the standard error — is undefined for a single
    observation, matching the ``sample_stdev`` guard in
    :func:`describe_quantities`). Item validation is delegated to
    ``sum_quantities`` so the accepted inputs stay identical to the rest of the
    aggregate family.
    """
    if confidence is None:
        confidence = CI_DEFAULT_CONFIDENCE
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("'confidence' must be a number")
    confidence = float(confidence)
    if confidence != confidence or confidence in (float("inf"), float("-inf")):
        raise ValueError("'confidence' must be finite")
    if not (0.0 < confidence < 1.0):
        raise ValueError("'confidence' must be strictly between 0 and 1")

    # sum_quantities does the full validation (list shape, item shape, finite
    # values, single linear category, valid target) and resolves both the running
    # total and the common target unit, so a bad input fails here before any
    # statistics run.
    total, unit, category = sum_quantities(items, to_unit)
    converted = _restate_items(items, unit)
    count = len(converted)
    if count < 2:
        raise ValueError(
            "confidence interval requires at least two values "
            "(the sample standard error is undefined for one observation)"
        )

    mean = total / count
    sample_variance = sum((x - mean) ** 2 for x in converted) / (count - 1)
    sample_stdev = math.sqrt(sample_variance)
    standard_error = sample_stdev / math.sqrt(count)

    critical_value = _inv_normal_cdf((1.0 + confidence) / 2.0)
    margin = critical_value * standard_error
    return {
        "category": category,
        "unit": unit,
        "count": count,
        "confidence": confidence,
        "mean": mean,
        "sample_stdev": sample_stdev,
        "standard_error": standard_error,
        "critical_value": critical_value,
        "margin_of_error": margin,
        "lower": mean - margin,
        "upper": mean + margin,
    }
