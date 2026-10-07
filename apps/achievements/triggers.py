"""Checks an achievement trigger with the rcheevos parser the emulators run, through the helper
`scripts/check-mem-addr.sh` compiles from `vendor/rcheevos`."""

import logging
import subprocess
from pathlib import Path

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

MEM_ADDR_CHECKER = Path(__file__).resolve().parents[2] / "scripts" / "check-mem-addr.sh"
# Also covers compiling the helper on its first use, which takes about a second.
CHECK_TIMEOUT_SECONDS = 10
EXIT_VALID = 0
EXIT_INVALID = 1
INVALID_VERDICT = "INVALID"
# The checker picks its parser from the text: a leaderboard starts with this prefix, and a rich
# presence script spans lines or carries this section.
LEADERBOARD_PREFIX = "STA:"
RICH_PRESENCE_MARKER = "Display:"
LINE_BREAKS = ("\n", "\r")
# 64 KiB. The condition travels as one argv element, which Linux caps at 128 KiB (MAX_ARG_STRLEN);
# a real trigger is a few KiB at most.
MAX_TRIGGER_BYTES = 65_536


def _not_a_trigger(mem_addr):
    return (
        mem_addr.startswith(LEADERBOARD_PREFIX)
        or RICH_PRESENCE_MARKER in mem_addr
        or any(line_break in mem_addr for line_break in LINE_BREAKS)
    )


def _unavailable(detail):
    logger.error("mem_addr checker unavailable: %s", detail)
    return ValidationError(
        _("The condition could not be checked right now; try again later."),
        code="checker_unavailable",
    )


def validate_trigger(mem_addr):
    """Raises `ValidationError` unless `mem_addr` parses as an achievement trigger; the message
    carries rcheevos' own reason."""
    if _not_a_trigger(mem_addr):
        raise ValidationError(
            _("An achievement condition is a single line of trigger conditions."),
            code="not_a_trigger",
        )
    if len(mem_addr.encode()) > MAX_TRIGGER_BYTES:
        raise ValidationError(
            _("The condition is too long: at most %(limit)s bytes."),
            code="trigger_too_long",
            params={"limit": MAX_TRIGGER_BYTES},
        )
    try:
        result = subprocess.run(
            ["bash", str(MEM_ADDR_CHECKER), mem_addr],
            capture_output=True,
            text=True,
            timeout=CHECK_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise _unavailable(f"timed out after {CHECK_TIMEOUT_SECONDS} s") from error
    except OSError as error:
        raise _unavailable(str(error)) from error

    verdict, _separator, reason = result.stdout.partition("\n")[0].partition(" ")
    if result.returncode == EXIT_VALID:
        return
    elif result.returncode == EXIT_INVALID and verdict == INVALID_VERDICT:
        raise ValidationError(
            _("rcheevos cannot parse this condition: %(reason)s."),
            code="invalid_trigger",
            params={"reason": reason.strip()},
        )
    else:
        # A failed compile also exits 1, but prints no verdict.
        raise _unavailable(f"exit {result.returncode}: {result.stderr.strip()}")
