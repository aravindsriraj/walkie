import sqlite3
from pathlib import Path

from app.models import Article

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_db: Path = DATA_DIR / "stepcast.db"


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_db)


def init(db: Path | None = None) -> None:
    global _db
    if db:
        _db = db
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


def list_all() -> list[Article]:
    with _conn() as c:
        rows = c.execute("SELECT data FROM articles ORDER BY created_at DESC").fetchall()
    return [Article.model_validate_json(r[0]) for r in rows]


def mark_interrupted() -> None:
    for a in list_all():
        if a.status == "processing":
            save(a.model_copy(update={"status": "failed", "error": "Interrupted — please re-upload"}))
