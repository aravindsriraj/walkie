"""Measure the upload path against ground truth.

    uv run python scripts/benchmark_uploads.py <extension recording folder> [runs] [--pointer]

An extension recording knows exactly where and when every action happened (from the page itself). This treats its
video as an upload, where Gemini must find the actions and locate them, and scores the result against that truth:
- found: true actions with a predicted action of the same kind within 1.5 s;
- on target: of those, the predicted outline's centre lies on the true element (8 px tolerance).

Tab recordings have no mouse pointer; --pointer draws one gliding to each true click, like a screen recording.

Measured on the demo flow (3 runs each): with a pointer, 27/27 outlines on target; without one, 18-19/21.
"""

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from app import upload
from app.models import ACTIONABLE, RecEvent

NEAR_MS = 1500
TOLERANCE = 8


def score(truth: list[RecEvent], predicted: list[RecEvent]) -> tuple[int, int, list[str]]:
    found = hit = 0
    notes = []
    unused = list(predicted)
    for t in truth:
        match = min((p for p in unused if p.kind == t.kind and abs(p.t - t.t) <= NEAR_MS),
                    key=lambda p: abs(p.t - t.t), default=None)
        if match is None:
            notes.append(f"missed   {t.t / 1000:5.1f}s {t.kind} '{t.label}'")
            continue
        unused.remove(match)
        found += 1
        r, p = t.rect, match.rect
        if p is None:
            notes.append(f"no box   {t.t / 1000:5.1f}s '{t.label}'")
            continue
        cx, cy = p.x + p.w / 2, p.y + p.h / 2
        if r.x - TOLERANCE <= cx <= r.x + r.w + TOLERANCE and r.y - TOLERANCE <= cy <= r.y + r.h + TOLERANCE:
            hit += 1
        else:
            notes.append(f"off      {t.t / 1000:5.1f}s '{t.label}' → outlined '{match.label}' at ({cx:.0f},{cy:.0f}), "
                         f"truth {r.x:.0f},{r.y:.0f} {r.w:.0f}x{r.h:.0f}")
    return found, hit, notes


def with_pointer(src: Path, truth: list[RecEvent], dst: Path) -> None:
    """The video with an arrow pointer that glides to each true click (over 0.5 s, ending 0.1 s before it) and
    rests there until the next one."""
    arrow = dst.with_suffix(".png")
    img = Image.new("RGBA", (24, 36), (0, 0, 0, 0))
    ImageDraw.Draw(img).polygon([(1, 1), (1, 28), (8, 21), (13, 33), (17, 31), (12, 20), (21, 20)],
                                fill="black", outline="white", width=2)
    img.save(arrow)
    points = [(e.t / 1000, e.rect.x + e.rect.w / 2, e.rect.y + e.rect.h / 2) for e in truth]
    ex, ey = f"{points[-1][1]:.1f}", f"{points[-1][2]:.1f}"  # after the last click: rest there
    for i in range(len(points) - 1, -1, -1):  # each click wraps the expression for everything after it
        t, cx, cy = points[i]
        ox, oy = (points[i - 1][1], points[i - 1][2]) if i else (100.0, 100.0)
        a, b = t - 0.6, t - 0.1
        ex = f"if(lt(t,{a:.3f}),{ox:.1f},if(lt(t,{b:.3f}),{ox:.1f}+({cx - ox:.1f})*(t-{a:.3f})/0.5,{ex}))"
        ey = f"if(lt(t,{a:.3f}),{oy:.1f},if(lt(t,{b:.3f}),{oy:.1f}+({cy - oy:.1f})*(t-{a:.3f})/0.5,{ey}))"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-i", str(arrow), "-filter_complex",
                    f"[0][1]overlay=x='{ex}':y='{ey}'", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                    str(dst)], check=True)


async def run(src: Path, truth: list[RecEvent], pointer: bool) -> tuple[int, int, int, list[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        video = Path(tmp) / "video.mp4"
        if pointer:
            with_pointer(src / "video.mp4", truth, video)
        else:
            shutil.copy(src / "video.mp4", video)
        predicted = [e for e in await upload.events_from_video(video, Path(tmp)) if e.kind in ACTIONABLE]
    found, hit, notes = score(truth, predicted)
    return found, hit, len(predicted), notes


async def main(src: Path, runs: int, pointer: bool) -> None:
    truth = [e for e in (RecEvent.model_validate(x) for x in json.loads((src / "events.json").read_text()))
             if e.kind in ACTIONABLE and e.rect]
    results = await asyncio.gather(*(run(src, truth, pointer) for _ in range(runs)))
    for n, (found, hit, predicted, notes) in enumerate(results, 1):
        print(f"run {n}: found {found}/{len(truth)} actions ({predicted} predicted), outline on target {hit}/{found}")
        for note in notes:
            print("   ", note)
    total_found = sum(r[0] for r in results)
    total_hit = sum(r[1] for r in results)
    print(f"overall: found {total_found}/{len(truth) * runs}, on target {total_hit}/{total_found} "
          f"({total_hit / max(1, total_found):.0%})")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    asyncio.run(main(Path(args[0]), int(args[1]) if len(args) > 1 else 3, "--pointer" in sys.argv))
