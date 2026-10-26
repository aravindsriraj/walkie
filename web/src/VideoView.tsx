import { useEffect, useRef, useState } from "react";
import { type Article, captionsUrl, getVoices, imageUrl, NO_VIDEO, type Step, videoUrl } from "./api";

const HOLDS = [0, 1000, 2000, 3000];

/** A textarea that grows with its text, like the article's fields. */
function Narration({ value, label, onChange }: { value: string; label: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) { el.style.height = "auto"; el.style.height = `${el.scrollHeight}px`; }
  }, [value]);
  return <textarea ref={ref} rows={1} className="narration" value={value} aria-label={label}
    placeholder="Nothing is said in this scene" onChange={(e) => onChange(e.target.value.replace(/\n/g, " "))} />;
}

function Player({ a, lang }: { a: Article; lang: string }) {
  const v = a.videos[lang] ?? NO_VIDEO;
  return (
    <div className="player">
      <video key={v.version} controls preload="metadata" src={videoUrl(a.id, lang, v.version)}>
        <track kind="captions" default srcLang={lang} label="Captions" src={captionsUrl(a.id, lang, v.version)} />
      </video>
    </div>
  );
}

export function VideoView({ a, lang, onNarration, onStep, onVoice, onMerge, onDelete, onMake, onRetry, onSettings }: {
  a: Article;
  lang: string;
  onNarration: (stepId: string, text: string) => void;
  onStep: (stepId: string, patch: Partial<Step>) => void;
  onVoice: (voice: string) => void;
  onMerge: (stepId: string) => void;
  onDelete: (stepId: string) => void;
  onMake: () => void;
  onRetry: () => void;
  onSettings: () => void;
}) {
  const [voices, setVoices] = useState<{ id: string; label: string }[]>([]);
  const [mine, setMine] = useState(false);
  useEffect(() => {
    getVoices().then((r) => { setVoices(r.voices); setMine(r.mine); }).catch(() => {});
  }, []);

  const source = lang === a.lang;
  const v = a.videos[lang] ?? NO_VIDEO;
  const scenes = [...a.steps].sort((x, y) => x.event_ids[0] - y.event_ids[0]); // the video plays in recorded order
  const tr = a.translations[lang];
  const stale = new Set(a.stale[lang] ?? []);
  const say = (s: Step) => (source ? s.narration : tr?.steps[s.id]?.narration ?? "");
  const updating = new Set(v.updating);

  if (v.status === "none" && source) {
    return (
      <div className="video-empty">
        <h2>Turn this article into a narrated video</h2>
        <p>
          Walkie writes a script from your steps and what you said, records a natural voiceover, and zooms in on
          every click. Edit the script here and the video follows.
        </p>
        <button className="button primary" onClick={onMake}>Make video</button>
      </div>
    );
  }

  return (
    <div className="video-view">
      {v.version > 0 ? <Player a={a} lang={lang} /> : <div className="player is-empty" aria-hidden="true" />}

      <div className="video-bar">
        {v.status === "rendering" ? (
          <p className="video-status is-busy" role="status">{v.stage || "Updating the video"}…</p>
        ) : v.status === "failed" ? (
          <p className="video-status is-failed" role="alert">
            {v.error} <button className="link" onClick={onRetry}>Try again</button>
          </p>
        ) : (
          <p className="video-status">{v.version > 0 ? "Up to date" : ""}</p>
        )}
        <label className="voice-pick">
          Voice
          <select value={a.voice} disabled={!source} onChange={(e) => {
            if (e.target.value === "setup") onSettings();
            else onVoice(e.target.value);
          }}>
            {voices.map((x, i) => (
              <option key={x.id} value={i === 0 ? "" : x.id}>{x.id}, {x.label.toLowerCase()}</option>
            ))}
            {mine ? <option value="mine">My voice</option> : <option value="setup">Set up my voice…</option>}
          </select>
        </label>
      </div>
      {v.note && <p className="video-note">{v.note}</p>}

      <ol className="scenes">
        {scenes.map((s, n) => (
          <li key={s.id} className={`scene${updating.has(s.id) ? " is-updating" : ""}`} aria-busy={updating.has(s.id)}>
            <span className="step-num" aria-hidden="true">{n + 1}</span>
            <div className="scene-body">
              <Narration value={say(s)} label={`Narration for scene ${n + 1}`} onChange={(t) => onNarration(s.id, t)} />
              {!source && stale.has(s.id) && <p className="scene-flag">The original changed since this was translated.</p>}
              {updating.has(s.id) && <p className="scene-flag is-busy">Updating…</p>}
              {source && (
                <div className="scene-tools">
                  <label className="toggle">
                    <input type="checkbox" checked={s.video_zoom} onChange={(e) => onStep(s.id, { video_zoom: e.target.checked })} />
                    Zoom in
                  </label>
                  <label className="hold">
                    Hold
                    <select value={s.hold_ms} onChange={(e) => onStep(s.id, { hold_ms: Number(e.target.value) })}>
                      {HOLDS.map((h) => <option key={h} value={h}>{h ? `+${h / 1000} s` : "No extra"}</option>)}
                    </select>
                  </label>
                  <button onClick={() => onMerge(s.id)} disabled={n === scenes.length - 1}>Merge with next</button>
                  <button className="danger" onClick={() => onDelete(s.id)}>Delete</button>
                </div>
              )}
            </div>
            <img className="scene-shot" src={imageUrl(a.id, s)} alt="" />
          </li>
        ))}
      </ol>
    </div>
  );
}
