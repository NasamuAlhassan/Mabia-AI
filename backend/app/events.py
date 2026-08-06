"""The append-only event log, and the fold that turns it into patient state.

Three properties matter here, and each one exists for a reason you can point at
in the field:

1. **Idempotent ingest.** The server de-duplicates on the client-generated
   event id. A worker on a failing 3G link can retry the same batch forever and
   the result is identical. This is the single property that removes most sync
   bugs.

2. **State is a fold, never a stored truth.** `PatientState` is a cache. A CHO
   who syncs three days late inserts events with older `occurred_at` values, the
   log is re-folded, and the result is correct -- there is no write for a late
   sync to clobber.

3. **A RED stays RED until a human closes it.** That is a clinical rule, not a
   merge rule. If the IVR says bleeding and a later visit says none, the newer
   observation wins for the *observation*, but the open emergency does not
   silently disappear.
"""
import datetime as dt
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .models import Event, Patient, PatientState

# Event types. Anything not listed here is still stored -- the log is not a
# schema -- but only these participate in the fold.
ENROLMENT = "enrolment"
CONSENT_GIVEN = "consent_given"
DANGER_SIGNS = "danger_signs_reported"
DIET_RECALL = "diet_recall"
MUAC = "muac_measured"
IFA = "ifa_adherence"
VISIT = "visit_recorded"
CALL_ATTEMPTED = "call_attempted"
CALL_COMPLETED = "call_completed"
EMERGENCY_RAISED = "emergency_raised"
EMERGENCY_VALIDATED = "emergency_validated"
REFERRAL_OUTCOME = "referral_outcome"
NURSE_ROUTED = "nurse_routed"
TRANSPORT_REQUESTED = "transport_requested"
RED_CLOSED = "red_closed"
DELIVERED = "delivered"


# How many unanswered food questions make a recall unusable rather than poor.
# Three is a third of the women's instrument and well over a third of the
# child's; below that the score still means something, above it it does not.
UNMEASURED_AFTER = 3


class Snapshot:
    """The folded view of one patient. Input to the risk engine."""

    def __init__(self) -> None:
        self.danger_signs: Dict[str, dt.datetime] = {}   # sign -> when last affirmed
        self.cleared_signs: Dict[str, dt.datetime] = {}  # sign -> when last denied
        self.mdd_score: Optional[int] = None
        self.mdd_unknown: Optional[int] = None
        self.mdd_instrument: Optional[str] = None
        self.mdd_missing: List[str] = []
        self.mdd_history: List[int] = []
        self.muac_mother: Optional[float] = None
        self.muac_child: Optional[float] = None
        self.ifa_adherent: Optional[bool] = None
        self.last_contact_at: Optional[dt.datetime] = None
        self.last_contact_outcome: Optional[str] = None
        self.consecutive_unreachable = 0
        self.red_open = False
        self.delivered = False
        self.unanswered: Dict[str, dt.datetime] = {}
        self.events_folded = 0

    @property
    def active_danger_signs(self) -> List[str]:
        """A sign counts if its most recent mention affirmed it."""
        out = []
        for sign, at in self.danger_signs.items():
            cleared = self.cleared_signs.get(sign)
            if cleared is None or at >= cleared:
                out.append(sign)
        return sorted(out)


def append(
    db: Session,
    *,
    patient_id: Optional[str],
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    actor_id: str = "system",
    event_id: Optional[str] = None,
    occurred_at: Optional[dt.datetime] = None,
    recorded_at: Optional[dt.datetime] = None,
    device_id: str = "server",
    seq: int = 0,
) -> Event:
    """Append one event. Returns the existing row if the id was already seen."""
    from .ids import uuid7

    event_id = event_id or uuid7()
    existing = db.get(Event, event_id)
    if existing is not None:
        return existing  # idempotent: a retry is a no-op, not a duplicate

    now = dt.datetime.utcnow()
    event = Event(
        event_id=event_id,
        patient_id=patient_id,
        actor_id=actor_id,
        event_type=event_type,
        payload=payload or {},
        occurred_at=occurred_at or now,
        recorded_at=recorded_at or now,
        server_received_at=now,
        device_id=device_id,
        seq=seq,
    )
    db.add(event)
    db.flush()
    return event


def load(db: Session, patient_id: str) -> List[Event]:
    """Events in deterministic clinical order.

    Ordering on (occurred_at, device_id, seq) rather than arrival time: a late
    sync must land in the right place in the history, not at the end of it.
    """
    rows = (
        db.query(Event)
        .filter(Event.patient_id == patient_id)
        .all()
    )
    return sorted(rows, key=lambda e: (e.occurred_at, e.device_id or "", e.seq or 0))


def fold(db: Session, patient_id: str) -> Snapshot:
    """Replay the log into a snapshot. Pure with respect to the database."""
    snap = Snapshot()
    for event in load(db, patient_id):
        _apply(snap, event)
        snap.events_folded += 1
    return snap


def _apply(snap: Snapshot, event: Event) -> None:
    payload = event.payload or {}
    kind = event.event_type
    when = event.occurred_at

    if kind == DANGER_SIGNS:
        for sign in payload.get("signs", []):
            snap.danger_signs[sign] = when
        for sign in payload.get("denied", []):
            snap.cleared_signs[sign] = when
        # "Not asked" and "asked and denied" are different clinical facts. An
        # unanswered question must never clear a sign she affirmed earlier.
        for sign in payload.get("unanswered", []):
            snap.unanswered[sign] = when

    elif kind == DIET_RECALL:
        snap.mdd_score = payload.get("score")
        # How many questions went unanswered. Without it the projection cannot
        # tell "she eats three food groups" from "we only got three answers",
        # and the worklist and the metrics were reading the second as the
        # first -- flagging a woman for nutrition follow-up on the strength of
        # a bad phone line.
        snap.mdd_unknown = len(payload.get("unknown") or [])
        snap.mdd_instrument = payload.get("instrument")
        snap.mdd_missing = payload.get("missing", [])
        # Only recalls we actually managed to take. The history drives the
        # "low on consecutive contacts" rule in the risk engine, and a call
        # where she answered nothing scores zero -- so two bad phone lines in a
        # row raised an AMBER and put her on a worker's list for a nutrition
        # visit she does not need. The same mistake was fixed in the worklist
        # and the metrics and missed here, which is the one place it becomes a
        # clinical decision.
        if (payload.get("score") is not None
                and len(payload.get("unknown") or []) < UNMEASURED_AFTER):
            snap.mdd_history.append(payload["score"])

    elif kind == MUAC:
        # A measurement event carrying no measurement used to overwrite the
        # one before it, so a follow-up with an empty field erased a severe
        # reading and the RED with it.
        value = payload.get("value_cm")
        if value is None:
            return
        # An absent or misspelt subject filed a child's arm circumference
        # under the mother, turning an 11 cm CMAM referral into an amber note
        # about undernutrition in pregnancy. Two known values, and anything
        # else is refused rather than guessed.
        subject = payload.get("subject")
        if subject not in ("child", "mother"):
            return
        if subject == "child":
            snap.muac_child = value
        else:
            snap.muac_mother = value

    elif kind == IFA:
        # Tri-state on purpose. bool() made an absent answer False -- which
        # the risk engine states as "not taking iron and folic acid, anaemia
        # risk" -- and made the string "no" True, because a non-empty string
        # is truthy. Both directions were wrong and both were reachable from
        # the sync endpoint.
        adherent = payload.get("adherent")
        if adherent is None:
            return
        if isinstance(adherent, str):
            adherent = adherent.strip().lower() in ("1", "true", "yes", "y")
        snap.ifa_adherent = bool(adherent)

    elif kind == CALL_ATTEMPTED:
        outcome = payload.get("outcome")
        snap.last_contact_outcome = outcome
        if outcome == "unreachable":
            snap.consecutive_unreachable += 1
        else:
            snap.consecutive_unreachable = 0
            snap.last_contact_at = when

    elif kind == CALL_COMPLETED:
        # The event carries the outcome; this used to hard-code "completed" and
        # reset the unreachable counter no matter what had actually happened.
        # A call the provider reported as dropped -- a ring-out, or a hang-up
        # mid-question -- ran finalisation, wrote this event, and was folded as
        # a contact that succeeded. So the rule three files away that says
        # "unreachable on three consecutive attempts is not safety" could never
        # fire for the two commonest failures on a rural line.
        outcome = payload.get("outcome") or "completed"
        snap.last_contact_at = when
        snap.last_contact_outcome = outcome
        if outcome in ("completed", "rescheduled"):
            snap.consecutive_unreachable = 0
        else:
            snap.consecutive_unreachable += 1

    elif kind == EMERGENCY_RAISED:
        snap.red_open = True

    elif kind in (RED_CLOSED, REFERRAL_OUTCOME):
        # Only a human closing the loop clears an open RED.
        snap.red_open = False
        # And only care actually received clears the signs that prompted it.
        #
        # If she reached a facility and was treated, the bleeding that triggered
        # the emergency has been dealt with, and leaving her permanently RED
        # would bury every genuinely new emergency underneath a stale one. If
        # she did NOT reach care, or the family declined, the sign stands and so
        # does the flag — which is the whole point of tracking outcomes rather
        # than just referrals.
        if payload.get("outcome") == "care_received":
            for sign in list(snap.danger_signs):
                snap.cleared_signs[sign] = when

    elif kind == DELIVERED:
        snap.delivered = True


def refresh_state(db: Session, patient_id: str) -> PatientState:
    """Recompute the projection. Called after every append that touches a patient."""
    from .engines.risk import classify

    patient = db.get(Patient, patient_id)
    snap = fold(db, patient_id)
    verdict = classify(snap, patient)

    state = db.get(PatientState, patient_id)
    if state is None:
        state = PatientState(patient_id=patient_id)
        db.add(state)

    state.risk_level = verdict.level
    state.reason_codes = [r.code for r in verdict.reasons]
    state.red_open = snap.red_open
    state.last_contact_at = snap.last_contact_at
    state.last_contact_outcome = snap.last_contact_outcome
    state.consecutive_unreachable = snap.consecutive_unreachable
    state.mdd_score = snap.mdd_score
    state.mdd_unknown = snap.mdd_unknown
    state.mdd_instrument = snap.mdd_instrument
    state.mdd_missing_groups = snap.mdd_missing
    state.muac_mother = snap.muac_mother
    state.muac_child = snap.muac_child
    state.ifa_adherent = snap.ifa_adherent
    state.events_folded = snap.events_folded
    db.flush()
    return state


def record(db: Session, **kwargs) -> Event:
    """Append and refresh the projection in one step."""
    event = append(db, **kwargs)
    if event.patient_id:
        refresh_state(db, event.patient_id)
    return event
