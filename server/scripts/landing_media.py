"""Landing page media, from one real Walkie recording of the Acme demo app (e2e/site).

    uv run python scripts/landing_media.py <article_id>

Reads the article from Walkie (WALKIE_URL, default http://localhost:8000) and what was said from its transcript in
WALKIE_DATA (default server/data). Writes web/public/landing/: {lang}.mp4 and {lang}.vtt for en, es, de, fr and ja
(the article needs a ready video in each), and landing.json with what was said, Walkie's script, and "Click Save to
finish." translated into every language Walkie offers.
"""

import asyncio
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

from app import gemini
from app.models import TDoc, TItem

load_dotenv()
LANGS = ["en", "es", "de", "fr", "ja"]
SAMPLE = "Click Save to finish."
OUT = Path(__file__).resolve().parents[2] / "web" / "site" / "public" / "landing"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url) as r:
        return r.read()


async def sample(lang: str) -> str:
    doc = TDoc(title="", intro="", outro="", steps=[TItem(id="s", text=SAMPLE, narration=SAMPLE)])
    out = await gemini.translate(doc, lang, [])
    return out.steps[0].text if out else ""


async def main(article_id: str) -> None:
    api = os.getenv("WALKIE_URL", "http://localhost:8000").rstrip("/")
    data = Path(os.getenv("WALKIE_DATA", Path(__file__).resolve().parents[1] / "data"))
    a = json.loads(fetch(f"{api}/articles/{article_id}"))
    OUT.mkdir(parents=True, exist_ok=True)
    for lang in LANGS:
        raw = OUT / f"{lang}.source.mp4"
        raw.write_bytes(fetch(f"{api}/articles/{article_id}/videos/{lang}.mp4"))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-vf", "scale=1280:-2", "-c:v", "libx264",
                        "-crf", "33", "-preset", "slow", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart",
                        str(OUT / f"{lang}.mp4")], check=True)
        raw.unlink()
        (OUT / f"{lang}.vtt").write_bytes(fetch(f"{api}/articles/{article_id}/videos/{lang}.vtt"))
    said = [s["text"] for s in json.loads((data / article_id / "narration.json").read_text())]
    script = [s["narration"] for s in sorted(a["steps"], key=lambda s: s["event_ids"][0])]  # the video's order
    langs = list(json.loads(fetch(f"{api}/languages")))
    texts = await asyncio.gather(*(sample(code) for code in langs if code != "en"))
    samples = {"en": SAMPLE, **dict(zip([c for c in langs if c != "en"], texts, strict=True))}
    (OUT / "landing.json").write_text(json.dumps({"said": said, "script": script, "samples": samples},
                                                 ensure_ascii=False, indent=1))
    print(f"wrote {OUT}: {len(said)} said, {len(script)} scenes, {len(samples)} samples")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
