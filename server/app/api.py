import base64
import json
import re
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import store
from app.export import image_name, markdown_zip, render_html
from app.models import Article, RecEvent, Step
from app.pipeline import process

load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init()
    store.mark_interrupted()
    yield


app = FastAPI(title="Stepcast", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_origin_regex=r"chrome-extension://.*", allow_methods=["*"], allow_headers=["*"])
store.DATA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=store.DATA_DIR), name="files")


def _article(article_id: str) -> Article:
    if not re.fullmatch(r"[0-9a-f]{12}", article_id) or not (a := store.get(article_id)):
        raise HTTPException(404, "Article not found")
    return a


@app.post("/recordings")
async def upload(background: BackgroundTasks, video: UploadFile, events: str = Form(...)) -> dict:
    try:
        parsed = sorted((RecEvent.model_validate(e).model_dump() for e in json.loads(events)), key=lambda e: e["t"])
    except ValueError as e:
        raise HTTPException(422, f"Invalid events: {e}") from e
    article_id = uuid.uuid4().hex[:12]
    d = store.DATA_DIR / article_id
    d.mkdir(parents=True)
    with open(d / "video.webm", "wb") as f:
        while chunk := await video.read(1 << 20):
            f.write(chunk)
    (d / "events.json").write_text(json.dumps(parsed))
    store.save(Article(id=article_id, created_at=datetime.now(UTC).isoformat()))
    background.add_task(process, article_id)
    return {"id": article_id}


@app.get("/articles")
def list_articles() -> list[Article]:
    return store.list_all()


@app.get("/articles/{article_id}")
def get_article(article_id: str) -> Article:
    return _article(article_id)


class ArticleEdit(BaseModel):
    title: str
    intro: str
    outro: str
    steps: list[Step]


@app.put("/articles/{article_id}")
def update_article(article_id: str, edit: ArticleEdit) -> Article:
    a = _article(article_id)
    if a.status != "ready":
        raise HTTPException(409, "Article is not ready")
    n_events = len(json.loads((store.DATA_DIR / article_id / "events.json").read_text()))
    if any(not 0 <= s.frame < n_events for s in edit.steps):
        raise HTTPException(422, "Step frame out of range")
    a = a.model_copy(update=dict(edit))  # dict() keeps Step objects; model_dump() would turn them into dicts
    store.save(a)
    return a


@app.get("/articles/{article_id}/export.md.zip")
def export_md(article_id: str) -> Response:
    a = _article(article_id)
    return Response(markdown_zip(a), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{article_id}.zip"'})


@app.get("/articles/{article_id}/export.html")
def export_html(article_id: str) -> Response:
    a = _article(article_id)
    d = store.DATA_DIR / article_id

    def inline(s: Step) -> str:
        return "data:image/png;base64," + base64.b64encode((d / image_name(s)).read_bytes()).decode()

    return Response(render_html(a, inline), media_type="text/html",
                    headers={"Content-Disposition": f'attachment; filename="{article_id}.html"'})


@app.get("/a/{article_id}", response_class=HTMLResponse)
def share(article_id: str, print: bool = False) -> str:
    a = _article(article_id)
    if a.status != "ready":
        raise HTTPException(404, "Article not found")
    return render_html(a, lambda s: f"/files/{a.id}/{image_name(s)}", autoprint=print)
