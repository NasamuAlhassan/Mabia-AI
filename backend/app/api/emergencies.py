"""Emergencies: validation, dispatch, and the outcome that closes the loop."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import services
from ..db import get_db
from ..models import Dispatch, Emergency, Patient, User
from ..security import current_user, patient_in_reach

router = APIRouter(prefix="/api/emergencies", tags=["emergencies"])


@router.get("")
def list_emergencies(db: Session = Depends(get_db),
                     user: User = Depends(current_user),
                     open_only: bool = True):
    # The same rule as patient_in_reach, not a narrower one. Filtering on
    # facility alone hid REDs for the worker's OWN assigned patients whenever
    # the patient sat at another facility (a referral) or at none -- so a case
    # she is responsible for never appeared on the list she works from, while
    # being perfectly openable by its URL.
    query = (db.query(Emergency).outerjoin(Patient, Emergency.patient_id == Patient.id)
               .filter(or_(Patient.assigned_cho_id == user.id,
                           Patient.facility_id == user.facility_id
                           if user.facility_id else False,
                           Patient.assigned_cho_id.is_(None)
                           & Patient.facility_id.is_(None))))
    if open_only:
        query = query.filter(Emergency.status.notin_(["closed", "cancelled"]))
    return [_view(db, e) for e in query.order_by(Emergency.created_at.desc()).all()]


def _reachable(db, emergency_id: str, user: User) -> Emergency:
    """The emergency, if this worker has any business with it.

    Locking /api/circle was not enough: this endpoint reads the same care
    circle through _payer, and /validate fires the family SMS that was
    deliberately moved behind a clinician. An outsider could therefore read a
    household's family names and numbers, and put "she needs to go to the
    health centre now" on their handsets, without ever touching the endpoint
    that was secured.
    """
    emergency = db.get(Emergency, emergency_id)
    if not emergency:
        raise HTTPException(404, "No such emergency")
    patient_in_reach(db, emergency.patient_id, user)
    return emergency


@router.get("/{emergency_id}")
def get_emergency(emergency_id: str, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    return _view(db, _reachable(db, emergency_id, user))


@router.post("/{emergency_id}/validate")
def validate(emergency_id: str, db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    """The human gate. Dispatch begins only after a person confirms."""
    emergency = _reachable(db, emergency_id, user)
    # Idempotent: a second tap on a slow link returns the same state rather
    # than dispatching a second vehicle.
    if emergency.status != "pending_validation":
        return _view(db, emergency)
    services.validate_emergency(db, emergency, user)
    services.offer_next_driver(db, emergency)
    db.commit()
    return _view(db, emergency)


class OutcomeIn(BaseModel):
    outcome: str          # care_received | not_reached | refused | other
    note: str = ""


@router.post("/{emergency_id}/outcome")
def record_outcome(emergency_id: str, body: OutcomeIn,
                   db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    """Proof of care, not just advice. This is the only thing that clears a RED."""
    emergency = _reachable(db, emergency_id, user)

    # A brand-new RED could be retired with two taps, before anyone confirmed
    # it, before a driver was called, before the family was told -- and the
    # patient screen showed the form for every status except closed, so the
    # button was right there. An outcome is a record of what happened, and
    # nothing has happened yet on a case awaiting confirmation.
    if emergency.status == "pending_validation":
        raise HTTPException(
            409, "Confirm this emergency first. There is no outcome to record "
                 "until something has been done about it.")
    if emergency.status in ("closed", "cancelled"):
        # Recording twice silently overwrote the first answer.
        raise HTTPException(409, "This case is already closed.")

    services.close_emergency(db, emergency, user, body.outcome, body.note)
    db.commit()
    return _view(db, emergency)


class LocationIn(BaseModel):
    note: str


@router.post("/dispatches/{dispatch_id}/location")
def log_location(dispatch_id: str, body: LocationIn,
                 db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    dispatch = db.get(Dispatch, dispatch_id)
    if not dispatch:
        raise HTTPException(404, "No such dispatch")
    # Reached through its emergency, so the same scoping applies.
    _reachable(db, dispatch.emergency_id, user)
    services.log_driver_location(db, dispatch, body.note)
    db.commit()
    return {"ok": True, "location_note": dispatch.location_note,
            "at": dispatch.location_at}


@router.post("/dispatches/{dispatch_id}/respond")
def respond(dispatch_id: str, accepted: bool, db: Session = Depends(get_db),
            user: User = Depends(current_user)):
    """Manual override, for when the CHO reaches a driver another way."""
    dispatch = db.get(Dispatch, dispatch_id)
    if not dispatch:
        raise HTTPException(404, "No such dispatch")
    _reachable(db, dispatch.emergency_id, user)
    services.driver_responded(db, dispatch, accepted)
    db.commit()
    return {"ok": True, "status": dispatch.status}


@router.post("/{emergency_id}/next-driver")
def next_driver(emergency_id: str, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    emergency = _reachable(db, emergency_id, user)
    dispatch = services.offer_next_driver(db, emergency)
    db.commit()
    return {"ok": dispatch is not None,
            "status": emergency.status,
            "note": ("Queue exhausted — the CHO has been alerted to assign "
                     "manually." if dispatch is None else "Driver called.")}


def _payer(db: Session, patient_id: str):
    """Who settles the bill, surfaced where the decision is made.

    This role was collected at enrolment and then read by nothing. Money is the
    third delay -- a woman can be detected, confirmed, driven to the facility
    and still not treated -- and "is she insured, and who is bringing the money"
    is the question the facility asks on arrival. Answering it before she
    arrives is most of what this field was for.
    """
    from ..models import CareCircleMember

    row = (db.query(CareCircleMember)
             .filter(CareCircleMember.patient_id == patient_id,
                     CareCircleMember.role == "payer").first())
    if row is None:
        return {"known": False,
                "note": "No one is recorded as paying. Ask before she travels."}
    return {"known": True, "name": row.name, "phone": row.phone,
            "nhis": row.detail, "confirmed": bool(row.confirmed),
            "note": None if row.detail else
                    "No NHIS number recorded — she may be asked to pay cash."}


def _view(db: Session, emergency: Emergency):
    patient = db.get(Patient, emergency.patient_id)
    return {
        "id": emergency.id, "status": emergency.status,
        "reasons": emergency.reason_codes or [], "source": emergency.source,
        "created_at": emergency.created_at,
        "validated_at": emergency.validated_at,
        "facility_notified_at": emergency.facility_notified_at,
        "outcome": emergency.outcome, "outcome_note": emergency.outcome_note,
        "alert_failed": bool(emergency.alert_failed),
        "alert_error": emergency.alert_error,
        "patient": {"id": patient.id, "name": patient.name,
                    "phone": patient.phone, "community": patient.community,
                    "language": patient.language} if patient else None,
        "payer": _payer(db, emergency.patient_id),
        "dispatches": [{
            "id": d.id, "status": d.status, "position": d.position,
            "offered_at": d.offered_at, "responded_at": d.responded_at,
            "location_note": d.location_note, "location_at": d.location_at,
            "driver": {"id": d.driver.id, "name": d.driver.name,
                       "phone": d.driver.phone, "community": d.driver.community,
                       "vehicle": d.driver.vehicle_type} if d.driver else None}
            for d in sorted(emergency.dispatches, key=lambda x: x.position or 0)],
    }
