#!/usr/bin/env python
"""Move every <phrase_key>.mp3 out of Downloads into the audio library.

The Studio names its own downloads with a UUID, so the browser-side generator
renames each blob to the phrase key before saving. This just files them and
records where they came from -- audio_source is "khaya_studio", distinct from
both "khaya_tts" (the API, currently down) and "recorded" (a human voice, which
is never overwritten).
"""
import shutil
import sys
from pathlib import Path

from app.db import SessionLocal
from app.language import pipeline
from app.models import Phrase

DOWNLOADS = Path.home() / "Downloads"
AUDIO = Path(__file__).resolve().parent / "audio"


def main(language: str = "dagbani") -> None:
    db = SessionLocal()
    known = {p.key: p for p in db.query(Phrase).filter(
        Phrase.language == language).all()}
    filed, skipped = [], []

    for source in sorted(DOWNLOADS.glob("*.mp3")):
        key = source.stem
        phrase = known.get(key)
        if phrase is None:
            continue                      # not one of ours; leave it alone
        if phrase.audio_source == "recorded":
            skipped.append(key + " (human recording kept)")
            source.unlink()
            continue

        folder = AUDIO / language
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (key + ".mp3")
        shutil.move(str(source), str(target))
        phrase.audio_path = "{}/{}.mp3".format(language, key)
        phrase.audio_source = "khaya_studio"
        phrase.audio_bytes = target.stat().st_size
        filed.append("{} ({:,} bytes)".format(key, phrase.audio_bytes))

    db.commit()
    for f in filed:
        print("  filed   " + f)
    for s in skipped:
        print("  skipped " + s)
    status = pipeline.status(db, language)
    print("\n{}: {}/{} spoken ({}%)".format(
        language, status["with_audio"], status["total"],
        status["spoken_coverage"]))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "dagbani")
