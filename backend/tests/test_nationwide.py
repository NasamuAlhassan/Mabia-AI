"""Ghana-wide, not northern-only.

The platform started as five northern regions, and two things in it only made
sense there: the region list, and a nutrition model whose calendar and foods
were the savanna's. These tests pin the ways that going national could quietly
give a household the wrong advice, plus the language service we now run
ourselves.
"""
import datetime as dt
import os
import re
import tempfile
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tempfile.mkdtemp(), "nationwide.db")
os.environ["SEED_ON_START"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app.data import foods  # noqa: E402
from app.db import Base, SessionLocal, engine, get_db  # noqa: E402
from app.engines.nutrition import MDD_CHILD, MDD_W, Recall, recommend  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Patient  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


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
    assert r.status_code == 200
    return {"Authorization": "Bearer " + r.json()["token"]}


SOUTH = ["Ashanti", "Eastern", "Greater Accra", "Volta", "Western", "Central"]
NORTH = ["Northern", "North East", "Savannah", "Upper East", "Upper West"]


# --------------------------------------------------------------- the regions


def test_all_sixteen_regions_are_known():
    assert len(foods.REGIONS) == 16
    for region in SOUTH + NORTH:
        assert region in foods.REGION_ZONES


def test_the_frontend_list_cannot_drift_from_the_backend_list():
    """The enrolment form is offline, so it carries its own copy of the names."""
    source = (REPO / "frontend" / "src" / "lib" / "regions.js").read_text(
        encoding="utf-8")
    listed = re.findall(r"'([^']+)'", source.split("export const REGIONS")[1])
    assert sorted(listed) == sorted(foods.REGIONS)


# ------------------------------------------------------------------- seasons


def test_the_calendar_follows_the_region_not_the_country():
    """The lean season is May-August in the north and April-June in the south."""
    assert foods.season_for(7, "Northern") == "lean"
    assert foods.season_for(7, "Ashanti") == "harvest"
    assert foods.season_for(5, "Upper East") == "lean"
    assert foods.season_for(5, "Greater Accra") == "lean"
    assert foods.season_for(8, "Northern") == "lean"
    assert foods.season_for(8, "Eastern") == "harvest"


def test_every_month_has_exactly_one_season_in_every_calendar():
    for zone, calendar in foods.SEASON_CALENDARS.items():
        months = sorted(m for ms in calendar.values() for m in ms)
        assert months == list(range(1, 13)), zone


def test_an_unknown_region_is_given_no_calendar_rather_than_the_northern_one():
    for region in (None, "", "Unknown", "Narnia"):
        assert foods.season_for(7, region) == foods.UNSPECIFIED_SEASON


# --------------------------------------------------------------------- foods


def test_northern_foods_are_not_offered_in_the_south():
    """Baobab and ayoyo are northern; a household in Ashanti cannot gather them."""
    gap = Recall.from_complete(MDD_W, [g for g, _ in foods.MDDW_GROUPS
                                       if g != "dark_leafy"])
    assert gap.missing == ["dark_leafy"]
    for month in range(1, 13):
        rec = recommend(gap, region="Ashanti", month=month, affordability="high")
        if rec.food is not None:
            assert rec.food["key"] not in ("baobab_leaf", "wild_greens", "kenaf"), \
                "northern food offered in Ashanti in month {}".format(month)


def test_the_same_gap_gets_northern_food_in_the_north():
    gap = Recall.from_complete(MDD_W, [g for g, _ in foods.MDDW_GROUPS
                                       if g != "dark_leafy"])
    rec = recommend(gap, region="Northern", month=7, affordability="low")
    assert rec.food["key"] in ("baobab_leaf", "wild_greens", "kenaf", "moringa")


def test_an_unknown_region_gets_only_foods_sold_everywhere():
    everywhere = {f["key"] for f in foods.FOODS if f["regions"] == foods.ALL}
    for group in [g for g, _ in foods.MDDW_GROUPS]:
        gap = Recall(MDD_W, [], denied=[group])
        rec = recommend(gap, region=None, month=7, affordability="high")
        if rec.food is not None:
            assert rec.food["key"] in everywhere


def test_a_region_tag_is_always_all_or_real_regions():
    for food in foods.FOODS:
        if food["regions"] != foods.ALL:
            assert food["regions"], food["key"]
            assert set(food["regions"]) <= set(foods.REGIONS), food["key"]


def test_the_thin_southern_table_is_reported_not_hidden():
    """The southern food table is unwritten; the groups it cannot fill are named."""
    north = foods.uncovered_groups(MDD_W, "Northern")
    south = foods.uncovered_groups(MDD_W, "Ashanti")
    assert set(north) <= set(south)
    assert len(south) >= len(north)


def test_the_foods_endpoint_says_where_coverage_is_thin(client):
    out = client.get("/api/nutrition/foods", params={"region": "Ashanti",
                                                      "month": 7}).json()
    assert out["zone"] == "bimodal" and out["season"] == "harvest"
    assert "mdd_w" in out["uncovered_groups"]
    north = client.get("/api/nutrition/foods", params={"region": "Northern",
                                                        "month": 7}).json()
    assert north["zone"] == "savanna" and north["season"] == "lean"


def test_the_regions_endpoint_lists_all_sixteen(client):
    out = client.get("/api/nutrition/regions").json()
    assert len(out) == 16
    assert {r["zone"] for r in out} == {"savanna", "bimodal"}


# --------------------------------------------------------------- enrolment


def _body(**over):
    body = {"name": "Ama Mensah", "phone": "+233240001111", "community": "Kumasi",
            "consent": True,
            "edd": (dt.date.today() + dt.timedelta(days=100)).isoformat()}
    body.update(over)
    return body


def test_enrolment_requires_a_region(client, auth):
    """No silent default: a missing region used to mean Northern."""
    r = client.post("/api/patients", headers=auth, json=_body())
    assert r.status_code == 422


def test_enrolment_refuses_a_region_that_does_not_exist(client, auth):
    r = client.post("/api/patients", headers=auth, json=_body(region="Atlantis"))
    assert r.status_code == 422


def test_a_southern_woman_can_be_enrolled_and_is_advised_as_one(client, auth, db):
    r = client.post("/api/patients", headers=auth,
                    json=_body(region="Ashanti", phone="+233240001112"))
    assert r.status_code == 200, r.text
    patient = db.query(Patient).filter(Patient.phone == "+233240001112").one()
    assert patient.region == "Ashanti"
    out = client.post("/api/nutrition/assess", headers=auth, json={
        "instrument": MDD_W, "present": ["grains"], "month": 7,
        "patient_id": patient.id}).json()
    assert out["recommendation"]["season"] == "harvest"


def test_a_queued_enrolment_without_a_region_is_kept_as_unknown(client, auth, db):
    """It cannot be asked again, so it is kept -- but not as a northern woman."""
    payload = {"events": [{
        "event_id": "nation-enrol-1", "event_type": "enrolment",
        "payload": {"name": "Queued Woman", "phone": "+233240001113",
                    "community": "Somewhere", "consent": True},
        "occurred_at": dt.datetime.utcnow().isoformat(), "device_id": "phone-z"}]}
    client.post("/api/sync/push", headers=auth, json=payload)
    patient = db.query(Patient).filter(Patient.phone == "+233240001113").one()
    assert patient.region == foods.UNKNOWN_REGION


def test_a_queued_enrolment_with_a_real_region_keeps_it(client, auth, db):
    payload = {"events": [{
        "event_id": "nation-enrol-2", "event_type": "enrolment",
        "payload": {"name": "Queued Volta", "phone": "+233240001114",
                    "community": "Ho", "region": "Volta", "consent": True},
        "occurred_at": dt.datetime.utcnow().isoformat(), "device_id": "phone-z"}]}
    client.post("/api/sync/push", headers=auth, json=payload)
    patient = db.query(Patient).filter(Patient.phone == "+233240001114").one()
    assert patient.region == "Volta"


# ---------------------------------------------- the language service (Space)


class _Resp:
    def __init__(self, status=200, body=None, text="", content=b""):
        self.status_code = status
        self._body = body
        self.text = text
        self.content = content

    def json(self):
        return self._body


def _fake_space(monkeypatch, translation="Fʋ mɔr ziimnam bee?", covered=True,
                audio=b"RIFF" + b"\x00" * 600):
    """Stand in for the Space's Gradio call/stream pair. No network."""
    from app.language import tekyerema
    monkeypatch.setenv("TEKYEREMA_URL", "https://space.test")
    calls = []

    def post(url, json=None, timeout=None):
        calls.append(("post", url, json))
        return _Resp(200, {"event_id": "e1"})

    def get(url, timeout=None):
        calls.append(("get", url, None))
        if "/gradio_api/file=" in url:
            return _Resp(200, content=audio)
        if url.endswith("/translate/e1"):
            import json as j
            body = j.dumps({"translation": translation, "covered": covered})
            return _Resp(200, text="event: complete\ndata: " + j.dumps([body]))
        if url.endswith("/tts_voice/e1"):
            return _Resp(200, text='event: complete\ndata: [{"path": "/tmp/x.wav"}]')
        return _Resp(200, text='event: complete\ndata: ["{}"]')

    monkeypatch.setattr(tekyerema.httpx, "post", post)
    monkeypatch.setattr(tekyerema.httpx, "get", get)
    return calls


def test_the_space_is_opt_in(monkeypatch):
    """Unset means unset: nothing reaches out, and behaviour is as before."""
    from app.language import pipeline, tekyerema
    monkeypatch.delenv("TEKYEREMA_URL", raising=False)
    assert not tekyerema.configured()
    assert "tekyerema" not in pipeline.translation_routes("dagbani")
    assert "tekyerema" not in pipeline.providers_for("kusaal")
    assert tekyerema.translate("Hello", "dagbani").ok is False


def test_the_space_goes_first_where_it_has_a_model(monkeypatch):
    from app.language import pipeline
    monkeypatch.setenv("TEKYEREMA_URL", "https://space.test")
    assert pipeline.translation_routes("dagbani") == ["tekyerema", "khaya"]
    assert pipeline.providers_for("kusaal")[0] == "tekyerema"
    # Frafra and Gonja are not in the Space; they behave exactly as before.
    assert pipeline.translation_routes("frafra") == ["khaya"]
    assert "tekyerema" not in pipeline.providers_for("frafra")
    assert pipeline.translation_routes("gonja") == []


def test_translate_reads_the_space_response(monkeypatch):
    from app.language import tekyerema
    calls = _fake_space(monkeypatch)
    out = tekyerema.translate("Do you have any bleeding?", "dagbani")
    assert out.ok and out.text == "Fʋ mɔr ziimnam bee?"
    assert out.provider == "tekyerema"
    assert calls[0][2] == {"data": ["Do you have any bleeding?", "eng", "dag"]}


def test_a_pass_through_is_not_a_translation(monkeypatch):
    """covered:false means the Space returned the text untouched."""
    from app.language import tekyerema
    _fake_space(monkeypatch, covered=False)
    out = tekyerema.translate("Do you have any bleeding?", "dagbani")
    assert out.ok is False and "does not cover" in out.error


def test_speech_is_fetched_from_our_own_host_only(monkeypatch):
    """The host we fetch audio from is configuration, not a response field."""
    from app.language import tekyerema
    calls = _fake_space(monkeypatch)
    out = tekyerema.synthesise("Ba ti ka", "kusaal")
    assert out.ok and out.audio.startswith(b"RIFF")
    fetched = [c[1] for c in calls if "/gradio_api/file=" in c[1]]
    assert fetched and all(u.startswith("https://space.test/") for u in fetched)


def test_an_unreachable_space_is_reported_as_unavailable(monkeypatch):
    from app.language import tekyerema
    monkeypatch.setenv("TEKYEREMA_URL", "https://space.test")

    def boom(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(tekyerema.httpx, "post", boom)
    out = tekyerema.translate("Hello there", "kusaal")
    assert out.ok is False
    # The pipeline's "stop asking this route" logic matches on these words.
    assert "unavailable" in out.error.lower() and "reach" in out.error.lower()


def test_khaya_catches_a_line_when_the_space_is_down(db, monkeypatch):
    """The Space failing must not leave a line untranslated if Khaya can do it."""
    from app.language import khaya, pipeline, tekyerema
    from app.language.khaya import LanguageResult
    monkeypatch.setenv("TEKYEREMA_URL", "https://space.test")
    monkeypatch.setattr(tekyerema, "translate", lambda t, l: LanguageResult(
        False, error="Tekyerema is unavailable: could not reach", provider="tekyerema"))
    monkeypatch.setattr(khaya, "translate", lambda t, l: LanguageResult(
        True, text="Fʋ mɔr ziimnam bee, naa?"))
    pipeline.sync_catalogue(db, "dagbani")
    phrase = next(p for p in db.query(pipeline.Phrase).filter(
        pipeline.Phrase.language == "dagbani").all()
        if p.status in ("pending", "failed", "stale"))
    pipeline.translate_pending(db, "dagbani", limit=1)
    db.refresh(phrase)
    assert phrase.status == "translated" and phrase.provider == "khaya"


def test_the_space_is_not_asked_again_once_it_is_known_to_be_down(db, monkeypatch):
    """A hung service would otherwise cost one timeout per line."""
    from app.language import khaya, pipeline, tekyerema
    from app.language.khaya import LanguageResult
    monkeypatch.setenv("TEKYEREMA_URL", "https://space.test")
    asked = []

    def down(text, language):
        asked.append(text)
        return LanguageResult(False, provider="tekyerema",
                              error="Tekyerema is unavailable: could not reach")
    monkeypatch.setattr(tekyerema, "translate", down)
    monkeypatch.setattr(khaya, "translate", lambda t, l: LanguageResult(
        True, text="Fʋ mɔr ziimnam bee, naa? " + t[:8]))
    pipeline.sync_catalogue(db, "dagbani")
    pipeline.translate_pending(db, "dagbani", limit=5)
    assert len(asked) == 1, "asked a known-dead service {} times".format(len(asked))


def test_audio_the_space_made_is_retired_when_the_wording_changes():
    """A model-made clip is replaced; a human recording never is."""
    from app.language import pipeline
    assert "tekyerema_tts" in pipeline.SYNTHESISED_SOURCES
    assert "recorded" not in pipeline.GENERATED_SOURCES


# ------------------------------------------- Twi, Ewe and Hausa as languages


def test_twi_ewe_and_hausa_are_product_languages():
    from app.language import pipeline
    from app import prompts
    for language in ("twi", "ewe", "hausa"):
        assert language in pipeline.ALL_LANGUAGES
        assert language in prompts.LANGUAGES


def test_only_the_space_can_reach_hausa_and_it_is_opt_in(monkeypatch):
    """Khaya has no Hausa model, so without the Space there is no route at all."""
    from app.language import pipeline
    monkeypatch.delenv("TEKYEREMA_URL", raising=False)
    assert pipeline.translation_routes("hausa") == []
    monkeypatch.setenv("TEKYEREMA_URL", "https://space.test")
    assert pipeline.translation_routes("hausa") == ["tekyerema"]
    assert pipeline.translation_routes("twi") == ["tekyerema", "khaya"]
    assert pipeline.translation_routes("ewe") == ["tekyerema", "khaya"]


def test_a_language_with_no_route_says_so_instead_of_failing_every_line(db, monkeypatch):
    from app.language import pipeline
    monkeypatch.delenv("TEKYEREMA_URL", raising=False)
    pipeline.sync_catalogue(db, "hausa")
    out = pipeline.translate_pending(db, "hausa", limit=5)
    assert out["translated"] == 0 and out["failed"] == 0
    assert "TEKYEREMA_URL" in out["note"]
    assert pipeline.status(db, "hausa")["can_translate"] is False
    stuck = db.query(pipeline.Phrase).filter(
        pipeline.Phrase.language == "hausa",
        pipeline.Phrase.status == "failed").count()
    assert stuck == 0, "lines were marked failed for a service nobody configured"


def test_a_new_language_is_translated_through_the_space(db, monkeypatch):
    from app.language import pipeline
    _fake_space(monkeypatch, translation="Wo ho te sɛn?")
    pipeline.sync_catalogue(db, "twi")
    out = pipeline.translate_pending(db, "twi", limit=3)
    assert out["translated"] >= 1
    row = db.query(pipeline.Phrase).filter(
        pipeline.Phrase.language == "twi",
        pipeline.Phrase.status == "translated").first()
    assert row.provider == "tekyerema"
    assert pipeline.status(db, "twi")["can_translate"] is True


def test_the_frontend_language_list_cannot_drift_from_the_backend_list():
    """The enrolment, Setup and Voice pickers import this one file."""
    from app import prompts
    from app.language import pipeline
    source = (REPO / "frontend" / "src" / "lib" / "languages.js").read_text(
        encoding="utf-8")
    keys = re.findall(r"key: '([a-z]+)'", source)
    assert sorted(keys) == sorted(prompts.LANGUAGES)
    # Everything but English is a language the Voice workbench manages.
    assert sorted(k for k in keys if k != "english") == sorted(
        pipeline.ALL_LANGUAGES)
