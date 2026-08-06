"""The transport roster.

Delay 2 is a vehicle arriving, so these are the claims that would cost one: a
number that cannot be dialled sitting in the queue, one handset holding two
positions, a man retired off the roster while he is on the road, and a village
with women enrolled and nothing registered that can carry them.
"""
import os
import tempfile

import pytest

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tempfile.mkdtemp(), "drivers.db")
os.environ["SEED_ON_START"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app import services  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (CareCircleMember, Dispatch, Driver, Emergency,  # noqa: E402
                        Patient)


@pytest.fixture(scope="module")
def db():
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


def test_roster_is_visible_at_all(client, auth):
    """It was not. There was no route that could list a driver."""
    r = client.get("/api/drivers", headers=auth)
    assert r.status_code == 200
    drivers = r.json()["drivers"]
    assert drivers, "the seed registers drivers and the roster shows none"
    assert {"name", "phone_display", "community", "vehicle_type",
            "available", "on_run"} <= set(drivers[0])


def test_roster_needs_a_session(client):
    assert client.get("/api/drivers").status_code == 401


def test_undiallable_number_is_refused(client, auth):
    """A driver who cannot be rung still holds a position in the cascade.

    normalise() hands back anything it cannot parse on purpose -- a short code
    is still something a person meant to type. On a driver it is not: the call
    fails at two in the morning instead of at the form.
    """
    r = client.post("/api/drivers", headers=auth,
                    json={"name": "Nobody", "phone": "12",
                          "community": "Tolon"})
    assert r.status_code == 422
    assert "dialled" in r.json()["detail"]


def test_local_number_is_stored_in_the_form_the_network_uses(client, auth):
    """Africa's Talking requires E.164; a CHO writes 024 with spaces in it."""
    r = client.post("/api/drivers", headers=auth,
                    json={"name": "Musah Abdulai", "phone": "024 411 1222",
                          "community": "Tolon", "vehicle_type": "motorking"})
    assert r.status_code == 200
    assert r.json()["phone"] == "+233244111222"
    # Stored as the network wants it, shown as a person writes it.
    assert r.json()["phone_display"] == "024 411 1222"


def test_one_handset_cannot_hold_two_positions(client, auth):
    """Two rows for one number rings the same man twice.

    The cascade already dedupes by handset, and it has to, because it burns a
    position in a queue that exists for a woman who is bleeding. The roster
    should not be creating the duplicate in the first place.
    """
    client.post("/api/drivers", headers=auth,
                json={"name": "Sulemana Adam", "phone": "0209990001",
                      "community": "Kpale"})
    again = client.post("/api/drivers", headers=auth,
                        json={"name": "S. Adam", "phone": "+233209990001",
                              "community": "Kpale"})
    assert again.status_code == 409
    assert "already on the roster" in again.json()["detail"]


def test_a_retired_number_comes_back_rather_than_duplicating(client, auth, db):
    """Correcting a mistake must not leave a household with no cascade.

    A row is retired by availability, not deleted, so re-registering the same
    handset revives the row instead of adding a second one.
    """
    made = client.post("/api/drivers", headers=auth,
                       json={"name": "Yakubu Seidu", "phone": "0209990002",
                             "community": "Kpale"}).json()
    off = client.patch("/api/drivers/" + made["id"], headers=auth,
                       json={"available": False})
    assert off.json()["available"] is False

    back = client.post("/api/drivers", headers=auth,
                       json={"name": "Yakubu Seidu", "phone": "0209990002",
                             "community": "Kpale", "vehicle_type": "car"})
    assert back.status_code == 200
    assert back.json()["id"] == made["id"], "a second row for one handset"
    assert back.json()["available"] is True
    assert back.json()["vehicle_type"] == "car"
    assert db.query(Driver).filter(Driver.phone == "+233209990002").count() == 1


def test_retired_drivers_are_out_of_the_list_but_findable(client, auth):
    shown = [d["name"] for d in client.get(
        "/api/drivers", headers=auth).json()["drivers"]]
    everyone = [d["name"] for d in client.get(
        "/api/drivers?include_retired=true", headers=auth).json()["drivers"]]
    assert len(everyone) >= len(shown)


def test_a_driver_on_the_road_cannot_be_retired(client, auth, db):
    """Retiring him removes the only row that says where she is."""
    patient = db.query(Patient).first()
    driver = db.query(Driver).filter(Driver.available.is_(True)).first()
    emergency = Emergency(patient_id=patient.id, status="transporting",
                          reason_codes=["danger_sign"])
    db.add(emergency)
    db.flush()
    dispatch = Dispatch(emergency_id=emergency.id, driver_id=driver.id,
                        status="accepted", position=1)
    db.add(dispatch)
    db.commit()

    refused = client.patch("/api/drivers/" + driver.id, headers=auth,
                           json={"available": False})
    assert refused.status_code == 409
    assert "on a run" in refused.json()["detail"]

    on_roster = {d["id"]: d for d in client.get(
        "/api/drivers", headers=auth).json()["drivers"]}
    assert on_roster[driver.id]["on_run"]["status"] == "accepted"
    assert on_roster[driver.id]["on_run"]["patient_name"] == patient.name

    emergency.status = "closed"
    db.commit()


def test_a_closed_case_is_not_a_live_run(client, auth, db):
    """An accepted dispatch stays accepted forever after the case closes.

    Reading that as a live run showed every driver who has ever helped as
    permanently busy, and a busy driver is one a worker will not ring.
    """
    driver = db.query(Driver).filter(Driver.available.is_(True)).first()
    view = {d["id"]: d for d in client.get(
        "/api/drivers", headers=auth).json()["drivers"]}
    assert view[driver.id]["on_run"] is None


def test_response_rate_is_absent_rather_than_invented(client, auth):
    """Ranking treats an untried driver as mid-table. A screen must not print
    that as though it were measured."""
    fresh = client.post("/api/drivers", headers=auth,
                        json={"name": "Untried Man", "phone": "0209990003",
                              "community": "Tolon"}).json()
    assert fresh["offered_count"] == 0
    assert fresh["response_rate"] is None


def test_the_queue_can_be_read_before_the_emergency(client, auth, db):
    """Ranking that only runs during an emergency cannot be checked before one.

    This is the same function the cascade calls, so what a worker reads on a
    quiet Tuesday is what happens at two in the morning.
    """
    patient = (db.query(Patient)
                 .filter(Patient.community == "Kpale").first())
    r = client.get("/api/drivers/for-patient/" + patient.id, headers=auth)
    assert r.status_code == 200
    queue = r.json()["queue"]
    assert queue, "no driver would be rung for her at all"
    assert [q["position"] for q in queue] == list(range(1, len(queue) + 1))
    assert queue[0]["why"]


def test_the_man_she_named_is_first_and_the_screen_says_why(client, auth, db):
    patient = db.query(Patient).filter(Patient.community == "Kpale").first()
    named = (db.query(CareCircleMember)
               .filter(CareCircleMember.patient_id == patient.id,
                       CareCircleMember.role == "driver").first())
    if named is None or not named.phone:
        pytest.skip("this household names no driver")
    top = client.get("/api/drivers/for-patient/" + patient.id,
                     headers=auth).json()["queue"][0]
    assert top["phone"] == named.phone
    assert top["why"] == "She named him herself"


def test_her_own_community_outranks_the_next_village(client, auth, db):
    patient = db.query(Patient).filter(Patient.community == "Kpale").first()
    queue = client.get("/api/drivers/for-patient/" + patient.id,
                       headers=auth).json()["queue"]
    communities = [q["community"] for q in queue]
    own = [i for i, c in enumerate(communities) if c == "Kpale"]
    away = [i for i, c in enumerate(communities) if c != "Kpale"]
    assert not own or not away or max(own) < min(away)


def test_the_queue_does_not_stop_at_her_village(client, auth, db):
    """A queue that excludes the next village stops with a vehicle unasked."""
    patient = db.query(Patient).filter(Patient.community == "Kpale").first()
    queue = client.get("/api/drivers/for-patient/" + patient.id,
                       headers=auth).json()["queue"]
    assert any(q["community"] != "Kpale" for q in queue)


def test_another_facility_cannot_read_a_household_queue(client, auth, db):
    """The queue carries family phone numbers. It is scoped like the record."""
    patient = db.query(Patient).first()
    was = (patient.assigned_cho_id, patient.facility_id)
    patient.assigned_cho_id = "someone-else"
    patient.facility_id = "another-facility"
    db.commit()
    try:
        r = client.get("/api/drivers/for-patient/" + patient.id, headers=auth)
        assert r.status_code == 404
    finally:
        # Put her back even if the assertion fails. Left reassigned, she is
        # invisible to every test after this one, and they fail somewhere else
        # entirely -- which is a worse bug to read than the one being tested.
        patient.assigned_cho_id, patient.facility_id = was
        db.commit()


def test_the_map_names_a_village_with_women_and_no_vehicle(client, auth, db):
    """The gap worth showing. It is knowable today and nothing said it."""
    db.add(Patient(name="Abibata Alhassan", phone="+233209998888",
                   community="Nyankpala",
                   minutes_to_facility=70, road_condition="poor"))
    db.commit()

    body = client.get("/api/drivers/map", headers=auth).json()
    places = {p["community"]: p for p in body["communities"]}
    assert "Nyankpala" in places
    assert places["Nyankpala"]["uncovered"] is True
    assert "Nyankpala" in body["uncovered"]
    assert places["Kpale"]["uncovered"] is False
    # Worst first: the villages with women and no vehicle are the work.
    assert body["communities"][0]["uncovered"] is True


def test_a_bicycle_is_not_cover(client, auth, db):
    """A vehicle that cannot carry a woman in labour is not transport."""
    client.post("/api/drivers", headers=auth,
                json={"name": "Bicycle Man", "phone": "0209990004",
                      "community": "Nyankpala", "vehicle_type": "bicycle"})
    places = {p["community"]: p for p in client.get(
        "/api/drivers/map", headers=auth).json()["communities"]}
    assert places["Nyankpala"]["drivers"] == 1
    assert places["Nyankpala"]["uncovered"] is True, \
        "a bicycle was counted as transport"

    client.post("/api/drivers", headers=auth,
                json={"name": "Motorking Man", "phone": "0209990005",
                      "community": "Nyankpala", "vehicle_type": "motorking"})
    places = {p["community"]: p for p in client.get(
        "/api/drivers/map", headers=auth).json()["communities"]}
    assert places["Nyankpala"]["uncovered"] is False


def test_the_map_reports_the_furthest_household_not_the_average(client, auth, db):
    """A mean hides the compound an hour further out."""
    db.add(Patient(name="Fati Mahama", phone="+233209997777",
                   community="Nyankpala",
                   minutes_to_facility=140, road_condition="poor"))
    db.commit()
    places = {p["community"]: p for p in client.get(
        "/api/drivers/map", headers=auth).json()["communities"]}
    assert places["Nyankpala"]["minutes_to_facility"] == 140
    assert places["Nyankpala"]["road_condition"] == "poor"


def test_an_unknown_vehicle_is_refused(client, auth):
    r = client.post("/api/drivers", headers=auth,
                    json={"name": "Helicopter Man", "phone": "0209990006",
                          "community": "Tolon", "vehicle_type": "helicopter"})
    assert r.status_code == 422


def test_location_is_a_note_a_person_typed(client, auth, db):
    """There is no automated tracking here. A nurse writes down what the driver
    said on the phone, and the record says when."""
    patient = db.query(Patient).filter(Patient.community == "Kpale").first()
    driver = db.query(Driver).filter(Driver.available.is_(True)).first()
    emergency = Emergency(patient_id=patient.id, status="transporting",
                          reason_codes=["danger_sign"])
    db.add(emergency)
    db.flush()
    dispatch = Dispatch(emergency_id=emergency.id, driver_id=driver.id,
                        status="accepted", position=1)
    db.add(dispatch)
    db.commit()

    r = client.post("/api/drivers/dispatches/{}/location".format(dispatch.id),
                    headers=auth, json={"note": "Passed the Kpale junction"})
    assert r.status_code == 200
    assert r.json()["location_note"] == "Passed the Kpale junction"
    assert r.json()["location_at"]

    emergency.status = "closed"
    db.commit()
    late = client.post("/api/drivers/dispatches/{}/location".format(dispatch.id),
                       headers=auth, json={"note": "Arrived"})
    assert late.status_code == 409


# ------------------------------------------------- she dials a driver herself
#
# The cascade rings drivers on the platform's initiative after a human confirms
# a case. This is the other direction: she asks, and is connected. Nothing is
# decided, so nothing waits for a validation that is not coming at 2am.


def _hotline(db, patient, session_id):
    from app.models import CallSession
    session = CallSession(id=session_id, patient_id=patient.id,
                          phone=patient.phone, purpose="hotline",
                          language="english", state="greet", answers={},
                          transcript=[], direction="outbound")
    db.add(session)
    db.commit()
    return session


def _press(client, session_id, phone, digit=None):
    data = {"sessionId": session_id, "isActive": "1",
            "callerNumber": "+233200000000", "destinationNumber": phone,
            "direction": "outbound"}
    if digit is not None:
        data["dtmfDigits"] = digit
    return client.post("/api/telephony/voice", data=data)


def test_transport_is_offered_on_the_hotline_menu(client, db):
    patient = db.query(Patient).filter(Patient.community == "Kpale").first()
    _hotline(db, patient, "menu-1")
    body = _press(client, "menu-1", patient.phone).text
    assert "Press 2" in body and "transport" in body.lower()
    # 9 stays the escape hatch rather than becoming a menu item.
    assert "Press 9" in body


def test_pressing_two_connects_her_to_a_driver(client, db):
    """Straight through, with no dispatch row and no validation in the way."""
    patient = db.query(Patient).filter(Patient.community == "Kpale").first()
    before = db.query(Dispatch).count()
    _hotline(db, patient, "dial-1")
    _press(client, "dial-1", patient.phone)
    body = _press(client, "dial-1", patient.phone, "2").text

    assert "<Dial" in body, "she was not put through to anyone"
    assert 'sequential="true"' in body
    assert db.query(Dispatch).count() == before, \
        "a direct call started a dispatch cascade"


def test_the_man_she_named_is_rung_first(client, db):
    patient = db.query(Patient).filter(Patient.community == "Kpale").first()
    named = (db.query(CareCircleMember)
               .filter(CareCircleMember.patient_id == patient.id,
                       CareCircleMember.role == "driver").first())
    if named is None or not named.phone:
        pytest.skip("this household names no driver")
    _hotline(db, patient, "dial-2")
    _press(client, "dial-2", patient.phone)
    body = _press(client, "dial-2", patient.phone, "2").text
    numbers = body.split('phoneNumbers="')[1].split('"')[0].split(",")
    assert numbers[0] == named.phone


def test_she_is_not_left_listening_to_one_ringing_phone(client, db):
    """Sequential down the queue, so a driver asleep is not the end of it."""
    patient = db.query(Patient).filter(Patient.community == "Kpale").first()
    _hotline(db, patient, "dial-3")
    _press(client, "dial-3", patient.phone)
    body = _press(client, "dial-3", patient.phone, "2").text
    numbers = body.split('phoneNumbers="')[1].split('"')[0].split(",")
    assert len(numbers) > 1
    assert len(numbers) == len(set(numbers)), "one handset rung twice"


def test_the_hold_message_is_about_a_driver_not_a_nurse(client, db):
    """dial() hardcoded the nurse's audio key, so any other use of it played
    'connecting you to a nurse' in her own language while ringing a driver."""
    patient = db.query(Patient).filter(Patient.community == "Kpale").first()
    _hotline(db, patient, "dial-4")
    _press(client, "dial-4", patient.phone)
    body = _press(client, "dial-4", patient.phone, "2").text
    assert "driver" in body.lower()
    assert "nurse" not in body.lower()


def test_asking_for_transport_tells_her_health_worker(client, db):
    """She may not ring anyone again once she is in the vehicle."""
    from app.models import Event, Message
    patient = db.query(Patient).filter(Patient.community == "Kpale").first()
    before = db.query(Message).count()
    _hotline(db, patient, "dial-5")
    _press(client, "dial-5", patient.phone)
    _press(client, "dial-5", patient.phone, "2")

    logged = (db.query(Event)
                .filter(Event.patient_id == patient.id,
                        Event.event_type == "transport_requested").count())
    assert logged >= 1, "nothing recorded that she asked for a vehicle"
    assert db.query(Message).count() > before, "nobody was told"


def test_a_village_with_no_driver_reaches_a_person_not_silence(client, db):
    """The one ending this call must never have."""
    from app.models import Message
    patient = Patient(name="Sanatu Yakubu", phone="+233209996666",
                      community="Zieng", minutes_to_facility=110,
                      road_condition="poor")
    db.add(patient)
    db.commit()

    for driver in db.query(Driver).all():
        driver.available = False
    db.commit()

    before = db.query(Message).count()
    _hotline(db, patient, "dial-6")
    _press(client, "dial-6", patient.phone)
    body = _press(client, "dial-6", patient.phone, "2").text

    assert "no driver" in body.lower(), "she was not told why the line changed"
    assert "<Dial" in body or "nurse" in body.lower() or "health worker" in body.lower()
    assert "goodbye" not in body.lower() or "nurse" in body.lower()
    assert db.query(Message).count() > before, "no CHO was told"

    for driver in db.query(Driver).all():
        driver.available = True
    db.commit()


def test_an_unknown_caller_gets_a_person(client, db):
    """No record means no community, so there is no queue to rank."""
    from app.models import CallSession
    session = CallSession(id="dial-7", patient_id=None, phone="+233209995555",
                          purpose="hotline", language="english", state="greet",
                          answers={}, transcript=[], direction="outbound")
    db.add(session)
    db.commit()
    _press(client, "dial-7", "+233209995555")
    body = _press(client, "dial-7", "+233209995555", "2").text
    assert "<Response>" in body
    assert "nurse" in body.lower() or "health worker" in body.lower()


# ------------------------------------------------ the cascade, while it runs
#
# A worker who confirmed an emergency saw "Status: dispatching" and nothing
# else. Whether anyone was left to try is what decides whether she waits or
# starts finding a car herself, and it was in the database the whole time.


def test_the_record_says_who_is_still_to_be_tried(client, auth, db):
    patient = db.query(Patient).filter(Patient.community == "Kpale").first()
    emergency = Emergency(patient_id=patient.id, status="dispatching",
                          reason_codes=["danger_sign"])
    db.add(emergency)
    db.flush()
    first = services.rank_drivers(db, patient)[0]
    db.add(Dispatch(emergency_id=emergency.id, driver_id=first.id,
                    status="declined", position=1))
    db.commit()

    body = client.get("/api/emergencies/" + emergency.id, headers=auth).json()
    assert [d["driver"]["name"] for d in body["dispatches"]] == [first.name]
    remaining = [d["name"] for d in body["queue_remaining"]]
    assert remaining, "two declines read as 'that was everyone'"
    assert first.name not in remaining, "a man who declined is not still to try"

    emergency.status = "closed"
    db.commit()


def test_the_queue_is_on_the_patient_record_too(client, auth, db):
    """This is the page she is looking at while it is running."""
    patient = db.query(Patient).filter(Patient.community == "Kpale").first()
    emergency = Emergency(patient_id=patient.id, status="dispatching",
                          reason_codes=["danger_sign"])
    db.add(emergency)
    db.commit()

    body = client.get("/api/patients/" + patient.id, headers=auth).json()
    live = [e for e in body["emergencies"] if e["id"] == emergency.id][0]
    assert isinstance(live["dispatches"], list)
    assert live["queue_remaining"], "the record cannot say who is next"

    emergency.status = "closed"
    db.commit()


def test_a_closed_case_lists_nobody_still_to_try(client, auth, db):
    """Nothing further happens on a closed case, so nothing is pending on it."""
    patient = db.query(Patient).filter(Patient.community == "Kpale").first()
    emergency = Emergency(patient_id=patient.id, status="closed",
                          reason_codes=["danger_sign"])
    db.add(emergency)
    db.commit()
    body = client.get("/api/emergencies/" + emergency.id, headers=auth).json()
    assert body["queue_remaining"] == []


def test_an_exhausted_queue_is_distinguishable_from_an_untouched_one(
        client, auth, db):
    """Empty for two different reasons, and only one of them means give up."""
    patient = db.query(Patient).filter(Patient.community == "Kpale").first()
    emergency = Emergency(patient_id=patient.id, status="no_transport",
                          reason_codes=["danger_sign"])
    db.add(emergency)
    db.flush()
    for position, driver in enumerate(services.rank_drivers(db, patient), 1):
        db.add(Dispatch(emergency_id=emergency.id, driver_id=driver.id,
                        status="declined", position=position))
    db.commit()

    body = client.get("/api/emergencies/" + emergency.id, headers=auth).json()
    assert body["queue_remaining"] == []
    assert body["dispatches"], "nothing distinguishes this from nobody tried"
    assert all(d["status"] == "declined" for d in body["dispatches"])

    emergency.status = "closed"
    db.commit()


# ------------------------------------------------------ credentials survive
#
# SQLite on a free-plan disk that is wiped on every deploy. An API key typed
# into Setup worked until the next push and then stopped, with nothing on
# screen changing when it did.


def test_a_setting_falls_back_to_the_environment(db, monkeypatch):
    from app import settings_store as store
    monkeypatch.setenv("AT_VOICE_NUMBER", "+233200000099")
    assert store.get(db, "at_voice_number") == "+233200000099"
    assert store.source(db, "at_voice_number") == "environment"


def test_what_was_typed_beats_the_environment(db, monkeypatch):
    """Someone standing at the screen changing a value must see it change."""
    from app import settings_store as store
    monkeypatch.setenv("AT_VOICE_NUMBER", "+233200000099")
    store.set_value(db, "at_voice_number", "+233200000088")
    db.commit()
    assert store.get(db, "at_voice_number") == "+233200000088"
    assert store.source(db, "at_voice_number") == "saved"
    store.set_value(db, "at_voice_number", "")
    db.commit()


def test_the_screen_says_whether_a_value_survives_a_deploy(client, auth, db,
                                                           monkeypatch):
    from app import settings_store as store
    monkeypatch.setenv("AT_API_KEY", "from-the-environment")
    fields = {f["key"]: f for f in client.get("/api/setup",
                                              headers=auth).json()["fields"]}
    assert fields["at_api_key"]["configured"] is True
    assert fields["at_api_key"]["source"] == "environment"
    # And still masked. The point of the env fallback is not to start
    # printing the key.
    assert "from-the-environment" not in str(fields["at_api_key"])


def test_an_environment_key_makes_the_provider_ready(db, monkeypatch):
    """The readiness panel is what a person reads before making a test call."""
    from app import settings_store as store
    monkeypatch.setenv("TELEPHONY_PROVIDER", "africastalking")
    monkeypatch.setenv("AT_API_KEY", "k")
    monkeypatch.setenv("AT_USERNAME", "sandbox")
    monkeypatch.setenv("AT_VOICE_NUMBER", "+233200000099")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.invalid")
    ready = store.readiness(db)
    assert ready["can_call"] is True
    assert ready["can_sms"] is True
    assert all(c["ok"] for c in ready["checks"] if c["name"] != "Test phone")
