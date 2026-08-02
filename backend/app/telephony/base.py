"""Telephony provider interface.

Two implementations: Africa's Talking for real handsets, and a simulator that
runs the identical state machine on screen with no account and no network. The
simulator is not a toy -- it is how you rehearse the demo on a laptop in a room
with no signal, and how the pitch survives a venue whose GSM does not cooperate.
"""
from typing import Optional


class SendResult:
    def __init__(self, ok: bool, provider_id: Optional[str] = None,
                 error: Optional[str] = None, raw=None):
        self.ok = ok
        self.provider_id = provider_id
        self.error = error
        self.raw = raw

    def to_dict(self):
        return {"ok": self.ok, "provider_id": self.provider_id,
                "error": self.error, "raw": self.raw}


class Provider:
    name = "base"
    live = False

    def place_call(self, to: str, session_hint: Optional[str] = None) -> SendResult:
        raise NotImplementedError

    def send_sms(self, to: str, body: str) -> SendResult:
        raise NotImplementedError
