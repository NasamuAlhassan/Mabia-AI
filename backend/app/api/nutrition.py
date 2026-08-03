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
    # Was every question actually put to her? A form filled in during a visit
    # normally was, and then anything not ticked is a real gap. A recall that
    # was interrupted was not, and the groups nobody reached are unknown --
    # not deficits. Defaulting to True keeps every existing caller correct,
    # and `unknown` is how a partial recall says so.
    complete: bool = True
    # None, not []. An empty list is a positive claim that nothing was left
    # unasked, and Recall reads it that way -- so `complete: false` did
    # precisely nothing unless the caller also enumerated every unasked
    # question by key, and a caller who can do that does not need the flag.
    unknown: Optional[List[str]] = None
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
    # A form filled in on paper and typed up is a completed questionnaire:
    # everything not ticked was asked and denied. Saying so explicitly is the
    # point -- the old constructor inferred it, which is how a partially
    # completed recall silently became a set of measured gaps.
    if body.complete:
        recall = Recall.from_complete(body.instrument, body.present)
    elif body.unknown is not None:
        recall = Recall(body.instrument, body.present, unknown=body.unknown)
    else:
        # Interrupted, and the caller has not said where. Everything she did
        # not name as eaten is unestablished -- which is the whole point of
        # saying the recall was not completed.
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
                           # Without this the projection reads a partial recall
                           # as fully measured, and all three guards that key on
                           # mdd_unknown are defeated by the absent key rather
                           # than by a wrong value.
                           "unknown": recall.unknown,
                           "present": recall.present,
                           "message": rec.message if rec else None})
        db.commit()

    return {"recall": recall.to_dict(),
            "recommendation": rec.to_dict() if rec else None}
