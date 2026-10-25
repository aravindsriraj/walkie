import asyncio
import json
import logging
from pathlib import Path

from app import media, store
from app.models import RecEvent, Rect, Step

log = logging.getLogger(__name__)
RENDERER = Path(__file__).resolve().parents[2] / "renderer"
SERVER_URL = "http://127.0.0.1:8000"
WINDOW_MS = 1500


def redact_timeline(events: list[RecEvent], vw: int, vh: int, start: int, end: int) -> list[dict]:
    """Each event's sensitive boxes apply from its time until the next event (source-video px)."""
    out = []
    for i, ev in enumerate(events):
        frm = 0 if i == 0 else ev.t
        to = events[i + 1].t if i + 1 < len(events) else end
        if ev.redact and frm < end and to > start:
            rects = [media.page_to_frame(r, vw, vh, ev.viewport).model_dump() for r in ev.redact]
            out.append({"fromMs": frm, "toMs": to, "rects": rects})
    return out


def clip_props(step: Step, events: list[RecEvent], vw: int, vh: int, duration_ms: int, src: str) -> dict:
    ev = events[step.frame]
    rect = media.page_to_frame(ev.rect, vw, vh, ev.viewport) if ev.rect and ev.rect.w > 0 else None
    # Zoom within the page area so a letterboxed (resized) recording never zooms into the black bars.
    cx, cy, cw, ch = media.content_box(vw, vh, ev.viewport)
    zoom = (cx, cy, cw, ch)
    if rect:
        zx, zy, zw, zh = media.crop_box(Rect(x=rect.x - cx, y=rect.y - cy, w=rect.w, h=rect.h), cw, ch)
        zoom = (zx + cx, zy + cy, zw, zh)
    start = max(0, ev.t - WINDOW_MS)
    end = min(duration_ms, ev.t + WINDOW_MS)
    end = max(end, start + 500)
    return {
        "src": src, "startMs": start, "endMs": end, "clickMs": ev.t,
        "redact": redact_timeline(events, vw, vh, start, end),
        "rect": rect.model_dump() if rect else None,
        "zoom": dict(zip(("x", "y", "w", "h"), zoom, strict=True)), "videoW": vw, "videoH": vh,
    }


async def render_clips(article_id: str) -> None:
    a = store.get(article_id)
    d = store.DATA_DIR / article_id
    try:
        events = [RecEvent.model_validate(e) for e in json.loads((d / "events.json").read_text())]
        vw, vh, duration_ms, _ = media.probe(d / "video.mp4")
        src = f"{SERVER_URL}/files/{article_id}/video.mp4"
        (d / "clips").mkdir(exist_ok=True)
        jobs = [{"out": str(d / f"clips/{s.id}.mp4"), "props": clip_props(s, events, vw, vh, duration_ms, src)}
                for s in a.steps]
        (d / "clip_jobs.json").write_text(json.dumps(jobs))
        proc = await asyncio.create_subprocess_exec(
            "node", "render.mjs", str(d / "clip_jobs.json"), cwd=RENDERER,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(out.decode()[-2000:])
        # Re-read: the user may have edited the article while clips rendered.
        a = store.get(article_id)
        steps = [s.model_copy(update={"clip": f"clips/{s.id}.mp4"}) if (d / f"clips/{s.id}.mp4").exists() else s
                 for s in a.steps]
        a = a.model_copy(update={"steps": steps, "clips_status": "ready"})
    except Exception:
        log.exception("clip rendering failed for %s", article_id)
        a = store.get(article_id).model_copy(update={"clips_status": "failed"})
    store.save(a)
