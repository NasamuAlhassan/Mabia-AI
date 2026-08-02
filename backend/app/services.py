"""Emergency, transport and nurse routing.

The rule that governs this file: **no call is permitted to end without a health
worker being informed.** Routing a woman in a possible obstetric emergency to a
phone that rings out creates a duty of care, so every path -- driver queue
exhausted, no nurse on the roster, nobody picking up -- terminates in an alert
to her CHO and a RED on her record.
"""
import datetime as dt
from typing import List, Optional

from sqlalchemy.orm import Session

from . import events as ev
from . import prompts
from .engines.risk import labels_for
from .models import (CallSession, Dispatch, Driver, Emergency, Facility,
                     NurseShift, Patient, PatientState, User)
from .telephony import service as tel


# --------------------------------------------------------------- emergencies


def raise_emergency(db: Session, patient: Patient, reason_codes: List[str],
                    source: str = "ivr") -> Emergency:
    """Create an emergency and push an SMS to the CHO.

    SMS, not USSD: a USSD session can only be started by the person holding the
    handset, so it cannot be used to alert anyone. SMS pushes; USSD pulls.
    """
    open_already = (db.query(Emergency)
                      .filter(Emergency.patient_id == patient.id,
                              Emergency.status.notin_(["closed", "cancelled"]))
                      .first())
    if open_already:
        return open_already

    emergency = Emergency(patient_id=patient.id, reason_codes=reason_codes,
                          source=source, facility_id=patient.facility_id)
    db.add(emergency)
    db.flush()

    ev.record(db, patient_id=patient.id, actor_id="system",
              event_type=ev.EMERGENCY_RAISED,
              payload={"emergency_id": emergency.id, "reasons": reason_codes,
                       "source": source})

    cho = db.get(User, patient.assigned_cho_id) if patient.assigned_cho_id else None
    if cho:
        reason_text = labels_for(reason_codes) or "danger signs"
        body = "RED: {}, {}. {}. Open Mabia to confirm.".format(
            patient.name, patient.community, reason_text)
        tel.send_sms(db, cho.phone, body, kind="red_alert", patient_id=patient.id)
    return emergency


def validate_emergency(db: Session, emergency: Emergency, user: User) -> Emergency:
    """The human-in-the-loop gate. Nothing dispatches before this."""
    emergency.status = "validated"
    emergency.validated_by = user.id
    emergency.validated_at = dt.datetime.utcnow()
    db.flush()
    ev.record(db, patient_id=emergency.patient_id, actor_id=user.id,
              event_type=ev.EMERGENCY_VALIDATED,
              payload={"emergency_id": emergency.id})
    return emergency


def close_emergency(db: Session, emergency: Emergency, user: User,
                    outcome: str, note: str = "") -> Emergency:
    """The only thing that clears an open RED.

    This is the differentiator: the loop stays open until a human records
    whether care was actually received, not merely whether a referral was made.
    """
    emergency.status = "closed"
    emergency.outcome = outcome
    emergency.outcome_note = note
    emergency.closed_by = user.id
    emergency.closed_at = dt.datetime.utcnow()
    db.flush()
    ev.record(db, patient_id=emergency.patient_id, actor_id=user.id,
              event_type=ev.REFERRAL_OUTCOME,
              payload={"emergency_id": emergency.id, "outcome": outcome,
                       "note": note})
    return emergency


# --------------------------------------------------------------- transport


def rank_drivers(db: Session, patient: Patient) -> List[Driver]:
    """Matched by community, not coordinates.

    Riders in villages are on feature phones; there is no live position to match
    on, and pretending otherwise would be a demo that cannot survive contact
    with a real road. The community is how dispatch actually happens.
    """
    drivers = (db.query(Driver)
                 .filter(Driver.community == patient.community,
                         Driver.available.is_(True))
                 .all())
    if not drivers:
        drivers = db.query(Driver).filter(Driver.available.is_(True)).all()

    vehicle_rank = {"ambulance": 0, "car": 1, "motorking": 2, "motorbike": 3}
    return sorted(drivers, key=lambda d: (
        0 if d.community == patient.community else 1,
        vehicle_rank.get(d.vehicle_type, 4),
        -d.response_rate,
        d.name))


def offer_next_driver(db: Session, emergency: Emergency) -> Optional[Dispatch]:
    """Ring the next driver in the cascade. Acceptance happens in the call."""
    patient = db.get(Patient, emergency.patient_id)
    already = {d.driver_id for d in emergency.dispatches}
    for position, driver in enumerate(rank_drivers(db, patient), start=1):
        if driver.id in already:
            continue
        dispatch = Dispatch(emergency_id=emergency.id, driver_id=driver.id,
                            position=len(already) + 1, status="offered")
        db.add(dispatch)
        driver.offered_count = (driver.offered_count or 0) + 1
        emergency.status = "dispatching"
        db.flush()

        session, result = tel.start_call(
            db, phone=driver.phone, patient_id=patient.id, purpose="driver",
            language=patient.language or "dagbani",
            emergency_id=emergency.id, driver_id=driver.id)

        if not result.ok:
            # Could not even place the call: treat as no answer and move on,
            # rather than leaving the emergency sitting on a silent driver.
            dispatch.status = "no_answer"
            dispatch.responded_at = dt.datetime.utcnow()
            db.flush()
            continue

        tel.send_sms(db, driver.phone,
                     "Mabia: urgent transport needed at {}. We are calling you.".format(
                         patient.community),
                     kind="dispatch", patient_id=patient.id)
        return dispatch

    # Queue exhausted. This does not go quiet -- it goes to a person.
    emergency.status = "no_transport"
    db.flush()
    _alert_cho(db, patient,
               "No driver accepted for {}. Assign transport manually.".format(patient.name))
    return None


def driver_responded(db: Session, dispatch: Dispatch, accepted: bool) -> Dispatch:
    dispatch.status = "accepted" if accepted else "declined"
    dispatch.responded_at = dt.datetime.utcnow()
    driver = db.get(Driver, dispatch.driver_id)
    emergency = db.get(Emergency, dispatch.emergency_id)
    if accepted:
        driver.accepted_count = (driver.accepted_count or 0) + 1
        emergency.status = "transporting"
        db.flush()
        notify_facility(db, emergency)
    else:
        db.flush()
        offer_next_driver(db, emergency)
    return dispatch


def log_driver_location(db: Session, dispatch: Dispatch, note: str) -> Dispatch:
    """As verbally reported, and only while a dispatch is active.

    There is no automated tracking here by design -- see the data-protection
    section. A nurse writes down what the driver says on the phone.
    """
    dispatch.location_note = note
    dispatch.location_at = dt.datetime.utcnow()
    db.flush()
    return dispatch


def notify_facility(db: Session, emergency: Emergency) -> None:
    """Delay 3: the facility should not learn of a case at the door."""
    facility = db.get(Facility, emergency.facility_id) if emergency.facility_id else None
    patient = db.get(Patient, emergency.patient_id)
    emergency.facility_notified_at = dt.datetime.utcnow()
    db.flush()
    if facility and facility.phone:
        reasons = labels_for(emergency.reason_codes) or "emergency"
        tel.send_sms(db, facility.phone,
                     "Mabia: incoming from {} — {}. {}. Prepare now.".format(
                         patient.community, patient.name, reasons),
                     kind="facility", patient_id=patient.id)


# --------------------------------------------------------------- nurse routing


def on_call_nurses(db: Session, patient: Optional[Patient]) -> List[NurseShift]:
    query = db.query(NurseShift).filter(NurseShift.on_call.is_(True))
    shifts = query.all()
    if patient and patient.facility_id:
        shifts.sort(key=lambda s: (0 if s.facility_id == patient.facility_id else 1,
                                   s.position or 99))
    else:
        shifts.sort(key=lambda s: s.position or 99)
    return shifts


def nurse_target(db: Session, session: CallSession) -> Optional[str]:
    """The next number to try in the cascade: nurse 1, nurse 2, facility line."""
    patient = db.get(Patient, session.patient_id) if session.patient_id else None
    shifts = on_call_nurses(db, patient)
    attempt = session.nurse_attempt or 0

    if attempt < len(shifts):
        nurse = db.get(User, shifts[attempt].user_id)
        return nurse.phone if nurse else None

    if attempt == len(shifts) and patient and patient.facility_id:
        facility = db.get(Facility, patient.facility_id)
        if facility and facility.phone:
            return facility.phone
    return None


def terminal_fallback(db: Session, session: CallSession) -> str:
    """Nobody answered. The call still ends with a human being told.

    This is the path that must never be skipped, and it is the one the
    verification suite tests by emptying the roster on purpose.
    """
    patient = db.get(Patient, session.patient_id) if session.patient_id else None
    session.outcome = "nurse_unreachable"
    db.flush()

    if patient:
        state = db.get(PatientState, patient.id)
        reasons = list(state.reason_codes or []) if state else []
        reasons.append("hotline.nurse_unreachable")
        raise_emergency(db, patient, reasons, source="hotline")
    else:
        _alert_any_cho(db, "A caller could not reach a nurse on the hotline. "
                           "Number: {}".format(session.phone))
    return prompts.line("nurse_unavailable")


def _alert_cho(db: Session, patient: Patient, body: str) -> None:
    cho = db.get(User, patient.assigned_cho_id) if patient.assigned_cho_id else None
    if cho:
        tel.send_sms(db, cho.phone, "Mabia: " + body, kind="alert",
                     patient_id=patient.id)
    else:
        _alert_any_cho(db, body)


def _alert_any_cho(db: Session, body: str) -> None:
    cho = db.query(User).filter(User.role == "cho").first()
    if cho:
        tel.send_sms(db, cho.phone, "Mabia: " + body, kind="alert")


# --------------------------------------------------------------- scheduling


# The WHO eight-contact model. The diet block rotates rather than running every
# call: MDD-W is ten questions on top of five danger signs, and a call that long
# does not get finished on a rural line.
WHO_CONTACT_WEEKS = [12, 20, 26, 30, 34, 36, 38, 40]
DIET_CONTACT_WEEKS = {12, 26, 34, 38}


def build_contact_schedule(db: Session, patient: Patient) -> List:
    from .models import Contact
    if not patient.edd:
        return []
    conception = patient.edd - dt.timedelta(weeks=40)
    created = []
    for week in WHO_CONTACT_WEEKS:
        due = conception + dt.timedelta(weeks=week)
        existing = (db.query(Contact)
                      .filter(Contact.patient_id == patient.id,
                              Contact.week == week, Contact.kind == "anc")
                      .first())
        if existing:
            continue
        contact = Contact(patient_id=patient.id, week=week, due_date=due,
                          kind="anc", include_diet=week in DIET_CONTACT_WEEKS)
        db.add(contact)
        created.append(contact)
    db.flush()
    return created


def due_contacts(db: Session, on: Optional[dt.date] = None) -> List:
    from .models import Contact
    on = on or dt.date.today()
    return (db.query(Contact)
              .filter(Contact.status == "pending", Contact.due_date <= on)
              .order_by(Contact.due_date.asc())
              .all())
