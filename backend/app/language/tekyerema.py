"""Tɛkyerɛma — our own language service. Translation and speech.

This is a Hugging Face Space we run ourselves
(PrinceAlhassanNasamu/tekyerema-lang), so unlike Khaya it has no quota that
replenishes in weeks, no key to lose, and no upstream we cannot fix. It is the
first route the pipeline tries; Khaya and MMS stay behind it as fallbacks.

What it serves, checked against the live Space rather than assumed:

  translate  eng <-> twi ewe hau kus dag      NLLB-600M fine-tune
  tts        twi ewe hau kus dag eng          VITS voices (Dagbani: female only)
  asr        twi ewe hau kus dag eng          not used here -- see below

Not covered: Frafra (Gurune) and Gonja. Those stay on Khaya and on a human
voice, exactly as before.

It is a Gradio app, so the REST shape is Gradio's: POST /gradio_api/call/<name>
returns an event id, and GET on that id returns a server-sent-event body whose
`complete` event carries the result. The Space is on shared hardware and can be
slow to wake, so the timeouts here are long on purpose -- these calls happen in
the preparation pipeline, never inside a phone call.

**Opt-in.** Nothing is called until TEKYEREMA_URL is set. There is no default
URL in code: a test run, or a developer's laptop, must never reach out to a
shared service by accident, and "unset" must keep meaning "behaves as it did".

**What is sent.** Only catalogue text -- the fixed sentences the platform says.
Never a patient's name, number or answers.

**Speech recognition is deliberately not wired.** It would mean sending a
caller's voice to a third-party host, which is a consent and data-protection
decision and not a plumbing one. The keypad path stands alone without it.

Quality is not guaranteed by being ours. One probe left an English word
("bloody") in a Twi sentence. Every output goes through the same validation as
Khaya's, and a speaker still has to read it before it is trusted with a patient.
"""
import json
import os
from typing import Optional

import httpx

from .khaya import LanguageResult

# What the product calls a language -> what the Space calls it. Frafra and
# Gonja are absent because the Space has no model for them.
TK_CODE = {
    "dagbani": "dag",
    "kusaal": "kus",
    "twi": "twi",
    "ewe": "ewe",
    "hausa": "hau",
    "english": "eng",
}

# Long, because the Space is on shared hardware and may be waking up.
CALL_TIMEOUT = 180.0
HEALTH_TIMEOUT = 10.0
MAX_TEXT_CHARS = 2000      # the Space refuses TTS input longer than this
DEFAULT_VOICE = "Female"   # Dagbani has no male voice; one choice, everywhere
DEFAULT_SPEED = 1.0

# Phrases the pipeline matches on to decide a provider is down for the whole
# batch rather than failing on one line. Kept in the messages below.
UNAVAILABLE = "Tekyerema is unavailable"


def base_url() -> str:
    return os.getenv("TEKYEREMA_URL", "").strip().rstrip("/")


def configured() -> bool:
    return bool(base_url())


def supports(language: str) -> bool:
    return language in TK_CODE


def _call(name: str, data: list, timeout: float = CALL_TIMEOUT):
    """One Gradio call. Returns (ok, payload_or_error)."""
    root = base_url()
    try:
        started = httpx.post("{}/gradio_api/call/{}".format(root, name),
                             json={"data": data}, timeout=timeout)
        if started.status_code >= 500:
            return False, "{}: HTTP {} starting {}".format(
                UNAVAILABLE, started.status_code, name)
        if started.status_code >= 400:
            return False, "Tekyerema refused {} (HTTP {})".format(
                name, started.status_code)
        event_id = (started.json() or {}).get("event_id")
        if not event_id:
            return False, "Tekyerema returned no event id for {}".format(name)

        # The body is complete once the server closes the stream, so a plain
        # GET is enough -- there is nothing to stream to a caller here.
        done = httpx.get("{}/gradio_api/call/{}/{}".format(root, name, event_id),
                         timeout=timeout)
    except Exception as exc:
        return False, "{}: could not reach {} ({})".format(
            UNAVAILABLE, root, exc.__class__.__name__)

    if done.status_code >= 400:
        return False, "{}: HTTP {} reading {}".format(
            UNAVAILABLE, done.status_code, name)

    event, payload = None, None
    for line in done.text.splitlines():
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:") and event in ("complete", "error"):
            raw = line[5:].strip()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = raw
            if event == "complete":
                return True, payload
            return False, "Tekyerema {} failed: {}".format(name, payload)
    return False, "Tekyerema {} ended without a result".format(name)


def health() -> dict:
    """Is it configured, and does it answer? Used by the status screen."""
    if not configured():
        return {"configured": False, "reachable": False, "url": None}
    # Short: this runs when someone opens the status screen, and a Space that
    # is asleep should read as "not reachable right now", not as a hung page.
    ok, payload = _call("health", [], timeout=HEALTH_TIMEOUT)
    info = None
    if ok and isinstance(payload, list) and payload:
        try:
            info = json.loads(payload[0]) if isinstance(payload[0], str) else payload[0]
        except ValueError:
            info = None
    return {"configured": True, "reachable": ok, "url": base_url(),
            "languages": (info or {}).get("languages") if isinstance(info, dict) else None,
            "error": None if ok else payload}


def translate(text: str, language: str) -> LanguageResult:
    """English into a Ghanaian language."""
    code = TK_CODE.get(language)
    if code is None:
        return LanguageResult(False, provider="tekyerema",
                              error="Tekyerema has no model for {}.".format(language))
    if code == "eng":
        return LanguageResult(True, text=text, provider="source")
    if not configured():
        return LanguageResult(False, provider="tekyerema",
                              error="No TEKYEREMA_URL set.")
    if len(text) > MAX_TEXT_CHARS:
        return LanguageResult(False, provider="tekyerema",
                              error="Text is too long to translate in one call.")

    ok, payload = _call("translate", [text, "eng", code])
    if not ok:
        return LanguageResult(False, provider="tekyerema", error=payload)
    try:
        body = payload[0]
        result = json.loads(body) if isinstance(body, str) else body
        out = (result or {}).get("translation")
        covered = (result or {}).get("covered", True)
    except Exception:
        return LanguageResult(False, provider="tekyerema",
                              error="Tekyerema returned a body we could not read.")
    # `covered: false` means it passed the text through untouched because it
    # has no model for the pair. That is not a translation.
    if not covered:
        return LanguageResult(False, provider="tekyerema",
                              error="Tekyerema does not cover eng->{}.".format(code))
    if not isinstance(out, str) or not out.strip():
        return LanguageResult(False, provider="tekyerema",
                              error="Tekyerema returned an empty translation.")
    return LanguageResult(True, text=out.strip(), provider="tekyerema")


def synthesise(text: str, language: str) -> LanguageResult:
    """Text into speech, as WAV bytes."""
    code = TK_CODE.get(language)
    if code is None:
        return LanguageResult(False, provider="tekyerema",
                              error="Tekyerema has no voice for {}.".format(language))
    if not configured():
        return LanguageResult(False, provider="tekyerema",
                              error="No TEKYEREMA_URL set.")
    if len(text) > MAX_TEXT_CHARS:
        return LanguageResult(False, provider="tekyerema",
                              error="Text is too long to speak in one call.")

    ok, payload = _call("tts_voice",
                        [text, code, DEFAULT_VOICE, DEFAULT_SPEED, None])
    if not ok:
        return LanguageResult(False, provider="tekyerema", error=payload)

    path: Optional[str] = None
    try:
        first = payload[0]
        path = first.get("path") if isinstance(first, dict) else None
    except Exception:
        path = None
    if not path:
        return LanguageResult(False, provider="tekyerema",
                              error="Tekyerema returned no audio file.")

    # Built from the returned path and our own configured host, never from the
    # URL the response supplies: the host we fetch from is not something a
    # response gets to choose.
    try:
        audio = httpx.get("{}/gradio_api/file={}".format(base_url(), path),
                          timeout=CALL_TIMEOUT)
    except Exception as exc:
        return LanguageResult(False, provider="tekyerema",
                              error="{}: could not fetch audio ({})".format(
                                  UNAVAILABLE, exc.__class__.__name__))
    if audio.status_code != 200 or not audio.content:
        return LanguageResult(False, provider="tekyerema",
                              error="Tekyerema audio fetch returned HTTP {}".format(
                                  audio.status_code))
    return LanguageResult(True, audio=audio.content, provider="tekyerema")
