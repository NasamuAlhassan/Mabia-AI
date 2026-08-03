"""The language pipeline's API, and the recorder interface behind it."""
import base64
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..language import khaya, pipeline
from ..models import Phrase, User
from ..security import current_user

router = APIRouter(prefix="/api/language", tags=["language"])


def known_language(language: str) -> str:
    """Reject any language this platform does not speak, before it reaches disk.

    `language` arrives as a free query string and ends up as a path segment
    under audio/, so "../../../../tmp/x" was an authenticated arbitrary
    directory create and file write anywhere the process could reach. It also
    minted eighty catalogue rows per distinct string, so the same parameter was
    an unbounded write into the database.

    A whitelist rather than a sanitiser: the set of languages is four, it is
    known at import time, and there is no reason to accept anything else.
    """
    if language not in pipeline.ALL_LANGUAGES:
        raise HTTPException(422, "Not a language this platform speaks")
    return language


@router.get("/status")
def status(db: Session = Depends(get_db), user: User = Depends(current_user)):
    for language in pipeline.ALL_LANGUAGES:
        pipeline.sync_catalogue(db, language)
    db.commit()
    ok, languages = khaya.supported_languages()
    return {
        "khaya_configured": khaya.configured(),
        "khaya_reachable": ok,
        "khaya_languages": languages,
        "languages": [pipeline.status(db, l) for l in pipeline.ALL_LANGUAGES],
    }


@router.get("/phrases")
def phrases(language: str, db: Session = Depends(get_db),
            user: User = Depends(current_user),
            category: Optional[str] = None, missing_audio: bool = False):
    known_language(language)
    pipeline.sync_catalogue(db, language)
    db.commit()
    query = db.query(Phrase).filter(Phrase.language == language)
    if category:
        query = query.filter(Phrase.category == category)
    if missing_audio:
        query = query.filter(Phrase.audio_path.is_(None))
    rows = sorted(query.all(), key=lambda p: (p.category, p.key))
    return {"language": language, "count": len(rows), "phrases": [{
        "id": p.id, "key": p.key, "category": p.category,
        "english": p.source_text, "translated": p.translated_text,
        "previous": p.previous_text,
        "status": p.status, "error": p.error, "provider": p.provider,
        "audio_url": "/audio/" + p.audio_path if p.audio_path else None,
        "audio_source": p.audio_source, "audio_bytes": p.audio_bytes,
    } for p in rows]}


@router.post("/translate")
def translate(language: str, db: Session = Depends(get_db),
              user: User = Depends(current_user), limit: int = 200):
    known_language(language)
    out = pipeline.translate_pending(db, language, limit=limit)
    db.commit()
    return out


@router.post("/speak")
def speak(language: str, db: Session = Depends(get_db),
          user: User = Depends(current_user), limit: int = 200):
    known_language(language)
    out = pipeline.speak_translated(db, language, limit=limit)
    db.commit()
    return out


class EditIn(BaseModel):
    translated_text: str
    reviewed: bool = True


@router.put("/phrases/{phrase_id}")
def edit(phrase_id: str, body: EditIn, db: Session = Depends(get_db),
         user: User = Depends(current_user)):
    """A speaker correcting the machine. This is the important direction."""
    phrase = db.get(Phrase, phrase_id)
    if not phrase:
        raise HTTPException(404, "No such phrase")
    phrase.translated_text = body.translated_text.strip()
    phrase.provider = "manual"
    phrase.error = None
    if body.reviewed:
        phrase.status = "reviewed"
        phrase.reviewed_by = user.id
        import datetime as dt
        phrase.reviewed_at = dt.datetime.utcnow()
    # A synthesised clip of the old wording is now wrong. A human recording is
    # left alone -- it may already be correct, and it is not ours to delete.
    if phrase.audio_source == "khaya_tts":
        phrase.audio_path = None
        phrase.audio_source = None
    db.commit()
    return {"ok": True, "status": phrase.status}


@router.post("/phrases/{phrase_id}/audio")
async def upload_audio(phrase_id: str, file: UploadFile = File(...),
                       db: Session = Depends(get_db),
                       user: User = Depends(current_user)):
    """A recorded human take. Always wins over anything generated."""
    phrase = db.get(Phrase, phrase_id)
    if not phrase:
        raise HTTPException(404, "No such phrase")
    # Read in chunks and stop at the ceiling, rather than materialising the
    # whole body first and checking afterwards -- a single large POST used to be
    # a straightforward way to exhaust the server's memory.
    limit = 5 * 1024 * 1024
    chunks, total = [], 0
    while True:
        chunk = await file.read(64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise HTTPException(400, "That recording is too large for a prompt.")
        chunks.append(chunk)
    data = b"".join(chunks)

    if len(data) < 512:
        raise HTTPException(400, "That recording is empty or far too short.")
    try:
        pipeline.write_audio(db, phrase, data, source="recorded")
    except ValueError as exc:
        # These reasons are written for the person holding the microphone --
        # "this is webm, which plays in a browser but not on a phone call". An
        # uncaught raise turned all of them into an unexplained 500.
        raise HTTPException(400, str(exc))
    db.commit()
    return {"ok": True, "audio_url": "/audio/" + phrase.audio_path,
            "bytes": phrase.audio_bytes}


@router.delete("/phrases/{phrase_id}/audio")
def clear_audio(phrase_id: str, db: Session = Depends(get_db),
                user: User = Depends(current_user)):
    phrase = db.get(Phrase, phrase_id)
    if not phrase:
        raise HTTPException(404, "No such phrase")
    # The IVR finds clips by looking on disk, not by reading this row, so
    # clearing the row alone left the caller hearing the take that was just
    # rejected. The file is renamed rather than deleted -- it is still a real
    # voice saying real words, and someone may want it back.
    pipeline._retire_audio(phrase)
    phrase.audio_path = None
    phrase.audio_source = None
    phrase.audio_bytes = None
    db.commit()
    return {"ok": True}


@router.get("/recording-pack")
def recording_pack(language: str, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    known_language(language)
    """What a native speaker sits down and reads, in order."""
    pipeline.sync_catalogue(db, language)
    db.commit()
    rows = pipeline.recording_pack(db, language)
    return {"language": language, "count": len(rows), "items": rows}


@router.post("/preview")
def preview(text: str, language: str, db: Session = Depends(get_db),
            user: User = Depends(current_user)):
    known_language(language)
    """Translate an arbitrary line — used to check the pipeline is live."""
    result = khaya.translate(text, language)
    if not result.ok:
        return {"ok": False, "error": result.error}
    problem = khaya.validate(text, result.text, language)
    return {"ok": problem is None, "translated": result.text,
            "warning": problem, "provider": result.provider}
