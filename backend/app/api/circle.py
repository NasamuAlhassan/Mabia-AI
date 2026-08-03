"""The care circle: who else has to be reached for her to get to care."""
import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CareCircleMember, Patient, User
from ..security import current_user

router = APIRouter(prefix="/api/circle", tags=["care circle"])

# Role -> what it is for, and which delay it addresses. Shown in the interface
# so a worker filling this in understands why she is being asked.
ROLES = [
    {"role": "decision_maker", "label": "Decision-maker",
     "why": "Who decides whether she goes to the health centre.",
     "delay": "Delay 1 — deciding to seek care"},
    {"role": "driver", "label": "Driver",
     "why": "Transport arranged in advance, from her own community.",
     "delay": "Delay 2 — reaching care"},
    {"role": "payer", "label": "Payer",
     "why": "NHIS number, or who pays if there is no cover.",
     "delay": "The cost barrier"},
    {"role": "emergency", "label": "Emergency contact",
     "why": "Who is called when she cannot be reached.",
     "delay": "When her own phone does not answer"},
]


@router.get("/roles")
def roles():
    return {"roles": ROLES}


@router.get("/{patient_id}")
def get_circle(patient_id: str, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    if db.get(Patient, patient_id) is None:
        raise HTTPException(404, "No such patient")
    rows = {m.role: m for m in db.query(CareCircleMember).filter(
        CareCircleMember.patient_id == patient_id).all()}
    out = []
    for spec in ROLES:
        member = rows.get(spec["role"])
        out.append({**spec,
                    "id": member.id if member else None,
                    "name": member.name if member else None,
                    "phone": member.phone if member else None,
                    "detail": member.detail if member else None,
                    "confirmed": bool(member.confirmed) if member else False})
    missing = [r["label"] for r in out if not r["name"]]
    return {"patient_id": patient_id, "members": out, "missing": missing,
            "complete": not missing}


class MemberIn(BaseModel):
    role: str
    name: str = Field(min_length=1, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=20)
    detail: Optional[str] = Field(default=None, max_length=120)
    confirmed: bool = False


@router.put("/{patient_id}")
def upsert(patient_id: str, body: MemberIn, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    if db.get(Patient, patient_id) is None:
        raise HTTPException(404, "No such patient")
    if body.role not in {r["role"] for r in ROLES}:
        raise HTTPException(422, "Unknown role")

    member = (db.query(CareCircleMember)
                .filter(CareCircleMember.patient_id == patient_id,
                        CareCircleMember.role == body.role).first())
    if member is None:
        member = CareCircleMember(patient_id=patient_id, role=body.role,
                                  name=body.name)
        db.add(member)
    member.name = body.name.strip()
    member.phone = (body.phone or "").strip() or None
    member.detail = (body.detail or "").strip() or None
    if body.confirmed and not member.confirmed:
        member.confirmed_at = dt.datetime.utcnow()
    member.confirmed = body.confirmed
    db.commit()
    return get_circle(patient_id, db, user)
