"""The transport roster, and the map of it.

Delay 2 is reaching care, and the thing that closes it is knowing — before
anyone is bleeding — which vehicles exist in which village and which of them
answer the phone. All of that was already in the database and none of it was on
a screen: there was no route that could even list a driver, so a worker had no
way to see who would be rung for her patient, or to add the man with the
motorking who everyone in Kpale already calls.

On the map. Every driver has a community and no driver has coordinates, because
riders in villages are on feature phones that emit nothing. So this maps by
community, which is both what the data honestly holds and how dispatch already
works. A pin dropped at a made-up latitude would look better and be a lie in the
one screen where a lie costs a vehicle.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (CareCircleMember, Dispatch, Driver, Emergency, Patient,
                      User)
from ..security import current_user
from .. import phones, services

router = APIRouter(prefix="/api/drivers", tags=["drivers"])

VEHICLES = ("ambulance", "car", "motorking", "motorbike", "tricycle", "bicycle")

# A vehicle that cannot carry a woman in labour is not transport. Shown on the
# roster so nobody registers a bicycle and believes the village is covered.
CARRIES = {"ambulance", "car", "motorking", "motorbike", "tricycle"}


def _active_dispatch(db: Session, driver_id: str) -> Optional[Dispatch]:
    """The run this driver is on right now, if any.

    Only counts against an emergency that is still open: a dispatch row stays
    "accepted" forever after the case closes, and treating that as a live run
    would show every driver who has ever helped as permanently busy.
    """
    rows = (db.query(Dispatch)
              .filter(Dispatch.driver_id == driver_id,
                      Dispatch.status.in_(("offered", "accepted")))
              .order_by(Dispatch.offered_at.desc()).all())
    for row in rows:
        if services.is_open(db.get(Emergency, row.emergency_id)):
            return row
    return None


def _named_by(db: Session, phone: Optional[str]) -> int:
    """How many households name this number as their own driver."""
    if not phone:
        return 0
    return (db.query(CareCircleMember)
              .filter(CareCircleMember.role == "driver",
                      CareCircleMember.phone == phone).count())


def _view(db: Session, driver: Driver) -> dict:
    run = _active_dispatch(db, driver.id)
    on_run = None
    if run is not None:
        emergency = db.get(Emergency, run.emergency_id)
        patient = db.get(Patient, emergency.patient_id) if emergency else None
        on_run = {
            "dispatch_id": run.id,
            "emergency_id": run.emergency_id,
            "status": run.status,
            "patient_name": patient.name if patient else None,
            "community": patient.community if patient else None,
            "location_note": run.location_note,
            "location_at": run.location_at.isoformat() if run.location_at else None,
        }
    return {
        "id": driver.id,
        "name": driver.name,
        "phone": driver.phone,
        "phone_display": phones.display(driver.phone),
        "community": driver.community,
        "vehicle_type": driver.vehicle_type,
        "carries_a_patient": driver.vehicle_type in CARRIES,
        "available": bool(driver.available),
        "source": driver.source,
        "offered_count": driver.offered_count or 0,
        "accepted_count": driver.accepted_count or 0,
        # None rather than 0.5 when unproven: the ranking treats an untried
        # driver as mid-table, but a screen must not print a response rate for
        # a man who has never been rung as though it were measured.
        "response_rate": (driver.accepted_count / float(driver.offered_count)
                          if driver.offered_count else None),
        "named_by_households": _named_by(db, driver.phone),
        "on_run": on_run,
    }


@router.get("")
def list_drivers(community: Optional[str] = None,
                 include_retired: bool = False,
                 db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    query = db.query(Driver)
    if community:
        query = query.filter(Driver.community == community)
    if not include_retired:
        query = query.filter(Driver.available.is_(True))
    drivers = [_view(db, d) for d in query.order_by(Driver.name).all()]
    return {
        "drivers": drivers,
        "vehicles": list(VEHICLES),
        "on_a_run": sum(1 for d in drivers if d["on_run"]),
    }


@router.get("/map")
def driver_map(db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    """Coverage by community: who lives there, and what can carry them out.

    The gap this exists to show is a community with women enrolled and no
    vehicle registered. That is a fact about a place, it is knowable today, and
    until now nothing in the product said it out loud.
    """
    places: dict[str, dict] = {}

    def place(name: Optional[str]) -> dict:
        key = (name or "unknown").strip() or "unknown"
        if key not in places:
            places[key] = {"community": key, "patients": 0, "drivers": 0,
                           "available": 0, "on_a_run": 0, "vehicles": [],
                           "minutes_to_facility": None, "road_condition": None}
        return places[key]

    for patient in db.query(Patient).all():
        row = place(patient.community)
        row["patients"] += 1
        # The furthest household in the village is the one that defines it: a
        # mean would hide the compound an hour further out.
        minutes = patient.minutes_to_facility
        if minutes is not None:
            row["minutes_to_facility"] = max(row["minutes_to_facility"] or 0,
                                             minutes)
        # Worst road wins for the same reason. A poor road is half of why
        # Delay 2 exists, and it decides whether a motorbike is transport.
        if patient.road_condition == "poor" or row["road_condition"] is None:
            row["road_condition"] = patient.road_condition or row["road_condition"]

    for driver in db.query(Driver).all():
        row = place(driver.community)
        row["drivers"] += 1
        if driver.available:
            row["available"] += 1
            if driver.vehicle_type not in row["vehicles"]:
                row["vehicles"].append(driver.vehicle_type)
        if _active_dispatch(db, driver.id):
            row["on_a_run"] += 1

    out = []
    for row in places.values():
        carrying = [v for v in row["vehicles"] if v in CARRIES]
        # Uncovered means a woman is enrolled here and nothing registered here
        # can carry her. A bicycle in the list is not cover.
        row["uncovered"] = bool(row["patients"]) and not carrying
        out.append(row)

    # Worst first: the villages with women and no vehicle are the work.
    out.sort(key=lambda r: (not r["uncovered"], -r["patients"], r["community"]))
    return {"communities": out,
            "uncovered": [r["community"] for r in out if r["uncovered"]]}


class DriverIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=1, max_length=20)
    community: str = Field(min_length=1, max_length=120)
    vehicle_type: str = "motorking"
    available: bool = True


@router.post("")
def add_driver(body: DriverIn, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    phone = phones.normalise(body.phone)
    # normalise deliberately hands back anything it cannot parse, because a
    # short code or a foreign number is still something a person meant to type
    # and discarding it would be worse. Here it is not: a driver whose number
    # cannot be dialled holds a position in a cascade that exists for a woman in
    # labour, and the call fails at two in the morning rather than at the form.
    # Anything genuinely diallable comes back in E.164.
    if not phone or not phone.startswith("+"):
        raise HTTPException(
            422, "That number cannot be dialled. Use 024 000 0000 or +233…")
    if body.vehicle_type not in VEHICLES:
        raise HTTPException(422, "Unknown vehicle type")

    # One handset, one row. Two rows carrying one number is the exact fault the
    # cascade has to dedupe around, and it costs a position in a queue that
    # exists for a woman who is bleeding. A number already on the roster is
    # brought back rather than added twice.
    existing = db.query(Driver).filter(Driver.phone == phone).first()
    if existing is not None:
        if existing.available:
            raise HTTPException(
                409, "{} is already on the roster in {}.".format(
                    existing.name, existing.community))
        existing.available = True
        existing.name = body.name.strip()
        existing.community = body.community.strip()
        existing.vehicle_type = body.vehicle_type
        db.commit()
        return _view(db, existing)

    driver = Driver(name=body.name.strip(), phone=phone,
                    community=body.community.strip(),
                    vehicle_type=body.vehicle_type,
                    available=body.available, source="roster")
    db.add(driver)
    db.commit()
    return _view(db, driver)


class DriverPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    community: Optional[str] = Field(default=None, max_length=120)
    vehicle_type: Optional[str] = None
    available: Optional[bool] = None


@router.patch("/{driver_id}")
def edit_driver(driver_id: str, body: DriverPatch,
                db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(404, "No such driver")

    if body.available is False:
        run = _active_dispatch(db, driver.id)
        # Taking a man off the roster while he is driving a woman to a facility
        # removes the only row that says where she is. He can be retired when
        # the run ends; refusing now is the safe direction.
        if run is not None and run.status == "accepted":
            raise HTTPException(
                409, "{} is on a run right now. Retire him once it ends.".format(
                    driver.name))

    if body.name is not None:
        driver.name = body.name.strip() or driver.name
    if body.community is not None:
        driver.community = body.community.strip() or driver.community
    if body.vehicle_type is not None:
        if body.vehicle_type not in VEHICLES:
            raise HTTPException(422, "Unknown vehicle type")
        driver.vehicle_type = body.vehicle_type
    if body.available is not None:
        driver.available = body.available

    db.commit()
    return _view(db, driver)


@router.get("/for-patient/{patient_id}")
def queue_for_patient(patient_id: str, db: Session = Depends(get_db),
                      user: User = Depends(current_user)):
    """Who would be rung for this woman, in the order they would be rung.

    Ranking that only runs during an emergency cannot be checked before one.
    This is the same function the cascade calls, so what a worker reads here on
    a quiet Tuesday is what will happen at two in the morning.
    """
    from ..security import patient_in_reach
    patient = patient_in_reach(db, patient_id, user)

    named = (db.query(CareCircleMember)
               .filter(CareCircleMember.patient_id == patient_id,
                       CareCircleMember.role == "driver").first())
    named_phone = named.phone if named and named.phone else None

    queue = []
    for position, driver in enumerate(services.rank_drivers(db, patient), 1):
        view = _view(db, driver)
        if named_phone and driver.phone == named_phone:
            why = "She named him herself"
        elif driver.community == patient.community:
            why = "Her own community"
        else:
            why = "Nearest village with a vehicle"
        queue.append({**view, "position": position, "why": why})

    return {"patient_id": patient_id,
            "community": patient.community,
            "named_driver": named.name if named else None,
            "queue": queue}


class LocationIn(BaseModel):
    note: str = Field(min_length=1, max_length=200)


@router.post("/dispatches/{dispatch_id}/location")
def log_location(dispatch_id: str, body: LocationIn,
                 db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    """Where the vehicle is, as the driver said it on the phone.

    Typed by a person, because the driver's handset cannot report a position.
    Kept here alongside the roster so the one screen that watches a run does not
    have to reach into the emergency API to write down an answer.
    """
    dispatch = db.get(Dispatch, dispatch_id)
    if dispatch is None:
        raise HTTPException(404, "No such dispatch")
    if not services.is_open(db.get(Emergency, dispatch.emergency_id)):
        raise HTTPException(409, "That case is closed")
    services.log_driver_location(db, dispatch, body.note.strip())
    db.commit()
    return {"dispatch_id": dispatch.id,
            "location_note": dispatch.location_note,
            "location_at": dispatch.location_at.isoformat()
            if dispatch.location_at else None}
