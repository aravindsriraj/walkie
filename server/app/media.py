import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from app.models import ACTIONABLE, RecEvent, Rect, Viewport

HIGHLIGHT = "#6D28D9"


def _run(args: list[str]) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def transcode(src: Path, dst: Path) -> None:
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-r", "30",
          "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
          "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
          "-c:a", "aac", "-movflags", "+faststart", str(dst)])


def probe(path: Path) -> tuple[int, int, int, bool]:
    info = json.loads(_run(["ffprobe", "-v", "error", "-print_format", "json",
                            "-show_streams", "-show_format", str(path)]))
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
    duration_ms = int(float(info["format"]["duration"]) * 1000)
    return video["width"], video["height"], duration_ms, has_audio


def extract_audio(video: Path, dst: Path) -> None:
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vn",
          "-ac", "1", "-ar", "16000", str(dst)])


def content_box(fw: int, fh: int, vp: Viewport) -> tuple[int, int, int, int]:
    """Where the page sits in an fw x fh capture. The extension records at the page's own shape, but if the
    window is resized mid-recording Chrome scales the page to fit and centres it (letterbox bars)."""
    s = min(fw / vp.w, fh / vp.h)
    w, h = round(vp.w * s), round(vp.h * s)
    return (fw - w) // 2, (fh - h) // 2, w, h


def page_to_frame(r: Rect, fw: int, fh: int, vp: Viewport) -> Rect:
    """Page CSS-px rect → pixel rect in the full capture frame."""
    x, y, w, _ = content_box(fw, fh, vp)
    s = w / vp.w
    return Rect(x=x + r.x * s, y=y + r.y * s, w=r.w * s, h=r.h * s)


def frame_time(ev: RecEvent, duration_ms: int) -> int:
    # Clicks: just before the UI reacts. Inputs: just after, so the typed value shows.
    t = ev.t + 100 if ev.kind == "input" else ev.t - 150
    return max(0, min(t, max(duration_ms - 50, 0)))


def crop_box(rect: Rect, fw: int, fh: int) -> tuple[int, int, int, int]:
    w = max(rect.w * 2.5, fw * 0.4)
    h = w / 1.6
    if h < rect.h * 1.5:
        h = rect.h * 1.5
        w = h * 1.6
    if w > fw:
        w, h = fw, fw / 1.6
    if h > fh:
        h, w = fh, fh * 1.6
    cx, cy = rect.x + rect.w / 2, rect.y + rect.h / 2
    x = min(max(cx - w / 2, 0), fw - w)
    y = min(max(cy - h / 2, 0), fh - h)
    return int(x), int(y), int(w), int(h)


def scale_rect(r: Rect, s: float) -> Rect:
    return Rect(x=r.x * s, y=r.y * s, w=r.w * s, h=r.h * s)


def _grab(video: Path, ms: int, dst: Path) -> None:
    _run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{ms / 1000:.3f}",
          "-i", str(video), "-frames:v", "1", str(dst)])


def render_frames(video: Path, events: list[RecEvent], out_dir: Path) -> None:
    _, _, duration_ms, _ = probe(video)
    frames = out_dir / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    for i, ev in enumerate(events):
        if ev.kind not in ACTIONABLE:
            continue
        raw = frames / f"{i}_raw.png"
        _grab(video, frame_time(ev, duration_ms), raw)
        img = Image.open(raw).convert("RGB")
        x, y, w, h = content_box(img.width, img.height, ev.viewport)
        img = img.crop((x, y, x + w, y + h))  # drop any letterbox bars; the page now fills the image
        s = img.width / ev.viewport.w
        for r in ev.redact:
            box = tuple(int(v) for v in (r.x * s, r.y * s, (r.x + r.w) * s, (r.y + r.h) * s))
            if box[2] > box[0] and box[3] > box[1]:
                img.paste(img.crop(box).filter(ImageFilter.GaussianBlur(12)), box[:2])
        rect = scale_rect(ev.rect, s) if ev.rect else None
        if rect and rect.w > 0 and rect.h > 0:
            pad = 4
            ImageDraw.Draw(img).rounded_rectangle(
                (rect.x - pad, rect.y - pad, rect.x + rect.w + pad, rect.y + rect.h + pad),
                radius=6, outline=HIGHLIGHT, width=3)
        img.save(frames / f"{i}_full.png")
        if rect and rect.w > 0 and rect.h > 0:
            x, y, w, h = crop_box(rect, img.width, img.height)
            img.crop((x, y, x + w, y + h)).save(frames / f"{i}_zoom.png")
        else:
            img.save(frames / f"{i}_zoom.png")
        raw.unlink()
