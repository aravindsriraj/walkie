"""How often does each click's outline sit on the element it names? For uploaded videos, where Gemini finds them.

    uv run python scripts/check_highlights.py <article folder>

For every action: crop the unmarked frame around its rect and ask Gemini whether the named element is inside.
"""

import asyncio
import io
import json
import sys
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image, ImageDraw
from pydantic import BaseModel

from app import media
from app.models import ACTIONABLE, RecEvent


class Verdict(BaseModel):
    pointer: str  # where the mouse pointer is, in words
    on_target: bool  # the magenta box is around the element the pointer is on / about to click


PROMPT = ("A frame from a screen recording at the moment of a click. A magenta box was drawn where a tutorial claims "
          "the click happened. Find the mouse pointer (arrow, hand or text cursor). on_target: is the magenta box "
          "around the element the pointer is on, or right next to (about to click)? If no pointer is visible, judge "
          "whether the box is on a plausible target for: {kind} on \"{label}\".")


async def judge(c, img: Image.Image, e: RecEvent) -> Verdict:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    r = await c.models.generate_content(
        model="gemini-3.8-flash",
        contents=[types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"),
                  PROMPT.format(kind=e.kind, label=e.label)],
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Verdict))
    return r.parsed


async def check(d: Path, only: list[int] | None = None) -> list[tuple[RecEvent, Verdict]]:
    events = [RecEvent.model_validate(e) for e in json.loads((d / "events.json").read_text())]
    acts = [e for e in events if e.kind in ACTIONABLE and e.rect]
    if only:
        acts = [min(acts, key=lambda e, t=t: abs(e.t - t)) for t in only]
    frames = []
    for e in acts:
        img = Image.open(io.BytesIO(media.frame_jpeg(d / "video.mp4", e.t, max_w=10_000))).convert("RGB")
        r = e.rect
        ImageDraw.Draw(img).rectangle((r.x - 4, r.y - 4, r.x + r.w + 4, r.y + r.h + 4), outline=(255, 0, 255), width=5)
        frames.append(img.resize((1600, round(img.height * 1600 / img.width))))
    async with genai.Client().aio as c:
        verdicts = await asyncio.gather(*(judge(c, img, e) for img, e in zip(frames, acts, strict=True)))
    return list(zip(acts, verdicts, strict=True))


async def main(d: Path, only: list[int] | None) -> None:
    results = await check(d, only)
    for e, v in results:
        if not v.on_target or only:
            print(f"  {'ok ' if v.on_target else 'OFF'} {e.t / 1000:6.1f}s {e.kind} '{e.label}': pointer {v.pointer[:90]}")
    print(f"outline on the clicked element: {sum(v.on_target for _, v in results)}/{len(results)}")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), [int(t) for t in sys.argv[2:]] or None))
