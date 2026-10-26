import asyncio
import base64
import json
import os
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import media, settings, store, translate, video, voice
from app.captions import Cue
from app.export import docs_zip, image_name, render_html, srt
from app.models import LANGUAGES, Article, RecEvent, Step, VideoState
from app.pipeline import process

load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init()
    store.mark_interrupted()
    yield


app = FastAPI(title="Walkie", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_origin_regex=r"chrome-extension://.*", allow_methods=["*"], allow_headers=["*"])
store.DATA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=store.DATA_DIR), name="files")


def _article(article_id: str) -> Article:
    if not re.fullmatch(r"[0-9a-f]{12}", article_id) or not (a := store.get(article_id)):
        raise HTTPException(404, "Article not found")
    return a


async def _save_file(video: UploadFile, dst: Path, limit: int | None = None) -> None:
    size = 0
    with open(dst, "wb") as f:
        while chunk := await video.read(1 << 20):
            size += len(chunk)
            if limit and size > limit:
                raise HTTPException(413, "This file is over 2 GB. Trim or compress it and upload it again.")
            f.write(chunk)


def _new_article() -> tuple[str, Path]:
    article_id = uuid.uuid4().hex[:12]
    d = store.DATA_DIR / article_id
    d.mkdir(parents=True)
    return article_id, d


@app.post("/recordings")
async def upload_recording(background: BackgroundTasks, video: UploadFile, events: str = Form(...)) -> dict:
    """From the extension: the tab video plus its action log."""
    try:
        parsed = sorted((RecEvent.model_validate(e).model_dump() for e in json.loads(events)), key=lambda e: e["t"])
    except ValueError as e:
        raise HTTPException(422, f"Invalid events: {e}") from e
    article_id, d = _new_article()
    await _save_file(video, d / "video.webm")
    (d / "events.json").write_text(json.dumps(parsed))
    store.save(Article(id=article_id, created_at=datetime.now(UTC).isoformat()))
    background.add_task(process, article_id)
    return {"id": article_id}


VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
MAX_UPLOAD_BYTES = 2 << 30


@app.post("/uploads")
async def upload_video(background: BackgroundTasks, video: UploadFile) -> dict:
    """A screen recording made any other way: no action log, so the pipeline finds the steps itself."""
    if not ((video.content_type or "").startswith("video/") or (video.filename or "").lower().endswith(VIDEO_SUFFIXES)):
        raise HTTPException(415, "That isn't a video file. Upload an MP4, MOV or WebM screen recording.")
    article_id, d = _new_article()
    try:
        await _save_file(video, d / "upload", MAX_UPLOAD_BYTES)
    except HTTPException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    store.save(Article(id=article_id, source="upload", created_at=datetime.now(UTC).isoformat()))
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
    voice: str = ""


@app.put("/articles/{article_id}")
def update_article(article_id: str, edit: ArticleEdit) -> Article:
    a = _article(article_id)
    if a.status != "ready":
        raise HTTPException(409, "Article is not ready")
    n_events = len(json.loads((store.DATA_DIR / article_id / "events.json").read_text()))
    if any(not 0 <= s.frame < n_events for s in edit.steps):
        raise HTTPException(422, "Step frame out of range")
    # Only the edited fields change: videos and translations are written by background jobs meanwhile.
    return store.update(article_id, lambda cur: cur.model_copy(update=dict(edit)))  # dict() keeps Step objects


@app.delete("/articles/{article_id}", status_code=204)
def delete_article(article_id: str) -> None:
    """Permanently removes the article, its recording and its screenshots."""
    a = _article(article_id)
    if a.status == "processing":  # the background job would write the article back
        raise HTTPException(409, "This article is still being written. Delete it once it's done.")
    if any(v.status == "rendering" for v in a.videos.values()):
        raise HTTPException(409, "A video for this article is still being made. Delete it once it's done.")
    store.delete(article_id)
    shutil.rmtree(store.DATA_DIR / article_id, ignore_errors=True)


@app.post("/articles/{article_id}/video", status_code=202)
def make_video(article_id: str, background: BackgroundTasks) -> None:
    """Narration (if missing) and the video in the article's language, e.g. for articles made before videos."""
    if _article(article_id).status != "ready":
        raise HTTPException(409, "Article is not ready")
    background.add_task(video.make, article_id)


@app.post("/articles/{article_id}/videos/{lang}", status_code=202)
def render_video(article_id: str, lang: str, background: BackgroundTasks) -> VideoState:
    """Re-render after edits; only changed scenes are regenerated."""
    a = _article(article_id)
    if lang != a.lang and lang not in a.translations:
        raise HTTPException(404, "This article has no version in that language")
    background.add_task(video.render, article_id, lang)
    return a.videos.get(lang, VideoState())


@app.get("/voices")
def list_voices() -> dict:
    return {"voices": [{"id": k, "label": v} for k, v in voice.VOICES.items()], "mine": voice.my_voice_ready()}


MAX_VOICE_BYTES = 10 * 1024 * 1024


@app.get("/my-voice")
def my_voice() -> dict:
    return {"ready": voice.my_voice_ready()}


@app.post("/my-voice", status_code=204)
async def set_up_my_voice(sample: UploadFile, consent: UploadFile) -> None:
    """Two recordings from the browser: a voice sample and the consent statement. Kept on this machine."""
    clips = []
    for f in (sample, consent):
        data = await f.read(MAX_VOICE_BYTES + 1)
        if len(data) > MAX_VOICE_BYTES:
            raise HTTPException(413, "That recording is too long. Keep each one under a minute.")
        clips.append(data)
    try:
        await voice.set_up_my_voice(*clips)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.delete("/my-voice", status_code=204)
def forget_my_voice() -> None:
    voice.forget_my_voice()


@app.get("/languages")
def list_languages() -> dict[str, str]:
    return LANGUAGES


@app.post("/articles/{article_id}/translations/{lang}", status_code=202)
def add_translation(article_id: str, lang: str, background: BackgroundTasks) -> None:
    a = _article(article_id)
    if lang not in LANGUAGES or lang == a.lang:
        raise HTTPException(422, "Choose a language this article isn't already in")
    if a.status != "ready":
        raise HTTPException(409, "Article is not ready")
    if a.videos.get(lang, VideoState()).status == "rendering":
        raise HTTPException(409, "This language is already being made")
    background.add_task(translate.add, article_id, lang)


class StaleSteps(BaseModel):
    step_ids: list[str]


@app.post("/articles/{article_id}/translations/{lang}/update", status_code=202)
def update_translation(article_id: str, lang: str, body: StaleSteps, background: BackgroundTasks) -> None:
    if lang not in _article(article_id).translations:
        raise HTTPException(404, "This article has no translation in that language")
    background.add_task(translate.update, article_id, lang, body.step_ids)


@app.put("/articles/{article_id}/translations/{lang}")
def save_translation(article_id: str, lang: str, edit: translate.TranslationEdit) -> Article:
    _article(article_id)
    try:
        return translate.save(article_id, lang, edit)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.delete("/articles/{article_id}/translations/{lang}", status_code=204)
def remove_translation(article_id: str, lang: str) -> None:
    a = _article(article_id)
    if a.videos.get(lang, VideoState()).status == "rendering":
        raise HTTPException(409, "This language is still being made. Remove it once it's done.")
    translate.remove(article_id, lang)


class Glossary(BaseModel):
    words: list[str]


@app.get("/settings/glossary")
def get_glossary() -> Glossary:
    return Glossary(words=settings.load().glossary)


@app.put("/settings/glossary")
def put_glossary(body: Glossary) -> Glossary:
    words = list(dict.fromkeys(w.strip() for w in body.words if w.strip()))
    settings.save(settings.load().model_copy(update={"glossary": words}))
    return Glossary(words=words)


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "video"


@app.get("/articles/{article_id}/videos/{name}")
async def download_video(article_id: str, name: str, captions: str = "") -> Response:
    """{lang}.mp4 (?captions=burned draws them into the picture), {lang}.vtt or {lang}.srt."""
    a = _article(article_id)
    lang, _, kind = name.rpartition(".")
    v = a.videos.get(lang)
    d = store.DATA_DIR / article_id
    mp4 = d / f"video.{lang}.mp4"
    if kind not in ("mp4", "vtt", "srt") or not v or v.version == 0 or not mp4.exists():
        raise HTTPException(404, "There's no finished video in that language yet")
    filename = f"{_slug(a.translations[lang].title if lang in a.translations else a.title)}.{lang}.{kind}"
    attach = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if kind == "vtt":
        return FileResponse(d / f"captions.{lang}.vtt", media_type="text/vtt", headers=attach)
    if kind == "srt":
        return Response(srt(a, lang), media_type="application/x-subrip", headers=attach)
    if captions == "burned":
        burned = d / f"video.{lang}.burned.{v.version}.mp4"  # cached per version
        if not burned.exists():
            for old in d.glob(f"video.{lang}.burned.*.mp4"):  # earlier versions
                old.unlink()
            cs = [Cue(**c) for c in json.loads((d / f"cues.{lang}.json").read_text())]
            try:
                await asyncio.to_thread(media.burn_captions, mp4, cs, burned)
            except ValueError as e:  # e.g. a script this server can't lay out: the captions file still works
                raise HTTPException(422, str(e)) from e
        mp4 = burned
    return FileResponse(mp4, media_type="video/mp4", headers=attach)


@app.get("/articles/{article_id}/export.md.zip")
def export_md(article_id: str) -> Response:
    a = _article(article_id)
    return Response(docs_zip(a), media_type="application/zip",
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


# The built web app, served at / (after every API route, so those win). In development Vite serves it instead.
WEB_DIST = Path(os.getenv("WALKIE_WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist"))
if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
