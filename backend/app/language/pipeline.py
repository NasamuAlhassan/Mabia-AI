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

# Magic numbers for the container formats a telephony provider can actually
# fetch and play. Checked because the alternative is what already happened: a
# 2 kB test fixture of the letter "x" was written to disk, adopted as audio by
# its file extension, counted toward spoken coverage, served in production, and
# played at the end of every Dagbani call -- which is to say, silence, in the
# system whose README promises no call ever ends silently.
AUDIO_MAGIC = (
    b"RIFF",          # WAV
    b"ID3",           # MP3 with an ID3 tag
    b"\xff\xfb", b"\xff\xf3", b"\xff\xf2",   # bare MPEG frame
    b"OggS",          # Ogg
)

# webm/opus is what a browser MediaRecorder produces. It plays in an <audio>
# tag, so a recording made in the workbench looks fine -- and it is not
# something a GSM call can play, which is the only place it matters.
# FLAC sits here rather than above because it is real audio that this system
# cannot serve: _audio_url probes wav, mp3 and ogg only, so a FLAC upload was
# accepted, counted toward spoken coverage, and silently never played.
REJECTED_MAGIC = {b"\x1a\x45\xdf\xa3": "webm or matroska",
                  b"fLaC": "FLAC"}


def looks_like_audio(data: bytes):
    """(ok, reason). Reason is human-facing; it is shown to whoever uploaded."""
    if len(data) < 512:
        return False, "the file is too small to be a recording"
    head = data[:4]
    for magic, name in REJECTED_MAGIC.items():
        if data.startswith(magic):
            return False, ("this is {}, which this system cannot play down a "
                           "phone line. Save it as WAV and upload again".format(name))
    if any(head.startswith(m) for m in AUDIO_MAGIC):
        return True, None
    return False, "this does not look like an audio file"

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
        if path.suffix.lower() not in (".wav", ".mp3"):
            continue
        # An extension is a claim, not evidence. Read the header.
        try:
            ok, _ = looks_like_audio(path.read_bytes()[:1024])
        except OSError:
            continue
        if ok:
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
                # Move the file aside rather than only clearing the row. It used
                # to be cleared and then re-adopted from disk by the call three
                # lines below, in the same function, so the invalidation was a
                # no-op and the clip came back relabelled "shipped".
                _retire_audio(phrase)
                phrase.audio_path = None
                phrase.audio_source = None
    db.flush()
    load_cached(db, language)
    adopt_audio_on_disk(db, language)
    return added


def _retire_audio(phrase: Phrase) -> None:
    """Take a clip out of service without destroying it.

    Renamed rather than deleted: the recording is still a real human voice
    saying real words, and with the quota exhausted it cannot be regenerated
    for weeks. It keeps a .retired suffix so adopt_audio_on_disk will not pick
    it up and a person can listen and decide.
    """
    if not phrase.audio_path:
        return
    try:
        current = AUDIO_ROOT / phrase.audio_path
        if current.exists():
            current.rename(current.with_suffix(current.suffix + ".retired"))
    except OSError:
        pass


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

    blocked = {}
    for phrase in rows:
        # The 100-character ceiling was measured against Khaya's live service.
        # It is not MMS's limit -- MMS synthesises 400 characters happily -- so
        # applying it above the route loop refused lines the local model could
        # have spoken today, which is why eight long Kusaal lines were reported
        # unspeakable while a working route sat right there.
        length = len(phrase.translated_text or "")
        usable = [r for r in routes
                  if r not in blocked
                  and not (r == "khaya" and length > MAX_SPOKEN_CHARS)]
        if not usable:
            failed += 1
            # Say every reason, not the first one that happens to match. A line
            # skipped by Khaya for length and by MMS for being uninstalled was
            # reported as an MMS problem, so the operator was never told about
            # the 100-character ceiling that was the actual reason -- and that
            # was exactly the case for the long Kusaal lines.
            reasons = []
            if length > MAX_SPOKEN_CHARS and "khaya" in routes:
                reasons.append(
                    "khaya: too long at {} characters (limit {}) — shorten the "
                    "English and re-translate".format(length, MAX_SPOKEN_CHARS))
            reasons += ["{}: {}".format(r, blocked[r])
                        for r in routes if r in blocked]
            phrase.error = "; ".join(reasons) or "No route available."
            continue

        # Reset per phrase. This used to be module-flow state carried across
        # iterations, so once every route was blocked the last error seen was
        # written onto phrases that had never been sent to any provider.
        last_error = None
        for route in usable:
            if route == "khaya":
                result = khaya.synthesise(phrase.translated_text, language)
                ok, audio, error = result.ok, result.audio, result.error
            else:
                ok, audio, error = mms.synthesise(phrase.translated_text, language)

            if ok:
                try:
                    write_audio(db, phrase, audio, source=route + "_tts")
                except ValueError as exc:
                    # A 200 that is not audio. Khaya's documented failure mode
                    # is an Azure "unavailable" HTML page served with a 200, and
                    # letting that raise out of here used to 500 the endpoint
                    # and roll back the whole batch -- leaving every clip
                    # already written orphaned on disk with no database row,
                    # ready for the next sync to adopt as "shipped".
                    last_error = "{} returned something that is not audio: {}".format(
                        route, exc)
                    blocked[route] = last_error
                    continue
                made += 1
                last_error = None
                # It worked. Leaving the previous failure on the row showed a
                # red error beside a line that now has a voice.
                phrase.error = None
                break

            last_error = error
            # A quota or an outage applies to every remaining line, not just
            # this one. Stop asking that provider and try the next route.
            if error and ("quota" in error.lower() or "429" in error
                          or "unavailable" in error.lower()
                          or "not installed" in error.lower()):
                blocked[route] = error
        else:
            failed += 1
            phrase.error = last_error
        note = last_error or note

    db.flush()
    return {"language": language, "generated": made, "failed": failed,
            "note": note, "routes": routes,
            "blocked": sorted(blocked),
            "blocked_because": dict(blocked),
            "needs_recording": needs_recording_count(db, language)}


def write_audio(db: Session, phrase: Phrase, data: bytes,
                source: str = "recorded") -> Phrase:
    """Put audio on disk where the IVR and Africa's Talking already look."""
    ok, reason = looks_like_audio(data)
    if not ok:
        raise ValueError(reason)

    # The API whitelists the language, but this function is the one that
    # touches the filesystem and it must not depend on its caller having been
    # careful. Both segments are resolved and checked to be inside the audio
    # root, so a language or key carrying "../" cannot write outside it.
    root = AUDIO_ROOT.resolve()
    path = (root / phrase.language / (phrase.key + _extension(data))).resolve()
    if root not in path.parents:
        raise ValueError("That language or key would write outside the audio "
                         "folder, so it was refused.")

    # Retire whatever was here first. Files are named <key>.<ext>, so an mp3
    # take used to land beside the wav it replaced -- and _audio_url probes
    # .wav first, so the superseded recording kept playing. Any extension for
    # this key goes, not just the one the row happens to name.
    for stale in path.parent.glob(phrase.key + ".*"):
        if stale.suffix != ".retired" and stale != path:
            try:
                stale.rename(stale.with_suffix(stale.suffix + ".retired"))
            except OSError:
                pass

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    phrase.audio_path = "{}/{}".format(phrase.language, path.name)
    phrase.audio_source = source
    phrase.audio_bytes = len(data)
    phrase.updated_at = dt.datetime.utcnow()
    db.flush()
    return phrase


def _extension(data: bytes) -> str:
    """Name the file after what it actually is.

    Everything used to be saved as .wav regardless of contents, so an MP3 or an
    Ogg upload was accepted and then served to the telephony provider under a
    name that lied about it -- the precise failure the header check above exists
    to prevent, reintroduced one line later.
    """
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return ".mp3"
    if data[:4] == b"OggS":
        return ".ogg"
    # No .flac: _audio_url probes wav, mp3 and ogg, so a flac was accepted,
    # counted toward spoken coverage, and silently unplayable. Refusing it is
    # honest; pretending to store it was not.
    return ".wav"


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


# Which lines every ordinary outreach call plays, as opposed to lines that
# depend on the month, her gaps, the week she is at, or a flow she may never
# enter. Recording the first set is what makes a call sound like her language;
# recording a food message she will not be offered until July does not.
CORE_CATEGORIES = ("script", "diet")


def status(db: Session, language: str) -> Dict:
    rows = db.query(Phrase).filter(Phrase.language == language).all()
    total = len(rows)
    core = [p for p in rows if p.category in CORE_CATEGORIES]
    core_with_audio = sum(1 for p in core if p.audio_path)
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
        # Two numbers, because one was misleading. spoken_coverage counts every
        # line in the catalogue equally, including thirty-four food messages of
        # which a given call plays exactly one, and eight next-visit intervals
        # of which it plays one. core_coverage is the spine every outreach call
        # walks -- greeting, consent, the five danger signs, the diet block, the
        # closing -- and it is the number behind any claim that we speak her
        # language.
        "spoken_coverage": round(100.0 * with_audio / total, 1) if total else 0.0,
        "core_total": len(core),
        "core_with_audio": core_with_audio,
        "core_coverage": (round(100.0 * core_with_audio / len(core), 1)
                          if core else 0.0),
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
