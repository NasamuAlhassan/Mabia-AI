"""Offline synchronisation.

The contract is one line long: **the server de-duplicates on the client's event
id.** A worker on a failing link can push the same batch as many times as she
likes and the result is identical, which is what makes an unreliable network
survivable rather than merely annoying.
"""
import datetime as dt
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import events as ev
from ..db import get_db
from ..models import Event, Patient, User
from ..security import current_user

router = APIRouter(prefix="/api/sync", tags=["sync"])


class EventIn(BaseModel):
    event_id: str
    patient_id: Optional[str] = None
    event_type: str
    payload: Dict[str, Any] = {}
    occurred_at: dt.datetime
    recorded_at: Optional[dt.datetime] = None
    device_id: str = "web"
    seq: int = 0


class PushIn(BaseModel):
    events: List[EventIn]


def _materialise_enrolment(db: Session, item, user: User) -> Optional[str]:
    """Turn a queued offline enrolment into an actual patient.

    Without this the CHO was told "queued on this device and will sync", the
    badge cleared, the event was stored with no patient_id, and the woman never
    existed. Losing a whole household while reporting success is the worst
    failure this system could have, so it is handled explicitly.
    """
    import datetime as dt2

    from .. import services

    prior = db.get(Event, item.event_id)
    if prior is not None and prior.patient_id:
        return prior.patient_id

    body = item.payload or {}
    phone = (body.get("phone") or "").strip()
    name = (body.get("name") or "").strip()
    if not phone or not name:
        return None

    existing = (db.query(Patient)
                  .filter(Patient.phone == phone,
                          Patient.status == "active").first())
    if existing is not None:
        return existing.id

    edd = body.get("edd")
    if isinstance(edd, str) and edd:
        try:
            edd = dt2.date.fromisoformat(edd[:10])
        except ValueError:
            edd = None
    else:
        edd = None

    patient = Patient(
        name=name, phone=phone,
        secondary_phone=body.get("secondary_phone") or None,
        language=body.get("language") or "dagbani",
        community=body.get("community") or (user.community or "Unknown"),
        region=body.get("region") or "Northern",
        edd=edd,
        affordability=body.get("affordability") or "low",
        taboos=body.get("taboos") or [],
        minutes_to_facility=body.get("minutes_to_facility"),
        road_condition=body.get("road_condition") or "fair",
        consent=bool(body.get("consent")),
        consent_at=dt2.datetime.utcnow() if body.get("consent") else None,
        assigned_cho_id=user.id, facility_id=user.facility_id)
    db.add(patient)
    db.flush()
    services.build_contact_schedule(db, patient)
    return patient.id


@router.post("/push")
def push(body: PushIn, db: Session = Depends(get_db),
         user: User = Depends(current_user)):
    accepted, duplicates, touched, rejected = 0, 0, set(), []
    for item in body.events:
        patient_id = item.patient_id

        if item.event_type == "enrolment" and not patient_id:
            patient_id = _materialise_enrolment(db, item, user)
            if patient_id is None:
                rejected.append({"event_id": item.event_id,
                                 "reason": "enrolment missing name or phone"})
                continue

        # An event for a patient who does not exist used to create a stray
        # PatientState row, inflating every metric denominator.
        if patient_id and db.get(Patient, patient_id) is None:
            rejected.append({"event_id": item.event_id,
                             "reason": "unknown patient"})
            continue

        existed = db.get(Event, item.event_id) is not None
        ev.append(db, patient_id=patient_id, actor_id=user.id,
                  event_type=item.event_type, payload=item.payload,
                  event_id=item.event_id, occurred_at=item.occurred_at,
                  recorded_at=item.recorded_at or item.occurred_at,
                  device_id=item.device_id, seq=item.seq)
        if existed:
            duplicates += 1
        else:
            accepted += 1
        if patient_id:
            touched.add(patient_id)

    # Re-fold once per patient, not once per event: a late batch lands in the
    # right place in history and the projection is rebuilt from the whole log.
    for patient_id in touched:
        ev.refresh_state(db, patient_id)
    db.commit()
    return {"accepted": accepted, "duplicates": duplicates,
            "rejected": rejected, "patients_refolded": len(touched)}


@router.get("/pull")
def pull(since: Optional[dt.datetime] = None, limit: int = 500,
         db: Session = Depends(get_db), user: User = Depends(current_user)):
    query = db.query(Event)
    if since:
        query = query.filter(Event.server_received_at > since)
    rows = query.order_by(Event.server_received_at.asc()).limit(limit).all()
    return {"events": [{"event_id": e.event_id, "patient_id": e.patient_id,
                        "event_type": e.event_type, "payload": e.payload,
                        "occurred_at": e.occurred_at,
                        "recorded_at": e.recorded_at,
                        "server_received_at": e.server_received_at,
                        "device_id": e.device_id, "seq": e.seq} for e in rows],
            "count": len(rows),
            "cursor": rows[-1].server_received_at if rows else since}
