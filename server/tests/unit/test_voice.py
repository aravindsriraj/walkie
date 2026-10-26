import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app import settings, store, voice
from tests.unit.helpers import wav_bytes


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return tmp_path


def test_clip_is_cached_by_voice_and_text(tmp_path, monkeypatch):
    calls = []

    async def fake_speak(text, v, style):
        calls.append((text, v))
        return wav_bytes(500)

    monkeypatch.setattr(voice.gemini, "speak", fake_speak)
    a = asyncio.run(voice.clip(tmp_path, "Click **Save**.", ""))
    b = asyncio.run(voice.clip(tmp_path, "Click **Save**.", ""))
    c = asyncio.run(voice.clip(tmp_path, "Click **Save**.", "Sulafat"))
    assert a == b != c and a.exists() and c.exists()
    assert calls == [("Click Save.", voice.DEFAULT_VOICE), ("Click Save.", "Sulafat")]
    with pytest.raises(ValueError):
        asyncio.run(voice.clip(tmp_path, "  ", ""))


def test_mine_without_setup_raises():
    with pytest.raises(LookupError, match="Set up your voice"):
        asyncio.run(voice.resolve("mine"))
    assert asyncio.run(voice.resolve("")) == voice.DEFAULT_VOICE
    assert asyncio.run(voice.resolve("Kore")) == "Kore"


def test_my_voice_key_is_refreshed_when_old(data, monkeypatch):
    keys = iter(["voicekey_1", "voicekey_2"])
    made = []

    async def fake_key(sample, consent):
        made.append((sample[:4], consent[:4]))
        return next(keys)

    monkeypatch.setattr(voice.gemini, "make_voice_key", fake_key)
    monkeypatch.setattr(voice.media, "to_wav", lambda src, dst: dst.write_bytes(wav_bytes(100)))
    asyncio.run(voice.set_up_my_voice(b"webm-sample", b"webm-consent"))
    assert voice.my_voice_ready() and made == [(b"RIFF", b"RIFF")]
    assert asyncio.run(voice.resolve("mine")) == "voicekey_1" and len(made) == 1

    s = settings.load()
    settings.save(s.model_copy(update={"my_voice_created": (datetime.now(UTC) - timedelta(days=6)).isoformat()}))
    assert asyncio.run(voice.resolve("mine")) == "voicekey_2" and len(made) == 2

    voice.forget_my_voice()
    assert not voice.my_voice_ready() and not (data / "my_voice").exists()
    with pytest.raises(LookupError):
        asyncio.run(voice.resolve("mine"))


def test_rejected_consent_saves_nothing(data, monkeypatch):
    async def reject(sample, consent):
        raise RuntimeError("400 consent verification failed")

    monkeypatch.setattr(voice.gemini, "make_voice_key", reject)
    monkeypatch.setattr(voice.media, "to_wav", lambda src, dst: dst.write_bytes(wav_bytes(100)))
    with pytest.raises(ValueError, match="couldn't verify the consent"):
        asyncio.run(voice.set_up_my_voice(b"a", b"b"))
    assert not voice.my_voice_ready() and not (data / "my_voice").exists()


def test_settings_round_trip(data):
    assert settings.load().glossary == []
    settings.save(settings.Settings(glossary=["Acmeflow"]))
    assert settings.load().glossary == ["Acmeflow"]
