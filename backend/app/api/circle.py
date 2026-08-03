"""The care circle: who else has to be reached for her to get to care."""
import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import events
from ..db import get_db
from ..models import CareCircleMember, Driver, Patient, User
from ..security import current_user, patient_in_reach
from .. import phones

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
    patient_in_reach(db, patient_id, user)
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
    # A name with no number is not a plan. The two roles that get contacted in
    # an emergency must carry a phone before the circle counts as complete;
    # reporting "complete" for four names and no way to ring any of them is the
    # kind of green tick that gets someone killed.
    must_be_reachable = {"decision_maker", "emergency"}
    missing = [r["label"] for r in out if not r["name"]]
    unreachable = [r["label"] for r in out
                   if r["name"] and not r["phone"]
                   and r["role"] in must_be_reachable]
    return {"patient_id": patient_id, "members": out, "missing": missing,
            "unreachable": unreachable,
            "complete": not missing and not unreachable}


class MemberIn(BaseModel):
    role: str
    name: str = Field(min_length=1, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=20)
    detail: Optional[str] = Field(default=None, max_length=120)
    confirmed: bool = False


@router.put("/{patient_id}")
def upsert(patient_id: str, body: MemberIn, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    patient_in_reach(db, patient_id, user)
    if body.role not in {r["role"] for r in ROLES}:
        raise HTTPException(422, "Unknown role")

    member = (db.query(CareCircleMember)
                .filter(CareCircleMember.patient_id == patient_id,
                        CareCircleMember.role == body.role).first())
    if member is None:
        member = CareCircleMember(patient_id=patient_id, role=body.role,
                                  name=body.name)
        db.add(member)
    # What it was, before it becomes what it is. This table is where an
    # emergency SMS gets its destination, so a silent overwrite of a phone
    # number is a safety event and has to leave a trace -- it was the only
    # clinical table in the system that never touched the event log.
    was = {"name": member.name, "phone": member.phone, "detail": member.detail}

    member.name = body.name.strip()
    member.phone = phones.normalise(body.phone)
    member.detail = (body.detail or "").strip() or None
    if body.confirmed and not member.confirmed:
        member.confirmed_at = dt.datetime.utcnow()
    member.confirmed = body.confirmed
    if body.role == "driver":
        _ensure_driver(db, patient_id, member, was.get("phone"))

    now = {"name": member.name, "phone": member.phone, "detail": member.detail}
    if now != was:
        events.append(db, patient_id=patient_id, actor_id=user.id,
                      event_type="care_circle_set",
                      payload={"role": body.role, "was": was, "now": now,
                               "confirmed": bool(member.confirmed)})
    db.commit()
    return get_circle(patient_id, db, user)


VEHICLES = ("ambulance", "car", "motorking", "motorbike", "bicycle", "tricycle")


def _vehicle_from(detail: Optional[str]) -> str:
    """A known vehicle if the note names one, otherwise the commonest."""
    text = (detail or "").lower()
    for vehicle in VEHICLES:
        if vehicle in text:
            return vehicle
    if "moto" in text or "okada" in text:
        return "motorbike"
    return "motorking"


def _ensure_driver(db: Session, patient_id: str, member: CareCircleMember,
                   previous_phone: Optional[str] = None) -> None:
    """Put the driver she named into the roster the cascade actually reads.

    Naming a driver here previously wrote a row nothing dialled: rank_drivers
    only ever sorts the Driver table, so a man who was not already registered
    could be recorded as her transport plan and never be rung. The field was
    decorative in exactly the emergency it exists for.
    """
    # Correcting a mistyped number used to leave the typo behind as a
    # permanent, always-available driver. There is no delete route here, and
    # rank_drivers falls back to the whole table when a community has nobody --
    # so a number that never belonged to a driver was dialled during other
    # households' emergencies, ahead of the real roster. A row this endpoint
    # created and nobody now names is retired.
    if previous_phone and previous_phone != member.phone:
        stale = (db.query(Driver)
                   .filter(Driver.phone == previous_phone,
                           Driver.source == "care_circle").first())
        if stale is not None and not _named_by_anyone(db, previous_phone, member):
            stale.available = False

    if not member.phone:
        return

    patient = db.get(Patient, patient_id)
    existing = db.query(Driver).filter(Driver.phone == member.phone).first()
    if existing is not None:
        # Already in the roster, and nothing here may edit him. Flipping
        # available back to True was the worst of it: a driver who had marked
        # himself off duty was put back on call by any worker saving his number
        # on any patient's form, and would then be rung for an emergency he had
        # said he could not take.
        return
    db.add(Driver(
        name=member.name,
        phone=member.phone,
        community=(patient.community if patient else None) or "unknown",
        # detail is a free-text relationship field on every other role, so
        # taking it raw wrote "his brother's motorbike" in as a vehicle type.
        vehicle_type=_vehicle_from(member.detail),
        available=True,
        # Marked as coming from a household form rather than the roster, so it
        # can be told apart from a driver who registered with the programme --
        # and so a correction can retire the row it replaced.
        source="care_circle",
    ))


def _named_by_anyone(db: Session, phone: str,
                     ignoring: Optional[CareCircleMember] = None) -> bool:
    """Whether any OTHER household still names this number as its driver.

    The row being edited is excluded explicitly rather than relied upon to have
    been flushed: this session runs with autoflush off, so a query here still
    sees the number as it was before the correction, and the check answered
    "yes, someone still names it" about the very edit that stopped naming it.
    """
    query = db.query(CareCircleMember).filter(
        CareCircleMember.role == "driver",
        CareCircleMember.phone == phone)
    if ignoring is not None and ignoring.id is not None:
        query = query.filter(CareCircleMember.id != ignoring.id)
    return query.count() > 0
