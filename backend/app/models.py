"""Database schema.

The event log is the source of truth. Everything else in this file is either
reference data (people, drivers, facilities, the food table) or a projection --
a cached fold of the log kept for query speed and always rebuildable from it.

Two writers act on the same patient by design: the cloud scheduler writing call
results, and a health worker recording a visit offline. Both append; neither
overwrites. That is why a worker who syncs three days late cannot destroy data.
"""
import datetime as dt

from sqlalchemy import (JSON, Boolean, Column, Date, DateTime, Float, ForeignKey,
                        Integer, String, Text, UniqueConstraint, event)
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import relationship

from .db import Base
from .ids import uuid7


def now() -> dt.datetime:
    return dt.datetime.utcnow()


# --------------------------------------------------------------- people


class User(Base):
    """A health worker. Roles: cho, nutrition_officer, nurse, admin."""
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=uuid7)
    name = Column(String, nullable=False)
    phone = Column(String, unique=True, nullable=False)
    pin_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="cho")
    community = Column(String)
    facility_id = Column(String, ForeignKey("facilities.id"))
    language = Column(String, default="dagbani")
    created_at = Column(DateTime, default=now)

    facility = relationship("Facility", back_populates="staff")


class Facility(Base):
    __tablename__ = "facilities"

    id = Column(String, primary_key=True, default=uuid7)
    name = Column(String, nullable=False)
    community = Column(String, nullable=False)
    region = Column(String, nullable=False)
    phone = Column(String)
    created_at = Column(DateTime, default=now)

    staff = relationship("User", back_populates="facility")


class NurseShift(Base):
    """The on-call roster.

    Deliberately a roster and not presence detection: a nurse marks herself on
    call, and that is all the system claims to know. Cascade order is by
    position, then facility.
    """
    __tablename__ = "nurse_shifts"

    id = Column(String, primary_key=True, default=uuid7)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    facility_id = Column(String, ForeignKey("facilities.id"), nullable=False)
    on_call = Column(Boolean, default=False)
    position = Column(Integer, default=1)
    shift_start = Column(String, default="08:00")
    shift_end = Column(String, default="20:00")

    user = relationship("User")
    facility = relationship("Facility")


class Driver(Base):
    """Community transport. Matched by community, never by GPS.

    Most riders are on feature phones in villages, so there is no live location
    to match on. The community is the unit of dispatch, which is also how it
    actually happens.
    """
    __tablename__ = "drivers"

    id = Column(String, primary_key=True, default=uuid7)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    community = Column(String, nullable=False)
    vehicle_type = Column(String, default="motorking")
    available = Column(Boolean, default=True)
    accepted_count = Column(Integer, default=0)
    offered_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=now)

    @property
    def response_rate(self) -> float:
        if not self.offered_count:
            return 0.5  # unproven drivers rank mid-table, not last
        return self.accepted_count / float(self.offered_count)


# --------------------------------------------------------------- patients


class Patient(Base):
    """A pregnant or lactating woman. Children hang off her record."""
    __tablename__ = "patients"

    id = Column(String, primary_key=True, default=uuid7)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=False)
    secondary_phone = Column(String)
    language = Column(String, default="dagbani")
    community = Column(String, nullable=False)
    region = Column(String, nullable=False, default="Northern")
    lmp = Column(Date)
    edd = Column(Date)
    affordability = Column(String, default="low")   # low | medium
    taboos = Column(JSON, default=list)             # food keys she will not eat
    # Geography is the whole point of Delay 2, so it is captured at enrolment
    # rather than inferred. Walking minutes, because that is the unit a CHO
    # actually knows and a kilometre on a bad road is not a kilometre.
    minutes_to_facility = Column(Integer)
    road_condition = Column(String, default="fair")  # good | fair | poor
    consent = Column(Boolean, default=False)
    consent_at = Column(DateTime)
    assigned_cho_id = Column(String, ForeignKey("users.id"))
    facility_id = Column(String, ForeignKey("facilities.id"))
    status = Column(String, default="active")       # active | delivered | closed
    created_at = Column(DateTime, default=now)

    children = relationship("Child", back_populates="patient")
    state = relationship("PatientState", uselist=False, back_populates="patient")


class Child(Base):
    __tablename__ = "children"

    id = Column(String, primary_key=True, default=uuid7)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)
    name = Column(String, nullable=False)
    dob = Column(Date)
    sex = Column(String)
    created_at = Column(DateTime, default=now)

    patient = relationship("Patient", back_populates="children")

    def age_months(self, on=None) -> int:
        if not self.dob:
            return 0
        on = on or dt.date.today()
        return (on.year - self.dob.year) * 12 + (on.month - self.dob.month)


# --------------------------------------------------------------- the log


class Event(Base):
    """Append-only. Never updated, never deleted.

    `occurred_at` is clinical truth -- when the thing happened. `recorded_at` is
    when it was entered, and `server_received_at` is when it arrived. Replay
    orders on occurred_at; audit reads recorded_at; the gap between recorded_at
    and server_received_at is the device's clock offset, which we store rather
    than try to correct.
    """
    __tablename__ = "events"

    event_id = Column(String, primary_key=True)      # client-generated UUIDv7
    patient_id = Column(String, ForeignKey("patients.id"), index=True)
    actor_id = Column(String)                        # user id, or "system"
    event_type = Column(String, nullable=False, index=True)
    payload = Column(JSON, default=dict)
    occurred_at = Column(DateTime, nullable=False, index=True)
    recorded_at = Column(DateTime, nullable=False)
    server_received_at = Column(DateTime, default=now)
    device_id = Column(String, default="server")
    seq = Column(Integer, default=0)

    @property
    def clock_offset_seconds(self) -> float:
        if not self.server_received_at or not self.recorded_at:
            return 0.0
        return (self.server_received_at - self.recorded_at).total_seconds()


class PatientState(Base):
    """A projection. Rebuildable from the log at any time; never authoritative.

    Kept only so the worklist can be sorted without folding every log on every
    request.
    """
    __tablename__ = "patient_state"

    patient_id = Column(String, ForeignKey("patients.id"), primary_key=True)
    risk_level = Column(String, default="green")     # green | amber | red
    reason_codes = Column(MutableList.as_mutable(JSON), default=list)
    red_open = Column(Boolean, default=False)        # a RED stays RED until a human closes it
    last_contact_at = Column(DateTime)
    last_contact_outcome = Column(String)
    consecutive_unreachable = Column(Integer, default=0)
    mdd_score = Column(Integer)
    mdd_instrument = Column(String)                  # mdd_w | mdd_child
    mdd_missing_groups = Column(MutableList.as_mutable(JSON), default=list)
    muac_mother = Column(Float)
    muac_child = Column(Float)
    ifa_adherent = Column(Boolean)
    events_folded = Column(Integer, default=0)
    updated_at = Column(DateTime, default=now, onupdate=now)

    patient = relationship("Patient", back_populates="state")


# --------------------------------------------------------------- scheduling


class Contact(Base):
    """The WHO eight-contact schedule, materialised per patient at enrolment."""
    __tablename__ = "contacts"

    id = Column(String, primary_key=True, default=uuid7)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)
    week = Column(Integer, nullable=False)           # gestational week
    due_date = Column(Date, nullable=False)
    kind = Column(String, default="anc")             # anc | postnatal
    include_diet = Column(Boolean, default=False)    # diet block rotates; triage does not
    status = Column(String, default="pending")       # pending | done | missed
    attempts = Column(Integer, default=0)
    completed_at = Column(DateTime)

    __table_args__ = (UniqueConstraint("patient_id", "week", "kind"),)


# --------------------------------------------------------------- telephony


class CallSession(Base):
    """One IVR call. State lives here because every keypress is a fresh request."""
    __tablename__ = "call_sessions"

    id = Column(String, primary_key=True)            # provider sessionId
    patient_id = Column(String, ForeignKey("patients.id"), index=True)
    contact_id = Column(String, ForeignKey("contacts.id"))
    direction = Column(String, default="outbound")   # outbound | inbound
    phone = Column(String)
    provider = Column(String, default="simulator")
    provider_session_id = Column(String, index=True)  # the provider's own id
    ringing = Column(Boolean, default=False)         # simulator: on screen, unanswered
    purpose = Column(String, default="outreach")     # outreach | driver | nurse | hotline
    emergency_id = Column(String)
    driver_id = Column(String)
    language = Column(String, default="dagbani")
    state = Column(String, default="greet")
    cursor = Column(Integer, default=0)              # index within the current block
    answers = Column(MutableDict.as_mutable(JSON), default=dict)
    include_diet = Column(Boolean, default=False)
    escalated_to_nurse = Column(Boolean, default=False)
    finalised = Column(Boolean, default=False)       # folded into the log already
    no_input = Column(Integer, default=0)            # consecutive silent turns
    nurse_attempt = Column(Integer, default=0)
    outcome = Column(String)                         # completed | unreachable | dropped | nurse
    started_at = Column(DateTime, default=now)
    ended_at = Column(DateTime)
    transcript = Column(MutableList.as_mutable(JSON), default=list)


class Message(Base):
    """Every SMS the platform sends, so a demo can show what a handset received."""
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=uuid7)
    to_phone = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    kind = Column(String, default="alert")
    patient_id = Column(String, ForeignKey("patients.id"))
    provider = Column(String, default="simulator")
    provider_id = Column(String)
    status = Column(String, default="sent")
    error = Column(Text)
    created_at = Column(DateTime, default=now)


class UssdSession(Base):
    __tablename__ = "ussd_sessions"

    id = Column(String, primary_key=True)
    phone = Column(String)
    user_id = Column(String, ForeignKey("users.id"))
    cursor = Column(JSON, default=dict)
    created_at = Column(DateTime, default=now)


class CallbackRequest(Base):
    """A missed call we owe a call back on.

    She rings and hangs up; we call her. She spends nothing, which matters most
    at exactly the moment she has no credit.
    """
    __tablename__ = "callback_requests"

    id = Column(String, primary_key=True, default=uuid7)
    phone = Column(String, nullable=False)
    patient_id = Column(String, ForeignKey("patients.id"))
    status = Column(String, default="pending")       # pending | called | failed
    requested_at = Column(DateTime, default=now)
    called_at = Column(DateTime)


# --------------------------------------------------------------- emergencies


class Emergency(Base):
    __tablename__ = "emergencies"

    id = Column(String, primary_key=True, default=uuid7)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False, index=True)
    reason_codes = Column(MutableList.as_mutable(JSON), default=list)
    source = Column(String, default="ivr")           # ivr | visit | hotline
    status = Column(String, default="pending_validation")
    # pending_validation -> validated -> dispatching -> transporting
    #                    -> arrived -> closed  (or cancelled)
    validated_by = Column(String, ForeignKey("users.id"))
    validated_at = Column(DateTime)
    facility_id = Column(String, ForeignKey("facilities.id"))
    facility_notified_at = Column(DateTime)
    arrived_at = Column(DateTime)
    outcome = Column(String)                         # care_received | not_reached | refused | other
    outcome_note = Column(Text)
    closed_by = Column(String, ForeignKey("users.id"))
    closed_at = Column(DateTime)
    created_at = Column(DateTime, default=now)

    dispatches = relationship("Dispatch", back_populates="emergency")


class Dispatch(Base):
    __tablename__ = "dispatches"

    id = Column(String, primary_key=True, default=uuid7)
    emergency_id = Column(String, ForeignKey("emergencies.id"), nullable=False)
    driver_id = Column(String, ForeignKey("drivers.id"), nullable=False)
    position = Column(Integer, default=1)            # position in the cascade
    status = Column(String, default="offered")       # offered | accepted | declined | no_answer | cancelled
    offered_at = Column(DateTime, default=now)
    responded_at = Column(DateTime)
    location_note = Column(String)                   # as verbally reported, nothing automatic
    location_at = Column(DateTime)

    emergency = relationship("Emergency", back_populates="dispatches")
    driver = relationship("Driver")


# --------------------------------------------------------------- settings


class CareCircleMember(Base):
    """The people around her who actually determine whether she reaches care.

    From the team's own design, and it closes a real gap. Three of the four
    roles map directly onto the Three Delays, which is why this is more than a
    contact list:

      decision_maker  Delay 1. In much of Northern Ghana the woman does not
                      decide alone whether to seek care; a husband or a
                      mother-in-law does. A platform that only ever calls her is
                      talking to someone who may not hold the decision.
      driver          Delay 2. Her own community's transport, known in advance
                      rather than found at midnight.
      payer           The money barrier, which is not one of the classic three
                      delays and stops just as many journeys. Usually an NHIS
                      number, sometimes a person.
      emergency       Whoever is called when she cannot be reached at all.

    Her own phone is often not hers -- it is frequently the husband's -- so
    recording who else can be reached, by name, is the difference between an
    alert landing and an alert evaporating.
    """
    __tablename__ = "care_circle"

    id = Column(String, primary_key=True, default=uuid7)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False,
                        index=True)
    role = Column(String, nullable=False)   # decision_maker|driver|payer|emergency
    name = Column(String, nullable=False)
    phone = Column(String)
    detail = Column(String)                 # NHIS number, relationship, vehicle
    confirmed = Column(Boolean, default=False)
    confirmed_at = Column(DateTime)
    created_at = Column(DateTime, default=now)

    __table_args__ = (UniqueConstraint("patient_id", "role"),)


class Phrase(Base):
    """One line of the call script, in one language.

    The unit the language pipeline works on. English is the source of truth;
    everything else is derived and can be regenerated, except a recorded human
    take, which cannot and is therefore never overwritten automatically.
    """
    __tablename__ = "phrases"

    id = Column(String, primary_key=True, default=uuid7)
    key = Column(String, nullable=False, index=True)     # e.g. danger_bleeding
    language = Column(String, nullable=False, index=True)
    category = Column(String, default="script")          # script | diet | food
    source_text = Column(Text, nullable=False)           # the English
    translated_text = Column(Text)
    # What this said before the English changed. Kept because a translation
    # cannot be regenerated on demand when the provider quota is gone, and
    # discarding one to keep a status column tidy is a bad trade.
    previous_text = Column(Text)
    status = Column(String, default="pending")
    # pending | translated | failed | unsupported | reviewed | stale
    provider = Column(String)                            # khaya | manual
    error = Column(Text)
    reviewed_by = Column(String, ForeignKey("users.id"))
    reviewed_at = Column(DateTime)
    audio_path = Column(String)                          # relative to backend/audio
    audio_source = Column(String)                        # khaya_tts | recorded
    audio_bytes = Column(Integer)
    updated_at = Column(DateTime, default=now, onupdate=now)

    __table_args__ = (UniqueConstraint("key", "language"),)


class Setting(Base):
    """Operational configuration entered from the browser.

    Held here rather than in the environment so that the platform can be
    configured by someone without shell access, which is the realistic case for
    a CHPS deployment.
    """
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=now, onupdate=now)


# ---------------------------------------------------- one form for a number

# Every phone column in this file, normalised on the way in, wherever the write
# came from. Doing it in the API handlers alone was not enough: the seed writes
# directly, the sync endpoint writes from an offline device's payload, the
# telephony layer writes from a provider callback, and each of those is a place
# for a number to enter in a different spelling and then never match a lookup
# again. Attaching it to the mapper means there is exactly one way a phone
# number can be stored, and no new code path can opt out of it by accident.
_PHONE_COLUMNS = {
    "users": ("phone",),
    "facilities": ("phone",),
    "drivers": ("phone",),
    "patients": ("phone", "secondary_phone"),
    "call_sessions": ("phone",),
    "messages": ("to_phone",),
    "callback_requests": ("phone",),
    "care_circle": ("phone",),
}


def _normalise_phones(mapper, connection, target):
    from .phones import normalise

    for field in _PHONE_COLUMNS.get(target.__tablename__, ()):
        current = getattr(target, field, None)
        if current:
            fixed = normalise(current)
            if fixed and fixed != current:
                setattr(target, field, fixed)


for _model in Base.registry.mappers:
    if _model.class_.__tablename__ in _PHONE_COLUMNS:
        event.listen(_model.class_, "before_insert", _normalise_phones)
        event.listen(_model.class_, "before_update", _normalise_phones)
