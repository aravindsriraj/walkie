"""Live Gemini runs (step writing, framing, transcription). Skipped without GEMINI_API_KEY."""

import asyncio
import functools
import operator
import os
import shutil
import subprocess

import pytest
from dotenv import load_dotenv
from PIL import Image, ImageDraw

from app.gemini import transcribe, write_meta, write_steps
from app.models import RecEvent, Rect, Viewport
from app.steps import build_parts, normalize_steps

load_dotenv()
pytestmark = pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="needs GEMINI_API_KEY")


def frame(path, title, button, highlight):
    img = Image.new("RGB", (1280, 800), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 30), title, fill="black", font_size=36)
    d.rectangle((500, 300, 780, 350), outline="gray")
    d.text((510, 312), "Project name", fill="gray", font_size=22)
    d.rectangle((500, 400, 780, 450), fill="#2563eb")
    d.text((560, 412), button, fill="white", font_size=22)
    d.rounded_rectangle(highlight, radius=6, outline="#6D28D9", width=3)
    img.save(path)


def test_gemini_writes_article(tmp_path):
    vp = Viewport(w=1280, h=800)
    events = [
        RecEvent(t=500, kind="click", viewport=vp, url="https://app.test/projects",
                 label="Project name", tag="input", rect=Rect(x=500, y=300, w=280, h=50)),
        RecEvent(t=2500, kind="input", viewport=vp, url="https://app.test/projects",
                 label="Project name", tag="input", value="Q4 Launch", rect=Rect(x=500, y=300, w=280, h=50)),
        RecEvent(t=4000, kind="click", viewport=vp, url="https://app.test/projects",
                 label="Create project", tag="button", rect=Rect(x=500, y=400, w=280, h=50)),
    ]
    frame(tmp_path / "0_full.png", "New project", "Create project", (496, 296, 784, 354))
    frame(tmp_path / "1_full.png", "New project", "Create project", (496, 296, 784, 354))
    frame(tmp_path / "2_full.png", "New project", "Create project", (496, 396, 784, 454))

    async def run():
        draft = await write_steps(build_parts(events, [], tmp_path))
        steps = normalize_steps(draft, events)
        return draft, steps, await write_meta([s.text for s in steps])

    draft, steps, meta = asyncio.run(run())
    print(draft, meta)
    assert draft is not None  # the reply parsed into the schema, no fallback
    assert "Create project" in " ".join(s.text for s in steps)
    assert meta.title.lower().startswith("how to")


@pytest.mark.skipif(not shutil.which("say"), reason="needs macOS `say` to synthesize speech")
def test_transcribe_gives_real_timestamps(tmp_path):
    subprocess.run(["say", "-o", str(tmp_path / "a.aiff"), "Click new project to get started."], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-t", "2", "-i", "anullsrc=r=16000:cl=mono",
                    "-i", str(tmp_path / "a.aiff"), "-filter_complex", "[0][1]concat=n=2:v=0:a=1",
                    "-ac", "1", "-ar", "16000", str(tmp_path / "a.mp3")], check=True)  # 2 s of silence first
    segs = asyncio.run(transcribe((tmp_path / "a.mp3").read_bytes()))
    assert "new project" in " ".join(s.text for s in segs).lower()
    assert 1700 <= segs[0].start_ms <= 2600


def test_speak_returns_a_wav_clip():
    import io
    import wave

    from app.gemini import speak
    data = asyncio.run(speak("Click Save.", "Achird", "a calm, friendly product-tour narrator"))
    assert data[:4] == b"RIFF"
    with wave.open(io.BytesIO(data)) as w:
        assert w.getframerate() == 24000 and w.getnchannels() == 1 and w.getnframes() / 24000 > 0.3


def test_translate_keeps_ids_and_glossary_words():
    from app.gemini import translate
    from app.models import TDoc, TItem
    doc = TDoc(title="How to create a project", intro="Create a project in Acmeflow.", outro="Done.", steps=[
        TItem(id="s1", text="Click **New project**.", narration="Click New project in Acmeflow."),
        TItem(id="s2", text="Type a name and click **Create**.", narration="Give it a name, then click Create.")])
    out = asyncio.run(translate(doc, "es", ["Acmeflow"]))
    print(out)
    assert [s.id for s in out.steps] == ["s1", "s2"]
    assert "Acmeflow" in out.intro and "**New project**" in out.steps[0].text
    assert out.title != doc.title


def test_write_narration_from_steps(tmp_path):
    from app.gemini import write_narration
    from app.models import Step
    from app.steps import narration_parts
    vp = Viewport(w=1280, h=800)
    events = [RecEvent(t=500, kind="click", viewport=vp, label="Project name"),
              RecEvent(t=4000, kind="click", viewport=vp, label="Create project")]
    frame(tmp_path / "0_full.png", "New project", "Create project", (496, 296, 784, 354))
    frame(tmp_path / "1_full.png", "New project", "Create project", (496, 396, 784, 454))
    steps = [Step(id="a", event_ids=[0], text="Click **Project name** and type a name.", frame=0),
             Step(id="b", event_ids=[1], text="Click **Create project**.", frame=1)]
    n = asyncio.run(write_narration(narration_parts(steps, events, [], tmp_path)))
    print(n)
    assert n.lang == "en" and len(n.scenes) == 2
    assert all(s.narration and "**" not in s.narration for s in n.scenes)


def test_video_and_translation_end_to_end(tmp_path, monkeypatch):
    """Synthetic 3-click recording → real narration, voices, render, sync check; then German. Prints timings."""
    import json
    import time

    from app import store, translate, video
    from app.models import Article, Step

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    store.init(tmp_path / "t.db")
    d = tmp_path / "a1"
    (d / "frames").mkdir(parents=True)
    vp = Viewport(w=1280, h=800)
    shots = [("New project", "Create project", (496, 296, 784, 354)), ("New project", "Create project", (496, 396, 784, 454)),
             ("Project created", "Open project", (496, 396, 784, 454))]
    for i, (title, button, hl) in enumerate(shots):
        frame(d / "frames" / f"{i}_full.png", title, button, hl)
        frame(tmp_path / f"s{i}.png", title, button, (0, 0, 0, 0))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *functools.reduce(operator.iadd, (["-loop", "1", "-t", "2", "-i", str(tmp_path / f"s{i}.png")]
                                                                for i in range(3)), []),
                    "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0,fps=30,format=yuv420p", str(d / "video.mp4")], check=True)
    events = [RecEvent(t=t, kind="click", viewport=vp, label=label, rect=Rect(x=500, y=y, w=280, h=50))
              for t, label, y in ((900, "Project name", 300), (2900, "Create project", 400), (4900, "Open project", 400))]
    (d / "events.json").write_text(json.dumps([e.model_dump() for e in events]))
    (d / "narration.json").write_text("[]")
    store.save(Article(id="a1", status="ready", created_at="t", title="How to create a project", steps=[
        Step(id=f"s{i}", event_ids=[i], text=text, frame=i)
        for i, text in enumerate(["Click **Project name** and type a name.", "Click **Create project**.", "Click **Open project**."])]))

    t = time.time()
    asyncio.run(video.make("a1"))
    a = store.get("a1")
    print(f"\nen: {time.time() - t:.0f}s", a.videos["en"], [s.narration for s in a.steps])
    assert a.videos["en"].status == "ready" and all(s.narration for s in a.steps)

    t = time.time()
    asyncio.run(translate.add("a1", "de"))
    a = store.get("a1")
    print(f"de: {time.time() - t:.0f}s", a.videos["de"], [s.narration for s in a.translations["de"].steps.values()])
    assert a.videos["de"].status == "ready" and a.stale == {"de": []}
    assert (d / "video.de.mp4").stat().st_size > 10_000 and "WEBVTT" in (d / "captions.de.vtt").read_text()
