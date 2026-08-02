"""The scheduler: the loop this whole product is named for.

Deliberately an endpoint driven by a cron rather than an in-process timer. A
free web dyno sleeps, and a background thread that stops when the dyno idles is
a scheduler that quietly does nothing — which is worse than not having one,
because it looks like it works.
"""
import datetime as dt
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .. import services
from ..db import get_db
from ..models import Contact, Patient, User
from ..security import current_user

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


def _authorise(cron_token: Optional[str], authorization: str, db: Session) -> str:
    """Either a signed-in worker, or the cron's shared secret."""
    expected = os.getenv("CRON_TOKEN", "")
    if expected and cron_token == expected:
        return "cron"
    if authorization.lower().startswith("bearer "):
        from ..security import decode_token
        claims = decode_token(authorization.split(" ", 1)[1].strip())
        if claims:
            return claims["sub"]
    raise HTTPException(401, "Signed-in worker or cron token required.")


@router.post("/run-due")
def run_due(db: Session = Depends(get_db),
            x_cron_token: str = Header(default=""),
            authorization: str = Header(default="")):
    """Place every call that is due today. Safe to run repeatedly."""
    actor = _authorise(x_cron_token, authorization, db)
    result = services.run_due_contacts(db)
    db.commit()
    return {"ran_by": actor, "at": dt.datetime.utcnow(), **result}


@router.get("/due")
def list_due(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = []
    for contact in services.due_contacts(db):
        patient = db.get(Patient, contact.patient_id)
        if not patient:
            continue
        rows.append({"contact_id": contact.id, "patient_id": patient.id,
                     "name": patient.name, "community": patient.community,
                     "week": contact.week, "due_date": contact.due_date,
                     "attempts": contact.attempts,
                     "include_diet": contact.include_diet})
    return {"due": rows, "count": len(rows)}


@router.get("/schedule/{patient_id}")
def schedule(patient_id: str, db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    rows = (db.query(Contact)
              .filter(Contact.patient_id == patient_id)
              .order_by(Contact.due_date).all())
    today = dt.date.today()
    return {"contacts": [{
        "id": c.id, "week": c.week, "due_date": c.due_date, "status": c.status,
        "attempts": c.attempts, "include_diet": c.include_diet,
        "overdue": c.status == "pending" and c.due_date < today,
    } for c in rows]}
