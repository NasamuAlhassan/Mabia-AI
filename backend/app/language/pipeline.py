"""English → translate → validate → speak → store → serve.

The order matters, and so does where the work happens. Translation and speech
are done **ahead of the call and cached on disk**, never inside it: a call has a
two-second budget per keypress, and a translation round trip plus a synthesis
round trip is several seconds on a good connection. A pipeline that ran during
the call would be a demo that works on wifi and fails on a rural GSM line.

So the flow is:

  1. The catalogue produces the English source for every line the system says.
  2. Khaya translates it into Dagbani, Kusaal or Frafra.
  3. Cheap validation rejects the obvious failures — empty, an HTML error page,
     the English echoed back.
  4. Khaya speech synthesises it, if the service is up.
  5. The audio is written to backend/audio/<language>/<key>.wav, which is the
     directory the IVR already reads from and Africa's Talking already fetches.
  6. Anything without audio goes onto the recording list for a human voice.

A recorded human take is never overwritten by a generated one. A speaker who
has read a line is more trustworthy than a model, and re-running the pipeline
must not silently undo an evening in a recording room.
"""
import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Phrase
from . import khaya, mms
from .catalogue import catalogue

AUDIO_ROOT = Path(__file__).resolve().parents[2] / "audio"

# Khaya's synthesis refuses text much beyond this, which is inconvenient and
# also correct: a prompt that cannot be synthesised in one clip is a prompt a
# woman on a poor line was never going to absorb in one breath either. Measured
# against the live service: 100 characters succeeds, 120 returns HTTP 400.
MAX_SPOKEN_CHARS = 100

SPEAKABLE = ["dagbani", "kusaal", "frafra"]     # Khaya has models for these
RECORD_ONLY = ["gonja"]                          # no model; human voice only
ALL_LANGUAGES = SPEAKABLE + RECORD_ONLY


CACHE_FILE = Path(__file__).resolve().parent / "translations.json"


def load_cached(db: Session, language: str) -> int:
    """Seed translations that were already fetched and committed to the repo.

    The free Khaya tier is a call-volume quota measured in weeks, so a demo that
    re-translates on every deploy would be a demo that stops working. The corpus
    is fetched once, committed, and loaded from disk; the API is only called for
    lines that are genuinely new.
    """
    import json
    if not CACHE_FILE.exists():
        return 0
    try:
        cached = json.loads(CACHE_FILE.read_text()).get(language, {})
    except Exception:
        return 0

    loaded = 0
    for phrase in db.query(Phrase).filter(Phrase.language == language).all():
        entry = cached.get(phrase.key)
        if not entry or phrase.translated_text:
            continue

        # Older caches stored a bare string with no record of its source.
        if isinstance(entry, dict):
            text, source = entry.get("t"), entry.get("src")
        else:
            text, source = entry, None
        if not text:
            continue

        phrase.translated_text = text
        phrase.provider = "khaya"
        # A cached translation of English that has since been rewritten is not
        # a current translation. Marked stale rather than presented as good,
        # because the alternative is confidently speaking a sentence that
        # renders wording nobody says any more.
        if source is not None and source != phrase.source_text:
            phrase.status = "stale"
            phrase.previous_text = text
        else:
            phrase.status = "translated"
        loaded += 1
    db.flush()
    return loaded


def adopt_audio_on_disk(db: Session, language: str) -> int:
    """Notice clips that exist on disk but not in this database.

    The audio ships in the repository; the database does not. On a host with an
    ephemeral disk the database is recreated on every deploy, and without this
    the platform would sit on a folder of real Dagbani and Kusaal recordings
    while telling every caller its English fallback -- silently, because nothing
    was actually broken.

    A row already pointing at a human recording is left alone.
    """
    folder = AUDIO_ROOT / language
    if not folder.is_dir():
        return 0

    on_disk = {}
    for path in folder.iterdir():
        if path.suffix.lower() in (".wav", ".mp3"):
            on_disk.setdefault(path.stem, path)

    adopted = 0
    for phrase in db.query(Phrase).filter(Phrase.language == language).all():
        path = on_disk.get(phrase.key)
        if path is None or phrase.audio_path:
            continue
        phrase.audio_path = "{}/{}".format(language, path.name)
        # Where it came from is no longer knowable from the file alone, so it
        # is recorded as what it certainly is: audio that shipped with the build.
        phrase.audio_source = "shipped"
        phrase.audio_bytes = path.stat().st_size
        adopted += 1
    db.flush()
    return adopted


def sync_catalogue(db: Session, language: str) -> int:
    """Make sure every English line has a row for this language."""
    existing = {p.key: p for p in db.query(Phrase).filter(
        Phrase.language == language).all()}
    added = 0
    for row in catalogue():
        phrase = existing.get(row["key"])
        if phrase is None:
            db.add(Phrase(key=row["key"], language=language,
                          category=row["category"], source_text=row["text"],
                          status="unsupported" if language in RECORD_ONLY
                          else "pending"))
            added += 1
        elif phrase.source_text != row["text"]:
            # The English changed, so the translation no longer matches it.
            #
            # The old wording is KEPT rather than deleted. Deleting it assumes a
            # replacement is a request away, and with the quota exhausted it is
            # not -- a translation thrown away here cannot be regenerated for
            # weeks. So it is marked stale: still visible, still playable if
            # someone judges it close enough, and clearly flagged as describing
            # the previous English.
            phrase.previous_text = phrase.translated_text
            phrase.source_text = row["text"]
            phrase.status = "stale"
            if phrase.audio_source in ("khaya_tts", "mms_tts", "shipped"):
                phrase.audio_path = None
                phrase.audio_source = None
    db.flush()
    load_cached(db, language)
    adopt_audio_on_disk(db, language)
    return added


def translate_pending(db: Session, language: str, limit: int = 200) -> Dict:
    """Translate everything still waiting. Safe to re-run."""
    if language in RECORD_ONLY:
        return {"language": language, "translated": 0, "failed": 0,
                "note": khaya.UNSUPPORTED_NOTE}

    sync_catalogue(db, language)
    pending = (db.query(Phrase)
                 .filter(Phrase.language == language,
                         Phrase.status.in_(["pending", "failed", "stale"]))
                 .limit(limit).all())

    translated, failed, errors = 0, 0, []
    for phrase in pending:
        result = khaya.translate(phrase.source_text, language)
        if not result.ok:
            phrase.status = "failed"
            phrase.error = result.error
            failed += 1
            errors.append(result.error)
            # A rate limit or a dead service will fail every remaining phrase
            # identically; stop rather than hammer it.
            if result.error and ("429" in result.error or "reach" in result.error):
                break
            continue

        problem = khaya.validate(phrase.source_text, result.text, language)
        if problem:
            phrase.status = "failed"
            phrase.error = "rejected: " + problem
            failed += 1
            continue

        phrase.translated_text = result.text
        phrase.status = "translated"
        phrase.provider = "khaya"
        phrase.error = None
        translated += 1

    db.flush()
    return {"language": language, "translated": translated, "failed": failed,
            "errors": sorted(set(e for e in errors if e))[:3],
            "remaining": db.query(Phrase).filter(
                Phrase.language == language,
                Phrase.status.in_(["pending", "failed", "stale"])).count()}


def providers_for(language: str) -> List[str]:
    """Which synthesis routes exist for this language, best first.

    Khaya first where it has a model: the voice is better. MMS second because
    it runs here, needs no credits and cannot be rate-limited. A human recording
    always outranks both and is never overwritten.
    """
    routes = []
    if khaya.KHAYA_CODE.get(language):
        routes.append("khaya")
    if mms.available_for(language):
        routes.append("mms")
    return routes


def speak_translated(db: Session, language: str, limit: int = 200) -> Dict:
    """Synthesise audio for translated lines that have none.

    Tries each provider in turn. A quota exhausted at one does not end the job
    if another can still speak the language.
    """
    rows = (db.query(Phrase)
              .filter(Phrase.language == language,
                      Phrase.status.in_(["translated", "reviewed"]),
                      Phrase.audio_path.is_(None))
              .limit(limit).all())

    made, failed, note = 0, 0, None
    routes = providers_for(language)
    if not routes:
        return {"language": language, "generated": 0, "failed": 0,
                "note": "No synthesis model exists for {} at any provider. "
                        "These lines need a recorded human voice.".format(language),
                "needs_recording": needs_recording_count(db, language)}

    blocked = set()
    for phrase in rows:
        if len(phrase.translated_text or "") > MAX_SPOKEN_CHARS:
            failed += 1
            phrase.error = ("Too long to synthesise ({} characters). Shorten "
                            "the English and re-translate.".format(
                                len(phrase.translated_text)))
            continue

        for route in routes:
            if route in blocked:
                continue
            if route == "khaya":
                result = khaya.synthesise(phrase.translated_text, language)
                ok, audio, error = result.ok, result.audio, result.error
            else:
                ok, audio, error = mms.synthesise(phrase.translated_text, language)

            if ok:
                made += 1
                write_audio(db, phrase, audio, source=route + "_tts")
                break
            note = error
            # A quota or an outage applies to every remaining line, not just
            # this one. Stop asking that provider and try the next route.
            if error and ("quota" in error.lower() or "429" in error
                          or "unavailable" in error.lower()):
                blocked.add(route)
        else:
            failed += 1
            phrase.error = note

    db.flush()
    return {"language": language, "generated": made, "failed": failed,
            "note": note, "routes": routes,
            "blocked": sorted(blocked),
            "needs_recording": needs_recording_count(db, language)}


def write_audio(db: Session, phrase: Phrase, data: bytes,
                source: str = "recorded") -> Phrase:
    """Put audio on disk where the IVR and Africa's Talking already look."""
    folder = AUDIO_ROOT / phrase.language
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (phrase.key + ".wav")
    path.write_bytes(data)
    phrase.audio_path = "{}/{}.wav".format(phrase.language, phrase.key)
    phrase.audio_source = source
    phrase.audio_bytes = len(data)
    phrase.updated_at = dt.datetime.utcnow()
    db.flush()
    return phrase


def too_long_to_speak(db: Session, language: str):
    """Lines that cannot be synthesised as one clip, and should be shortened.

    Reported rather than silently failed: each one is a prompt to rewrite, not a
    bug to work around.
    """
    rows = (db.query(Phrase)
              .filter(Phrase.language == language,
                      Phrase.translated_text.isnot(None)).all())
    return [{"key": p.key, "chars": len(p.translated_text),
             "category": p.category}
            for p in rows if len(p.translated_text) > MAX_SPOKEN_CHARS]


def needs_recording_count(db: Session, language: str) -> int:
    return (db.query(Phrase)
              .filter(Phrase.language == language,
                      Phrase.audio_path.is_(None)).count())


def status(db: Session, language: str) -> Dict:
    rows = db.query(Phrase).filter(Phrase.language == language).all()
    total = len(rows)
    translated = sum(1 for p in rows if p.status in ("translated", "reviewed"))
    stale = sum(1 for p in rows if p.status == "stale")
    reviewed = sum(1 for p in rows if p.status == "reviewed")
    with_audio = sum(1 for p in rows if p.audio_path)
    recorded = sum(1 for p in rows if p.audio_source == "recorded")
    return {
        "language": language,
        "total": total,
        "translated": translated,
        "reviewed": reviewed,
        "stale": stale,
        "with_audio": with_audio,
        "recorded_by_human": recorded,
        "synthesised": with_audio - recorded,
        "needs_recording": total - with_audio,
        "can_translate": language in SPEAKABLE,
        "note": khaya.UNSUPPORTED_NOTE if language in RECORD_ONLY else None,
        # What a caller actually hears today, which is the only number that
        # matters for the claim "we speak her language".
        "spoken_coverage": round(100.0 * with_audio / total, 1) if total else 0.0,
        "too_long": too_long_to_speak(db, language),
        "routes": providers_for(language),
        "mms": mms.describe() if mms.available_for(language) else None,
    }


def recording_pack(db: Session, language: str) -> List[Dict]:
    """The list a native speaker works through, in the order they should record."""
    rows = (db.query(Phrase)
              .filter(Phrase.language == language,
                      Phrase.audio_path.is_(None))
              .all())
    priority = {"script": 0, "diet": 1, "food": 2}
    rows.sort(key=lambda p: (priority.get(p.category, 3), p.key))
    return [{"key": p.key, "category": p.category,
             "english": p.source_text,
             "to_read": p.translated_text or "(needs translation first)",
             "filename": "{}.wav".format(p.key)} for p in rows]
