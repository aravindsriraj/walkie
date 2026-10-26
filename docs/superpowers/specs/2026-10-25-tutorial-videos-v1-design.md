# Stepcast v1: Tutorial Videos + Help Articles, in Every Language

Builds on `2026-10-25-help-articles-v1-design.md` (the article pipeline, extension, editor, uploads and blurring,
all of which stay).

## Intent

Stepcast today turns a screen recording into a help article. On its own that is a crowded, cheap category (Scribe,
Tango, Guidde). The problem people pay Clueso for is bigger: **turning a messy screen recording into a polished
product video, fast, and keeping it available in every language.**

**Who it's for:** the customer-education lead at a SaaS company. They own the docs site, tutorial videos and
onboarding content, usually with a team of one or two, and they are not video editors.

**Their problem today:** a 2-minute how-to video takes half a day or more (script, record, re-record, fix audio, add
zooms in Camtasia, export), the matching help article is written separately, localization is expensive or skipped,
and many people dislike their own recorded voice.

**What v1 does for them:** they walk through a feature once in the Stepcast extension, talking naturally (mistakes
and "umm"s are fine). A few minutes later they have a polished, in-sync, natural-sounding tutorial video plus the
help article, in every language they need, as files ready to drop into their docs site.

**Success:** a publishable 2-minute tutorial in about 15 minutes of the user's time, good enough to put in front of
customers without opening another tool.

**Distribution:** open source and self-hosted (going public soon). Not a hosted SaaS.

## Goals (v1)

1. **Capture:** record with the extension (exact click log) or upload a screen recording (Gemini finds the clicks).
   Both exist today.
2. **Clean script:** transcribe the narration (exists), then rewrite it into a tight spoken script split into
   **scenes**, one per article step, each sentence tied to the click it describes.
3. **Natural voiceover:** a small set of reviewed AI voices, or the presenter's **own voice** recreated without the
   stumbles and background noise.
4. **Polished video:** narration and screen always in sync; a zoom and highlight on each click; captions; personal
   data blurred.
5. **Edit by text:** change a sentence and only that scene's voice, timing and render regenerate. Per-scene delete,
   merge, zoom toggle and "hold longer". One voice setting per video.
6. **Help article:** generated from the same steps as today, with its own written-style wording.
7. **Localization:** "Add language" produces a translated script, a voiceover in that language, a re-timed video,
   captions and the article. Each language can be edited on its own.
8. **Export for docs sites:** one zip per article (Markdown with the video embedded, images, MP4, captions, per
   language), plus separate downloads.
9. **Self-hosted:** bring your own Gemini API key; one-command setup; no accounts.

## Non-goals (v1)

- Hosted SaaS, accounts, roles, billing, multi-tenancy.
- A help center or public site (users publish to their own docs site).
- A timeline editor, keyframes, transitions, music, stock media, avatars, motion graphics.
- An agent that records by itself, and auto-updating videos when the product changes.
- Translating the product's own UI in the recording (the screen stays in the language it was recorded in).
- Comments, approvals, review workflows.

## Anti-goals (failure even if it "works")

- **A robotic-sounding voice.** The founder named this as the top way to get it wrong.
- **Narration out of sync with the screen.** Also named by the founder. A click shown before or long after the
  sentence that describes it is a failed video.
- **Personal data visible in an exported video.** Blurring has to hold for the whole video, not just at click
  moments.
- **Cloning a voice without that person's consent.**
- **Needing another tool to finish the job.** If users must open Camtasia or a video editor to fix things, v1 failed.
- **Videos too big for a docs repo.** Docs sites live in git.
- **A setup only a developer can follow.**

## Constraints

- **Stack (existing):** Chrome MV3 extension, FastAPI + SQLite server, React + Vite editor, google-genai SDK,
  ffmpeg, Pillow. Keep it; add as little as possible (founder's standing preference: simple and efficient).
- **Rendering with ffmpeg, not Remotion.** Remotion's license is only free for individuals and companies of up to
  three people, so every larger company using this open-source project would need to buy one. ffmpeg is already a
  dependency and does all v1 needs.
- **Gemini models:**
  - `gemini-3.8-flash`: script rewrite, translation, and the existing step writing and video analysis;
  - `gemini-3.5-flash-lite`: title, intro and outro (existing);
  - `gemini-3.5-transcribe`: narration transcription with word timings (existing);
  - `gemini-3.8-flash-tts`: voiceover, including Voice Replication for the presenter's own voice.
- **Data stays local** apart from the Gemini calls. Keep `store=False` on Gemini calls that send user audio, as
  transcription does today.
- **Upload limits stay:** 10 minutes and 2 GB.

## How it works

### Scenes

A **scene** is the video counterpart of an article step. It covers the same events (`event_ids`) and has its own
spoken **narration**, kept separate from the article's written text because speech and instructions read
differently ("Now let's link a term" is good speech but a poor article step).

- Deleting or merging a step affects the scene and the article step together. Reordering is article-only for v1,
  because the video can't be played back out of recorded order.
- Editing narration changes only the video. Editing article text changes only the article.

### Script

`gemini-3.8-flash` gets the steps, their screenshots and the transcribed narration segments (as the step writer
does today) and returns one narration passage per scene:
- cleaned up (fillers, false starts and repetition removed, grammar fixed);
- in the presenter's intent and terminology, never inventing UI;
- short enough to say over the scene, roughly 1–2 sentences.

If the recording has no speech, it writes narration from the steps alone.

### Voice

**Clips:** each scene's narration is synthesized as its own clip, so editing one scene regenerates one clip.

**AI voices:** a small curated set of `gemini-3.8-flash-tts` voices (about 4–6), each chosen by listening to real
product-tutorial scripts, delivered in a calm, friendly product-tour style.

**Own voice (Voice Replication), set up once:**
- Gemini's Voice Replication needs two clips from the same speaker, on the same mic:
  - a 10–30 s sample of natural speech;
  - the speaker reading a fixed **consent statement** aloud ("I am the owner of this voice and I consent to Google
    using this voice to create a synthetic voice model.", with a statement for each of 30 locales).
- So own voice is a one-time **"Set up your voice"** in the app: read a short paragraph, then the consent statement,
  in the browser. It is not learned silently from a recording. The consent requirement means a voice can only be
  replicated by the person it belongs to, which covers the consent anti-goal, including for uploaded videos.
- Privacy: use the **stateless** voice key (`store=False`, nothing kept by Google, 7-day expiry). Keep the two clips
  on the user's machine and re-create the key when it is about to expire.
- If replication fails or sounds poor, fall back to the closest stock voice and say so.

### Sync (the core of v1)

**The video is fitted to the voice, never the voice to the video.**

**Inputs per scene:**
- the click times of its events (exact for extension recordings, from Gemini for uploads);
- its voice clip length.

**Output:** a re-timed video segment in which **every click happens while its scene's narration is playing**:
- after a short lead-in, so the viewer hears what is about to happen;
- before the sentence ends.

**Tools:**
- **hold:** freeze a frame when the narration is longer than the action;
- **speed up:** speed through idle or slow stretches such as waiting, page loads and cursor wandering;
- **cut:** remove dead time beyond a speed-up limit, so the video never looks frantic.

The re-timing is a pure function from (events, clip lengths, settings) to a cut list, so it can be unit tested on
its own. Rendering applies the cut list.

**Automatic sync check:** after each render, verify that every click falls inside its scene's narration span. A
failure is a bug to fix, not something shown to users. This mirrors the existing extension e2e check, which caught a
993 ms mic drift.

### Visuals

- **Zoom and highlight:** on each scene, ease in toward the clicked element, hold, then ease out. The highlight is
  the existing purple outline style. Zoom can be toggled per scene.
- **Click indicator:** extension recordings don't show the mouse cursor in tab capture (to verify), so draw a click
  ring at each click position and time. Uploaded videos already show the cursor.
- **Captions:** from the narration with known clip timing, split into lines of about 42 characters and at most two
  lines. Exported as VTT and SRT, with an option to burn them into the MP4 (drawn with Pillow and overlaid, since
  common ffmpeg builds lack the subtitle filters).
- **Blur over time:** redaction boxes have to cover the whole video, not just click moments.
  - **Extension:** the content script also records redaction boxes when the page scrolls or changes (throttled, a
    few per second), not only at clicks.
  - **Uploads:** Gemini locates sensitive boxes at more frames than just the click frames, for example every couple
    of seconds and at scene changes. Each box applies until the next sample.

### Rendering

- Render **per scene** into segments, then concatenate, so editing one scene re-renders one segment.
- Output 1080p H.264 + AAC, tuned for screen content, aiming for about 20 MB for a 2-minute video.
- Show progress in the existing progress screen.
- When a scene re-renders after an edit, show an "Updating scene N…" state on that scene, not a full-page wait.

### Localization

- **Add language** (from the list Gemini TTS supports) translates the narration, article steps, title, intro and
  outro with `gemini-3.8-flash`, then synthesizes, re-times, captions and renders that language's video with the
  same pipeline.
- **One "don't translate" list** (product names, UI labels) is a workspace setting, applied to every translation.
- **Each language is its own editable version.**
  - Editing a scene re-renders only that scene in that language.
  - When the source language changes after a translation, that language's matching scenes and steps are marked
    **"Source changed, update?"**, never silently overwritten.
- **Voice:** the same voice is used where possible. Whether Voice Replication carries across languages needs testing
  (see "To verify"). The fallback is the closest stock voice in the target language.

### Editor

The existing article editor gains a **Video** view next to the **Article** view:
- the video player at the top, with captions;
- under it, the scene list: narration text, editable like step text today, with a small screenshot of the scene's
  click;
- per-scene tools: delete, merge with next, zoom on/off, hold longer;
- one voice setting per video;
- a language switcher with "Add language".

### Export for docs sites

- **"Export for docs"** downloads a zip:
  - `article.md`, with the video embedded at the top as an HTML `<video>` tag pointing at the MP4, with a captions
    `<track>`;
  - `images/`;
  - `video.mp4`;
  - `video.vtt`;
  - per language: `article.<lang>.md`, `video.<lang>.mp4`, `video.<lang>.vtt`.
- **Targets:** Mintlify, Docusaurus and similar Markdown/MDX sites. GitBook users upload the MP4 themselves.
- **Separate downloads:** MP4, VTT and SRT captions, and Markdown and HTML for the article, as today.

### Self-hosting

- **Setup:**
  - `docker compose up` runs the server and the built web app, with ffmpeg included, and reads `GEMINI_API_KEY` from
    `.env`;
  - the existing `uv` and `npm` route stays for developers;
  - the extension is loaded unpacked as today.
- **Server address:** today it is hard-coded to `127.0.0.1:8000` in `extension/offscreen.js` and `web/src/api.ts`.
  Make it configurable (an extension option, and same-origin for the web app when served by the server), so a team
  can run Stepcast on a shared machine.
- **README:** a customer-education lead must be able to set it up from the README alone.

## Decided by the founder

- First user: customer-education lead at a SaaS company.
- Biggest failures: a robotic voice, or video out of sync with narration.
- Edits are made to the script as text, not on a timeline.
- Open source and self-hosted, not a hosted SaaS.
- Output goes to a docs site.
- v1 includes localization, as Clueso does.
- No visual mockups needed during design.

## My calls (please check)

- **Rendering:** ffmpeg instead of Remotion, because of Remotion's company license.
- **Separate wording:** narration and article text are separate per step, with structural edits (delete, merge)
  shared.
- **Reordering** is article-only.
- **Own voice:** a one-time voice setup with Gemini's consent statement (forced by the API, and better than a
  checkbox), stored as a stateless key re-created from the local clips.
- **Voices:** a few curated AI voices, not a large library.
- **Glossary:** one workspace-wide "don't translate" list, since there are no projects.
- **Captions:** sidecar VTT/SRT by default, with burn-in as an export option.
- **Fallbacks:** no-speech recordings get narration written from the steps; no "keep my original audio" option.
- **Setup:** Docker Compose for one-command setup.
- **License:** left to the founder (MIT/Apache-2.0 for adoption, AGPL to deter hosted competitors). It doesn't change
  what gets built.

## To verify early (risks)

1. **Voice quality:** listen to the curated voices on real scripts before building on them. This is the top risk.
2. **Voice Replication:** whether a laptop-mic sample is good enough, and whether the replicated voice can speak
   other languages (the docs don't say).
3. **Cursor:** whether tab-capture recordings show the cursor (decides whether the click indicator is needed).
4. **Render speed:** per-scene ffmpeg rendering with zoom at 1080p on a laptop. Target about 2× the video's length
   or faster.
5. **File size:** about 20 MB for 2 minutes of 1080p screen content.

## Left to the builder

- Prompts for the script rewrite and translation.
- The exact sync rules: lead-in, speed-up limit, when to cut instead of speed up.
- The zoom curve and level, and the click-indicator style.
- Data model shape for scenes, voice clips, languages and stale flags, including migrating existing articles (they
  get scenes generated on first open, or with a "Make video" button).
- Job handling and progress for long renders (FastAPI background tasks today).
- Caption line breaking.
- Which TTS languages to test end to end. At least English, Spanish, German, French and Japanese.

## Testing

- **Unit:**
  - the re-timing function (sync guaranteed, limits respected);
  - caption timing;
  - the "source changed" marking;
  - export zip contents.
- **Pipeline:** with Gemini stubbed, as the existing tests do.
- **Live:** a short real recording through script → voice → render → sync check, in two languages.
- **End to end:** extension recording → video, with the automatic sync check on the output.
- **Listening and watching:** sample videos reviewed by a person before release. Automated checks can't judge "does
  this sound robotic".

## Decided during build

- **Voices (provisional, for the founder to confirm by ear):** Achird (friendly, the default), Sulafat (warm), Kore
  (firm), Aoede (breezy), Charon (informative). All eight candidates rendered cleanly in English, Spanish and German,
  at about 4 s per clip and a natural ~15 characters per second. An automated Gemini judge rated every voice the same,
  3/10, so it didn't help choose. Its one consistent note: slight pauses around English UI names inside Spanish and
  German sentences. Samples: `server/scripts/voice_samples.py`.
- **Cursor:** tab capture does not show the cursor (checked on the end-to-end recording). The click outline is
  drawn in every video, so nothing depends on it.
- **Own voice across languages:** untested until the founder records a sample and the consent statement. Translated
  videos fall back to the default voice if their voice fails.
- **Sync by construction:** scenes are rendered video-only and the voiceover is one WAV with each clip at its exact
  sample offset (per-scene AAC segments drift ~20 ms at every join). Freezes use ffmpeg `loop` (`tpad` on a single
  frame holds nothing on ffmpeg 7.1).
- **Blurring over time:** one blurred copy of the frame shown through a time-varying mask (a per-box filter chain
  took more than 10 minutes on a 2.5-minute video; now about 40 s). Each set of boxes covers the interval before it
  and after the next sample, so one missed detection leaves no gap. Uploads are sampled every 2 s and 0.8 s after
  each action, 8 frames per Gemini request, with usernames named in the rules. Samples live in `redact.json`.
- **Zoom:** in on the element before the first click, back out 0.5 s after the last, so the result is shown in full.
  The outline shows from 0.6 s before a click until 0.4 s after.
- **Measured:** the Atlan upload (2.5 min) became an article and a 93 s narrated video in under 3 minutes, and a
  Spanish version in 33 s. Videos are about 2.6–12 MB per 2 minutes. After the fixes, two automated scans found no
  readable personal data.
- **Burned-in captions:** the font is picked by glyph coverage (Noto in Docker). Scripts that need shaping (Arabic,
  Hindi, Thai) are refused where Pillow lacks raqm; the Docker image has it.
- **Voices, measured:** every sample clip is transcribed back and compared word for word
  (`server/scripts/voice_samples.py`). The five chosen voices score 0–5% word error in English, Spanish and German.
  Iapetus read Spanish as English (94% wrong) and is excluded.
  French and Japanese, checked last: 0–10% and 3% (Japanese scored on hiragana and kanji, since the transcript
  writes English UI names in katakana). Both rendered end to end in Docker in 51 s, with captions and burn-in.
- **Outlines on uploads:** elements are located on the frame at the click, trusting the mouse pointer over the
  guessed label, and the element's real visible name replaces the guess (which also fixes the narration). On the
  Atlan upload: about 22 of 23 correct by eye, up from about 13–17. `server/scripts/check_highlights.py` measures it.
  On the final Atlan run, two independent video reviews found no readable personal data, no wrong outline and nothing
  out of sync.
