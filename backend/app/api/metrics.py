"""Impact measurement.

'Nutrition gaps closed' is the uncommon one and the one worth watching: it
measures whether guidance was actionable, not merely whether it was delivered.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..data.foods import CHILD_MINIMUM, MDDW_MINIMUM
from ..models import (Contact, Dispatch, Emergency, Event, Patient,
                      PatientState, User)
from ..security import current_user
from ..events import UNMEASURED_AFTER

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("")
def metrics(db: Session = Depends(get_db), user: User = Depends(current_user)):
    patients = db.query(Patient).filter(Patient.status == "active").count()

    contacts = db.query(Contact).count()
    done = db.query(Contact).filter(Contact.status == "done").count()
    reached = db.query(PatientState).filter(
        PatientState.last_contact_at.isnot(None)).count()

    emergencies = db.query(Emergency).count()
    closed = db.query(Emergency).filter(Emergency.status == "closed").count()
    care_received = db.query(Emergency).filter(
        Emergency.outcome == "care_received").count()

    ifa_yes = db.query(PatientState).filter(PatientState.ifa_adherent.is_(True)).count()
    ifa_known = db.query(PatientState).filter(
        PatientState.ifa_adherent.isnot(None)).count()

    # Split by instrument, because the screen below this says they are never
    # combined and this code was combining them. MDD-W is ten groups for a
    # woman; the child indicator is eight and includes breast milk. The
    # threshold happens to be five in both, which is exactly what made pooling
    # them look harmless -- the denominators and the populations differ, so the
    # pooled number is a percentage of nothing in particular.
    # Only diets we actually measured. A recall where three or more questions
    # went unanswered is a bad phone line, not a deficient diet, and counting
    # it as a failure understated the reach figure and the diversity figure at
    # the same time.
    mdd_rows = [s for s in db.query(PatientState)
                .filter(PatientState.mdd_score.isnot(None)).all()
                if (s.mdd_unknown or 0) < UNMEASURED_AFTER]
    women = [s for s in mdd_rows if s.mdd_instrument == "mdd_w"]
    children = [s for s in mdd_rows if s.mdd_instrument == "mdd_child"]
    women_ok = sum(1 for s in women if (s.mdd_score or 0) >= MDDW_MINIMUM)
    children_ok = sum(1 for s in children if (s.mdd_score or 0) >= CHILD_MINIMUM)

    gaps_closed, gaps_measured = _gap_closure(db)

    # The Three Delays, as a funnel. This is the intellectual core of the whole
    # product and it was previously invisible behind seven percentage tiles.
    detected = db.query(Emergency).count()
    validated = db.query(Emergency).filter(
        Emergency.validated_at.isnot(None)).count()
    accepted = db.query(Dispatch).filter(Dispatch.status == "accepted").count()
    arrived = db.query(Emergency).filter(Emergency.arrived_at.isnot(None)).count()
    recorded = db.query(Emergency).filter(Emergency.outcome.isnot(None)).count()

    funnel = [
        {"stage": "Danger sign detected", "count": detected, "delay": 1},
        {"stage": "Confirmed by a health worker", "count": validated, "delay": 1},
        {"stage": "Driver accepted", "count": accepted, "delay": 2},
        {"stage": "Arrived at the facility", "count": arrived, "delay": 3},
        {"stage": "Outcome recorded", "count": recorded, "delay": 3},
    ]
    for index, step in enumerate(funnel):
        previous = funnel[index - 1]["count"] if index else step["count"]
        step["lost"] = max(0, previous - step["count"])

    return {
        "funnel": funnel,
        "reached_care": care_received,
        "enrolled": patients,
        "reach_rate": _pct(reached, patients),
        "contact_completion": _pct(done, contacts),
        "ifa_adherence": _pct(ifa_yes, ifa_known),
        "mdd_women": _pct(women_ok, len(women)),
        "mdd_women_n": len(women),
        "mdd_children": _pct(children_ok, len(children)),
        "mdd_children_n": len(children),
        "nutrition_gaps_closed": _pct(gaps_closed, gaps_measured),
        "referral_closure_rate": _pct(closed, emergencies),
        "care_received_rate": _pct(care_received, emergencies),
        "counts": {"emergencies": emergencies, "closed": closed,
                   "contacts": contacts, "contacts_done": done,
                   "gaps_measured": gaps_measured, "gaps_closed": gaps_closed},
    }


def _gap_closure(db: Session):
    """Did a group missing at one contact come back at the next?"""
    rows = (db.query(Event)
              .filter(Event.event_type == "diet_recall")
              .order_by(Event.patient_id, Event.occurred_at).all())
    by_patient = {}
    for event in rows:
        by_patient.setdefault(event.patient_id, []).append(event)

    measured = closed = 0
    for recalls in by_patient.values():
        for earlier, later in zip(recalls, recalls[1:]):
            missing = set((earlier.payload or {}).get("missing", []))
            present_now = set((later.payload or {}).get("present", []))
            if not missing:
                continue
            measured += len(missing)
            closed += len(missing & present_now)
    return closed, measured


def _pct(part, whole):
    if not whole:
        return None
    return round(100.0 * part / whole, 1)
