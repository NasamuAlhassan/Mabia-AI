"""One canonical form for a phone number, because there are four in the wild.

Every lookup in this system is an exact string match on a phone number, and
nothing normalised them. That is fine right up until it meets reality:

    a CHO enrols her as        0240000001      (how the number is written here)
    Africa's Talking reports   +233240000001   (E.164, what the network uses)
    someone types              233 24 000 0001 (a copy-paste from a contact list)

Those are the same handset and none of them match each other. The consequences
are not cosmetic. A woman who flashes the hotline is looked up by caller ID; if
that lookup misses, she is rung back as an anonymous caller with no record, no
language preference, no pregnancy, no danger-sign history -- the platform speaks
English at a stranger. A driver saved on a household form does not match the
roster, so the cascade never reaches him. Outbound calls fail outright, because
Africa's Talking requires E.164.

So: store E.164, compare E.164, and accept anything a human might plausibly
type. Ghana's country code is 233 and national numbers are nine digits after
the leading zero.
"""
import re
from typing import Optional

GHANA = "233"
NATIONAL_DIGITS = 9          # after the trunk zero, e.g. 24 000 0001


def normalise(raw: Optional[str], country: str = GHANA) -> Optional[str]:
    """The E.164 form, or the input cleaned up if it is not recognisably Ghanaian.

    Deliberately does not throw away a number it cannot parse. A foreign number,
    or a short code, is still a number someone meant to type, and silently
    discarding it would be worse than storing it as given.
    """
    if raw is None:
        return None
    digits = re.sub(r"[^\d+]", "", str(raw))
    if not digits:
        return None

    if digits.startswith("+"):
        rest = digits[1:]
        return "+" + rest if rest else None

    # 00233... — the international prefix as dialled from a landline.
    if digits.startswith("00"):
        return "+" + digits[2:]

    # 233240000001
    if digits.startswith(country) and len(digits) == len(country) + NATIONAL_DIGITS:
        return "+" + digits

    # 0240000001 — the trunk zero, which is how it is written locally.
    if digits.startswith("0") and len(digits) == NATIONAL_DIGITS + 1:
        return "+" + country + digits[1:]

    # 240000001 — written without the zero, which people do.
    if len(digits) == NATIONAL_DIGITS:
        return "+" + country + digits

    return digits


def same(a: Optional[str], b: Optional[str]) -> bool:
    """Whether two numbers are the same handset."""
    if not a or not b:
        return False
    return normalise(a) == normalise(b)


def display(raw: Optional[str]) -> str:
    """How it is shown to a health worker: 024 000 0001, not +233240000001.

    The E.164 form is correct and unreadable. A CHO checking a number against a
    scrap of paper reads it in the local grouping, and asking her to do that
    translation in her head is how numbers get mistyped.
    """
    number = normalise(raw)
    if not number or not number.startswith("+" + GHANA):
        return raw or ""
    national = number[1 + len(GHANA):]
    if len(national) != NATIONAL_DIGITS:
        return number
    return "0{} {} {}".format(national[:2], national[2:5], national[5:])


def variants(raw):
    """Every spelling of this number that might be sitting in the database.

    Rows written before normalisation existed keep their original form, and a
    row the migration could not rewrite -- because doing so would collide --
    keeps it forever. Looking only for the canonical form meant such a row was
    unreachable by any spelling its owner could type, which for the users table
    is a permanent lockout.
    """
    # Deliberately NOT the raw string. normalise() re-derives every spelling of
    # a parseable Ghanaian number, so including the input verbatim adds nothing
    # -- and this set goes straight into an authentication IN clause, which is
    # the one place not to carry arbitrary caller-supplied text.
    canonical = normalise(raw)
    out = set()
    if canonical:
        out.add(canonical)
        if canonical.startswith("+" + GHANA):
            national = canonical[1 + len(GHANA):]
            out.add("0" + national)
            out.add(GHANA + national)
            out.add(national)
        else:
            # A number we cannot parse as Ghanaian -- a foreign one -- can only
            # be matched as it normalises, never as it was typed.
            out.add(canonical)
    return {v for v in out if v}
