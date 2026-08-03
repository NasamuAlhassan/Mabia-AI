"""The facility view: what is coming in, and confirming that it arrived."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Emergency, Facility, Patient, User
from ..security import current_user, patient_in_reach

router = APIRouter(prefix="/api/facility", tags=["facility"])


@router.get("/inbound")
def inbound(db: Session = Depends(get_db), user: User = Depends(current_user)):
    query = (db.query(Emergency)
               .filter(Emergency.status.in_(["validated", "dispatching",
                                             "transporting", "no_transport"])))
    if user.facility_id:
        query = query.filter(Emergency.facility_id == user.facility_id)
    rows = []
    for emergency in query.order_by(Emergency.created_at.desc()).all():
        patient = db.get(Patient, emergency.patient_id)
        accepted = [d for d in emergency.dispatches if d.status == "accepted"]
        rows.append({
            "id": emergency.id, "status": emergency.status,
            "reasons": emergency.reason_codes or [],
            "created_at": emergency.created_at,
            "notified_at": emergency.facility_notified_at,
            "patient": {"name": patient.name, "community": patient.community,
                        "phone": patient.phone} if patient else None,
            "driver": ({"name": accepted[0].driver.name,
                        "phone": accepted[0].driver.phone,
                        "vehicle": accepted[0].driver.vehicle_type,
                        "location": accepted[0].location_note}
                       if accepted and accepted[0].driver else None)})
    return {"inbound": rows}


@router.post("/{emergency_id}/arrived")
def arrived(emergency_id: str, db: Session = Depends(get_db),
            user: User = Depends(current_user)):
    emergency = db.get(Emergency, emergency_id)
    if not emergency:
        raise HTTPException(404, "No such emergency")
    # The facility receiving her, or the worker responsible for her. Anyone
    # else marking a woman as arrived puts a false end on the one timestamp
    # the Three Delays funnel is measured from.
    if emergency.facility_id and user.facility_id != emergency.facility_id:
        patient_in_reach(db, emergency.patient_id, user)
    emergency.arrived_at = dt.datetime.utcnow()
    emergency.status = "arrived"
    db.commit()
    return {"ok": True, "arrived_at": emergency.arrived_at,
            "note": "The case stays open until a health worker records the "
                    "outcome."}


@router.get("/list")
def facilities(db: Session = Depends(get_db)):
    return [{"id": f.id, "name": f.name, "community": f.community,
             "region": f.region, "phone": f.phone}
            for f in db.query(Facility).order_by(Facility.name).all()]
