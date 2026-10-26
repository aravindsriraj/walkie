import { type CSSProperties, type MouseEvent, useEffect, useRef, useState } from "react";
import { GITHUB_URL } from "./firstVisit";
import "./landing.css";

type Media = { said: string[]; script: string[]; samples: Record<string, string> };

const DEMO = [["en", "English"], ["es", "Español"], ["de", "Deutsch"], ["fr", "Français"], ["ja", "日本語"]] as const;
const FILLER = /\b(uh+|um+|er+|so yeah)\b/gi;
const RTL = new Set(["ar"]);

const calm = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

function nativeName(code: string): string {
  try {
    const name = new Intl.DisplayNames([code], { type: "language" }).of(code) ?? code;
    return name.charAt(0).toLocaleUpperCase(code) + name.slice(1); // "español" → "Español", like a menu item
  } catch {
    return code;
  }
}

// The app routes by the URL hash, so in-page links scroll instead of changing it.
function scrollTo(e: MouseEvent, id: string) {
  e.preventDefault();
  document.getElementById(id)?.scrollIntoView({ behavior: calm() ? "auto" : "smooth" });
}

/** Adds is-lit to an element once it scrolls into view (at once where IntersectionObserver is missing). */
function useLit<T extends Element>() {
  const ref = useRef<T>(null);
  const [lit, setLit] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return setLit(true);
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setLit(true); io.disconnect(); } }, { threshold: 0.35 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return [ref, lit] as const;
}

function Star({ big }: { big?: boolean }) {
  return (
    <a className={`l-btn ${big ? "l-primary" : "l-ghost"}`} href={GITHUB_URL} target="_blank" rel="noopener noreferrer">
      ★ Star on GitHub
    </a>
  );
}

function Demo() {
  const video = useRef<HTMLVideoElement>(null);
  const [lang, setLang] = useState("en");
  const [muted, setMuted] = useState(true);
  const resume = useRef<{ at: number; playing: boolean } | null>(null);

  useEffect(() => { if (video.current) video.current.muted = muted; }, [muted]);
  useEffect(() => {
    const v = video.current;
    if (!v) return;
    const r = resume.current;
    const ready = () => {
      if (r && Number.isFinite(v.duration)) v.currentTime = r.at * v.duration;
      if (r ? r.playing : !calm()) v.play()?.catch(() => {}); // browsers may refuse autoplay; the controls still work
    };
    v.addEventListener("loadedmetadata", ready, { once: true });
    v.load();
    return () => v.removeEventListener("loadedmetadata", ready);
  }, [lang]);

  const pick = (code: string) => {
    const v = video.current;
    resume.current = v && v.duration ? { at: v.currentTime / v.duration, playing: !v.paused } : null;
    setLang(code);
  };

  return (
    <figure className="l-demo">
      <div className="l-screen">
        <video ref={video} src={`/landing/${lang}.mp4`} muted playsInline loop controls preload="metadata"
          aria-label="A tutorial video Walkie made from one recording of a demo CRM">
          <track key={lang} kind="captions" src={`/landing/${lang}.vtt`} srcLang={lang} label={nativeName(lang)} default />
        </video>
        <button className="l-sound" onClick={() => setMuted((m) => !m)} aria-pressed={!muted}>
          {muted ? "Sound on" : "Sound off"}
        </button>
      </div>
      <div className="l-channels" role="group" aria-label="Language of the demo video">
        {DEMO.map(([code, name]) => (
          <button key={code} lang={code} aria-pressed={code === lang} onClick={() => pick(code)}>{name}</button>
        ))}
      </div>
      <figcaption>Made by Walkie from one recording of a demo CRM. Switch language: the same video, a new voice and captions.</figcaption>
    </figure>
  );
}

function marked(line: string) {
  return line.split(FILLER).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part));
}

function RoughTake({ media }: { media: Media }) {
  const [mix, setMix] = useState(50);
  return (
    <section className="l-section l-take" id="script" style={{ "--mix": mix / 100 } as CSSProperties}>
      <h2>Talk the way you normally would</h2>
      <p className="l-lede">Umms, restarts and all. On the left is what was said while recording the demo above; on the right,
        the script Walkie wrote from it and narrated.</p>
      <div className="l-take-cols">
        <div className="l-said">
          <h3>What you said</h3>
          {media.said.map((t, i) => <p key={i}>{marked(t)}</p>)}
        </div>
        <div className="l-clean">
          <h3>What Walkie says</h3>
          <ol>{media.script.map((t, i) => <li key={i}>{t}</li>)}</ol>
        </div>
      </div>
      <label className="l-mixer">
        <span>What you said</span>
        <input type="range" min={0} max={100} value={mix} onChange={(e) => setMix(Number(e.target.value))}
          aria-label="Compare what you said with what Walkie says" />
        <span>What Walkie says</span>
      </label>
    </section>
  );
}

const STEPS = [
  ["Record", "Click through the task in Chrome with the Walkie extension, talking if you like. Or upload a screen recording you already have."],
  ["Edit the script as text", "Change a sentence and only that scene is re-recorded and re-rendered. Merge, delete, or hold a busy screen longer."],
  ["Export to your docs", "One zip with Markdown, screenshots, the video and captions, for every language."],
];

function Step({ n, title, body }: { n: number; title: string; body: string }) {
  const [ref, lit] = useLit<HTMLLIElement>();
  return (
    <li ref={ref} className={lit ? "is-lit" : ""} style={{ transitionDelay: `${n * 120}ms` }}>
      <span className="l-step-n" aria-hidden="true">{n + 1}</span>
      <h3>{title}</h3>
      <p>{body}</p>
    </li>
  );
}

function Features() {
  const [ref, lit] = useLit<HTMLDivElement>();
  return (
    <section className="l-section" id="features">
      <h2>What Walkie takes care of</h2>
      <div ref={ref} className={`l-features${lit ? " is-lit" : ""}`}>
        <article className="l-feature l-wide">
          <div className="l-art l-art-sync" aria-hidden="true">
            <span>Click</span><span>New</span><span>deal</span><span>to</span><span>start.</span><i />
          </div>
          <h3>Always in sync</h3>
          <p>Each click lands just after its sentence starts. The video is cut to fit the voice, not the other way round,
            and every translation is re-timed the same way.</p>
        </article>
        <article className="l-feature">
          <div className="l-art l-art-voice" aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /></div>
          <h3>Your own voice</h3>
          <p>Record a short sample once, and Walkie narrates in your voice, translations included, without retakes.</p>
        </article>
        <article className="l-feature">
          <div className="l-art l-art-edit" aria-hidden="true"><span>Choose a <em><b>stage</b><b>contact</b></em> for the deal.</span></div>
          <h3>Edit a sentence, not a timeline</h3>
          <p>Fix a word in the script and only that scene is re-rendered.</p>
        </article>
        <article className="l-feature">
          <div className="l-art l-art-zoom" aria-hidden="true"><div><i /></div></div>
          <h3>Zoom and an outline on every click</h3>
          <p>Viewers see exactly where to click, without hunting for a cursor.</p>
        </article>
        <article className="l-feature">
          <div className="l-art l-art-blur" aria-hidden="true"><span>maya.chen@example.com</span></div>
          <h3>Personal data blurred</h3>
          <p>Passwords, emails and other personal details are blurred for the whole video, not just at the clicks.</p>
        </article>
        <article className="l-feature">
          <div className="l-art l-art-files" aria-hidden="true"><span>article.md</span><span>video.mp4</span><span>video.vtt</span></div>
          <h3>Ready for your docs site</h3>
          <p>Markdown that also works as MDX, an MP4, and VTT and SRT captions.</p>
        </article>
      </div>
    </section>
  );
}

function Languages({ samples }: { samples: Record<string, string> }) {
  const [active, setActive] = useState("en");
  return (
    <section className="l-section" id="languages">
      <h2>20 languages from one recording</h2>
      <p className="l-lede">Each language gets its own voiceover, re-timed video, captions and article, and each one can be
        edited on its own. Point at a language to read the same line in it.</p>
      <p className="l-sample" lang={active} dir={RTL.has(active) ? "rtl" : "ltr"} aria-live="polite">{samples[active]}</p>
      <div className="l-langs">
        {Object.keys(samples).map((code) => (
          <button key={code} lang={code} aria-pressed={code === active} onMouseEnter={() => setActive(code)}
            onFocus={() => setActive(code)} onClick={() => setActive(code)}>{nativeName(code)}</button>
        ))}
      </div>
    </section>
  );
}

export function Landing({ onStart }: { onStart: () => void }) {
  const [media, setMedia] = useState<Media | null>(null);
  useEffect(() => {
    document.title = "Walkie: narrated tutorial videos from one walkthrough";
    let stop = false;
    fetch("/landing/landing.json").then((r) => r.json()).then((m: Media) => { if (!stop) setMedia(m); }).catch(() => {});
    return () => { stop = true; };
  }, []);

  const start = <button className="l-btn l-primary" onClick={onStart}>Start your first walkthrough</button>;

  return (
    <div className="landing">
      <header className="l-bar">
        <span className="l-wordmark"><span className="mark" aria-hidden="true" />Walkie</span>
        <nav aria-label="On this page">
          <a href="#how" onClick={(e) => scrollTo(e, "how")}>How it works</a>
          <a href="#features" onClick={(e) => scrollTo(e, "features")}>Features</a>
          <a href="#languages" onClick={(e) => scrollTo(e, "languages")}>Languages</a>
          <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer">★ GitHub</a>
        </nav>
        <button className="l-btn l-small" onClick={onStart}>Open Walkie</button>
      </header>

      <main>
        <section className="l-hero">
          <h1>Walk through it once.{" "}<br />Walkie does the talking.</h1>
          <p className="l-sub">A narrated tutorial video and help article, in 20 languages, ready for your docs site.</p>
          <div className="l-actions">{start}<Star /></div>
          <Demo />
        </section>

        {media && <RoughTake media={media} />}

        <section className="l-section" id="how">
          <h2>From one walkthrough to your docs</h2>
          <ol className="l-steps">{STEPS.map(([title, body], n) => <Step key={title} n={n} title={title} body={body} />)}</ol>
        </section>

        <Features />

        {media && <Languages samples={media.samples} />}

        <section className="l-section l-own" id="open-source">
          <h2>Runs on your machine</h2>
          <ul>
            <li><b>Your recordings stay with you.</b> Only the AI calls leave your computer, using your own Gemini API key.</li>
            <li><b>No accounts, no tracking.</b> Walkie is for one team on one machine or a private network.</li>
            <li><b>Open source.</b> Apache-2.0: read it, change it, run it wherever you like.</li>
          </ul>
        </section>

        <section className="l-section l-support">
          <h2>Walkie is free and open source. If it saved you a retake, give it a star.</h2>
          <div className="l-actions"><Star big /><a className="l-btn l-ghost" href={GITHUB_URL} target="_blank" rel="noopener noreferrer">View the code</a></div>
        </section>

        <section className="l-section l-final">
          <h2>Your next tutorial is one walkthrough away.</h2>
          <div className="l-actions">{start}</div>
        </section>
      </main>

      <footer className="l-foot">
        <span className="l-wordmark"><span className="mark" aria-hidden="true" />Walkie</span>
        <a href={GITHUB_URL} target="_blank" rel="noopener noreferrer">GitHub</a>
        <a href={`${GITHUB_URL}/blob/main/LICENSE`} target="_blank" rel="noopener noreferrer">License</a>
        <a href={`${GITHUB_URL}#readme`} target="_blank" rel="noopener noreferrer">README</a>
      </footer>
    </div>
  );
}
