#!/usr/bin/env python
"""Generate English placeholder clips so the <Play> path can be exercised.

Not committed, and deliberately so. These are macOS `say` output — a
development artifact, not content. They exist to prove that the pipeline ends in
a file that Africa's Talking can actually fetch and play, and to let the call
flow be rehearsed with audio before any real recording exists.

Real Dagbani clips come from one of two places, and neither is this script:
Khaya's speech service when it returns, or a native speaker in front of the
Voice screen.

    python scripts_generate_placeholder_audio.py [limit]
"""
import subprocess
import sys

from app.db import SessionLocal
from app.language import pipeline
from app.models import Phrase


def main(limit: int = 40) -> None:
    db = SessionLocal()
    pipeline.sync_catalogue(db, "english")
    db.commit()
    rows = (db.query(Phrase)
              .filter(Phrase.language == "english", Phrase.audio_path.is_(None))
              .limit(limit).all())
    made = 0
    for phrase in rows:
        try:
            subprocess.run(["say", "-o", "/tmp/mabia.aiff",
                            phrase.source_text[:300]], check=True)
            # 16 kHz mono: telephony is narrowband, so anything more is wasted.
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000",
                            "-c", "1", "/tmp/mabia.aiff", "/tmp/mabia.wav"],
                           check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("`say`/`afconvert` unavailable — macOS only. Skipping.")
            return
        with open("/tmp/mabia.wav", "rb") as handle:
            pipeline.write_audio(db, phrase, handle.read(), source="recorded")
        made += 1
    db.commit()
    print("Generated {} English clips in backend/audio/english/".format(made))
    print(pipeline.status(db, "english"))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
