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


def _failed(message) -> bool:
    """Whether an SMS we tried to send did not go.

    send_sms returns the Message ROW, whose field is `status`. The first
    attempt at this guard tested `getattr(message, "ok", True)` -- an attribute
    the row does not have -- so it was always True and the whole failure branch
    was unreachable. The test guarding it stubbed a fake object carrying `ok`,
    a shape the real function never returns, so it passed against dead code.
    Every alert-failure surface in this file depended on that branch.
    """
    return getattr(message, "status", None) == "failed"


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
        # She already has an emergency open -- but she has just reported
        # something new. Returning silently here meant a woman who reported
        # bleeding on a follow-up call generated no alert at all, because an
        # open RED forces every later classification to RED. Merge the new
        # reasons in and tell the CHO what changed.
        known = set(open_already.reason_codes or [])
        fresh = [c for c in reason_codes if c not in known and c != "emergency.open"]
        if fresh:
            open_already.reason_codes = list(known | set(fresh))
            db.flush()
            ev.record(db, patient_id=patient.id, actor_id="system",
                      event_type=ev.EMERGENCY_RAISED,
                      payload={"emergency_id": open_already.id,
                               "reasons": fresh, "escalation": True})
            # A woman reporting bleeding on top of an open case is the
            # highest-acuity event this system handles, and this was the one
            # branch with neither a failure check nor a fallback when no worker
            # is assigned. The fresh-RED branch below has both.
            body = "WORSE: {}, {}. Now also {}.".format(
                patient.name, patient.community, labels_for(fresh))
            cho = (db.get(User, patient.assigned_cho_id)
                   if patient.assigned_cho_id else None)
            if cho is None:
                _alert_any_cho(db, body)
                open_already.alert_failed = True
                open_already.alert_error = (
                    "No health worker is assigned to this patient.")
            else:
                sent = tel.send_sms(db, cho.phone, body, kind="red_alert",
                                    patient_id=patient.id)
                if _failed(sent):
                    open_already.alert_failed = True
                    open_already.alert_error = (sent.error or "")[:200]
            db.flush()
        return open_already

    emergency = Emergency(patient_id=patient.id, reason_codes=reason_codes,
                          source=source, facility_id=patient.facility_id)
    db.add(emergency)
    db.flush()

    ev.record(db, patient_id=patient.id, actor_id="system",
              event_type=ev.EMERGENCY_RAISED,
              payload={"emergency_id": emergency.id, "reasons": reason_codes,
                       "source": source})

    reason_text = labels_for(reason_codes) or "danger signs"
    body = "RED: {}, {}. {}. Open Mabia to confirm.".format(
        patient.name, patient.community, reason_text)
    cho = db.get(User, patient.assigned_cho_id) if patient.assigned_cho_id else None
    if cho is None:
        # No assigned worker, or her account is gone. _alert_cho already falls
        # back to any worker on duty; the RED path -- the one that matters most
        # -- had no else at all, so a danger sign for an unassigned household
        # reached nobody and the emergency sat waiting for a confirmation
        # nobody had been asked for.
        _alert_any_cho(db, body)
        emergency.alert_failed = True
        emergency.alert_error = "No health worker is assigned to this patient."
    if cho:
        sent = tel.send_sms(db, cho.phone, body, kind="red_alert",
                            patient_id=patient.id)
        # Nobody looked at this result. A provider that refuses -- no key, a
        # rotated key, quota exhausted, an account not enabled for live SMS --
        # produced an emergency that read everywhere as though the health
        # worker had been told, waiting for a confirmation she was never asked
        # for. This file opens by saying no call may end without a health
        # worker being informed; that rule needs to know when it failed.
        if _failed(sent):
            emergency.alert_failed = True
            emergency.alert_error = (sent.error or "")[:200]
            ev.record(db, patient_id=patient.id, actor_id="system",
                      event_type=ev.CALL_ATTEMPTED,
                      payload={"outcome": "alert_failed",
                               "channel": "sms", "to": cho.phone,
                               "error": emergency.alert_error,
                               "emergency_id": emergency.id})

    # The family is NOT told yet. validate_emergency is documented as the
    # human-in-the-loop gate, and that was true of transport and untrue of the
    # people whose reaction matters most: a mis-pressed 1 on the bleeding
    # question sent her husband "Amina needs to go to the health centre now"
    # with no clinician anywhere in the loop. A household that is alarmed twice
    # for nothing stops responding to the third message, which is the one that
    # counts. The health worker is told immediately, because judging this is her
    # job; the family is told the moment she confirms.
    return emergency


def alert_care_circle(db: Session, patient: Patient, reason_text: str,
                      emergency: Optional[Emergency] = None) -> int:
    """Tell the people who actually determine whether she leaves the compound.

    Alerting only the health worker assumes the woman decides for herself and
    that her phone is hers. In much of Northern Ghana neither is reliably true:
    a husband or a mother-in-law often holds the decision, and the handset is
    frequently his. A message that reaches the CHO and nobody else can still end
    with her sitting at home.

    The decision-maker is told plainly and without diagnosis -- that is not ours
    to give over SMS to a third party -- and the message says what to do rather
    than what is wrong.

    Called once, when the emergency opens. A later worsening re-alerts the
    health worker but deliberately not the family: a husband who receives a
    fresh alarming message every time a symptom is updated stops reading them,
    and the one that matters arrives among the ones that did not.
    """
    from .models import CareCircleMember

    members = (db.query(CareCircleMember)
                 .filter(CareCircleMember.patient_id == patient.id,
                         CareCircleMember.role.in_(["decision_maker", "emergency"]))
                 .all())
    sent, refused = 0, []
    for member in members:
        if not member.phone:
            continue
        message = tel.send_sms(
            db, member.phone,
            "Mabia: {} needs to go to the health centre now. A health worker "
            "has been told and transport is being arranged.".format(patient.name),
            kind="circle_alert", patient_id=patient.id)
        if _failed(message):
            refused.append(member.role.replace("_", " "))
        else:
            sent += 1

    # The family is the mechanism for the first delay, and a refused message to
    # them looked identical to a delivered one. If the worker is not told, she
    # believes the household has been reached and it has not.
    if refused and emergency is not None:
        emergency.alert_failed = True
        note = "Could not text: {}.".format(", ".join(refused))
        emergency.alert_error = ((emergency.alert_error or "") + " " + note).strip()[:200]
        db.flush()
    return sent


def validate_emergency(db: Session, emergency: Emergency, user: User) -> Emergency:
    """The human-in-the-loop gate. Nothing leaves this building before it.

    That now includes the family. Alerting them on an unreviewed keypress meant
    the one part of the system that cannot be retracted -- a message already on
    a husband's handset -- was the only part with no clinician in front of it.
    """
    # Idempotent here, not only in the HTTP handler. This is the function the
    # docstring calls the gate, and calling it twice sent the family a second
    # "she needs to go to the health centre now" -- the guard lived one layer
    # up, so anything else calling the gate directly bypassed it.
    if emergency.validated_at is not None:
        return emergency

    emergency.status = "validated"
    emergency.validated_by = user.id
    emergency.validated_at = dt.datetime.utcnow()
    db.flush()
    ev.record(db, patient_id=emergency.patient_id, actor_id=user.id,
              event_type=ev.EMERGENCY_VALIDATED,
              payload={"emergency_id": emergency.id})

    patient = db.get(Patient, emergency.patient_id)
    if patient is not None:
        alert_care_circle(db, patient,
                          labels_for(emergency.reason_codes or []) or "danger signs",
                          emergency=emergency)
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
    from .models import CareCircleMember

    drivers = (db.query(Driver)
                 .filter(Driver.community == patient.community,
                         Driver.available.is_(True))
                 .all())

    # A driver she has already agreed with beats the best-ranked stranger.
    named = (db.query(CareCircleMember)
               .filter(CareCircleMember.patient_id == patient.id,
                       CareCircleMember.role == "driver").first())
    if not drivers:
        drivers = db.query(Driver).filter(Driver.available.is_(True)).all()

    # The preference has to live IN the sort key. A pre-sort followed by a
    # second sorted() on different keys silently discarded it, so the man she
    # named and trusts was ranked as a stranger by response rate.
    named_phone = named.phone if named and named.phone else None
    vehicle_rank = {"ambulance": 0, "car": 1, "motorking": 2, "motorbike": 3}
    return sorted(drivers, key=lambda d: (
        0 if named_phone and d.phone == named_phone else 1,
        0 if d.community == patient.community else 1,
        vehicle_rank.get(d.vehicle_type, 4),
        -d.response_rate,
        d.name))


def _nobody_is_coming(db: Session, emergency: Emergency) -> bool:
    """Whether this case still needs a vehicle found for it."""
    if emergency.status in ("transporting", "arrived", "closed", "cancelled"):
        return False
    return not (db.query(Dispatch)
                  .filter(Dispatch.emergency_id == emergency.id,
                          Dispatch.status == "accepted").count())


def offer_next_driver(db: Session, emergency: Emergency) -> Optional[Dispatch]:
    """Ring the next driver in the cascade. Acceptance happens in the call.

    Never before a human has confirmed the case, and never after it closes.
    "Nothing dispatches before a human confirms" is the rule this whole
    product is built on, and the endpoint that calls this had no status guard:
    a driver could be rung and texted with no clinician anywhere in the loop,
    validated_by left empty so the audit trail showed no human, and /validate
    then short-circuited -- so the family alert could never fire for that case
    at all.
    """
    if emergency.status == "pending_validation":
        return None
    if not is_open(emergency):
        return None
    patient = db.get(Patient, emergency.patient_id)
    if patient is None:
        emergency.status = "cancelled"
        db.flush()
        return None
    # Deduped by handset, not by row. Two rows can carry one number -- a
    # household naming a driver already on the roster under a different
    # spelling, or a migration normalising both into agreement -- and this
    # cascade then rang the same man twice, telling the health worker it had
    # moved on to the next driver while burning a position in a queue that
    # exists for a bleeding woman.
    # Queried, not read off the relationship: emergency.dispatches is stale
    # immediately after a flush, so the second call in a cascade saw an empty
    # list and happily rang the same man again.
    offered = (db.query(Dispatch)
                 .filter(Dispatch.emergency_id == emergency.id).all())
    already = {d.driver_id for d in offered}
    tried_numbers = {db.get(Driver, d.driver_id).phone
                     for d in offered
                     if db.get(Driver, d.driver_id) is not None}
    for driver in rank_drivers(db, patient):
        if driver.id in already or driver.phone in tried_numbers:
            continue
        already.add(driver.id)
        dispatch = Dispatch(emergency_id=emergency.id, driver_id=driver.id,
                            position=len(already), status="offered")
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


OPEN_STATES = ("pending_validation", "validated", "dispatching",
               "transporting", "no_transport", "arrived")


def is_open(emergency) -> bool:
    """Whether this case is still live. Closed and cancelled are not."""
    return bool(emergency) and emergency.status in OPEN_STATES


def driver_responded(db: Session, dispatch: Dispatch, accepted: bool) -> Dispatch:
    # Two drivers both pressing 1 used to give one woman two vehicles and the
    # facility two alerts, with the UI showing whichever the ORM returned first.
    if dispatch.status != "offered":
        return dispatch
    emergency = db.get(Emergency, dispatch.emergency_id)

    # A driver who presses 1 after the case is closed must not reopen it. It
    # used to: the case went back to "transporting", the facility was told to
    # prepare for a woman already at home, and -- worst -- raise_emergency then
    # saw an open case for her, found no NEW reason code, and returned having
    # sent nothing and logged nothing. Her next danger sign vanished, and
    # /validate refused her because the status was no longer awaiting one.
    if not is_open(emergency):
        dispatch.status = "cancelled"
        dispatch.responded_at = dt.datetime.utcnow()
        db.flush()
        return dispatch
    if accepted and emergency and any(
            d.status == "accepted" for d in emergency.dispatches):
        dispatch.status = "cancelled"
        dispatch.responded_at = dt.datetime.utcnow()
        db.flush()
        return dispatch

    dispatch.status = "accepted" if accepted else "declined"
    dispatch.responded_at = dt.datetime.utcnow()
    driver = db.get(Driver, dispatch.driver_id)
    if driver is None:
        db.flush()
        return dispatch
    if accepted:
        driver.accepted_count = (driver.accepted_count or 0) + 1
        emergency.status = "transporting"
        db.flush()
        notify_facility(db, emergency)
    else:
        db.flush()
        # Only if nobody is already coming. The gate added last commit closed
        # the accept direction and left this one open: a LOSING driver pressing
        # 2 after another had accepted rewound the case from transporting back
        # to dispatching, rang and paid a second vehicle, and -- if he was the
        # last in the queue -- flipped it to no_transport and texted the health
        # worker that nobody had accepted, while a driver was on the road. It
        # would even un-mark an arrival.
        if _nobody_is_coming(db, emergency):
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
        # Unconditionally, not only when raise_emergency finds a new reason.
        # The second time she rang, "nurse_unreachable" was already on the open
        # case, so raise_emergency returned early having sent nothing -- and
        # she was told her health worker had been informed. This function's own
        # docstring calls this the path that must never be skipped.
        _alert_cho(db, patient,
                   "{} rang the hotline again and no nurse answered. "
                   "Call her: {}".format(patient.name, patient.phone))
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


def run_due_contacts(db: Session, limit: int = 25) -> dict:
    """Place the calls that are due. This is the loop the product is named for.

    Called by a cron hitting POST /api/contacts/run-due. Deliberately an
    endpoint rather than an in-process timer: a free web dyno sleeps, and a
    thread that stops when the dyno idles is a scheduler that quietly does
    nothing -- which is worse than not having one.
    """
    from .telephony import service as tel_service

    placed, failed, skipped = [], [], []
    for contact in due_contacts(db)[:limit]:
        patient = db.get(Patient, contact.patient_id)
        # Never called and unreachable are different facts, and both were
        # written as "missed". A woman enrolled without consent, or already
        # delivered, showed up on a worker's screen as a contact that failed --
        # so the response is to try the phone again, when the actual problem is
        # that nobody may ring her at all until she has agreed.
        if patient is None or patient.status != "active":
            contact.status = "not_due"
            skipped.append(contact.id)
            continue
        if not patient.consent:
            contact.status = "no_consent"
            skipped.append(contact.id)
            continue

        # Three tries across the day, then it stops being a phone problem and
        # becomes a visit.
        if (contact.attempts or 0) >= 3:
            contact.status = "missed"
            ev.record(db, patient_id=patient.id, actor_id="system",
                      event_type=ev.CALL_ATTEMPTED,
                      payload={"outcome": "unreachable", "contact": contact.id,
                               "note": "three attempts — needs a physical visit"})
            skipped.append(contact.id)
            continue

        contact.attempts = (contact.attempts or 0) + 1
        session, result = tel_service.outreach_call(db, patient, contact)
        if result.ok:
            placed.append({"patient": patient.name, "week": contact.week,
                           "session_id": session.id})
        else:
            failed.append({"patient": patient.name, "error": result.error})
        db.flush()

    return {"placed": placed, "failed": failed, "skipped": len(skipped),
            "remaining": len(due_contacts(db))}


def due_contacts(db: Session, on: Optional[dt.date] = None) -> List:
    from .models import Contact
    on = on or dt.date.today()
    return (db.query(Contact)
              .filter(Contact.status == "pending", Contact.due_date <= on)
              .order_by(Contact.due_date.asc())
              .all())
