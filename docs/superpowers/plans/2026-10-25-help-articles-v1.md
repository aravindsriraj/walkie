# Stepcast v1 Help Articles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record a browser flow with a Chrome extension → get an editable, exportable step-by-step help article, with optional Remotion step clips.

**Architecture:** A plain-JS MV3 extension uploads `video.webm` + `events.json` to a local FastAPI server. A background task transcodes, extracts highlighted/redacted/zoomed frames, runs an ADK `SequentialAgent` (step_writer → article_writer) on Gemini, validates the output and stores the article as JSON in SQLite. A React editor edits and exports it. A Node Remotion project renders per-step clips on demand.

**Tech Stack:** Python 3.13 (uv), google-adk 2.x, FastAPI, Pillow, ffmpeg, SQLite · Chrome MV3 (plain JS) · React + Vite + TS · Remotion 4.x

**Spec:** `docs/superpowers/specs/2026-10-25-help-articles-v1-design.md`

## Global Constraints

- The server listens on `127.0.0.1:8000`; data lives at `server/data/` (DB `stepcast.db`, files `{article_id}/`); files are served at `/files/{article_id}/...`.
- Model: `MODEL = "gemini-3.8-flash"` in `server/app/agent.py` (founder's choice).
- Credentials: AI Studio key via `GEMINI_API_KEY`, with `.env` `GOOGLE_GENAI_USE_VERTEXAI=FALSE`.
- Highlight colour `#6D28D9`, 3px, rounded. Zoom crop aspect 16:10.
- Frame time: click/keydown `t-150`, input `t+100` (ms, clamped to `[0, duration]`).
- Max 120 actionable events, else fail with "Recording too long — keep it under ~100 actions".
- No actionable events → fail with "No clicks or typing were recorded".
- Step text Markdown subset: `**bold**`, `` `code` `` only; all HTML output is escaped first.
- Clips: window `click±1500ms`, 30fps, 1280px wide, even height.

## Review Focus

1. Recording with only scrolling (no actionable events) → article `failed` with the "No clicks or typing" message (Task 4 test).
2. LLM returns bad/duplicate/out-of-range event ids, or nothing usable → fallback steps; Gemini exception → `failed` with the error text, never stuck in `processing` (Tasks 2, 4 tests).
3. Password/email typed → value never leaves the page; the field is blurred in the frame (Task 6 test; Task 1 blur pixel test).
4. Server restarted mid-processing → on startup, `processing` articles become `failed` with "Interrupted — please re-upload" (Task 3 test).
5. LLM/user text containing `<script>` → escaped in the share page and HTML export (Task 5 test).

---

### Task 1: Media — transcode, frames, crop, highlight, redact

**Files:** Create `server/app/media.py`, `server/tests/unit/test_media.py`

**Interfaces — Produces:**
- `transcode(src: Path, dst: Path) -> None` (ffmpeg → H.264 yuv420p faststart, 30fps, keeps audio as AAC if present)
- `probe(path: Path) -> tuple[int, int, int, bool]` → `(width, height, duration_ms, has_audio)` via ffprobe
- `frame_time(ev: RecEvent, duration_ms: int) -> int`
- `crop_box(rect: Rect, fw: int, fh: int) -> tuple[int, int, int, int]` → `(x, y, w, h)`
- `render_frames(video: Path, events: list[RecEvent], out_dir: Path) -> None` — writes `frames/{i}_full.png` and `frames/{i}_zoom.png` for each actionable index `i`
- `extract_audio(video: Path, dst: Path) -> None` (mono 16 kHz mp3)

`crop_box` algorithm: `w = max(rect.w*2.5, fw*0.4)`, `h = w/1.6`; if `h < rect.h*1.5` then `h = rect.h*1.5; w = h*1.6`; cap `w<=fw`, `h<=fh`; centre on the rect, clamp into the frame; ints.

- [ ] Tests: `crop_box` keeps 16:10 and lies inside the frame for a rect at the corner `(0,0,10,10)` and at the far edge; a big rect gets a box ≥ the rect; `frame_time` gives click → t-150, input → t+100, clamps at 0; `render_frames` on a 2s ffmpeg `testsrc` mp4 writes both PNGs, and the redact region's pixel variance drops (blurred).
- [ ] Implement; run `uv run pytest tests/unit/test_media.py`; commit.

### Task 2: Models + step logic (prompt parts, transcript attach, normalize)

**Files:** Create `server/app/models.py`, `server/app/steps.py`, `server/tests/unit/test_steps.py`

**Produces (`models.py`):** `Rect`, `Viewport`, `RecEvent`, `Step`, `Article`, `Segment(start_ms, end_ms, text)`, plus the agent schemas `DraftStep(event_ids, text)`, `StepsDraft(steps)`, `ArticleMeta(title, intro, outro)`, `Transcript(segments)`, and `ACTIONABLE = {"click","input","keydown"}`.

**Produces (`steps.py`):**
- `actionable(events) -> list[int]` (indices)
- `attach_narration(events, segments) -> dict[int, str]` (window `(prev_actionable.t, ev.t+1000]`, each segment used once)
- `build_parts(events, narration, frames_dir) -> list[types.Part]` — one text line per actionable event `[i] kind on tag "label" at url (value: …) (narration: "…")` followed by its full frame as JPEG, ≤1280px wide
- `normalize_steps(draft: StepsDraft | dict | None, events) -> list[Step]` — drop non-actionable/out-of-range/duplicate ids, sort, drop empty steps; empty result → one fallback step per actionable event (`Click **label**.`, `Type in **label**.`, `Press **Enter**.`); `frame = event_ids[0]`, `zoomed=True`, `id = uuid4().hex[:8]`

- [ ] Tests: bad ids `[99, -1]` dropped; duplicate id across steps kept only in the first; `None` → fallback; narration attaches to the right event; `build_parts` gives 2 parts per actionable event.
- [ ] Implement; run tests; commit.

### Task 3: Store (SQLite)

**Files:** Create `server/app/store.py`, `server/tests/unit/test_store.py`

**Produces:** `DATA_DIR: Path`, `init(db: Path | None = None)`, `save(a: Article)`, `get(id) -> Article | None`, `list_all() -> list[Article]` (newest first), `mark_interrupted()`. One table `articles(id TEXT PK, data TEXT, created_at TEXT)`.

- [ ] Tests: round-trip; `mark_interrupted` flips `processing` → `failed` with "Interrupted — please re-upload".
- [ ] Implement; commit.

### Task 4: Agents + pipeline

**Files:** Rewrite `server/app/agent.py` (keep `MODEL`, the Gemini retry wrapper and `app = App(...)`), create `server/app/pipeline.py`, `server/tests/unit/test_pipeline.py`, `server/tests/integration/test_live.py`

**Produces:** `transcriber` (output_schema `Transcript`, output_key `transcript`); `step_writer` (`StepsDraft`, `steps_draft`); `article_writer` (`ArticleMeta`, `article_meta`, `include_contents="none"`, reads `{steps_draft}`); `root_agent = SequentialAgent(name="article_pipeline", sub_agents=[step_writer, article_writer])`; `async run_agent(agent, parts) -> dict` (InMemoryRunner → final session state); `async process(article_id: str) -> None` in pipeline.py, which never raises and always ends in `ready` or `failed`.

- [ ] Tests (monkeypatch `pipeline.run_agent`): happy path → ready with title and steps; no actionable events → failed with the message; 121 events → failed "too long"; `run_agent` raises → failed with the error text.
- [ ] Live test (skipped without `GEMINI_API_KEY`): synthetic recording → ready, ≥1 step, non-empty title.
- [ ] Commit.

### Task 5: API + exports + share page

**Files:** Create `server/app/api.py`, `server/app/export.py`, `server/tests/unit/test_api.py`

**Endpoints:** `POST /recordings` (multipart `video`, `events` JSON string; `started_at` unused) → `{id}` and schedules `process`; `GET /articles`; `GET /articles/{id}`; `PUT /articles/{id}` (title/intro/outro/steps only); `POST /articles/{id}/clips` → 202; `GET /articles/{id}/export.md.zip`; `GET /articles/{id}/export.html` (images inlined base64); `GET /a/{id}` (share page; `?print=1` auto-prints); static `/files`. CORS: `http://localhost:5173`, `chrome-extension://.*` regex. Startup: `store.init(); store.mark_interrupted()`.

**Produces (`export.py`):** `md_inline(text) -> str` (escape, then bold/code), `render_html(a, img_src: Callable[[Step], str]) -> str`, `markdown_zip(a) -> bytes`.

- [ ] Tests: upload → 200 with an id and the article stored as `processing`; PUT updates text; 404 on an unknown id; `<script>` in the title is escaped in `/a/{id}`; the md zip contains `article.md` + `images/1.png`.
- [ ] Commit.

### Task 6: Chrome extension

**Files:** `extension/manifest.json`, `background.js`, `offscreen.html/js`, `content.js`, `popup.html/js`, `permission.html/js`, `test/content.test.mjs`, `package.json` (devDep `jsdom`)

**content.js exports (via `module.exports` guard):** `targetOf(el)`, `elementLabel(el)`, `isSensitive(el)`, `redactRects(doc)`, `makeEvent(kind, el, extra)`.

- [ ] Tests (`node --test`): a password input change → `value === ""`; a button's label comes from aria-label, then text; `targetOf` climbs from a span to the button; `redactRects` finds the email input.
- [ ] Manual: load unpacked, record, stop → upload → the editor opens.
- [ ] Commit.

### Task 7: Remotion renderer + clips

**Files:** `renderer/package.json`, `renderer/src/index.ts`, `renderer/src/Root.tsx`, `renderer/src/StepClip.tsx`, `renderer/render.mjs`; `server/app/clips.py`; a test in `server/tests/unit/test_clips.py`

**Produces:** `clip_props(step, events, vw, vh, duration_ms, src) -> dict` (`src, startMs, endMs, clickMs, rect, zoom, videoW, videoH`); `async render_clips(article_id) -> None` (writes the jobs JSON, runs `node render.mjs jobs.json`, sets `step.clip = "clips/{step.id}.mp4"` and `clips_status`).

- [ ] Test: `clip_props` clamps the window at 0 and at the duration.
- [ ] Smoke: render one clip from the test video.
- [ ] Commit.

### Task 8: Web editor

**Files:** `web/` (Vite react-ts), `web/src/api.ts`, `web/src/stepOps.ts` + `stepOps.test.ts`, `web/src/App.tsx`, `web/src/Editor.tsx`, `web/src/App.css`

**Produces (`stepOps.ts`):** `move(steps, i, dir)`, `remove(steps, i)`, `mergeNext(steps, i)` (concatenates `event_ids` and text; keeps the first frame).

- [ ] Tests (vitest) for the three ops.
- [ ] UI: hash routes `#/` list, `#/a/{id}` editor; polls every 2s while processing; Save; export links; Render clips.
- [ ] E2E: run the server + web, drive a real recording through the extension in Chrome, verify the article, edit/save, exports and clips.
- [ ] Commit.
