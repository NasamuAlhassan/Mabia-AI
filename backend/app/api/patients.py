"""Enrolment and the patient record."""
import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import events as ev
from .. import services
from ..db import get_db
from ..models import Child, Emergency, Event, Patient, PatientState, User
from ..security import current_user

router = APIRouter(prefix="/api/patients", tags=["patients"])


class EnrolIn(BaseModel):
    name: str
    phone: str
    secondary_phone: Optional[str] = None
    language: str = "dagbani"
    community: str
    region: str = "Northern"
    lmp: Optional[dt.date] = None
    edd: Optional[dt.date] = None
    affordability: str = "low"
    taboos: List[str] = []
    # Geography, collected rather than inferred. The risk engine shortens the
    # follow-up window for a symptom that could worsen when she is far from
    # care; without these fields that rule is dead code, which is exactly what
    # it was before.
    minutes_to_facility: Optional[int] = None
    road_condition: str = "fair"
    secondary_name: Optional[str] = None
    consent: bool = False
    facility_id: Optional[str] = None
    danger_signs: List[str] = []
    event_id: Optional[str] = None      # client-generated: makes retries safe
    device_id: str = "web"


@router.post("")
def enrol(body: EnrolIn, db: Session = Depends(get_db),
          user: User = Depends(current_user)):
    if not body.consent:
        raise HTTPException(400, "Consent must be recorded before enrolment.")

    # The retry case, which is the normal case on a bad link: the same
    # enrolment arriving twice must produce one woman, not two. Only the event
    # was de-duplicated before, so the Patient row was inserted every time.
    if body.event_id:
        prior = db.get(Event, body.event_id)
        if prior is not None and prior.patient_id:
            return detail(prior.patient_id, db, user)
    same_phone = (db.query(Patient)
                    .filter(Patient.phone == body.phone.strip(),
                            Patient.status == "active").first())
    if same_phone is not None:
        return detail(same_phone.id, db, user)

    edd = body.edd
    if edd is None and body.lmp is not None:
        edd = body.lmp + dt.timedelta(days=280)

    patient = Patient(
        name=body.name.strip(), phone=body.phone.strip(),
        secondary_phone=body.secondary_phone, language=body.language,
        community=body.community, region=body.region, lmp=body.lmp, edd=edd,
        affordability=body.affordability, taboos=body.taboos,
        minutes_to_facility=body.minutes_to_facility,
        road_condition=body.road_condition,
        consent=True, consent_at=dt.datetime.utcnow(),
        assigned_cho_id=user.id, facility_id=body.facility_id or user.facility_id)
    db.add(patient)
    db.flush()

    ev.append(db, patient_id=patient.id, actor_id=user.id,
              event_type=ev.ENROLMENT, event_id=body.event_id,
              device_id=body.device_id,
              payload={"community": body.community, "language": body.language})
    ev.append(db, patient_id=patient.id, actor_id=user.id,
              event_type=ev.CONSENT_GIVEN, device_id=body.device_id,
              payload={"scope": ["scheduled_calls", "health_record",
                                 "secondary_contact"],
                       "secondary_name": body.secondary_name})
    if body.danger_signs:
        ev.append(db, patient_id=patient.id, actor_id=user.id,
                  event_type=ev.DANGER_SIGNS, device_id=body.device_id,
                  payload={"signs": body.danger_signs, "source": "enrolment"})

    services.build_contact_schedule(db, patient)
    ev.refresh_state(db, patient.id)
    db.commit()
    return detail(patient.id, db, user)


@router.get("")
def list_patients(db: Session = Depends(get_db), user: User = Depends(current_user),
                  community: Optional[str] = None):
    query = db.query(Patient).filter(Patient.status != "closed")
    if community:
        query = query.filter(Patient.community == community)
    return [_summary(db, p) for p in query.order_by(Patient.name).all()]


@router.get("/{patient_id}")
def detail(patient_id: str, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "No such patient")
    state = db.get(PatientState, patient_id)
    history = ev.load(db, patient_id)
    emergencies = (db.query(Emergency)
                     .filter(Emergency.patient_id == patient_id)
                     .order_by(Emergency.created_at.desc()).all())
    return {
        **_summary(db, patient),
        "secondary_phone": patient.secondary_phone,
        "taboos": patient.taboos or [],
        "consent_at": patient.consent_at,
        "children": [{"id": c.id, "name": c.name, "dob": c.dob,
                      "age_months": c.age_months()} for c in patient.children],
        "state": _state(state),
        "events": [{"event_id": e.event_id, "type": e.event_type,
                    "payload": e.payload, "occurred_at": e.occurred_at,
                    "recorded_at": e.recorded_at, "actor": e.actor_id,
                    "device": e.device_id,
                    "clock_offset_seconds": e.clock_offset_seconds}
                   for e in history],
        "emergencies": [{"id": em.id, "status": em.status,
                         "reasons": em.reason_codes, "created_at": em.created_at,
                         "outcome": em.outcome} for em in emergencies],
    }


class ObservationIn(BaseModel):
    signs: List[str] = []
    denied: List[str] = []
    muac_mother: Optional[float] = None
    muac_child: Optional[float] = None
    ifa_adherent: Optional[bool] = None
    note: Optional[str] = None
    occurred_at: Optional[dt.datetime] = None
    event_id: Optional[str] = None
    device_id: str = "web"


@router.post("/{patient_id}/observations")
def record_observation(patient_id: str, body: ObservationIn,
                       db: Session = Depends(get_db),
                       user: User = Depends(current_user)):
    """A household visit. Appends; never overwrites what the call recorded."""
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(404, "No such patient")
    when = body.occurred_at or dt.datetime.utcnow()

    if body.signs or body.denied:
        ev.append(db, patient_id=patient_id, actor_id=user.id,
                  event_type=ev.DANGER_SIGNS, event_id=body.event_id,
                  occurred_at=when, device_id=body.device_id,
                  payload={"signs": body.signs, "denied": body.denied,
                           "source": "visit"})
    if body.muac_mother is not None:
        ev.append(db, patient_id=patient_id, actor_id=user.id,
                  event_type=ev.MUAC, occurred_at=when, device_id=body.device_id,
                  payload={"subject": "mother", "value_cm": body.muac_mother})
    if body.muac_child is not None:
        ev.append(db, patient_id=patient_id, actor_id=user.id,
                  event_type=ev.MUAC, occurred_at=when, device_id=body.device_id,
                  payload={"subject": "child", "value_cm": body.muac_child})
    if body.ifa_adherent is not None:
        ev.append(db, patient_id=patient_id, actor_id=user.id,
                  event_type=ev.IFA, occurred_at=when, device_id=body.device_id,
                  payload={"adherent": body.ifa_adherent})
    if body.note:
        ev.append(db, patient_id=patient_id, actor_id=user.id,
                  event_type=ev.VISIT, occurred_at=when, device_id=body.device_id,
                  payload={"note": body.note})

    state = ev.refresh_state(db, patient_id)
    if state.risk_level == "red" and not state.red_open:
        services.raise_emergency(db, patient, state.reason_codes or [], source="visit")
    db.commit()
    return detail(patient_id, db, user)


def _summary(db: Session, patient: Patient):
    state = db.get(PatientState, patient.id)
    return {"id": patient.id, "name": patient.name, "phone": patient.phone,
            "community": patient.community, "region": patient.region,
            "minutes_to_facility": patient.minutes_to_facility,
            "road_condition": patient.road_condition,
            "language": patient.language, "edd": patient.edd,
            "affordability": patient.affordability, "status": patient.status,
            "risk_level": state.risk_level if state else "green",
            "reason_codes": (state.reason_codes if state else []) or [],
            "red_open": bool(state.red_open) if state else False,
            "last_contact_at": state.last_contact_at if state else None}


def _state(state: Optional[PatientState]):
    if not state:
        return {}
    return {"risk_level": state.risk_level, "reason_codes": state.reason_codes,
            "red_open": state.red_open, "mdd_score": state.mdd_score,
            "mdd_instrument": state.mdd_instrument,
            "mdd_missing": state.mdd_missing_groups,
            "muac_mother": state.muac_mother, "muac_child": state.muac_child,
            "ifa_adherent": state.ifa_adherent,
            "consecutive_unreachable": state.consecutive_unreachable,
            "events_folded": state.events_folded,
            "last_contact_at": state.last_contact_at}
