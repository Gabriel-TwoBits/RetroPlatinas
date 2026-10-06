"""Leaderboard scores formatted as rcheevos formats them, checked against values worked out from
`format.c` by hand and against the vendored C itself."""

import subprocess
from pathlib import Path

import pytest
from django.template import Context, Template

from apps.leaderboards.formatting import format_score
from apps.leaderboards.models import LEADERBOARD_FORMAT_ALIASES, Leaderboard

Format = Leaderboard.Format
FORMAT_SCORE = Path(__file__).resolve().parents[2] / "scripts" / "format-score.sh"

INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1
UINT32_MAX = 2**32 - 1

# (format, score, what format.c prints), each worked out from its rules.
CASES = [
    # FRAMES (and its TIME alias): frames * 10 / 6 centiseconds, i.e. 60 fps.
    (Format.FRAMES, 0, "0:00.00"),
    (Format.FRAMES, 60, "0:01.00"),
    (Format.FRAMES, 5000, "1:23.33"),
    (Format.FRAMES, 83456, "23:10.93"),
    (Format.FRAMES, 216000, "1h00:00.00"),
    # uint32 wrap: 429,496,730 * 10 overflows to 4, and 4 / 6 is 0.
    (Format.FRAMES, 429496730, "0:00.00"),
    # -1 reads as 4,294,967,295 frames, whose * 10 wraps to 4,294,967,286.
    (Format.FRAMES, -1, "1,988h24:38.81"),
    ("TIME", 5000, "1:23.33"),
    # MILLISECS: centiseconds, despite the name.
    (Format.MILLISECS, 8345, "1:23.45"),
    (Format.MILLISECS, 7, "0:00.07"),
    (Format.MILLISECS, 360000, "1h00:00.00"),
    (Format.SECS, 59, "0:59"),
    (Format.SECS, 83, "1:23"),
    (Format.SECS, 3600, "1h00:00"),
    (Format.SECS, 3723, "1h02:03"),
    (Format.SECS, 3600000, "1,000h00:00"),
    (Format.SECS, -1, "1,193,046h28:15"),
    ("TIMESECS", 83, "1:23"),
    (Format.MINUTES, 59, "0h59"),
    (Format.MINUTES, 125, "2h05"),
    (Format.MINUTES, 60000, "1,000h00"),
    (Format.SECS_AS_MINS, 3725, "1h02"),
    (Format.SECS_AS_MINS, 59, "0h00"),
    # SCORE: six digits, no commas.
    (Format.SCORE, 0, "000000"),
    (Format.SCORE, 123, "000123"),
    (Format.SCORE, 1234567, "1234567"),
    (Format.SCORE, -5, "-00005"),
    ("POINTS", 123, "000123"),
    ("OTHER", 123, "000123"),
    (Format.VALUE, 0, "0"),
    (Format.VALUE, 999, "999"),
    (Format.VALUE, 1000, "1,000"),
    (Format.VALUE, 1234567, "1,234,567"),
    (Format.VALUE, -1234567, "-1,234,567"),
    (Format.VALUE, INT32_MIN, "-2,147,483,648"),
    (Format.UNSIGNED, 1234, "1,234"),
    (Format.UNSIGNED, -1, "4,294,967,295"),
    (Format.TENS, 0, "0"),
    (Format.TENS, 5, "50"),
    (Format.TENS, 123, "1,230"),
    (Format.TENS, -5, "-50"),
    (Format.HUNDREDS, 12345, "1,234,500"),
    (Format.THOUSANDS, 1, "1,000"),
    (Format.THOUSANDS, 0, "0"),
    (Format.FIXED1, 15, "1.5"),
    (Format.FIXED1, 12345, "1,234.5"),
    (Format.FIXED1, -15, "-1.5"),
    # The sign lives only in the integer part, which is 0 here.
    (Format.FIXED1, -5, "0.5"),
    (Format.FIXED2, 5, "0.05"),
    (Format.FIXED2, 123456, "1,234.56"),
    (Format.FIXED2, -105, "-1.05"),
    (Format.FIXED3, 1234567, "1,234.567"),
    (Format.FIXED3, -1, "0.001"),
    # -INT32_MIN overflows back to itself, and its remainder prints as unsigned.
    (Format.FIXED1, INT32_MIN, "-214,748,364.4294967288"),
    (Format.FLOAT1, 0, "0.0"),
    (Format.FLOAT1, 1234567, "1,234,567.0"),
    (Format.FLOAT2, -5, "-5.00"),
    (Format.FLOAT3, 12, "12.000"),
    (Format.FLOAT4, 1, "1.0000"),
    (Format.FLOAT5, 1000, "1,000.00000"),
    (Format.FLOAT6, 7, "7.000000"),
    # Past 2^24 a float32 rounds to an even neighbour.
    (Format.FLOAT1, 16777217, "16,777,216.0"),
    (Format.FLOAT1, INT32_MAX, "2,147,483,648.0"),
    # Not a format rcheevos knows: VALUE.
    ("BOGUS", 1234, "1,234"),
    ("", 1234, "1,234"),
    # A score outside int32 reaches rcheevos wrapped.
    (Format.VALUE, 2**31, "-2,147,483,648"),
    (Format.UNSIGNED, UINT32_MAX + 1, "0"),
]

ORACLE_SCORES = [
    0,
    1,
    -1,
    5,
    -5,
    59,
    60,
    99,
    100,
    999,
    1000,
    3599,
    3600,
    5000,
    83456,
    216000,
    999999,
    1234567,
    -1234567,
    16777217,
    429496729,
    429496730,
    INT32_MAX,
    INT32_MIN,
]
ORACLE_FORMATS = [*Format.values, *LEADERBOARD_FORMAT_ALIASES, "BOGUS"]


@pytest.mark.parametrize(("format_name", "score", "expected"), CASES)
def test_format_score_matches_the_rcheevos_rules(format_name, score, expected):
    assert format_score(score, format_name) == expected


@pytest.mark.parametrize("format_name", ORACLE_FORMATS)
def test_format_score_matches_the_vendored_rcheevos(format_name):
    result = subprocess.run(
        ["bash", str(FORMAT_SCORE), format_name, *map(str, ORACLE_SCORES)],
        capture_output=True,
        text=True,
        check=True,
    )
    expected = result.stdout.splitlines()
    assert [format_score(score, format_name) for score in ORACLE_SCORES] == expected


def test_template_filter_formats_by_the_leaderboards_format():
    template = Template("{% load leaderboard_scores %}{{ score|leaderboard_score:format }}")
    rendered = template.render(Context({"score": 5000, "format": Format.FRAMES}))
    assert rendered == "1:23.33"
