"""Africa's Talking provider.

Ghana is supported for Voice, SMS and USSD. Two things are worth knowing before
this works against a real handset:

* The voice callback URL must be public HTTPS. A call will connect and then sit
  in silence if Africa's Talking has nowhere to ask what to play. During local
  development, tunnel it (ngrok) and put the tunnel URL in Setup.

* Sandbox and live are different hosts *and* a different username. In sandbox
  the username is literally "sandbox".
"""
from typing import Optional

import httpx

from .base import Provider, SendResult

LIVE_VOICE = "https://voice.africastalking.com/call"
SANDBOX_VOICE = "https://voice.sandbox.africastalking.com/call"
LIVE_SMS = "https://api.africastalking.com/version1/messaging"
SANDBOX_SMS = "https://api.sandbox.africastalking.com/version1/messaging"

TIMEOUT = 15.0


class AfricasTalkingProvider(Provider):
    name = "africastalking"

    def __init__(self, username: str, api_key: str, voice_number: str = "",
                 sender_id: str = "", environment: str = "sandbox"):
        self.username = username
        self.api_key = api_key
        self.voice_number = voice_number
        self.sender_id = sender_id
        self.environment = environment
        self.live = environment == "live"

    @property
    def _headers(self):
        return {
            "apiKey": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    def place_call(self, to: str, session_hint: Optional[str] = None) -> SendResult:
        if not self.voice_number:
            return SendResult(False, error="No voice number configured in Setup.")
        if not self.api_key:
            return SendResult(False, error="No Africa's Talking API key configured.")

        url = LIVE_VOICE if self.live else SANDBOX_VOICE
        data = {"username": self.username, "from": self.voice_number, "to": to}
        try:
            response = httpx.post(url, data=data, headers=self._headers, timeout=TIMEOUT)
        except Exception as exc:  # network, DNS, TLS -- all the same to the caller
            return SendResult(False, error="Could not reach Africa's Talking: {}".format(exc))

        payload = _json_or_text(response)
        if response.status_code >= 400:
            return SendResult(False, error=_describe(response, payload), raw=payload)

        entries = (payload or {}).get("entries") or []
        if entries:
            entry = entries[0]
            status = (entry.get("status") or "").lower()
            if status not in ("queued", "success"):
                return SendResult(False, error=entry.get("errorMessage") or status,
                                  raw=payload)
            return SendResult(True, provider_id=entry.get("sessionId"), raw=payload)

        error = (payload or {}).get("errorMessage")
        if error and error != "None":
            return SendResult(False, error=error, raw=payload)
        return SendResult(True, raw=payload)

    def send_sms(self, to: str, body: str) -> SendResult:
        if not self.api_key:
            return SendResult(False, error="No Africa's Talking API key configured.")
        url = LIVE_SMS if self.live else SANDBOX_SMS
        data = {"username": self.username, "to": to, "message": body}
        if self.sender_id:
            data["from"] = self.sender_id
        try:
            response = httpx.post(url, data=data, headers=self._headers, timeout=TIMEOUT)
        except Exception as exc:
            return SendResult(False, error="Could not reach Africa's Talking: {}".format(exc))

        payload = _json_or_text(response)
        if response.status_code >= 400:
            return SendResult(False, error=_describe(response, payload), raw=payload)

        recipients = ((payload or {}).get("SMSMessageData") or {}).get("Recipients") or []
        if recipients:
            first = recipients[0]
            if int(first.get("statusCode", 0)) not in (100, 101, 102):
                return SendResult(False, error=first.get("status"), raw=payload)
            return SendResult(True, provider_id=first.get("messageId"), raw=payload)

        message = ((payload or {}).get("SMSMessageData") or {}).get("Message")
        return SendResult(False, error=message or "No recipients accepted", raw=payload)


def _json_or_text(response):
    try:
        return response.json()
    except Exception:
        return {"raw": response.text[:500]}


def _describe(response, payload) -> str:
    if response.status_code == 401:
        return ("Africa's Talking rejected the credentials (401). Check the API "
                "key and that the username matches the environment.")
    if response.status_code == 403:
        return ("Africa's Talking refused the request (403). In live mode this "
                "usually means the account is not enabled for this product.")
    detail = payload.get("errorMessage") if isinstance(payload, dict) else None
    return detail or "HTTP {} from Africa's Talking".format(response.status_code)
