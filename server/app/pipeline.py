import json
import logging

from app import gemini, media, store
from app.models import ArticleMeta, RecEvent, Segment
from app.steps import actionable, build_parts, normalize_steps

log = logging.getLogger(__name__)
MAX_ACTIONS = 120


async def _narration(video, d) -> list[Segment]:
    audio = d / "audio.mp3"
    media.extract_audio(video, audio)
    return await gemini.transcribe(audio.read_bytes())


async def process(article_id: str) -> None:
    """Recording → article. Never raises: always ends in status ready or failed."""
    a = store.get(article_id)
    d = store.DATA_DIR / article_id
    try:
        events = [RecEvent.model_validate(e) for e in json.loads((d / "events.json").read_text())]
        n = len(actionable(events))
        if n == 0:
            raise ValueError("No clicks or typing were recorded")
        if n > MAX_ACTIONS:
            raise ValueError("Recording too long — keep it under ~100 actions")

        video = d / "video.mp4"
        media.transcode(d / "video.webm", video)
        media.render_frames(video, events, d)

        narration = []
        if media.probe(video)[3]:
            try:
                narration = await _narration(video, d)
            except Exception:  # narration is a bonus; the steps still work without it
                log.exception("transcription failed for %s", article_id)

        steps = normalize_steps(await gemini.write_steps(build_parts(events, narration, d / "frames")), events)
        # Framing is written from the validated steps, so it never describes a step that was dropped.
        meta = await gemini.write_meta([s.text for s in steps]) or ArticleMeta(title="Untitled guide", intro="", outro="")
        a = a.model_copy(update={
            "status": "ready", "steps": steps, "title": meta.title, "intro": meta.intro, "outro": meta.outro,
        })
    except Exception as e:
        log.exception("processing failed for %s", article_id)
        a = a.model_copy(update={"status": "failed", "error": str(e) or type(e).__name__})
    store.save(a)
