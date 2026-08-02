"""Telephony service: everything the rest of the app calls to reach a handset.

Chooses a provider from the settings the team entered on the Setup screen, so
switching from the simulator to real calls is a dropdown, not a deploy.
"""
import datetime as dt
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from .. import settings_store as store
from ..ids import uuid7
from ..models import CallSession, Contact, Message, Patient
from .africastalking import AfricasTalkingProvider
from .base import Provider, SendResult
from .simulator import SimulatorProvider


def provider_for(db: Session) -> Provider:
    if store.get(db, "telephony_provider") == store.AFRICASTALKING:
        return AfricasTalkingProvider(
            username=store.get(db, "at_username"),
            api_key=store.get(db, "at_api_key"),
            voice_number=store.get(db, "at_voice_number"),
            sender_id=store.get(db, "at_sender_id"),
            environment=store.get(db, "at_environment"))
    return SimulatorProvider(db)


def base_url(db: Session) -> str:
    from ..config import settings as env
    return store.get(db, "public_base_url") or env.public_base_url or ""


def callback_url(db: Session) -> str:
    return "{}/api/telephony/voice".format(base_url(db).rstrip("/"))


# ------------------------------------------------------------------ SMS


def send_sms(db: Session, to: str, body: str, kind: str = "alert",
             patient_id: Optional[str] = None) -> Message:
    provider = provider_for(db)
    result = provider.send_sms(to, body)
    message = Message(
        to_phone=to, body=body, kind=kind, patient_id=patient_id,
        provider=provider.name, provider_id=result.provider_id,
        status="sent" if result.ok else "failed", error=result.error)
    db.add(message)
    db.flush()
    return message


# ------------------------------------------------------------------ calls


def start_call(db: Session, *, phone: str, patient_id: Optional[str] = None,
               purpose: str = "outreach", language: str = "dagbani",
               include_diet: bool = False, contact_id: Optional[str] = None,
               emergency_id: Optional[str] = None,
               driver_id: Optional[str] = None) -> Tuple[CallSession, SendResult]:
    """Create the session first, then ask the provider to ring.

    Session first, deliberately: with Africa's Talking the callback can arrive
    before the HTTP response does, and a callback for a session that does not
    exist yet is a dropped call.
    """
    provider = provider_for(db)
    session_id = uuid7()
    session = CallSession(
        id=session_id, patient_id=patient_id, contact_id=contact_id,
        direction="outbound", phone=phone, provider=provider.name,
        purpose=purpose, language=language, include_diet=include_diet,
        emergency_id=emergency_id, driver_id=driver_id,
        state="greet", answers={}, transcript=[],
        ringing=(provider.name == "simulator"))
    db.add(session)
    db.flush()

    result = provider.place_call(phone, session_hint=session_id)
    if not result.ok:
        session.outcome = "failed"
        session.ended_at = dt.datetime.utcnow()
        db.flush()
    elif provider.name == "africastalking" and result.provider_id:
        # Africa's Talking assigns its own sessionId; keep ours as the key and
        # record theirs so the two can be reconciled in the transcript.
        session.transcript = [{"provider_session": result.provider_id}]
        db.flush()
    return session, result


def outreach_call(db: Session, patient: Patient,
                  contact: Optional[Contact] = None) -> Tuple[CallSession, SendResult]:
    return start_call(
        db, phone=patient.phone, patient_id=patient.id, purpose="outreach",
        language=patient.language or "dagbani",
        include_diet=bool(contact.include_diet) if contact else True,
        contact_id=contact.id if contact else None)


def test_call(db: Session) -> Tuple[Optional[CallSession], SendResult]:
    """Ring the number the team entered on Setup. The fifteen-minute check."""
    phone = store.get(db, "test_phone")
    if not phone:
        return None, SendResult(False, error="No test phone number set in Setup.")
    session, result = start_call(
        db, phone=phone, purpose="outreach",
        language=store.get(db, "default_language"), include_diet=True)
    return session, result


def test_sms(db: Session) -> Tuple[Optional[Message], SendResult]:
    phone = store.get(db, "test_phone")
    if not phone:
        return None, SendResult(False, error="No test phone number set in Setup.")
    body = ("Mabia AI test message. If you are reading this on a handset, SMS "
            "is working.")
    message = send_sms(db, phone, body, kind="test")
    return message, SendResult(message.status == "sent", message.provider_id,
                               message.error)
