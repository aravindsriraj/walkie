import asyncio
import json

import pytest

from app import settings, store, translate
from app.models import Article, Step, TDoc, TItem

VP = {"w": 640, "h": 400, "dpr": 1}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    store.init(tmp_path / "t.db")
    (tmp_path / "a1").mkdir()
    (tmp_path / "a1/events.json").write_text(json.dumps([{"t": t, "kind": "click", "viewport": VP} for t in (1000, 2000)]))
    store.save(Article(id="a1", status="ready", created_at="t", title="How to go", intro="Intro.", outro="Done.", steps=[
        Step(id="s1", event_ids=[0], text="Click **Go**.", frame=0, narration="Click Go."),
        Step(id="s2", event_ids=[1], text="Click **Save**.", frame=1, narration="Then save.")]))
    seen = {"keep": [], "docs": [], "rendered": []}

    async def fake_translate(doc: TDoc, lang, keep):
        seen["keep"].append(keep)
        seen["docs"].append(doc)
        tag = f"[{lang}] "
        return TDoc(title=tag + doc.title, intro=tag + doc.intro, outro=tag + doc.outro,
                    steps=[TItem(id=s.id, text=tag + s.text, narration=tag + s.narration) for s in doc.steps])

    async def fake_render(article_id, lang):
        seen["rendered"].append((article_id, lang))

    monkeypatch.setattr(translate.gemini, "translate", fake_translate)
    monkeypatch.setattr(translate.video, "render", fake_render)
    return seen


def test_add_translates_everything_and_renders(env):
    asyncio.run(translate.add("a1", "es"))
    a = store.get("a1")
    t = a.translations["es"]
    assert t.title == "[es] How to go" and t.steps["s1"].narration == "[es] Click Go."
    assert t.steps["s2"].text == "[es] Click **Save**."
    assert a.stale == {"es": []} and env["rendered"] == [("a1", "es")]


def test_glossary_words_are_passed_as_keep(env):
    settings.save(settings.Settings(glossary=["Acmeflow", "Go"]))
    asyncio.run(translate.add("a1", "de"))
    assert env["keep"] == [["Acmeflow", "Go"]]


def test_update_only_touches_listed_steps_and_keeps_manual_edits(env):
    asyncio.run(translate.add("a1", "es"))
    translate.save("a1", "es", translate.TranslationEdit(title="Mi título", intro="i", outro="o", steps={
        "s2": translate.StepEdit(text="Guarda **Save**.", narration="Guárdalo.")}))
    store.update("a1", lambda a: a.model_copy(update={"steps": [
        s.model_copy(update={"narration": "Click the Go button."}) if s.id == "s1" else s for s in a.steps]}))
    assert store.get("a1").stale == {"es": ["s1"]}
    asyncio.run(translate.update("a1", "es", ["s1"]))
    t = store.get("a1").translations["es"]
    assert [s.id for s in env["docs"][-1].steps] == ["s1"]
    assert t.steps["s1"].narration == "[es] Click the Go button."
    assert t.steps["s2"].narration == "Guárdalo." and t.title == "Mi título"
    assert store.get("a1").stale == {"es": []}


def test_new_source_step_is_stale(env):
    asyncio.run(translate.add("a1", "es"))
    store.update("a1", lambda a: a.model_copy(update={"steps": [*a.steps, Step(
        id="s3", event_ids=[1], text="New.", frame=1, narration="New.")]}))
    assert store.get("a1").stale == {"es": ["s3"]}


def test_failed_translation_marks_the_language_failed(env, monkeypatch):
    async def none(doc, lang, keep):
        return None

    monkeypatch.setattr(translate.gemini, "translate", none)
    asyncio.run(translate.add("a1", "fr"))
    a = store.get("a1")
    assert "fr" not in a.translations and a.videos["fr"].status == "failed"
    assert "didn't work" in a.videos["fr"].error and env["rendered"] == []


def test_save_rejects_unknown_steps(env):
    asyncio.run(translate.add("a1", "es"))
    with pytest.raises(ValueError):
        translate.save("a1", "es", translate.TranslationEdit(title="t", intro="", outro="", steps={
            "nope": translate.StepEdit(text="x", narration="y")}))


def test_remove_deletes_translation_and_its_files(env, tmp_path):
    asyncio.run(translate.add("a1", "es"))
    (tmp_path / "a1/video.es.mp4").write_bytes(b"v")
    (tmp_path / "a1/captions.es.vtt").write_text("WEBVTT\n")
    translate.remove("a1", "es")
    a = store.get("a1")
    assert "es" not in a.translations and "es" not in a.videos
    assert not (tmp_path / "a1/video.es.mp4").exists() and not (tmp_path / "a1/captions.es.vtt").exists()
