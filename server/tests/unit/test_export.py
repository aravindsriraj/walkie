import io
import json
import zipfile

import pytest
from PIL import Image

from app import store
from app.export import docs_zip
from app.models import Article, Step, Translation, TStep, VideoState


@pytest.fixture
def article(tmp_path, monkeypatch):
    """A ready article with real frames, a finished English and Spanish video, and a Spanish translation."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    d = tmp_path / "a1"
    (d / "frames").mkdir(parents=True)
    for i in range(2):
        Image.new("RGB", (32, 20)).save(d / f"frames/{i}_zoom.png")
    for lang in ("en", "es"):
        (d / f"video.{lang}.mp4").write_bytes(f"video-{lang}".encode())
        (d / f"captions.{lang}.vtt").write_text(f"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n{lang}\n")
    return Article(
        id="a1", status="ready", created_at="t", title="How to go", intro="Intro.", outro="Done.",
        steps=[Step(id="s1", event_ids=[0], text="Click **Go**.", frame=0),
               Step(id="s2", event_ids=[1], text="Click **Save**.", frame=1)],
        videos={"en": VideoState(status="ready", version=2), "es": VideoState(status="ready", version=1)},
        translations={"es": Translation(title="Cómo ir", intro="Intro es.", outro="Hecho.", steps={
            "s1": TStep(text="[es] Haz clic en **Go**.", narration="", src="")})})


def test_docs_zip_has_video_and_every_language(article):
    z = zipfile.ZipFile(io.BytesIO(docs_zip(article)))
    names = set(z.namelist())
    assert {"article.md", "video.mp4", "video.vtt", "article.es.md", "video.es.mp4", "video.es.vtt",
            "images/1.png", "images/2.png"} <= names
    md = z.read("article.md").decode()
    assert md.index("<video") < md.index("1. Click **Go**.") and 'src="video.vtt"' in md and 'srcLang="en" label="English" default /></video>' in md
    es = z.read("article.es.md").decode()
    assert es.startswith("# Cómo ir") and "[es] Haz clic" in es and 'src="video.es.mp4"' in es
    assert "2. Click **Save**." in es  # an untranslated step falls back to the original text
    assert z.read("video.es.mp4") == b"video-es"


def test_docs_zip_without_video_is_the_plain_article(article):
    plain = article.model_copy(update={"videos": {}, "translations": {}})
    z = zipfile.ZipFile(io.BytesIO(docs_zip(plain)))
    assert not any(n.endswith(".mp4") for n in z.namelist())
    assert "<video" not in z.read("article.md").decode()


def test_rendering_video_is_left_out_but_the_old_one_isnt(article):
    a = article.model_copy(update={"videos": {"en": VideoState(status="rendering", version=2),
                                              "es": VideoState(status="failed", version=0)}})
    names = zipfile.ZipFile(io.BytesIO(docs_zip(a))).namelist()
    assert "video.mp4" in names and "video.es.mp4" not in names  # a finished earlier version is still a video


def test_cues_round_trip_to_srt(tmp_path, monkeypatch, article):
    from app.export import srt
    (tmp_path / "a1/cues.en.json").write_text(json.dumps([{"start_ms": 250, "end_ms": 1500, "text": "Hi"}]))
    assert srt(article, "en") == "1\n00:00:00,250 --> 00:00:01,500\nHi\n"


def test_mdx_safe_escapes_jsx_outside_code():
    from app.export import mdx_safe
    assert mdx_safe("Type {name} in <Name>, then `{x} <y>`") == "Type \\{name\\} in \\<Name>, then `{x} <y>`"
