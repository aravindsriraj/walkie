import itertools

from app.captions import Cue, caption_png, cues, speakable, to_srt, to_vtt


def test_cues_wrap_split_and_stay_inside_the_clip():
    long = "Click Link assets to search for the tables you want and connect them to this glossary term in one go."
    cs = cues([(250, 6000, long), (7000, 0, ""), (8000, 2000, "Click **Save**.")])
    assert all(len(line) <= 42 for c in cs for line in c.text.split("\n"))
    assert all(c.text.count("\n") <= 1 for c in cs)
    first = [c for c in cs if c.start_ms < 7000]
    assert first[0].start_ms == 250 and first[-1].end_ms == 6250 and len(first) == 2
    assert " ".join(c.text.replace("\n", " ") for c in first) == long
    assert cs[-1].text == "Click Save." and cs[-1].start_ms == 8000  # markdown stripped; empty narration made no cue
    assert all(a.end_ms <= b.start_ms for a, b in itertools.pairwise(cs))


def test_one_long_word_does_not_break_wrapping():
    cs = cues([(0, 1000, "x" * 60)])
    assert cs == [Cue(0, 1000, "x" * 60)]


def test_vtt_and_srt_formats():
    cs = [Cue(250, 61500, "Hello\nthere"), Cue(3_600_000, 3_601_000, "Late")]
    assert to_vtt(cs) == ("WEBVTT\n\n00:00:00.250 --> 00:01:01.500\nHello\nthere\n\n"
                          "01:00:00.000 --> 01:00:01.000\nLate\n")
    assert to_srt(cs) == "1\n00:00:00,250 --> 00:01:01,500\nHello\nthere\n\n2\n01:00:00,000 --> 01:00:01,000\nLate\n"


def test_speakable_strips_markdown():
    assert speakable("  Click **Save**,\n then type `acme`. ") == "Click Save, then type acme."


def test_caption_png_is_transparent_outside_the_box():
    img = caption_png("Click Save.", 1280)
    assert img.mode == "RGBA" and img.width == 1280 and img.getpixel((0, 0))[3] == 0
    assert any(img.getpixel((640, y))[3] > 0 for y in range(img.height))


def test_caption_font_covers_accents_and_cjk():
    # Real bug: the built-in font drew "navegación" as "navegaci?n".
    from app.captions import caption_font, covers
    for text in ("navegación izquierda", "Перейдите", "日本語のテキスト"):
        assert covers(caption_font(text, 30), text), text


def test_scripts_that_need_shaping_are_refused_without_a_shaper(monkeypatch):
    import pytest

    from app import captions
    monkeypatch.setattr(captions.features, "check", lambda name: False)
    with pytest.raises(ValueError, match="captions file"):
        caption_png("مرحبا بك", 1280)
    caption_png("Hola, ¿qué tal?", 1280)  # Latin needs no shaping
