import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import api, store
from app.clips import clip_props
from app.models import RecEvent, Rect, Step, Viewport

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


def test_clip_props_clamps_window():
    vp = Viewport(w=640, h=400)
    events = [RecEvent(t=200, kind="click", viewport=vp, rect=Rect(x=10, y=10, w=50, h=20)),
              RecEvent(t=4900, kind="click", viewport=vp)]
    p = clip_props(Step(id="a", event_ids=[0], text="", frame=0), events, 1280, 800, 5000, "u")
    assert (p["startMs"], p["endMs"], p["rect"]["x"]) == (0, 1700, 20)
    p = clip_props(Step(id="b", event_ids=[1], text="", frame=1), events, 1280, 800, 5000, "u")
    assert p["endMs"] == 5000 and p["rect"] is None and p["zoom"] == {"x": 0, "y": 0, "w": 1280, "h": 800}


def test_clip_redaction_timeline_covers_window():
    vp = Viewport(w=640, h=400)
    secret = Rect(x=10, y=10, w=100, h=20)
    events = [RecEvent(t=0, kind="navigate", viewport=vp, redact=[secret]),
              RecEvent(t=2000, kind="click", viewport=vp, rect=Rect(x=10, y=10, w=50, h=20), redact=[secret]),
              RecEvent(t=6000, kind="click", viewport=vp)]
    p = clip_props(Step(id="a", event_ids=[1], text="", frame=1), events, 1280, 800, 9000, "u")
    assert [(r["fromMs"], r["toMs"]) for r in p["redact"]] == [(0, 2000), (2000, 6000)]
    assert p["redact"][0]["rects"][0] == {"x": 20, "y": 20, "w": 200, "h": 40}


def test_clip_props_offsets_for_letterbox():
    vp = Viewport(w=1280, h=800)
    ev = RecEvent(t=1000, kind="click", viewport=vp, rect=Rect(x=100, y=100, w=10, h=10), redact=[Rect(x=0, y=0, w=10, h=10)])
    p = clip_props(Step(id="a", event_ids=[0], text="", frame=0), [ev], 3840, 2160, 5000, "u")
    assert round(p["rect"]["x"]) == 462 and round(p["redact"][0]["rects"][0]["x"]) == 192


def test_clip_zoom_stays_inside_page_when_letterboxed():
    vp = Viewport(w=900, h=718)  # window narrowed mid-recording; capture stayed 1280x718 → side bars
    ev = RecEvent(t=1000, kind="click", viewport=vp, rect=Rect(x=10, y=100, w=200, h=40))  # near the page's left edge
    z = clip_props(Step(id="a", event_ids=[0], text="", frame=0), [ev], 1280, 718, 5000, "u")["zoom"]
    left = (1280 - 900) // 2
    assert z["x"] >= left and z["x"] + z["w"] <= left + 900
