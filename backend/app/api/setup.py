"""The Setup screen's API.

This is what makes the site usable by someone who will never open a terminal:
credentials, the voice number, and the phone to test against all go in here,
and the two test buttons prove the whole chain end to end.
"""
from typing import Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import settings_store as store
from ..db import get_db
from ..models import User
from ..security import current_user
from ..telephony import service as tel

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SettingsIn(BaseModel):
    values: Dict[str, str]


@router.get("")
def read_settings(db: Session = Depends(get_db)):
    return {"fields": store.public_view(db), "readiness": store.readiness(db)}


@router.put("")
def write_settings(body: SettingsIn, db: Session = Depends(get_db)):
    store.set_many(db, body.values)
    db.commit()
    return {"fields": store.public_view(db), "readiness": store.readiness(db)}


@router.post("/test-call")
def do_test_call(db: Session = Depends(get_db)):
    """The fifteen-minute check: does a real handset actually ring?"""
    session, result = tel.test_call(db)
    db.commit()
    return {"ok": result.ok, "error": result.error,
            "session_id": session.id if session else None,
            "provider": store.get(db, "telephony_provider"),
            "hint": _hint(db, result)}


@router.post("/test-sms")
def do_test_sms(db: Session = Depends(get_db)):
    message, result = tel.test_sms(db)
    db.commit()
    return {"ok": result.ok, "error": result.error,
            "message_id": message.id if message else None,
            "provider": store.get(db, "telephony_provider")}


def _hint(db: Session, result) -> str:
    if result.ok and store.get(db, "telephony_provider") == store.SIMULATOR:
        return ("Simulator: open the Simulator screen and the handset will be "
                "ringing there.")
    if result.ok and not store.get(db, "public_base_url"):
        return ("The call was placed, but no public callback URL is set, so it "
                "will connect and then fall silent. Set one in Setup.")
    if result.ok:
        return "Placed. Your handset should ring within a few seconds."
    return ""
