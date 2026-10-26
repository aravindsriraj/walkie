"""Frame-by-frame privacy check of a finished video: every `step` seconds, ask Gemini which person names or usernames
are readable. A stricter check than watching the whole video at once.

    uv run python scripts/scan_names.py <video.mp4> [step_seconds]
"""

import asyncio
import subprocess
import sys

from google import genai
from google.genai import types
from pydantic import BaseModel

from app import media


class Seen(BaseModel):
    readable_names: list[str]


PROMPT = ("List every person name or username (like first.last) that is clearly READABLE in this screenshot. "
          "Blurred or partly hidden text does not count. Group or role names like senior_management do not count.")


def frame(video: str, t: float) -> bytes:
    return subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1", "-f",
                           "image2pipe", "-vcodec", "mjpeg", "-"], capture_output=True, check=True).stdout


async def main(video: str, step: float) -> None:
    seconds = media.video_ms(__import__("pathlib").Path(video)) / 1000
    times = [round(i * step, 2) for i in range(int(seconds / step))]
    gate = asyncio.Semaphore(12)
    async with genai.Client().aio as c:
        async def one(t: float) -> tuple[float, list[str]]:
            async with gate:
                r = await c.models.generate_content(
                    model="gemini-3.8-flash", contents=[types.Part.from_bytes(data=frame(video, t), mime_type="image/jpeg"),
                                                        PROMPT],
                    config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Seen))
                return t, r.parsed.readable_names if r.parsed else []
        hits = [(t, n) for t, n in await asyncio.gather(*(one(t) for t in times)) if n]
    print(f"{len(times)} frames checked ({step} s apart):", hits or "no readable names")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 0.5))
