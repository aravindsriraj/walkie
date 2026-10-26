"""The video job end to end on a synthetic recording: real ffmpeg, fake Gemini."""

import asyncio
import hashlib
import json
import subprocess

import pytest
from PIL import Image

from app import store, video
from app.models import Article, Narration, SceneLine, Step, Translation, TStep, VideoState
from app.scenes import FRAME_MS
from tests.unit.helpers import wav_bytes

VP = {"w": 640, "h": 400, "dpr": 1}
CLICKS = [1000, 2500, 4000]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    store.init(tmp_path / "t.db")
    d = tmp_path / "a1"
    (d / "frames").mkdir(parents=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x400:rate=30:duration=6",
                    "-pix_fmt", "yuv420p", str(d / "video.mp4")], check=True)
    events = [{"t": t, "kind": "click", "viewport": VP, "label": f"B{i}",
               "rect": {"x": 100 + 50 * i, "y": 100, "w": 40, "h": 20}} for i, t in enumerate(CLICKS)]
    (d / "events.json").write_text(json.dumps(events))
    (d / "narration.json").write_text("[]")
    for i in range(3):
        Image.new("RGB", (64, 40)).save(d / "frames" / f"{i}_full.png")
    # steps saved out of recorded order (the user reordered the article)
    steps = [Step(id="s2", event_ids=[2], text="Click **B2**.", frame=2), Step(id="s0", event_ids=[0], text="Click **B0**.", frame=0),
             Step(id="s1", event_ids=[1], text="Click **B1**.", frame=1)]
    store.save(Article(id="a1", status="ready", created_at="t", steps=steps))

    calls = {"clip": [], "narration": 0}

    async def fake_narration(parts):
        calls["narration"] += 1
        return Narration(lang="en", scenes=[SceneLine(step=n, narration=f"Now press button {n - 1}.") for n in (1, 2, 3)])

    async def fake_clip(dd, text, v):
        calls["clip"].append((text, v))
        p = dd / "voice" / f"{hashlib.sha1(f'{v}{text}'.encode()).hexdigest()[:8]}.wav"
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(wav_bytes(600 + 25 * len(text)))  # longer sentences take longer to say
        return p

    monkeypatch.setattr(video.gemini, "write_narration", fake_narration)
    monkeypatch.setattr(video.voice, "clip", fake_clip)
    return d, calls


def vtt_lines(d, lang="en"):
    return [line for line in (d / f"captions.{lang}.vtt").read_text().splitlines()
            if line and "-->" not in line and line != "WEBVTT"]


def test_make_writes_narration_then_renders_in_recorded_order(env):
    d, _calls = env
    asyncio.run(video.make("a1"))
    a = store.get("a1")
    by_id = {s.id: s.narration for s in a.steps}
    assert by_id == {"s0": "Now press button 0.", "s1": "Now press button 1.", "s2": "Now press button 2."}
    v = a.videos["en"]
    assert (v.status, v.version, v.error, v.updating) == ("ready", 1, "", [])
    assert vtt_lines(d) == ["Now press button 0.", "Now press button 1.", "Now press button 2."]
    out = d / "video.en.mp4"
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(out)],
                             capture_output=True, text=True, check=True).stdout.split()
    assert sorted(streams) == ["audio", "video"]
    cues = json.loads((d / "cues.en.json").read_text())
    assert [c["text"] for c in cues] == vtt_lines(d)


def test_editing_one_narration_rerenders_one_scene(env):
    d, calls = env
    asyncio.run(video.make("a1"))
    before = set((d / "scenes").iterdir())
    store.update("a1", lambda a: a.model_copy(update={"steps": [
        s.model_copy(update={"narration": "Press the middle button now, please."}) if s.id == "s1" else s for s in a.steps]}))
    n = len(calls["clip"])
    asyncio.run(video.render("a1", "en"))
    after = set((d / "scenes").iterdir())
    assert len(after - before) == 1 and store.get("a1").videos["en"].version == 2
    assert "Press the middle button now, please." in [t for t, _ in calls["clip"][n:]]
    assert calls["narration"] == 1  # narration already written: not rewritten


def test_failure_keeps_previous_video(env, monkeypatch):
    d, _ = env
    asyncio.run(video.make("a1"))
    good = (d / "video.en.mp4").read_bytes()

    async def broken(dd, text, v):
        raise RuntimeError("429 quota exceeded {json...}")

    monkeypatch.setattr(video.voice, "clip", broken)
    asyncio.run(video.render("a1", "en"))
    v = store.get("a1").videos["en"]
    assert v.status == "failed" and "Try again" in v.error and "quota" not in v.error and v.version == 1
    assert (d / "video.en.mp4").read_bytes() == good


def test_render_requests_during_a_render_coalesce(env, monkeypatch):
    runs = []
    real = video._render_once

    async def counted(article_id, lang):
        runs.append(lang)
        await asyncio.sleep(0.05)
        await real(article_id, lang)

    monkeypatch.setattr(video, "_render_once", counted)

    async def go():
        first = asyncio.create_task(video.render("a1", "en"))
        await asyncio.sleep(0.01)
        await asyncio.gather(video.render("a1", "en"), video.render("a1", "en"))
        await first

    asyncio.run(go())
    assert runs == ["en", "en"]


def test_empty_narration_scene_has_no_voice(env):
    d, calls = env
    asyncio.run(video.make("a1"))
    store.update("a1", lambda a: a.model_copy(update={"steps": [
        s.model_copy(update={"narration": "   "}) if s.id == "s0" else s for s in a.steps]}))
    calls["clip"].clear()
    asyncio.run(video.render("a1", "en"))
    assert store.get("a1").videos["en"].status == "ready"
    assert all(t.strip() for t, _ in calls["clip"]) and len(calls["clip"]) == 2
    assert vtt_lines(d) == ["Now press button 1.", "Now press button 2."]


def test_translated_video_uses_translation_and_skips_missing_steps(env):
    d, _calls = env
    asyncio.run(video.make("a1"))
    store.update("a1", lambda a: a.model_copy(update={"translations": {"es": Translation(
        title="t", intro="", outro="", steps={"s0": TStep(text="x", narration="Pulsa el botón 0.", src=""),
                                              "s2": TStep(text="x", narration="Pulsa el botón 2.", src="")})}}))
    asyncio.run(video.render("a1", "es"))
    assert store.get("a1").videos["es"].status == "ready"
    assert vtt_lines(d, "es") == ["Pulsa el botón 0.", "Pulsa el botón 2."]  # s1 has no translation: silent


def test_video_length_matches_scene_plans(env):
    d, _ = env
    asyncio.run(video.make("a1"))
    scenes = sorted((d / "scenes").iterdir())
    total = sum(video.media.video_ms(p) for p in scenes)
    assert abs(video.media.video_ms(d / "video.en.mp4") - total) <= FRAME_MS


def test_narration_fallback_when_gemini_fails(env, monkeypatch):
    async def none(parts):
        return None

    monkeypatch.setattr(video.gemini, "write_narration", none)
    asyncio.run(video.make("a1"))
    a = store.get("a1")
    assert {s.id: s.narration for s in a.steps}["s0"] == "Click B0." and a.videos["en"].status == "ready"


def test_unknown_article_or_language_is_ignored(env):
    asyncio.run(video.render("nope", "en"))
    asyncio.run(video.render("a1", "fr"))  # no French translation
    assert "fr" not in store.get("a1").videos


def test_no_steps_fails_with_a_message(env):
    store.update("a1", lambda a: a.model_copy(update={"steps": []}))
    asyncio.run(video.render("a1", "en"))
    v = store.get("a1").videos["en"]
    assert v.status == "failed" and "no steps" in v.error


def test_mark_interrupted_fails_rendering_videos(env):
    store.update("a1", lambda a: a.model_copy(update={"videos": {"en": VideoState(status="rendering", stage="x")}}))
    store.mark_interrupted()
    v = store.get("a1").videos["en"]
    assert v.status == "failed" and "restarted" in v.error




def test_old_upload_gets_blur_samples_before_its_first_video(env, monkeypatch):
    from app.models import RecEvent, Rect, Viewport
    d, _ = env
    store.update("a1", lambda a: a.model_copy(update={"source": "upload"}))
    sample = RecEvent(t=1800, kind="redact", viewport=Viewport(w=640, h=400), redact=[Rect(x=0, y=0, w=50, h=20)])
    asked, cleaned = [], []

    async def fake_samples(video, events):
        asked.append(len(events))
        return [sample]

    real_clean = video.media.clean_video

    def spy_clean(v, events, dst):
        cleaned.append([e.kind for e in events])
        real_clean(v, events, dst)

    monkeypatch.setattr(video.upload, "redact_samples", fake_samples)
    monkeypatch.setattr(video.media, "clean_video", spy_clean)
    asyncio.run(video.make("a1"))
    asyncio.run(video.render("a1", "en"))  # second render: samples already saved
    assert asked == [3] and json.loads((d / "redact.json").read_text())[0]["t"] == 1800
    assert cleaned[0].count("redact") == 1 and store.get("a1").videos["en"].status == "ready"


def test_rebuilt_clean_pass_rerenders_every_scene(env):
    # Real bug: after clean.mp4 was rebuilt with better blurring, cached scenes cut from the old one were reused,
    # so names stayed readable in the video.
    d, _ = env
    asyncio.run(video.make("a1"))
    before = set((d / "scenes").iterdir())
    (d / "clean.mp4").unlink()
    asyncio.run(video.render("a1", "en"))
    after = set((d / "scenes").iterdir())
    assert len(after - before) == 3
