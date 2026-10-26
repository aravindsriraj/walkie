"""Uploaded screen recordings have no action log, so Gemini rebuilds one; the normal pipeline takes it from there."""

import asyncio
import io
import logging
import re
from pathlib import Path

from PIL import Image

from app import gemini, media
from app.models import Located, RecEvent, Rect, Viewport

log = logging.getLogger(__name__)
SAMPLE_MS = 2000  # between actions, look for personal data this often, so the video stays blurred throughout
NEAR_MS = 500  # frames this close to an action are already covered by the action's own check
AFTER_MS = 800  # also look just after each action, when its new screen has settled
SETTLE_AFTER_CHANGE_MS = 400  # and just after every screen change (page loads, panels open), once it has settled
FOLD_MS = 300  # samples closer than this are one sample
MAX_SAMPLES = 120
SAME_CONTENT = 0.75  # correlation above which a box region still shows the same thing after a screen change
MAX_OUTLINE_SHARE = 0.06  # of the frame: bigger "elements" are clicks on empty space; no outline or zoom
CLOSE_UP = (480, 300)  # px around the pointer for a second look at what it's on
POINTER_SLACK = 12  # px: a pointer this close to a box counts as on it
LOCATE_BATCH = 6  # actions per Gemini request when finding the clicked element; fewer images, better aim
SENSITIVE_BATCH = 8  # frames per Gemini request: with ~80 at once it missed names it finds in small batches

EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
LONG_NUMBER = re.compile(r"\+?\d[\d\s().-]{6,}\d")  # phone, card, account numbers: 8+ chars of digits


def mask_pii(text: str) -> str:
    """Labels and typed values read out of a video end up in step text; never let personal data through."""
    return LONG_NUMBER.sub("•••", EMAIL.sub("•••", text))


def seconds(at: str) -> float | None:
    """'MM:SS.s' (or H:MM:SS, or plain seconds) → seconds; None if it isn't a time."""
    try:
        parts = [float(p) for p in at.strip().split(":")]
    except ValueError:
        return None
    if not parts or len(parts) > 3 or any(p < 0 for p in parts) or any(p >= 60 for p in parts[1:]):
        return None
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


FRAME_BUDGET = 450  # frames Gemini watches per video: keeps a long upload's cost bounded


def analysis_fps(duration_ms: int) -> int:
    """How closely to watch: short videos at up to 5 fps (clicks a second apart need it), long ones down to 1."""
    return max(1, min(5, FRAME_BUDGET * 1000 // max(1, duration_ms)))


def box_to_rect(box: list[int], w: int, h: int) -> Rect | None:
    """Gemini's [ymin, xmin, ymax, xmax] on a 0-1000 scale → pixel rect; None if it isn't a usable box."""
    if len(box) != 4:
        return None
    y0, x0, y1, x1 = (min(max(v, 0), 1000) / 1000 for v in box)
    if x1 <= x0 or y1 <= y0:
        return None
    return Rect(x=x0 * w, y=y0 * h, w=(x1 - x0) * w, h=(y1 - y0) * h)


def _outline(box: list[int], w: int, h: int) -> Rect | None:
    """The clicked element's rect, unless it's too big to point at anything (a click on empty space)."""
    r = box_to_rect(box, w, h)
    return r if r and r.w * r.h <= MAX_OUTLINE_SHARE * w * h else None


def pad(r: Rect, w: int, h: int) -> Rect:
    """Gemini's boxes are estimates and often hug the text too tightly, leaving part of it readable.
    Grow every blur box generously (an extra blur costs nothing; a missed edge leaks data)."""
    dx, dy = max(8, r.w * 0.08), max(8, r.h * 0.5)
    x0, y0 = max(0, r.x - dx), max(0, r.y - dy)
    x1, y1 = min(w, r.x + r.w + dx), min(h, r.y + r.h + dy)
    return Rect(x=x0, y=y0, w=x1 - x0, h=y1 - y0)


async def events_from_video(video: Path, d: Path) -> list[RecEvent]:
    w, h, duration_ms, _ = await asyncio.to_thread(media.probe, video)
    small = d / "analysis.mp4"
    fps = analysis_fps(duration_ms)
    await asyncio.to_thread(media.analysis_copy, video, small, fps)
    found = await gemini.find_actions(small.read_bytes(), fps)
    small.unlink()

    vp = Viewport(w=w, h=h)  # the video is the page: rects are in video pixels
    timed = ((seconds(a.at), a) for a in (found.actions if found else []))
    events = sorted((RecEvent(t=round(s * 1000), kind=a.kind, viewport=vp, label=mask_pii(a.label), value=mask_pii(a.value))
                     for s, a in timed if s is not None and s * 1000 <= duration_ms), key=lambda e: e.t)
    if not events:
        return []

    # Locate each element on the exact frame the screenshot will use, so highlight and blur line up with it.
    # The frame at the action itself: the pointer is on the element then (just before, it may still be on its way).
    frames = [await asyncio.to_thread(media.frame_jpeg, video, min(e.t, max(duration_ms - 50, 0))) for e in events]
    descriptions = [f'{e.kind} on "{e.label}"' for e in events]
    chunks = [range(i, min(i + LOCATE_BATCH, len(events))) for i in range(0, len(events), LOCATE_BATCH)]
    replies = await asyncio.gather(*(gemini.locate([frames[k] for k in c], [descriptions[k] for k in c]) for c in chunks))
    spots = []
    for c, reply in zip(chunks, replies, strict=True):  # keep actions and boxes aligned even if a reply is short
        got = reply.frames if reply else []
        spots += [got[k] if k < len(got) else None for k in range(len(c))]
    spots = list(await asyncio.gather(*(_check_pointer(video, e, spot, w, h) for e, spot in zip(events, spots, strict=False))))
    out = []
    for i, e in enumerate(events):
        spot = spots[i] if i < len(spots) else None
        out.append(e.model_copy(update={
            "label": mask_pii(spot.label.strip()) if spot and spot.label.strip() else e.label,  # what was really clicked
            "rect": _outline(spot.box, w, h) if spot else None,
            "redact": [pad(r, w, h) for b in (spot.sensitive if spot else []) if (r := box_to_rect(b, w, h))],
        }))
    return out


async def _check_pointer(video: Path, e: RecEvent, spot: Located | None, w: int, h: int) -> Located | None:
    """The pointer decides what was clicked. If the box Gemini drew doesn't contain the pointer (it followed a wrongly
    guessed label), find the element again on a close-up around the pointer, where there's only one candidate."""
    if spot is None or len(spot.pointer) != 2:
        return spot
    py, px = spot.pointer[0] / 1000 * h, spot.pointer[1] / 1000 * w
    r = box_to_rect(spot.box, w, h)
    if r and r.x - POINTER_SLACK <= px <= r.x + r.w + POINTER_SLACK and r.y - POINTER_SLACK <= py <= r.y + r.h + POINTER_SLACK:
        return spot
    cw, ch = min(w, CLOSE_UP[0]), min(h, CLOSE_UP[1])
    x0, y0 = round(min(max(px - cw / 2, 0), w - cw)), round(min(max(py - ch / 2, 0), h - ch))
    try:
        frame = Image.open(io.BytesIO(await asyncio.to_thread(media.frame_jpeg, video, e.t, 10_000))).convert("RGB")
        k = frame.width / w
        buf = io.BytesIO()
        frame.crop((x0 * k, y0 * k, (x0 + cw) * k, (y0 + ch) * k)).save(buf, "JPEG", quality=90)
        reply = await gemini.locate([buf.getvalue()], [f"{e.kind} on the element under the mouse pointer"])
    except Exception:
        log.exception("second look around the pointer failed for %s", e.label)
        return spot
    near = reply.frames[0] if reply and reply.frames else None
    if near is None or not (inner := box_to_rect(near.box, cw, ch)):
        return spot
    # back to whole-frame 0-1000 coordinates, so the caller treats it like any other box
    box = [round((y0 + inner.y) / h * 1000), round((x0 + inner.x) / w * 1000),
           round((y0 + inner.y + inner.h) / h * 1000), round((x0 + inner.x + inner.w) / w * 1000)]
    return Located(box=box, label=near.label or spot.label, sensitive=spot.sensitive, pointer=spot.pointer)


async def redact_samples(video: Path, actions: list[RecEvent]) -> list[RecEvent]:
    """`redact` events (where to blur, nothing else) for frames between actions and just after each one, when its
    new screen has settled, so the video stays blurred throughout. Kept in redact.json, apart from the action log.
    Best effort: a failure here leaves the blurring found at each action."""
    w, h, duration_ms, _ = await asyncio.to_thread(media.probe, video)
    vp = Viewport(w=w, h=h)
    changes = await asyncio.to_thread(media.scene_changes, video)
    candidates = sorted(t for t in {*range(0, duration_ms, SAMPLE_MS),
                                    *(e.t + AFTER_MS for e in actions), *(c + SETTLE_AFTER_CHANGE_MS for c in changes)}
                        if t < duration_ms and all(abs(t - e.t) > NEAR_MS for e in actions))
    times: list[int] = []
    for t in candidates:
        if not times or t - times[-1] >= FOLD_MS:
            times.append(t)
    if len(times) > MAX_SAMPLES:  # thin evenly, never just cut off the end of a long video
        times = [times[round(i * (len(times) - 1) / (MAX_SAMPLES - 1))] for i in range(MAX_SAMPLES)]
    if not times:
        return []
    try:
        frames = [await asyncio.to_thread(media.frame_jpeg, video, t) for t in times]
        batches = [frames[i:i + SENSITIVE_BATCH] for i in range(0, len(frames), SENSITIVE_BATCH)]
        found = await asyncio.gather(*(gemini.find_sensitive(b) for b in batches))
    except Exception:
        log.exception("sampling sensitive boxes failed")
        return []
    boxes = []
    for batch, result in zip(batches, found, strict=True):  # keep frames and boxes aligned even if one reply is short
        got = result.frames if result else []
        boxes += [got[k] if k < len(got) else [] for k in range(len(batch))]
    # While the screen doesn't change its layout doesn't either: a box found in any sample of a stable stretch
    # covers the whole stretch, so one missed detection (Gemini sometimes drops one of several names) leaks nothing.
    stretch = [sum(1 for c in changes if c <= t) for t in times]
    union: dict[int, list[list[int]]] = {}
    for k, frame in zip(stretch, boxes, strict=False):
        seen = union.setdefault(k, [])
        seen += [b for b in frame if b not in seen]
    # Across a screen change, a box stays while what's under it is still there: a dialog dims the page behind it
    # and Gemini stops seeing the dimmed name, but it is still readable.
    for i in range(1, len(times)):
        if stretch[i] != stretch[i - 1]:
            here = union.setdefault(stretch[i], [])
            here += [b for b in union[stretch[i - 1]] if b not in here and _same_content(frames[i - 1], frames[i], b)]
    return [RecEvent(t=t, kind="redact", viewport=vp,
                     redact=[pad(r, w, h) for b in union.get(k, []) if (r := box_to_rect(b, w, h))])
            for t, k in zip(times, stretch, strict=False)]


def _same_content(before: bytes, after: bytes, box: list[int]) -> bool:
    """Is the same thing still in this box (same pattern, whatever the brightness)? Pearson correlation of the two
    crops, small and grey, so dimming or a little compression noise doesn't matter but new content does."""
    def pixels(jpeg: bytes) -> list[int]:
        img = Image.open(io.BytesIO(jpeg)).convert("L")
        y0, x0, y1, x1 = (v / 1000 for v in box)
        crop = img.crop((x0 * img.width, y0 * img.height, x1 * img.width, y1 * img.height))
        return list(crop.resize((48, 16)).get_flattened_data())
    a, b = pixels(before), pixels(after)
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    da, db = [v - ma for v in a], [v - mb for v in b]
    sa, sb = sum(v * v for v in da) ** 0.5, sum(v * v for v in db) ** 0.5
    if sa < 1 or sb < 1:  # a blank region: nothing left to hide (or nothing was there)
        return False
    return sum(x * y for x, y in zip(da, db, strict=True)) / (sa * sb) > SAME_CONTENT

