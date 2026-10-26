"""The video job: spoken narration per step → one voice clip per scene → retimed, zoomed scenes → one video per
language, with captions. Everything is cached by content, so an edit regenerates only what it changed."""

import asyncio
import hashlib
import json
import logging
import wave
from pathlib import Path

from app import gemini, media, store, upload, voice
from app.captions import cues, speakable, to_vtt
from app.models import ACTIONABLE, LANGUAGES, RecEvent, Rect, Segment, Step, VideoState
from app.scenes import plan_scene, scene_spans, sync_errors
from app.steps import narration_parts

log = logging.getLogger(__name__)
CLIPS_AT_ONCE = 4
GENERIC_ERROR = "Something went wrong while making the video. Try again."

# ponytail: in-process only; one server process. A request during a render queues exactly one re-run.
_running: set[tuple[str, str]] = set()
_again: set[tuple[str, str]] = set()


def _set(article_id: str, lang: str, **fields) -> None:
    def change(a):
        v = a.videos.get(lang, VideoState()).model_copy(update=fields)
        return a.model_copy(update={"videos": {**a.videos, lang: v}})
    store.update(article_id, change)


def _events(d: Path) -> list[RecEvent]:
    return [RecEvent.model_validate(e) for e in json.loads((d / "events.json").read_text())]


def _in_order(steps: list[Step], events: list[RecEvent]) -> list[Step]:
    """Scenes play in recorded order, whatever order the article shows its steps in."""
    return sorted(steps, key=lambda s: events[s.event_ids[0]].t)


def _lang(code: str) -> str:
    if code in LANGUAGES:
        return code
    base = code.split("-")[0].lower()
    return base if base in LANGUAGES else "en"


async def _segments(d: Path) -> list[Segment]:
    saved = d / "narration.json"
    if saved.exists():
        return [Segment.model_validate(s) for s in json.loads(saved.read_text())]
    segs: list[Segment] = []  # articles made before videos existed: transcribe now
    if (await asyncio.to_thread(media.probe, d / "video.mp4"))[3]:
        audio = d / "audio.mp3"
        await asyncio.to_thread(media.extract_audio, d / "video.mp4", audio)
        segs = await gemini.transcribe(audio.read_bytes())
    saved.write_text(json.dumps([s.model_dump() for s in segs]))
    return segs


async def make(article_id: str) -> None:
    """Write the narration if any step lacks it, then render the video in the article's language."""
    a = store.get(article_id)
    if a is None:
        return
    if any(not s.narration for s in a.steps):
        _set(article_id, a.lang, status="rendering", stage="Writing the narration", error="", note="")
        d = store.DATA_DIR / article_id
        events = _events(d)
        ordered = _in_order(a.steps, events)
        draft = None
        try:
            parts = await asyncio.to_thread(narration_parts, ordered, events, await _segments(d), d / "frames")
            draft = await gemini.write_narration(parts)
        except Exception:
            log.exception("narration failed for %s; using the step text", article_id)
        lines = {sc.step: sc.narration.strip() for sc in draft.scenes} if draft else {}
        written = {s.id: lines.get(n) or speakable(s.text) for n, s in enumerate(ordered, 1)}

        def apply(cur):
            steps = [s if s.narration else s.model_copy(update={"narration": written.get(s.id, speakable(s.text))})
                     for s in cur.steps]
            lang = _lang(draft.lang) if draft else cur.lang
            videos = {lang if k == cur.lang else k: v for k, v in cur.videos.items()}  # status follows the language
            return cur.model_copy(update={"steps": steps, "lang": lang, "videos": videos})
        a = store.update(article_id, apply)
    await render(article_id, a.lang)


async def render(article_id: str, lang: str) -> None:
    """Make (or update) the video for one language. Never raises; concurrent requests coalesce."""
    key = (article_id, lang)
    if key in _running:
        _again.add(key)
        return
    _running.add(key)
    try:
        while True:
            _again.discard(key)
            await _render_once(article_id, lang)
            if key not in _again:
                break
    finally:
        _running.discard(key)


async def _redact_samples(source: str, d: Path, events: list[RecEvent]) -> list[RecEvent]:
    """Uploads: where to blur between actions (made at upload; older uploads get them now). The extension sends
    its own as it records."""
    saved = d / "redact.json"
    if source != "upload":
        return []
    if not saved.exists():
        samples = await upload.redact_samples(d / "video.mp4", [e for e in events if e.kind in ACTIONABLE])
        saved.write_text(json.dumps([e.model_dump() for e in samples]))
    return [RecEvent.model_validate(e) for e in json.loads(saved.read_text())]


def _wav_ms(path: Path) -> int:
    with wave.open(str(path), "rb") as w:
        return round(w.getnframes() * 1000 / w.getframerate())


async def _render_once(article_id: str, lang: str) -> None:
    a = store.get(article_id)
    if a is None or (lang != a.lang and lang not in a.translations):
        return
    d = store.DATA_DIR / article_id
    try:
        _set(article_id, lang, status="rendering", stage="Preparing the video", error="", updating=[])
        if not a.steps:
            raise ValueError("This article has no steps to make a video from.")
        events = _events(d)
        ordered = _in_order(a.steps, events)
        if lang == a.lang:
            lines = [s.narration for s in ordered]
        else:
            tr = a.translations[lang].steps
            lines = [tr[s.id].narration if s.id in tr else "" for s in ordered]  # untranslated: silent, never wrong-language

        clean = d / "clean.mp4"
        if not clean.exists():
            await asyncio.to_thread(media.clean_video, d / "video.mp4", events + await _redact_samples(a.source, d, events),
                                    clean)

        _set(article_id, lang, stage="Recording the voiceover")
        note = ""
        gate = asyncio.Semaphore(CLIPS_AT_ONCE)

        async def clip(text: str) -> Path | None:
            nonlocal note
            if not speakable(text):
                return None
            async with gate:
                try:
                    return await voice.clip(d, text, a.voice)
                except Exception:
                    if a.voice != voice.MINE or lang == a.lang:
                        raise
                    note = (f"Your voice couldn't be used in {LANGUAGES.get(lang, lang)}, "
                            f"so {voice.DEFAULT_VOICE} was used.")
                    return await voice.clip(d, text, voice.DEFAULT_VOICE)

        clips = await asyncio.gather(*(clip(t) for t in lines))
        clip_ms = [_wav_ms(c) if c else 0 for c in clips]

        cw, _, duration_ms, _ = await asyncio.to_thread(media.probe, clean)
        groups = [[events[i].t for i in s.event_ids if events[i].kind in ACTIONABLE] or [events[s.event_ids[0]].t]
                  for s in ordered]
        spans = scene_spans(groups, duration_ms)
        plans = [plan_scene(g, sp, ms, s.hold_ms) for g, sp, ms, s in zip(groups, spans, clip_ms, ordered, strict=True)]
        scale = cw / events[0].viewport.w

        def zoom(s: Step) -> Rect | None:
            r = next((events[i].rect for i in s.event_ids if events[i].kind in ACTIONABLE and events[i].rect), None)
            return media.scale_rect(r, scale) if s.video_zoom and r and r.w > 0 and r.h > 0 else None

        zooms = [zoom(s) for s in ordered]
        source = clean.stat()  # scenes are cut from this clean pass: a rebuilt one (e.g. better blurring) re-cuts all
        files = [d / "scenes" / f"{hashlib.sha1(repr((p, z, source.st_mtime_ns, source.st_size)).encode()).hexdigest()[:16]}.mp4"
                 for p, z in zip(plans, zooms, strict=True)]
        (d / "scenes").mkdir(exist_ok=True)
        todo = [i for i, f in enumerate(files) if not f.exists()]
        _set(article_id, lang, stage="Putting the video together", updating=[ordered[i].id for i in todo])
        for i in todo:
            tmp = files[i].with_suffix(".part.mp4")
            await asyncio.to_thread(media.render_scene, clean, plans[i], zooms[i], tmp)
            tmp.replace(files[i])

        rendered = [await asyncio.to_thread(media.video_ms, f) for f in files]
        if errors := sync_errors(plans, clip_ms, rendered):  # never replace a good video with an out-of-sync one
            log.error("sync check failed for %s/%s: %s", article_id, lang, errors)
            raise ValueError("The video couldn't be synced. Try again, and report it if it keeps happening.")

        starts, t = [], 0
        for ms in rendered:
            starts.append(t)
            t += ms
        placements = [(st + p.voice_at_ms, c) for st, p, c in zip(starts, plans, clips, strict=True) if c]
        wav = d / f"voice.{lang}.wav"
        await asyncio.to_thread(media.build_audio, placements, t, wav)
        await asyncio.to_thread(media.concat, files, wav, d / f"video.{lang}.mp4")
        wav.unlink()

        cs = cues([(st + p.voice_at_ms, ms, line)
                   for st, p, ms, line in zip(starts, plans, clip_ms, lines, strict=True)])
        (d / f"captions.{lang}.vtt").write_text(to_vtt(cs))
        (d / f"cues.{lang}.json").write_text(json.dumps([c.__dict__ for c in cs]))
        version = (store.get(article_id).videos.get(lang) or VideoState()).version
        _set(article_id, lang, status="ready", stage="", updating=[], error="", note=note, version=version + 1)
    except Exception as e:
        log.exception("video failed for %s/%s", article_id, lang)
        message = str(e) if isinstance(e, ValueError | LookupError) and str(e) else GENERIC_ERROR
        _set(article_id, lang, status="failed", stage="", updating=[], error=message)
