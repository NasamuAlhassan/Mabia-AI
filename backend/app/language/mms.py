"""Local speech synthesis with Meta's MMS, for languages Khaya cannot reach.

Khaya is the better voice where it has a model, and it is the one to prefer.
But it has a model for three of the four languages this platform speaks, its
synthesis endpoint is currently down, and its free tier is a call-volume quota
measured in weeks. Depending on a single paid service for the one capability the
whole product is named after is a bad bet.

MMS runs on the machine. No credits, no network at generation time, no quota,
and the model weights are downloaded once. It is slower and generally rougher
than Khaya, so it is a fallback rather than a replacement.

Coverage, checked against Hugging Face rather than assumed:

    Kusaal   facebook/mms-tts-kus   available
    Dagaare  facebook/mms-tts-dga   available (not currently a product language)
    Moore    facebook/mms-tts-mos   available (not currently a product language)
    Dagbani  no model
    Frafra   no model (Gurune)
    Gonja    no model

So MMS unblocks Kusaal and nothing else here. Dagbani and Frafra still need
either Khaya's quota to replenish or a human voice, and Gonja was only ever
going to be a human voice. That is a narrower win than it first looks, and it is
stated plainly rather than dressed up.
"""
import io
import os
import wave
from typing import Optional, Tuple

# Which product language maps to which MMS checkpoint. Absent means no model.
MMS_MODEL = {
    "kusaal": "facebook/mms-tts-kus",
}

_CACHE = {}


def available_for(language: str) -> Optional[str]:
    return MMS_MODEL.get(language)


def installed() -> bool:
    """Whether the machine can run this at all, without importing the world."""
    try:
        import importlib.util
        return all(importlib.util.find_spec(m) is not None
                   for m in ("torch", "transformers"))
    except Exception:
        return False


def _load(model_id: str):
    if model_id in _CACHE:
        return _CACHE[model_id]
    from transformers import VitsModel, AutoTokenizer

    model = VitsModel.from_pretrained(model_id)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model.eval()
    _CACHE[model_id] = (model, tokenizer)
    return _CACHE[model_id]


def synthesise(text: str, language: str) -> Tuple[bool, bytes, Optional[str]]:
    """Speak `text`. Returns (ok, wav_bytes, error).

    Emits 16-bit mono WAV at the model's own rate. Telephony is narrowband
    anyway, so nothing is gained by keeping more.
    """
    model_id = available_for(language)
    if model_id is None:
        return False, b"", (
            "No MMS model exists for {}. This language needs Khaya, or a "
            "recorded human voice.".format(language))
    if not installed():
        return False, b"", (
            "torch and transformers are not installed. Run: "
            "pip install torch transformers")

    try:
        import numpy as np
        import torch

        model, tokenizer = _load(model_id)
        inputs = tokenizer(text, return_tensors="pt")
        with torch.no_grad():
            output = model(**inputs).waveform

        samples = output.squeeze().cpu().numpy()
        # Guard against a model that returns silence rather than failing: a
        # clip of nothing played down a phone line is worse than English.
        if samples.size == 0 or float(np.abs(samples).max()) < 1e-4:
            return False, b"", "MMS produced silence for this text."

        samples = np.clip(samples, -1.0, 1.0)
        pcm = (samples * 32767).astype("<i2")

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(int(model.config.sampling_rate))
            handle.writeframes(pcm.tobytes())
        return True, buffer.getvalue(), None

    except Exception as exc:                       # pragma: no cover
        return False, b"", "MMS failed: {}".format(str(exc)[:180])


def describe() -> dict:
    """What this provider can do right now, for the Voice screen to report."""
    return {
        "provider": "mms",
        "installed": installed(),
        "languages": sorted(MMS_MODEL),
        "note": ("Runs on this machine. No credits and no quota, but a model "
                 "exists only for Kusaal among the languages this platform "
                 "speaks."),
    }
