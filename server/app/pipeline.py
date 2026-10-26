import asyncio
import json
import logging
import subprocess

from app import gemini, media, store, upload, video
from app.models import Article, ArticleMeta, RecEvent, Segment
from app.steps import actionable, build_parts, normalize_steps

log = logging.getLogger(__name__)
MAX_ACTIONS = 120
MAX_UPLOAD_MS = 10 * 60 * 1000  # same cap as the extension's auto-stop


async def _narration(mp4, d) -> list[Segment]:
    audio = d / "audio.mp3"
    await asyncio.to_thread(media.extract_audio, mp4, audio)
    return await gemini.transcribe(audio.read_bytes())


async def process(article_id: str) -> None:
    """Recording → article. Never raises: always ends in status ready or failed."""
    a = store.get(article_id)
    d = store.DATA_DIR / article_id

    def progress(**update) -> Article:
        nonlocal a
        a = a.model_copy(update=update)
        store.save(a)  # the editor polls this to show live progress
        return a

    def check(events: list[RecEvent]) -> int:
        n = len(actionable(events))
        if n == 0:
            raise ValueError("No clicks or typing were recorded" if a.source == "extension"
                             else "No clicks or typing were found in this video")
        if n > MAX_ACTIONS:
            raise ValueError("Recording too long — keep it under ~100 actions")
        return n

    try:
        log_file = d / "events.json"  # the extension's action log; uploads don't have one
        events = [RecEvent.model_validate(e) for e in json.loads(log_file.read_text())] if log_file.exists() else []
        if log_file.exists():
            check(events)  # fail fast, before the slow work

        # ffmpeg and Pillow block, so they run in a worker thread: on the event loop they would
        # freeze the whole API, including the progress polls.
        progress(stage="Preparing the recording")
        mp4 = d / "video.mp4"
        source = d / "video.webm" if a.source == "extension" else d / "upload"
        try:
            await asyncio.to_thread(media.transcode, source, mp4)
        except subprocess.CalledProcessError as e:
            raise ValueError("This file isn't a video Walkie can read. Try an MP4, MOV or WebM file.") from e

        if not log_file.exists():
            if (await asyncio.to_thread(media.probe, mp4))[2] > MAX_UPLOAD_MS:
                raise ValueError("This video is longer than 10 minutes. Trim it and upload it again.")
            progress(stage="Finding the steps in your video")
            events = await upload.events_from_video(mp4, d)
            log_file.write_text(json.dumps([e.model_dump() for e in events]))
            samples = await upload.redact_samples(mp4, events)  # the video's blurring between actions
            (d / "redact.json").write_text(json.dumps([e.model_dump() for e in samples]))
        n = check(events)

        progress(stage="Capturing screenshots", stage_total=n)
        await asyncio.to_thread(media.render_frames, mp4, events, d, lambda i: progress(frames=[*a.frames, i]))

        narration = []
        if (await asyncio.to_thread(media.probe, mp4))[3]:
            progress(stage="Listening to your narration")
            try:
                narration = await _narration(mp4, d)
            except Exception:  # narration is a bonus; the steps still work without it
                log.exception("transcription failed for %s", article_id)

        (d / "narration.json").write_text(json.dumps([s.model_dump() for s in narration]))  # the video's script uses it
        progress(stage="Writing the steps")
        parts = await asyncio.to_thread(build_parts, events, narration, d / "frames")
        steps = normalize_steps(await gemini.write_steps(parts), events)
        # Framing is written from the validated steps, so it never describes a step that was dropped.
        progress(stage="Writing the title and intro")
        meta = await gemini.write_meta([s.text for s in steps]) or ArticleMeta(title="Untitled guide", intro="", outro="")
        a = a.model_copy(update={
            "status": "ready", "stage": "", "steps": steps, "title": meta.title, "intro": meta.intro, "outro": meta.outro,
        })
    except Exception as e:
        log.exception("processing failed for %s", article_id)
        a = a.model_copy(update={"status": "failed", "stage": "", "error": str(e) or type(e).__name__})
    store.save(a)
    if a.status == "ready":
        await video.make(article_id)  # the article is already editable; the video follows in its own status
