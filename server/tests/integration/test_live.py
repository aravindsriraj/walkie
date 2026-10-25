"""Live Gemini runs (step writing, framing, transcription). Skipped without GEMINI_API_KEY."""

import asyncio
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
