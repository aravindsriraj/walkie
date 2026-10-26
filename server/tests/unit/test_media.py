import subprocess

from PIL import Image, ImageStat

from app.media import content_box, crop_box, frame_time, render_frames
from app.models import RecEvent, Rect, Viewport

VP = Viewport(w=640, h=400)


def ev(**kw):
    return RecEvent(viewport=VP, **{"t": 1000, "kind": "click", **kw})


def inside(box, fw, fh):
    x, y, w, h = box
    return x >= 0 and y >= 0 and x + w <= fw and y + h <= fh


def test_crop_box_corner_and_edge_stay_inside_with_16_10():
    for r in [Rect(x=0, y=0, w=10, h=10), Rect(x=1900, y=1060, w=20, h=20)]:
        box = crop_box(r, 1920, 1080)
        assert inside(box, 1920, 1080)
        assert abs(box[2] / box[3] - 1.6) < 0.02


def test_crop_box_covers_big_rect():
    _, _, w, h = crop_box(Rect(x=100, y=100, w=900, h=500), 1920, 1080)
    assert w >= 900 and h >= 500


def test_frame_time():
    assert frame_time(ev(kind="click"), 5000) == 850
    assert frame_time(ev(kind="input"), 5000) == 1100
    assert frame_time(ev(t=50), 5000) == 0


def test_render_frames_writes_and_blurs(tmp_path):
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "nullsrc=s=640x400:r=30:d=2,geq=lum='random(1)*255':cb=128:cr=128", "-pix_fmt", "yuv420p",
                    str(video)], check=True)
    redact = Rect(x=0, y=0, w=200, h=100)
    events = [ev(kind="navigate"), ev(rect=Rect(x=300, y=200, w=80, h=30), redact=[redact])]
    render_frames(video, events, tmp_path)
    full = tmp_path / "frames/1_full.png"
    assert full.exists() and (tmp_path / "frames/1_zoom.png").exists()
    assert not (tmp_path / "frames/0_full.png").exists()

    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.85", "-i", str(video),
                    "-frames:v", "1", str(tmp_path / "orig.png")], check=True)
    region = (10, 10, 190, 90)
    var_orig = ImageStat.Stat(Image.open(tmp_path / "orig.png").convert("L").crop(region)).var[0]
    var_blur = ImageStat.Stat(Image.open(full).convert("L").crop(region)).var[0]
    assert var_blur < var_orig * 0.5


def test_content_box_letterbox():
    vp = Viewport(w=1280, h=800)  # 16:10 page inside a 16:9 capture → bars left/right
    assert content_box(3840, 2160, vp) == (192, 0, 3456, 2160)
    assert content_box(2560, 1600, vp) == (0, 0, 2560, 1600)  # same shape: no bars


def test_render_frames_crops_letterbox_and_aligns_highlight(tmp_path):
    video = tmp_path / "lb.mp4"  # 1152x720 page padded to 1280x720 with 64 px black bars each side
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=white:s=1152x720:r=30:d=1,pad=1280:720:64:0:black", "-pix_fmt", "yuv420p",
                    str(video)], check=True)
    events = [RecEvent(t=500, kind="click", viewport=VP, rect=Rect(x=100, y=100, w=50, h=20))]
    render_frames(video, events, tmp_path)
    img = Image.open(tmp_path / "frames/0_full.png").convert("RGB")
    assert img.size == (1152, 720)  # bars removed
    r, g, b = img.getpixel((round(100 * 1.8) - 3, round(100 * 1.8) + 10))  # left edge of the outline
    assert b > 150 and g < 120, (r, g, b)  # purple highlight sits on the element, not 64 px off


# --- Video rendering -------------------------------------------------------------------------------------

import wave  # noqa: E402

import pytest  # noqa: E402
from PIL import ImageChops  # noqa: E402

from app.captions import Cue  # noqa: E402
from app.media import (  # noqa: E402
    OVERLAP_MS,
    blur_windows,
    build_audio,
    burn_captions,
    clean_video,
    concat,
    render_scene,
    video_ms,
)
from app.scenes import FRAME_MS, plan_scene  # noqa: E402
from tests.unit.helpers import wav_bytes  # noqa: E402


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *map(str, args)], check=True)


def frame_at(video, sec, dst):
    ffmpeg("-ss", f"{sec:.3f}", "-i", video, "-frames:v", "1", dst)
    return Image.open(dst).convert("RGB")


@pytest.fixture
def src(tmp_path):
    v = tmp_path / "src.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc=size=640x400:rate=30:duration=6", "-pix_fmt", "yuv420p", v)
    return v


def test_render_scene_matches_the_plan_length(tmp_path, src):
    plan = plan_scene([3000], (1000, 4200), 1000)
    render_scene(src, plan, Rect(x=300, y=180, w=40, h=20), tmp_path / "s.mp4")
    assert abs(video_ms(tmp_path / "s.mp4") - plan.out_ms) <= FRAME_MS


def test_freeze_piece_repeats_one_frame(tmp_path):
    noise = tmp_path / "noise.mp4"  # every frame different, so only a real freeze looks the same twice
    ffmpeg("-f", "lavfi", "-i", "nullsrc=s=640x400:r=30:d=6,geq=lum='random(1)*255':cb=128:cr=128",
           "-pix_fmt", "yuv420p", noise)
    plan = plan_scene([3000], (2500, 4200), 4000)  # 0.5 s of action for a 4 s sentence: a long freeze first
    assert plan.pieces[0].src_ms == plan.pieces[0].src_end_ms
    out = tmp_path / "s.mp4"
    render_scene(noise, plan, None, out)
    freeze_s = plan.pieces[0].out_ms / 1000
    diff = lambda x, y: max(ImageStat.Stat(ImageChops.difference(x, y)).mean)  # noqa: E731
    a, b = frame_at(out, 0.2, tmp_path / "a.png"), frame_at(out, freeze_s - 0.2, tmp_path / "b.png")
    c = frame_at(out, plan.out_ms / 1000 - 0.2, tmp_path / "c.png")  # after the click: playing, not frozen
    assert diff(a, b) < 3 and diff(a, c) > 20


def test_zoom_enlarges_the_clicked_area(tmp_path):
    v = tmp_path / "box.mp4"  # black frame, white 40x20 box at (300, 180)
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=640x400:r=30:d=6",
           "-vf", "drawbox=x=300:y=180:w=40:h=20:color=white:t=fill", "-pix_fmt", "yuv420p", v)
    plan = plan_scene([3000], (1000, 4200), 2000)
    render_scene(v, plan, Rect(x=300, y=180, w=40, h=20), tmp_path / "z.mp4")
    white = lambda img: sum(1 for p in img.get_flattened_data() if p[0] > 200)  # noqa: E731
    before = white(frame_at(v, 3.0, tmp_path / "o.png"))
    at_click = white(frame_at(tmp_path / "z.mp4", plan.clicks_at_ms[0] / 1000, tmp_path / "c.png"))
    assert at_click > before * 2.5  # zoomed ~2x in each direction
    # then back out soon after the click, so the result of the click is seen in full
    late = white(frame_at(tmp_path / "z.mp4", (plan.clicks_at_ms[0] + 1200) / 1000, tmp_path / "late.png"))
    assert late < before * 1.3


def test_clean_video_blurs_inside_the_window_and_highlights_clicks(tmp_path):
    v = tmp_path / "noise.mp4"
    ffmpeg("-f", "lavfi", "-i", "nullsrc=s=640x400:r=30:d=5,geq=lum='random(1)*255':cb=128:cr=128",
           "-pix_fmt", "yuv420p", v)
    box = Rect(x=0, y=0, w=200, h=100)
    events = [ev(t=0, kind="navigate"), ev(t=1000, kind="redact", redact=[box]), ev(t=2500, kind="redact"),
              ev(t=3000, rect=Rect(x=400, y=300, w=80, h=30))]
    out = tmp_path / "clean.mp4"
    clean_video(v, events, out)
    var = lambda img: ImageStat.Stat(img.convert("L").crop((20, 20, 180, 80))).var[0]  # noqa: E731
    assert var(frame_at(out, 1.5, tmp_path / "in.png")) < var(frame_at(out, 0.5, tmp_path / "before.png")) * 0.3
    assert var(frame_at(out, 4.5, tmp_path / "after.png")) > 1000  # ended: one interval past the next sample
    r, g, b = frame_at(out, 3.0, tmp_path / "hl.png").getpixel((400 - 3, 315))  # left edge of the click outline
    assert b > 150 and g < 120, (r, g, b)
    r, g, b = frame_at(out, 3.6, tmp_path / "gone.png").getpixel((400 - 3, 315))  # gone once the page reacts
    assert not (b > 150 and g < 120), (r, g, b)


def test_blur_windows_cover_the_whole_video_and_merge_repeats():
    r1, r2 = Rect(x=0, y=0, w=10, h=10), Rect(x=50, y=50, w=10, h=10)
    evs = [ev(t=1000, redact=[r1]), ev(t=2000, kind="redact", redact=[r1]), ev(t=4000, kind="redact", redact=[r2]),
           ev(t=6000)]
    # Each set of boxes also covers the interval before it and the one after the next sample: one missed
    # detection must not open a gap (on the Atlan video a single miss left a name readable for ~2 s).
    assert blur_windows(evs, 8000) == [(0, 6000 + OVERLAP_MS, r1), (2000, 8000, r2)]
    assert blur_windows([ev(t=500, redact=[r1])], 3000) == [(0, 3000, r1)]
    assert blur_windows([ev(t=500, redact=[r1]), ev(t=2900)], 3000) == [(0, 3000, r1)]  # clamped to the video
    missed = [ev(t=0, redact=[r1]), ev(t=2000, kind="redact"), ev(t=4000, kind="redact", redact=[r1]), ev(t=6000)]
    assert blur_windows(missed, 8000) == [(0, 8000, r1)]  # the miss at 2 s leaves no gap


def test_build_audio_places_clips_at_exact_samples(tmp_path):
    clip = tmp_path / "c.wav"
    clip.write_bytes(wav_bytes(500))
    with wave.open(str(clip), "rb") as w:  # make the clip non-silent so its position is findable
        params, n = w.getparams(), w.getnframes()
    with wave.open(str(clip), "wb") as w:
        w.setparams(params)
        w.writeframes(b"\x10\x27" * n)
    build_audio([(1000, clip), (3000, clip)], 5000, tmp_path / "all.wav")
    with wave.open(str(tmp_path / "all.wav"), "rb") as w:
        rate, data = w.getframerate(), w.readframes(w.getnframes())
        assert w.getnframes() == 5 * rate
    samples = [int.from_bytes(data[i:i + 2], "little", signed=True) for i in range(0, len(data), 2)]
    loud = [i for i, s in enumerate(samples) if s]
    assert loud[0] == rate and loud[-1] == round(3.5 * rate) - 1


def test_concat_muxes_audio_and_failure_keeps_the_old_file(tmp_path, src):
    parts = []
    for n in range(2):
        plan = plan_scene([2000 + n * 1000], (1000 + n * 1000, 3200 + n * 1000), 1000)
        render_scene(src, plan, None, tmp_path / f"p{n}.mp4")
        parts.append(tmp_path / f"p{n}.mp4")
    total = sum(video_ms(p) for p in parts)
    (tmp_path / "a.wav").write_bytes(wav_bytes(total))
    out = tmp_path / "v.mp4"
    concat(parts, tmp_path / "a.wav", out)
    assert abs(video_ms(out) - total) <= FRAME_MS
    streams = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                              str(out)], capture_output=True, text=True, check=True).stdout.split()
    assert sorted(streams) == ["audio", "video"]

    good = tmp_path / "keep.mp4"
    good.write_bytes(b"old")
    with pytest.raises(subprocess.CalledProcessError):
        concat([tmp_path / "missing.mp4"], tmp_path / "a.wav", good)
    assert good.read_bytes() == b"old"


def test_burn_captions_changes_only_the_bottom_during_the_cue(tmp_path, src):
    out = tmp_path / "b.mp4"
    burn_captions(src, [Cue(0, 1000, "Click Save.")], out)
    a0, b0 = frame_at(src, 0.5, tmp_path / "a0.png"), frame_at(out, 0.5, tmp_path / "b0.png")
    assert ImageChops.difference(a0.crop((0, 0, 640, 200)), b0.crop((0, 0, 640, 200))).getbbox() is None or \
        max(ImageStat.Stat(ImageChops.difference(a0.crop((0, 0, 640, 200)), b0.crop((0, 0, 640, 200)))).mean) < 4
    under = (260, 350, 380, 385)  # the middle of the caption box, near the bottom
    assert max(ImageStat.Stat(ImageChops.difference(a0.crop(under), b0.crop(under))).mean) > 40
    a1, b1 = frame_at(src, 1.5, tmp_path / "a1.png"), frame_at(out, 1.5, tmp_path / "b1.png")
    assert max(ImageStat.Stat(ImageChops.difference(a1, b1)).mean) < 4  # cue over: nothing drawn


def test_clean_video_blurs_thin_boxes(tmp_path):
    # Real case: a 33 px tall email line. boxblur's radius is capped by the box size; a fixed radius crashed ffmpeg.
    v = tmp_path / "noise.mp4"
    ffmpeg("-f", "lavfi", "-i", "nullsrc=s=640x400:r=30:d=2,geq=lum='random(1)*255':cb=128:cr=128",
           "-pix_fmt", "yuv420p", v)
    events = [ev(t=0, kind="redact", redact=[Rect(x=100, y=100, w=120, h=30), Rect(x=300, y=300, w=6, h=4)])]
    clean_video(v, events, tmp_path / "clean.mp4")
    var = ImageStat.Stat(frame_at(tmp_path / "clean.mp4", 1.0, tmp_path / "f.png").convert("L")
                         .crop((105, 105, 215, 125))).var[0]
    assert var < 600  # noise variance is ~5000; blurred is far lower


def test_clean_video_failure_leaves_no_file(tmp_path, src, monkeypatch):
    # A failed pass must not leave a half-written clean.mp4: the video job would reuse it forever.
    real_run = __import__("app.media", fromlist=["_run"])._run

    def fail_after_writing(args):
        if args[0] == "ffmpeg":
            open(args[-1], "wb").write(b"partial")
            raise subprocess.CalledProcessError(1, args)
        return real_run(args)

    monkeypatch.setattr("app.media._run", fail_after_writing)
    out = tmp_path / "clean.mp4"
    with pytest.raises(subprocess.CalledProcessError):
        clean_video(src, [ev(t=0)], out)
    assert not out.exists()
