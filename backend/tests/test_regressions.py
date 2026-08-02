"""Regression tests.

Every test here corresponds to a bug that was actually reachable in the shipped
build, most of them found by adversarial review rather than by writing tests
first. They are separated from the main suite deliberately: this file is the
record of what went wrong, and each name states the failure rather than the
feature.
"""
import datetime as dt
import os
import tempfile

import pytest

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tempfile.mkdtemp(), "regressions.db")
os.environ["SEED_ON_START"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app import events as ev  # noqa: E402
from app import services  # noqa: E402
from app.db import Base, SessionLocal, engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (CallSession, Contact, Dispatch, Emergency, Event,  # noqa: E402
                        Message, Patient, PatientState)
from app.telephony import service as tel  # noqa: E402


@pytest.fixture(scope="module")
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    from app.seed import seed
    seed(session)
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.clear()
    session.close()


@pytest.fixture(scope="module")
def client(db):
    return TestClient(app)


@pytest.fixture(scope="module")
def auth(client):
    r = client.post("/api/auth/login",
                    json={"phone": "+233200000001", "pin": "1234"})
    return {"Authorization": "Bearer " + r.json()["token"]}


def _voice(client, **fields):
    payload = {"isActive": "1", "direction": "outbound"}
    payload.update({k: str(v) for k, v in fields.items()})
    return client.post("/api/telephony/voice", data=payload)


def _start(db, patient, purpose="outreach", diet=False):
    session, result = tel.start_call(db, phone=patient.phone,
                                     patient_id=patient.id, purpose=purpose,
                                     language="english", include_diet=diet)
    db.commit()
    assert result.ok
    return session


# ------------------------------------------------------------------ IVR


def test_silence_does_not_loop_the_greeting_forever(db, client):
    """She may simply be listening. The call must end, not replay for ever."""
    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    session = _start(db, patient)
    for _ in range(6):
        _voice(client, sessionId=session.id, dtmfDigits="",
               destinationNumber=patient.phone)
    db.expire_all()
    refreshed = db.get(CallSession, session.id)
    assert refreshed.ended_at is not None, "the greeting looped for ever"
    assert refreshed.outcome == "no_input"


def test_a_timeout_is_never_recorded_as_a_denial(db, client):
    """The worst possible bug for a product whose slogan is that silence is not safety."""
    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    session = _start(db, patient)
    _voice(client, sessionId=session.id, destinationNumber=patient.phone)
    _voice(client, sessionId=session.id, dtmfDigits="1",
           destinationNumber=patient.phone)          # yes, a good time
    # Now say nothing at all to the bleeding question, twice.
    _voice(client, sessionId=session.id, dtmfDigits="",
           destinationNumber=patient.phone)
    _voice(client, sessionId=session.id, dtmfDigits="",
           destinationNumber=patient.phone)
    db.expire_all()
    answers = db.get(CallSession, session.id).answers or {}
    assert answers.get("danger", {}).get("bleeding") is None, \
        "an unanswered question was recorded as 'no'"


def test_a_stray_key_is_not_recorded_as_a_denial(db, client):
    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    session = _start(db, patient)
    _voice(client, sessionId=session.id, destinationNumber=patient.phone)
    _voice(client, sessionId=session.id, dtmfDigits="1",
           destinationNumber=patient.phone)
    _voice(client, sessionId=session.id, dtmfDigits="7",
           destinationNumber=patient.phone)          # misdial
    db.expire_all()
    answers = db.get(CallSession, session.id).answers or {}
    assert "bleeding" not in answers.get("danger", {}), \
        "a misdial cleared a danger sign"


def test_an_extra_keypress_does_not_duplicate_the_whole_call(db, client):
    """A judge double-tapping used to manufacture a clinical finding."""
    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    session = _start(db, patient)
    _voice(client, sessionId=session.id, destinationNumber=patient.phone)
    _voice(client, sessionId=session.id, dtmfDigits="1",
           destinationNumber=patient.phone)
    for _ in range(5):
        _voice(client, sessionId=session.id, dtmfDigits="2",
               destinationNumber=patient.phone)
    _voice(client, sessionId=session.id, dtmfDigits="1",
           destinationNumber=patient.phone)          # birth plan -> ends

    before = db.query(Event).filter(Event.patient_id == patient.id).count()
    for _ in range(3):
        _voice(client, sessionId=session.id, dtmfDigits="1",
               destinationNumber=patient.phone)
    db.expire_all()
    after = db.query(Event).filter(Event.patient_id == patient.id).count()
    assert after == before, "late keypresses re-folded the call into the log"


def test_pressing_9_keeps_what_she_already_told_us(db, client):
    """She reports bleeding, then asks for a person. Losing that is unforgivable."""
    patient = db.query(Patient).filter(Patient.name == "Hawa Sulemana").first()
    session = _start(db, patient)
    _voice(client, sessionId=session.id, destinationNumber=patient.phone)
    _voice(client, sessionId=session.id, dtmfDigits="1",
           destinationNumber=patient.phone)
    _voice(client, sessionId=session.id, dtmfDigits="1",
           destinationNumber=patient.phone)          # yes, bleeding
    _voice(client, sessionId=session.id, dtmfDigits="9",
           destinationNumber=patient.phone)          # take me to a nurse
    db.expire_all()
    signs = [e for e in ev.load(db, patient.id)
             if e.event_type == ev.DANGER_SIGNS
             and "bleeding" in (e.payload or {}).get("signs", [])]
    assert signs, "her danger signs were discarded on the way to the nurse"


# ------------------------------------------------------------- dispatch


def test_a_driver_who_never_answers_advances_the_queue(db, client, auth):
    """This used to strand an emergency in 'dispatching' with nobody told."""
    patient = db.query(Patient).filter(Patient.name == "Rahma Osman").first()
    emergency = services.raise_emergency(db, patient, ["sign.bleeding"], "visit")
    db.commit()
    client.post("/api/emergencies/{}/validate".format(emergency.id), headers=auth)
    db.expire_all()

    first = [d for d in db.get(Emergency, emergency.id).dispatches][0]
    session = (db.query(CallSession)
                 .filter(CallSession.driver_id == first.driver_id,
                         CallSession.emergency_id == emergency.id).first())
    client.post("/api/telephony/voice",
                data={"sessionId": session.id, "isActive": "0",
                      "direction": "outbound",
                      "destinationNumber": session.phone})
    db.expire_all()
    dispatches = db.get(Emergency, emergency.id).dispatches
    assert len(dispatches) >= 2, "the cascade stopped at a silent phone"
    assert dispatches[0].status == "no_answer"


def test_two_drivers_cannot_both_accept(db, client, auth):
    patient = db.query(Patient).filter(Patient.name == "Zeinab Mahama").first()
    emergency = services.raise_emergency(db, patient, ["sign.convulsions"], "visit")
    db.commit()
    client.post("/api/emergencies/{}/validate".format(emergency.id), headers=auth)
    db.expire_all()

    emergency = db.get(Emergency, emergency.id)
    services.offer_next_driver(db, emergency)
    db.flush()
    offered = [d for d in emergency.dispatches if d.status == "offered"]
    for dispatch in offered:
        services.driver_responded(db, dispatch, True)
    db.flush()
    accepted = [d for d in emergency.dispatches if d.status == "accepted"]
    assert len(accepted) == 1, "one woman was assigned two vehicles"


def test_double_tapping_confirm_does_not_ring_two_drivers(db, client, auth):
    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    emergency = services.raise_emergency(db, patient, ["sign.fits"], "visit")
    db.commit()
    url = "/api/emergencies/{}/validate".format(emergency.id)
    client.post(url, headers=auth)
    client.post(url, headers=auth)
    db.expire_all()
    offered = [d for d in db.get(Emergency, emergency.id).dispatches]
    assert len(offered) == 1, "a second tap dispatched a second vehicle"


def test_a_new_sign_on_an_open_emergency_still_alerts_the_cho(db, client):
    patient = db.query(Patient).filter(Patient.name == "Zeinab Mahama").first()
    before = db.query(Message).filter(Message.kind == "red_alert").count()
    services.raise_emergency(db, patient, ["sign.bleeding"], "ivr")
    db.commit()
    after = db.query(Message).filter(Message.kind == "red_alert").count()
    assert after > before, "a worsening woman generated no alert"


# ------------------------------------------------------------ sync / data


def test_an_offline_enrolment_becomes_a_real_patient(db, client, auth):
    """The CHO was told it synced. The woman did not exist."""
    body = {"events": [{
        "event_id": "offline-enrol-1", "event_type": "enrolment",
        "payload": {"name": "Offline Woman", "phone": "+233240000911",
                    "community": "Kpale", "language": "dagbani",
                    "consent": True,
                    "edd": (dt.date.today() + dt.timedelta(days=90)).isoformat()},
        "occurred_at": dt.datetime.utcnow().isoformat(), "device_id": "phone-x"}]}
    client.post("/api/sync/push", headers=auth, json=body)
    db.expire_all()
    created = db.query(Patient).filter(Patient.phone == "+233240000911").first()
    assert created is not None, "the household was silently lost"
    assert created.name == "Offline Woman"
    assert db.query(Contact).filter(
        Contact.patient_id == created.id).count() == 8, "no contact schedule"


def test_pushing_the_same_offline_enrolment_twice_creates_one_woman(db, client, auth):
    body = {"events": [{
        "event_id": "offline-enrol-2", "event_type": "enrolment",
        "payload": {"name": "Repeat Woman", "phone": "+233240000912",
                    "community": "Kpale", "consent": True},
        "occurred_at": dt.datetime.utcnow().isoformat(), "device_id": "phone-x"}]}
    client.post("/api/sync/push", headers=auth, json=body)
    client.post("/api/sync/push", headers=auth, json=body)
    db.expire_all()
    assert db.query(Patient).filter(
        Patient.phone == "+233240000912").count() == 1


def test_enrolling_the_same_woman_twice_online_creates_one_patient(db, client, auth):
    body = {"name": "Retry Woman", "phone": "+233240000913",
            "community": "Kpale", "consent": True, "event_id": "enrol-retry-9",
            "edd": (dt.date.today() + dt.timedelta(days=120)).isoformat()}
    for _ in range(3):
        client.post("/api/patients", headers=auth, json=body)
    db.expire_all()
    assert db.query(Patient).filter(
        Patient.phone == "+233240000913").count() == 1


def test_an_event_for_a_patient_who_does_not_exist_is_rejected(db, client, auth):
    before = db.query(PatientState).count()
    out = client.post("/api/sync/push", headers=auth, json={"events": [{
        "event_id": "ghost-1", "patient_id": "no-such-patient",
        "event_type": "visit_recorded", "payload": {},
        "occurred_at": dt.datetime.utcnow().isoformat()}]}).json()
    db.expire_all()
    assert out["rejected"], "a ghost patient was accepted"
    assert db.query(PatientState).count() == before


def test_a_malformed_measurement_does_not_500_the_patient(db, client, auth):
    """A stringified number used to poison that patient's every later read."""
    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    out = client.post("/api/sync/push", headers=auth, json={"events": [{
        "event_id": "bad-muac-1", "patient_id": patient.id,
        "event_type": "muac_measured",
        "payload": {"subject": "child", "value_cm": "11.0"},
        "occurred_at": dt.datetime.utcnow().isoformat()}]})
    assert out.status_code == 200
    assert client.get("/api/patients/{}".format(patient.id),
                      headers=auth).status_code == 200


# ------------------------------------------------------------- scheduler


def test_the_scheduler_actually_places_the_calls_that_are_due(db, client, auth):
    """The loop the whole product is named for. It previously had no trigger."""
    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    contact = (db.query(Contact)
                 .filter(Contact.patient_id == patient.id,
                         Contact.status == "pending").first())
    contact.due_date = dt.date.today() - dt.timedelta(days=1)
    db.commit()

    out = client.post("/api/contacts/run-due", headers=auth).json()
    assert out["placed"], "nothing was called even though a contact was due"
    db.expire_all()
    assert (db.get(Contact, contact.id).attempts or 0) >= 1


def test_the_scheduler_gives_up_after_three_tries_and_asks_for_a_visit(db, client, auth):
    patient = db.query(Patient).filter(Patient.name == "Rahma Osman").first()
    contact = (db.query(Contact)
                 .filter(Contact.patient_id == patient.id,
                         Contact.status == "pending").first())
    contact.due_date = dt.date.today() - dt.timedelta(days=1)
    contact.attempts = 3
    db.commit()
    client.post("/api/contacts/run-due", headers=auth)
    db.expire_all()
    assert db.get(Contact, contact.id).status == "missed"


# ---------------------------------------------------------------- access


def test_distance_escalates_a_symptom_but_not_a_missed_tablet(db):
    """The geography rule was dead code against columns that did not exist."""
    from app.engines.risk import AMBER, RED, classify

    class Far:
        minutes_to_facility = 120
        road_condition = "poor"

    class Snap:
        danger_signs = {"fever": dt.datetime.utcnow()}
        cleared_signs = {}
        mdd_score = None; mdd_instrument = None; mdd_missing = []
        mdd_history = []; muac_mother = None; muac_child = None
        ifa_adherent = None; last_contact_at = None
        last_contact_outcome = None; consecutive_unreachable = 0
        red_open = False; delivered = False; unanswered = {}
        events_folded = 0

        @property
        def active_danger_signs(self):
            return list(self.danger_signs)

    symptom = Snap()
    assert classify(symptom, Far()).level == RED

    adherence = Snap()
    adherence.danger_signs = {}
    adherence.ifa_adherent = False
    verdict = classify(adherence, Far())
    assert verdict.level == AMBER, \
        "a missed iron tablet dispatched a vehicle because the road is poor"


# ------------------------------------------------------------- language


def test_the_catalogue_covers_everything_the_platform_says(db):
    """A new danger sign or food must not silently escape translation."""
    from app.language.catalogue import by_key
    from app.prompts import DANGER_QUESTIONS
    from app.data.foods import FOODS

    keys = by_key()
    for sign, _ in DANGER_QUESTIONS:
        assert "danger_" + sign in keys
    for food in FOODS:
        assert "food_" + food["key"] in keys


def test_gonja_is_declared_unsupported_rather_than_silently_failing(db):
    from app.language import khaya, pipeline
    result = khaya.translate("Are you bleeding?", "gonja")
    assert result.ok is False
    assert "Guang" in result.error
    assert pipeline.status(db, "gonja")["can_translate"] is False


def test_the_shipped_corpus_speaks_real_dagbani(db):
    """The demo must not depend on an API with a two-week quota."""
    from app.language import pipeline
    from app.models import Phrase

    pipeline.sync_catalogue(db, "dagbani")
    db.flush()
    row = (db.query(Phrase)
             .filter(Phrase.language == "dagbani",
                     Phrase.key == "danger_bleeding").first())
    assert row.translated_text, "the shipped corpus is empty"
    assert row.translated_text != row.source_text
    # Dagbani orthography uses characters English does not.
    assert any(ch in row.translated_text for ch in "ɛɣŋʒɔɨ")


def test_a_translation_that_is_really_an_error_page_is_rejected():
    from app.language.khaya import validate
    assert validate("Are you bleeding?", "<!DOCTYPE html><html>", "dagbani")
    assert validate("Are you bleeding?", "", "dagbani")
    assert validate("Are you bleeding?", "Are you bleeding?", "dagbani")
    assert validate("Are you bleeding?", "A dɔɣiri kambɔŋ ni ʒim mali a?",
                    "dagbani") is None


def test_a_recorded_voice_is_never_overwritten_by_a_generated_one(db):
    """Re-running the pipeline must not undo an evening in a recording room."""
    from app.language import pipeline
    from app.models import Phrase

    pipeline.sync_catalogue(db, "dagbani")
    phrase = (db.query(Phrase)
                .filter(Phrase.language == "dagbani",
                        Phrase.key == "closing").first())
    pipeline.write_audio(db, phrase, b"x" * 2000, source="recorded")
    db.flush()

    out = pipeline.speak_translated(db, "dagbani", limit=50)
    db.expire_all()
    again = db.get(Phrase, phrase.id)
    assert again.audio_source == "recorded", "a human take was overwritten"
    assert out["generated"] == 0 or again.audio_source == "recorded"


def test_coverage_reports_what_a_caller_actually_hears(db):
    """The honest number: translated text is not the same as a spoken clip."""
    from app.language import pipeline
    status = pipeline.status(db, "dagbani")
    assert status["translated"] >= 70
    assert status["spoken_coverage"] <= 100
    assert status["needs_recording"] == status["total"] - status["with_audio"]
