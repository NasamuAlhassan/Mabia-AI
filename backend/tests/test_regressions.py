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

    xml = ivr.speak("http://x", "dagbani", "danger_bleeding", "Are you bleeding?")
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
    services.raise_emergency(db, patient, ["sign.bleeding"], "ivr")
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


def test_kusaal_audio_came_from_the_local_model(db):
    """Generated on this machine with no credits and no network at call time."""
    from app.models import Phrase

    rows = (db.query(Phrase)
              .filter(Phrase.language == "kusaal",
                      Phrase.audio_path.isnot(None)).all())
    if not rows:
        pytest.skip("no Kusaal clips in this checkout")
    assert all(r.audio_source == "mms_tts" for r in rows)
    assert all(r.audio_bytes > 5000 for r in rows), "a clip is suspiciously small"


def test_mms_refuses_rather_than_returning_silence():
    """A clip of nothing played down a phone line is worse than English."""
    from app.language import mms
    ok, audio, error = mms.synthesise("Hello", "dagbani")
    assert ok is False
    assert "No MMS model exists" in error
