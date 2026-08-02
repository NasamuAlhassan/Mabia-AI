"""Khaya (GhanaNLP) client — translation and speech.

Probed against the live API rather than written from documentation, because the
documentation and the deployed service disagree in two places that matter.

What is actually true today, verified with a real key:

  GET  /v1/languages   200  eng twi ewe gaa fat yor dag kik gur luo mer kus
  POST /v1/translate   200  {"in": "...", "lang": "en-dag"} -> a bare JSON string
  POST /tts/v1/tts     403  an Azure "Web App - Unavailable" HTML page

So translation works and speech synthesis is currently unavailable upstream —
not a bad key, an upstream app that is down. The pipeline therefore treats TTS
as *optional*: a phrase that cannot be synthesised is not a failure, it is a
phrase that needs a human voice, and it goes onto the recording list.

The language mapping matters and is not one-to-one with what the product
speaks:

  Dagbani -> dag     supported
  Kusaal  -> kus     supported
  Frafra  -> gur     supported (Khaya calls it Gurune)
  Gonja   -> none    NOT supported. Gonja is a Guang language, not Mabia, and
                     Khaya has no model for it. Gonja prompts have to be
                     recorded by a speaker; there is no synthesis path.
"""
import os
from typing import Optional, Tuple

import httpx

TRANSLATE_URL = "https://translation-api.ghananlp.org/v1/translate"
LANGUAGES_URL = "https://translation-api.ghananlp.org/v1/languages"
TTS_URL = "https://translation-api.ghananlp.org/tts/v1/tts"

TIMEOUT = 45.0

# What the product calls a language -> what Khaya calls it.
KHAYA_CODE = {
    "dagbani": "dag",
    "kusaal": "kus",
    "frafra": "gur",
    "gonja": None,      # no model exists; must be recorded
    "english": "eng",
}

UNSUPPORTED_NOTE = ("Khaya has no model for Gonja — it is a Guang language, "
                    "not Mabia. These prompts must be recorded by a speaker.")


class LanguageResult:
    def __init__(self, ok: bool, text: str = "", audio: bytes = b"",
                 error: Optional[str] = None, provider: str = "khaya"):
        self.ok = ok
        self.text = text
        self.audio = audio
        self.error = error
        self.provider = provider


def api_key() -> str:
    return os.getenv("GHANANLP_API_KEY", "")


def _headers():
    return {"Ocp-Apim-Subscription-Key": api_key(),
            "Content-Type": "application/json"}


def configured() -> bool:
    return bool(api_key())


def supported_languages() -> Tuple[bool, dict]:
    if not configured():
        return False, {}
    try:
        r = httpx.get(LANGUAGES_URL, headers=_headers(), timeout=TIMEOUT)
        if r.status_code != 200:
            return False, {}
        return True, (r.json() or {}).get("languages", {})
    except Exception:
        return False, {}


def translate(text: str, language: str) -> LanguageResult:
    """English into a Ghanaian language. Live."""
    code = KHAYA_CODE.get(language)
    if code is None:
        return LanguageResult(False, error=UNSUPPORTED_NOTE)
    if code == "eng":
        return LanguageResult(True, text=text, provider="source")
    if not configured():
        return LanguageResult(False, error="No GHANANLP_API_KEY set.")

    try:
        r = httpx.post(TRANSLATE_URL, headers=_headers(), timeout=TIMEOUT,
                       json={"in": text, "lang": "en-{}".format(code)})
    except Exception as exc:
        return LanguageResult(False, error="Could not reach Khaya: {}".format(exc))

    if r.status_code == 401:
        return LanguageResult(False, error="Khaya rejected the API key (401).")
    if r.status_code in (403, 429):
        # The free tier is a call-volume quota, not a per-second rate limit, and
        # it returns 403 with the replenishment time in the body. Surfacing that
        # verbatim matters: "HTTP 403" reads as a broken key and sends you
        # hunting for the wrong problem for an hour.
        detail = ""
        try:
            detail = (r.json() or {}).get("message", "")
        except Exception:
            detail = r.text[:160]
        if "quota" in detail.lower():
            return LanguageResult(False, error="Khaya quota exhausted. " + detail)
        return LanguageResult(False, error="Khaya refused the request: " + detail)
    if r.status_code >= 400:
        return LanguageResult(False, error="Khaya returned HTTP {}".format(
            r.status_code))

    try:
        out = r.json()
    except Exception:
        return LanguageResult(False, error="Khaya returned a non-JSON body.")

    # The endpoint returns a bare JSON string, not an object.
    if isinstance(out, dict):
        out = out.get("translation") or out.get("out") or ""
    if not isinstance(out, str) or not out.strip():
        return LanguageResult(False, error="Khaya returned an empty translation.")
    return LanguageResult(True, text=out.strip())


def synthesise(text: str, language: str) -> LanguageResult:
    """Text into speech. Currently unavailable upstream; handled, not hidden."""
    code = KHAYA_CODE.get(language)
    if code is None:
        return LanguageResult(False, error=UNSUPPORTED_NOTE)
    if not configured():
        return LanguageResult(False, error="No GHANANLP_API_KEY set.")

    try:
        r = httpx.post(TTS_URL, headers=_headers(), timeout=TIMEOUT,
                       json={"text": text, "language": code})
    except Exception as exc:
        return LanguageResult(False, error="Could not reach Khaya TTS: {}".format(exc))

    content_type = r.headers.get("content-type", "")
    if r.status_code == 200 and ("audio" in content_type or len(r.content) > 2000):
        return LanguageResult(True, audio=r.content)

    if r.status_code == 403 and "text/html" in content_type:
        return LanguageResult(
            False,
            error="Khaya text-to-speech is unavailable upstream right now "
                  "(the service returns an Azure 'Web App - Unavailable' page, "
                  "not an auth error). Translation is unaffected. This phrase "
                  "needs a recorded voice until it comes back.")
    return LanguageResult(False, error="Khaya TTS returned HTTP {}".format(
        r.status_code))


def validate(source: str, translated: str, language: str) -> Optional[str]:
    """Cheap sanity checks before a translation is trusted with a patient.

    None means it passed. These are not a substitute for a speaker reading it —
    they exist to catch the failures that are obvious from the outside: an empty
    string, an HTML error page, the English echoed back, or a result so much
    shorter than the source that content was clearly dropped.
    """
    if not translated or not translated.strip():
        return "empty"
    lowered = translated.lower()
    if "<html" in lowered or "<!doctype" in lowered:
        return "looks like an error page, not a translation"
    if translated.strip() == source.strip():
        return "identical to the English — probably not translated"
    if len(translated) < max(4, len(source) * 0.25):
        return "much shorter than the source — content may have been dropped"
    if len(translated) > len(source) * 6:
        return "far longer than the source — probably not a translation"
    return None
