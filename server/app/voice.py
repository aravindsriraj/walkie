"""The video's voice: a few stock Gemini voices, or the user's own (set up once, with a consent recording)."""

import asyncio
import hashlib
import logging
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app import gemini, media, settings, store
from app.captions import speakable

log = logging.getLogger(__name__)

# Chosen by listening to real tutorial lines (scripts/voice_samples.py). The first is the default.
VOICES = {"Achird": "Friendly", "Sulafat": "Warm", "Kore": "Firm", "Aoede": "Breezy", "Charon": "Informative"}
DEFAULT_VOICE = next(iter(VOICES))
MINE = "mine"
STYLE = "a calm, friendly product-tour narrator speaking at a natural, unhurried pace"
KEY_MAX_AGE = timedelta(days=6)  # Gemini's stateless keys expire after 7 days


def _mine_dir() -> Path:
    return store.DATA_DIR / "my_voice"


def my_voice_ready() -> bool:
    return bool(settings.load().my_voice_key)


async def resolve(voice: str) -> str:
    """What to pass to Gemini: a stock voice name, or a fresh key for the user's own voice."""
    if voice != MINE:
        return voice or DEFAULT_VOICE
    s = settings.load()
    if not s.my_voice_key:
        raise LookupError("Set up your voice first.")
    if datetime.now(UTC) - datetime.fromisoformat(s.my_voice_created) >= KEY_MAX_AGE:
        d = _mine_dir()
        key = await gemini.make_voice_key((d / "sample.wav").read_bytes(), (d / "consent.wav").read_bytes())
        s = s.model_copy(update={"my_voice_key": key, "my_voice_created": datetime.now(UTC).isoformat()})
        settings.save(s)
    return s.my_voice_key


def spoken(words: str, say: dict[str, str]) -> str:
    """The words as the voice should say them: each listed word (whole word, any case) swapped for how to say it."""
    if not say:
        return words
    lookup = {w.lower(): s for w, s in say.items()}
    pattern = "|".join(re.escape(w) for w in sorted(say, key=len, reverse=True))  # "Acme CRM" before "CRM"
    return re.sub(rf"(?<!\w)(?:{pattern})(?!\w)", lambda m: lookup[m[0].lower()], words, flags=re.IGNORECASE)


async def clip(d: Path, text: str, voice: str) -> Path:
    """The narration clip for `text`, cached by voice and spoken words, so unchanged scenes are never re-spoken."""
    words = spoken(speakable(text), settings.load().pronunciations)
    if not words:
        raise ValueError("Nothing to say")
    voice = voice or DEFAULT_VOICE
    key = hashlib.sha1(f"{voice}\0{words}".encode()).hexdigest()[:16]
    path = d / "voice" / f"{key}.wav"
    if not path.exists():
        data = await gemini.speak(words, await resolve(voice), STYLE)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(".tmp").write_bytes(data)
        path.with_suffix(".tmp").rename(path)  # never leave a half-written clip in the cache
    return path


async def set_up_my_voice(sample: bytes, consent: bytes) -> None:
    """Both clips as recorded in the browser. Gemini checks the consent statement matches the sample's speaker."""
    d = _mine_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        try:
            for name, data in (("sample", sample), ("consent", consent)):
                (d / f"{name}.upload").write_bytes(data)
                await asyncio.to_thread(media.to_wav, d / f"{name}.upload", d / f"{name}.wav")
                (d / f"{name}.upload").unlink()
        except Exception as e:
            raise ValueError("Couldn't read that recording. Record it again.") from e
        try:
            key = await gemini.make_voice_key((d / "sample.wav").read_bytes(), (d / "consent.wav").read_bytes())
        except Exception as e:
            log.warning("voice setup rejected: %s", e)
            raise ValueError("Gemini couldn't verify the consent recording. Read the statement exactly, in the same "
                             "place as the sample, and try again.") from e
    except ValueError:
        shutil.rmtree(d, ignore_errors=True)
        raise
    settings.save(settings.load().model_copy(update={"my_voice_key": key,
                                                     "my_voice_created": datetime.now(UTC).isoformat()}))


def forget_my_voice() -> None:
    shutil.rmtree(_mine_dir(), ignore_errors=True)
    settings.save(settings.load().model_copy(update={"my_voice_key": "", "my_voice_created": ""}))
