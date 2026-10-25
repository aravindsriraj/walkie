import subprocess

from PIL import Image, ImageStat

from app.media import content_box, crop_box, frame_time, page_to_frame, render_frames
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


def test_content_box_and_page_to_frame_letterbox():
    vp = Viewport(w=1280, h=800)  # 16:10 page inside a 16:9 capture → bars left/right
    assert content_box(3840, 2160, vp) == (192, 0, 3456, 2160)
    assert content_box(2560, 1600, vp) == (0, 0, 2560, 1600)  # same shape: no bars
    r = page_to_frame(Rect(x=100, y=100, w=10, h=10), 3840, 2160, vp)
    assert (round(r.x), round(r.y), round(r.w)) == (462, 270, 27)


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
