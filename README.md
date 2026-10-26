# Stepcast

Walk through a feature once. Get a polished tutorial video (natural voiceover, zoom on every click, captions,
personal data blurred) and the matching step-by-step help article, in every language you need, ready to drop into
your docs site.

Open source and self-hosted: your recordings stay on your machine. The only thing sent out is the Gemini calls.

| Part | What | Stack |
|---|---|---|
| `extension/` | Chrome recorder: tab video, optional mic, click/typing log, where to blur | MV3, plain JS |
| `server/` | API, video rendering, Gemini calls, exports | FastAPI, `google-genai`, ffmpeg, Pillow |
| `web/` | Article and video editor | React + Vite |
| `e2e/` | Real-extension end-to-end test + demo app | Playwright |

Designs: `docs/superpowers/specs/`. Plans: `docs/superpowers/plans/`.

## Run it

You need Docker, Google Chrome and a Gemini API key ([get one](https://aistudio.google.com/apikey)).

1. Put your key in `server/.env`:

   ```bash
   echo "GEMINI_API_KEY=your-key" >> server/.env
   ```

2. Start Stepcast:

   ```bash
   docker compose up -d
   ```

3. Load the recorder: Chrome → `chrome://extensions` → turn on **Developer mode** → **Load unpacked** → pick the
   `extension/` folder.
4. Open <http://localhost:8000>.

To record, open the page you want to document, click the Stepcast icon → **Start recording**, walk through the task
(talking is welcome, mistakes and all), then **Stop & create article**. The article opens first; the narrated
video follows a minute later under **Video**. You can also **Upload a video** you already have (MP4, MOV or WebM,
up to 10 minutes).

Running Stepcast somewhere other than this computer? Set its address in the extension: right-click the Stepcast
icon → **Options**.

## Using it

- **Video:** edit the script as text; only the changed scene is re-recorded and re-rendered. Per scene you can turn
  the zoom off, hold a busy screen longer, merge or delete. Pick a voice, or set up **your own voice** in
  **Settings** (two short recordings; Google requires the second one, a consent statement, before it copies a voice).
- **Languages:** **English → Add language** translates the article and narration, records the voiceover and renders
  the video. Each language is editable on its own. When you change the original, the translated steps are marked
  so you can update them; your translators' edits are never overwritten. Names you list under **Settings → Don't
  translate** stay as they are.
- **Export for docs** (in **Share**): a zip with `article.md` (video embedded), `images/`, `video.mp4` and
  `video.vtt`, plus the same per language (`article.es.md`, `video.es.mp4`, …). It drops into Mintlify, Docusaurus
  and most Markdown/MDX sites. GitBook: upload the MP4 there. You can also download the video alone, the video with
  captions drawn in, or the captions as SRT for YouTube.

## Privacy

- **Blurring:** password, email, phone and card fields, anything marked `data-stepcast-redact`, and visible text
  containing an email are blurred in the screenshots and throughout the video. Uploaded videos: Gemini looks for
  personal data on frames every 2 seconds and after every click. Check uploads before you share them.
- **What Gemini sees:** blurred screenshots and the text of your steps, plus the narration audio when transcribing
  (sent with `store=False`, so Google doesn't keep it).
- **Your voice:** the two recordings stay in `server/data/my_voice/`. Gemini makes a temporary voice key from them
  each week and keeps nothing. **Settings → Remove my voice** deletes them.
- **No accounts:** Stepcast is for one team on one machine or private network. Don't expose it to the internet.

## Developing

Needs `uv`, Node 20+, `ffmpeg` 7 or newer, Chrome, and `GEMINI_API_KEY` in your shell.

```bash
cd server && uv sync && uv run uvicorn app.api:app --host 127.0.0.1 --port 8000 --reload
cd web && npm install && npm run dev          # http://localhost:5173, forwards API calls to :8000
```

Set the extension's address to `http://localhost:5173` while developing. Settings:

- `STEPCAST_DATA`: data folder (default `server/data`);
- `STEPCAST_API`: where the dev server forwards to;
- `STEPCAST_CAPTION_FONT`: a font file for burned-in captions if none installed covers your language.

```bash
cd server && uv run pytest tests/unit tests/integration   # integration calls Gemini (needs GEMINI_API_KEY)
cd extension && npm test
cd web && npx vitest run
cd e2e && npm install && npm test   # real extension in Chromium: record → article → video
cd server && uv run python scripts/voice_samples.py out/   # candidate voices: listen, plus word-error check
cd server && uv run python scripts/check_highlights.py data/<article id>   # do upload outlines sit on the click?
```

## License

Apache-2.0, see [LICENSE](LICENSE). Copyright 2026 TR Aravindan.
