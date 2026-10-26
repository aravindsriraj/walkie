# Walkie Rename and Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename Stepcast to Walkie everywhere, and show a dark "Studio" landing page the first time someone opens Walkie, with real demo media and a GitHub star ask.

**Architecture:** The rename is a mechanical sweep plus a one-time database file move. The landing page is a new view in the existing hash-routed React app: a small pure module decides which view to show, `Landing.tsx` renders the page, and its media (five language videos, captions, and real text samples) are static files in `web/public/landing/`, produced once by a script from a real Walkie recording.

**Tech Stack:** React 19 + Vite + vitest (jsdom), FastAPI + SQLite, ffmpeg, Chrome MV3 extension. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-10-26-walkie-landing-page-design.md`

## Global Constraints

- Product name: **Walkie**. GitHub: `https://github.com/aravindsriraj/walkie` (one constant, `GITHUB_URL` in `web/src/landing.ts`).
- Settings: `STEPCAST_*` → `WALKIE_*` (`WALKIE_DATA`, `WALKIE_WEB_DIST`, `WALKIE_CAPTION_FONT`, `WALKIE_API`, `WALKIE_URL`); marker `data-stepcast-redact` → `data-walkie-redact`. No fallbacks to old names.
- Past design and plan documents dated before 2026-10-26 are not rewritten.
- No new runtime dependencies; animations in CSS/SVG only.
- Landing page is always dark; works at 390 px wide with no sideways scroll; keyboard-usable; `prefers-reduced-motion: reduce` stops animations and autoplay.
- Demo languages: `en`, `es`, `de`, `fr`, `ja`. The five videos together stay under 8 MB.
- Copy, exact: hero "Walk through it once. Walkie does the talking."; sub "A narrated tutorial video and help article, in 20 languages, ready for your docs site."; main button "Start your first walkthrough"; star button "★ Star on GitHub"; support "Walkie is free and open source. If it saved you a retake, give it a star."; final "Your next tutorial is one walkthrough away."
- No claims, numbers, testimonials or logos the product can't back. Demo footage is the Acme demo app (`e2e/site/`) only.
- Commit after each task; push `main` to `origin` at the end.

## Review Focus

1. **Blocked storage** (private window, storage disabled): the landing page shows, and "Start your first walkthrough" still reaches the library without an error. Test in Task 2.
2. **Deep links on a first visit:** `#/a/<id>` opens the editor, never the landing page; share pages (`/a/<id>`) are server-rendered and unaffected. Test in Task 2.
3. **Autoplay refused or a video that fails to load:** the page stays usable and switching language doesn't throw. Test in Task 4.
4. **An existing install after the rename:** articles in `stepcast.db` are still there under `walkie.db`. Test in Task 1.
5. **Phone width and video seeking in production:** no horizontal scroll at 390 px; the built app serves `/landing/*.mp4` with range requests (HTTP 206) so the player can seek. Checks in Task 5.

---

### Task 1: Rename Stepcast to Walkie

**Files:**
- Modify: every file listed by `git grep -il stepcast -- ':!docs/superpowers/specs/2026-10-2[45]*' ':!docs/superpowers/plans/2026-10-2[45]*'` (about 40: `server/app/{store,api,captions,gemini,pipeline}.py`, `server/pyproject.toml`, `extension/*`, `web/src/*`, `web/index.html`, `web/vite.config.ts`, `Dockerfile`, `docker-compose.yml`, `e2e/*`, `README.md`). Regenerate `server/uv.lock`, `extension/package-lock.json`, `e2e/package-lock.json` after renaming package names (`walkie-server`, `walkie-extension`, `walkie-e2e`).
- Test: `server/tests/unit/test_store.py` (new), `extension/test/content.test.mjs`

**Interfaces:**
- Produces: `store.init(db: Path | None = None)` now defaults to `DATA_DIR / "walkie.db"` and, when only `DATA_DIR / "stepcast.db"` exists, renames it to `walkie.db` first.

- [ ] **Step 1: Write the failing test** in `server/tests/unit/test_store.py`:

```python
import sqlite3


def test_init_moves_an_old_stepcast_db(tmp_path, monkeypatch):
    from app import store
    old = tmp_path / "stepcast.db"
    sqlite3.connect(old).execute("CREATE TABLE articles (id TEXT PRIMARY KEY, data TEXT, created_at TEXT)").connection.commit()
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "_db", tmp_path / "walkie.db")
    store.init()
    assert (tmp_path / "walkie.db").exists() and not old.exists()
```

- [ ] **Step 2:** `cd server && uv run pytest tests/unit/test_store.py -q` → FAIL (`walkie.db` missing).
- [ ] **Step 3:** In `store.init`, before connecting: if `db` is None, `_db` doesn't exist and `_db.with_name("stepcast.db")` does, `rename` it. Then sweep every name in the file list (visible text, comments, env vars, the redact marker, Docker service `walkie`, FastAPI title, Gemini voice `display_name`, page titles, extension name "Walkie Recorder" and title "Walkie"). In `web/src/index.css` line 1 the comment becomes "Walkie — …".
- [ ] **Step 4:** Run, all must pass and the grep must print nothing:

```bash
cd server && uv lock && uv run pytest tests/unit -q && uv run ruff check app tests scripts
cd extension && npm install --package-lock-only && npm test
cd web && npx vitest run && npm run build && npm run lint
cd e2e && npm install --package-lock-only
git grep -i stepcast -- ':!docs/superpowers/specs/2026-10-2[45]*' ':!docs/superpowers/plans/2026-10-2[45]*' ':!docs/superpowers/specs/2026-10-26-walkie-landing-page-design.md' ':!docs/superpowers/plans/2026-10-26-walkie-landing-page.md'
```

The README screenshots still show the old wordmark; Task 5 retakes them.

- [ ] **Step 5: Commit** `git commit -am "Rename Stepcast to Walkie"` (plus `git add server/tests/unit/test_store.py`).

### Task 2: Which view to show (first-visit rule)

**Files:**
- Create: `web/src/landing.ts`, `web/src/landing.test.ts`
- Modify: `web/src/App.tsx`, `web/src/Library.tsx` (an "About Walkie" link to `#/welcome` next to Settings in the top bar)

**Interfaces:**
- Produces (in `web/src/landing.ts`):
  - `export const GITHUB_URL = "https://github.com/aravindsriraj/walkie";`
  - `export type View = { name: "landing" } | { name: "library" } | { name: "editor"; id: string };`
  - `export function pickView(hash: string, seen: boolean): View` — `#/a/<12 hex>` → editor; `#/welcome` → landing; anything else → landing if `!seen`, else library.
  - `export function landingSeen(storage?: Storage): boolean` and `export function markLandingSeen(storage?: Storage): void` — key `"walkie.landingSeen"`, value `"1"`; both default to `localStorage` and swallow any exception (blocked storage reads as not seen; a failed write is ignored).
- `App.tsx` keeps `seen` in React state (initialised from `landingSeen()`), renders `<Landing onStart={…} />` for the landing view, where `onStart` calls `markLandingSeen()`, sets `seen` to true and sets `location.hash = "#/"`.

- [ ] **Step 1: Write the failing tests** in `web/src/landing.test.ts`:

```ts
test("first visit at the root shows the landing page, later visits the library", () => {
  expect(pickView("", false)).toEqual({ name: "landing" });
  expect(pickView("#/", false)).toEqual({ name: "landing" });
  expect(pickView("", true)).toEqual({ name: "library" });
  expect(pickView("#/", true)).toEqual({ name: "library" });
});
test("deep links never show the landing page", () => {
  expect(pickView("#/a/0123456789ab", false)).toEqual({ name: "editor", id: "0123456789ab" });
});
test("#/welcome always shows it", () => {
  expect(pickView("#/welcome", true)).toEqual({ name: "landing" });
});
test("seen is remembered, and blocked storage doesn't throw", () => {
  const mem = new Map<string, string>();
  const s = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v) } as Storage;
  expect(landingSeen(s)).toBe(false);
  markLandingSeen(s);
  expect(landingSeen(s)).toBe(true);
  const blocked = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } } as unknown as Storage;
  expect(landingSeen(blocked)).toBe(false);
  expect(() => markLandingSeen(blocked)).not.toThrow();
});
```

- [ ] **Step 2:** `cd web && npx vitest run src/landing.test.ts` → FAIL (module missing).
- [ ] **Step 3:** Implement `landing.ts` as specified; wire `App.tsx` (temporary `Landing` placeholder with the main button is fine until Task 4); add the About Walkie link.
- [ ] **Step 4:** `cd web && npx vitest run && npm run build && npm run lint` → all pass.
- [ ] **Step 5: Commit** `"Show a landing view on first open"`.

### Task 3: Real demo media

The founder records the take; the builder starts the demo app and runs the script.

**Files:**
- Create: `server/scripts/landing_media.py`, outputs in `web/public/landing/`: `{en,es,de,fr,ja}.mp4`, `{en,es,de,fr,ja}.vtt`, `landing.json`
- Modify: `README.md` (one line under Developing on regenerating the landing media)

**Interfaces:**
- Produces `web/public/landing/landing.json`:

```json
{ "said": ["…what the founder said, per transcript segment…"],
  "script": ["…Walkie's narration, per scene…"],
  "samples": { "en": "Click Save to finish.", "es": "…", "…": "one entry per language from GET /languages" } }
```

- Usage: `uv run python scripts/landing_media.py <article_id>` with `WALKIE_URL` (default `http://localhost:8000`) and `WALKIE_DATA` (default `server/data`).

- [ ] **Step 1:** Start the Acme demo app: `python3 -m http.server 8090 -d e2e/site`. Tell the founder to open `http://127.0.0.1:8090`, record 30–60 s with the Walkie extension while talking naturally (sign in, create a project), stop, and give the article id. Wait for it.
- [ ] **Step 2:** On that article, make the English video, then add `es`, `de`, `fr`, `ja` (`POST /articles/{id}/translations/{lang}`), and wait until all five videos are `ready`.
- [ ] **Step 3:** Write `landing_media.py`: download `/articles/{id}/videos/{lang}.mp4` and `.vtt` for the five languages; re-encode each with `ffmpeg -vf scale=1280:-2 -c:v libx264 -crf 30 -preset slow -c:a aac -b:a 64k -movflags +faststart`; `said` from `<data>/<id>/narration.json` (`text` of each segment); `script` from the article's steps' `narration` in recorded order; `samples` from `gemini.translate(TDoc(title="", intro="", outro="", steps=[TItem(id="s", text="Click Save to finish.", narration="Click Save to finish.")]), lang, [])` for every non-English language in `/languages` (`en` keeps the source line).
- [ ] **Step 4:** Run it and verify: `du -ch web/public/landing/*.mp4 | tail -1` is under 8 MB; `ffprobe` shows audio and video in each; `landing.json` has 20 `samples`; read `said` and confirm it is the founder's real words (with any "umm"s the transcriber kept).
- [ ] **Step 5: Commit** `"Add real landing page demo media"`.

### Task 4: The landing page

**Files:**
- Create: `web/src/Landing.tsx`, `web/src/landing.css`, `web/src/Landing.test.tsx`
- Modify: `web/src/App.tsx` (replace the placeholder)

**Interfaces:**
- Consumes: `GITHUB_URL` (Task 2); `/landing/{lang}.mp4|.vtt` and `/landing/landing.json` (Task 3); `getLanguages()` is not needed (samples carry the language list; names come from `Intl.DisplayNames`).
- Produces: `export function Landing({ onStart }: { onStart: () => void })`.

Sections and behaviour are those in the spec's "The page, top to bottom", in the Studio look of `.superpowers/brainstorm/77196-1793006919/content/hero-direction.html` (option A). Decisions the spec leaves:
- **Language switch:** set the `<video>` `src` and `<track>` to the new language, then seek to the same fraction of the duration and resume if it was playing. `play()` rejections are caught and ignored.
- **Sound:** video starts muted (autoplay only without reduced motion); a "Sound on" button unmutes.
- **Rough → clean:** an `<input type="range">` (0–100) cross-fades `said` (left) and `script` (right); labelled "What you said" / "What Walkie says".
- **How it works:** `IntersectionObserver` adds `is-lit` to each step as it scrolls in; without it, all are lit.
- **Language chips:** a `button` per language; hover or focus shows its sample beneath; tap toggles.
- **Styles** live in `landing.css` under a `.landing` root, with their own dark tokens, so the app's theme is untouched.

- [ ] **Step 1: Write the failing tests** in `web/src/Landing.test.tsx` (first line `// @vitest-environment jsdom`; render with `createRoot` + `act` from `react` into a container; stub `fetch` to return a `landing.json` fixture; stub `HTMLMediaElement.prototype.play` to return `Promise.reject(new Error("autoplay"))`):

```tsx
test("the hero says what Walkie does and the main button calls onStart", async () => {
  // container text includes "Walk through it once. Walkie does the talking."
  // clicking the button named "Start your first walkthrough" calls onStart once
});
test("star links go to the GitHub repo", async () => {
  // every link whose text includes "Star on GitHub" has href === GITHUB_URL
});
test("choosing a language switches the video and captions, even if play() is refused", async () => {
  // click the "ES" pill → video src ends with "/landing/es.mp4", track src ends with "/landing/es.vtt"; no unhandled rejection
});
test("the rough take and the script come from landing.json", async () => {
  // fixture said[0] and script[0] both appear in the container
});
```

- [ ] **Step 2:** `cd web && npx vitest run src/Landing.test.tsx` → FAIL.
- [ ] **Step 3:** Implement `Landing.tsx` and `landing.css`.
- [ ] **Step 4:** `cd web && npx vitest run && npm run build && npm run lint` → all pass.
- [ ] **Step 5: Commit** `"Add the Walkie landing page"`.

### Task 5: Check it for real, refresh the README, ship

**Files:**
- Modify: `README.md`, `docs/media/*.png` (retaken), `docs/media/demo.gif` (only if it shows the old name; it doesn't today)
- Create: `docs/media/landing.png`

- [ ] **Step 1:** Rebuild and run the image: `docker compose build && docker compose up -d` (stop any other server on 8000 first, with the founder's OK). Then verify:
  - fresh browser profile at `http://localhost:8000/` shows the landing page; "Start your first walkthrough" opens the library; reload shows the library; "About Walkie" brings the page back; `#/a/<id>` on a fresh profile opens the editor;
  - `curl -s -o /dev/null -w "%{http_code}" -H "Range: bytes=0-99" http://localhost:8000/landing/en.mp4` prints `206`;
  - Playwright at 390×844: `document.documentElement.scrollWidth <= innerWidth`, and a screenshot of each section looks right; at 1280×800 too;
  - with `reducedMotion: "reduce"` the video doesn't autoplay and nothing animates.
- [ ] **Step 2:** Retake the README screenshots (Walkie wordmark) the way they were made (the demo article on a scratch server), add `docs/media/landing.png` near the top of the README, and mention the landing page and "About Walkie" under Using it.
- [ ] **Step 3:** Run everything: server unit tests, extension tests, web tests, and the e2e suite against the rebuilt image (`cd e2e && WALKIE_URL=http://localhost:8000 npm test`) → all pass.
- [ ] **Step 4: Commit** `"README: Walkie screenshots and landing page"` and `git push origin main`.
