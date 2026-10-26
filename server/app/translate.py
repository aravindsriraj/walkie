"""Other languages: the article and its narration translated, then the video rendered from the translation.
Each language stays editable on its own; source changes mark steps stale (Article.stale) instead of overwriting."""

import logging

from pydantic import BaseModel

from app import gemini, settings, store, video
from app.models import Article, TDoc, TItem, Translation, TStep, VideoState, source_hash

log = logging.getLogger(__name__)
FAILED = "The translation didn't work. Try again."


class StepEdit(BaseModel):
    text: str
    narration: str


class TranslationEdit(BaseModel):
    title: str
    intro: str
    outro: str
    steps: dict[str, StepEdit] = {}


def _state(article_id: str, lang: str, **fields) -> None:
    store.update(article_id, lambda a: a.model_copy(update={"videos": {
        **a.videos, lang: a.videos.get(lang, VideoState()).model_copy(update=fields)}}))


async def _translate(a: Article, lang: str, step_ids: list[str], framing: tuple[str, str, str]) -> TDoc:
    steps = [TItem(id=s.id, text=s.text, narration=s.narration) for s in a.steps if s.id in step_ids]
    doc = TDoc(title=framing[0], intro=framing[1], outro=framing[2], steps=steps)
    out = await gemini.translate(doc, lang, settings.load().glossary)
    if out is None or {s.id for s in out.steps} != {s.id for s in steps}:
        raise ValueError(FAILED)
    return out


async def add(article_id: str, lang: str) -> None:
    """Translate everything, then make that language's video. Never raises."""
    a = store.get(article_id)
    if a is None:
        return
    _state(article_id, lang, status="rendering", stage="Translating", error="", note="", updating=[])
    try:
        out = await _translate(a, lang, [s.id for s in a.steps], (a.title, a.intro, a.outro))
    except Exception:
        log.exception("translation to %s failed for %s", lang, article_id)
        _state(article_id, lang, status="failed", stage="", error=FAILED)
        return
    src = {s.id: source_hash(s) for s in a.steps}

    def apply(cur: Article) -> Article:
        t = Translation(title=out.title, intro=out.intro, outro=out.outro,
                        steps={i.id: TStep(text=i.text, narration=i.narration, src=src[i.id]) for i in out.steps})
        return cur.model_copy(update={"translations": {**cur.translations, lang: t}})

    store.update(article_id, apply)
    await video.render(article_id, lang)


async def update(article_id: str, lang: str, step_ids: list[str]) -> None:
    """Re-translate only these (changed) steps, keeping every other edit, then re-render. Never raises."""
    a = store.get(article_id)
    if a is None or lang not in a.translations:
        return
    t = a.translations[lang]
    _state(article_id, lang, status="rendering", stage="Translating", error="")
    try:
        out = await _translate(a, lang, step_ids, (t.title, t.intro, t.outro))
    except Exception:
        log.exception("updating %s translation failed for %s", lang, article_id)
        _state(article_id, lang, status="failed", stage="", error=FAILED)
        return

    def apply(cur: Article) -> Article:
        now = {s.id: source_hash(s) for s in cur.steps}
        tr = cur.translations[lang]
        steps = {**tr.steps, **{i.id: TStep(text=i.text, narration=i.narration, src=now.get(i.id, ""))
                                for i in out.steps}}
        return cur.model_copy(update={"translations": {**cur.translations, lang: tr.model_copy(update={"steps": steps})}})

    store.update(article_id, apply)
    await video.render(article_id, lang)


def save(article_id: str, lang: str, edit: TranslationEdit) -> Article:
    """A translator's edits. Each step keeps the source version it was translated from."""
    def apply(cur: Article) -> Article:
        tr = cur.translations.get(lang)
        if tr is None:
            raise ValueError("This article has no translation in that language")
        if unknown := set(edit.steps) - set(tr.steps):
            raise ValueError(f"Unknown steps: {sorted(unknown)}")
        steps = {**tr.steps, **{k: tr.steps[k].model_copy(update=v.model_dump()) for k, v in edit.steps.items()}}
        t = tr.model_copy(update={"title": edit.title, "intro": edit.intro, "outro": edit.outro, "steps": steps})
        return cur.model_copy(update={"translations": {**cur.translations, lang: t}})
    return store.update(article_id, apply)


def remove(article_id: str, lang: str) -> None:
    store.update(article_id, lambda a: a.model_copy(update={
        "translations": {k: v for k, v in a.translations.items() if k != lang},
        "videos": {k: v for k, v in a.videos.items() if k != lang}}))
    d = store.DATA_DIR / article_id
    for name in (f"video.{lang}.mp4", f"captions.{lang}.vtt", f"cues.{lang}.json"):
        (d / name).unlink(missing_ok=True)
    for burned in d.glob(f"video.{lang}.burned.*.mp4"):
        burned.unlink()
