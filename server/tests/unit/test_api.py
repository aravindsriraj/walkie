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

