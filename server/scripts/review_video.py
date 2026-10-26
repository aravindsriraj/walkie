"""An independent check of a finished tutorial video before publishing: Gemini watches it with its audio and lists
readable personal data, outlines on the wrong element, and narration out of step with the screen.

    uv run python scripts/review_video.py <video.mp4> [reviews]

It is a second pair of eyes, not proof: check each reported moment yourself.
"""

import asyncio
import sys
from pathlib import Path

from google import genai
from google.genai import types
from pydantic import BaseModel


class Issue(BaseModel):
    at: str
    kind: str
    detail: str


class Review(BaseModel):
    issues: list[Issue]


PROMPT = """You are a strict reviewer of a product tutorial video before it is published. Watch it with its audio.
Report only REAL problems, each with MM:SS.s:
- personal_data: a READABLE person name, username (first.last), email or avatar initials that is not blurred.
- wrong_highlight: the purple outline is on a different element than the one the narrator describes at that moment.
- out_of_sync: the narrator describes an action clearly different from what happens on screen at that moment.
Blurred text is fine. If there is nothing, return an empty list."""


async def review(c, video: bytes) -> list[Issue]:
    r = await c.models.generate_content(model="gemini-3.8-flash", contents=types.Content(role="user", parts=[
        types.Part(inline_data=types.Blob(data=video, mime_type="video/mp4"), video_metadata=types.VideoMetadata(fps=2)),
        types.Part.from_text(text=PROMPT)]),
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Review))
    return r.parsed.issues if r.parsed else []


async def main(path: Path, n: int) -> None:
    video = path.read_bytes()
    async with genai.Client().aio as c:
        for i, issues in enumerate(await asyncio.gather(*(review(c, video) for _ in range(n))), 1):
            print(f"review {i}:", "nothing found" if not issues else "")
            for x in issues:
                print(f"  {x.at} [{x.kind}] {x.detail[:160]}")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 2))
