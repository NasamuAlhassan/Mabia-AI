#!/usr/bin/env python
"""File a clip generated in Khaya Studio into the platform's audio library.

Khaya's TTS *API* endpoint is unavailable, but the Studio produces the same
Dagbani speech and lets you download it. This script is the other half of that
loop: it takes the most recent download and files it under the phrase key it
belongs to, so a browser-driven session ends with audio the IVR can actually
play rather than a folder of UUIDs.

    python ingest_studio_audio.py <language> <phrase_key>
"""
import shutil
import sys
import time
from pathlib import Path

from app.db import SessionLocal
from app.language import pipeline
from app.models import Phrase

DOWNLOADS = Path.home() / "Downloads"
AUDIO = Path(__file__).resolve().parent / "audio"


def newest_download(max_age_seconds: int = 180):
    """The most recent audio file, if it is recent enough to be ours."""
    candidates = [p for p in DOWNLOADS.glob("*.mp3")] + \
                 [p for p in DOWNLOADS.glob("*.wav")]
    if not candidates:
        return None
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    if time.time() - newest.stat().st_mtime > max_age_seconds:
        return None          # stale: a leftover from an earlier session
    return newest


def ingest(language: str, key: str) -> str:
    source = newest_download()
    if source is None:
        return "no recent download found"

    db = SessionLocal()
    phrase = (db.query(Phrase)
                .filter(Phrase.language == language, Phrase.key == key)
                .first())
    if phrase is None:
        return "no phrase {} in {}".format(key, language)
    if phrase.audio_source == "recorded":
        return "skipped: {} already has a human recording".format(key)

    folder = AUDIO / language
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (key + source.suffix)
    shutil.move(str(source), str(target))

    phrase.audio_path = "{}/{}{}".format(language, key, source.suffix)
    phrase.audio_source = "khaya_studio"
    phrase.audio_bytes = target.stat().st_size
    db.commit()
    covered = pipeline.status(db, language)
    return "{} -> {} ({} bytes) · {}/{} spoken".format(
        key, target.name, phrase.audio_bytes,
        covered["with_audio"], covered["total"])


if __name__ == "__main__":
    print(ingest(sys.argv[1], sys.argv[2]))
