"""The prioritised worklist -- RED first, then AMBER, then the rest.

Sorting is trivial and the value is high: it is the difference between a worker
opening the app and knowing who to see, and opening the app and reading a list.
"""
import datetime as dt

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..engines.risk import AMBER, GREEN, RED
from ..models import Patient, PatientState, User
from ..security import current_user
from ..events import UNMEASURED_AFTER

router = APIRouter(prefix="/api/worklist", tags=["worklist"])

ORDER = {RED: 0, AMBER: 1, GREEN: 2}


def weeks_pregnant(patient):
    """Weeks of gestation today, from the expected delivery date.

    Forty weeks minus what remains. Absent an EDD there is no honest answer,
    and None says so rather than guessing zero.
    """
    if not patient.edd:
        return None
    remaining = (patient.edd - dt.date.today()).days
    weeks = 40 - round(remaining / 7)
    return weeks if 0 <= weeks <= 45 else None


@router.get("")
def worklist(db: Session = Depends(get_db), user: User = Depends(current_user),
             mine: bool = False):
    query = db.query(Patient).filter(Patient.status == "active")
    if mine:
        query = query.filter(Patient.assigned_cho_id == user.id)
    rows = []
    for patient in query.all():
        state = db.get(PatientState, patient.id)
        level = state.risk_level if state else GREEN
        rows.append({
            "id": patient.id, "name": patient.name, "phone": patient.phone,
            "community": patient.community, "language": patient.language,
            "risk_level": level,
            "reason_codes": (state.reason_codes if state else []) or [],
            "red_open": bool(state.red_open) if state else False,
            "mdd_score": state.mdd_score if state else None,
            "mdd_instrument": state.mdd_instrument if state else None,
            "muac_mother": state.muac_mother if state else None,
            "muac_child": state.muac_child if state else None,
            "unreachable": state.consecutive_unreachable if state else 0,
            "last_contact_at": state.last_contact_at if state else None,
            # The two facts a worker sorts a list of pregnant women by, and
            # neither was here: how far along she is, and how far away she is.
            "weeks_pregnant": weeks_pregnant(patient),
            "minutes_to_facility": patient.minutes_to_facility,
            "road_condition": patient.road_condition,
            "edd": patient.edd,
        })
    rows.sort(key=lambda r: (ORDER.get(r["risk_level"], 3), r["name"]))
    return {"counts": {level: sum(1 for r in rows if r["risk_level"] == level)
                       for level in (RED, AMBER, GREEN)},
            "patients": rows}


@router.get("/nutrition")
def nutrition_worklist(db: Session = Depends(get_db),
                       user: User = Depends(current_user)):
    """The nutrition officer's view of the same caseload."""
    from .. import events as ev

    rows = []
    for patient in db.query(Patient).filter(Patient.status == "active").all():
        state = db.get(PatientState, patient.id)
        if not state:
            continue

        # Direction of travel is the entire clinical question in CMAM, and a
        # single number cannot express it. One reading of 12.2 cm on the way up
        # and one on the way down are different children.
        # Coerced, not trusted. A device can push "11.0" as a string over a
        # lossy link, and a measurement that cannot be parsed is not a
        # measurement -- it must not be subtracted from the next one.
        from ..engines.risk import _number

        history = []
        for e in ev.load(db, patient.id):
            if e.event_type != ev.MUAC:
                continue
            value = _number((e.payload or {}).get("value_cm"))
            if value is None:
                continue
            history.append({"at": e.occurred_at,
                            "subject": (e.payload or {}).get("subject"),
                            "value": value})
        child_series = [h["value"] for h in history if h["subject"] == "child"][-4:]
        mother_series = [h["value"] for h in history if h["subject"] != "child"][-4:]

        def trend(series):
            if len(series) < 2:
                return None
            return round(series[-1] - series[0], 1)
        concern = (
            (state.mdd_score is not None and state.mdd_score < 5
             and (state.mdd_unknown or 0) < UNMEASURED_AFTER)
            or (state.muac_mother is not None and state.muac_mother < 23.0)
            or (state.muac_child is not None and state.muac_child < 12.5)
            or state.ifa_adherent is False)
        rows.append({
            "id": patient.id, "name": patient.name,
            "community": patient.community, "region": patient.region,
            "mdd_score": state.mdd_score, "mdd_instrument": state.mdd_instrument,
            "mdd_missing": state.mdd_missing_groups or [],
            "muac_mother": state.muac_mother, "muac_child": state.muac_child,
            "ifa_adherent": state.ifa_adherent, "concern": concern,
            "child_series": child_series, "mother_series": mother_series,
            "child_trend": trend(child_series),
            "mother_trend": trend(mother_series),
            "risk_level": state.risk_level})
    # Sorted by how fast they are getting worse, not alphabetically.
    rows.sort(key=lambda r: (not r["concern"],
                             r["child_trend"] if r["child_trend"] is not None else 99,
                             r["mother_trend"] if r["mother_trend"] is not None else 99,
                             r["name"]))
    return {"patients": rows,
            "concerns": sum(1 for r in rows if r["concern"])}
