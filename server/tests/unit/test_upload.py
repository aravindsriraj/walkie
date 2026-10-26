import asyncio
import io
import subprocess

import pytest
from PIL import Image

from app import upload
from app.media import scene_changes as real_scene_changes
from app.models import FoundAction, FoundActions, Located, LocatedFrames, RecEvent, Rect, SensitiveFrames, Viewport
from app.upload import _same_content as real_same_content
from app.upload import box_to_rect, mask_pii, pad, seconds


@pytest.fixture(autouse=True)
def no_screen_changes(monkeypatch):
    """The synthetic test pattern moves constantly; tests about other sampling rules see no screen changes."""
    monkeypatch.setattr(upload.media, "scene_changes", lambda video: [])
    monkeypatch.setattr(upload, "_same_content", lambda before, after, box: False)  # content-matching tested on its own


def test_box_to_rect_converts_and_rejects_bad_boxes():
    r = box_to_rect([100, 200, 300, 500], 1000, 500)  # ymin, xmin, ymax, xmax on 0-1000
    assert (r.x, r.y, r.w, r.h) == pytest.approx((200, 50, 300, 100))
    assert box_to_rect([0, 0, 1200, -5], 100, 100) is None  # clamped to an empty box
    assert box_to_rect([1, 2, 3], 100, 100) is None
    assert box_to_rect([500, 500, 400, 600], 100, 100) is None  # upside down


def test_seconds_reads_video_timestamps():
    # The real bug: asked for plain seconds, Gemini wrote 1:03.5 as 103.5, so every step after a minute was mistimed.
    assert seconds("1:03.5") == pytest.approx(63.5)
    assert seconds("01:00.9") == pytest.approx(60.9)
    assert seconds("0:07") == 7
    assert seconds("1:02:03") == 3723
    assert seconds("42.5") == 42.5
    assert seconds("") is None and seconds("soon") is None and seconds("1:75") is None


def test_mask_pii_in_text_read_from_video():
    assert mask_pii("Invite ada@acme.com") == "Invite •••"
    assert mask_pii("Call +1 (415) 555-0132 now") == "Call ••• now"
    assert mask_pii("Card 4242 4242 4242 4242") == "Card •••"
    assert mask_pii("Q4 Launch 2026") == "Q4 Launch 2026"  # short numbers stay


def test_events_from_video(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x400:rate=30:duration=3",
                    "-pix_fmt", "yuv420p", str(video)], check=True)

    async def fake_find(_, fps=2):
        return FoundActions(actions=[
            FoundAction(at="0:02", kind="click", label="Save"),
            FoundAction(at="00:00.5", kind="input", label="Email", value="ada@acme.com"),
            FoundAction(at="0:09", kind="click", label="Past the end"),  # beyond the video: dropped
            FoundAction(at="soon", kind="click", label="No time"),  # unreadable time: dropped
        ])

    seen = {}

    async def fake_locate(frames, descriptions):
        seen["frames"], seen["descriptions"] = frames, descriptions
        return LocatedFrames(frames=[Located(box=[100, 100, 200, 300], sensitive=[[0, 0, 100, 500], [9, 9, 1]])])

    monkeypatch.setattr(upload.gemini, "find_actions", fake_find)
    monkeypatch.setattr(upload.gemini, "locate", fake_locate)
    events = asyncio.run(upload.events_from_video(video, tmp_path))

    assert [(e.t, e.kind) for e in events] == [(500, "input"), (2000, "click")]  # sorted by time
    assert events[0].value == "•••"  # typed email masked
    assert seen["descriptions"] == ['input on "Email"', 'click on "Save"'] and all(f[:2] == b"\xff\xd8" for f in seen["frames"])
    assert (events[0].rect.x, events[0].rect.y) == pytest.approx((64, 40))  # 0-1000 → video pixels
    assert len(events[0].redact) == 1  # malformed blur box dropped
    assert events[0].redact[0].w > 320  # and the good one was padded
    assert events[1].rect is None and events[1].redact == []  # Gemini located fewer frames than actions
    assert events[0].viewport.w == 640 and not (tmp_path / "analysis.mp4").exists()


def test_blur_boxes_are_padded_and_clamped():
    # The real case: a 12 px box around ~16 px of email text left the bottom half readable.
    r = pad(Rect(x=460, y=229, w=109, h=12), 1280, 774)
    assert r.y <= 221 and r.y + r.h >= 249  # at least 8 px above and below
    assert r.x <= 452 and r.x + r.w >= 577
    edge = pad(Rect(x=2, y=2, w=10, h=10), 100, 100)
    assert (edge.x, edge.y) == (0, 0)  # never outside the frame


def test_redact_samples_cover_between_and_just_after_actions(tmp_path, monkeypatch):
    # a screen change just before each sample: every sample is its own stretch (no spreading between them)
    monkeypatch.setattr(upload.media, "scene_changes", lambda v: [2400, 3600, 5600, 8400])
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x400:rate=30:duration=10",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    vp = Viewport(w=640, h=400)
    actions = [RecEvent(t=2000, kind="click", viewport=vp), RecEvent(t=8000, kind="click", viewport=vp)]
    sampled = []

    async def fake_sensitive(frames):
        sampled.append(len(frames))
        return SensitiveFrames(frames=[[[100, 100, 150, 400]], [], [], [[500, 500, 550, 900]], []])

    monkeypatch.setattr(upload.gemini, "find_sensitive", fake_sensitive)
    samples = asyncio.run(upload.redact_samples(video, actions))
    # every 2 s, plus 0.8 s after each action (when its new screen has settled); never on an action itself
    assert [e.t for e in samples] == [0, 2800, 4000, 6000, 8800] and sampled == [5]
    assert all(e.kind == "redact" for e in samples)
    assert samples[1].redact == []  # nothing to blur on that frame: it ends the earlier blur
    assert samples[0].redact[0].w > 192  # padded like every other blur box


def test_redact_samples_failure_is_not_fatal(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x400:rate=30:duration=6",
                    "-pix_fmt", "yuv420p", str(video)], check=True)

    async def broken(frames):
        raise RuntimeError("quota")

    monkeypatch.setattr(upload.gemini, "find_sensitive", broken)
    actions = [RecEvent(t=1000, kind="click", viewport=Viewport(w=640, h=400))]
    assert asyncio.run(upload.redact_samples(video, actions)) == []


def test_redact_samples_are_checked_in_small_batches_in_order(tmp_path, monkeypatch):
    # One request with ~80 frames missed a username on the Atlan video; small batches keep attention per frame.
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x400:rate=30:duration=10",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    monkeypatch.setattr(upload, "SENSITIVE_BATCH", 2)
    monkeypatch.setattr(upload.media, "scene_changes", lambda v: [1600, 3600, 5600, 7600])  # one stretch per sample
    sizes = []

    async def fake_sensitive(frames):
        sizes.append(len(frames))
        n = sum(sizes) - len(frames)  # index of this batch's first frame
        return SensitiveFrames(frames=[[[100 * (n + k), 0, 100 * (n + k) + 50, 100]] for k in range(len(frames))])

    monkeypatch.setattr(upload.gemini, "find_sensitive", fake_sensitive)
    samples = asyncio.run(upload.redact_samples(video, []))
    assert sorted(sizes, reverse=True) == [2, 2, 1]
    assert [e.t for e in samples] == [0, 2000, 4000, 6000, 8000]
    assert [round(e.redact[0].y + e.redact[0].h / 2) for e in samples] == [15, 50, 90, 130, 170]  # each frame's own box


def test_locate_runs_in_small_batches(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x400:rate=30:duration=4",
                    "-pix_fmt", "yuv420p", str(video)], check=True)

    async def fake_find(_, fps=2):
        return FoundActions(actions=[FoundAction(at=f"0:0{n}", kind="click", label=f"B{n}") for n in (1, 2, 3)])

    calls = []

    async def fake_locate(frames, descriptions):
        calls.append(descriptions)
        return LocatedFrames(frames=[Located(box=[100, 100 * int(d[-2]), 200, 100 * int(d[-2]) + 50]) for d in descriptions])

    async def no_samples(frames):
        return SensitiveFrames(frames=[[] for _ in frames])

    monkeypatch.setattr(upload, "LOCATE_BATCH", 2)
    monkeypatch.setattr(upload.gemini, "find_actions", fake_find)
    monkeypatch.setattr(upload.gemini, "locate", fake_locate)
    monkeypatch.setattr(upload.gemini, "find_sensitive", no_samples)
    events = asyncio.run(upload.events_from_video(video, tmp_path))
    assert sorted(len(c) for c in calls) == [1, 2]
    assert [round(e.rect.x) for e in events] == [64, 128, 192]  # each action got its own box, in order


def test_locate_corrects_the_label_to_what_was_clicked(tmp_path, monkeypatch):
    # Real case: an action Gemini named "main" was a click on the search field; the outline went to "main"'s
    # neighbour and the narration said the wrong thing. Locating reads the element under the pointer instead.
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x400:rate=30:duration=4",
                    "-pix_fmt", "yuv420p", str(video)], check=True)

    async def fake_find(_, fps=2):
        return FoundActions(actions=[FoundAction(at="0:01", kind="click", label="main"),
                                     FoundAction(at="0:02", kind="click", label="Close")])

    seen = {}

    async def fake_locate(frames, descriptions):
        seen["descriptions"] = descriptions
        return LocatedFrames(frames=[Located(box=[100, 100, 200, 300], label="Search all assets"),
                                     Located(box=[100, 100, 200, 300], label="Invite ada@acme.com")])

    async def no_samples(frames):
        return SensitiveFrames(frames=[[] for _ in frames])

    monkeypatch.setattr(upload.gemini, "find_actions", fake_find)
    monkeypatch.setattr(upload.gemini, "locate", fake_locate)
    monkeypatch.setattr(upload.gemini, "find_sensitive", no_samples)
    events = asyncio.run(upload.events_from_video(video, tmp_path))
    assert [e.label for e in events] == ["Search all assets", "Invite •••"]  # corrected, personal data still masked
    assert seen["descriptions"] == ['click on "main"', 'click on "Close"']


def test_short_videos_are_watched_at_more_frames_per_second():
    # Measured: at 2 fps, clicks ~1 s apart in a 32 s video got times ~1.5 s off and outlines landed on the
    # neighbouring element. Short videos are cheap to watch closely; long ones step down to keep cost bounded.
    assert upload.analysis_fps(32_000) == 5
    assert upload.analysis_fps(143_000) == 3
    assert upload.analysis_fps(600_000) == 1
    assert all(upload.analysis_fps(ms) * ms / 1000 <= 900 for ms in range(1000, 600_001, 1000))  # frame budget


def test_redact_samples_follow_screen_changes(tmp_path, monkeypatch):
    # Real case: a panel finished loading between two 2 s samples and a username was readable until the next one.
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x400:rate=30:duration=6",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    monkeypatch.setattr(upload.media, "scene_changes", lambda v: [3100, 3200])

    async def boxes(frames):
        return SensitiveFrames(frames=[[] for _ in frames])

    monkeypatch.setattr(upload.gemini, "find_sensitive", boxes)
    times = [e.t for e in asyncio.run(upload.redact_samples(video, []))]
    assert 3100 + upload.SETTLE_AFTER_CHANGE_MS in times  # just after the change (near-duplicates folded)
    assert 3200 + upload.SETTLE_AFTER_CHANGE_MS not in times
    assert {0, 2000, 4000} <= set(times)


def test_scene_changes_finds_cuts(tmp_path):
    video = tmp_path / "cut.mp4"  # black for 1 s, then white
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x200:r=30:d=1",
                    "-f", "lavfi", "-i", "color=c=white:s=320x200:r=30:d=1", "-filter_complex", "[0][1]concat=n=2:v=1",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    changes = real_scene_changes(video)  # the real one, not the stub above
    assert len(changes) == 1 and 950 <= changes[0] <= 1050


def test_box_that_misses_the_pointer_is_found_again_around_the_pointer(tmp_path, monkeypatch):
    # Real case: the pointer was on a table row, but the action was guessed as "Data Addressability Score" and that
    # icon got the outline. When the box doesn't contain the pointer, the element under the pointer wins.
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x400:rate=30:duration=4",
                    "-pix_fmt", "yuv420p", str(video)], check=True)

    async def fake_find(_, fps=2):
        return FoundActions(actions=[FoundAction(at="0:01", kind="click", label="Data Addressability Score"),
                                     FoundAction(at="0:02", kind="click", label="Save")])

    calls = []

    async def fake_locate(frames, descriptions):
        calls.append((len(frames), descriptions, Image.open(io.BytesIO(frames[0])).size))
        if len(calls) == 1:  # the whole frames: first box misses its pointer, second contains it
            return LocatedFrames(frames=[
                Located(box=[0, 0, 50, 50], label="Data Addressability Score", pointer=[500, 500]),
                Located(box=[480, 480, 520, 520], label="Save", pointer=[500, 500])])
        return LocatedFrames(frames=[Located(box=[450, 400, 550, 600], label="stg_invoice_lines")])  # in the close-up

    async def no_samples(frames):
        return SensitiveFrames(frames=[[] for _ in frames])

    monkeypatch.setattr(upload.gemini, "find_actions", fake_find)
    monkeypatch.setattr(upload.gemini, "locate", fake_locate)
    monkeypatch.setattr(upload.gemini, "find_sensitive", no_samples)
    events = asyncio.run(upload.events_from_video(video, tmp_path))
    assert len(calls) == 2 and calls[1][1] == ["click on the element under the mouse pointer"]
    assert calls[1][2][0] < 640  # a close-up, not the whole frame
    first, second = events
    assert first.label == "stg_invoice_lines"
    assert first.rect.x <= 320 <= first.rect.x + first.rect.w and first.rect.y <= 200 <= first.rect.y + first.rect.h
    assert second.label == "Save"  # its box contained the pointer: kept, no second look


def test_boxes_found_once_cover_the_whole_stable_stretch(tmp_path, monkeypatch):
    # Real case: two copies of a username on screen; Gemini reported the second in one sample and missed it in the
    # next two, so it was readable between them. While the screen doesn't change, one sighting covers the stretch.
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x400:rate=30:duration=10",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    monkeypatch.setattr(upload.media, "scene_changes", lambda v: [5000])
    a, b = [100, 100, 150, 400], [600, 100, 650, 400]

    async def boxes(frames):  # samples at 0, 2000, 4000, 5400 (after the change), 6000, 8000
        return SensitiveFrames(frames=[[a, b], [a], [a], [b], [], [b]])

    monkeypatch.setattr(upload.gemini, "find_sensitive", boxes)
    samples = asyncio.run(upload.redact_samples(video, []))
    assert [e.t for e in samples] == [0, 2000, 4000, 5400, 6000, 8000]
    assert [len(e.redact) for e in samples] == [2, 2, 2, 1, 1, 1]  # b everywhere before the change; after it, only b
    after = {(round(r.y), round(r.h)) for e in samples[3:] for r in e.redact}
    assert len(after) == 1  # the box from before the change doesn't leak into the new screen


def test_huge_boxes_get_no_outline(tmp_path, monkeypatch):
    # Real case: a click on empty space (to dismiss a popup) came back as a 480x300 box; an outline that big shows
    # nothing in particular. Such actions keep their place in the steps but get no outline or zoom.
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=640x400:rate=30:duration=4",
                    "-pix_fmt", "yuv420p", str(video)], check=True)

    async def fake_find(_, fps=2):
        return FoundActions(actions=[FoundAction(at="0:01", kind="click", label="editor"),
                                     FoundAction(at="0:02", kind="click", label="Search all assets")])

    async def fake_locate(frames, descriptions):
        return LocatedFrames(frames=[Located(box=[100, 100, 500, 500]),  # 16% of the frame
                                     Located(box=[50, 300, 100, 700])])  # a 256x20 search bar: 2%

    async def no_samples(frames):
        return SensitiveFrames(frames=[[] for _ in frames])

    monkeypatch.setattr(upload.gemini, "find_actions", fake_find)
    monkeypatch.setattr(upload.gemini, "locate", fake_locate)
    monkeypatch.setattr(upload.gemini, "find_sensitive", no_samples)
    events = asyncio.run(upload.events_from_video(video, tmp_path))
    assert events[0].rect is None and events[1].rect is not None


def test_boxes_survive_a_screen_change_while_their_content_stays(tmp_path, monkeypatch):
    # Real case: a dialog opened and dimmed the page; Gemini didn't flag the dimmed name, and because a dialog
    # opening is a screen change, the earlier boxes were dropped. A box now stays across a change while what's
    # under it is still there (same pattern, any brightness); content that really changed loses it.
    from PIL import ImageDraw
    frames = tmp_path / "f"
    frames.mkdir()

    def pattern(d, x0, y0, seed):
        for i in range(12):
            d.rectangle((x0 + i * 20, y0, x0 + i * 20 + 8 + (seed * i) % 9, y0 + 20), fill="black")

    for n in range(90):  # 3 s at 30 fps
        img = Image.new("RGB", (640, 400), "white")
        d = ImageDraw.Draw(img)
        pattern(d, 40, 40, 1)  # a "name" that stays, dimmed after 1.5 s
        if n < 45:
            pattern(d, 40, 300, 3)  # a "name" that is replaced by other content after 1.5 s
        else:
            d.ellipse((60, 290, 300, 330), fill="black")
        if n >= 45:
            img = Image.eval(img, lambda v: v // 2)  # the dialog's dimming
        img.save(frames / f"{n:03}.png")
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "30", "-i", str(frames / "%03d.png"),
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    monkeypatch.setattr(upload, "SAMPLE_MS", 500)
    monkeypatch.setattr(upload.media, "scene_changes", lambda v: [1500])
    top, bottom = [90, 50, 160, 450], [740, 50, 810, 450]  # 0-1000 boxes around the two patterns

    async def boxes(frames_):  # found only before the change
        return SensitiveFrames(frames=[[top, bottom] if k < 3 else [] for k in range(len(frames_))])

    monkeypatch.setattr(upload, "SENSITIVE_BATCH", 100)
    monkeypatch.setattr(upload, "_same_content", real_same_content)
    monkeypatch.setattr(upload.gemini, "find_sensitive", boxes)
    samples = asyncio.run(upload.redact_samples(video, []))
    after = [e for e in samples if e.t >= 1500]
    assert after and all(len(e.redact) == 1 and e.redact[0].y < 100 for e in after)  # the dimmed name kept its blur
