import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import api, store
from app.models import Step

VP = {"w": 640, "h": 400, "dpr": 1}
EVENTS = [{"t": 1000, "kind": "click", "viewport": VP, "label": "Go", "rect": {"x": 10, "y": 10, "w": 50, "h": 20}}]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_db", tmp_path / "t.db")
    calls = []

    async def fake_process(article_id):
        calls.append(article_id)

    monkeypatch.setattr(api, "process", fake_process)
    with TestClient(api.app) as c:
        c.calls = calls
        yield c


def upload(client):
    r = client.post("/recordings", files={"video": ("v.webm", b"fake", "video/webm")},
                    data={"events": json.dumps(EVENTS)})
    assert r.status_code == 200
    return r.json()["id"]


def make_ready(article_id, title="How to go"):
    d = store.DATA_DIR / article_id / "frames"
    d.mkdir(parents=True)
    Image.new("RGB", (64, 40)).save(d / "0_zoom.png")
    a = store.get(article_id).model_copy(update={
        "status": "ready", "title": title,
        "steps": [Step(id="s1", event_ids=[0], text="Click **Go**.", frame=0)]})
    store.save(a)


def test_upload_stores_processing_and_schedules(client):
    article_id = upload(client)
    assert client.calls == [article_id]
    assert client.get(f"/articles/{article_id}").json()["status"] == "processing"
    assert (store.DATA_DIR / article_id / "video.webm").read_bytes() == b"fake"


def test_upload_rejects_bad_events(client):
    r = client.post("/recordings", files={"video": ("v.webm", b"x")}, data={"events": '[{"kind": "click"}]'})
    assert r.status_code == 422


def test_put_updates_and_validates(client):
    article_id = upload(client)
    make_ready(article_id)
    body = {"title": "New", "intro": "i", "outro": "o",
            "steps": [{"id": "s1", "event_ids": [0], "text": "Tap **Go**.", "frame": 0, "zoomed": True}]}
    assert client.put(f"/articles/{article_id}", json=body).json()["title"] == "New"
    body["steps"][0]["frame"] = 5
    assert client.put(f"/articles/{article_id}", json=body).status_code == 422


def test_unknown_and_malformed_ids_404(client):
    assert client.get("/articles/000000000000").status_code == 404
    assert client.get("/articles/..%2F..%2Fetc").status_code == 404


def test_share_escapes_html(client):
    article_id = upload(client)
    make_ready(article_id, title="<script>alert(1)</script>")
    page = client.get(f"/a/{article_id}").text
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page
    assert "<strong>Go</strong>" in page


def test_markdown_zip(client):
    article_id = upload(client)
    make_ready(article_id)
    z = zipfile.ZipFile(io.BytesIO(client.get(f"/articles/{article_id}/export.md.zip").content))
    assert set(z.namelist()) == {"article.md", "images/1.png"}
    assert "1. Click **Go**." in z.read("article.md").decode()



def test_video_upload_creates_upload_article(client):
    r = client.post("/uploads", files={"video": ("demo.mov", b"movie-bytes", "video/quicktime")})
    assert r.status_code == 200
    article_id = r.json()["id"]
    a = client.get(f"/articles/{article_id}").json()
    assert a["source"] == "upload" and a["status"] == "processing" and client.calls == [article_id]
    assert (store.DATA_DIR / article_id / "upload").read_bytes() == b"movie-bytes"
    assert not (store.DATA_DIR / article_id / "events.json").exists()  # the pipeline will find the steps


def test_video_upload_rejects_non_video(client):
    r = client.post("/uploads", files={"video": ("notes.pdf", b"%PDF", "application/pdf")})
    assert r.status_code == 415 and "MP4, MOV or WebM" in r.json()["detail"]
    assert client.calls == []


def test_delete_removes_article_and_files(client):
    article_id = upload(client)
    assert client.delete(f"/articles/{article_id}").status_code == 409  # still processing: the job would recreate it
    make_ready(article_id)
    assert client.delete(f"/articles/{article_id}").status_code == 204
    assert client.get(f"/articles/{article_id}").status_code == 404
    assert not (store.DATA_DIR / article_id).exists()
    assert client.delete(f"/articles/{article_id}").status_code == 404


def test_put_keeps_videos_and_translations(client):
    from app.models import VideoState
    article_id = upload(client)
    make_ready(article_id)
    store.update(article_id, lambda a: a.model_copy(update={"videos": {"en": VideoState(status="ready", version=3)}}))
    steps = [s.model_dump() for s in store.get(article_id).steps]
    r = client.put(f"/articles/{article_id}", json={"title": "T", "intro": "", "outro": "", "steps": steps,
                                                    "voice": "Sulafat"})
    assert r.status_code == 200
    a = store.get(article_id)
    assert a.voice == "Sulafat" and a.title == "T" and a.videos["en"].version == 3


def test_store_update_missing_article_returns_none(client):
    assert store.update("nope00000000", lambda a: a) is None


def test_video_endpoints(client, monkeypatch):
    from app import video
    from app.models import VideoState
    calls = []

    async def fake_make(article_id):
        calls.append(("make", article_id))

    async def fake_render(article_id, lang):
        calls.append(("render", article_id, lang))

    monkeypatch.setattr(video, "make", fake_make)
    monkeypatch.setattr(video, "render", fake_render)
    article_id = upload(client)
    make_ready(article_id)
    assert client.post(f"/articles/{article_id}/video").status_code == 202
    r = client.post(f"/articles/{article_id}/videos/en")
    assert r.status_code == 202 and r.json()["status"] == "none"
    assert client.post(f"/articles/{article_id}/videos/fr").status_code == 404  # not translated
    assert calls == [("make", article_id), ("render", article_id, "en")]

    store.update(article_id, lambda a: a.model_copy(update={"videos": {"en": VideoState(status="rendering")}}))
    r = client.delete(f"/articles/{article_id}")
    assert r.status_code == 409 and "video" in r.json()["detail"]


def test_voices_lists_stock_voices_and_mine(client):
    r = client.get("/voices").json()
    assert r["voices"][0] == {"id": "Achird", "label": "Friendly"} and r["mine"] is False


def test_translation_endpoints(client, monkeypatch):
    from app import translate
    from app.models import Translation, TStep, VideoState
    calls = []

    async def fake_add(article_id, lang):
        calls.append(("add", lang))

    async def fake_update(article_id, lang, ids):
        calls.append(("update", lang, ids))

    monkeypatch.setattr(translate, "add", fake_add)
    monkeypatch.setattr(translate, "update", fake_update)
    article_id = upload(client)
    make_ready(article_id)
    assert client.get("/languages").json()["es"] == "Spanish"
    assert client.post(f"/articles/{article_id}/translations/es").status_code == 202
    assert client.post(f"/articles/{article_id}/translations/xx").status_code == 422  # unknown code
    assert client.post(f"/articles/{article_id}/translations/en").status_code == 422  # the article's own language
    store.update(article_id, lambda a: a.model_copy(update={
        "videos": {"de": VideoState(status="rendering")},
        "translations": {"es": Translation(title="t", intro="", outro="", steps={
            "s1": TStep(text="x", narration="y", src="")})}}))
    assert client.post(f"/articles/{article_id}/translations/de").status_code == 409  # already in progress
    r = client.post(f"/articles/{article_id}/translations/es/update", json={"step_ids": ["s1"]})
    assert r.status_code == 202
    assert calls == [("add", "es"), ("update", "es", ["s1"])]

    r = client.put(f"/articles/{article_id}/translations/es", json={"title": "Hola", "intro": "", "outro": "",
                                                                   "steps": {"s1": {"text": "a", "narration": "b"}}})
    assert r.status_code == 200 and r.json()["translations"]["es"]["title"] == "Hola"
    r = client.put(f"/articles/{article_id}/translations/es", json={"title": "x", "intro": "", "outro": "",
                                                                   "steps": {"zz": {"text": "a", "narration": "b"}}})
    assert r.status_code == 422
    assert client.delete(f"/articles/{article_id}/translations/es").status_code == 204
    assert "es" not in store.get(article_id).translations


def test_pronunciations_round_trip(client):
    assert client.get("/settings/pronunciations").json() == {"words": {}}
    r = client.put("/settings/pronunciations", json={"words": {" SQL ": " sequel ", "": "x", "nginx": " "}})
    assert r.status_code == 200 and r.json() == {"words": {"SQL": "sequel"}}
    assert client.get("/settings/pronunciations").json() == {"words": {"SQL": "sequel"}}


def test_glossary_round_trip(client):
    assert client.get("/settings/glossary").json() == {"words": []}
    r = client.put("/settings/glossary", json={"words": [" Acmeflow ", "", "Acmeflow", "Save"]})
    assert r.json() == {"words": ["Acmeflow", "Save"]}
    assert client.get("/settings/glossary").json() == {"words": ["Acmeflow", "Save"]}


def test_my_voice_endpoints(client, monkeypatch):
    from app import voice
    got = []

    async def fake_setup(sample, consent):
        got.append((sample, consent))
        if sample == b"bad":
            raise ValueError("Gemini couldn't verify the consent recording.")

    monkeypatch.setattr(voice, "set_up_my_voice", fake_setup)
    monkeypatch.setattr(voice, "forget_my_voice", lambda: got.append("forgot"))
    assert client.get("/my-voice").json() == {"ready": False}
    files = {"sample": ("s.webm", b"sample", "audio/webm"), "consent": ("c.webm", b"consent", "audio/webm")}
    assert client.post("/my-voice", files=files).status_code == 204
    r = client.post("/my-voice", files={**files, "sample": ("s.webm", b"bad", "audio/webm")})
    assert r.status_code == 422 and "consent" in r.json()["detail"]
    assert client.delete("/my-voice").status_code == 204
    assert got == [(b"sample", b"consent"), (b"bad", b"consent"), "forgot"]


def test_my_voice_rejects_huge_uploads(client, monkeypatch):
    from app import voice

    async def never(sample, consent):
        raise AssertionError("should not be called")

    monkeypatch.setattr(voice, "set_up_my_voice", never)
    big = b"x" * (10 * 1024 * 1024 + 1)
    r = client.post("/my-voice", files={"sample": ("s.webm", big, "audio/webm"), "consent": ("c.webm", b"c", "audio/webm")})
    assert r.status_code == 413


def test_video_downloads(client, monkeypatch):
    from app import media
    from app.models import VideoState
    article_id = upload(client)
    make_ready(article_id, title="How to: link a term!")
    d = store.DATA_DIR / article_id
    assert client.get(f"/articles/{article_id}/videos/en.mp4").status_code == 404  # no video yet
    store.update(article_id, lambda a: a.model_copy(update={"videos": {"en": VideoState(status="ready", version=3)}}))
    (d / "video.en.mp4").write_bytes(b"mp4")
    (d / "captions.en.vtt").write_text("WEBVTT\n")
    (d / "cues.en.json").write_text(json.dumps([{"start_ms": 0, "end_ms": 1000, "text": "Hi"}]))
    burns = []
    monkeypatch.setattr(media, "burn_captions", lambda v, cues, dst: (burns.append(dst), dst.write_bytes(b"burned")))

    r = client.get(f"/articles/{article_id}/videos/en.mp4")
    assert r.content == b"mp4" and 'filename="how-to-link-a-term.en.mp4"' in r.headers["content-disposition"]
    assert client.get(f"/articles/{article_id}/videos/en.srt").text == "1\n00:00:00,000 --> 00:00:01,000\nHi\n"
    assert client.get(f"/articles/{article_id}/videos/en.vtt").text == "WEBVTT\n"
    for _ in range(2):
        assert client.get(f"/articles/{article_id}/videos/en.mp4?captions=burned").content == b"burned"
    assert len(burns) == 1  # cached per video version
    assert client.get(f"/articles/{article_id}/videos/en.mov").status_code == 404


def test_data_folder_can_be_set(tmp_path):
    import subprocess
    import sys
    out = subprocess.run([sys.executable, "-c", "from app import store; print(store.DATA_DIR)"], capture_output=True,
                         text=True, env={"WALKIE_DATA": str(tmp_path), "PATH": ""}, check=True).stdout.strip()
    assert out == str(tmp_path)


def test_server_serves_the_built_web_app(tmp_path):
    import subprocess
    import sys
    (tmp_path / "web").mkdir()
    (tmp_path / "web/index.html").write_text('<div id="root"></div>')
    code = ("from fastapi.testclient import TestClient; from app import api; c = TestClient(api.app); "
            "print(c.get('/').text); print(c.get('/languages').json()['es'])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"WALKIE_WEB_DIST": str(tmp_path / "web"), "WALKIE_DATA": str(tmp_path / "data"),
                              "PATH": ""}).stdout.split("\n")
    assert out[0] == '<div id="root"></div>' and out[1] == "Spanish"  # app at /, API routes still win


def test_burned_captions_that_cant_be_drawn_say_why(client, monkeypatch):
    from app import media
    from app.models import VideoState
    article_id = upload(client)
    make_ready(article_id)
    d = store.DATA_DIR / article_id
    store.update(article_id, lambda a: a.model_copy(update={"videos": {"en": VideoState(status="ready", version=1)}}))
    (d / "video.en.mp4").write_bytes(b"mp4")
    (d / "cues.en.json").write_text("[]")

    def refuse(v, cues, dst):
        raise ValueError("Captions in this language can't be drawn into the video here. Download the captions file.")

    monkeypatch.setattr(media, "burn_captions", refuse)
    r = client.get(f"/articles/{article_id}/videos/en.mp4?captions=burned")
    assert r.status_code == 422 and "captions file" in r.json()["detail"]
