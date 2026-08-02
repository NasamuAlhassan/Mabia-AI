"""The simulator provider.

Runs the identical IVR state machine with no account, no credentials and no
network. A call becomes a handset on screen: it rings, you answer it, you press
keys, and the backend cannot tell the difference -- the same webhook, the same
XML, the same transitions.

This exists for three reasons, in ascending order of importance:
  1. It lets the team build the whole flow before the telephony account is live.
  2. It lets the app be demonstrated on a laptop with no signal.
  3. It means a venue with bad GSM cannot take the pitch down.
"""
import datetime as dt
from typing import Optional

from sqlalchemy.orm import Session

from ..ids import uuid7
from ..models import CallSession, Message
from .base import Provider, SendResult


class SimulatorProvider(Provider):
    name = "simulator"
    live = False

    def __init__(self, db: Session):
        self.db = db

    def place_call(self, to: str, session_hint: Optional[str] = None) -> SendResult:
        # The session row itself is the ringing handset; the caller creates it.
        return SendResult(True, provider_id=session_hint or uuid7())

    def send_sms(self, to: str, body: str) -> SendResult:
        # Nothing leaves the machine. The message is stored so the Messages
        # screen can show exactly what a handset would have received.
        return SendResult(True, provider_id="sim-" + uuid7()[:8])


def ring(db: Session, session_id: str) -> None:
    session = db.get(CallSession, session_id)
    if session:
        session.ringing = True
        db.flush()


def answer(db: Session, session_id: str) -> Optional[CallSession]:
    session = db.get(CallSession, session_id)
    if session:
        session.ringing = False
        db.flush()
    return session


def pending_handsets(db: Session, limit: int = 20):
    return (db.query(CallSession)
              .filter(CallSession.provider == "simulator",
                      CallSession.ended_at.is_(None))
              .order_by(CallSession.started_at.desc())
              .limit(limit)
              .all())


def recent_messages(db: Session, limit: int = 30):
    return (db.query(Message)
              .order_by(Message.created_at.desc())
              .limit(limit)
              .all())
