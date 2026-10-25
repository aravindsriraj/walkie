# Stepcast

Record a flow in your product → get a step-by-step help article (screenshots, highlights, privacy blur).

| Part | What | Stack |
|---|---|---|
| `extension/` | Chrome recorder: tab video, optional mic, click/typing log | MV3, plain JS |
| `server/` | Upload API, frames, Gemini calls, exports | FastAPI, Gemini SDK `google-genai` (`gemini-3.8-flash` steps, `gemini-3.5-flash-lite` title/intro, `gemini-3.5-transcribe` narration), ffmpeg |
| `web/` | Article editor | React + Vite |
| `e2e/` | Real-extension end-to-end test + demo app | Playwright |

Spec: `docs/superpowers/specs/2026-10-25-help-articles-v1-design.md` · Plan: `docs/superpowers/plans/2026-10-25-help-articles-v1.md`

## Run it

Needs `uv`, Node 20+, `ffmpeg`, Google Chrome, and `GEMINI_API_KEY` in your shell.

```bash
# 1. API (http://127.0.0.1:8000)
cd server && uv sync && uv run uvicorn app.api:app --host 127.0.0.1 --port 8000

# 2. Editor (http://localhost:5173)
cd web && npm install && npm run dev
```

3. Chrome → `chrome://extensions` → enable **Developer mode** → **Load unpacked** → pick `extension/`.
4. Open any web app, click the Stepcast icon → **Start recording**, do the flow → **Stop & create article**. The editor opens on the new article.
5. Optional narration: click **Enable microphone** in the popup once, then tick **Narrate with microphone**.

## Tests

```bash
cd server && uv run pytest tests/unit tests/integration   # integration hits Gemini live (needs GEMINI_API_KEY)
cd extension && npm test
cd web && npx vitest run
cd e2e && npm install && npm test   # real extension in Chromium: record → upload → article (API + editor must be running)
```

## Notes

- Privacy: password/email/phone/card fields, any element with `data-stepcast-redact`, and visible text containing an email are blurred in screenshots; sensitive typed values are never sent.
- Per-step animated clips (Remotion) were removed from v1 to keep it lean; the working version is at git tag `v1-with-remotion-clips`. Remotion returns with the video product.
- Local, single-user: no auth. Don't expose port 8000.
