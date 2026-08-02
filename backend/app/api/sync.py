"""Offline synchronisation.

The contract is one line long: **the server de-duplicates on the client's event
id.** A worker on a failing link can push the same batch as many times as she
likes and the result is identical, which is what makes an unreliable network
survivable rather than merely annoying.
"""
import datetime as dt
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import events as ev
from ..db import get_db
from ..models import Event, User
from ..security import current_user

router = APIRouter(prefix="/api/sync", tags=["sync"])


class EventIn(BaseModel):
    event_id: str
    patient_id: Optional[str] = None
    event_type: str
    payload: Dict[str, Any] = {}
    occurred_at: dt.datetime
    recorded_at: Optional[dt.datetime] = None
    device_id: str = "web"
    seq: int = 0


class PushIn(BaseModel):
    events: List[EventIn]


@router.post("/push")
def push(body: PushIn, db: Session = Depends(get_db),
         user: User = Depends(current_user)):
    accepted, duplicates, touched = 0, 0, set()
    for item in body.events:
        existed = db.get(Event, item.event_id) is not None
        ev.append(db, patient_id=item.patient_id, actor_id=user.id,
                  event_type=item.event_type, payload=item.payload,
                  event_id=item.event_id, occurred_at=item.occurred_at,
                  recorded_at=item.recorded_at or item.occurred_at,
                  device_id=item.device_id, seq=item.seq)
        if existed:
            duplicates += 1
        else:
            accepted += 1
        if item.patient_id:
            touched.add(item.patient_id)

    # Re-fold once per patient, not once per event: a late batch lands in the
    # right place in history and the projection is rebuilt from the whole log.
    for patient_id in touched:
        ev.refresh_state(db, patient_id)
    db.commit()
    return {"accepted": accepted, "duplicates": duplicates,
            "patients_refolded": len(touched)}


@router.get("/pull")
def pull(since: Optional[dt.datetime] = None, limit: int = 500,
         db: Session = Depends(get_db), user: User = Depends(current_user)):
    query = db.query(Event)
    if since:
        query = query.filter(Event.server_received_at > since)
    rows = query.order_by(Event.server_received_at.asc()).limit(limit).all()
    return {"events": [{"event_id": e.event_id, "patient_id": e.patient_id,
                        "event_type": e.event_type, "payload": e.payload,
                        "occurred_at": e.occurred_at,
                        "recorded_at": e.recorded_at,
                        "server_received_at": e.server_received_at,
                        "device_id": e.device_id, "seq": e.seq} for e in rows],
            "count": len(rows),
            "cursor": rows[-1].server_received_at if rows else since}
