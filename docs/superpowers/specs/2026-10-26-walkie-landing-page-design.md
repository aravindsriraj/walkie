# Walkie: rename and landing page

Date: 2026-10-26. Status: draft for the founder's review.

## Intent

The product is now called **Walkie** (was Stepcast). Walkie needs a landing page: the first thing someone sees when
they open it, telling them clearly and interactively what Walkie does, the way a good AI product's landing page
does, and then getting them into the product. Today a first-time visitor lands straight on an empty library with no
explanation.

The page also asks visitors to support the project by starring the GitHub repository.

## Goals

1. **Rename Stepcast to Walkie** everywhere a person or a developer sees the name: the app's wordmark and page title,
   the Chrome extension, the share and print pages, the README and its screenshots, Docker, and settings names.
2. **A landing page** shown the first time someone opens Walkie, in the "Studio" look the founder chose: dark and
   cinematic, with the video front and centre and a purple glow.
3. **One main action:** "Start your first walkthrough" opens the Walkie home screen (the library). After that,
   opening Walkie goes straight to the library.
4. **Star the project:** a "★ Star on GitHub" button in the top bar and hero, and a "Support the project" section.
5. **A way back:** an "About Walkie" link on the home screen opens the landing page again.

## Non-goals

- Sign-up, accounts, a waitlist, pricing, or a separate hosted marketing site.
- A live GitHub star count (the repository isn't public yet, and the count isn't needed to ask for a star).
- Analytics or tracking of any kind.
- Testimonials, customer logos or usage numbers: Walkie has none yet.

## Anti-goals (failure even if it works)

- **Claims Walkie can't back up.** Every statement on the page matches what Walkie does today. No made-up numbers
  ("in 2 minutes", "10× faster").
- **A staged demo passed off as real.** The demo video and the "rough take" are real Walkie input and output.
- **Getting in the way of work.** A returning user never has to click through the landing page to reach their
  articles, and shared article links (`/a/{id}`) and editor links (`#/a/{id}`) open directly as they do today.
- **A slow first impression.** The page must feel instant; videos load only when needed.
- **Showing a real company's product.** Demo footage uses the Acme demo app from `e2e/site/`, not Atlan or anyone
  else's product.

## The page, top to bottom (approved by the founder)

1. **Top bar:** Walkie wordmark; links to How it works, Features, Languages; "★ GitHub"; an "Open Walkie" button
   (same destination as the main action).
2. **Hero:** "Walk through it once. Walkie does the talking." One line: a narrated tutorial video and help article,
   in 20 languages, ready for your docs site. Buttons: **Start your first walkthrough** (main) and **★ Star on
   GitHub**. Below them, a real Walkie-made demo video of the Acme app, muted autoplay with a clear "sound on"
   control, captions on. Language pills **EN ES DE FR JA**: clicking one switches the same video to that language's
   voiceover and captions.
3. **From rough take to clean script:** what a person actually said while recording, next to the script Walkie wrote
   from it. A slider moves between "what you said" and "what Walkie says". Real data only (see Open questions).
4. **How it works:** three steps: record in Chrome or upload a video; edit the script as text; export to your docs
   site. The steps light up in turn as the visitor scrolls.
5. **Features, six cards, each with a small looping animation:**
   - always in sync: each click lands just after its sentence starts;
   - your own voice, which also speaks the translations;
   - edit a sentence, and only that scene re-renders;
   - zoom and an outline on every click;
   - passwords and emails blurred for the whole video;
   - docs-ready export: Markdown that also works as MDX, MP4, and captions.
6. **20 languages:** all 20 as chips (from `GET /languages`). Hovering or tapping one shows a sample line in that
   language. The sample lines are real Walkie translations of one source line, generated once and stored with the page.
7. **Open source and private:** runs on your own machine; recordings stay there apart from the Gemini calls; bring
   your own Gemini key; no accounts; Apache-2.0.
8. **Support the project:** "Walkie is free and open source. If it saved you a retake, give it a star." Big **★ Star on
   GitHub** button and **View the code**.
9. **Final call:** "Your next tutorial is one walkthrough away." with **Start your first walkthrough**. Footer:
   GitHub, License, README.

## Constraints

- **Lives in the existing web app** (React + Vite, `web/`), served by the same server, no new runtime dependencies.
  Animations in CSS (and a little SVG); no animation or UI library.
- **Routing stays hash-based**, as `web/src/App.tsx` does today. The landing page is a view of the app at its root,
  shown when nothing else is asked for and the visitor hasn't seen it yet.
- **"Seen it" is remembered per browser** (local storage), wrapped so a blocked or empty storage simply shows the page
  again rather than breaking.
- **Always dark** (the Studio look), independent of the app's light/dark theme. Uses Geist, already loaded.
- **Works at phone width** with no sideways scrolling; keyboard-usable; honours "reduce motion" (animations stop,
  videos don't autoplay); the demo video has captions; images and videos have text alternatives.
- **Demo media is static files** in the web app's public folder: per language (en, es, de, fr, ja) a short MP4 and its
  VTT captions, made by Walkie from one recording of the Acme demo app, sized for the web (target: the five videos
  together under about 8 MB).
- **GitHub address in one place** in the code, so it is easy to change.

## Rename details

- The visible name becomes **Walkie** in the app, the extension (name, popup, options, permission page), share and
  print pages, Docker (image and service), README, and docs going forward. Past design documents keep their history
  and are not rewritten.
- Settings and markers renamed: `STEPCAST_*` environment variables become `WALKIE_*`, and the page marker
  `data-stepcast-redact` becomes `data-walkie-redact`. There are no outside users yet, so no compatibility shims.
- The README screenshots that show the old wordmark are retaken.

## Left to the builder

- Component structure, file names, and how the language switch keeps the viewer's place (for example, jumping to the
  start of the same scene in the new language).
- The exact animations, spacing and type scale, within the approved Studio look.
- How the demo media and the 20 sample lines are generated (a small script is fine), as long as they are real
  Walkie output and the steps to regenerate them are written down.
- Tests: at least the first-visit rule (landing shown once, then the library; About Walkie brings it back; editor and
  share links never show it) and the rename (no "Stepcast" left outside past documents).

## Decided by the founder

- Look: "Studio" (dark, cinematic, video front and centre).
- Main action: open the Walkie home screen; shown on first open only.
- The section list above, as approved.
- GitHub repository: `https://github.com/aravindsriraj/walkie`.
- The rough take: the founder records 30–60 seconds walking through the Acme demo app, talking naturally. The section
  shows what they said (Walkie's transcript) beside the script Walkie wrote from it. The builder starts the demo app
  and tells the founder when to record.

## My calls (please check)

- The landing page is always dark, whatever the app's theme.
- "Seen it" is remembered per browser; a new browser sees the page once.
- The current logo mark stays, with the new name; no new logo in this project.
- The demo video uses the five languages already checked by ear and by the voice check (en, es, de, fr, ja).
- No compatibility for the old `STEPCAST_*` names, since there are no outside users yet.
