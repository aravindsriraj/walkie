"""Every Gemini call the app makes, through the google-genai SDK.

Models are chosen per job:
- MODEL: reads the action timeline + screenshots and decides the steps (multimodal, the hard part)
- LITE_MODEL: title/intro/outro from the finished steps (short, text-only)
- TRANSCRIBE_MODEL: narration with exact word timings (served only through the Interactions API)
"""

import base64

from google import genai
from google.genai import types
from google.genai.client import AsyncClient

from app.models import ArticleMeta, Segment, StepsDraft

MODEL = "gemini-3.8-flash"
LITE_MODEL = "gemini-3.5-flash-lite"
TRANSCRIBE_MODEL = "gemini-3.5-transcribe"

STEPS_PROMPT = """You turn a recorded software walkthrough into the steps of a how-to help article.

The user message is a timeline. Each recorded action is a line `[index] time kind on tag "label" at url`
(optionally with the typed value), followed by a screenshot taken at that moment, with the element
acted on outlined in purple. Lines like `time narrator: "..."` are what the presenter said, placed in
time order between the actions.

Write the steps:
- Group consecutive actions that form one logical step (e.g. clicking a field then typing in it,
  or opening a menu then picking an item). Most steps cover 1-2 actions.
- A click that submits, saves, confirms or opens a new screen or dialog (Sign in, Save, Create,
  Next, + New) is its own step, and it ends the step before it. Never combine actions from
  different screens into one step.
- Drop actions that are clearly noise (accidental or repeated clicks on empty space).
- Each step is ONE imperative sentence, at most 25 words. Put UI labels exactly as they appear
  on screen in **bold**. Use `code` for literal values the reader must type.
- Describe what to type generically ("Enter your project name") unless the exact value matters.
- When the narrator gives a reason or tip, keep it as a short clause in the step it is about
  ("To send the report to finance, click **Share**."). People talk before, during or after the
  action they mean, so match narration by meaning, not by position. Skip filler.
- Only describe what is visible in the screenshots or recorded in the action list. Never invent
  buttons, menus or values. Never mention the purple outline, screenshots, or the recording.
- event_ids must be the indices from the list, ascending."""

META_PROMPT = """You write the framing for a how-to help article, given its steps.

Return:
- title: "How to <task>", at most 10 words, sentence case.
- intro: 1-2 sentences telling the reader what they will accomplish.
- outro: one sentence on the result or a natural next step.
Plain, friendly product-docs tone. No marketing language."""

SENTENCE_END = (".", "?", "!")
PAUSE_MS = 1000


def _aio() -> AsyncClient:
    # A client per call, used as `async with`: a shared async client is bound to the first event loop and
    # breaks in any other, and the context manager keeps it alive for the call and closes it after.
    return genai.Client(http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=3))).aio


def _json(schema: type, system: str) -> types.GenerateContentConfig:
    # Default (high) thinking spent ~11k tokens / 50-90 s on a 10-action recording; LOW takes ~5 s, same quality.
    return types.GenerateContentConfig(
        system_instruction=system, response_mime_type="application/json", response_schema=schema,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
    )


async def write_steps(parts: list[types.Part]) -> StepsDraft | None:
    async with _aio() as c:
        r = await c.models.generate_content(
            model=MODEL, contents=types.Content(role="user", parts=parts), config=_json(StepsDraft, STEPS_PROMPT))
    return r.parsed  # None if the reply doesn't fit the schema; normalize_steps then falls back


async def write_meta(step_texts: list[str]) -> ArticleMeta | None:
    steps = "\n".join(f"{n}. {t}" for n, t in enumerate(step_texts, 1))
    async with _aio() as c:
        r = await c.models.generate_content(
            model=LITE_MODEL, contents=f"Steps:\n{steps}", config=_json(ArticleMeta, META_PROMPT))
    return r.parsed


def _ms(offset: str) -> int:
    return round(float(offset.rstrip("s")) * 1000)


def words_to_segments(words) -> list[Segment]:
    """Group word_info annotations into sentences, also splitting on long pauses."""
    segments: list[Segment] = []
    current: list = []
    for i, w in enumerate(words):
        current.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if nxt is None or w.text.endswith(SENTENCE_END) or _ms(nxt.start_offset) - _ms(w.end_offset) > PAUSE_MS:
            segments.append(Segment(start_ms=_ms(current[0].start_offset), end_ms=_ms(current[-1].end_offset),
                                    text=" ".join(x.text for x in current)))
            current = []
    return segments


async def transcribe(audio: bytes, mime_type: str = "audio/mp3") -> list[Segment]:
    async with _aio() as c:
        r = await c.interactions.create(
            model=TRANSCRIBE_MODEL,
            input=[{"type": "audio", "data": base64.b64encode(audio).decode(), "mime_type": mime_type}],
            generation_config={"transcription_config": {
                "mode": {"type": "verbatim", "timestamp_granularities": ["word"]},
            }},
            store=False,  # don't keep users' voice recordings server-side
        )
    words = [a for step in r.steps for part in (getattr(step, "content", None) or [])
             for a in (getattr(part, "annotations", None) or []) if a.type == "word_info"]
    return words_to_segments(words)
