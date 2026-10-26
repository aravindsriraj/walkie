import asyncio
import json

import pytest
from PIL import Image

from app import pipeline, store
from app.models import Article, ArticleMeta, DraftStep, StepsDraft

VP = {"w": 640, "h": 400, "dpr": 1}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    store.init(tmp_path / "t.db")

    def fake_frames(video, events, d, on_frame=None):
        (d / "frames").mkdir(exist_ok=True)
        for i in range(len(events)):
            Image.new("RGB", (64, 40)).save(d / f"frames/{i}_full.png")
            if on_frame:
                on_frame(i)

    monkeypatch.setattr(pipeline.media, "transcode", lambda s, d: None)
    monkeypatch.setattr(pipeline.media, "render_frames", fake_frames)
    monkeypatch.setattr(pipeline.media, "probe", lambda v: (640, 400, 5000, False))
    made = []

    async def fake_make(article_id):
        made.append(article_id)

    monkeypatch.setattr(pipeline.video, "make", fake_make)

    def make(events):
        (tmp_path / "a1").mkdir()
        (tmp_path / "a1/events.json").write_text(json.dumps(events))
        store.save(Article(id="a1", created_at="2026-01-01"))
        asyncio.run(pipeline.process("a1"))
        return store.get("a1")

    make.made = made
    return make


def click(t):
    return {"t": t, "kind": "click", "viewport": VP, "label": "Go"}


def test_happy_path(setup, monkeypatch):
    meta_input = []

    async def fake_steps(parts):
        return StepsDraft(steps=[DraftStep(event_ids=[0], text="Click **Go**."), DraftStep(event_ids=[99], text="bogus")])

    async def fake_meta(texts):
        meta_input.append(texts)
        return ArticleMeta(title="How to go", intro="i", outro="o")

    monkeypatch.setattr(pipeline.gemini, "write_steps", fake_steps)
    monkeypatch.setattr(pipeline.gemini, "write_meta", fake_meta)
    a = setup([click(1000)])
    assert a.status == "ready" and a.title == "How to go"
    assert [s.text for s in a.steps] == ["Click **Go**."]
    assert meta_input == [["Click **Go**."]]  # framing sees only validated steps


def test_progress_is_reported_while_processing(setup, monkeypatch):
    seen = []
    real_save = store.save

    def spy(a):
        seen.append((a.stage, list(a.frames)))
        real_save(a)

    async def fake_steps(parts):
        return None

    async def fake_meta(texts):
        return ArticleMeta(title="How to go", intro="", outro="")

    monkeypatch.setattr(pipeline.store, "save", spy)
    monkeypatch.setattr(pipeline.gemini, "write_steps", fake_steps)
    monkeypatch.setattr(pipeline.gemini, "write_meta", fake_meta)
    a = setup([click(1000), click(2000)])
    stages = list(dict.fromkeys(s for s, _ in seen[1:]))  # seen[0] is the upload's initial save
    assert stages == ["Preparing the recording", "Capturing screenshots", "Writing the steps",
                      "Writing the title and intro", ""]
    assert ("Capturing screenshots", [0]) in seen and a.frames == [0, 1]  # screenshots arrive one by one
    assert a.stage_total == 2 and a.status == "ready"


def test_unparseable_replies_fall_back(setup, monkeypatch):
    async def none(_):
        return None

    monkeypatch.setattr(pipeline.gemini, "write_steps", none)
    monkeypatch.setattr(pipeline.gemini, "write_meta", none)
    a = setup([click(1000)])
    assert a.status == "ready" and a.title == "Untitled guide"
    assert [s.text for s in a.steps] == ["Click **Go**."]


def test_no_actions_fails(setup):
    a = setup([{"t": 0, "kind": "navigate", "viewport": VP}])
    assert a.status == "failed" and a.error == "No clicks or typing were recorded"


def test_too_many_actions_fails(setup):
    a = setup([click(i) for i in range(121)])
    assert a.status == "failed" and "too long" in a.error


def test_gemini_error_marks_failed(setup, monkeypatch):
    async def boom(parts):
        raise RuntimeError("quota exceeded")
    monkeypatch.setattr(pipeline.gemini, "write_steps", boom)
    a = setup([click(1000)])
    assert a.status == "failed" and a.error == "quota exceeded"


def test_uploaded_video_finds_steps_first(setup, monkeypatch, tmp_path):
    seen = []
    real_save = store.save
    monkeypatch.setattr(pipeline.store, "save", lambda a: (seen.append(a.stage), real_save(a)))

    async def fake_events(video, d):
        from app.models import RecEvent, Viewport
        return [RecEvent(t=1000, kind="click", viewport=Viewport(w=640, h=400), label="Go")]

    async def fake_steps(parts):
        return None

    async def fake_meta(texts):
        return ArticleMeta(title="How to go", intro="", outro="")

    async def fake_samples(video, events):
        from app.models import RecEvent, Rect, Viewport
        return [RecEvent(t=3000, kind="redact", viewport=Viewport(w=640, h=400), redact=[Rect(x=0, y=0, w=9, h=9)])]

    monkeypatch.setattr(pipeline.upload, "events_from_video", fake_events)
    monkeypatch.setattr(pipeline.upload, "redact_samples", fake_samples)
    monkeypatch.setattr(pipeline.gemini, "write_steps", fake_steps)
    monkeypatch.setattr(pipeline.gemini, "write_meta", fake_meta)
    (tmp_path / "u1").mkdir()
    (tmp_path / "u1/upload").write_bytes(b"video")
    store.save(Article(id="u1", source="upload", created_at="2026-01-01"))
    asyncio.run(pipeline.process("u1"))
    a = store.get("u1")
    assert a.status == "ready" and [s.text for s in a.steps] == ["Click **Go**."]
    assert "Finding the steps in your video" in seen
    assert json.loads((tmp_path / "u1/events.json").read_text())[0]["label"] == "Go"  # the rebuilt log is kept
    assert json.loads((tmp_path / "u1/redact.json").read_text())[0]["t"] == 3000  # blurring between actions


def test_uploaded_file_that_isnt_a_video(setup, monkeypatch, tmp_path):
    import subprocess

    def bad(src, dst):
        raise subprocess.CalledProcessError(1, "ffmpeg")

    monkeypatch.setattr(pipeline.media, "transcode", bad)
    (tmp_path / "u2").mkdir()
    (tmp_path / "u2/upload").write_bytes(b"not a video")
    store.save(Article(id="u2", source="upload", created_at="2026-01-01"))
    asyncio.run(pipeline.process("u2"))
    a = store.get("u2")
    assert a.status == "failed" and "isn't a video" in a.error


def test_ready_article_saves_narration_and_starts_the_video(setup, monkeypatch):
    async def fake_steps(parts):
        return None

    async def fake_meta(texts):
        return ArticleMeta(title="How to go", intro="", outro="")

    monkeypatch.setattr(pipeline.gemini, "write_steps", fake_steps)
    monkeypatch.setattr(pipeline.gemini, "write_meta", fake_meta)
    a = setup([click(1000)])
    assert a.status == "ready" and setup.made == ["a1"]
    assert json.loads((store.DATA_DIR / "a1/narration.json").read_text()) == []


def test_failed_article_makes_no_video(setup):
    a = setup([{"t": 0, "kind": "navigate", "viewport": VP}])
    assert a.status == "failed" and setup.made == []
