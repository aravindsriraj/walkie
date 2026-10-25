# Stepcast v1 — Help Articles from a Screen Recording

**Date:** 2026-10-25 · **Status:** Draft for review · **Working name:** Stepcast (placeholder)

## Intent

Clueso (clueso.io) turns screen recordings into polished videos and how-to articles. We are building our own product, starting with the capability the founder likes most: **record a product flow once, get a publish-ready step-by-step help article** (Clueso's `/features/help-articles`).

Clueso's article feature, as advertised: a recording from a Chrome extension → auto-captured, auto-zoomed screenshots → transcript polished into step text plus an AI intro and outro → rich-text editing with team review → publish to a help center hosted by Clueso, or export. It claims this takes "under a minute".

### Why we can be better (v1 differentiators)

1. **DOM-aware capture.** The extension records *what* was clicked: the element's label, its on-screen rectangle and the URL, timestamped against the video. Highlights land exactly on the element, and step text names the real UI label.
2. **Works silently.** Narration is optional. Steps come from the recorded actions; narration, when present, adds the "why".
3. **Privacy by default.** Password, email and card inputs (and anything tagged `data-stepcast-redact`) are blurred in every screenshot. Their typed values are never stored.
4. **Docs-as-code export.** The Markdown + images zip drops straight into Docusaurus, Mintlify or GitHub.

## Goals (v1)

- A Chrome extension records the tab (video, optional mic) plus an action log (clicks, field changes, Enter presses, page loads).
- The server turns a recording into an article (title, intro, ordered steps each with a screenshot, outro) in under 60 seconds for a 2-minute recording.
- An editor lets you edit the title, intro, outro and step text; reorder, delete and merge steps; and toggle each screenshot between zoomed and full.
- Exports: Markdown zip, self-contained HTML, a shareable page (`/a/{id}`), and PDF through the browser's print dialog on the shareable page.

## Non-goals (v1)

Animated per-step clips, AI voiceover, avatars, translation, a full video editor, a hosted help center with search/navigation, team accounts, comments or approvals, auth, cloud deployment, freshness checks (re-running a flow to detect UI drift), Zendesk/Intercom/Notion push, and an MCP server. Freshness checks and push integrations are the first v1.1 candidates.

## Anti-goals (failure even if it "works")

- Any screenshot or stored event leaks a password, email, or card number that was typed.
- Step text that describes something not on screen (a hallucinated button or value).
- An article stuck forever in "processing" with no error.

## Constraints

- **Gemini:** called directly with the Gemini SDK (`google-genai`), all in `server/app/gemini.py`. (v1 started on Google ADK; dropped 2026-10-25 because this is a fixed two-call pipeline with no tools, multi-turn or delegation — ADK added 58 packages, ~1 s per article and a deprecation path, for nothing used. Bring ADK back for genuinely agentic features, e.g. the freshness checker.) Models by capability: `gemini-3.8-flash` for step_writer (founder's choice; multimodal grounding is the hard part), `gemini-3.5-flash-lite` for article_writer (short text-only writing), `gemini-3.5-transcribe` for narration (exact word timestamps; called through the Interactions API with `store=False`).
- **Local, single-user:** the server binds to `127.0.0.1:8000`. Data lives in SQLite at `server/data/stepcast.db` plus files under `server/data/{article_id}/`. The editor runs on `localhost:5173`.
- **Media:** `ffmpeg` on PATH. Recordings are transcoded to H.264 MP4 at ingest (MediaRecorder WebM isn't seekable).
- **Limits:** the extension auto-stops at 10 minutes. The server rejects recordings with more than 120 actionable events ("Recording too long — keep it under ~100 actions").

## How it works

```
Chrome extension ──(video.webm + events.json)──▶ POST /recordings
                                                     │ background task
                                                     ▼
  transcode → extract frames per action → highlight + redact + zoom crop
           → (if audio) gemini-3.5-transcribe → timestamped sentences
           → step_writer (gemini-3.8-flash) → validate → article_writer (gemini-3.5-flash-lite)
           → normalize/validate steps → Article saved (status=ready)
                                                     │
              Web editor (React) ◀── GET/PUT /articles/{id}
              Exports: .md.zip · .html · /a/{id} (print → PDF)
```

### Event log (extension → server)

Each event has:
- `t`: ms since the recording started
- `kind`: `click` | `input` | `keydown` | `navigate`
- `url`
- `viewport`: `{w, h, dpr}`
- `rect`: the element's viewport rect in CSS px
- `label`: the element's accessible name or visible text, ≤80 chars
- `tag`
- `value`: for an input, its final value. Empty for sensitive fields.
- `key`: only `Enter`
- `redact`: viewport rects of sensitive elements at that moment

`click`, `input` and `keydown` events are **actionable**. `navigate` events are context only.

### Frames

For each actionable event:
- **Frame time:** `click`/`keydown` take the frame at `t − 150ms`, before the UI changes. `input` takes it at `t + 100ms`, so the typed value shows.
- **Scaling:** the frame is cropped to where the page sits (`media.content_box`), then rects are scaled by `frame_width / viewport.w`.
- **Output:** `full.png` has the element outlined (3px, rounded, brand colour `#6D28D9`) and the redact rects Gaussian-blurred. `zoom.png` is a 16:10 crop around the element, clamped to the frame.

### Agents

- **Transcription:** runs only when the recording has audio. `gemini-3.5-transcribe` returns word timings; words are grouped into sentences (split at sentence punctuation or pauses over 1s). Sentences are *not* matched to actions by a timing rule (people talk before, during and after the action they mean); they're placed in time order between the actions in step_writer's input, and the model matches them by meaning.
- **step_writer:** receives a timeline: one text line per actionable event (index, time, kind, label, url, value), each followed by that event's highlighted full frame (JPEG, ≤1280px wide), with narration sentences interleaved by time. It groups consecutive events into steps (e.g., clicking a field then typing in it); a click that submits or opens a new screen is its own step and writes one imperative sentence per step, with UI labels in **bold**. It must describe only what's visible or recorded.
- **article_writer:** given the *validated* steps (so it never describes a dropped step), writes the title ("How to …", ≤10 words), a 1–2 sentence intro, and a one-sentence outro.
- **Validation:** step_writer output is untrusted. Out-of-range or duplicate event ids are dropped, and steps with no ids are removed. If nothing survives, fall back to one step per actionable event ("Click **{label}**.").

### Article model

An article has:
- `id`, `status` (`processing` | `ready` | `failed`), `error`
- `title`, `intro`, `outro`
- `steps[]`: each step has `id`, `event_ids`, `text` (supports Markdown `**bold**` and `` `code` `` only), `frame` (the event index whose screenshot is shown), and `zoomed`
- `created_at`

## Decided by the founder

v1 = the help-articles capability. The founder's original stack was Google ADK + Remotion; both were dropped on 2026-10-25 after measuring them (founder: "always simple and efficient"):
- ADK → the Gemini SDK directly (see Constraints).
- Remotion only powered optional per-step clips, which aren't part of the help-articles feature, and cost 1.1 GB of Node packages, a Chrome dependency, ~8 s per clip and a company licence above 3 people. The working clips are kept at git tag `v1-with-remotion-clips`; Remotion returns with the video product (narrated videos, captions, templates), where it's the right tool.

## My calls (please check)

- Product name "Stepcast", the repo at `~/Downloads/stepcast`, local single-user with no auth.
- Stack: FastAPI + SQLite + Pillow + ffmpeg server; plain-JS MV3 extension (no build step); React + Vite editor with plain textareas (no rich-text library); hash routing.
- PDF is the browser's print-to-PDF on the share page, not a server-side PDF engine.
- No QA/reviewer agent in v1. Add one when evals show text/screenshot mismatches.

## Decided during build/testing

- Gemini thinking level **LOW** on all agents: default thinking spent ~11k tokens (50–90 s) on a 10-action recording; LOW gives ~5 s with equal step quality.
- Inputs are stamped at the **last keystroke**, not at `change` (which fires on blur, usually at the next click, after the screen has moved on). The server sorts events by time.
- Redaction also covers **visible text containing an email** (e.g. "Signed in as …").
- Models chosen per job after side-by-side runs: flash-lite matched 3.8-flash on step_writer for the demo but ignored the "describe values generically" rule, so step_writer stays on 3.8-flash; transcribe-model timestamps were exact where 3.8-flash's were 0.4–0.6 s off.
- The extension records at the **page's own pixel size** (asked from the content script, capped at 4K). A fixed 4K 16:9 capture made Chrome letterbox non-16:9 tabs, shifting every highlight and blur box — found by the real-extension test. As a safety net (window resized mid-recording), the server crops each frame to where that event's page sits (`media.content_box`) before drawing highlights and blur.
- The real extension is tested end to end in Chromium (`e2e/`), including narration with the microphone swapped for a speech clip. Only the toolbar-icon click and the mic permission prompt are stood in for (a test switch and a stub).

## Left to the builder

Visual design of the editor and share page; exact prompt wording within the rules above; the extension popup's look.
