"""The simulator: ringing handsets on screen, and every message the platform sent.

The point is that this drives the *same* webhook as a real call. Nothing here is
a mock of the IVR -- it is the IVR, reached from a browser instead of a handset.
"""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CallSession, Message, Patient, User
from ..security import current_user
from ..telephony import simulator as sim

router = APIRouter(prefix="/api/simulator", tags=["simulator"])


@router.get("/handsets")
def handsets(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = []
    for session in sim.pending_handsets(db):
        patient = db.get(Patient, session.patient_id) if session.patient_id else None
        # Whose handset is this? For a dispatch it is the driver's, not the
        # patient's -- showing her name on his phone was confusing.
        who = patient.name if patient else session.phone
        if session.purpose == "driver" and session.driver_id:
            from ..models import Driver
            driver = db.get(Driver, session.driver_id)
            if driver:
                who = "{} (driver)".format(driver.name)
        elif session.purpose == "nurse":
            who = "{} (nurse)".format(session.phone)
        rows.append({
            "session_id": session.id, "phone": session.phone,
            "purpose": session.purpose, "ringing": bool(session.ringing),
            "state": session.state, "language": session.language,
            "who": who,
            "about": patient.name if patient else None,
            "transcript": session.transcript or [],
            "started_at": session.started_at})
    return {"handsets": rows}


@router.get("/messages")
def messages(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = []
    for message in sim.recent_messages(db):
        rows.append({"id": message.id, "to": message.to_phone,
                     "body": message.body, "kind": message.kind,
                     "status": message.status, "error": message.error,
                     "provider": message.provider, "at": message.created_at})
    return {"messages": rows}


class PressIn(BaseModel):
    session_id: str
    digit: Optional[str] = None


@router.post("/press")
async def press(body: PressIn, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    """Answer, or press a key. Routes straight into the real voice webhook."""
    from .telephony import voice

    session = db.get(CallSession, body.session_id)
    if session is None:
        return {"error": "No such call"}
    if session.ringing:
        sim.answer(db, session.id)
        db.commit()

    class _Form(dict):
        async def __call__(self):
            return self

    class _Request:
        def __init__(self, data):
            self._data = data

        async def form(self):
            return self._data

    data = {"sessionId": session.id, "isActive": "1",
            "dtmfDigits": body.digit or "",
            "callerNumber": session.phone,
            "destinationNumber": session.phone,
            "direction": session.direction}
    response = await voice(_Request(data), db)
    xml = response.body.decode() if hasattr(response, "body") else ""

    refreshed = db.get(CallSession, body.session_id)
    return {"xml": xml, "spoken": _spoken(xml),
            "options": _options(xml),
            "state": refreshed.state if refreshed else None,
            "ended": bool(refreshed.ended_at) if refreshed else True,
            "outcome": refreshed.outcome if refreshed else None}


def _spoken(xml: str) -> str:
    import re
    says = re.findall(r"<Say>(.*?)</Say>", xml, flags=re.S)
    plays = re.findall(r'<Play url="(.*?)"', xml)
    parts = [s.strip() for s in says]
    parts += ["[audio: {}]".format(p.rsplit("/", 1)[-1]) for p in plays]
    return " ".join(parts)


def _options(xml: str):
    if "<GetDigits" not in xml:
        return []
    return ["1", "2", "9"]
