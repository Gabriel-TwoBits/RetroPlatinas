"""Leaderboard scores rendered exactly as rcheevos renders them in the emulator.

A port of `rc_format_value` (`vendor/rcheevos/src/rcheevos/format.c`): the score is a signed
32-bit integer, converted to unsigned or to a 32-bit float per format as `rc_typed_value_convert`
does, with the same wrap-around, truncating division and comma grouping as the C code.
"""

import re
import struct

from apps.leaderboards.models import Leaderboard

INT32_SIGN_BIT = 1 << 31
UINT32_MODULUS = 1 << 32

SECONDS_PER_MINUTE = 60
MINUTES_PER_HOUR = 60
CENTISECONDS_PER_SECOND = 100
# FRAMES is 60 fps: rcheevos multiplies frames by 10 / 6 (100 cs / 60 frames) in uint32, which
# wraps for scores over 429,496,729 frames.
FRAMES_TO_CENTISECONDS_MULTIPLIER = 10
FRAMES_TO_CENTISECONDS_DIVISOR = 6

DECIMAL_BASE = 10
# SCORE pads to six digits ("%06d").
SCORE_DIGITS = 6
DIGITS_PER_GROUP = 3

Format = Leaderboard.Format
# Digits after the decimal point.
FLOAT_DECIMALS = {
    Format.FLOAT1: 1,
    Format.FLOAT2: 2,
    Format.FLOAT3: 3,
    Format.FLOAT4: 4,
    Format.FLOAT5: 5,
    Format.FLOAT6: 6,
}
FIXED_DECIMALS = {Format.FIXED1: 1, Format.FIXED2: 2, Format.FIXED3: 3}
# Zeros written after the value.
APPENDED_ZEROS = {Format.TENS: 1, Format.HUNDREDS: 2, Format.THOUSANDS: 3}

LEADING_NUMBER = re.compile(r"(-?)(\d*)(.*)", re.DOTALL)


def _int32(value):
    """`value` as C's `int32_t` holds it: two's complement, wrapped."""
    return (value + INT32_SIGN_BIT) % UINT32_MODULUS - INT32_SIGN_BIT


def _uint32(value):
    """`value` as C's `uint32_t` holds it, wrapped."""
    return value % UINT32_MODULUS


def _float32(value):
    """`(float)value`: the nearest 32-bit float."""
    return struct.unpack("f", struct.pack("f", value))[0]


def _c_div(dividend, divisor):
    """C integer division, which truncates toward zero."""
    quotient = abs(dividend) // abs(divisor)
    if (dividend < 0) != (divisor < 0):
        return -quotient
    else:
        return quotient


def _c_mod(dividend, divisor):
    """C's `%`, whose result takes the sign of the dividend."""
    return dividend - divisor * _c_div(dividend, divisor)


def _insert_commas(text):
    """`rc_format_insert_commas`: groups the leading number's digits in threes with commas."""
    sign, digits, rest = LEADING_NUMBER.match(text).groups()
    head = len(digits) % DIGITS_PER_GROUP or DIGITS_PER_GROUP
    groups = [digits[:head]] + [
        digits[start : start + DIGITS_PER_GROUP]
        for start in range(head, len(digits), DIGITS_PER_GROUP)
    ]
    return sign + ",".join(groups) + rest


def _minutes(minutes):
    hours, minutes = divmod(minutes, MINUTES_PER_HOUR)
    return f"{hours}h{minutes:02d}"


def _seconds(seconds):
    minutes, seconds = divmod(seconds, SECONDS_PER_MINUTE)
    if minutes < MINUTES_PER_HOUR:
        return f"{minutes}:{seconds:02d}"
    else:
        hours, minutes = divmod(minutes, MINUTES_PER_HOUR)
        return f"{hours}h{minutes:02d}:{seconds:02d}"


def _centiseconds(centiseconds):
    seconds, centiseconds = divmod(centiseconds, CENTISECONDS_PER_SECOND)
    return f"{_seconds(seconds)}.{centiseconds:02d}"


def _fixed(decimals):
    """`rc_format_value_fixed`: a negative value keeps its sign only through the integer part, so
    -5 in FIXED1 reads "0.5" in the emulator too."""
    factor = DECIMAL_BASE**decimals

    def formatter(value):
        if value >= 0:
            remainder = value % factor
        else:
            remainder = _uint32(_c_mod(_int32(-value), factor))
        return _insert_commas(f"{_c_div(value, factor)}.{remainder:0{decimals}d}")

    return formatter


def _padded(zeros):
    """`rc_format_value_padded`: the value followed by `zeros` zeros, except a plain 0."""

    def formatter(value):
        if value == 0:
            return "0"
        else:
            return _insert_commas(f"{value}{'0' * zeros}")

    return formatter


def _float(decimals):
    return lambda value: _insert_commas(f"{_float32(value):.{decimals}f}")


def _frames(value):
    centiseconds = _uint32(_uint32(value) * FRAMES_TO_CENTISECONDS_MULTIPLIER)
    return _insert_commas(_centiseconds(centiseconds // FRAMES_TO_CENTISECONDS_DIVISOR))


def _centisecs(value):
    return _insert_commas(_centiseconds(_uint32(value)))


def _secs(value):
    return _insert_commas(_seconds(_uint32(value)))


def _secs_as_mins(value):
    return _insert_commas(_minutes(_uint32(value) // SECONDS_PER_MINUTE))


def _whole_minutes(value):
    return _insert_commas(_minutes(_uint32(value)))


def _score(value):
    """The one format rcheevos leaves without commas."""
    return f"{value:0{SCORE_DIGITS}d}"


def _unsigned(value):
    return _insert_commas(str(_uint32(value)))


def _value(value):
    return _insert_commas(str(value))


FORMATTERS = {
    Format.FRAMES: _frames,
    Format.MILLISECS: _centisecs,
    Format.SECS: _secs,
    Format.SECS_AS_MINS: _secs_as_mins,
    Format.MINUTES: _whole_minutes,
    Format.SCORE: _score,
    Format.UNSIGNED: _unsigned,
    Format.VALUE: _value,
    **{name: _float(decimals) for name, decimals in FLOAT_DECIMALS.items()},
    **{name: _fixed(decimals) for name, decimals in FIXED_DECIMALS.items()},
    **{name: _padded(zeros) for name, zeros in APPENDED_ZEROS.items()},
}


def format_score(score, format_name):
    """`score` as the emulator displays it for a leaderboard of `format_name`.

    A format name rcheevos does not know falls back to VALUE, as `rc_parse_format` does.
    """
    formatter = FORMATTERS.get(Leaderboard.canonical_format(format_name), _value)
    return formatter(_int32(score))
