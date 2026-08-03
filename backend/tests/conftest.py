"""Shared fixtures, and one guarantee: tests never touch the real recordings.

Three tests wrote into backend/audio/, which is tracked by git and holds the
only Dagbani recordings anyone has made. One of them renamed a committed clip
and renamed it back *only if the test passed*, so any failure after that point
left a real recording missing from the working tree -- and then cascaded, since
every other Dagbani test depends on that file existing. It showed up as
unrelated tests failing under unrelated changes, and as a suite whose result
depended on the order it ran in and on what the last run left behind.

So the whole audio tree is copied into a temporary directory once per session
and everything is pointed at the copy. Tests can write, retire and delete
freely; the repository's recordings are never opened for writing.
"""
import hashlib
import shutil
from pathlib import Path

import pytest

REAL_AUDIO = Path(__file__).resolve().parents[1] / "audio"


@pytest.fixture(scope="session", autouse=True)
def sandboxed_audio(tmp_path_factory):
    sandbox = tmp_path_factory.mktemp("audio")
    if REAL_AUDIO.exists():
        shutil.copytree(REAL_AUDIO, sandbox, dirs_exist_ok=True)

    from app.language import pipeline
    original = pipeline.AUDIO_ROOT
    pipeline.AUDIO_ROOT = sandbox
    try:
        yield sandbox
    finally:
        pipeline.AUDIO_ROOT = original


@pytest.fixture(autouse=True)
def _recordings_are_untouched():
    """Fail loudly if anything ever writes to the tracked audio directory."""
    before = _snapshot()
    yield
    after = _snapshot()
    assert after == before, (
        "a test modified the repository's own recordings: {}".format(
            sorted(set(before) ^ set(after)) or "contents changed"))


def _snapshot():
    """Content hashes, not sizes.

    Comparing sizes caught a rename or a deletion and nothing else: a take
    overwritten by another of the same length, or wiped to silence in place,
    passed cleanly. These are the only recordings anyone has made.
    """
    if not REAL_AUDIO.exists():
        return {}
    return {str(p.relative_to(REAL_AUDIO)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(REAL_AUDIO.rglob("*")) if p.is_file()}


def wav(seconds_of_silence: int = 2000) -> bytes:
    """A real WAV, big enough to get past the size check.

    Several tests built a 44-byte header, which looks_like_audio rejects as
    "too small to be a recording" -- so assertions meant to prove a *later*
    check were satisfied by the size check and never reached the thing they
    were guarding. A fixture has to be valid in every way except the one under
    test.
    """
    body = b"\x00" * seconds_of_silence
    return (b"RIFF" + (36 + len(body)).to_bytes(4, "little") + b"WAVEfmt "
            + (16).to_bytes(4, "little") + (1).to_bytes(2, "little")
            + (1).to_bytes(2, "little") + (8000).to_bytes(4, "little")
            + (16000).to_bytes(4, "little") + (2).to_bytes(2, "little")
            + (16).to_bytes(2, "little")
            + b"data" + len(body).to_bytes(4, "little") + body)
