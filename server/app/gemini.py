"""Every Gemini call the app makes, through the google-genai SDK.

Models are chosen per job:
- MODEL: reads the action timeline + screenshots and decides the steps (multimodal, the hard part); for uploaded
  videos it also finds the actions in the video and locates them on screen
- LITE_MODEL: title/intro/outro from the finished steps (short, text-only)
- TRANSCRIBE_MODEL: narration with exact word timings (served only through the Interactions API)
- TTS_MODEL: the video's voiceover, one clip per scene (Interactions API)
"""

import base64

from google import genai
from google.genai import types
from google.genai.client import AsyncClient

from app.models import (
    ArticleMeta,
    FoundActions,
    LocatedFrames,
    Narration,
    Segment,
    SensitiveFrames,
    StepsDraft,
    TDoc,
)

MODEL = "gemini-3.8-flash"
LITE_MODEL = "gemini-3.5-flash-lite"
TRANSCRIBE_MODEL = "gemini-3.5-transcribe"
TTS_MODEL = "gemini-3.8-flash-tts"

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


FIND_PROMPT = """You watch a screen recording of someone using software and list every action they take, in order.

An action is a click on something (a button, link, field, menu item, tab, checkbox), finishing typing into a field,
or pressing Enter. List each one with the moment it happens: when the click lands, or when the typing ends.
Use the narration, if any, only to understand intent; list only actions you can see.
- label: the element's visible text, label or placeholder, exactly as on screen.
- Skip scrolling, mouse movement without clicks, and accidental clicks on empty space.
- Never write out passwords, emails or other personal data in value."""

SENSITIVE_RULES = """a box around EVERY piece of personal or secret information visible anywhere in the image, so it
can be blurred before the screenshot is published: email addresses; phone numbers; people's names (not company or
product names); usernames and handles such as first.last or @name, wherever they appear (owners, "edited by", activity,
certificates); profile photos, avatars and avatar initials; street addresses; passwords and password fields (even masked);
card, bank account and ID numbers; API keys, tokens and secrets; dates of birth. Include text inside fields,
tables, headers and menus. When unsure, include it: a missed item leaks data, an extra blur costs nothing.
Empty only if there is nothing personal or secret in the image."""

LOCATE_PROMPT = f"""Each image is a frame from a screen recording at the moment of one action, introduced by a line
describing it. The description was guessed from the video and its label may be wrong. The mouse pointer (arrow, hand
or text cursor), when visible, is on the element really acted on: trust the pointer over the label.
For every image, in order, return:
- box: the element acted on (the one under the pointer), as [ymin, xmin, ymax, xmax] scaled 0-1000. Box the whole
  control (button, field, tab, menu item, icon), not just a word inside it.
- label: that element's visible text exactly as on screen, or a 2-4 word description if it's an icon
  (e.g. "plus icon next to Terms").
- pointer: [y, x] of the mouse pointer's tip, scaled 0-1000, or [] if no pointer is visible.
- sensitive: {SENSITIVE_RULES}
Return exactly one entry per image."""

SENSITIVE_PROMPT = f"""Each image is a frame from a screen recording. For every image, in order, return {SENSITIVE_RULES}
Boxes are [ymin, xmin, ymax, xmax] scaled 0-1000. Return exactly one list per image."""

NARRATION_PROMPT = """You write the voiceover for a short product tutorial video, one passage per step.

The user message lists the finished help-article steps in order (`[step n] text`, then the screenshot of that
moment). Lines like `time narrator: "..."` are what the presenter actually said while recording, in time order.

For each step, write what the narrator says while that step happens on screen:
- Spoken, second person, present tense, friendly and plain ("Now open Settings and pick Billing.").
- 1-2 sentences, at most 30 words. Name the UI label the viewer will see, but use no markdown.
- Keep the presenter's reasons and tips; drop fillers, false starts, repetition and anything off-topic.
  People talk before, during or after the action they mean, so match speech to steps by meaning, not position.
- Only describe what the steps and screenshots show. Never invent buttons, menus or values.
- Write in the language the presenter spoke (English if they didn't speak), and return its BCP-47 code as lang.
- Return one entry per step; step is the step number."""

TRANSLATE_PROMPT = """You translate a product help article and its video narration.

Translate every field of the JSON into the target language. Keep every id unchanged. Keep **bold** and `code`
markers. Never translate the words in the "keep" list, nor UI labels inside **...** (the product's interface is not
translated). Use the tone of a product help center: clear, friendly, natural for native speakers."""


async def find_actions(video: bytes, fps: int = 2) -> FoundActions | None:
    """Watch an uploaded screen recording and list the actions in it (with timestamps)."""
    part = types.Part(inline_data=types.Blob(data=video, mime_type="video/mp4"),
                      video_metadata=types.VideoMetadata(fps=fps))  # clicks need finer timing than the 1 fps default
    async with _aio() as c:
        r = await c.models.generate_content(model=MODEL, contents=types.Content(role="user", parts=[part]),
                                            config=_json(FoundActions, FIND_PROMPT))
    return r.parsed


async def locate(frames: list[bytes], descriptions: list[str]) -> LocatedFrames | None:
    """For each action's screenshot, find the element acted on and anything that should be blurred."""
    parts: list[types.Part] = []
    for n, (jpeg, what) in enumerate(zip(frames, descriptions, strict=True), 1):
        parts += [types.Part.from_text(text=f"Image {n}: {what}"), types.Part.from_bytes(data=jpeg, mime_type="image/jpeg")]
    async with _aio() as c:
        r = await c.models.generate_content(model=MODEL, contents=types.Content(role="user", parts=parts),
                                            config=_json(LocatedFrames, LOCATE_PROMPT))
    return r.parsed


async def find_sensitive(frames: list[bytes]) -> SensitiveFrames | None:
    """Sensitive boxes on frames between actions, so blurring covers the whole uploaded video."""
    parts: list[types.Part] = []
    for n, jpeg in enumerate(frames, 1):
        parts += [types.Part.from_text(text=f"Image {n}"), types.Part.from_bytes(data=jpeg, mime_type="image/jpeg")]
    async with _aio() as c:
        r = await c.models.generate_content(model=MODEL, contents=types.Content(role="user", parts=parts),
                                            config=_json(SensitiveFrames, SENSITIVE_PROMPT))
    return r.parsed


async def write_narration(parts: list[types.Part]) -> Narration | None:
    async with _aio() as c:
        r = await c.models.generate_content(
            model=MODEL, contents=types.Content(role="user", parts=parts), config=_json(Narration, NARRATION_PROMPT))
    return r.parsed


async def translate(doc: TDoc, lang: str, keep: list[str]) -> TDoc | None:
    prompt = f"Target language: {lang}\nKeep: {keep}\n\n{doc.model_dump_json()}"
    async with _aio() as c:
        r = await c.models.generate_content(model=MODEL, contents=prompt, config=_json(TDoc, TRANSLATE_PROMPT))
    return r.parsed


async def speak(text: str, voice: str, style: str) -> bytes:
    """One narration clip: WAV, 24 kHz mono 16-bit. store=False: users' scripts and voices aren't kept."""
    async with _aio() as c:
        r = await c.interactions.create(
            model=TTS_MODEL, store=False, response_format={"type": "audio"},
            input=[{"type": "user_input", "content": [{
                "type": "text", "text": text, "annotations": [{"type": "speech_metadata", "style": style}]}]}],
            generation_config={"speech_config": [{"voice": voice}]},
        )
    return base64.b64decode(r.output_audio.data)


async def make_voice_key(sample_wav: bytes, consent_wav: bytes) -> str:
    """A stateless voice key for the user's own voice (Google keeps nothing; the key expires in 7 days)."""
    b64 = lambda data: {"mime_type": "audio/wav", "data": base64.b64encode(data).decode()}  # noqa: E731
    async with _aio() as c:
        v = await c.voices.create(store=False, voice={
            "model": TTS_MODEL, "type": "replicated", "display_name": "Stepcast",
            "replicated": {"source_audio": b64(sample_wav), "consent_audio": b64(consent_wav)}})
    return v.key


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
