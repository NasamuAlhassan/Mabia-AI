"""Nutrition: score a recall, preview a recommendation, browse the food table."""
import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import events as ev
from ..data.foods import CHILD_GROUPS, FOODS, MDDW_GROUPS, season_for
from ..db import get_db
from ..engines.nutrition import MDD_CHILD, MDD_W, Recall, questions, recommend
from ..models import Patient, User
from ..security import current_user

router = APIRouter(prefix="/api/nutrition", tags=["nutrition"])


@router.get("/instruments")
def instruments():
    """The two instruments, kept explicitly separate.

    MDD-W is ten groups for a woman. The child indicator is eight, including
    breast milk. They are not interchangeable and are never reported together.
    """
    return {
        "mdd_w": {"groups": [{"key": k, "label": v} for k, v in MDDW_GROUPS],
                  "minimum": 5, "applies_to": "pregnant or lactating women",
                  "questions": questions(MDD_W)},
        "mdd_child": {"groups": [{"key": k, "label": v} for k, v in CHILD_GROUPS],
                      "minimum": 5, "applies_to": "children 6-23 months",
                      "questions": questions(MDD_CHILD)},
    }


@router.get("/foods")
def food_table(month: Optional[int] = None, region: str = "Northern"):
    month = month or dt.date.today().month
    rows = []
    for food in FOODS:
        available = month in food["months"] and (
            food["regions"] == "all" or region in food["regions"])
        rows.append({"key": food["key"], "name": food["name"],
                     "tier": food["tier"], "source": food["source"],
                     "groups_women": food["w_groups"],
                     "groups_child": food["c_groups"],
                     "iron_rich": food["iron_rich"],
                     "vitamin_c": food["vitamin_c"],
                     "local_names": food["local_names"],
                     "available_now": available, "message": food["message"]})
    return {"month": month, "region": region, "season": season_for(month),
            "foods": rows}


class RecallIn(BaseModel):
    instrument: str = MDD_W
    present: List[str] = []
    region: Optional[str] = None
    month: Optional[int] = Field(default=None, ge=1, le=12)
    affordability: Optional[str] = None
    taboos: List[str] = []
    anaemia_focus: bool = False
    patient_id: Optional[str] = None
    save: bool = False

    @field_validator("instrument")
    @classmethod
    def _known_instrument(cls, value):
        if value not in (MDD_W, MDD_CHILD):
            raise ValueError(
                "instrument must be 'mdd_w' (women, ten groups) or "
                "'mdd_child' (6-23 months, eight groups). They are different "
                "instruments and are never interchangeable.")
        return value


@router.post("/assess")
def assess(body: RecallIn, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    """Score the recall and choose the one message she will actually hear."""
    patient = db.get(Patient, body.patient_id) if body.patient_id else None
    recall = Recall(body.instrument, body.present)
    rec = recommend(
        recall,
        region=body.region or (patient.region if patient else "Northern"),
        month=body.month,
        affordability=body.affordability or (patient.affordability if patient else "low"),
        taboos=body.taboos or ((patient.taboos if patient else []) or []),
        anaemia_focus=body.anaemia_focus)

    if body.save and patient:
        ev.record(db, patient_id=patient.id, actor_id=user.id,
                  event_type=ev.DIET_RECALL,
                  payload={"instrument": recall.instrument, "score": recall.score,
                           "total": recall.total, "missing": recall.missing,
                           "present": recall.present,
                           "message": rec.message if rec else None})
        db.commit()

    return {"recall": recall.to_dict(),
            "recommendation": rec.to_dict() if rec else None}
