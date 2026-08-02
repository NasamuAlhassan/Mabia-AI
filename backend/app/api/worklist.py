"""The prioritised worklist -- RED first, then AMBER, then the rest.

Sorting is trivial and the value is high: it is the difference between a worker
opening the app and knowing who to see, and opening the app and reading a list.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..engines.risk import AMBER, GREEN, RED
from ..models import Patient, PatientState, User
from ..security import current_user

router = APIRouter(prefix="/api/worklist", tags=["worklist"])

ORDER = {RED: 0, AMBER: 1, GREEN: 2}


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
        })
    rows.sort(key=lambda r: (ORDER.get(r["risk_level"], 3), r["name"]))
    return {"counts": {level: sum(1 for r in rows if r["risk_level"] == level)
                       for level in (RED, AMBER, GREEN)},
            "patients": rows}


@router.get("/nutrition")
def nutrition_worklist(db: Session = Depends(get_db),
                       user: User = Depends(current_user)):
    """The nutrition officer's view of the same caseload."""
    rows = []
    for patient in db.query(Patient).filter(Patient.status == "active").all():
        state = db.get(PatientState, patient.id)
        if not state:
            continue
        concern = (
            (state.mdd_score is not None and state.mdd_score < 5)
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
            "risk_level": state.risk_level})
    rows.sort(key=lambda r: (not r["concern"], r["name"]))
    return {"patients": rows,
            "concerns": sum(1 for r in rows if r["concern"])}
