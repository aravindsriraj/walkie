import { useEffect, useRef, useState } from "react";
import { forgetMyVoice, getGlossary, getMyVoice, getPronunciations, saveGlossary, savePronunciations, setUpMyVoice } from "./api";
import { formatPronunciations, parsePronunciations } from "./pronounce";

const SAMPLE_TEXT =
  "Hi, I'm recording a short sample of my voice. In a moment I'll walk you through a feature step by step: " +
  "where to click, what to type, and what happens next. Good tutorials are calm and clear, so I'm speaking at my " +
  "usual pace, in the room where I record my product videos.";
// Gemini requires this exact statement, spoken by the same person, before it will copy a voice.
const CONSENT_TEXT =
  "I am the owner of this voice and I consent to Google using this voice to create a synthetic voice model.";
const MIN_SAMPLE_S = 10;
const MAX_S = 30;

/** Record from the microphone in the browser. Stops by itself after MAX_S seconds. */
function Recorder({ label, script, min, onDone }: {
  label: string;
  script: string;
  min: number;
  onDone: (clip: Blob | null) => void;
}) {
  const [state, setState] = useState<"idle" | "recording" | "done">("idle");
  const [seconds, setSeconds] = useState(0);
  const [url, setUrl] = useState("");
  const [error, setError] = useState("");
  const rec = useRef<MediaRecorder | null>(null);
  const timer = useRef(0);

  useEffect(() => () => { clearInterval(timer.current); rec.current?.stream.getTracks().forEach((t) => t.stop()); }, []);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);

  const start = async () => {
    setError("");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      return setError("Walkie can't use your microphone. Allow it in the browser's address bar, then try again.");
    }
    const chunks: Blob[] = [];
    const r = new MediaRecorder(stream);
    r.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    const began = Date.now();
    r.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      clearInterval(timer.current);
      const took = (Date.now() - began) / 1000;
      const clip = new Blob(chunks, { type: r.mimeType });
      setUrl(URL.createObjectURL(clip));
      setState("done");
      if (took < min) {
        setError(`That was ${Math.round(took)} seconds. Record at least ${min}.`);
        onDone(null);
      } else {
        onDone(clip);
      }
    };
    rec.current = r;
    r.start();
    setSeconds(0);
    setState("recording");
    timer.current = window.setInterval(() => {
      const s = Math.floor((Date.now() - began) / 1000);
      setSeconds(s);
      if (s >= MAX_S) r.stop();
    }, 250);
  };

  return (
    <div className="recorder">
      <p className="recorder-label">{label}</p>
      <blockquote className="recorder-script">{script}</blockquote>
      <div className="recorder-controls">
        {state === "recording" ? (
          <button className="button record is-on" onClick={() => rec.current?.stop()}>
            <span className="record-dot" aria-hidden="true" /> Stop <span className="record-time">{seconds}s</span>
          </button>
        ) : (
          <button className="button record" onClick={start}>
            <span className="record-dot" aria-hidden="true" /> {state === "done" ? "Record again" : "Record"}
          </button>
        )}
        {state === "done" && url && <audio controls src={url} aria-label={`Play back: ${label}`} />}
      </div>
      {error && <p className="error-text" role="alert">{error}</p>}
    </div>
  );
}

function VoiceSection() {
  const [ready, setReady] = useState<boolean | null>(null);
  const [sample, setSample] = useState<Blob | null>(null);
  const [consent, setConsent] = useState<Blob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [round, setRound] = useState(0); // remounts the recorders after removing a voice

  useEffect(() => { getMyVoice().then((v) => setReady(v.ready)).catch(() => setReady(false)); }, []);

  const save = async () => {
    if (!sample || !consent) return;
    setBusy(true);
    setError("");
    try {
      await setUpMyVoice(sample, consent);
      setReady(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="settings-section" aria-labelledby="voice-h">
      <h3 id="voice-h">Your voice</h3>
      {ready === null ? null : ready ? (
        <div className="voice-ready">
          <p>Your voice is ready. Choose <strong>My voice</strong> in any video.</p>
          <button className="button quiet-danger" onClick={async () => {
            await forgetMyVoice();
            setReady(false);
            setSample(null);
            setConsent(null);
            setRound((n) => n + 1);
          }}>Remove my voice</button>
        </div>
      ) : (
        <>
          <p className="settings-hint">
            Narrate videos in your own voice, without the retakes. Record two short clips in the same quiet place.
          </p>
          <Recorder key={`s${round}`} label="1. Read this aloud, at your normal pace" script={SAMPLE_TEXT}
            min={MIN_SAMPLE_S} onDone={setSample} />
          <Recorder key={`c${round}`} label="2. Then read this sentence exactly" script={CONSENT_TEXT} min={3}
            onDone={setConsent} />
          {error && <p className="error-text" role="alert">{error}</p>}
          <div className="settings-actions">
            <button className="button primary" disabled={!sample || !consent || busy} onClick={save}>
              {busy ? "Setting up…" : "Use my voice"}
            </button>
          </div>
        </>
      )}
      <p className="settings-note">
        Your recordings stay on this computer. Gemini makes a temporary voice from them each week and keeps nothing.
      </p>
    </section>
  );
}

function PronunciationSection() {
  const [text, setText] = useState("");
  const [saved, setSaved] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    // Keep anything typed while the saved list was loading.
    getPronunciations().then((p) => { const t = formatPronunciations(p.words); setText((cur) => cur || t); setSaved(t); }).catch(() => {});
  }, []);

  const save = async () => {
    if (text === saved) return;
    try {
      const t = formatPronunciations((await savePronunciations(parsePronunciations(text))).words);
      setText(t);
      setSaved(t);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <section className="settings-section" aria-labelledby="say-h">
      <h3 id="say-h">Pronunciations</h3>
      <p className="settings-hint">
        How the voice should say product names and jargon, one per line: <strong>word = how to say it</strong>. Captions
        and articles keep the real spelling. Videos use it the next time they're updated.
      </p>
      <textarea className="keep-list" rows={4} value={text} onChange={(e) => setText(e.target.value)} onBlur={save}
        aria-labelledby="say-h" placeholder={"SQL = sequel\nnginx = engine x"} />
      <p className="settings-hint" aria-live="polite">{error ? <span className="error-text">{error}</span> : text === saved && saved ? "Saved" : ""}</p>
    </section>
  );
}

function GlossarySection() {
  const [text, setText] = useState("");
  const [saved, setSaved] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    getGlossary().then((g) => { setText((cur) => cur || g.words.join("\n")); setSaved(g.words.join("\n")); }).catch(() => {});
  }, []);

  const save = async () => {
    if (text === saved) return;
    try {
      const g = await saveGlossary(text.split("\n"));
      setText(g.words.join("\n"));
      setSaved(g.words.join("\n"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <section className="settings-section" aria-labelledby="keep-h">
      <h3 id="keep-h">Don't translate</h3>
      <p className="settings-hint">Product names and button labels that should stay as they are, one per line.</p>
      <textarea className="keep-list" rows={5} value={text} onChange={(e) => setText(e.target.value)} onBlur={save}
        aria-labelledby="keep-h" placeholder={"Acmeflow\nWorkspace"} />
      <p className="settings-hint" aria-live="polite">{error ? <span className="error-text">{error}</span> : text === saved && saved ? "Saved" : ""}</p>
    </section>
  );
}

export function SettingsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (open) ref.current?.showModal();
    else ref.current?.close();
  }, [open]);
  return (
    <dialog ref={ref} className="dialog settings" onClose={onClose} aria-labelledby="settings-title">
      <div className="dialog-head">
        <h2 id="settings-title">Settings</h2>
        <button className="dialog-close" onClick={onClose} aria-label="Close">×</button>
      </div>
      {open && (
        <>
          <VoiceSection />
          <PronunciationSection />
          <GlossarySection />
        </>
      )}
    </dialog>
  );
}

export function SettingsButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="button" onClick={() => setOpen(true)}>Settings</button>
      <SettingsDialog open={open} onClose={() => setOpen(false)} />
    </>
  );
}
