import os
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

from app.models import Article

DATA_DIR = Path(os.getenv("WALKIE_DATA", Path(__file__).resolve().parent.parent / "data"))
_db: Path = DATA_DIR / "walkie.db"


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_db)


def init(db: Path | None = None) -> None:
    global _db
    if db:
        _db = db
    elif not _db.exists() and _db.with_name("stepcast.db").exists():  # the product was called Stepcast
        _db.with_name("stepcast.db").rename(_db)
    _db.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS articles (id TEXT PRIMARY KEY, data TEXT, created_at TEXT)")


def save(a: Article) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO articles VALUES (?, ?, ?)", (a.id, a.model_dump_json(), a.created_at))


def get(article_id: str) -> Article | None:
    with _conn() as c:
        row = c.execute("SELECT data FROM articles WHERE id = ?", (article_id,)).fetchone()
    return Article.model_validate_json(row[0]) if row else None


_lock = threading.Lock()


def update(article_id: str, change: Callable[[Article], Article]) -> Article | None:
    """Read, change and save as one step, so a background job and an editor save never overwrite each other."""
    with _lock:
        a = get(article_id)
        if a is None:
            return None
        a = change(a)
        save(a)
        return a


def delete(article_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM articles WHERE id = ?", (article_id,))


def list_all() -> list[Article]:
    with _conn() as c:
        rows = c.execute("SELECT data FROM articles ORDER BY created_at DESC").fetchall()
    return [Article.model_validate_json(r[0]) for r in rows]


def mark_interrupted() -> None:
    """On startup: work that was running when the server stopped will never finish."""
    for a in list_all():
        if a.status == "processing":
            a = a.model_copy(update={"status": "failed", "error": "Interrupted — please re-upload"})
        videos = {lang: v.model_copy(update={"status": "failed", "stage": "", "updating": [],
                                             "error": "Walkie was restarted while making this video. Try again."})
                  if v.status == "rendering" else v for lang, v in a.videos.items()}
        save(a.model_copy(update={"videos": videos}))
