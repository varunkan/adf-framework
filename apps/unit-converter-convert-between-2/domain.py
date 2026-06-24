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


def convert_units(value, from_unit, to_unit):
    """Convert ``value`` from ``from_unit`` to ``to_unit``.

    Returns (result, category). Raises ValueError for unknown units,
    cross-category mismatches, or non-finite values.
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise ValueError("'value' must be a number")
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        raise ValueError("'value' must be finite")

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
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise ValueError("'value' must be a number")
    if numeric != numeric or numeric in (float("inf"), float("-inf")):
        raise ValueError("'value' must be finite")

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

    if from_cat == "temperature":
        return numeric * _TEMP_DELTA_SCALE[_TEMP_UNITS[f]] / _TEMP_DELTA_SCALE[_TEMP_UNITS[t]], from_cat
    if from_cat == "fuel":
        raise ValueError("interval conversion is not defined for the fuel category")
    table = _LINEAR[from_cat]
    return numeric * table[f] / table[t], from_cat
