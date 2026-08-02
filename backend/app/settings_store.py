"""Operational settings, entered from the browser rather than the shell.

A CHPS deployment is handed to people who will never open a terminal. So the
Africa's Talking credentials, the voice number, the USSD code and the phone to
test against all live in the database and are edited on a Setup screen.

Secrets are masked on read. The only way to see an API key again is to replace
it, which is the correct behaviour for a field that someone will screenshot.
"""
from typing import Dict, Optional

from sqlalchemy.orm import Session

from .models import Setting

SIMULATOR = "simulator"
AFRICASTALKING = "africastalking"

# key -> (default, is_secret, label, help)
SCHEMA = {
    "telephony_provider": (
        SIMULATOR, False, "Telephony provider",
        "Simulator needs no account and runs the whole flow on screen. "
        "Switch to Africa's Talking once your credentials are in."),
    "at_environment": (
        "sandbox", False, "Africa's Talking environment",
        "sandbox for testing, live for real calls to real handsets."),
    "at_username": (
        "sandbox", False, "Africa's Talking username",
        "Use 'sandbox' in the sandbox environment, or your app username when live."),
    "at_api_key": (
        "", True, "Africa's Talking API key",
        "From the Africa's Talking dashboard. Stored server-side and masked after saving."),
    "at_voice_number": (
        "", False, "Voice number",
        "The Africa's Talking number that places calls, e.g. +233XXXXXXXXX. "
        "Outbound calls will not work without it."),
    "at_sender_id": (
        "MABIA", False, "SMS sender ID",
        "Alphanumeric sender IDs need registration in Ghana; leave as is if unsure."),
    "at_ussd_code": (
        "", False, "USSD code",
        "Your shared code, e.g. *384*1234#. Only needed for the USSD worklist."),
    "public_base_url": (
        "", False, "Public callback URL",
        "The HTTPS address Africa's Talking will call back on. Use an ngrok URL "
        "for local testing. Calls fail silently without this."),
    "test_phone": (
        "", False, "Your test phone number",
        "The handset you want to receive test calls and messages on, e.g. +233XXXXXXXXX."),
    "default_language": (
        "dagbani", False, "Default language",
        "dagbani, kusaal, frafra, gonja or english."),
    "hotline_number": (
        "", False, "Hotline number",
        "The number caregivers ring and hang up on. The platform calls them back, "
        "so they spend no airtime."),
}

MASK = "••••••••"


def get(db: Session, key: str) -> str:
    row = db.get(Setting, key)
    if row is not None and row.value is not None and row.value != "":
        return row.value
    default, _, _, _ = SCHEMA.get(key, ("", False, "", ""))
    return default


def set_value(db: Session, key: str, value: str) -> None:
    if key not in SCHEMA:
        return
    _, is_secret, _, _ = SCHEMA[key]
    # A masked value coming back from the browser means "unchanged".
    if is_secret and value == MASK:
        return
    row = db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.flush()


def set_many(db: Session, values: Dict[str, str]) -> None:
    for key, value in values.items():
        set_value(db, key, value if value is not None else "")


def public_view(db: Session):
    """Everything the Setup screen needs, with secrets masked."""
    out = []
    for key, (default, is_secret, label, help_text) in SCHEMA.items():
        raw = get(db, key)
        out.append({
            "key": key,
            "label": label,
            "help": help_text,
            "secret": is_secret,
            "value": MASK if (is_secret and raw) else ("" if is_secret else raw),
            "configured": bool(raw),
        })
    return out


def readiness(db: Session) -> Dict[str, object]:
    """What can actually be done right now, and what is missing to do more.

    The Setup screen shows this verbatim, so it has to be honest: half-configured
    telephony that silently does nothing is worse than telephony that says why.
    """
    provider = get(db, "telephony_provider")
    checks = []

    if provider == SIMULATOR:
        checks.append({"name": "Simulator", "ok": True,
                       "detail": "Every flow runs on screen. No credentials needed."})
        return {"provider": provider, "can_call": True, "can_sms": True,
                "live": False, "checks": checks}

    api_key = get(db, "at_api_key")
    username = get(db, "at_username")
    voice_number = get(db, "at_voice_number")
    base_url = get(db, "public_base_url")
    test_phone = get(db, "test_phone")

    checks.append({"name": "API key", "ok": bool(api_key),
                   "detail": "Set" if api_key else "Missing — nothing will send"})
    checks.append({"name": "Username", "ok": bool(username),
                   "detail": username or "Missing"})
    checks.append({"name": "Voice number", "ok": bool(voice_number),
                   "detail": voice_number or "Missing — outbound calls cannot be placed"})
    checks.append({
        "name": "Public callback URL", "ok": bool(base_url),
        "detail": base_url or
        "Missing — a call will connect and then go silent, because Africa's "
        "Talking has nowhere to ask what to play"})
    checks.append({"name": "Test phone", "ok": bool(test_phone),
                   "detail": test_phone or "Missing — set one to try a real call"})

    can_sms = bool(api_key and username)
    can_call = bool(api_key and username and voice_number and base_url)
    return {"provider": provider, "can_call": can_call, "can_sms": can_sms,
            "live": get(db, "at_environment") == "live", "checks": checks}
