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
from app.models import (CallSession, Contact, Dispatch, Driver, Emergency,  # noqa: E402
                        Event, Message, Patient, PatientState, User)
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
    # A real WAV header, because write_audio now refuses anything that is not
    # audio. That check exists because a 2 kB run of the letter "x" -- written
    # by an earlier version of this very test -- reached production and every
    # Dagbani call ended on it.
    import io
    import wave
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x01" * 8000)
    pipeline.write_audio(db, phrase, buffer.getvalue(), source="recorded")
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


# ------------------------------------------------------- offline visits


def test_a_queued_visit_keeps_the_arm_measurement(db, client, auth):
    """The offline path dropped MUAC, iron and the note while reporting success."""
    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    body = {"events": [{
        "event_id": "offline-visit-1", "patient_id": patient.id,
        "event_type": "visit_recorded",
        "payload": {"signs": ["fever"], "denied": ["bleeding"],
                    "muac_mother": 21.8, "muac_child": 12.2,
                    "ifa_adherent": False, "note": "seen at home"},
        "occurred_at": dt.datetime.utcnow().isoformat(), "device_id": "phone-y"}]}
    client.post("/api/sync/push", headers=auth, json=body)
    db.expire_all()
    state = db.get(PatientState, patient.id)
    assert state.muac_mother == 21.8, "the arm measurement was dropped"
    assert state.muac_child == 12.2
    assert state.ifa_adherent is False


def test_pushing_the_same_queued_visit_twice_is_harmless(db, client, auth):
    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    body = {"events": [{
        "event_id": "offline-visit-2", "patient_id": patient.id,
        "event_type": "visit_recorded",
        "payload": {"muac_mother": 20.1},
        "occurred_at": dt.datetime.utcnow().isoformat(), "device_id": "phone-y"}]}
    client.post("/api/sync/push", headers=auth, json=body)
    before = db.query(Event).filter(Event.patient_id == patient.id).count()
    client.post("/api/sync/push", headers=auth, json=body)
    db.expire_all()
    after = db.query(Event).filter(Event.patient_id == patient.id).count()
    assert after == before, "a repeated flush duplicated the visit"


def test_the_funnel_reports_every_stage_of_the_three_delays(db, client, auth):
    out = client.get("/api/metrics", headers=auth).json()
    stages = [f["stage"] for f in out["funnel"]]
    assert len(stages) == 5
    assert "Danger sign detected" in stages[0]
    assert "Outcome recorded" in stages[-1]
    assert all("delay" in f and "lost" in f for f in out["funnel"])


def test_geography_is_actually_collected_at_enrolment(db, client, auth):
    """The rule that reads these fields was dead code once already."""
    body = {"name": "Far Woman", "phone": "+233240000922", "community": "Kpale",
            "consent": True, "minutes_to_facility": 120, "road_condition": "poor",
            "edd": (dt.date.today() + dt.timedelta(days=60)).isoformat()}
    out = client.post("/api/patients", headers=auth, json=body).json()
    assert out["minutes_to_facility"] == 120
    assert out["road_condition"] == "poor"

    created = db.query(Patient).filter(Patient.phone == "+233240000922").first()
    ev.append(db, patient_id=created.id, event_type=ev.DANGER_SIGNS,
              payload={"signs": ["fever"], "denied": []})
    state = ev.refresh_state(db, created.id)
    db.commit()
    assert state.risk_level == "red", \
        "a symptom two hours from care on a poor road should not wait a week"
    assert "access.remote" in (state.reason_codes or [])


def test_care_received_clears_the_sign_but_not_reaching_care_does_not(db, client, auth):
    """Found by running three actors through one emergency end to end.

    Leaving her permanently RED after treatment would bury every genuinely new
    emergency under a stale one. But a referral that did not land must keep the
    flag up — that distinction is the entire reason for tracking outcomes rather
    than referrals.
    """
    for outcome, expect_red in (("not_reached", True), ("care_received", False)):
        patient = Patient(name="Outcome " + outcome, phone="+2332400009" + outcome[:2],
                          community="Kpale", region="Northern", consent=True)
        db.add(patient)
        db.flush()
        ev.append(db, patient_id=patient.id, event_type=ev.DANGER_SIGNS,
                  payload={"signs": ["bleeding"], "denied": []})
        ev.refresh_state(db, patient.id)
        emergency = services.raise_emergency(db, patient, ["sign.bleeding"], "ivr")
        db.commit()
        assert db.get(PatientState, patient.id).risk_level == "red"

        client.post("/api/emergencies/{}/outcome".format(emergency.id),
                    headers=auth, json={"outcome": outcome, "note": ""})
        db.expire_all()
        level = db.get(PatientState, patient.id).risk_level
        assert (level == "red") is expect_red, \
            "outcome '{}' left her at {}".format(outcome, level)


# --------------------------------------------------------------- hostile input


@pytest.mark.parametrize("payload,expected", [
    ({}, 422),
    ({"name": "X", "phone": "+233240000441", "community": "K", "consent": False}, 400),
    ({"name": "a" * 500, "phone": "+233240000442", "community": "K", "consent": True}, 422),
    ({"name": "X", "phone": "not-a-number", "community": "K", "consent": True}, 422),
    ({"name": "X", "phone": "+233240000443", "community": "K", "consent": True,
      "minutes_to_facility": -5}, 422),
])
def test_enrolment_refuses_nonsense(client, auth, payload, expected):
    assert client.post("/api/patients", headers=auth, json=payload).status_code == expected


@pytest.mark.parametrize("body", [
    {"instrument": "mdd_w", "present": [], "month": 13},
    {"instrument": "mdd_w", "present": [], "month": 0},
    {"instrument": "not-a-thing", "present": []},
])
def test_nutrition_refuses_impossible_parameters(client, auth, body):
    assert client.post("/api/nutrition/assess", headers=auth, json=body).status_code == 422


def test_a_string_where_a_list_belongs_is_rejected_not_silently_dropped(
        db, client, auth):
    """It used to be iterated character by character, losing the danger sign."""
    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    out = client.post("/api/sync/push", headers=auth, json={"events": [{
        "event_id": "malformed-signs-1", "patient_id": patient.id,
        "event_type": "danger_signs_reported",
        "payload": {"signs": "bleeding"},
        "occurred_at": dt.datetime.utcnow().isoformat()}]}).json()
    assert out["rejected"], "a malformed payload was accepted"
    assert out["accepted"] == 0


def test_nothing_in_the_api_returns_a_500_for_bad_input(client, auth):
    """A 4xx is a conversation. A 5xx is a dropped call and a stuck emergency."""
    probes = [
        ("GET", "/api/patients/does-not-exist", None),
        ("POST", "/api/emergencies/nope/validate", None),
        ("GET", "/api/language/phrases?language=klingon", None),
        ("POST", "/api/language/translate?language=klingon", None),
    ]
    for method, url, body in probes:
        r = client.request(method, url, headers=auth, json=body)
        assert r.status_code < 500, "{} {} returned {}".format(method, url, r.status_code)


# ------------------------------------------------------------- nutrition depth


def test_advice_explains_why_the_gap_matters_without_diagnosing(db):
    """Plain language, and modest: a screening measure is not a diagnosis."""
    from app.engines.nutrition import MDD_W, Recall, recommend
    gap = Recall(MDD_W, ["grains", "other_veg"])
    rec = recommend(gap, region="Northern", month=7, affordability="low")
    body = rec.to_dict()
    assert body["why"], "no explanation of why the gap matters"
    assert body["hydration"], "hydration advice missing"
    # No unsupported clinical claims.
    for banned in ("will die", "diagnos", "cure", "guarantee"):
        assert banned not in body["why"].lower()
        assert banned not in body["message"].lower()


def test_the_caseload_reports_direction_of_travel(db, client, auth):
    """One arm measurement cannot say whether a child is recovering."""
    patient = db.query(Patient).filter(Patient.name == "Hawa Sulemana").first()
    for offset, value in ((20, 12.8), (10, 12.1), (2, 11.4)):
        ev.append(db, patient_id=patient.id, event_type=ev.MUAC,
                  occurred_at=dt.datetime.utcnow() - dt.timedelta(days=offset),
                  payload={"subject": "child", "value_cm": value})
    ev.refresh_state(db, patient.id)
    db.commit()

    rows = client.get("/api/worklist/nutrition", headers=auth).json()["patients"]
    hers = [r for r in rows if r["id"] == patient.id][0]
    assert hers["child_series"] == [12.8, 12.1, 11.4]
    assert hers["child_trend"] == -1.4, "a falling child was not reported as falling"

    # And a falling child must sort above every child who is not falling.
    # Asserted relatively, not as index 0: other tests in this file add their
    # own measurements, and a test that depends on the order the suite happens
    # to run in is a test that will fail for the wrong reason one morning.
    stable = [r for r in rows
              if r["child_trend"] is None or r["child_trend"] >= 0]
    for other in stable:
        assert rows.index(hers) < rows.index(other), \
            "a falling child sorted below a stable one"


def test_a_generated_clip_is_played_instead_of_english(db):
    """The whole claim: she hears her own language, not a machine reading English."""
    from pathlib import Path
    from app.telephony import ivr
    from app.models import Phrase

    clip = (Path(__file__).resolve().parents[1] / "audio" / "dagbani"
            / "danger_bleeding.mp3")
    if not clip.exists():
        pytest.skip("no Dagbani clip present in this checkout")

    xml = ivr.speak(db, "http://x", "dagbani", "danger_bleeding",
                    "Are you bleeding?")
    assert "<Play" in xml and "danger_bleeding.mp3" in xml
    assert "<Say>" not in xml, "fell back to English despite having a clip"


def test_lines_too_long_to_synthesise_are_reported_not_hidden(db):
    """Khaya refuses past ~100 characters. Silently failing would look like a bug."""
    from app.language import pipeline
    status = pipeline.status(db, "dagbani")
    assert "too_long" in status
    for row in status["too_long"]:
        assert row["chars"] > pipeline.MAX_SPOKEN_CHARS


# ---------------------------------------------------------- care circle


def test_an_emergency_also_reaches_the_decision_maker(db, client, auth):
    """Alerting only the health worker assumes she decides alone. Often she does not."""
    from app.models import CareCircleMember, Message

    # A patient with no emergency already open: an escalation on an existing
    # one deliberately does NOT re-alert the family. A husband receiving a
    # fresh alarming message every time a symptom is updated stops reading them.
    patient = Patient(name="Circle Test", phone="+233240000802",
                      community="Kpale", region="Northern", consent=True)
    db.add(patient)
    db.flush()
    db.add(CareCircleMember(patient_id=patient.id, role="decision_maker",
                            name="Her husband", phone="+233240000801"))
    db.flush()

    before = db.query(Message).filter(Message.kind == "circle_alert").count()
    emergency = services.raise_emergency(db, patient, ["sign.bleeding"], "ivr")
    db.commit()

    # Not yet. The family is the one part of this that cannot be retracted, so
    # it waits for a human -- a mis-pressed 1 must not put "she needs to go to
    # the health centre now" on her husband's handset unreviewed.
    assert db.query(Message).filter(
        Message.kind == "circle_alert").count() == before, \
        "the family was alarmed before any clinician looked at it"

    worker = db.query(User).filter(User.role == "cho").first()
    services.validate_emergency(db, emergency, worker)
    db.commit()
    after = db.query(Message).filter(Message.kind == "circle_alert").count()
    assert after > before, "the person who decides was never told"

    note = (db.query(Message)
              .filter(Message.kind == "circle_alert")
              .order_by(Message.created_at.desc()).first())
    # Say what to do, not what is wrong: a third party gets no diagnosis.
    assert "health centre" in note.body
    for clinical in ("bleeding", "convulsions", "haemorrhage"):
        assert clinical not in note.body.lower()


def test_a_driver_she_already_agreed_with_is_called_first(db):
    from app.models import CareCircleMember, Driver

    patient = db.query(Patient).filter(Patient.name == "Rahma Osman").first()
    others = db.query(Driver).filter(Driver.community == patient.community).all()
    assert len(others) >= 2
    preferred = others[-1]        # deliberately not the top-ranked one
    db.add(CareCircleMember(patient_id=patient.id, role="driver",
                            name=preferred.name, phone=preferred.phone))
    db.flush()
    ranked = services.rank_drivers(db, patient)
    assert ranked[0].phone == preferred.phone, \
        "the driver she had already arranged was not called first"


def test_the_circle_reports_what_is_still_missing(db, client, auth):
    patient = db.query(Patient).filter(Patient.name == "Hawa Sulemana").first()
    body = client.get("/api/circle/{}".format(patient.id), headers=auth).json()
    assert len(body["members"]) == 4
    assert body["missing"], "a partly-filled circle claimed to be complete"
    # Each role explains which delay it addresses, so the form teaches.
    assert all(m["delay"] for m in body["members"])


# ------------------------------------------------- local speech (MMS)


def test_the_pipeline_is_not_tied_to_one_paid_provider(db):
    """Khaya is better where it has a model; it must not be the only route."""
    from app.language import mms, pipeline

    assert "khaya" in pipeline.providers_for("dagbani")
    # Kusaal has both, so an exhausted quota at one does not end the job.
    assert pipeline.providers_for("kusaal") == ["khaya", "mms"]
    # Gonja has neither. That is stated, not silently empty.
    assert pipeline.providers_for("gonja") == []
    assert mms.available_for("gonja") is None


def test_a_language_with_no_model_anywhere_says_so(db):
    from app.language import pipeline
    out = pipeline.speak_translated(db, "gonja", limit=5)
    assert out["generated"] == 0
    assert "recorded human voice" in out["note"]


def test_kusaal_audio_is_machine_generated_not_a_human_take(db):
    """Generated with no credits and no network at call time.

    Either label is correct: "mms_tts" when this database saw it generated, and
    "shipped" when a fresh database adopted it from the repository. What must
    never appear here is "recorded" -- that would mean a human voice had been
    silently overwritten.
    """
    from app.models import Phrase

    rows = (db.query(Phrase)
              .filter(Phrase.language == "kusaal",
                      Phrase.audio_path.isnot(None)).all())
    if not rows:
        pytest.skip("no Kusaal clips in this checkout")
    assert all(r.audio_source in ("mms_tts", "shipped") for r in rows)
    assert all(r.audio_bytes > 5000 for r in rows), "a clip is suspiciously small"


def test_mms_refuses_rather_than_returning_silence():
    """A clip of nothing played down a phone line is worse than English."""
    from app.language import mms
    ok, audio, error = mms.synthesise("Hello", "dagbani")
    assert ok is False
    assert "No MMS model exists" in error


def test_shipped_audio_is_found_when_the_database_is_new(db):
    """The clips ship in the repository; the database does not.

    On a host with an ephemeral disk the database is rebuilt on every deploy.
    Without reconciliation the platform would sit on a folder of real recordings
    and tell every caller its English fallback -- silently, because nothing was
    actually broken.
    """
    from pathlib import Path
    from app.language import pipeline
    from app.models import Phrase

    folder = Path(__file__).resolve().parents[1] / "audio" / "kusaal"
    known = {p.key for p in db.query(Phrase).filter(
        Phrase.language == "kusaal").all()}
    # Only clips whose name matches a phrase can be adopted. A stray file is
    # deliberately left alone rather than guessed at.
    clips = [f for f in folder.glob("*.wav") if f.stem in known] \
        if folder.is_dir() else []
    if not clips:
        pytest.skip("no Kusaal clips in this checkout")

    # Wipe every audio pointer, as a fresh deploy would.
    for phrase in db.query(Phrase).filter(Phrase.language == "kusaal").all():
        phrase.audio_path = None
        phrase.audio_source = None
    db.flush()
    assert pipeline.status(db, "kusaal")["with_audio"] == 0

    adopted = pipeline.adopt_audio_on_disk(db, "kusaal")
    db.flush()
    assert adopted == len(clips)
    assert pipeline.status(db, "kusaal")["with_audio"] == len(clips)


def test_adoption_never_overwrites_a_human_recording(db):
    from app.language import pipeline
    from app.models import Phrase

    pipeline.sync_catalogue(db, "kusaal")
    phrase = (db.query(Phrase)
                .filter(Phrase.language == "kusaal",
                        Phrase.key == "danger_bleeding").first())
    if phrase is None:
        pytest.skip("catalogue not present")
    phrase.audio_source = "recorded"
    phrase.audio_path = "kusaal/danger_bleeding.wav"
    db.flush()

    pipeline.adopt_audio_on_disk(db, "kusaal")
    db.expire_all()
    again = db.get(Phrase, phrase.id)
    assert again.audio_source == "recorded"


def test_the_greeting_now_fits_the_synthesis_ceiling(db):
    """It was 148 characters and could not be spoken in any language."""
    from app.language import pipeline
    from app.language.catalogue import by_key

    catalogue = by_key()
    assert len(catalogue["greet_consent"]["text"]) <= 110
    assert "press 9" not in catalogue["greet_consent"]["text"].lower(), \
        "the escape hint belongs after she agrees to talk, not in the greeting"
    assert "9" in catalogue["escape_hint"]["text"]

    pipeline.sync_catalogue(db, "dagbani")
    db.flush()
    over = {row["key"] for row in pipeline.too_long_to_speak(db, "dagbani")}
    assert "greet_consent" not in over, "the greeting is still unsynthesisable"


def test_the_escape_hint_is_spoken_once_she_has_agreed(db):
    """Told at a point she can use it, rather than tacked onto a greeting."""
    from app.telephony import ivr
    from app.models import Patient

    patient = db.query(Patient).first()
    session = CallSession(id="hint-order", patient_id=patient.id,
                          phone=patient.phone, purpose="outreach",
                          language="english", state="greet", answers={},
                          transcript=[])
    db.add(session)
    db.flush()

    greeting = ivr.advance(db, session, None, "", "http://x/cb").xml
    assert "press 9" not in greeting.lower()

    after_consent = ivr.advance(db, session, "1", "", "http://x/cb").xml
    assert "press 9" in after_consent.lower(), \
        "she was never told how to reach a person"


# ------------------------------------------------- stale translations


def test_rewritten_english_marks_its_translation_stale_not_current(db):
    """A translation of wording nobody says any more is not a translation.

    On a fresh database the cache is loaded with no memory of what it was
    translated from, so without recording the source English the platform would
    confidently speak a sentence rendering a prompt that had since been
    rewritten -- and nothing would look wrong.
    """
    from app.language import pipeline
    from app.models import Phrase

    pipeline.sync_catalogue(db, "dagbani")
    db.flush()
    stale = (db.query(Phrase)
               .filter(Phrase.language == "dagbani",
                       Phrase.status == "stale").all())
    assert stale, "no line reported stale despite the English being rewritten"
    for phrase in stale:
        assert phrase.previous_text, "the old wording was discarded"
        assert phrase.translated_text, "the line was blanked instead of flagged"


def test_a_stale_translation_is_never_silently_deleted(db):
    """It cannot be regenerated while the provider quota is gone."""
    from app.language import pipeline
    from app.models import Phrase

    pipeline.sync_catalogue(db, "dagbani")
    phrase = (db.query(Phrase)
                .filter(Phrase.language == "dagbani",
                        Phrase.key == "closing").first())
    original = phrase.translated_text
    assert original

    phrase.source_text = "Something completely different."
    db.flush()
    pipeline.sync_catalogue(db, "dagbani")
    db.expire_all()

    again = db.get(Phrase, phrase.id)
    assert again.status == "stale"
    assert again.previous_text == original, "the old translation was lost"


def test_stale_lines_are_re_translated_when_credits_return(db):
    """They must be queued for another attempt, not left as permanent debris."""
    from app.language import pipeline
    from app.models import Phrase

    pipeline.sync_catalogue(db, "dagbani")
    db.flush()
    pending = (db.query(Phrase)
                 .filter(Phrase.language == "dagbani",
                         Phrase.status.in_(["pending", "failed", "stale"]))
                 .count())
    out = pipeline.translate_pending(db, "dagbani", limit=0)
    assert out["remaining"] == pending


# ------------------------------------------- the call speaks her language


def test_her_language_is_played_and_never_read_by_an_english_voice(db):
    """Two failures, one either side of the same line.

    First the call ignored the phrase table entirely and every Dagbani prompt
    went out in English. Then, fixing that, the translation was handed to
    <Say> -- which is the provider's ENGLISH text-to-speech voice. There is no
    Dagbani voice behind it, so that produced an English speaker failing at
    Dagbani orthography: worse for the woman on the line than plain English.

    The rule is: a clip in her language is played; anything with no clip is
    said in English until one is recorded. Nothing ever hands her language to
    an English voice.
    """
    import re
    from app.telephony import ivr, service as tel

    patient = db.query(Patient).filter(Patient.name == "Amina Fuseini").first()
    patient.language = "dagbani"
    db.flush()
    session, _ = tel.start_call(db, phone=patient.phone, patient_id=patient.id,
                                purpose="outreach", language="dagbani")
    db.flush()

    said, played = [], []
    for digit in (None, "1", "1", "2", "2", "2", "1", "1"):
        turn = ivr.advance(db, session, digit, "http://x", "http://x/cb")
        said += re.findall(r"<Say>(.*?)</Say>", turn.xml, re.S)
        played += re.findall(r'<Play url="(.*?)"', turn.xml)
        if turn.finished:
            break

    assert played, "no recorded Dagbani was used at all"
    for line in said:
        assert all(ch not in line for ch in "ɛɣŋʒɔɨɩʋ"), \
            "Dagbani handed to the English voice: {}".format(line[:70])


def test_a_woman_who_reported_bleeding_is_not_told_to_expect_a_text(db):
    """red_closing was written, translated, shipped -- and never emitted."""
    import re
    from app.telephony import ivr, service as tel

    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    session, _ = tel.start_call(db, phone=patient.phone, patient_id=patient.id,
                                purpose="outreach", language="english")
    db.flush()

    ivr.advance(db, session, None, "", "http://x/cb")
    ivr.advance(db, session, "1", "", "http://x/cb")      # good time
    ivr.advance(db, session, "1", "", "http://x/cb")      # yes, bleeding
    last = None
    for _ in range(6):
        turn = ivr.advance(db, session, "2", "", "http://x/cb")
        last = turn
        if turn.finished:
            break

    said = " ".join(re.findall(r"<Say>(.*?)</Say>", last.xml, re.S)).lower()
    assert "health worker" in said, "she was not told anyone had been alerted"
    assert "do not travel alone" in said
    assert "send the date by message" not in said


def test_fetal_movement_is_not_asked_before_quickening(db):
    """Asking a woman at 12 weeks if her baby stopped moving, then dispatching."""
    import datetime as dt2
    from app.telephony import ivr, service as tel

    early = Patient(name="Twelve Weeks", phone="+233240000931",
                    community="Kpale", region="Northern", consent=True,
                    edd=dt2.date.today() + dt2.timedelta(weeks=28))
    late = Patient(name="Thirty Weeks", phone="+233240000932",
                   community="Kpale", region="Northern", consent=True,
                   edd=dt2.date.today() + dt2.timedelta(weeks=10))
    db.add_all([early, late])
    db.flush()

    for patient, expected in ((early, False), (late, True)):
        session, _ = tel.start_call(db, phone=patient.phone,
                                    patient_id=patient.id, purpose="outreach",
                                    language="english")
        db.flush()
        keys = [k for k, _ in ivr.danger_questions_for(db, session)]
        assert ("reduced_fetal_movement" in keys) is expected, \
            "{} asked the wrong question set".format(patient.name)
        # Everything else is still asked either way.
        assert "bleeding" in keys and "convulsions" in keys


def test_a_file_that_is_not_audio_can_never_count_as_a_voice(db):
    """A 2 kB run of the letter "x" reached production and ended every call."""
    from app.language import pipeline
    from app.models import Phrase

    pipeline.sync_catalogue(db, "dagbani")
    phrase = (db.query(Phrase)
                .filter(Phrase.language == "dagbani",
                        Phrase.key == "closing").first())
    with pytest.raises(ValueError):
        pipeline.write_audio(db, phrase, b"x" * 2000, source="recorded")

    ok, reason = pipeline.looks_like_audio(b"\x1a\x45\xdf\xa3" + b"\x00" * 1000)
    assert ok is False and "phone line" in reason, \
        "a browser recording was accepted for a GSM call"


def test_a_composed_turn_resolves_each_part_on_its_own(db):
    """Joining parts under one key silently threw all but the first away.

    ask(key, hint + " " + question) played the clip for `key` and discarded the
    string entirely -- which is how "press 9 to speak to a nurse" came to be
    dropped from every call in every language that had audio, including the one
    we had just finished recording.
    """
    from app.telephony import ivr

    xml = ivr.utterance(db, "http://x", "dagbani", [
        ("danger_bleeding", "Are you bleeding?"),
        (None, "Some runtime message."),
    ])
    assert "<Play" in xml, "the recorded part was not played"
    assert "Some runtime message." in xml, "the runtime part was thrown away"


def test_the_escape_hint_survives_a_question_that_has_a_recording(db):
    """It has its own catalogue entry and its own clip. Nothing played it."""
    from app.telephony import ivr, service as tel

    patient = db.query(Patient).filter(Patient.name == "Amina Fuseini").first()
    patient.language = "dagbani"
    db.flush()
    session, _ = tel.start_call(db, phone=patient.phone, patient_id=patient.id,
                                purpose="outreach", language="dagbani")
    db.flush()

    ivr.advance(db, session, None, "http://x", "http://x/cb")
    turn = ivr.advance(db, session, "1", "http://x", "http://x/cb")
    assert "press 9" in turn.xml.lower(), \
        "the only way to reach a human was dropped from the call"


# --------------------------------------------- nutrition truth and affordability


def test_the_local_word_for_groundnut_is_not_the_word_for_rice(db):
    """sinkaafa is rice. The engine's most-recommended food was mislabelled."""
    from app.data.foods import FOODS_BY_KEY

    assert FOODS_BY_KEY["groundnut"]["local_names"]["dagbani"] == "sinkpam"
    for food in FOODS_BY_KEY.values():
        assert food["local_names"].get("dagbani") != "sinkaafa", \
            "{} is labelled with the Dagbani word for rice".format(food["key"])


def test_fat_is_not_counted_as_a_vegetable(db):
    """Shea butter carried other_veg, crediting a group she had not eaten.

    Fats and oils are deliberately excluded from both MDD-W and the child
    indicator. Counting one inflated the score the whole product reports.
    """
    from app.data.foods import FOODS_BY_KEY

    shea = FOODS_BY_KEY["shea_butter"]
    assert shea["w_groups"] == [] and shea["c_groups"] == []


def test_the_lean_season_example_the_readme_leads_with_actually_works(db):
    """Groundnut priced to medium in the lean season -- unaffordable in July."""
    from app.data.foods import FOODS_BY_KEY, tier_for

    assert tier_for(FOODS_BY_KEY["groundnut"], "lean") == "low"


def test_an_unknown_budget_is_treated_as_the_tightest_one(db):
    """The affordability filter failed open, defeating its only purpose."""
    from app.data.foods import AFFORDABILITY_CEILING, FOODS_BY_KEY
    from app.engines.nutrition import _affordable

    goat = FOODS_BY_KEY["goat"]
    # "high" must be a real key, not something that used to work by falling
    # through to "allow everything".
    assert "high" in AFFORDABILITY_CEILING
    assert _affordable(goat, "high", "dry") is True
    for bad in (None, "", "unknown", "LOW", "medium-ish"):
        assert _affordable(goat, bad, "dry") is False, \
            "affordability={!r} let an expensive food through".format(bad)


def test_a_child_who_stopped_breastfeeding_is_not_congratulated(db):
    """No food carries the breastmilk group, so the gap was skipped entirely."""
    from app.engines.nutrition import MDD_CHILD, Recall, recommend

    # Five of eight groups, but breast milk is not one of them.
    recall = Recall(MDD_CHILD, ["grains", "pulses_nuts_seeds", "dairy",
                                "flesh", "eggs"])
    assert recall.meets_minimum is True
    rec = recommend(recall, month=7)
    assert rec.group == "breastmilk"
    assert "breast milk" in rec.message.lower()
    assert "varied enough" not in rec.message


# --------------------------------------------------------- the two instruments


def test_the_two_diversity_scores_are_never_pooled(client, db, auth):
    """The screen said they are never combined, twelve lines under the pooling.

    Both minimums are five, which is what made this look harmless -- but the
    denominators are ten and eight and the populations are women and infants.
    """
    body = client.get("/api/metrics", headers=auth).json()
    assert "minimum_dietary_diversity" not in body
    assert "mdd_women" in body and "mdd_children" in body
    assert body["mdd_women_n"] + body["mdd_children_n"] == db.query(
        PatientState).filter(PatientState.mdd_score.isnot(None)).count()


# ------------------------------------------------------------- the care circle


def test_the_driver_she_named_is_rung_first(db):
    """A pre-sort then a second sorted() on other keys discarded the preference."""
    from app.models import CareCircleMember
    from app.services import rank_drivers

    patient = db.query(Patient).filter(Patient.name == "Amina Fuseini").first()
    # A stranger with a perfect record, in her community, in a car.
    star = Driver(name="Star Stranger", phone="+233240000941",
                  community=patient.community, vehicle_type="car",
                  available=True, accepted_count=20, offered_count=20)
    hers = Driver(name="Her Man", phone="+233240000942",
                  community=patient.community, vehicle_type="motorbike",
                  available=True, accepted_count=0, offered_count=4)
    db.add_all([star, hers])
    # Amina's circle is seeded complete, so name over the existing entry.
    row = (db.query(CareCircleMember)
             .filter(CareCircleMember.patient_id == patient.id,
                     CareCircleMember.role == "driver").first())
    if row is None:
        row = CareCircleMember(patient_id=patient.id, role="driver")
        db.add(row)
    row.name, row.phone = "Her Man", "+233240000942"
    db.flush()

    order = rank_drivers(db, patient)
    assert order[0].phone == "+233240000942", \
        "ranked her named driver below a stranger: {}".format(
            [d.name for d in order[:3]])


def test_naming_a_driver_puts_him_in_the_roster_that_gets_dialled(client, db, auth):
    """rank_drivers reads the Driver table; the circle wrote somewhere else."""
    from app.services import rank_drivers

    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    before = db.query(Driver).filter(Driver.phone == "+233240000955").count()
    assert before == 0

    r = client.put("/api/circle/{}".format(patient.id), headers=auth, json={
        "role": "driver", "name": "Yakubu", "phone": "+233240000955",
        "detail": "motorking"})
    assert r.status_code == 200

    db.expire_all()
    created = db.query(Driver).filter(Driver.phone == "+233240000955").first()
    assert created is not None, "named driver never entered the roster"
    assert created.community == patient.community
    assert rank_drivers(db, patient)[0].phone == "+233240000955"


def test_a_care_circle_of_names_with_no_numbers_is_not_complete(client, db, auth):
    """complete went true with four names and no way to ring any of them."""
    patient = db.query(Patient).filter(Patient.name == "Rahma Osman").first()
    roles = ["decision_maker", "driver", "payer", "emergency"]
    for role in roles:
        body = client.put("/api/circle/{}".format(patient.id), headers=auth,
                          json={"role": role, "name": "Someone"}).json()
    assert body["missing"] == []
    assert body["complete"] is False, "complete with no phone numbers at all"
    assert body["unreachable"]

    for role in ("decision_maker", "emergency"):
        body = client.put("/api/circle/{}".format(patient.id), headers=auth,
                          json={"role": role, "name": "Someone",
                                "phone": "+23324000096" + str(roles.index(role))}
                          ).json()
    assert body["complete"] is True


def test_saving_a_name_does_not_claim_the_person_agreed(client, db, auth):
    """The form hardcoded confirmed: true, so 'agreed' meant 'typed'."""
    patient = db.query(Patient).filter(Patient.name == "Rahma Osman").first()
    body = client.put("/api/circle/{}".format(patient.id), headers=auth,
                      json={"role": "payer", "name": "Uncle"}).json()
    payer = [m for m in body["members"] if m["role"] == "payer"][0]
    assert payer["confirmed"] is False


def test_the_simulator_shows_what_she_actually_hears(client, db, auth):
    """The panel ran backwards, then showed text no handset would produce.

    A <Play> is a recording in her language, so she hears the translated
    wording; a <Say> is the English voice, so she hears English. Printing them
    identically is what made the coverage number abstract.
    """
    from app.telephony import ivr, service as tel

    patient = db.query(Patient).filter(Patient.name == "Amina Fuseini").first()
    patient.language = "dagbani"
    db.flush()
    session, _ = tel.start_call(db, phone=patient.phone, patient_id=patient.id,
                               purpose="outreach", language="dagbani")
    db.commit()

    client.post("/api/simulator/press", headers=auth,
                json={"session_id": session.id, "digit": None})
    body = client.post("/api/simulator/press", headers=auth,
                       json={"session_id": session.id, "digit": "1"}).json()

    assert "in_language" not in body
    # The bleeding question has a Dagbani recording, so it is heard in Dagbani
    # and glossed in English.
    assert any(ch in body["spoken"] for ch in "ɛɣŋʒɔ"), \
        "the recorded Dagbani line is not on screen"
    assert body["english"], "no English gloss for whoever is watching"
    assert "bleeding" in body["english"].lower()


# ----------------------------------------------------------------- boundaries


def test_the_language_parameter_cannot_write_outside_the_audio_folder(client, db, auth):
    """An authenticated worker could create directories anywhere on the box.

    `language` arrived as a free query string and became a path segment under
    audio/, so "../../../../tmp/x" was an arbitrary directory create and file
    write. It also minted eighty catalogue rows per distinct string, making the
    same parameter an unbounded write into the database.
    """
    from app.models import Phrase

    before = db.query(Phrase).count()
    for hostile in ("../../../../tmp/pwned", "..%2f..%2fetc", "english/../..",
                    "dagbani/../../tmp"):
        r = client.get("/api/language/phrases", headers=auth,
                       params={"language": hostile})
        assert r.status_code == 422, \
            "{!r} was accepted as a language".format(hostile)
    db.expire_all()
    assert db.query(Phrase).count() == before, "junk phrase rows were created"


def test_write_audio_refuses_to_escape_its_root_even_if_called_directly(db):
    """The API whitelists, but the function that touches disk must not rely on it."""
    from app.language import pipeline
    from app.models import Phrase
    from tests.conftest import wav

    rogue = Phrase(language="../../../../tmp", key="pwned", category="danger",
                   source_text="x")
    db.add(rogue)
    db.flush()

    # The audio must be valid in every other respect, or the size check
    # satisfies pytest.raises and the path check is never reached -- which is
    # exactly what this test used to do.
    payload = wav()
    assert pipeline.looks_like_audio(payload)[0], "fixture is not valid audio"

    with pytest.raises(ValueError) as caught:
        pipeline.write_audio(db, rogue, payload)
    assert "outside the audio folder" in str(caught.value), \
        "raised for the wrong reason: {}".format(caught.value)


def test_a_file_is_named_after_what_it_actually_is(db):
    """Everything was saved as .wav, so an mp3 was served under a lying name."""
    from app.language import pipeline
    from app.models import Phrase

    pipeline.sync_catalogue(db, "kusaal")
    phrase = (db.query(Phrase)
                .filter(Phrase.language == "kusaal",
                        Phrase.key == "escape_hint").first())
    pipeline.write_audio(db, phrase, b"ID3\x04\x00" + b"\x00" * 3000)
    assert phrase.audio_path.endswith(".mp3")

    from pathlib import Path
    written = pipeline.AUDIO_ROOT / phrase.audio_path
    assert written.exists()
    written.unlink()


def test_one_facility_cannot_read_or_rewrite_another_ones_care_circle(client, db, auth):
    """Authentication proves who; it never proved whether.

    The emergency SMS is sent to the number in this table, so an overwrite
    silently redirects "she needs to go to the health centre now" to a
    stranger's handset.
    """
    from app.models import Facility, User
    from app.security import hash_pin

    other_facility = Facility(name="Far Away CHPS", community="Elsewhere",
                              region="Upper West")
    db.add(other_facility)
    db.flush()
    outsider = User(name="Outside Worker", phone="+233209999999", role="cho",
                    pin_hash=hash_pin("1234"), facility_id=other_facility.id)
    db.add(outsider)
    db.commit()

    token = client.post("/api/auth/login",
                        json={"phone": "+233209999999", "pin": "1234"}
                        ).json()["token"]
    theirs = {"Authorization": "Bearer {}".format(token)}

    patient = db.query(Patient).filter(Patient.name == "Amina Fuseini").first()
    assert client.get("/api/circle/{}".format(patient.id),
                      headers=theirs).status_code == 404
    r = client.put("/api/circle/{}".format(patient.id), headers=theirs,
                   json={"role": "decision_maker", "name": "Attacker",
                         "phone": "+233000000000"})
    assert r.status_code == 404

    # And her own worker is unaffected.
    mine = client.get("/api/circle/{}".format(patient.id), headers=auth).json()
    decision = [m for m in mine["members"] if m["role"] == "decision_maker"][0]
    assert decision["phone"] != "+233000000000"


def test_changing_a_care_circle_number_leaves_a_trace(client, db, auth):
    """The only clinical table that never touched the append-only log."""
    from app.models import Event

    patient = db.query(Patient).filter(Patient.name == "Amina Fuseini").first()
    before = db.query(Event).filter(
        Event.event_type == "care_circle_set").count()
    client.put("/api/circle/{}".format(patient.id), headers=auth,
               json={"role": "decision_maker", "name": "Mahamadu Fuseini",
                     "phone": "+233240000199"})
    db.expire_all()
    rows = (db.query(Event).filter(Event.event_type == "care_circle_set")
              .order_by(Event.recorded_at.desc()).all())
    assert len(rows) == before + 1
    assert rows[0].payload["now"]["phone"] == "+233240000199"
    assert rows[0].payload["was"]["phone"] != "+233240000199", \
        "the number it replaced was not recorded"


def test_a_column_added_after_the_database_existed_is_added_to_it(tmp_path):
    """create_all never alters an existing table, so new columns were missing.

    The first query naming one failed with "no such column" on any deployment
    with a persistent disk -- which is exactly what render.yaml invites you to
    turn on.
    """
    from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect, text
    from app.migrate import add_missing_columns
    from app.db import Base

    url = "sqlite:///{}".format(tmp_path / "old.db")
    engine = create_engine(url)

    # A database created before `previous_text` existed.
    old = MetaData()
    Table("phrases", old,
          Column("id", String, primary_key=True),
          Column("language", String),
          Column("key", String))
    old.create_all(engine)
    with engine.begin() as c:
        c.execute(text("INSERT INTO phrases (id, language, key) "
                       "VALUES ('1', 'dagbani', 'closing')"))

    Base.metadata.create_all(bind=engine)
    added = add_missing_columns(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("phrases")}
    assert "previous_text" in columns, "the missing column was not added"
    assert any("previous_text" in a for a in added)
    with engine.begin() as c:
        assert c.execute(text("SELECT COUNT(*) FROM phrases")).scalar() == 1, \
            "existing rows were lost"


def _pending_kusaal(db, n):
    """n Kusaal lines that are translated and waiting for a voice."""
    from app.language import pipeline
    from app.models import Phrase

    pipeline.sync_catalogue(db, "kusaal")
    rows = db.query(Phrase).filter(Phrase.language == "kusaal").limit(n).all()
    for index, row in enumerate(rows):
        row.translated_text = "ka{} ba".format(index)
        row.status = "translated"
        row.audio_path = None
        row.audio_source = None
        row.error = None
    db.flush()
    return rows


# ------------------------------------------ what a recording can actually reach


def test_the_food_advice_can_be_played_as_a_recording(db):
    """34 food clips existed in the catalogue and no call could request one.

    The nutrition message was passed into the turn as a bare string with no
    key, so the utterance layer had nothing to look up -- the entire output of
    the nutrition engine was structurally unable to use its own recordings.
    """
    from app.telephony import ivr, service as tel

    patient = db.query(Patient).filter(Patient.name == "Amina Fuseini").first()
    session, _ = tel.start_call(db, phone=patient.phone, patient_id=patient.id,
                                purpose="outreach", language="dagbani")
    db.flush()

    advice, food_key = ivr._nutrition_message(db, session)
    assert advice, "no advice produced at all"
    assert food_key, "the chosen food was not reported back to the caller"
    key = advice[0][0]
    assert key and key.startswith("food_"), \
        "the advice carries no catalogue key: {!r}".format(advice[0])

    from app.language import catalogue
    assert key in catalogue.by_key(), \
        "{} is not a line anyone can record".format(key)


def test_the_anaemia_tips_are_lines_someone_can_record(db):
    """The only spoken text in the system with no catalogue entry at all."""
    from app import prompts
    from app.engines.nutrition import ANAEMIA_TIPS
    from app.language import catalogue

    known = catalogue.by_key()
    for tip in ANAEMIA_TIPS:
        key = prompts.anaemia_tip_key(tip)
        assert key, "no key for: {}".format(tip[:40])
        assert key in known


def test_coverage_separates_the_spine_from_the_long_tail(db):
    """One number mixed lines every call plays with lines almost none do."""
    from app.language import pipeline

    pipeline.sync_catalogue(db, "dagbani")
    db.flush()
    st = pipeline.status(db, "dagbani")

    assert st["core_total"] < st["total"], "everything counted as core"
    assert st["core_total"] > 10, "the spine is implausibly short"
    # The bleeding recording is on the spine, so core coverage must see it.
    assert st["core_with_audio"] >= 1
    assert st["core_coverage"] > st["spoken_coverage"], \
        "the long tail is still dragging the headline number down"


def test_a_provider_returning_html_does_not_lose_the_whole_batch(db, monkeypatch):
    """Khaya's documented failure is an Azure error page served with a 200.

    write_audio raises on that, and nothing caught it: the endpoint 500ed, the
    transaction rolled back, and every clip already written was left orphaned
    on disk with no row -- ready for the next sync to adopt as "shipped".
    """
    from app.language import khaya, mms, pipeline

    _pending_kusaal(db, 5)

    wav = (b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt "
           + (16).to_bytes(4, "little") + (1).to_bytes(2, "little")
           + (1).to_bytes(2, "little") + (8000).to_bytes(4, "little")
           + (16000).to_bytes(4, "little") + (2).to_bytes(2, "little")
           + (16).to_bytes(2, "little") + b"data" + (2000).to_bytes(4, "little")
           + b"\x00" * 2000)
    calls = {"n": 0}

    def flaky(text, language):
        calls["n"] += 1
        if calls["n"] == 3:
            return True, b"<html>Web App - Unavailable</html>" * 100, None
        return True, wav, None

    monkeypatch.setattr(mms, "synthesise", flaky)
    monkeypatch.setattr(pipeline, "providers_for", lambda language: ["mms"])

    out = pipeline.speak_translated(db, "kusaal", limit=5)
    assert out["generated"] >= 2, "the good clips were lost with the bad one"
    assert "mms" in out["blocked"]
    assert "not audio" in out["blocked_because"]["mms"]

    for path in (pipeline.AUDIO_ROOT / "kusaal").glob("*.wav"):
        if path.stat().st_size == len(wav):
            path.unlink()


def test_an_error_is_never_pinned_on_a_phrase_that_was_never_sent(db, monkeypatch):
    """`note` was module-flow state, carried across loop iterations."""
    from app.language import mms, pipeline

    _pending_kusaal(db, 6)
    monkeypatch.setattr(pipeline, "providers_for", lambda language: ["mms"])
    monkeypatch.setattr(mms, "synthesise",
                        lambda t, l: (False, b"", "quota exhausted until Tuesday"))

    rows = _pending_kusaal(db, 6)
    out = pipeline.speak_translated(db, "kusaal", limit=6)
    assert out["failed"] >= 2
    db.expire_all()

    # Exactly one phrase was actually sent -- the quota blocks the route after
    # it -- and only that one may carry the provider's own words. Every phrase
    # after it was never sent to anything, so it must be told the route was
    # blocked rather than handed someone else's error. Asserting `any` here let
    # the real misattribution through, because the one correctly-attributed
    # phrase satisfied it single-handedly.
    sent, unsent = rows[0], rows[1:]
    assert sent.error == "quota exhausted until Tuesday"
    for phrase in unsent:
        assert phrase.error and phrase.error.startswith("mms: "), \
            "pinned on a phrase from someone else's request: {!r}".format(
                phrase.error)


def test_the_khaya_length_ceiling_is_not_applied_to_the_local_model(db, monkeypatch):
    """A limit measured against one service was refusing work for another.

    MMS synthesises 400 characters happily. Applying Khaya's 100-character
    ceiling above the route loop is why eight long Kusaal lines were reported
    unspeakable while a working route sat right there.
    """
    from app.language import mms, pipeline
    from app.models import Phrase

    long_one = _pending_kusaal(db, 1)[0]
    long_one.translated_text = "ka " * 60          # 180 characters
    db.flush()

    seen = {}
    monkeypatch.setattr(pipeline, "providers_for", lambda language: ["mms"])
    monkeypatch.setattr(mms, "synthesise",
                        lambda t, l: (seen.setdefault("len", len(t)),
                                      (False, b"", "no model here"))[1])
    pipeline.speak_translated(db, "kusaal", limit=1)
    assert seen.get("len", 0) > pipeline.MAX_SPOKEN_CHARS, \
        "the local route never saw the long line"


def test_an_off_duty_driver_is_not_put_back_on_call_by_a_household_form(client, db, auth):
    """He would then be rung for an emergency he had said he could not take."""
    driver = db.query(Driver).filter(Driver.phone == "+233200000021").first()
    driver.available = False
    db.commit()

    patient = db.query(Patient).filter(Patient.name == "Zeinab Mahama").first()
    client.put("/api/circle/{}".format(patient.id), headers=auth,
               json={"role": "driver", "name": "Iddrisu Mohammed",
                     "phone": "+233200000021", "detail": "uncle"})
    db.expire_all()
    assert db.query(Driver).filter(
        Driver.phone == "+233200000021").first().available is False


def test_a_relationship_note_is_not_written_in_as_a_vehicle(client, db, auth):
    """detail is free text on every other role; it was taken raw as a type."""
    patient = db.query(Patient).filter(Patient.name == "Rahma Osman").first()
    client.put("/api/circle/{}".format(patient.id), headers=auth,
               json={"role": "driver", "name": "Yakubu B",
                     "phone": "+233240000977",
                     "detail": "his brother's motorbike"})
    db.expire_all()
    created = db.query(Driver).filter(Driver.phone == "+233240000977").first()
    assert created.vehicle_type == "motorbike"


def test_a_rejected_recording_stops_being_played(client, db, auth):
    """The IVR finds clips on disk, so clearing the row alone changed nothing."""
    from app.language import pipeline
    from app.models import Phrase
    from app.telephony import ivr

    pipeline.sync_catalogue(db, "dagbani")
    phrase = (db.query(Phrase)
                .filter(Phrase.language == "dagbani",
                        Phrase.key == "danger_bleeding").first())
    assert phrase.audio_path, "fixture expects a shipped clip here"
    assert ivr._audio_url("", "dagbani", "danger_bleeding")

    r = client.delete("/api/language/phrases/{}/audio".format(phrase.id),
                      headers=auth)
    assert r.status_code == 200
    assert ivr._audio_url("", "dagbani", "danger_bleeding") is None, \
        "the caller still hears the take that was just rejected"

    # Retired, not destroyed -- it is still a real voice saying real words.
    retired = list((pipeline.AUDIO_ROOT / "dagbani").glob("danger_bleeding.*.retired"))
    assert retired
    retired[0].rename(str(retired[0]).replace(".retired", ""))


def test_mms_refuses_an_input_it_cannot_finish_inside_a_request(db):
    """Measured: 11k characters ran 28 CPU-minutes at 29% of memory.

    This is called synchronously from an HTTP handler, so an unbounded input is
    a request that never returns rather than a slow one.
    """
    from app.language import mms

    ok, audio, error = mms.synthesise("ka " * 5000, "kusaal")
    assert ok is False and not audio
    assert str(mms.MAX_SYNTHESIS_CHARS) in error
    assert "Split it into two prompts" in error

    ok, _, error = mms.synthesise("   ", "kusaal")
    assert ok is False and "nothing to say" in error


def test_the_family_is_not_alarmed_before_a_clinician_has_looked(db):
    """The only irreversible step was the one with no human in front of it."""
    from app.models import CareCircleMember, Message

    patient = Patient(name="Gate Test", phone="+233240000811",
                      community="Kpale", region="Northern", consent=True)
    db.add(patient)
    db.flush()
    db.add(CareCircleMember(patient_id=patient.id, role="decision_maker",
                            name="Her husband", phone="+233240000812"))
    db.flush()

    sent = lambda: db.query(Message).filter(
        Message.kind == "circle_alert").count()
    before = sent()
    emergency = services.raise_emergency(db, patient, ["sign.bleeding"], "ivr")
    db.flush()
    assert sent() == before

    # The health worker, though, is told at once -- judging this is her job.
    assert db.query(Message).filter(Message.kind == "red_alert").count() > 0

    worker = db.query(User).filter(User.role == "cho").first()
    services.validate_emergency(db, emergency, worker)
    db.flush()
    assert sent() == before + 1


# ------------------------------------------------- one number, four spellings


def test_the_same_handset_written_four_ways_is_one_number(db):
    """Every lookup here is an exact string match and nothing normalised them.

    A CHO writes 0240000001, Africa's Talking reports +233240000001, and a
    pasted contact says 233 24 000 0001. Same handset, three strings, no match
    between any of them.
    """
    from app import phones

    for spelling in ("0240000001", "+233240000001", "233240000001",
                     "024 000 0001", "00233240000001", "240000001",
                     "+233 24-000-0001"):
        assert phones.normalise(spelling) == "+233240000001", \
            "{!r} did not normalise".format(spelling)

    # A number we cannot parse is kept, not discarded -- someone meant to type it.
    assert phones.normalise("+14155550100") == "+14155550100"
    assert phones.normalise("") is None and phones.normalise(None) is None

    # And shown back the way it is written locally.
    assert phones.display("+233240000001") == "024 000 0001"


def test_no_write_path_can_store_an_unnormalised_number(db):
    """Fixing the API handlers was not enough: seed, sync and the telephony
    callback all write directly, and each is a different spelling entering."""
    patient = Patient(name="Typed Locally", phone="024 111 2233",
                      secondary_phone="0201112233", community="Kpale",
                      region="Northern", consent=True)
    driver = Driver(name="Roster Man", phone="0201112299", community="Kpale")
    db.add_all([patient, driver])
    db.flush()

    assert patient.phone == "+233241112233"
    assert patient.secondary_phone == "+233201112233"
    assert driver.phone == "+233201112299"

    patient.phone = "0555000111"
    db.flush()
    assert patient.phone == "+233555000111", "an update slipped past"


def test_she_is_recognised_when_she_flashes_from_her_own_handset(client, db, auth):
    """The hotline looks her up by caller ID. A miss means a stranger.

    She is then rung back with no record, no pregnancy, no danger-sign history
    and no language preference -- the platform speaks English at a woman it has
    called eight times.
    """
    from app.models import CallbackRequest

    patient = db.query(Patient).filter(Patient.name == "Amina Fuseini").first()
    patient.language = "dagbani"
    db.commit()

    # The trunk-zero spelling, which is how the number is written in Ghana.
    local = "0" + patient.phone[len("+233"):]
    r = client.post("/api/telephony/voice", data={
        "sessionId": "flash-probe", "isActive": "1",
        "callerNumber": local, "destinationNumber": "+233200000099",
        "direction": "inbound", "dtmfDigits": ""})
    assert r.status_code == 200
    assert "Reject" in r.text, "she was answered, so she was charged airtime"

    db.expire_all()
    queued = (db.query(CallbackRequest)
                .filter(CallbackRequest.status == "pending",
                        CallbackRequest.phone == patient.phone).first())
    assert queued is not None
    assert queued.phone == patient.phone, "stored under a spelling that matches nothing"
    assert queued.patient_id == patient.id, \
        "she was queued as an anonymous caller from her own handset"


def test_a_worker_can_sign_in_with_the_number_as_she_writes_it(client, db):
    """At two in the morning she should not have to guess which of four
    spellings she was enrolled under."""
    r = client.post("/api/auth/login",
                    json={"phone": "0200000001", "pin": "1234"})
    assert r.status_code == 200, r.text
    assert r.json().get("token")


# ------------------------------------------------- gaps a mutation test found


def test_the_clinically_important_gap_is_filled_before_the_trivial_one(db):
    """Emptying GROUP_PRIORITY changed nothing that any test noticed.

    Without it the engine fills whichever gap happens to have the cheapest
    food, so a woman short of flesh foods, dark leaves AND "other fruit" is
    advised about fruit. The ordering is the difference between advice that
    addresses anaemia and stunting and advice that addresses neither.
    """
    from app.engines.nutrition import MDD_W, Recall, recommend

    # Everything present except one important gap and one trivial one.
    present = ["grains", "pulses", "nuts_seeds", "dairy", "eggs",
               "vita_fruit_veg", "other_veg"]
    recall = Recall(MDD_W, present)
    assert set(recall.missing) == {"flesh", "dark_leafy", "other_fruit"}

    rec = recommend(recall, month=7, affordability="low")
    assert rec.group in ("flesh", "dark_leafy"), \
        "filled the trivial gap first: chose {}".format(rec.group)

    # And the priority table must cover every group in both instruments, or a
    # missing key silently falls to the default and reorders everything.
    from app.data.foods import groups_for
    from app.engines.nutrition import GROUP_PRIORITY, MDD_CHILD
    for instrument in (MDD_W, MDD_CHILD):
        for group in groups_for(instrument):
            assert group in GROUP_PRIORITY, \
                "{} has no priority, so it sorts as an average gap".format(group)


def test_an_oversized_upload_is_refused_before_it_is_held_in_memory(client, db, auth):
    """Removing the ceiling entirely broke no test."""
    from app.language import pipeline
    from app.models import Phrase

    pipeline.sync_catalogue(db, "kusaal")
    db.commit()
    phrase = db.query(Phrase).filter(Phrase.language == "kusaal").first()

    from tests.conftest import wav
    huge = wav(6 * 1024 * 1024)
    r = client.post("/api/language/phrases/{}/audio".format(phrase.id),
                    headers=auth, files={"file": ("big.wav", huge, "audio/wav")})
    assert r.status_code == 400
    assert "too large" in r.json()["detail"]

    db.expire_all()
    assert db.get(Phrase, phrase.id).audio_path is None


def test_a_replaced_recording_stops_outranking_the_one_that_replaced_it(db):
    """Clips are <key>.<ext> and .wav is probed first, so an mp3 take lost."""
    from app.language import pipeline
    from app.models import Phrase
    from app.telephony import ivr
    from tests.conftest import wav

    pipeline.sync_catalogue(db, "kusaal")
    phrase = (db.query(Phrase)
                .filter(Phrase.language == "kusaal", Phrase.key == "closing").first())

    pipeline.write_audio(db, phrase, wav(), source="recorded")
    assert phrase.audio_path.endswith(".wav")

    pipeline.write_audio(db, phrase, b"ID3\x04\x00" + b"\x00" * 3000,
                         source="recorded")
    assert phrase.audio_path.endswith(".mp3")
    assert ivr._audio_url("", "kusaal", "closing").endswith(".mp3"), \
        "the superseded take is still what a caller hears"


def test_a_format_this_system_cannot_play_is_refused_not_stored(client, db, auth):
    """FLAC was accepted, counted toward coverage, and never playable."""
    from app.language import pipeline
    from app.models import Phrase

    ok, reason = pipeline.looks_like_audio(b"fLaC" + b"\x00" * 2000)
    assert ok is False and "FLAC" in reason

    pipeline.sync_catalogue(db, "kusaal")
    db.commit()
    phrase = db.query(Phrase).filter(Phrase.language == "kusaal").first()
    r = client.post("/api/language/phrases/{}/audio".format(phrase.id),
                    headers=auth,
                    files={"file": ("x.flac", b"fLaC" + b"\x00" * 2000,
                                    "audio/flac")})
    assert r.status_code == 400


def test_correcting_a_translation_takes_the_old_clip_out_of_service(client, db, auth):
    """The fix landed in the pipeline and not in the sibling endpoint.

    The IVR resolves clips from disk, so nulling the column alone left the
    rejected wording going down the line -- and the next sync re-adopted it.
    """
    from app.language import pipeline
    from app.models import Phrase
    from app.telephony import ivr
    from tests.conftest import wav

    pipeline.sync_catalogue(db, "kusaal")
    phrase = (db.query(Phrase)
                .filter(Phrase.language == "kusaal", Phrase.key == "no_answer").first())
    for source in ("khaya_tts", "mms_tts"):
        pipeline.write_audio(db, phrase, wav(), source=source)
        db.commit()
        assert ivr._audio_url("", "kusaal", "no_answer")

        r = client.put("/api/language/phrases/{}".format(phrase.id), headers=auth,
                       json={"translated_text": "A corrected wording."})
        assert r.status_code == 200
        db.expire_all()
        assert ivr._audio_url("", "kusaal", "no_answer") is None, \
            "{} clip of the old wording still plays".format(source)

        pipeline.sync_catalogue(db, "kusaal")
        db.commit()
        assert ivr._audio_url("", "kusaal", "no_answer") is None, \
            "the retired {} clip was re-adopted by the next sync".format(source)


def test_the_advice_she_was_given_is_actually_recorded(db):
    """The helper wrote to session.answers and advance overwrote it.

    Net effect at flush: both the chosen food and the message vanished, so the
    no-repeat logic read None forever -- the exact failure `exclude` exists to
    prevent, in the commit that claimed to fix it.
    """
    from app.telephony import ivr, service as tel

    patient = db.query(Patient).filter(Patient.name == "Amina Fuseini").first()
    session, _ = tel.start_call(db, phone=patient.phone, patient_id=patient.id,
                                purpose="outreach", language="english")
    session.include_diet = True
    db.flush()

    for digit in [None, "1"] + ["2"] * 20:
        turn = ivr.advance(db, session, digit, "", "http://x/cb")
        if session.state in ("birth_plan", "done"):
            break
    db.commit()
    db.expire_all()

    stored = db.get(CallSession, session.id).answers or {}
    assert stored.get("nutrition_message"), "what she was told was not recorded"
    assert stored.get("nutrition_food"), "the food chosen was not recorded"


def test_she_is_not_given_word_for_word_identical_advice_every_call(db):
    """`exclude` was passed, read None, and did nothing."""
    from app.telephony import ivr, service as tel

    patient = db.query(Patient).filter(Patient.name == "Zeinab Mahama").first()
    heard = []
    for _ in range(2):
        session, _ = tel.start_call(db, phone=patient.phone,
                                    patient_id=patient.id, purpose="outreach",
                                    language="english")
        session.include_diet = True
        db.flush()
        # Run to the end: the diet event that `exclude` reads is only written
        # when the call finalises.
        for digit in [None, "1"] + ["2"] * 20 + ["1"] * 3:
            turn = ivr.advance(db, session, digit, "", "http://x/cb")
            if turn.finished:
                break
        # What the telephony callback does when the provider reports the call
        # ended. It is what writes the diet event that `exclude` reads.
        ivr.finalise(db, session)
        db.commit()
        heard.append((db.get(CallSession, session.id).answers or {}).get(
            "nutrition_food"))

    assert all(heard), "no advice recorded at all: {}".format(heard)
    assert heard[0] != heard[1], \
        "identical advice on consecutive contacts: {}".format(heard[0])


def test_silence_at_the_birth_plan_is_not_recorded_as_an_answer(db):
    """The danger block refuses to read silence as "no". This branch did not.

    A dropped keypress was filed as "she has made no birth plan", she was given
    the advice for that, and the call ended.
    """
    from app.telephony import ivr, service as tel

    patient = db.query(Patient).filter(Patient.name == "Hawa Sulemana").first()
    session, _ = tel.start_call(db, phone=patient.phone, patient_id=patient.id,
                                purpose="outreach", language="english")
    db.flush()
    for digit in [None, "1"] + ["2"] * 8:
        ivr.advance(db, session, digit, "", "http://x/cb")
        if session.state == "birth_plan":
            break
    assert session.state == "birth_plan"

    first = ivr.advance(db, session, None, "", "http://x/cb")
    assert not first.finished, "silence ended the call on the first try"
    assert session.state == "birth_plan", "it moved on without an answer"

    ivr.advance(db, session, None, "", "http://x/cb")
    last = ivr.advance(db, session, None, "", "http://x/cb")
    assert last.finished
    assert (session.answers or {}).get("birth_plan_ready") is None, \
        "recorded an answer she never gave"
    assert "birth_plan_no" not in last.xml and "birth_plan_yes" not in last.xml
    assert "arrange money" not in last.xml.lower(), \
        "gave the advice for a plan she was never asked about"


def test_a_wrong_key_does_not_hold_the_line_open_forever(db):
    """Silence was capped at two tries. A misdial was capped at nothing."""
    from app.telephony import ivr, service as tel

    patient = db.query(Patient).filter(Patient.name == "Rahma Osman").first()
    session, _ = tel.start_call(db, phone=patient.phone, patient_id=patient.id,
                                purpose="outreach", language="english")
    db.flush()
    ivr.advance(db, session, None, "", "http://x/cb")

    for _ in range(ivr.MAX_MISDIALS):
        turn = ivr.advance(db, session, "7", "", "http://x/cb")
        assert not turn.finished
        assert "did not get that" in turn.xml, \
            "she was re-asked with no sign anything went wrong"

    final = ivr.advance(db, session, "7", "", "http://x/cb")
    assert final.finished, "the call never ends however many keys are pressed"


def test_a_woman_who_rings_the_hotline_is_not_asked_if_it_is_a_good_time(db):
    """She rang because something is wrong, and got the routine check-in.

    Pressing 2 -- "no, not a good time" -- ended her emergency call with "we
    will call you another time", and she was never told about pressing 9,
    because the escape hint only played after she had already pressed 1.
    """
    from app.telephony import ivr, service as tel

    patient = db.query(Patient).filter(Patient.name == "Amina Fuseini").first()
    session, _ = tel.start_call(db, phone=patient.phone, patient_id=patient.id,
                                purpose="hotline", language="english")
    db.flush()

    opening = ivr.advance(db, session, None, "", "http://x/cb")
    text = opening.xml.lower()
    assert "good time to talk" not in text, "she got the scheduled-contact greeting"
    assert "press 9" in text, "never told how to reach a person"
    assert "emergency" in text

    turn = ivr.advance(db, session, "1", "", "http://x/cb")
    assert not turn.finished
    assert session.state == "danger", "pressing 1 did not start the questions"


def test_a_worker_elsewhere_cannot_read_or_confirm_this_emergency(client, db, auth):
    """Locking /api/circle left the same data readable through /api/emergencies.

    _payer reads the same table, and /validate fires the family SMS that was
    deliberately moved behind a clinician.
    """
    from app.models import Facility, User as UserModel
    from app.security import hash_pin

    far = Facility(name="Distant CHPS", community="Nowhere", region="Upper East")
    db.add(far)
    db.flush()
    outsider = UserModel(name="Outsider Two", phone="+233209999881", role="cho",
                         pin_hash=hash_pin("1234"), facility_id=far.id)
    db.add(outsider)
    db.commit()
    token = client.post("/api/auth/login",
                        json={"phone": "+233209999881", "pin": "1234"}
                        ).json()["token"]
    theirs = {"Authorization": "Bearer {}".format(token)}

    emergency = db.query(Emergency).first()
    assert emergency is not None
    for method, path in (("get", ""), ("post", "/validate"), ("post", "/outcome")):
        url = "/api/emergencies/{}{}".format(emergency.id, path)
        r = (client.get(url, headers=theirs) if method == "get"
             else client.post(url, headers=theirs,
                              json={"outcome": "care_received"}))
        assert r.status_code == 404, "{} {} -> {}".format(method, path, r.status_code)


def test_correcting_a_mistyped_driver_number_does_not_leave_it_on_call(client, db, auth):
    """There is no delete route, and rank_drivers falls back to the whole table.

    So a number that never belonged to a driver was dialled during other
    households' emergencies, ahead of the real roster.
    """
    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    for number in ("+233201110001", "+233201110002", "+233201110003"):
        client.put("/api/circle/{}".format(patient.id), headers=auth,
                   json={"role": "driver", "name": "Yakubu", "phone": number,
                         "detail": "motorking"})
    db.expire_all()

    mine = {"+233201110001", "+233201110002", "+233201110003"}
    live = {d.phone for d in db.query(Driver)
            .filter(Driver.source == "care_circle",
                    Driver.available.is_(True)).all()} & mine
    assert live == {"+233201110003"}, \
        "typos left on call: {}".format(sorted(live))
    # The retired rows are kept, not deleted -- one of them may be the real
    # number and the correction the mistake.
    assert db.query(Driver).filter(Driver.phone.in_(mine)).count() == 3


def test_the_gate_is_idempotent_in_the_function_that_is_the_gate(db):
    """The guard lived in the HTTP handler, so calling the gate twice re-sent."""
    from app.models import CareCircleMember, Message

    patient = Patient(name="Twice Test", phone="+233240000821",
                      community="Kpale", region="Northern", consent=True)
    db.add(patient)
    db.flush()
    db.add(CareCircleMember(patient_id=patient.id, role="decision_maker",
                            name="Him", phone="+233240000822"))
    db.flush()

    emergency = services.raise_emergency(db, patient, ["sign.bleeding"], "ivr")
    worker = db.query(User).filter(User.role == "cho").first()
    before = db.query(Message).filter(Message.kind == "circle_alert").count()
    services.validate_emergency(db, emergency, worker)
    services.validate_emergency(db, emergency, worker)
    db.flush()
    assert db.query(Message).filter(
        Message.kind == "circle_alert").count() == before + 1


def test_an_added_column_gets_the_default_the_models_promise(tmp_path):
    """A SQLAlchemy `default=` is applied in Python; the database never sees it.

    So a not-null column added by ALTER TABLE held NULL on every existing row
    while the models insisted it could not be null, and the migration reported
    plain success.
    """
    from sqlalchemy import (Column, MetaData, String, Table, create_engine,
                            text)
    from app.db import Base
    from app.migrate import add_missing_columns

    engine = create_engine("sqlite:///{}".format(tmp_path / "old2.db"))
    old = MetaData()
    Table("patients", old,
          Column("id", String, primary_key=True),
          Column("name", String),
          Column("phone", String))
    old.create_all(engine)
    with engine.begin() as c:
        c.execute(text("INSERT INTO patients (id, name, phone) "
                       "VALUES ('1', 'Old Row', '+233240000001')"))

    Base.metadata.create_all(bind=engine)
    added = add_missing_columns(engine)

    with engine.begin() as c:
        region = c.execute(text("SELECT region FROM patients")).scalar()
    assert region == "Northern", \
        "existing row holds {!r} in a column the models say is never null".format(
            region)
    assert any("backfilled" in a for a in added), \
        "the migration did not report what it filled in"
    again = [a for a in add_missing_columns(engine) if not a.startswith("SKIPPED")]
    assert again == [], "not idempotent: {}".format(again)
