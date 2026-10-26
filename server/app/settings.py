"""App-wide settings in data/settings.json: one self-hosted workspace, so no per-user or per-project settings."""

from pydantic import BaseModel

from app import store


class Settings(BaseModel):
    glossary: list[str] = []  # never translated: product names, UI labels
    pronunciations: dict[str, str] = {}  # word → how the voice says it; captions and articles keep the word
    my_voice_key: str = ""  # stateless Gemini voice key for the user's own voice
    my_voice_created: str = ""  # ISO time the key was made; keys expire after 7 days


def _path():
    return store.DATA_DIR / "settings.json"  # looked up per call: tests point DATA_DIR elsewhere


def load() -> Settings:
    p = _path()
    return Settings.model_validate_json(p.read_text()) if p.exists() else Settings()


def save(s: Settings) -> None:
    _path().parent.mkdir(parents=True, exist_ok=True)
    _path().write_text(s.model_dump_json(indent=2))
