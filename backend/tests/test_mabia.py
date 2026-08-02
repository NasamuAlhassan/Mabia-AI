"""The verification suite.

These are the claims the pitch makes. Each test is here because the claim would
be embarrassing to make and then have a judge break in thirty seconds.
"""
import datetime as dt
import os
import tempfile

import pytest

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tempfile.mkdtemp(), "test.db")
os.environ["SEED_ON_START"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app import events as ev  # noqa: E402
from app import services  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.engines.nutrition import MDD_CHILD, MDD_W, Recall, recommend  # noqa: E402
from app.engines.risk import AMBER, GREEN, RED, classify  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (CallSession, Emergency, Event, Message, NurseShift,  # noqa: E402
                        Patient, PatientState, User)
from app.security import hash_pin  # noqa: E402


@pytest.fixture(scope="module")
def db():
    """One session shared by the tests and the API.

    Without this the API opens its own connection, and SQLite -- correctly --
    refuses to let two writers into the same file. Sharing the session also
    means a test sees exactly what a request left behind.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    from app.db import get_db
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
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["token"]}


# ------------------------------------------------------------------ risk


class FakeSnap:
    def __init__(self, **kw):
        self.danger_signs = {}
        self.cleared_signs = {}
        self.mdd_score = None
        self.mdd_instrument = None
        self.mdd_missing = []
        self.mdd_history = []
        self.muac_mother = None
        self.muac_child = None
        self.ifa_adherent = None
        self.last_contact_at = None
        self.last_contact_outcome = None
        self.consecutive_unreachable = 0
        self.red_open = False
        self.delivered = False
        self.events_folded = 0
        for key, value in kw.items():
            setattr(self, key, value)

    @property
    def active_danger_signs(self):
        out = []
        for sign, at in self.danger_signs.items():
            cleared = self.cleared_signs.get(sign)
            if cleared is None or at >= cleared:
                out.append(sign)
        return sorted(out)


NOW = dt.datetime(2026, 8, 2, 12, 0)


@pytest.mark.parametrize("snapshot,expected,code", [
    (FakeSnap(), GREEN, None),
    (FakeSnap(danger_signs={"bleeding": NOW}), RED, "sign.bleeding"),
    (FakeSnap(danger_signs={"convulsions": NOW}), RED, "sign.convulsions"),
    (FakeSnap(danger_signs={"fever": NOW}), AMBER, "sign.fever"),
    (FakeSnap(muac_mother=21.4), AMBER, "muac.mother_low"),
    (FakeSnap(muac_mother=24.0), GREEN, None),
    (FakeSnap(muac_child=12.0), AMBER, "muac.child_moderate"),
    (FakeSnap(muac_child=11.0), RED, "muac.child_severe"),
    (FakeSnap(ifa_adherent=False), AMBER, "ifa.not_adherent"),
    (FakeSnap(consecutive_unreachable=3), AMBER, "contact.unreachable"),
    (FakeSnap(mdd_instrument="mdd_w", mdd_history=[3, 2]), AMBER,
     "diet.persistently_low"),
    (FakeSnap(mdd_instrument="mdd_w", mdd_history=[3, 7]), GREEN, None),
])
def test_risk_fixtures(snapshot, expected, code):
    verdict = classify(snapshot)
    assert verdict.level == expected, verdict.explain()
    if code:
        assert code in verdict.codes


def test_maternal_muac_threshold_is_23cm():
    assert classify(FakeSnap(muac_mother=22.9)).level == AMBER
    assert classify(FakeSnap(muac_mother=23.1)).level == GREEN


def test_a_denied_sign_clears_an_earlier_affirmation():
    later = NOW + dt.timedelta(hours=2)
    snap = FakeSnap(danger_signs={"fever": NOW}, cleared_signs={"fever": later})
    assert classify(snap).level == GREEN


def test_red_stays_red_until_a_human_closes_it():
    """The clinical rule. A newer benign observation must not silently clear it."""
    snap = FakeSnap(red_open=True)
    verdict = classify(snap)
    assert verdict.level == RED
    assert "emergency.open" in verdict.codes


# ------------------------------------------------------------- instruments


def test_the_two_instruments_are_not_the_same():
    """MDD-W is ten groups for a woman; the child indicator is eight."""
    assert Recall(MDD_W, []).total == 10
    assert Recall(MDD_CHILD, []).total == 8
    assert "breastmilk" in Recall(MDD_CHILD, []).missing
    assert "breastmilk" not in Recall(MDD_W, []).missing


def test_minimum_is_five_on_both_instruments():
    assert Recall(MDD_W, ["grains"] * 1).minimum == 5
    assert Recall(MDD_CHILD, []).minimum == 5
    assert Recall(MDD_W, ["grains", "pulses", "nuts_seeds", "dairy",
                          "flesh"]).meets_minimum


# ------------------------------------------------------------- nutrition


def test_the_same_gap_gives_different_advice_in_different_months():
    """The test that proves the engine is real and not a static message bank."""
    gap = Recall(MDD_W, ["grains", "pulses", "nuts_seeds", "dairy", "flesh",
                         "eggs", "dark_leafy", "other_veg", "other_fruit"])
    assert gap.missing == ["vita_fruit_veg"]
    june = recommend(gap, region="Savannah", month=6, affordability="low")
    october = recommend(gap, region="Savannah", month=10, affordability="low")
    assert june.food["key"] != october.food["key"]
    assert june.season == "lean" and october.season == "harvest"


def test_lean_season_prefers_what_is_gathered_over_what_is_bought():
    """Within one gap, the lean season should push towards what is gathered.

    Stated per-gap, because the engine picks the gap first: across gaps, a
    missing flesh group outranks a missing fruit group regardless of season,
    and it should.
    """
    only_leaves_missing = Recall(MDD_W, [
        "grains", "pulses", "nuts_seeds", "dairy", "flesh", "eggs",
        "vita_fruit_veg", "other_veg", "other_fruit"])
    lean = recommend(only_leaves_missing, region="Northern", month=7,
                     affordability="low")
    assert lean.food["source"] == "gathered"
    assert lean.food["tier"] == "free"


def test_advice_rotates_through_her_gaps_instead_of_repeating():
    """A woman missing seven groups used to hear one sentence for a year."""
    gap = Recall(MDD_W, ["grains", "other_veg", "nuts_seeds"])
    seen, groups = [], []
    for _ in range(4):
        rec = recommend(gap, region="Northern", month=7, affordability="low",
                        recent_groups=groups)
        seen.append(rec.food["key"])
        groups.append(rec.group)
    assert len(set(seen)) == 4, "the engine repeated itself: {}".format(seen)


def test_lean_season_prices_put_eggs_out_of_reach():
    """The file's premise is that lean means prices up. It must actually bite."""
    from app.data.foods import FOODS_BY_KEY, tier_for
    eggs = FOODS_BY_KEY["eggs"]
    assert tier_for(eggs, "harvest") == "medium"
    assert tier_for(eggs, "lean") == "high"


def test_a_taboo_substitutes_within_the_same_food_group():
    """We do not argue with a taboo on an automated call. We offer another food."""
    gap = Recall(MDD_W, ["grains", "pulses", "nuts_seeds", "dairy", "flesh",
                         "eggs", "other_veg", "other_fruit", "vita_fruit_veg"])
    assert gap.missing == ["dark_leafy"]
    first = recommend(gap, month=7, affordability="low")
    second = recommend(gap, month=7, affordability="low",
                       taboos=[first.food["key"]])
    assert second.food["key"] != first.food["key"]
    assert "dark_leafy" in second.food["w_groups"]


def test_affordability_never_recommends_what_she_cannot_buy():
    gap = Recall(MDD_W, ["grains", "pulses", "nuts_seeds", "dairy", "eggs",
                         "dark_leafy", "vita_fruit_veg", "other_veg",
                         "other_fruit"])
    assert gap.missing == ["flesh"]
    low = recommend(gap, month=7, affordability="low")
    assert low.food["tier"] in ("free", "low")


def test_a_full_diet_is_told_so():
    every = [g for g in Recall(MDD_W, []).missing]
    full = Recall(MDD_W, every)
    rec = recommend(full, month=7)
    assert rec.food is None
    assert "every food group" in rec.message


# ------------------------------------------------------------------ log


def test_ingest_is_idempotent(db):
    patient = db.query(Patient).first()
    before = db.query(Event).count()
    for _ in range(3):
        ev.append(db, patient_id=patient.id, event_type=ev.VISIT,
                  event_id="fixed-id-1", payload={"note": "same event"})
    db.flush()
    assert db.query(Event).count() == before + 1


def test_a_late_sync_lands_in_history_not_at_the_end(db):
    """A worker syncing three days late must not clobber what the call recorded."""
    patient = db.query(Patient).filter(Patient.name == "Hawa Sulemana").first()
    now = dt.datetime.utcnow()

    ev.append(db, patient_id=patient.id, event_type=ev.MUAC,
              occurred_at=now, payload={"subject": "mother", "value_cm": 24.5})
    ev.refresh_state(db, patient.id)
    assert db.get(PatientState, patient.id).muac_mother == 24.5

    # Now a visit recorded THREE DAYS AGO arrives. It is older, so it must not
    # become the current value.
    ev.append(db, patient_id=patient.id, event_type=ev.MUAC,
              occurred_at=now - dt.timedelta(days=3),
              payload={"subject": "mother", "value_cm": 20.0})
    state = ev.refresh_state(db, patient.id)
    assert state.muac_mother == 24.5, "a late event overwrote a newer one"


def test_state_is_a_projection_and_can_be_rebuilt(db):
    patient = db.query(Patient).filter(Patient.name == "Amina Fuseini").first()
    before = ev.fold(db, patient.id).events_folded
    db.delete(db.get(PatientState, patient.id))
    db.flush()
    rebuilt = ev.refresh_state(db, patient.id)
    assert rebuilt.risk_level == RED
    assert rebuilt.events_folded == before


# ------------------------------------------------------------ emergencies


def test_a_red_call_raises_an_emergency_and_texts_the_cho(db):
    patient = db.query(Patient).filter(Patient.name == "Amina Fuseini").first()
    emergency = (db.query(Emergency)
                   .filter(Emergency.patient_id == patient.id).first())
    assert emergency is not None
    assert "sign.bleeding" in (emergency.reason_codes or [])
    assert emergency.status == "pending_validation", "must await a human"
    alerts = db.query(Message).filter(Message.kind == "red_alert").all()
    assert any("+233200000001" == m.to_phone for m in alerts)


def test_dispatch_cascades_and_records_response(db, client, auth):
    patient = db.query(Patient).filter(Patient.name == "Amina Fuseini").first()
    emergency = (db.query(Emergency)
                   .filter(Emergency.patient_id == patient.id).first())
    r = client.post("/api/emergencies/{}/validate".format(emergency.id),
                    headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("dispatching", "transporting")
    assert body["dispatches"], "validation should have called a driver"
    assert body["dispatches"][0]["driver"]["community"] == "Kpale"


def test_the_loop_stays_open_until_a_human_records_the_outcome(db, client, auth):
    patient = db.query(Patient).filter(Patient.name == "Amina Fuseini").first()
    emergency = (db.query(Emergency)
                   .filter(Emergency.patient_id == patient.id).first())
    assert db.get(PatientState, patient.id).risk_level == RED

    client.post("/api/emergencies/{}/outcome".format(emergency.id),
                headers=auth, json={"outcome": "care_received",
                                    "note": "Delivered at Kpale."})
    db.expire_all()
    assert db.get(Emergency, emergency.id).outcome == "care_received"
    assert db.get(PatientState, patient.id).red_open is False


# --------------------------------------------------------- no dead ends


def test_no_call_ever_dead_ends(db):
    """Empty the roster on purpose. The call must still alert a health worker.

    This is the one with real duty-of-care exposure: a woman routed to a phone
    that rings out, and nothing happening afterwards.
    """
    for shift in db.query(NurseShift).all():
        shift.on_call = False
    db.flush()

    patient = db.query(Patient).filter(Patient.name == "Zeinab Mahama").first()
    session = CallSession(id="dead-end-test", patient_id=patient.id,
                          phone=patient.phone, purpose="hotline",
                          language="dagbani", state="nurse", answers={},
                          transcript=[])
    db.add(session)
    db.flush()

    # Walk the whole cascade -- nurses, then the facility line -- until there is
    # genuinely nobody left to try.
    for _ in range(10):
        if services.nurse_target(db, session) is None:
            break
        session.nurse_attempt = (session.nurse_attempt or 0) + 1
    assert services.nurse_target(db, session) is None, "cascade should be exhausted"

    before = db.query(Message).count()
    message = services.terminal_fallback(db, session)
    db.flush()

    assert "health worker" in message.lower()
    assert db.query(Message).count() > before, "nobody was told"
    assert db.get(PatientState, patient.id).red_open is True

    for shift in db.query(NurseShift).all():
        shift.on_call = True
    db.flush()


def test_the_escape_hatch_works_from_any_state(db):
    from app.telephony import ivr
    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    session = CallSession(id="escape-test", patient_id=patient.id,
                          phone=patient.phone, purpose="outreach",
                          language="english", state="danger", cursor=2,
                          answers={}, transcript=[])
    db.add(session)
    db.flush()
    turn = ivr.advance(db, session, "9", "", "http://x/cb")
    assert turn.note == "nurse"
    assert session.escalated_to_nurse is True


# ------------------------------------------------------------------ IVR


def test_a_full_call_runs_and_folds_into_the_log(db, client, auth):
    """Drive the real webhook the way the simulator does."""
    patient = db.query(Patient).filter(Patient.name == "Memuna Iddris").first()
    from app.telephony import service as tel
    session, result = tel.start_call(db, phone=patient.phone,
                                     patient_id=patient.id, purpose="outreach",
                                     language="english", include_diet=False)
    db.commit()
    assert result.ok

    def press(digit=None):
        return client.post("/api/simulator/press", headers=auth,
                           json={"session_id": session.id, "digit": digit}).json()

    first = press(None)
    assert "GetDigits" in first["xml"]

    press("1")                       # yes, a good time
    for _ in range(4):
        press("2")                   # no to the first four danger signs
    last = press("1")                # yes to reduced fetal movement
    final = press("1")               # birth plan ready

    db.expire_all()
    refreshed = db.get(CallSession, session.id)
    assert refreshed.ended_at is not None
    state = db.get(PatientState, patient.id)
    assert state.risk_level == RED, "reduced fetal movement is an emergency"
    assert "sign.reduced_fetal_movement" in (state.reason_codes or [])


def test_prompts_stay_short_enough_to_finish_on_a_bad_line():
    from app.prompts import DANGER_QUESTIONS, SCRIPT
    for _, text in DANGER_QUESTIONS:
        assert len(text) < 120, text
    for key, text in SCRIPT.items():
        assert len(text) < 200, key


# ----------------------------------------------------------------- USSD


def test_ussd_screens_fit_the_character_budget(db, client):
    r = client.post("/api/telephony/ussd",
                    data={"sessionId": "u1", "phoneNumber": "+233200000001",
                          "text": "", "serviceCode": "*384*1234#"})
    assert r.status_code == 200
    assert r.text.startswith("CON ")
    assert len(r.text) <= 182, "USSD screens must fit one screen"

    r2 = client.post("/api/telephony/ussd",
                     data={"sessionId": "u2", "phoneNumber": "+233200000001",
                           "text": "2", "serviceCode": "*384*1234#"})
    assert len(r2.text) <= 182


def test_ussd_refuses_an_unknown_number(client):
    r = client.post("/api/telephony/ussd",
                    data={"sessionId": "u3", "phoneNumber": "+233999999999",
                          "text": "", "serviceCode": "*384*1234#"})
    assert r.text.startswith("END")


# ------------------------------------------------------------- hotline


def test_an_inbound_call_is_rejected_so_she_pays_nothing(db, client):
    """Flash-to-callback: we never answer, so she is never charged."""
    r = client.post("/api/telephony/voice",
                    data={"sessionId": "in-1", "isActive": "1",
                          "callerNumber": "+233240000002",
                          "destinationNumber": "+233200000000",
                          "direction": "inbound"})
    assert "<Reject/>" in r.text
    from app.models import CallbackRequest
    assert db.query(CallbackRequest).filter(
        CallbackRequest.phone == "+233240000002").count() >= 1


def test_callbacks_are_placed_back_to_the_caller(db, client, auth):
    r = client.post("/api/telephony/run-callbacks", headers=auth)
    assert r.status_code == 200
    assert r.json()["count"] >= 1


def test_dialling_endpoints_refuse_anonymous_callers(client):
    """These place outbound calls. Unauthenticated, they are toll fraud."""
    assert client.post("/api/telephony/run-callbacks").status_code == 401
    assert client.post("/api/telephony/flash",
                       params={"phone": "+15550001111"}).status_code == 401


# ------------------------------------------------------------------ sync


def test_sync_push_is_safe_to_repeat(client, auth, db):
    patient = db.query(Patient).first()
    payload = {"events": [{
        "event_id": "sync-dup-1", "patient_id": patient.id,
        "event_type": "visit_recorded", "payload": {"note": "offline visit"},
        "occurred_at": dt.datetime.utcnow().isoformat(), "device_id": "phone-a"}]}
    first = client.post("/api/sync/push", headers=auth, json=payload).json()
    second = client.post("/api/sync/push", headers=auth, json=payload).json()
    assert first["accepted"] == 1
    assert second["accepted"] == 0 and second["duplicates"] == 1


def test_enrolment_twice_offline_creates_one_patient(client, auth, db):
    body = {"name": "Test Duplicate", "phone": "+233240000777",
            "community": "Kpale", "consent": True, "event_id": "enrol-dup-1",
            "edd": (dt.date.today() + dt.timedelta(days=100)).isoformat()}
    client.post("/api/patients", headers=auth, json=body)
    count = db.query(Patient).filter(Patient.phone == "+233240000777").count()
    assert count == 1
    assert db.query(Event).filter(Event.event_id == "enrol-dup-1").count() == 1


# --------------------------------------------------------------- metrics


def test_metrics_report_gap_closure(client, auth):
    body = client.get("/api/metrics", headers=auth).json()
    assert "nutrition_gaps_closed" in body
    assert body["counts"]["gaps_measured"] >= 0
    assert body["enrolled"] >= 5
