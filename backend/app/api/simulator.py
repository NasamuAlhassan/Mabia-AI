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
    spoken, english = _render(db, refreshed_language(db, body.session_id), xml)
    return {"xml": xml, "spoken": spoken, "english": english,
            "options": _options(xml),
            "connecting": _connecting(db, xml),
            "state": refreshed.state if refreshed else None,
            "ended": bool(refreshed.ended_at) if refreshed else True,
            "outcome": refreshed.outcome if refreshed else None}


def _connecting(db, xml: str):
    """Who the call is being handed to, for whoever is watching.

    A <Dial> is the one thing that happens in a call and says nothing: it plays
    no audio, so the panel showed "please hold" and then a blank screen. On the
    transport path that is the whole event -- the numbers being rung in order
    are what there is to see.
    """
    import re
    from ..models import Driver

    found = re.search(r'<Dial phoneNumbers="(.*?)"', xml)
    if not found:
        return []
    out = []
    for position, number in enumerate(found.group(1).split(","), 1):
        driver = db.query(Driver).filter(Driver.phone == number.strip()).first()
        out.append({"position": position, "phone": number.strip(),
                    "name": driver.name if driver else None,
                    "vehicle": driver.vehicle_type if driver else None,
                    "community": driver.community if driver else None})
    return out


def refreshed_language(db, session_id):
    s = db.get(CallSession, session_id)
    return s.language if s else "english"


def _render(db, language: str, xml: str):
    """What she actually hears, and the English for whoever is watching.

    Two different things, and the panel used to conflate them. A <Play> is a
    recording in her language, so she hears the translated wording -- which is
    on screen only if we look up the clip's key. A <Say> is the provider's
    English voice, so she hears English and there is nothing to translate.

    Rendering them the same way is what made the coverage number abstract: on
    this screen you can see, line by line, which parts of the call reached her
    in her own language and which did not.
    """
    import re
    from ..models import Phrase

    heard, english = [], []
    for say, url in re.findall(r"<Say>(.*?)</Say>|<Play url=\"(.*?)\"", xml, re.S):
        if say:
            heard.append(say.strip())
            english.append(say.strip())
            continue
        key = url.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        row = (db.query(Phrase)
                 .filter(Phrase.language == language, Phrase.key == key).first())
        heard.append((row.translated_text if row and row.translated_text
                      else "[recording: {}]".format(key)))
        english.append((row.source_text if row and row.source_text
                        else "[recording: {}]".format(key)))

    spoken = " ".join(h for h in heard if h)
    gloss = " ".join(e for e in english if e)
    return spoken, ("" if gloss == spoken else gloss)


def _options(xml: str):
    if "<GetDigits" not in xml:
        return []
    return ["1", "2", "9"]
