import itertools
import json
import re
import shutil
import subprocess
import wave
from collections.abc import Callable
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


def analysis_copy(video: Path, dst: Path, fps: int = 2) -> None:
    """Small copy for Gemini to watch: ≤1280 px wide, `fps` frames a second, low bitrate, mono audio (narration helps)."""
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vf", f"scale='min(1280,iw)':-2,fps={fps}",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "32", "-c:a", "aac", "-ac", "1", "-b:a", "32k", str(dst)])


def frame_jpeg(video: Path, ms: int, max_w: int = 1280) -> bytes:
    return subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{ms / 1000:.3f}", "-i", str(video), "-frames:v", "1",
                           "-vf", f"scale='min({max_w},iw)':-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                          check=True, capture_output=True).stdout


def scene_changes(video: Path, threshold: float = 0.01) -> list[int]:
    """Times (ms) where the picture changes: a page loads, a panel opens, a list scrolls. Web UIs change only part
    of the frame (a side panel), so the threshold is low; 0.04 missed a panel loading on the Atlan video."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "info", "-i", str(video), "-an", "-vf",
                          f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
                         capture_output=True, text=True, check=True).stderr
    return [round(float(t) * 1000) for t in re.findall(r"pts_time:([\d.]+)", out)]


def to_wav(src: Path, dst: Path) -> None:
    """24 kHz mono 16-bit WAV: what Gemini's voice replication expects."""
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "24000",
          "-sample_fmt", "s16", str(dst)])


def audio_ms(path: Path) -> int:
    info = json.loads(_run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", str(path)]))
    return round(float(info["format"]["duration"]) * 1000)


def extract_audio(video: Path, dst: Path) -> None:
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vn",
          "-ac", "1", "-ar", "16000", str(dst)])


def content_box(fw: int, fh: int, vp: Viewport) -> tuple[int, int, int, int]:
    """Where the page sits in an fw x fh capture. The extension records at the page's own shape, but if the
    window is resized mid-recording Chrome scales the page to fit and centres it (letterbox bars)."""
    s = min(fw / vp.w, fh / vp.h)
    w, h = round(vp.w * s), round(vp.h * s)
    return (fw - w) // 2, (fh - h) // 2, w, h


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


def render_frames(video: Path, events: list[RecEvent], out_dir: Path,
                  on_frame: Callable[[int], None] | None = None) -> None:
    """Writes frames/{i}_full.png and {i}_zoom.png per action; calls on_frame(i) as each one is ready."""
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
        if on_frame:
            on_frame(i)


# --- Video -----------------------------------------------------------------------------------------------
# A video is: one clean pass over the recording (blur + click highlights, on the source timeline), then one
# segment per scene cut from it (retimed per ScenePlan, zoomed), joined, with one voiceover track laid under it.

FPS = 30
CLEAN_MAX = (2560, 1440)  # headroom for zooming in
OUT_MAX = (1920, 1080)
ENCODE = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-tune", "stillimage", "-pix_fmt", "yuv420p"]
ZOOM_EASE_S = 0.4


def _fit(w: int, h: int, box: tuple[int, int]) -> tuple[int, int]:
    s = min(1, box[0] / w, box[1] / h)
    return max(2, round(w * s / 2) * 2), max(2, round(h * s / 2) * 2)


def _graph(dst: Path, graph: str) -> list[str]:
    """Long filter graphs go through a file (command lines have length limits)."""
    path = dst.with_suffix(".filter")
    path.write_text(graph)
    return ["-/filter_complex", str(path)]


def video_ms(path: Path) -> int:
    info = json.loads(_run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-print_format",
                            "json", "-show_entries", "stream=nb_read_packets,r_frame_rate", str(path)]))
    s = info["streams"][0]
    num, den = (int(x) for x in s["r_frame_rate"].split("/"))
    return round(int(s["nb_read_packets"]) * 1000 * den / num)


OVERLAP_MS = 800  # blur boxes outlast their screen a little: pages don't change on the exact frame of a click


def blur_windows(events: list[RecEvent], duration_ms: int) -> list[tuple[int, int, Rect]]:
    """Where to blur, over time. Each event's boxes cover the interval before it and the one after it, so a box
    missed on one sample is still covered by its neighbours (over-blurring costs nothing; a gap leaks data).
    Windows of the same box that touch or overlap are merged."""
    timed = sorted(events, key=lambda e: e.t)
    out: list[tuple[int, int, Rect]] = []
    for i, e in enumerate(timed):
        start = 0 if i <= 1 else timed[i - 1].t
        end = min(duration_ms, timed[i + 2].t + OVERLAP_MS) if i + 2 < len(timed) else duration_ms
        for r in e.redact:
            prev = next((k for k, w in enumerate(out) if w[2] == r and w[1] >= start), None)
            if prev is not None:
                out[prev] = (out[prev][0], max(out[prev][1], end), r)
            elif end > start:
                out.append((start, end, r))
    return sorted(out, key=lambda w: (w[0], w[2].y, w[2].x))


def _blur_masks(windows: list[tuple[int, int, Rect]], duration_ms: int, size: tuple[int, int], s: float,
                work: Path) -> Path:
    """A concat list of mask images (white = blur), one per stretch of time with the same set of boxes."""
    cuts = sorted({0, duration_ms, *(w[0] for w in windows), *(w[1] for w in windows)})
    lines, last = [], None
    for a, b in itertools.pairwise(cuts):
        if b <= a:
            continue
        img = Image.new("L", size, 0)
        draw = ImageDraw.Draw(img)
        for x0, x1, r in windows:
            if x0 <= a < x1:
                draw.rectangle((r.x * s, r.y * s, (r.x + r.w) * s, (r.y + r.h) * s), fill=255)
        last = work / f"{len(lines)}.png"
        img.save(last)
        lines.append(f"file '{last}'\nduration {(b - a) / 1000:.3f}\n")
    lines.append(f"file '{last}'\n")  # the concat demuxer ignores the last entry's duration unless it's repeated
    listing = work / "masks.txt"
    listing.write_text("".join(lines))
    return listing


def clean_video(video: Path, events: list[RecEvent], dst: Path) -> None:
    """The recording with personal data blurred and each click outlined, cropped to the page, no audio.

    Blurring is one blurred copy of the frame shown through a mask that changes only when the set of boxes
    does, so the cost doesn't grow with the number of boxes (a filter chain per box took minutes)."""
    fw, fh, duration_ms, _ = probe(video)
    vp = events[0].viewport
    cx, cy, cw, ch = content_box(fw, fh, vp)
    ow, oh = _fit(cw, ch, CLEAN_MAX)
    s = ow / vp.w
    windows = blur_windows(events, duration_ms)
    boxes = []
    for e in events:
        if e.kind in ACTIONABLE and e.rect and e.rect.w > 0 and e.rect.h > 0:
            r = scale_rect(e.rect, s)
            boxes.append(f"drawbox=x={int(r.x) - 4}:y={int(r.y) - 4}:w={int(r.w) + 8}:h={int(r.h) + 8}:"
                         f"color={HIGHLIGHT.replace('#', '0x')}:t=4:"
                         f"enable='between(t,{(e.t - 600) / 1000:.3f},{(e.t + 400) / 1000:.3f})'")  # gone as the page reacts
    outline = ",".join(boxes) or "null"
    base = f"[0:v]crop={cw}:{ch}:{cx}:{cy},scale={ow}:{oh},setsar=1,fps={FPS}"
    work = dst.with_suffix(".work")
    work.mkdir(exist_ok=True)
    tmp = dst.with_suffix(".part.mp4")  # the video job reuses clean.mp4 if it exists: never leave a broken one
    try:
        inputs = ["-i", str(video)]
        if windows:
            inputs += ["-f", "concat", "-safe", "0", "-i", str(_blur_masks(windows, duration_ms, (ow, oh), s, work))]
            graph = (f"{base},split[main][soft];[soft]boxblur=luma_radius=16:luma_power=2:chroma_radius=8[blur];"
                     f"[1:v]fps={FPS},format=gray,scale={ow}:{oh}[mask];[blur][mask]alphamerge[hidden];"
                     f"[main][hidden]overlay=0:0:eof_action=pass,{outline}[out]")
        else:
            graph = f"{base},{outline}[out]"
        _run(["ffmpeg", "-y", "-loglevel", "error", *inputs, *_graph(dst, graph), "-map", "[out]", "-an",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", str(tmp)])
        tmp.replace(dst)
    finally:
        tmp.unlink(missing_ok=True)
        shutil.rmtree(work, ignore_errors=True)
        dst.with_suffix(".filter").unlink(missing_ok=True)


def _zoom(plan, zoom: Rect, w: int, h: int) -> str:
    """zoompan expressions: ease in to the element just before the first click, then back out just after the last,
    so the viewer sees what to click up close and what it did in full."""
    z = min(2.0, max(1.0, min(w / (3 * zoom.w), h / (3 * zoom.h))))
    end_in = max(ZOOM_EASE_S, plan.clicks_at_ms[0] / 1000 - 0.15)
    a = end_in - ZOOM_EASE_S
    b = max(end_in, min(plan.out_ms / 1000 - ZOOM_EASE_S, plan.clicks_at_ms[-1] / 1000 + 0.5))
    ease = "ld({0})*ld({0})*(3-2*ld({0}))"
    zexpr = (f"st(0,clip((it-{a:.3f})/{ZOOM_EASE_S},0,1));st(1,clip((it-{b:.3f})/{ZOOM_EASE_S},0,1));"
             f"1+{z - 1:.4f}*{ease.format(0)}*(1-{ease.format(1)})")
    cx, cy = zoom.x + zoom.w / 2, zoom.y + zoom.h / 2
    return (f"zoompan=z='{zexpr}':x='clip({cx:.1f}-iw/zoom/2,0,iw-iw/zoom)':"
            f"y='clip({cy:.1f}-ih/zoom/2,0,ih-ih/zoom)':d=1:fps={FPS}")


def render_scene(clean: Path, plan, zoom: Rect | None, dst: Path) -> None:
    """One scene, video only: the plan's pieces (played, sped up or frozen) joined, zoomed, at most 1080p."""
    w, h, duration_ms, _ = probe(clean)
    ow, oh = _fit(w, h, OUT_MAX)
    frames = round(plan.out_ms * FPS / 1000)
    inputs, chains = [], []
    for i, p in enumerate(plan.pieces):
        if p.src_end_ms == p.src_ms:  # freeze: one frame, held
            at = min(p.src_ms, max(0, duration_ms - 100))  # the very last instant may have no frame
            inputs += ["-ss", f"{at / 1000:.3f}", "-t", "0.2", "-i", str(clean)]
            n = max(1, round(p.out_ms * FPS / 1000))  # loop, not tpad: tpad on one frame holds nothing on ffmpeg 7
            chains.append(f"[{i}:v]trim=end_frame=1,loop=loop={n - 1}:size=1:start=0,setpts=N/{FPS}/TB[p{i}]")
        else:
            src = (p.src_end_ms - p.src_ms) / 1000
            inputs += ["-ss", f"{p.src_ms / 1000:.3f}", "-t", f"{src + 0.2:.3f}", "-i", str(clean)]
            chains.append(f"[{i}:v]trim=duration={src:.3f},setpts=(PTS-STARTPTS)*{p.out_ms / 1000 / src:.6f}[p{i}]")
    joined = "".join(f"[p{i}]" for i in range(len(plan.pieces)))
    look = _zoom(plan, zoom, w, h) + f":s={ow}x{oh}" if zoom else f"scale={ow}:{oh}"
    chains.append(f"{joined}concat=n={len(plan.pieces)}:v=1:a=0,fps={FPS},setpts=PTS-STARTPTS,{look},setsar=1,"
                  f"tpad=stop_mode=clone:stop_duration=1[out]")
    try:
        _run(["ffmpeg", "-y", "-loglevel", "error", *inputs, *_graph(dst, ";".join(chains)), "-map", "[out]",
              "-frames:v", str(frames), *ENCODE, "-bf", "0", "-r", str(FPS), str(dst)])  # no B-frames: joins lose none
    finally:
        dst.with_suffix(".filter").unlink(missing_ok=True)


def build_audio(placements: list[tuple[int, Path]], total_ms: int, dst: Path) -> None:
    """The whole voiceover as one WAV: each clip at its exact sample offset, silence elsewhere.
    One track for the whole video keeps sync exact (per-scene AAC segments drift at every join)."""
    rate = params = None
    track = bytearray()
    for start_ms, clip in placements:
        with wave.open(str(clip), "rb") as w:
            if params is None:
                params, rate = w.getparams(), w.getframerate()
            elif (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (rate, params.nchannels, params.sampwidth):
                raise ValueError(f"{clip.name}: unexpected audio format")
            data = w.readframes(w.getnframes())
        at = round(start_ms * rate / 1000) * params.sampwidth * params.nchannels
        if len(track) < at:
            track.extend(b"\0" * (at - len(track)))
        track[at:at + len(data)] = data
    if params is None:  # a silent video
        rate, nch, width = 24000, 1, 2
    else:
        nch, width = params.nchannels, params.sampwidth
    size = round(total_ms * rate / 1000) * nch * width
    track = track[:size] + b"\0" * max(0, size - len(track))
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(nch)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(bytes(track))


def concat(parts: list[Path], audio: Path, dst: Path) -> None:
    """Join scene segments (same encoding, so no re-encode) and lay the voiceover under them.
    Written to a temp file first, so a failure never replaces a good video."""
    listing = dst.with_suffix(".txt")
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    tmp = dst.with_suffix(".tmp.mp4")
    try:
        _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(audio),
              "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-ar", "48000",
              "-shortest", "-movflags", "+faststart", str(tmp)])
        tmp.replace(dst)
    finally:
        listing.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)


def burn_captions(video: Path, cues, dst: Path) -> None:
    """Captions drawn into the picture (images overlaid, so no subtitle library is needed in ffmpeg)."""
    from app.captions import caption_png

    w, h, _, _ = probe(video)
    tmp = dst.parent / f"{dst.stem}_captions"
    tmp.mkdir(exist_ok=True)
    try:
        inputs, chain, last = [], [], "0:v"
        for i, c in enumerate(cues):
            png = tmp / f"{i}.png"
            caption_png(c.text, w).save(png)
            inputs += ["-i", str(png)]
            chain.append(f"[{last}][{i + 1}:v]overlay=0:H-h-{round(h * 0.04)}:"
                         f"enable='between(t,{c.start_ms / 1000:.3f},{c.end_ms / 1000:.3f})'[o{i}]")
            last = f"o{i}"
        graph = ";".join(chain) if chain else "[0:v]null[o]"
        out = f"[{last}]" if chain else "[o]"
        _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), *inputs, *_graph(dst, graph), "-map", out,
              "-map", "0:a?", *ENCODE, "-c:a", "copy", "-movflags", "+faststart", str(dst)])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        dst.with_suffix(".filter").unlink(missing_ok=True)
