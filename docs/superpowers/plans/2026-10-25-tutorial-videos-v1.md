# Tutorial Videos v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn each Stepcast recording into a narrated, in-sync tutorial video (AI or own voice, zoom, captions,
blur) alongside the article, in any number of languages, exported as a docs-site zip, self-hosted with one command.

**Architecture:** The existing pipeline still produces the article. A new **video job** then writes spoken narration
per step and synthesizes one voice clip per step with Gemini TTS. A pure timing function fits the recorded video
around each clip, and ffmpeg renders one cached segment per scene and joins them. Caching is content-addressed (file
names are hashes of their inputs), so editing one sentence regenerates one clip and one segment. Translations are
extra text versions of the article that go through the same video job.

**Tech Stack:**
- server: Python 3.11+, FastAPI, SQLite, Pillow, ffmpeg (CLI), google-genai ≥ 2.33;
- web: React 19 + Vite + vitest;
- extension: Chrome MV3 (`node --test` + jsdom);
- e2e: Playwright;
- packaging: Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-25-tutorial-videos-v1-design.md`. Read it first. It builds on
`docs/superpowers/specs/2026-10-25-help-articles-v1-design.md`.

## Global Constraints

- **Founder's rule: simplest approach that works.** No new Python or npm dependencies except where a task names one.
  ffmpeg is the only renderer; no Remotion.
- **Models (constants in `server/app/gemini.py`):**
  - `MODEL = "gemini-3.8-flash"` for narration, translation and finding sensitive boxes;
  - `LITE_MODEL = "gemini-3.5-flash-lite"` (existing);
  - `TRANSCRIBE_MODEL = "gemini-3.5-transcribe"` (existing);
  - `TTS_MODEL = "gemini-3.8-flash-tts"` (new).
- **Gemini calls that send user audio or voice use `store=False`.** Own voice uses the stateless voice key
  (`client.voices.create(store=False, ...)` → `voice.key`, `voicekey_...`, 7-day TTL).
- **TTS output:** WAV, 24 kHz, mono, 16-bit, via `client.aio.interactions.create(model=TTS_MODEL, ...,
  response_format={"type": "audio"}, generation_config={"speech_config": [{"voice": <name|key>}]})`. Audio bytes are
  `base64.b64decode(r.output_audio.data)`. Style goes in a `speech_metadata` annotation, never in the text.
- **The video is fitted to the voice, never the voice to the video.** Every click must land inside its scene's
  narration: at least `LEAD_MS = 400` after the clip starts and before it ends.
- **Speed-ups never exceed `MAX_SPEED = 3.0`.** Longer stretches are cut.
- **Output video:** H.264 + AAC, 30 fps, at most 1920×1080 (keep the recording's aspect ratio, even dimensions),
  `-crf 26 -preset veryfast -tune stillimage`, `+faststart`. Target ≤ 20 MB for 2 minutes.
- **Never send personal data:** narration and translation inputs are step text plus screenshots that are already
  blurred, as today.
- **Long ffmpeg/Pillow work runs in `asyncio.to_thread`** (existing rule: never block the event loop).
- **Commit scope:** each task commits only its own files. Commit messages end with the session's attribution lines.
- **Copy rules:** plain, friendly UI text, no jargon. Errors say what happened and what to do.

## Review Focus

1. **Steps reordered in the article.** The video still plays scenes in recorded order (by each step's first event
   time). Test in Task 7.
2. **A scene's narration cleared to empty.** The scene shows its action for at least 1.5 s with no voice, and TTS is
   never called with empty text. Tests in Tasks 2 and 5.
3. **TTS or ffmpeg failing mid-render.** The video goes to `failed` with a readable error, and the previous finished
   `video.<lang>.mp4` is still served. Test in Task 7.
4. **Deleting an article while a video renders.** Returns 409, the same rule as while processing. Test in Task 7.
5. **A step with no translation** (added or merged after translating). The translated video gives it no voice
   rather than speaking the source language, and the step is listed as stale. Test in Task 9.

---

## File map

**Server (`server/app/`):**
- `models.py`: `Step.narration`, `hold_ms` and `video_zoom`; `RecEvent` kind `"redact"`; `VideoState`, `TStep`,
  `Translation`; `Article.lang`, `voice`, `videos`, `translations` and the computed `stale`.
- `store.py`: `update(article_id, change)` under a lock.
- `scenes.py` (new): the pure timing (spans, scene plan, sync check).
- `captions.py` (new): cues, VTT, SRT, caption images.
- `settings.py` (new): `settings.json` (glossary, own-voice key).
- `voice.py` (new): voice list, speakable text, cached clips, own-voice setup and key refresh.
- `gemini.py`: `write_narration`, `speak`, `make_voice_key`, `translate`, `find_sensitive`.
- `steps.py`: `narration_parts`.
- `media.py`: `blur_windows`, `clean_video`, `render_scene`, `concat`, `burn_captions`, `audio_ms`, `to_wav`.
- `video.py` (new): the video job (`make`, `render`).
- `translate.py` (new): add, update and save translations; `source_hash`.
- `pipeline.py`: saves narration segments; starts `video.make`.
- `upload.py`: sensitive-box samples between actions.
- `export.py`: the docs zip.
- `api.py`: new endpoints; serves `web/dist`.

**Server tests (`server/tests/unit/`):**
- new: `test_scenes.py`, `test_captions.py`, `test_voice.py`, `test_video.py`, `test_translate.py`, `test_export.py`;
- extended: existing files plus `tests/integration/test_live.py`.

**Web (`web/src/`):**
- `api.ts`;
- `VideoView.tsx` (new);
- `Settings.tsx` (new: voice setup and glossary);
- `LanguageMenu.tsx` (new);
- `Editor.tsx`, `Library.tsx`, `ShareMenu.tsx`, `stepOps.ts`, `index.css`;
- `videoEdits.ts` and `videoEdits.test.ts` (new);
- `web/vite.config.ts`.

**Extension:**
- `content.js`: redaction snapshots;
- `options.html` and `options.js` (new);
- `background.js`, `offscreen.js`, `manifest.json`;
- `test/content.test.mjs`.

**Packaging:** `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `README.md`.

---

### Task 0: Voice and capture check (spike, founder listens)

Verifies the spec's "To verify early" items before anything is built on them. Throwaway apart from the script, which
is kept for future voice reviews.

**Files:**
- Create: `server/scripts/voice_samples.py`
- Modify: `docs/superpowers/specs/2026-10-25-tutorial-videos-v1-design.md` (add a "Decided during build" section)

- [ ] **Step 1: Write `server/scripts/voice_samples.py`**

  Run as `uv run python scripts/voice_samples.py <out_dir> [--mine sample.wav consent.wav]`. It synthesizes each of
  these lines with each candidate voice, using the TTS call from Global Constraints and the style `"a calm, friendly
  product-tour narrator speaking at a natural, unhurried pace"`:
  - **English:** "Click Glossary in the left navigation to see all your business glossaries." /
    "Expand Atlan Corporate Glossary, then open Business Definitions to see its terms." /
    "Click Save, and the term is now linked to this table."
  - **Spanish and German:** the same three lines, translated with one `gemini-3.8-flash` call.
  - **Candidate voices:** Achird, Sulafat, Charon, Aoede, Iapetus, Kore, Schedar, Vindemiatrix.

  It writes `<out_dir>/<voice>.<lang>.<n>.wav` and prints each call's latency and audio length.

  With `--mine`, it converts both clips to 24 kHz mono WAV with ffmpeg, creates a stateless key with
  `client.voices.create(store=False, voice={"model": TTS_MODEL, "type": "replicated", "display_name": "Stepcast",
  "replicated": {"source_audio": {...}, "consent_audio": {...}}})`, and synthesizes the same lines as `mine.*`.

- [ ] **Step 2: Run it**

  Run: `cd server && uv run python scripts/voice_samples.py ../tmp-voices`

  Expected: 72 WAVs (8 voices × 3 languages × 3 lines), no errors. Note the median latency per clip.

- [ ] **Step 3: Check the cursor in tab capture**

  Run: `cd e2e && node extension.test.mjs` (the existing real-extension test). Then extract a frame 100 ms before a
  logged click from the produced `server/data/<id>/video.mp4` with ffmpeg, and look at it.

  Expected: a finding, "cursor visible" or "cursor not visible". If not visible, Task 6 draws the click highlight; it
  draws it either way.

- [ ] **Step 4: Founder checkpoint (stop and ask)**

  Send the founder the WAV folder path. Ask them to:
  - pick 4–6 voices that don't sound robotic;
  - optionally run `--mine` with their own 20 s sample and the consent statement, and say whether their voice
    survives in Spanish and German.

  Do not continue until they answer.

- [ ] **Step 5: Record the decisions**

  Add a `## Decided during build` section to the spec with:
  - the chosen voices and the default (first);
  - the cursor finding;
  - the own-voice cross-language finding: if their voice fails or sounds wrong in other languages, translated
    videos use the default stock voice and say so (Task 7).

  Put the chosen voices in Task 5's `VOICES`.

- [ ] **Step 6: Commit** the script and the spec. `tmp-voices/` is not committed.

---

### Task 1: Data model and safe concurrent updates

**Files:**
- Modify: `server/app/models.py`, `server/app/store.py`, `server/app/api.py:107-124` (PUT)
- Test: `server/tests/unit/test_api.py`, `server/tests/unit/test_steps.py`

**Interfaces:**
- Produces:
  - **`Step` fields:** `narration: str = ""`, `hold_ms: int = 0`, `video_zoom: bool = True`.
  - **`RecEvent.kind`:** adds `"redact"`. It is not actionable, and its only payload is `redact` and `viewport`.
  - **`VideoState`:**
    - `status: Literal["none", "rendering", "ready", "failed"] = "none"`;
    - `stage: str = ""`;
    - `updating: list[str] = []` (step ids being regenerated);
    - `error: str = ""`;
    - `note: str = ""`;
    - `version: int = 0`.
  - **`TStep`:** `text: str`, `narration: str`, `src: str` (the source hash at translation time).
  - **`Translation`:** `title: str`, `intro: str`, `outro: str`, `steps: dict[str, TStep] = {}` (keyed by step id).
  - **`Article` additions:**
    - `lang: str = "en"`;
    - `voice: str = ""` (empty means the default voice);
    - `videos: dict[str, VideoState] = {}`;
    - `translations: dict[str, Translation] = {}`;
    - `@computed_field stale: dict[str, list[str]]`: for each translated language, the source step ids whose
      `source_hash` differs from the translated `src`, or that have no translation.
  - **`models.source_hash(s: Step) -> str`:** `sha1(f"{s.text}\0{s.narration}")`, first 10 hex characters.
  - **`store.update(article_id: str, change: Callable[[Article], Article]) -> Article | None`:** read, change and save
    under a module-level `threading.Lock`; returns `None` if the article is missing. Used by every writer from here
    on, so a background job never overwrites a user's edit or the reverse.
  - **`ArticleEdit` (PUT body):** adds `voice: str = ""` (`title`, `intro`, `outro`, `steps` as before). The PUT
    applies the edit with `store.update`, so `videos` and `translations` are never overwritten by an editor save.

- [ ] **Step 1: Write the failing tests**

```python
# test_steps.py
def test_stale_lists_changed_and_untranslated_steps():
    s1, s2 = Step(id="a", event_ids=[0], text="Click **Go**.", frame=0, narration="Click Go."), \
             Step(id="b", event_ids=[1], text="Save.", frame=1, narration="Save it.")
    a = Article(id="x", created_at="t", steps=[s1, s2], translations={"es": Translation(
        title="", intro="", outro="", steps={"a": TStep(text="Haz clic", narration="Haz clic", src=source_hash(s1))})})
    assert a.stale == {"es": ["b"]}
    a.steps[0] = s1.model_copy(update={"narration": "Click the Go button."})
    assert a.stale == {"es": ["a", "b"]}
    assert Article.model_validate_json(a.model_dump_json()).stale == a.stale  # round-trips despite the computed key

# test_api.py
def test_put_keeps_videos_and_translations(client, ready_article):
    store.update(ready_article.id, lambda a: a.model_copy(update={"videos": {"en": VideoState(status="ready", version=3)}}))
    r = client.put(f"/articles/{ready_article.id}", json={"title": "T", "intro": "", "outro": "", "steps": [
        s.model_dump() for s in ready_article.steps], "voice": "Sulafat"})
    assert r.status_code == 200
    a = store.get(ready_article.id)
    assert a.voice == "Sulafat" and a.videos["en"].version == 3
```

  If `test_api.py` has no `ready_article` fixture, add one beside `client` that saves a ready article with two steps
  and an `events.json` of two clicks.

- [ ] **Step 2: Run them to make sure they fail**

  Run: `cd server && uv run pytest tests/unit/test_steps.py tests/unit/test_api.py -q`

  Expected: FAIL (`ImportError` on `Translation` / `source_hash`, and the missing fixture or field).

- [ ] **Step 3: Implement the model fields, `source_hash`, `store.update`, and the PUT change**

- [ ] **Step 4: Run all unit tests**

  Run: `cd server && uv run pytest tests/unit -q && uv run ruff check app tests`

  Expected: all pass, no lint errors.

- [ ] **Step 5: Commit**

---

### Task 2: Scene timing (pure)

The core of the spec's "Sync" section. No I/O.

**Files:**
- Create: `server/app/scenes.py`
- Test: `server/tests/unit/test_scenes.py`

**Interfaces:**
- Produces:
  - **Constants:** `LEAD_MS = 400`, `TAIL_MS = 500`, `GAP_MS = 250`, `SETTLE_MS = 1200`, `MIN_AFTER_MS = 700`,
    `SILENT_MS = 1500`, `MAX_SPEED = 3.0`, `INTRO_MS = 2000`, `FRAME_MS = 34`.
  - **`Piece`** (frozen dataclass): `src_ms: int`, `src_end_ms: int`, `out_ms: int`. Plays source
    `[src_ms, src_end_ms)` in `out_ms`. `src_ms == src_end_ms` means freeze on that frame.
  - **`ScenePlan`** (frozen dataclass): `pieces: tuple[Piece, ...]`, `voice_at_ms: int`, `out_ms: int`,
    `clicks_at_ms: tuple[int, ...]` (click times in the scene's output).
  - **`scene_spans(click_groups: list[list[int]], duration_ms: int) -> list[tuple[int, int]]`:** one source span per
    scene. Groups are each scene's click times in recorded order, sorted by first click.
  - **`plan_scene(clicks_ms: list[int], span: tuple[int, int], clip_ms: int, hold_ms: int = 0) -> ScenePlan`.**
  - **`sync_errors(plans: list[ScenePlan], clip_ms: list[int], rendered_ms: list[int]) -> list[str]`:** empty when in
    sync. One message per broken rule:
    - a click outside `[voice_at + LEAD_MS, voice_at + clip_ms)` (skipped when `clip_ms == 0`);
    - a rendered scene's length differing from `out_ms` by more than `FRAME_MS`.

- [ ] **Step 1: Write the failing tests**

```python
def speed(p): return (p.src_end_ms - p.src_ms) / p.out_ms

def check(plan, clicks, span, clip, hold=0):
    assert sum(p.out_ms for p in plan.pieces) == plan.out_ms
    assert all(speed(p) <= MAX_SPEED + 1e-9 for p in plan.pieces)
    srcs = [(p.src_ms, p.src_end_ms) for p in plan.pieces]
    assert all(a[1] <= b[0] for a, b in zip(srcs, srcs[1:]))  # forward in time, never repeats
    assert all(span[0] <= a <= b <= span[1] for a, b in srcs)
    assert plan.out_ms >= plan.voice_at_ms + clip + TAIL_MS + hold
    if clip:
        assert all(plan.voice_at_ms + LEAD_MS <= c < plan.voice_at_ms + clip for c in plan.clicks_at_ms)
    assert len(plan.clicks_at_ms) == len(clicks)

@pytest.mark.parametrize("clicks,span,clip", [
    ([5000], (3000, 6200), 4000),          # narration longer than the action: freeze before the click
    ([20000], (2000, 21200), 3000),        # 18 s of waiting before a quick sentence: speed + cut
    ([4000, 4600, 9000], (2500, 10200), 6000),  # three clicks in one sentence
    ([100], (0, 1300), 2500),              # click at the very start of the video
])
def test_plan_keeps_every_click_inside_its_sentence(clicks, span, clip):
    check(plan_scene(clicks, span, clip), clicks, span, clip)

def test_hold_adds_time_after_the_narration():
    a, b = plan_scene([5000], (3000, 6200), 3000), plan_scene([5000], (3000, 6200), 3000, hold_ms=1000)
    assert b.out_ms == a.out_ms + 1000

def test_empty_narration_still_shows_the_action():
    p = plan_scene([5000], (3000, 6200), 0)
    assert p.out_ms >= SILENT_MS and p.clicks_at_ms[0] < p.out_ms

def test_cut_keeps_the_moments_right_before_the_click():
    p = plan_scene([20000], (2000, 21200), 3000)
    pre = [q for q in p.pieces if q.src_end_ms <= 20000]
    assert pre[-1].src_end_ms == 20000 and pre[0].src_ms > 2000  # the start of the wait was cut, not the approach

def test_spans_cover_recorded_order_and_skip_the_intro():
    spans = scene_spans([[41000], [47000, 47500], [60000]], 143000)
    assert spans[0][0] == 41000 - INTRO_MS
    assert all(a[1] == b[0] for a, b in zip(spans, spans[1:]))  # contiguous
    assert spans[1][0] == 41000 + SETTLE_MS and spans[-1][1] == 60000 + 2 * SETTLE_MS
    assert scene_spans([[300]], 1000) == [(0, 1000)]  # clamped to the video

def test_sync_errors():
    p = plan_scene([5000], (3000, 6200), 4000)
    assert sync_errors([p], [4000], [p.out_ms + 20]) == []
    assert sync_errors([p], [4000], [p.out_ms + 200])  # rendered length drifted
    bad = ScenePlan(p.pieces, p.voice_at_ms, p.out_ms, (p.voice_at_ms + 100,))
    assert sync_errors([bad], [4000], [p.out_ms])      # click before the lead-in
```

- [ ] **Step 2: Run to make sure they fail**

  Run: `cd server && uv run pytest tests/unit/test_scenes.py -q`

  Expected: FAIL (`ModuleNotFoundError: app.scenes`).

- [ ] **Step 3: Implement `app/scenes.py`**

  **`scene_spans`:**
  - scene 0 starts at `max(0, first_click - INTRO_MS)`;
  - scene `i > 0` starts at `prev_last + min(SETTLE_MS, (first_i - prev_last) // 2)`, and scene `i - 1` ends there;
  - the last scene ends at `min(duration_ms, last_click + 2 * SETTLE_MS)`;
  - everything is clamped to `[0, duration_ms]`.

  **`plan_scene`**, with `k` clicks, `v = GAP_MS` (the voice start), `c = clip_ms`:
  1. **Click targets in the output:**
     - with narration: `T_j = v + max(LEAD_MS, round(c * (0.35 + 0.5 * j / k)))`, capped at `v + c - 200`, then
       made strictly increasing with at least 300 ms between targets;
     - with `c == 0`: `T_j = 600 + 400 * j`.
  2. **Scene length:**
     - `out = max(v + c + TAIL_MS, T_last + MIN_AFTER_MS) + hold_ms`;
     - with `c == 0`, `out = max(SILENT_MS, T_last + MIN_AFTER_MS) + hold_ms`.
  3. **Anchors:** source `[span0, click_1..click_k, span1]` against output `[0, T_1..T_k, out]`. For each pair, with
     `src` = the source gap and `dur` = the output gap:
     - **`src <= dur`:** play at 1×, padded with a freeze. Before a click, the freeze comes first (on the gap's first
       frame) and then the gap plays into the click. After the last click, the gap plays first and then freezes on
       its last frame.
     - **`src / dur <= MAX_SPEED`:** one sped-up piece.
     - **Otherwise:** keep `dur * MAX_SPEED` of source at `MAX_SPEED` and cut the rest. Before a click, keep the
       stretch ending at the click; after the last click, keep the stretch starting at it.
  4. **Rounding:** each piece's `out_ms` is an int, and the rounding remainder is added to the last piece, so the sum
     equals `out` exactly.

- [ ] **Step 4: Run the tests**

  Run: `cd server && uv run pytest tests/unit/test_scenes.py -q`

  Expected: PASS.

- [ ] **Step 5: Commit**

---

### Task 3: Captions

**Files:**
- Create: `server/app/captions.py`
- Test: `server/tests/unit/test_captions.py`

**Interfaces:**
- Produces:
  - **`Cue`** (frozen dataclass): `start_ms: int`, `end_ms: int`, `text: str` (at most two lines joined by `"\n"`).
  - **`cues(lines: list[tuple[int, int, str]]) -> list[Cue]`:** one tuple per scene: `(voice start in the final
    video, clip_ms, narration)`. It wraps words into lines of at most `LINE = 42` characters, two lines per cue, and
    times cues within the clip in proportion to their characters. Empty narration produces no cues.
  - **`to_vtt(cues) -> str`** and **`to_srt(cues) -> str`.**
  - **`speakable(text: str) -> str`:** strips `**` and backticks and collapses whitespace. Used for captions here and
    for TTS input in Task 5.
  - **`caption_png(text: str, width: int) -> PIL.Image.Image`:** RGBA, white text centred on a rounded
    `rgba(0,0,0,0.72)` box. Font size `max(18, width // 40)` via `ImageFont.load_default(size=...)`. The image is
    `width` wide and as tall as its box plus margin. Used for burned-in captions.

- [ ] **Step 1: Write the failing tests**

```python
def test_cues_wrap_split_and_stay_inside_the_clip():
    long = "Click Link assets to search for the tables you want and connect them to this glossary term in one go."
    cs = cues([(250, 6000, long), (7000, 0, ""), (8000, 2000, "Click **Save**.")])
    assert all(len(line) <= 42 for c in cs for line in c.text.split("\n"))
    assert all(c.text.count("\n") <= 1 for c in cs)
    first = [c for c in cs if c.start_ms < 7000]
    assert first[0].start_ms == 250 and first[-1].end_ms == 6250 and len(first) == 2
    assert cs[-1].text == "Click Save."  # markdown stripped; empty narration made no cue
    assert all(a.end_ms <= b.start_ms for a, b in zip(cs, cs[1:]))

def test_vtt_and_srt_formats():
    cs = [Cue(250, 61500, "Hello\nthere")]
    assert to_vtt(cs) == "WEBVTT\n\n00:00:00.250 --> 00:01:01.500\nHello\nthere\n"
    assert to_srt(cs) == "1\n00:00:00,250 --> 00:01:01,500\nHello\nthere\n"

def test_caption_png_is_transparent_outside_the_box():
    img = caption_png("Click Save.", 1280)
    assert img.mode == "RGBA" and img.width == 1280 and img.getpixel((0, 0))[3] == 0
```

- [ ] **Step 2: Run to make sure they fail.** `cd server && uv run pytest tests/unit/test_captions.py -q` → FAIL.
- [ ] **Step 3: Implement `app/captions.py`.**
- [ ] **Step 4: Run the tests** → PASS.
- [ ] **Step 5: Commit**

---

### Task 4: Gemini calls

**Files:**
- Modify: `server/app/gemini.py`, `server/app/models.py` (schemas), `server/app/steps.py`
- Test: `server/tests/unit/test_steps.py`, `server/tests/integration/test_live.py`

**Interfaces:**
- Produces, in `models.py`:
  - `SceneLine(step: int, narration: str)`;
  - `Narration(lang: str, scenes: list[SceneLine])`, where `lang` is the BCP-47 code of the spoken language, `"en"`
    when silent;
  - `TItem(id: str, text: str, narration: str)`;
  - `TDoc(title: str, intro: str, outro: str, steps: list[TItem])`;
  - `SensitiveFrames(frames: list[list[list[int]]])`: per frame, `[ymin, xmin, ymax, xmax]` boxes (0–1000).
- Produces, in `gemini.py`:
  - `TTS_MODEL = "gemini-3.8-flash-tts"`;
  - **`NARRATION_PROMPT`**, with these rules:
    - spoken, second person, present tense;
    - 1–2 sentences and at most 30 words per step;
    - names the UI label the viewer will see, but no markdown;
    - keeps the presenter's reasons and tips, drops fillers and false starts;
    - never invents UI;
    - written in the language the presenter spoke;
    - one entry per step, `step` = the 1-based step number.
  - **`async def write_narration(parts: list[types.Part]) -> Narration | None`** (`MODEL`, `_json(Narration, ...)`).
  - **`async def speak(text: str, voice: str, style: str) -> bytes`:** WAV bytes, using the TTS call from Global
    Constraints with `store=False` and `annotations=[{"type": "speech_metadata", "style": style}]`.
  - **`async def make_voice_key(sample_wav: bytes, consent_wav: bytes) -> str`:** `client.aio.voices.create(
    store=False, voice={...replicated...})`, returning `.key`.
  - **`TRANSLATE_PROMPT`:** translate every field into `lang`; keep ids; keep `**bold**` and `` `code` ``; never
    translate the terms in the "keep" list, nor text inside `**...**` when it is a UI label from an untranslated
    product. Tone matches a product help center.
  - **`async def translate(doc: TDoc, lang: str, keep: list[str]) -> TDoc | None`.**
  - **`async def find_sensitive(frames: list[bytes]) -> SensitiveFrames | None`:** reuses the sensitive-data rules
    from `LOCATE_PROMPT`, moved into a shared `SENSITIVE_RULES` string so both prompts use the same list.
- Produces, in `steps.py`:
  - **`narration_parts(steps: list[Step], events: list[RecEvent], segments: list[Segment], frames_dir: Path) ->
    list[types.Part]`:** for each step in recorded order, the line `[step n] <article text>` plus its `{frame}_full.png`
    as JPEG. Narrator lines are interleaved by time before the step whose first event follows them, as `build_parts`
    does.

- [ ] **Step 1: Write the failing test**

```python
def test_narration_parts_orders_by_recorded_time_and_interleaves_speech(tmp_path):
    for i in range(2):
        Image.new("RGB", (32, 20)).save(tmp_path / f"{i}_full.png")
    evs = [ev(t=1000), ev(t=5000)]
    steps = [Step(id="b", event_ids=[1], text="Save.", frame=1), Step(id="a", event_ids=[0], text="Open.", frame=0)]
    parts = narration_parts(steps, evs, [Segment(start_ms=3000, end_ms=4000, text="now save it")], tmp_path)
    texts = [p.text for p in parts if p.text]
    assert texts == ["[step 1] Open.", '3.0s narrator: "now save it"', "[step 2] Save."]
```

- [ ] **Step 2: Run to make sure it fails.** `cd server && uv run pytest tests/unit/test_steps.py -q` → FAIL.
- [ ] **Step 3: Implement the schemas, the prompts and the five calls.** Use `async with _aio() as c:` as the existing
  calls do.
- [ ] **Step 4: Add live tests** in `tests/integration/test_live.py` (skipped without a key):
  - `speak("Click Save.", "Achird", STYLE)` returns RIFF/WAV bytes longer than 0.3 s;
  - `translate` of a two-step `TDoc` into `"es"` keeps both ids and keeps a `keep` word untouched;
  - `write_narration` on the existing synthetic two-frame fixture returns 2 scenes with non-empty text and no `**`.
- [ ] **Step 5: Run.** `cd server && uv run pytest tests/unit -q && uv run pytest tests/integration -q` → PASS
  (integration needs `GEMINI_API_KEY`).
- [ ] **Step 6: Commit**

---

### Task 5: Voices and settings

**Files:**
- Create: `server/app/settings.py`, `server/app/voice.py`
- Modify: `server/app/media.py` (`to_wav`, `audio_ms`)
- Test: `server/tests/unit/test_voice.py`

**Interfaces:**
- Consumes: `gemini.speak`, `gemini.make_voice_key` (Task 4).
- Produces:
  - **`settings.Settings`:** `glossary: list[str] = []`, `my_voice_key: str = ""`, `my_voice_created: str = ""` (ISO).
    `settings.load() -> Settings` and `settings.save(s) -> None` use `store.DATA_DIR / "settings.json"`, resolved at
    call time so tests can redirect it.
  - **`voice.VOICES: dict[str, str]`:** name → label, from Task 0. `voice.DEFAULT_VOICE` = its first key.
    `voice.MINE = "mine"`.
  - **`voice.STYLE`** = the Task 0 style string.
  - **`async def voice.clip(d: Path, text: str, voice: str) -> Path`:**
    - `""` means `DEFAULT_VOICE`;
    - the clip is cached at `d / "voice" / f"{sha1(voice + '\0' + captions.speakable(text))[:16]}.wav"`;
    - Gemini is only called on a cache miss;
    - raises `ValueError` for empty text.
  - **`async def voice.resolve(voice: str) -> str`:**
    - a stock name, or `""`, resolves to the name;
    - `"mine"` resolves to the saved key, re-created with `gemini.make_voice_key` from `DATA_DIR/my_voice/sample.wav`
      and `consent.wav` when it is 6 or more days old;
    - raises `LookupError("Set up your voice first.")` when `"mine"` isn't set up.

    The cache key uses the name `"mine"`, not the rotating key, so a key refresh doesn't invalidate cached clips.
  - **`voice.my_voice_ready() -> bool`.**
  - **`async def voice.set_up_my_voice(sample: bytes, consent: bytes) -> None`:** converts both with
    `media.to_wav(src, dst)` (24 kHz mono s16), then creates the key. On rejection it raises
    `ValueError("Gemini couldn't verify the consent recording. Read the statement exactly, in the same place as the
    sample, and try again.")` and saves nothing.
  - **`voice.forget_my_voice() -> None`:** deletes the files and the key.
  - **`media.to_wav(src: Path, dst: Path) -> None`** and **`media.audio_ms(path: Path) -> int`.**

- [ ] **Step 1: Write the failing tests** (monkeypatch `gemini.speak` and `gemini.make_voice_key`, and point
  `store.DATA_DIR` at `tmp_path`):

```python
def test_clip_is_cached_by_voice_and_text(tmp_path, monkeypatch):
    calls = []
    async def fake_speak(text, v, style): calls.append((text, v)); return wav_bytes(500)
    monkeypatch.setattr(voice.gemini, "speak", fake_speak)
    a = asyncio.run(voice.clip(tmp_path, "Click **Save**.", ""))
    b = asyncio.run(voice.clip(tmp_path, "Click **Save**.", ""))
    c = asyncio.run(voice.clip(tmp_path, "Click **Save**.", "Sulafat"))
    assert a == b != c and calls == [("Click Save.", voice.DEFAULT_VOICE), ("Click Save.", "Sulafat")]
    with pytest.raises(ValueError):
        asyncio.run(voice.clip(tmp_path, "  ", ""))

def test_my_voice_key_is_refreshed_when_old(tmp_path, monkeypatch):
    ...  # set_up_my_voice with fake key "voicekey_1"; resolve("mine") == "voicekey_1" with no new call;
         # set my_voice_created to 6 days ago; resolve("mine") makes one new key; forget_my_voice → resolve raises LookupError

def test_rejected_consent_saves_nothing(tmp_path, monkeypatch):
    ...  # make_voice_key raises → ValueError with the message above; my_voice_ready() is False; no files left
```

  `wav_bytes(ms) -> bytes` (a silent WAV built with the `wave` module) goes in a new `server/tests/unit/helpers.py`,
  imported as `from tests.unit.helpers import wav_bytes`. Task 7 reuses it.

- [ ] **Step 2: Run to make sure they fail.** `cd server && uv run pytest tests/unit/test_voice.py -q` → FAIL.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run the tests** → PASS.
- [ ] **Step 5: Commit**

---

### Task 6: Rendering with ffmpeg

**Files:**
- Modify: `server/app/media.py`
- Test: `server/tests/unit/test_media.py`

**Interfaces:**
- Consumes: `ScenePlan`/`Piece` (Task 2), `Cue`/`caption_png` (Task 3), `content_box`, `scale_rect`, `HIGHLIGHT`
  (existing).
- Produces:
  - **`blur_windows(events: list[RecEvent], duration_ms: int) -> list[tuple[int, int, Rect]]`:**
    - each event's `redact` boxes (any kind, including `"redact"`) apply from its `t` until the next event's `t`;
    - the first event's boxes also apply from 0;
    - the last event's boxes apply until `duration_ms`.
  - **`clean_video(video: Path, events: list[RecEvent], dst: Path) -> None`.** One pass on the source timeline,
    with the content box cropped as `render_frames` does:
    - Gaussian-style blur (`boxblur=12`) over each window's rect via crop + overlay with
      `enable='between(t,a,b)'`;
    - a 4 px `HIGHLIGHT` `drawbox` around each actionable event's rect from `t - 600` to `t + 900` ms.

    Long graphs go through `-filter_complex_script`. The output is lossless enough to cut again (`-crf 16`), and
    keeps the audio-free video only.
  - **`render_scene(clean: Path, plan: ScenePlan, clip: Path | None, zoom: Rect | None, dst: Path) -> None`.**
    1. **Pieces:** each piece becomes `trim` + `setpts` at its speed; a freeze is a one-frame trim with `tpad` or
       `loop` to `out_ms`. Pieces are joined with the `concat` filter.
    2. **Zoom** (when `zoom` is set):
       - eases in over 400 ms, ending at the first click;
       - holds;
       - eases out over the last 400 ms;
       - factor `Z = clamp(min(W / (3 * zoom.w), H / (3 * zoom.h)), 1.0, 2.0)`, centred on the rect and clamped to
         the frame;
       - implemented as `scale=...:eval=frame` followed by `crop` with per-frame `x`/`y`, so the output size is
         fixed.
    3. **Output size:** scaled to fit 1920×1080, even dimensions.
    4. **Audio:** silence for `voice_at_ms`, then the clip, then silence to `out_ms`. AAC 48 kHz mono, 96 kbps.
       With no clip, silence throughout.
    5. **Encoding:** the settings from Global Constraints.
  - **`concat(parts: list[Path], dst: Path) -> None`:** concat demuxer, `-c copy`, `+faststart`. Writes to
    `dst.with_suffix(".tmp.mp4")`, then renames, so a failure never replaces a good video.
  - **`burn_captions(video: Path, cues: list[Cue], dst: Path) -> None`:** each cue's `caption_png` is overlaid at
    the bottom centre with an `enable` window. No libass needed.
  - **`video_ms(path: Path) -> int`:** the video stream's duration from ffprobe.

- [ ] **Step 1: Write the failing tests** (synthetic input: `testsrc=size=640x400:rate=30:duration=6` plus a 1 s WAV
  of a sine tone from `sine=frequency=440:duration=1`):

```python
def test_render_scene_matches_the_plan_length_and_has_audio(tmp_path):
    plan = plan_scene([3000], (1000, 4200), 1000)
    render_scene(src, plan, tone, Rect(x=300, y=180, w=40, h=20), tmp_path / "s.mp4")
    assert abs(video_ms(tmp_path / "s.mp4") - plan.out_ms) <= FRAME_MS
    assert has_audio_stream(tmp_path / "s.mp4")

def test_freeze_piece_repeats_one_frame(tmp_path):
    ...  # plan with a long clip so a freeze exists; frames sampled at two times inside the freeze are identical
         # (ImageChops.difference(...).getbbox() is None)

def test_zoom_enlarges_the_clicked_area(tmp_path):
    ...  # source: black frame with a white 40x20 box at the zoom rect; at the click time in the output, the white
         # area covers more pixels than in the source frame (count pixels > 200)

def test_clean_video_blurs_only_inside_the_window(tmp_path):
    ...  # noise source (as the existing blur test does); one redact event at t=1000 and a click at t=3000:
         # the box region at 1.5 s has much lower variance than the same region at 0.5 s in a clean_video without
         # that event; outside the box, frames are unchanged

def test_concat_failure_keeps_the_old_file(tmp_path):
    good = tmp_path / "v.mp4"; good.write_bytes(b"old")
    with pytest.raises(subprocess.CalledProcessError):
        concat([tmp_path / "missing.mp4"], good)
    assert good.read_bytes() == b"old"

def test_blur_windows_cover_the_whole_video():
    evs = [ev(t=1000, redact=[R1]), ev(t=4000, kind="redact", redact=[R2]), ev(t=6000)]
    assert blur_windows(evs, 8000) == [(0, 4000, R1), (4000, 6000, R2)]

def test_burn_captions_changes_only_the_bottom(tmp_path):
    ...  # burn one cue over 0-1000 ms; top half of a frame at 0.5 s is unchanged, bottom area differs; at 1.5 s nothing differs
```

- [ ] **Step 2: Run to make sure they fail.** `cd server && uv run pytest tests/unit/test_media.py -q` → FAIL.
- [ ] **Step 3: Implement the functions.** Each builds an ffmpeg argument list run through the existing `_run`.
- [ ] **Step 4: Run the tests** → PASS.
- [ ] **Step 5: Commit**

---

### Task 7: The video job, API, and pipeline hook

**Files:**
- Create: `server/app/video.py`
- Modify: `server/app/pipeline.py`, `server/app/api.py`
- Test: `server/tests/unit/test_video.py`, `server/tests/unit/test_api.py`, `server/tests/unit/test_pipeline.py`

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces:
  - **The pipeline saves narration segments** to `d / "narration.json"` (a list of `Segment` dicts, `[]` when there
    is no speech). At the end of `process`, after the article is saved as ready, it calls
    `await video.make(article_id)`. The video's status lives in `Article.videos`, so the article is editable while
    the video is made.
  - **`async def video.make(article_id: str) -> None`:**
    1. If any step has empty `narration`, it writes narration first, with stage `"Writing the narration"`:
       - segments come from `narration.json`, or from a fresh transcription when that file is missing and the video
         has audio (for older articles);
       - it calls `gemini.write_narration(narration_parts(...))` and sets `Article.lang` from the result;
       - `store.update` writes each step's narration by position. Steps the reply leaves out get
         `captions.speakable(text)`.
    2. Then it runs `await render(article_id, article.lang)`.
  - **`async def video.render(article_id: str, lang: str) -> None`.** It never raises, and it coalesces: a call
    while the same `(article_id, lang)` is rendering queues exactly one re-run. The coalescing uses module-level
    `_running`/`_again` sets, marked `# ponytail: in-process only; one server process`. Steps:
    1. **Narration:** `VideoState(status="rendering")`. Scenes are the steps sorted by first event time. For
       `lang == article.lang`, narration comes from `step.narration`. Otherwise it comes from
       `translations[lang].steps[step.id].narration`, and a missing entry means an empty narration (Review Focus 5).
    2. **Clean source:** stage `"Preparing the video"`; `clean.mp4` is built once per article (skipped if it exists).
    3. **Voice:** stage `"Recording the voiceover"`. `updating` = ids of scenes whose segment isn't cached yet. Clips
       come from `voice.clip` with at most 4 at once. With `voice == "mine"`, if a clip fails in a translated
       language, retry with `DEFAULT_VOICE` and set
       `note = "Your voice couldn't be used in <Language>, so <Voice> was used."`.
    4. **Scenes:** stage `"Putting the video together"`.
       - Plans come from `scene_spans` and `plan_scene(clicks, span, audio_ms(clip), step.hold_ms)`.
       - Each scene renders to `d / "scenes" / f"{sha1(plan, clip name, zoom)[:16]}.mp4"` if missing.
       - `zoom` = the rect of the step's first actionable event when `step.video_zoom`, scaled to the content box as
         `render_frames` does.
    5. **Join:** `concat` → `d / f"video.{lang}.mp4"`; `to_vtt(cues(...))` → `d / f"captions.{lang}.vtt"`.
    6. **Sync check:** `sync_errors(plans, clip lengths, [video_ms(scene) ...])`. Any error → `failed` with
       `error = "The video couldn't be synced. Try again, and report it if it keeps happening."` and a log line with
       the details.
    7. **Done:** `status="ready"`, `version += 1`, `updating=[]`, `stage=""`.

    Any exception → `status="failed"`, `error = str(e)`. The previous `video.<lang>.mp4` stays, because `concat` only
    replaces it on success. Every state write goes through `store.update`.
- **API:**
  - `POST /articles/{id}/video` → schedules `video.make` (for older articles' "Make video").
  - `POST /articles/{id}/videos/{lang}` → schedules `video.render`. 404 for an unknown language (neither
    `article.lang` nor a translation). Returns the current `VideoState`.
  - `GET /voices` → `{"voices": [{"id": "Achird", "label": "Friendly"}, ...], "mine": voice.my_voice_ready()}`.
  - `DELETE /articles/{id}` → also 409 when any `videos[*].status == "rendering"`, with the message "A video for
    this article is still being made. Delete it once it's done."
  - **Startup:** `store.mark_interrupted()` also sets any `rendering` video to `failed` with "Stepcast was restarted
    while making this video. Try again."
- **Progress screen:** keep `web/src/Progress.tsx` as is. Video progress is shown in the Video view (Task 11), not on
  the article progress screen.

- [ ] **Step 1: Write the failing tests** in `test_video.py`. Fake `gemini.write_narration`, `voice.clip` (writes
  `wav_bytes(1000)`) and `media.clean_video` (copies a `testsrc` mp4). Real `render_scene`/`concat` run on 640×400
  synthetic video, so these are the end-to-end timing tests.

```python
def test_make_writes_narration_then_renders_in_recorded_order(article_with_steps):  # steps saved out of order
    asyncio.run(video.make("a1"))
    a = store.get("a1")
    assert all(s.narration for s in a.steps) and a.videos["en"].status == "ready" and a.videos["en"].version == 1
    assert (DATA / "a1/video.en.mp4").exists() and (DATA / "a1/captions.en.vtt").read_text().startswith("WEBVTT")
    assert spoken_order(fake_clip_calls) == [s.narration for s in sorted(a.steps, key=first_event_time)]

def test_editing_one_narration_rerenders_one_scene(...):
    ...  # render; change step 2 narration; render; exactly one new file in scenes/ and one new clip call

def test_failure_keeps_previous_video(...):
    ...  # render ok; then voice.clip raises RuntimeError("quota"); status failed, error "quota", video.en.mp4 unchanged bytes

def test_render_requests_during_a_render_coalesce(...):
    ...  # start render, call render twice more before it finishes: exactly two full runs

def test_empty_narration_scene_has_no_voice(...):
    ...  # step narration "" → voice.clip never called with it; video still ready
```

  In `test_api.py`: 409 on delete while `videos.en.status == "rendering"`; `POST /videos/xx` → 404; `GET /voices`
  shape.

  In `test_pipeline.py`: the happy path writes `narration.json` and calls `video.make` once (monkeypatched).

- [ ] **Step 2: Run to make sure they fail.** `cd server && uv run pytest tests/unit -q` → FAIL on the new tests.
- [ ] **Step 3: Implement `video.py`, the pipeline hook and the endpoints.**
- [ ] **Step 4: Run.** `cd server && uv run pytest tests/unit -q && uv run ruff check app tests` → PASS.
- [ ] **Step 5: Commit**

---

### Task 8: Blur for the whole video

**Files:**
- Modify: `extension/content.js`, `server/app/upload.py`
- Test: `extension/test/content.test.mjs`, `server/tests/unit/test_upload.py`

**Interfaces:**
- **Extension:**
  - `content.js` exports `redactEvent(doc) -> {kind: "redact", ts, url, viewport, rect: null, label: "", tag: "",
    value: "", key: "", redact}` and `sameRects(a, b) -> boolean`.
  - While recording, it sends a `redact` event on `scroll` (capture), `resize`, and a `MutationObserver` on `body`,
    throttled to one per 500 ms, and only when the rects differ from the last one sent.
- **Server:** `upload.events_from_video` also samples sensitive boxes between actions:
  - frame times every `SAMPLE_MS = 2000`, skipping any within 500 ms of an action;
  - at most 60 frames;
  - `gemini.find_sensitive` (Task 4) in one call;
  - each frame with boxes becomes a `RecEvent(kind="redact", t=..., redact=[pad(...)])`, merged into the sorted
    events before they are written. `check()` still counts only actionable events.

- [ ] **Step 1: Write the failing tests**

```js
// content.test.mjs (jsdom, as the existing tests)
test("redactEvent reports sensitive boxes only", () => { /* page with a password input and an email in text */ });
test("sameRects ignores sub-pixel noise", () => { /* {x:10.2} vs {x:10.4} → true; different count → false */ });
```

```python
def test_upload_adds_redact_samples_between_actions(tmp_path, monkeypatch):
    ...  # 10 s testsrc video, actions at 2 s and 8 s; samples at 0, 2000, 4000, 6000, 8000 minus those within
         # 500 ms of an action; fake find_sensitive returns one box per frame → redact events at t = 0, 4000, 6000,
         # each kind "redact" with padded boxes; the actionable count is unchanged
```

- [ ] **Step 2: Run to make sure they fail.** `cd extension && node --test test/` and
  `cd server && uv run pytest tests/unit/test_upload.py -q` → FAIL.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Run both** → PASS. Also run `cd e2e && node extension.test.mjs`, which should still pass (14
  checks).
- [ ] **Step 5: Commit**

---

### Task 9: Translations

**Files:**
- Create: `server/app/translate.py`
- Modify: `server/app/api.py`
- Test: `server/tests/unit/test_translate.py`

**Interfaces:**
- Consumes: `gemini.translate`, `settings.load().glossary`, `source_hash`, `video.render`.
- Produces:
  - **`LANGUAGES: dict[str, str]`**, BCP-47 → English name: `en, es, fr, de, it, pt-BR, nl, sv, pl, tr, ru, uk, ar,
    hi, id, vi, th, ja, ko, zh-CN`. The web app gets it from `GET /languages`.
  - **`async def translate.add(article_id: str, lang: str) -> None`:**
    - translates the title, intro, outro and every step (text + narration), with `src = source_hash(step)`;
    - shows `videos[lang] = VideoState(status="rendering", stage="Translating")` meanwhile;
    - saves `translations[lang]` and then runs `video.render(article_id, lang)`;
    - on failure, `videos[lang]` becomes `failed` with "The translation didn't work. Try again.";
    - never raises.
  - **`async def translate.update(article_id: str, lang: str, step_ids: list[str]) -> None`:** re-translates only
    those steps (the `TDoc` carries only them, with the existing title/intro/outro), keeps the translator's other
    edits, refreshes `src`, then re-renders.
  - **`translate.save(article_id, lang, edit: TranslationEdit) -> Article`:** saves edited title, intro, outro and
    step text/narration, keeping each step's `src`. `TranslationEdit` holds `title`, `intro`, `outro` and
    `steps: dict[str, {text, narration}]`; unknown step ids are rejected with 422.
- **API:**
  - `GET /languages`;
  - `POST /articles/{id}/translations/{lang}` → `add` (409 if that language is already rendering; 422 for an
    unknown code or the article's own language);
  - `POST /articles/{id}/translations/{lang}/update` with body `{"step_ids": [...]}`;
  - `PUT /articles/{id}/translations/{lang}` → `save`;
  - `DELETE /articles/{id}/translations/{lang}` → removes the translation, its `videos[lang]` and its
    `video.<lang>.mp4`/`captions.<lang>.vtt`;
  - `GET /settings/glossary` → `{"words": [...]}`;
  - `PUT /settings/glossary` → saves the trimmed, de-duplicated non-empty words.

- [ ] **Step 1: Write the failing tests** (fake `gemini.translate` returns `[es] <text>` for each field; fake
  `video.render`):

```python
def test_add_translates_everything_and_renders():
    asyncio.run(translate.add("a1", "es"))
    a = store.get("a1")
    assert a.translations["es"].steps["s1"].narration.startswith("[es]") and a.stale == {"es": []}
    assert rendered == [("a1", "es")]

def test_glossary_words_are_passed_as_keep(): ...

def test_update_only_touches_listed_steps_and_keeps_manual_edits():
    ...  # add; save a manual edit to s2; change source s1 → stale == {"es": ["s1"]}; update(["s1"]) → s1 refreshed,
         # s2 keeps the manual edit, stale == {"es": []}

def test_new_source_step_is_stale_and_silent_in_translated_video():
    ...  # add a step after translating → listed in stale; video.render (real, with fakes as in Task 7) gives it no clip
```

- [ ] **Step 2: Run to make sure they fail.** `cd server && uv run pytest tests/unit/test_translate.py -q` → FAIL.
- [ ] **Step 3: Implement `translate.py` and the endpoints.**
- [ ] **Step 4: Run.** `cd server && uv run pytest tests/unit -q` → PASS.
- [ ] **Step 5: Commit**

---

### Task 10: Settings: own voice and "don't translate"

**Files:**
- Create: `web/src/Settings.tsx`
- Modify: `server/app/api.py`, `web/src/api.ts`, `web/src/Library.tsx`, `web/src/Editor.tsx` (a Settings entry
  in the More menu), `web/src/index.css`
- Test: `server/tests/unit/test_api.py`

**Interfaces:**
- **API:**
  - `GET /my-voice` → `{"ready": bool}`.
  - `POST /my-voice` (multipart `sample`, `consent`, each audio up to 10 MB) → 204, or 422 with
    `voice.set_up_my_voice`'s message.
  - `DELETE /my-voice` → 204.
- **`api.ts`:** `getVoices()`, `getMyVoice()`, `setUpMyVoice(sample: Blob, consent: Blob)`, `forgetMyVoice()`,
  `getGlossary()`, `saveGlossary(words: string[])`.
- **`Settings.tsx`:** exports `SettingsButton`, a `<dialog>` that follows `NewArticleButton`'s pattern, with two
  sections:
  1. **"Your voice":**
     - **Not set up:** two recorders built on `MediaRecorder` with the mic:
       - "Read this paragraph" (a ~60-word neutral passage, 10–30 s);
       - "Then read this sentence exactly": "I am the owner of this voice and I consent to Google using this voice
         to create a synthetic voice model."

       Each recorder has Record/Stop and plays back what was recorded. **Save** posts both clips and shows the
       server's error text on 422.
     - **Set up:** "Your voice is ready", and **Remove my voice**.
     - **Note:** "Recordings stay on this computer. Gemini makes a temporary voice key from them each week."
  2. **"Don't translate":** a textarea, one term per line, saved on blur. Hint: "Product names and button labels
     that should stay as they are."

- [ ] **Step 1: Write the failing API tests:** `POST /my-voice` calls a monkeypatched `voice.set_up_my_voice` and
  returns 204; a `ValueError` becomes 422 with the message; glossary PUT/GET round-trips with trimming and de-dupe.
- [ ] **Step 2: Run to make sure they fail.** `cd server && uv run pytest tests/unit/test_api.py -q` → FAIL.
- [ ] **Step 3: Implement the endpoints, then the UI.**
- [ ] **Step 4: Verify.**
  - Run: `cd server && uv run pytest tests/unit -q`
  - Run: `cd web && npm run build && npm run lint && npx vitest run`

  Expected: all pass. Then in the running app, open Settings: record both clips, save, see "ready", remove, and see
  the not-set-up state. Check the dialog fits at 390 px wide.
- [ ] **Step 5: Commit**

---

### Task 11: The Video view

**Files:**
- Create: `web/src/VideoView.tsx`, `web/src/videoEdits.ts`, `web/src/videoEdits.test.ts`
- Modify: `web/src/api.ts`, `web/src/Editor.tsx`, `web/src/stepOps.ts`, `web/src/stepOps.test.ts`,
  `web/src/index.css`

**Interfaces:**
- **`api.ts` types:**
  - `Step` adds `narration`, `hold_ms`, `video_zoom`;
  - `VideoState`;
  - `Article` adds `lang`, `voice`, `videos`, `translations`, `stale`.
- **`api.ts` functions:**
  - `makeVideo(id)` (POST `/video`), `renderVideo(id, lang)`;
  - `videoUrl(id, lang, version)` = `${API}/files/${id}/video.${lang}.mp4?v=${version}`;
  - `captionsUrl(id, lang, version)`;
  - `saveArticle` also sends `voice`.
- **`stepOps.mergeNext`:** also joins `narration` with a space, and keeps the larger `hold_ms` and `a.video_zoom`.
- **`videoEdits.ts`:** `affectsVideo(before: Article, after: Article): boolean`. True when the voice, the step order
  by id, or any step's `narration`/`hold_ms`/`video_zoom`/`event_ids` changed. Title, intro, outro and step text
  edits don't count.
- **`Editor.tsx`:**
  - **Views:** a segmented **Article | Video** switch in the TopBar; `view` state, defaulting to `"article"`.
  - **Polling:** the existing poll also runs while any `videos[*].status === "rendering"`.
  - **Re-render after saves:** after a save succeeds, if `affectsVideo(lastSaved, saved)`, call
    `renderVideo(id, a.lang)` 1500 ms after the last such save (debounced; also on leaving the view), then poll.
- **`VideoView.tsx`** (props `{a, lang, onStep(i, patch), onVoice(v), onStructural(message, steps), onMake()}`):
  - **Status** (`a.videos[lang]`):
    - `none`: an empty state, "Turn this article into a narrated video", with a **Make video** button;
    - `rendering`: the stage text, plus the player still showing the previous version if one exists;
    - `failed`: the error and **Try again**;
    - `note`: shown as an info line.
  - **Player:** `<video controls preload="metadata" src={videoUrl} key={version}>` with
    `<track kind="captions" default srcLang={lang} src={captionsUrl}>`.
  - **Voice:** a `<select>` of `getVoices()` plus "My voice" when `mine` is true. Otherwise a "Set up my voice…"
    entry opens Settings.
  - **Scenes:** in recorded order, each `<section className="scene">` has:
    - the step number;
    - the screenshot thumbnail (`imageUrl`);
    - an auto-sizing `<textarea aria-label="Narration for step N">`;
    - **Zoom** (toggle `video_zoom`);
    - **Hold** (a `<select>` of 0/1/2/3 s → `hold_ms`);
    - **Merge with next** and **Delete**, reusing `structural` and the undo toast; source language only.

    A scene whose id is in `updating` gets `aria-busy` and an "Updating…" label.

- [ ] **Step 1: Write the failing tests**

```ts
// videoEdits.test.ts
test("narration, hold, zoom, voice and order affect the video; article text does not", () => {
  const a = article([step("a", { narration: "Hi" }), step("b")]);
  expect(affectsVideo(a, { ...a, title: "New" })).toBe(false);
  expect(affectsVideo(a, withStep(a, 0, { text: "Changed" }))).toBe(false);
  expect(affectsVideo(a, withStep(a, 0, { narration: "Hello" }))).toBe(true);
  expect(affectsVideo(a, withStep(a, 1, { hold_ms: 1000 }))).toBe(true);
  expect(affectsVideo(a, { ...a, voice: "Sulafat" })).toBe(true);
  expect(affectsVideo(a, { ...a, steps: [a.steps[1], a.steps[0]] })).toBe(true);
});
// stepOps.test.ts
test("mergeNext joins narration too", () => { /* "Open it." + "Save." → "Open it. Save." */ });
```

- [ ] **Step 2: Run to make sure they fail.** `cd web && npx vitest run` → FAIL.
- [ ] **Step 3: Implement it.** Styles follow the existing tokens in `index.css` (paper, sheet, ink, accent,
  dark mode). The scene list reuses the `.step` layout with a smaller shot; nothing scrolls sideways at 390 px.
- [ ] **Step 4: Verify.**
  - Run: `cd web && npx vitest run && npm run build && npm run lint`
  - Expected: all pass.
  - Then, against a running server with a real article:
    1. edit one narration;
    2. within ~2 s that scene shows "Updating…";
    3. the player reloads with the new sentence spoken;
    4. Z and Hold changes re-render;
    5. Article view text edits do not trigger a render.

  Take screenshots at desktop and 390 px for the founder.
- [ ] **Step 5: Commit**

---

### Task 12: Languages in the editor

**Files:**
- Create: `web/src/LanguageMenu.tsx`
- Modify: `web/src/api.ts`, `web/src/Editor.tsx`, `web/src/VideoView.tsx`, `web/src/index.css`

**Interfaces:**
- **`api.ts`:**
  - `getLanguages(): Promise<Record<string, string>>`;
  - `addLanguage(id, lang)`;
  - `updateTranslation(id, lang, stepIds)`;
  - `saveTranslation(id, lang, edit)`;
  - `removeLanguage(id, lang)`.
- **`LanguageMenu.tsx`:** a popover button in the TopBar showing the current language name. It lists the source
  language, every translated language (with a dot when that language has stale steps), and **Add language…**, a
  dialog with a filterable list of `getLanguages()` minus the existing ones.
- **`Editor.tsx`:** a `lang` state, defaulting to `a.lang`. When `lang !== a.lang`, both views show and edit
  `a.translations[lang]`:
  - title, intro, outro and step text in the Article view; narration in the Video view;
  - autosave goes through `saveTranslation` on the same serialized chain;
  - structural tools, drag-and-drop and Zoom/Hold are hidden (source-only);
  - a stale step shows "The original changed. **Update** this step" → `updateTranslation(id, lang, [stepId])`;
  - a banner lists the count with **Update all**;
  - the More menu gains **Remove <Language>…** (confirm dialog, `ConfirmDelete`-style copy).

  After a translation edit that affects narration, call `renderVideo(id, lang)` (same debounce as Task 11).

- [ ] **Step 1: Write the failing test:** `affectsVideo` gets a translation overload,
  `affectsTranslationVideo(before: Translation, after: Translation)`, which is true only when a step's narration
  changed. Add it to `videoEdits.test.ts`.
- [ ] **Step 2: Run to make sure it fails.** `cd web && npx vitest run` → FAIL.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Verify.**
  - Run: `cd web && npx vitest run && npm run build && npm run lint`
  - Expected: all pass.
  - Then, in the running app:
    1. add Spanish to a real article; progress shows "Translating", then the voice and video stages;
    2. the Spanish video plays with Spanish voice and captions;
    3. edit one Spanish narration, and only that scene updates;
    4. change the English step text: Spanish shows the stale dot and the Update link, and Update clears it;
    5. remove Spanish.
- [ ] **Step 5: Commit**

---

### Task 13: Export for docs

**Files:**
- Modify: `server/app/export.py`, `server/app/api.py`, `web/src/ShareMenu.tsx`, `web/src/api.ts`
- Test: `server/tests/unit/test_export.py` (create; move any existing export assertions from `test_api.py` only if
  they test `markdown_zip`)

**Interfaces:**
- **`export.docs_zip(a: Article) -> bytes`** replaces `markdown_zip`. The `/articles/{id}/export.md.zip` endpoint is
  kept and serves it.
  - **Contents:** `article.md`, `images/<n>.png`, plus `video.mp4` and `video.vtt` when `videos[a.lang]` is ready.
    For each translation: `article.<lang>.md` (with its own step text), plus `video.<lang>.mp4` and
    `video.<lang>.vtt` when that video is ready. All languages share the images.
  - **`article*.md`:** `# title`, the intro, then, when a video exists:

    ```
    <video controls width="100%" src="video.mp4"><track kind="captions" src="video.vtt" srclang="en" label="English" default></video>
    ```

    then the numbered steps with images, as today, and the outro.
- **`GET /articles/{id}/videos/{lang}.mp4`:**
  - attachment named `<slug-of-title>.<lang>.mp4`;
  - `?captions=burned` serves `media.burn_captions` output, cached as `video.<lang>.burned.<version>.mp4` and built
    in `asyncio.to_thread`;
  - 404 when that video isn't ready.
- **`GET /articles/{id}/videos/{lang}.vtt` and `.srt`:** the SRT is built from the same cues. `video.py` saves them
  to `d / f"cues.{lang}.json"` at render time.
- **`ShareMenu`:**
  - "Markdown (zip)" becomes **Export for docs (zip)**, hinted "Article, screenshots, video and captions, in every
    language";
  - adds **Video (MP4)**, **Video with captions burned in** and **Captions (SRT)** for the current language, shown
    only when that video is ready;
  - the HTML and print entries stay.

- [ ] **Step 1: Write the failing tests**

```python
# fixture: a ready article with real frames, fake video.en.mp4/video.es.mp4 + VTTs, and an "es" translation
def test_docs_zip_has_video_and_every_language(ready_article_with_video_and_es):
    z = zipfile.ZipFile(io.BytesIO(docs_zip(a)))
    assert {"article.md", "video.mp4", "video.vtt", "article.es.md", "video.es.mp4", "video.es.vtt",
            "images/1.png"} <= set(z.namelist())
    md = z.read("article.md").decode()
    assert md.index("<video") < md.index("1. ") and 'src="video.vtt"' in md
    assert "[es]" in z.read("article.es.md").decode()

def test_docs_zip_without_video_is_the_old_article(): ...  # no <video>, no mp4

def test_burned_download_is_cached(client, ...):  # monkeypatch burn_captions; two GETs → one call
```

- [ ] **Step 2: Run to make sure they fail.** `cd server && uv run pytest tests/unit/test_export.py -q` → FAIL.
- [ ] **Step 3: Implement it.**
- [ ] **Step 4: Verify.**
  - Run: `cd server && uv run pytest tests/unit -q` and `cd web && npm run build && npm run lint`
  - Expected: all pass.
  - Then unzip a real export into a scratch Docusaurus or Mintlify-like folder, or simply open `article.md` in a
    Markdown preview that renders HTML. The video plays with captions.
- [ ] **Step 5: Commit**

---

### Task 14: Self-hosting

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `extension/options.html`, `extension/options.js`
- Modify: `server/app/api.py`, `web/src/api.ts`, `web/vite.config.ts`, `extension/background.js`,
  `extension/offscreen.js`, `extension/manifest.json`, `README.md`
- Test: `server/tests/unit/test_api.py`

**Interfaces:**
- **`api.py` serves the web app:** when `WEB_DIST` exists, `app.mount("/", StaticFiles(directory=WEB_DIST,
  html=True))` is added **after** all routes. `WEB_DIST = Path(os.getenv("STEPCAST_WEB_DIST",
  Path(__file__).resolve().parents[2] / "web" / "dist"))`.
- **`web/src/api.ts`:** `API = ""` (same-origin).
- **`vite.config.ts`:** `server.proxy` sends `/recordings`, `/uploads`, `/articles`, `/files`, `/a/`, `/voices`,
  `/languages`, `/settings`, `/my-voice` to `http://127.0.0.1:8000`, so dev and Docker behave the same.
- **Extension:**
  - `options.html`/`options.js`: one field, "Stepcast address", default `http://localhost:8000`, saved to
    `chrome.storage.sync.server`, with a **Test** button that GETs `/languages` and says "Connected" or "Can't reach
    Stepcast at that address".
  - `manifest.json`: `"options_page": "options.html"`.
  - `background.js`: reads `server` at start, and opens `${server}/#/a/${id}`. It passes `server` in the offscreen
    `start` message.
  - `offscreen.js`: posts to `${server}/recordings`.
  - The popup's error text names the address it tried.
- **`Dockerfile`:**
  - stage 1: `node:22-slim`, `npm ci && npm run build` in `web/`;
  - stage 2: `python:3.12-slim`, `apt-get install -y --no-install-recommends ffmpeg`, `uv` from
    `ghcr.io/astral-sh/uv`, the repo's `server/` and the built `web/dist` copied to `/app/server` and `/app/web/dist`,
    `uv sync --frozen --no-dev`, `CMD ["uv", "run", "uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]`
    with `WORKDIR /app/server`.
- **`docker-compose.yml`:**
  - one service, `stepcast`, with `build: .`;
  - `ports: ["8000:8000"]`;
  - `environment: [GEMINI_API_KEY]`;
  - `env_file: {path: server/.env, required: false}`;
  - `volumes: ["./server/data:/app/server/data"]`.
- **README:** "Run it" leads with:
  1. put the key in `.env`;
  2. `docker compose up`;
  3. load the extension (Load unpacked → `extension/`);
  4. open `http://localhost:8000`.

  A "Developing" section keeps the `uv`/`npm` route and says to set the extension address to
  `http://localhost:5173`. It also lists what leaves the machine (Gemini calls only), the voice-key note, and an
  "Export to your docs site" section.

- [ ] **Step 1: Write the failing test:** with a temporary `WEB_DIST` containing `index.html`, `GET /` returns it,
  and `GET /articles` still returns JSON (routes win over the mount).
- [ ] **Step 2: Run to make sure it fails.** `cd server && uv run pytest tests/unit/test_api.py -q` → FAIL.
- [ ] **Step 3: Implement everything above.**
- [ ] **Step 4: Verify.**
  - Run: `docker compose build && docker compose up -d`, then `curl -s localhost:8000/ | grep -c '<div id="root">'`
    and `curl -s localhost:8000/languages`.
  - Expected: `1`, then the language JSON.
  - Then point the extension at `http://localhost:8000`, record a short flow, and get an article and a video.
  - Run: `cd e2e && node extension.test.mjs` (update its server/editor URLs to the new single address).
  - Expected: all checks pass.
  - Run: `docker compose down`.
- [ ] **Step 5: Commit**

---

### Task 15: End-to-end proof and founder review

**Files:**
- Modify: `e2e/extension.test.mjs`, `server/tests/integration/test_live.py`, the spec's "Decided during build"
- Test: the same files

- [ ] **Step 1: Extend the e2e test.** After the article is ready:
  - wait for `videos.en.status === "ready"` (timeout 5 min);
  - check that `video.en.mp4` has a video and an audio stream (ffprobe);
  - check that its length equals the sum of the scene plans (the server's sync check has already passed, otherwise
    the status would be `failed`);
  - check the size is under 20 MB per 2 minutes;
  - check that a frame sampled 200 ms after each logged click's place in the output shows the purple highlight
    (pixels near `#6D28D9`).
- [ ] **Step 2: Add a live integration test.** A short 3-click synthetic flow (the existing fixture frames assembled
  into a video with ffmpeg) runs through `video.make` with real Gemini in `en`, then `translate.add` to `de`. Both
  videos end `ready`, and render time and file size are printed.
- [ ] **Step 3: Run both.** `cd e2e && node extension.test.mjs` and
  `cd server && uv run pytest tests/integration -q -s` → PASS. Record the render time and size per minute of video.
- [ ] **Step 4: Run the Atlan upload.** Put the founder's Atlan video
  (`~/Downloads/vidssave.com Atlan Product Tour_ Building a Business Glossary 1080P.mp4`) through upload → video, in
  English and Spanish.
- [ ] **Step 5: Founder checkpoint (stop and ask).** Send both videos and the export zip. Ask:
  - does the voice sound natural;
  - is anything out of sync;
  - is any personal data visible;
  - would they put this on a docs site as is?

  Fix what they report (each fix through the normal test-first loop), then record the outcomes in the spec.
- [ ] **Step 6: Commit**
