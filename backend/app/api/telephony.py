"""Telephony webhooks: voice, USSD, inbound SMS, delivery reports.

Africa's Talking POSTs here. The handlers are deliberately thin -- everything
expensive happens after the call ends, because a slow response here is a dropped
call, not a slow page.
"""
import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, Response
from sqlalchemy.orm import Session

from .. import events as ev
from .. import prompts, services
from .. import settings_store as store
from ..db import get_db
from ..models import (CallbackRequest, CallSession, Dispatch, Emergency,
                      Patient, User, UssdSession)
from ..security import current_user
from ..telephony import ivr
from ..telephony import service as tel

router = APIRouter(prefix="/api/telephony", tags=["telephony"])

XML = "application/xml"


def _xml(body: str) -> Response:
    return Response(content=body, media_type=XML)


def _find_session(db: Session, session_id: str, caller: str, destination: str,
                  direction: str) -> Optional[CallSession]:
    """Reconcile the provider's session id with ours.

    We mint our own id when placing a call, because the callback can arrive
    before the HTTP response carrying theirs. On the first callback we bind the
    two together by matching the handset number, and thereafter it is a lookup.
    """
    session = db.get(CallSession, session_id)
    if session:
        return session

    session = (db.query(CallSession)
                 .filter(CallSession.provider_session_id == session_id)
                 .first())
    if session:
        return session

    phone = destination if direction == "outbound" else caller
    if phone:
        session = (db.query(CallSession)
                     .filter(CallSession.phone == phone,
                             CallSession.direction == direction,
                             CallSession.ended_at.is_(None))
                     .order_by(CallSession.started_at.desc())
                     .first())
        if session:
            session.provider_session_id = session_id
            db.flush()
            return session
    return None


@router.post("/voice")
async def voice(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    session_id = (form.get("sessionId") or "").strip()
    is_active = str(form.get("isActive") or "1").strip()
    dtmf = (form.get("dtmfDigits") or "").strip() or None
    caller = (form.get("callerNumber") or "").strip()
    destination = (form.get("destinationNumber") or "").strip()
    direction = (form.get("direction") or "outbound").strip().lower()

    base = tel.base_url(db)
    callback = tel.callback_url(db)

    # ---- inbound: reject and call back, so she pays nothing ---------------
    if direction == "inbound":
        session = _find_session(db, session_id, caller, destination, direction)
        if session is None:
            patient = db.query(Patient).filter(Patient.phone == caller).first()
            existing = (db.query(CallbackRequest)
                          .filter(CallbackRequest.phone == caller,
                                  CallbackRequest.status == "pending").first())
            if existing is None:
                db.add(CallbackRequest(phone=caller,
                                       patient_id=patient.id if patient else None))
            db.commit()
            # Rejecting means the call is never answered, so she is never
            # charged. The platform rings her straight back.
            return _xml("<Response><Reject/></Response>")

    # ---- call ended -------------------------------------------------------
    if is_active == "0":
        session = _find_session(db, session_id, caller, destination, direction)
        if session and session.ended_at is None:
            session.ended_at = dt.datetime.utcnow()
            if not session.outcome:
                session.outcome = "dropped"
            db.flush()
            if session.purpose == "driver":
                # He never answered, or hung up without pressing anything. The
                # emergency must move on rather than sit on a silent phone --
                # this is the path that used to strand a bleeding woman in
                # "dispatching" with nobody told.
                _driver_no_answer(db, session)
            else:
                _after_call(db, session)
        db.commit()
        return Response(status_code=200)

    session = _find_session(db, session_id, caller, destination, direction)
    if session is None:
        db.commit()
        return _xml("<Response><Say>Sorry, this call could not be matched. "
                    "Goodbye.</Say></Response>")

    # The call is over. A late keypress, or a provider retry of the last
    # webhook, must not walk the state machine again -- that used to duplicate
    # the entire call into the event log.
    if session.ended_at is not None:
        db.commit()
        return _xml(ivr.tell(db, base, session.language, "closing",
                             prompts.line("closing")))

    # ---- driver dispatch: one question, one key --------------------------
    if session.purpose == "driver":
        return _driver_turn(db, session, dtmf, base, callback)

    # ---- outreach and hotline --------------------------------------------
    turn = ivr.advance(db, session, dtmf, base, callback)

    if turn.note == "nurse":
        # Fold what she has already said into the log BEFORE routing her. She
        # may have just reported bleeding and then asked for a person; losing
        # that on the way to the nurse is the worst possible moment to lose it.
        _after_call(db, session, keep_open=True)
        xml = _nurse_turn(db, session, base)
        db.commit()
        return _xml(xml)

    if turn.finished:
        session.ended_at = dt.datetime.utcnow()
        if not session.outcome:
            session.outcome = turn.note or "completed"
        db.flush()
        _after_call(db, session)
    db.commit()
    return _xml(turn.xml)


def _driver_no_answer(db: Session, session: CallSession) -> None:
    dispatch = (db.query(Dispatch)
                  .filter(Dispatch.emergency_id == session.emergency_id,
                          Dispatch.driver_id == session.driver_id,
                          Dispatch.status == "offered")
                  .first())
    if dispatch is None:
        return
    dispatch.status = "no_answer"
    dispatch.responded_at = dt.datetime.utcnow()
    db.flush()
    emergency = db.get(Emergency, session.emergency_id)
    if emergency and emergency.status in ("dispatching", "validated"):
        services.offer_next_driver(db, emergency)


def _driver_turn(db: Session, session: CallSession, dtmf, base, callback) -> Response:
    dispatch = (db.query(Dispatch)
                  .filter(Dispatch.emergency_id == session.emergency_id,
                          Dispatch.driver_id == session.driver_id,
                          Dispatch.status == "offered")
                  .first())
    if dtmf is None:
        db.commit()
        return _xml(ivr.ask(db, base, session.language, "driver_request",
                            prompts.line("driver_request"), callback))

    if dtmf not in ("1", "2"):
        db.commit()
        return _xml(ivr.ask(db, base, session.language, "driver_request",
                            prompts.line("not_understood") + " " +
                            prompts.line("driver_request"), callback))
    accepted = dtmf == "1"
    if dispatch:
        services.driver_responded(db, dispatch, accepted)
    session.state = "done"
    session.outcome = "accepted" if accepted else "declined"
    session.ended_at = dt.datetime.utcnow()
    db.flush()
    db.commit()
    key = "driver_accepted" if accepted else "driver_declined"
    return _xml(ivr.tell(db, base, session.language, key, prompts.line(key)))


def _nurse_turn(db: Session, session: CallSession, base: str) -> str:
    """Cascade: nurse one, nurse two, then the facility line.

    If every step is exhausted the call still ends with her CHO being told. That
    is the rule this whole file exists to keep.
    """
    target = services.nurse_target(db, session)
    if target:
        session.nurse_attempt = (session.nurse_attempt or 0) + 1
        db.flush()
        if session.patient_id:
            ev.append(db, patient_id=session.patient_id, actor_id="system",
                      event_type=ev.NURSE_ROUTED,
                      payload={"attempt": session.nurse_attempt, "to": target})
        return ivr.dial(db, target, prompts.line("nurse_connecting"), base,
                        session.language)

    message = services.terminal_fallback(db, session)
    session.ended_at = dt.datetime.utcnow()
    db.flush()
    return ivr.tell(db, base, session.language, "nurse_unavailable", message)


def _after_call(db: Session, session: CallSession, keep_open: bool = False) -> None:
    """Everything expensive, once, off the call's critical path."""
    if session.purpose not in ("outreach", "hotline"):
        return
    if session.outcome in ("failed", "no_input"):
        if session.patient_id:
            ev.record(db, patient_id=session.patient_id, actor_id="system",
                      event_type=ev.CALL_ATTEMPTED,
                      payload={"outcome": "unreachable", "session": session.id})
        return

    level, reasons = ivr.finalise(db, session)
    if session.contact_id:
        from ..models import Contact
        contact = db.get(Contact, session.contact_id)
        if contact:
            contact.status = "done" if session.outcome == "completed" else "missed"
            contact.attempts = (contact.attempts or 0) + 1
            contact.completed_at = dt.datetime.utcnow()
            db.flush()

    if level == "red" and session.patient_id:
        patient = db.get(Patient, session.patient_id)
        if patient:
            services.raise_emergency(db, patient, reasons, source=session.purpose)


# ------------------------------------------------------------------ USSD


@router.post("/ussd")
async def ussd(request: Request, db: Session = Depends(get_db)):
    """USSD pulls; it cannot push.

    A session is only ever started by the person holding the handset, which is
    why alerts go by SMS and this screen exists for retrieval. Each screen is
    kept well inside the ~182 character budget.
    """
    form = await request.form()
    session_id = (form.get("sessionId") or "").strip()
    phone = (form.get("phoneNumber") or "").strip()
    text = (form.get("text") or "").strip()

    user = db.query(User).filter(User.phone == phone).first()
    if not user:
        db.commit()
        return Response("END This number is not registered with Mabia.",
                        media_type="text/plain")

    if db.get(UssdSession, session_id) is None:
        db.add(UssdSession(id=session_id, phone=phone, user_id=user.id))
        db.flush()

    steps = [s for s in text.split("*") if s != ""]
    body = _ussd_screen(db, user, steps)
    db.commit()
    return Response(body, media_type="text/plain")


def _ussd_screen(db: Session, user: User, steps) -> str:
    from ..models import PatientState
    if not steps:
        return ("CON Mabia\n1. Red cases\n2. Amber cases\n3. My next visits")

    choice = steps[0]
    if choice in ("1", "2"):
        level = "red" if choice == "1" else "amber"
        rows = (db.query(Patient, PatientState)
                  .join(PatientState, PatientState.patient_id == Patient.id)
                  .filter(PatientState.risk_level == level,
                          Patient.status == "active")
                  .limit(4).all())
        if not rows:
            return "END No {} cases right now.".format(level)
        if len(steps) == 1:
            lines = ["CON {} cases:".format(level.upper())]
            for index, (patient, _) in enumerate(rows, start=1):
                lines.append("{}. {} ({})".format(index, patient.name[:14],
                                                  patient.community[:8]))
            return "\n".join(lines)[:180]
        try:
            patient, state = rows[int(steps[1]) - 1]
        except (ValueError, IndexError):
            return "END Not a valid choice."
        from ..engines.risk import labels_for
        reasons = labels_for(state.reason_codes) or "no reasons recorded"
        return "END {}: {}. Call {}.".format(patient.name[:16], reasons[:90],
                                             patient.phone)[:180]

    if choice == "3":
        from ..models import Contact
        today = dt.date.today()
        rows = (db.query(Contact, Patient)
                  .join(Patient, Patient.id == Contact.patient_id)
                  .filter(Contact.status == "pending",
                          Patient.assigned_cho_id == user.id)
                  .order_by(Contact.due_date.asc()).limit(4).all())
        if not rows:
            return "END No visits scheduled."
        lines = ["END Next visits:"]
        for contact, patient in rows:
            lines.append("{} {} wk{}".format(
                contact.due_date.strftime("%d/%m"), patient.name[:12], contact.week))
        return "\n".join(lines)[:180]

    return "END Not a valid choice."


# ------------------------------------------------------------ callbacks


@router.post("/run-callbacks")
def run_callbacks(db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    """Ring back everyone who flashed us. She spends nothing."""
    pending = (db.query(CallbackRequest)
                 .filter(CallbackRequest.status == "pending").limit(10).all())
    placed = []
    for request_row in pending:
        patient = (db.get(Patient, request_row.patient_id)
                   if request_row.patient_id else None)
        session, result = tel.start_call(
            db, phone=request_row.phone,
            patient_id=patient.id if patient else None,
            purpose="hotline",
            language=(patient.language if patient else
                      store.get(db, "default_language")))
        request_row.status = "called" if result.ok else "failed"
        request_row.called_at = dt.datetime.utcnow()
        placed.append({"phone": request_row.phone, "ok": result.ok,
                       "error": result.error, "session_id": session.id})
    db.commit()
    return {"placed": placed, "count": len(placed)}


@router.post("/flash")
def simulate_flash(phone: str, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    """Stand-in for a missed call, so the call-back path is demonstrable."""
    patient = db.query(Patient).filter(Patient.phone == phone).first()
    db.add(CallbackRequest(phone=phone, patient_id=patient.id if patient else None))
    db.commit()
    return {"ok": True, "phone": phone,
            "note": "Queued. Run callbacks to ring back."}
