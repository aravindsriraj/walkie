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

    def fake_frames(video, events, d):
        (d / "frames").mkdir(exist_ok=True)
        for i in range(len(events)):
            Image.new("RGB", (64, 40)).save(d / f"frames/{i}_full.png")

    monkeypatch.setattr(pipeline.media, "transcode", lambda s, d: None)
    monkeypatch.setattr(pipeline.media, "render_frames", fake_frames)
    monkeypatch.setattr(pipeline.media, "probe", lambda v: (640, 400, 5000, False))

    def make(events):
        (tmp_path / "a1").mkdir()
        (tmp_path / "a1/events.json").write_text(json.dumps(events))
        store.save(Article(id="a1", created_at="2026-01-01"))
        asyncio.run(pipeline.process("a1"))
        return store.get("a1")

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
