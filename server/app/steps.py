import io
import uuid
from pathlib import Path

from google.genai import types
from PIL import Image

from app.models import ACTIONABLE, RecEvent, Segment, Step, StepsDraft


def actionable(events: list[RecEvent]) -> list[int]:
    return [i for i, e in enumerate(events) if e.kind in ACTIONABLE]


def describe(i: int, ev: RecEvent) -> str:
    line = f'[{i}] {ev.t / 1000:.1f}s {ev.kind} on {ev.tag or "element"} "{ev.label}" at {ev.url}'
    if ev.kind == "keydown":
        line += f" (key: {ev.key})"
    if ev.value:
        line += f' (value: "{ev.value}")'
    return line


def _jpeg(path: Path, max_w: int = 1280) -> bytes:
    img = Image.open(path).convert("RGB")
    if img.width > max_w:
        img = img.resize((max_w, round(img.height * max_w / img.width)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _said(seg: Segment) -> types.Part:
    return types.Part.from_text(text=f'{seg.start_ms / 1000:.1f}s narrator: "{seg.text}"')


def build_parts(events: list[RecEvent], segments: list[Segment], frames_dir: Path) -> list[types.Part]:
    """Actions (text + screenshot) and narration interleaved in time order.

    Which action a sentence is about is left to the model: people talk before, during and after
    the action they mean, so no timing rule matches them reliably.
    """
    parts = []
    pending = sorted(segments, key=lambda s: s.start_ms)
    for i in actionable(events):
        while pending and pending[0].start_ms <= events[i].t:
            parts.append(_said(pending.pop(0)))
        parts.append(types.Part.from_text(text=describe(i, events[i])))
        parts.append(types.Part.from_bytes(data=_jpeg(frames_dir / f"{i}_full.png"), mime_type="image/jpeg"))
    parts.extend(_said(seg) for seg in pending)
    return parts


def narration_parts(steps: list[Step], events: list[RecEvent], segments: list[Segment],
                    frames_dir: Path) -> list[types.Part]:
    """Finished steps (text + screenshot) in recorded order, with what the presenter said interleaved by time."""
    parts = []
    pending = sorted(segments, key=lambda s: s.start_ms)
    for n, s in enumerate(sorted(steps, key=lambda s: events[s.event_ids[0]].t), 1):
        while pending and pending[0].start_ms <= events[s.event_ids[0]].t:
            parts.append(_said(pending.pop(0)))
        parts.append(types.Part.from_text(text=f"[step {n}] {s.text}"))
        parts.append(types.Part.from_bytes(data=_jpeg(frames_dir / f"{s.frame}_full.png"), mime_type="image/jpeg"))
    parts.extend(_said(seg) for seg in pending)
    return parts


def _fallback_text(ev: RecEvent) -> str:
    label = ev.label or ev.tag or "the element"
    if ev.kind == "input":
        return f"Type in **{label}**."
    if ev.kind == "keydown":
        return f"Press **{ev.key or 'Enter'}**."
    return f"Click **{label}**."


def _step(event_ids: list[int], text: str) -> Step:
    return Step(id=uuid.uuid4().hex[:8], event_ids=event_ids, text=text, frame=event_ids[0])


def normalize_steps(draft: StepsDraft | dict | None, events: list[RecEvent]) -> list[Step]:
    """LLM output is untrusted: keep only valid, unused, actionable ids; fall back if nothing survives."""
    valid = set(actionable(events))
    used: set[int] = set()
    steps: list[Step] = []
    try:
        draft = StepsDraft.model_validate(draft) if draft is not None else None
    except ValueError:
        draft = None
    for ds in draft.steps if draft else []:
        ids = sorted({i for i in ds.event_ids if i in valid and i not in used})
        if ids and ds.text.strip():
            used.update(ids)
            steps.append(_step(ids, ds.text.strip()))
    if not steps:
        steps = [_step([i], _fallback_text(events[i])) for i in sorted(valid)]
    return sorted(steps, key=lambda s: s.event_ids[0])
