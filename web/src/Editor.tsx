import { useEffect, useRef, useState } from "react";
import { API, type Article, fileUrl, getArticle, imageUrl, renderClips, saveArticle, type Step } from "./api";
import { mergeNext, move, remove } from "./stepOps";

function AutoText({ value, onChange, className, placeholder }: {
  value: string; onChange: (v: string) => void; className?: string; placeholder?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) { el.style.height = "auto"; el.style.height = `${el.scrollHeight}px`; }
  }, [value]);
  return <textarea ref={ref} rows={1} className={className} value={value} placeholder={placeholder}
    onChange={(e) => onChange(e.target.value)} />;
}

export function Editor({ id }: { id: string }) {
  const [a, setA] = useState<Article | null>(null);
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  // Poll while the server is still writing the article or rendering clips.
  // Once the article is ready, only clip fields are merged in so local edits survive.
  const polling = !a || a.status === "processing" || a.clips_status === "rendering";
  useEffect(() => {
    if (!polling) return;
    let stop = false;
    let timer = 0;
    const load = async () => {
      try {
        const next = await getArticle(id);
        if (stop) return;
        setA((cur) => (!cur || cur.status !== "ready" ? next : {
          ...cur, clips_status: next.clips_status,
          steps: cur.steps.map((s) => ({ ...s, clip: next.steps.find((n) => n.id === s.id)?.clip ?? s.clip })),
        }));
        if (next.status === "processing" || next.clips_status === "rendering") timer = window.setTimeout(load, 2000);
      } catch (e) {
        setError((e as Error).message);
      }
    };
    load();
    return () => { stop = true; clearTimeout(timer); };
  }, [id, polling]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) e.preventDefault(); };
    addEventListener("beforeunload", warn);
    return () => removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (error) return <p className="error">{error}</p>;
  if (!a) return <p className="muted">Loading…</p>;
  if (a.status === "processing")
    return <div className="empty"><div className="spinner" /><h2>Writing your article…</h2><p className="muted">Grabbing screenshots and drafting the steps. This usually takes under a minute.</p></div>;
  if (a.status === "failed")
    return <div className="empty"><h2>Couldn't create this article</h2><p className="error">{a.error}</p></div>;

  const edit = (patch: Partial<Article>) => { setA({ ...a, ...patch }); setDirty(true); setMsg(""); };
  const setSteps = (steps: Step[]) => edit({ steps });
  const setStep = (i: number, patch: Partial<Step>) => setSteps(a.steps.map((s, k) => (k === i ? { ...s, ...patch } : s)));

  const save = async () => {
    try {
      setA(await saveArticle(a));
      setDirty(false);
      setMsg("Saved");
    } catch (e) {
      setMsg(`Save failed: ${(e as Error).message}`);
    }
  };
  const clips = async () => {
    if (dirty) await save();
    await renderClips(a.id);
    setA({ ...a, clips_status: "rendering" });
  };

  const share = `${API}/a/${a.id}`;
  return (
    <div className="editor">
      <div className="toolbar">
        <button className="primary" onClick={save} disabled={!dirty}>{dirty ? "Save" : "Saved"}</button>
        <span className="muted msg">{msg}</span>
        <span className="spacer" />
        <a className="btn" href={share} target="_blank" title={dirty ? "Save first to share your edits" : ""}>Open share page</a>
        <a className="btn" href={`${share}?print=1`} target="_blank">PDF</a>
        <a className="btn" href={`${API}/articles/${a.id}/export.md.zip`}>Markdown</a>
        <a className="btn" href={`${API}/articles/${a.id}/export.html`}>HTML</a>
        <button className="btn" onClick={clips} disabled={a.clips_status === "rendering"}>
          {a.clips_status === "rendering" ? "Rendering clips…" : a.clips_status === "ready" ? "Re-render clips" : "Render clips"}
        </button>
      </div>
      {a.clips_status === "failed" && <p className="error">Clip rendering failed. Check the server log and try again.</p>}

      <AutoText className="title" value={a.title} onChange={(title) => edit({ title })} placeholder="Article title" />
      <AutoText className="prose" value={a.intro} onChange={(intro) => edit({ intro })} placeholder="Intro" />

      <ol className="steps">
        {a.steps.map((s, i) => (
          <li key={s.id} className="step">
            <div className="step-head">
              <span className="num">{i + 1}</span>
              <AutoText className="prose step-text" value={s.text} onChange={(text) => setStep(i, { text })} />
              <div className="step-actions">
                <button title="Move up" onClick={() => setSteps(move(a.steps, i, -1))} disabled={i === 0}>↑</button>
                <button title="Move down" onClick={() => setSteps(move(a.steps, i, 1))} disabled={i === a.steps.length - 1}>↓</button>
                <button title="Merge with next step" onClick={() => setSteps(mergeNext(a.steps, i))} disabled={i === a.steps.length - 1}>Merge ↓</button>
                <button title="Delete step" onClick={() => setSteps(remove(a.steps, i))}>Delete</button>
              </div>
            </div>
            <div className="media">
              <img src={imageUrl(a.id, s)} alt={`Step ${i + 1}`} />
              {s.clip && <video src={fileUrl(a.id, s.clip)} controls muted loop playsInline />}
            </div>
            <label className="toggle">
              <input type="checkbox" checked={s.zoomed} onChange={(e) => setStep(i, { zoomed: e.target.checked })} /> Zoom into the element
            </label>
          </li>
        ))}
      </ol>
      <AutoText className="prose" value={a.outro} onChange={(outro) => edit({ outro })} placeholder="Outro" />
    </div>
  );
}
