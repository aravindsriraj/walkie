import { useCallback, useEffect, useRef, useState } from "react";
import {
  addLanguage, type Article, getArticle, imageUrl, makeVideo, NO_VIDEO, removeLanguage, renderVideo, saveArticle,
  saveTranslation, type Step, type Translation, updateTranslation, type VideoState,
} from "./api";
import { ConfirmDelete } from "./ConfirmDelete";
import { LanguageMenu } from "./LanguageMenu";
import { Progress } from "./Progress";
import { RichText } from "./RichText";
import { SettingsDialog } from "./Settings";
import { ShareMenu } from "./ShareMenu";
import { StepRail } from "./StepRail";
import { TopBar } from "./TopBar";
import { mergeIds, mergeNext, moveTo, remove } from "./stepOps";
import { affectsTranslationVideo, affectsVideo, serverCopy } from "./videoEdits";
import { VideoView } from "./VideoView";

type SaveState = "saved" | "saving" | "error";
type View = "article" | "video";
const RENDER_DELAY = 1500; // after the last edit that changes the video, ask for a re-render

function TitleField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) { el.style.height = "auto"; el.style.height = `${el.scrollHeight}px`; }
  }, [value]);
  return <textarea ref={ref} rows={1} className="title" value={value} placeholder="Article title" aria-label="Title"
    onChange={(e) => onChange(e.target.value.replace(/\n/g, " "))} />;
}

const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const working = (a: Article | null) =>
  a?.status === "processing" || Object.values(a?.videos ?? {}).some((v) => v.status === "rendering");

export function Editor({ id }: { id: string }) {
  const [a, setA] = useState<Article | null>(null);
  const [error, setError] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [undo, setUndo] = useState<{ message: string; steps: Step[] } | null>(null);
  const [active, setActive] = useState(0);
  const [confirming, setConfirming] = useState(false);
  const [noteHidden, setNoteHidden] = useState(false);
  const [view, setView] = useState<View>("article");
  const [pickedLang, setPickedLang] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settingsRound, setSettingsRound] = useState(0);
  const stepEls = useRef<(HTMLElement | null)[]>([]);

  // Autosave state. Edits bump `version`; saves run one at a time so an older save never lands after a newer one.
  const latest = useRef<Article | null>(null);
  latest.current = a;
  const version = useRef(0);
  const savedVersion = useRef(0);
  const chain = useRef<Promise<void>>(Promise.resolve());
  const articleDirty = useRef(false);
  const dirtyLangs = useRef(new Set<string>());
  const lastSaved = useRef<Article | null>(null); // what the server has: decides whether an edit needs a re-render
  const renderTimers = useRef<Record<string, number>>({});

  const setVideo = useCallback((lang: string, patch: Partial<VideoState>) => {
    setA((cur) => cur && ({ ...cur, videos: { ...cur.videos, [lang]: { ...(cur.videos[lang] ?? NO_VIDEO), ...patch } } }));
  }, []);

  // Server-side work (writing the article, making videos, translating) shows up by polling. While the article is
  // editable, only what the server owns is taken from the poll, so typing is never overwritten.
  const merge = useCallback((cur: Article | null, next: Article): Article => {
    if (!cur || cur.status !== "ready" || next.status !== "ready") return next;
    const pending = version.current !== savedVersion.current;
    const translations = { ...next.translations };
    for (const l of dirtyLangs.current) if (cur.translations[l]) translations[l] = cur.translations[l];
    const steps = pending ? cur.steps : cur.steps.map((s) => {
      const fresh = next.steps.find((x) => x.id === s.id);
      return !s.narration && fresh?.narration ? { ...s, narration: fresh.narration } : s;
    });
    return { ...cur, steps, translations, videos: next.videos, stale: next.stale, lang: next.lang };
  }, []);

  useEffect(() => {
    let stop = false;
    getArticle(id).then((next) => {
      if (stop) return;
      lastSaved.current = next;
      setA(next);
    }).catch((e) => setError((e as Error).message));
    return () => { stop = true; };
  }, [id]);

  const polling = working(a);
  useEffect(() => {
    if (!polling) return;
    const t = setInterval(async () => {
      try {
        const next = await getArticle(id);
        lastSaved.current = serverCopy(lastSaved.current, next, version.current !== savedVersion.current);
        setA((cur) => merge(cur, next));
      } catch { /* keep polling; the next try may work */ }
    }, 1200);
    return () => clearInterval(t);
  }, [polling, id, merge]);

  useEffect(() => { document.title = a?.title ? `${a.title} – Stepcast` : "Stepcast"; }, [a?.title]);

  const scheduleRender = useCallback((lang: string) => {
    clearTimeout(renderTimers.current[lang]);
    renderTimers.current[lang] = window.setTimeout(() => {
      renderVideo(id, lang).then(() => setVideo(lang, { status: "rendering", stage: "Updating the video", error: "" }))
        .catch(() => {});
    }, RENDER_DELAY);
  }, [id, setVideo]);

  const persist = useCallback(() => {
    chain.current = chain.current.then(async () => {
      const v = version.current;
      const snapshot = latest.current;
      if (!snapshot || v === savedVersion.current) return;
      const saveArticleToo = articleDirty.current;
      const langs = [...dirtyLangs.current];
      articleDirty.current = false;
      dirtyLangs.current.clear();
      try {
        if (saveArticleToo) await saveArticle(snapshot);
        for (const l of langs) await saveTranslation(snapshot.id, snapshot.translations[l], l);
        savedVersion.current = v;
        setSaveState(version.current === v ? "saved" : "saving");
        const prev = lastSaved.current;
        lastSaved.current = snapshot;
        if (!prev) return;
        const hasVideo = (l: string) => (snapshot.videos[l]?.status ?? "none") !== "none";
        if (saveArticleToo && affectsVideo(prev, snapshot)) {
          const all = prev.voice !== snapshot.voice ? Object.keys(snapshot.videos) : [snapshot.lang];
          all.filter(hasVideo).forEach(scheduleRender);
        }
        for (const l of langs) {
          const before = prev.translations[l];
          if (before && affectsTranslationVideo(before, snapshot.translations[l])) scheduleRender(l);
        }
      } catch {
        if (saveArticleToo) articleDirty.current = true;
        langs.forEach((l) => dirtyLangs.current.add(l));
        setSaveState("error");
      }
    });
    return chain.current;
  }, [scheduleRender]);

  useEffect(() => {
    if (saveState !== "saving") return;
    const t = setTimeout(persist, 700);
    return () => clearTimeout(t);
  }, [a, saveState, persist]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (version.current !== savedVersion.current) e.preventDefault(); };
    addEventListener("beforeunload", warn);
    return () => removeEventListener("beforeunload", warn);
  }, []);

  useEffect(() => {
    if (!undo) return;
    const t = setTimeout(() => setUndo(null), 8000);
    return () => clearTimeout(t);
  }, [undo]);

  const edit = useCallback((change: (a: Article) => Article) => {
    version.current++;
    articleDirty.current = true;
    setSaveState("saving");
    setA((cur) => (cur ? change(cur) : cur));
  }, []);
  const editTranslation = useCallback((lang: string, change: (t: Translation) => Translation) => {
    version.current++;
    dirtyLangs.current.add(lang);
    setSaveState("saving");
    setA((cur) => (cur?.translations[lang] ? { ...cur, translations: { ...cur.translations, [lang]: change(cur.translations[lang]) } } : cur));
  }, []);
  const setSteps = useCallback((steps: Step[]) => edit((cur) => ({ ...cur, steps })), [edit]);
  const setStepById = useCallback((stepId: string, patch: Partial<Step>) =>
    edit((cur) => ({ ...cur, steps: cur.steps.map((s) => (s.id === stepId ? { ...s, ...patch } : s)) })), [edit]);

  const jump = useCallback((i: number) => {
    const el = stepEls.current[i];
    if (!el) return;
    setActive(i);
    el.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" });
    el.focus({ preventScroll: true });
  }, []);

  // The step nearest the top of the screen is the active one (rail highlight, shortcuts).
  const stepCount = a?.steps.length ?? 0;
  useEffect(() => {
    if (view !== "article") return;
    const observer = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && setActive(Number((e.target as HTMLElement).dataset.index))),
      { rootMargin: "-15% 0px -75% 0px" },
    );
    stepEls.current.slice(0, stepCount).forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, [stepCount, a?.status, view]);

  const structural = useCallback((message: string, next: Step[]) => {
    if (!a) return;
    setUndo({ message, steps: a.steps });
    setSteps(next);
  }, [a, setSteps]);

  const restore = useCallback(() => {
    if (!undo) return;
    setSteps(undo.steps);
    setUndo(null);
  }, [undo, setSteps]);

  const lang = a ? pickedLang ?? a.lang : "";
  const source = !!a && lang === a.lang;
  const tr = a && !source ? a.translations[lang] : undefined;

  const moveStep = useCallback((from: number, to: number) => {
    if (!a || !source || to < 0 || to >= a.steps.length) return;
    setSteps(moveTo(a.steps, from, to));
    // Follow the moved step. Reordering the elements also fires the active-step watcher, which would
    // otherwise settle on whatever step now sits in that spot (and the next ⌘↑/⌘↓ would move the wrong one).
    requestAnimationFrame(() => jump(to));
  }, [a, source, setSteps, jump]);

  // Keyboard shortcuts, active in the article view when you're not typing in a field.
  useEffect(() => {
    if (a?.status !== "ready" || view !== "article") return;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target instanceof Element ? e.target : document.body;
      const typing = target.closest("[contenteditable='true'], textarea, input, select");
      if (e.key === "Escape" && typing) return (document.activeElement as HTMLElement | null)?.blur();
      if (typing || target.closest("[popover]") || document.querySelector("dialog[open]")) return;
      const mod = e.metaKey || e.ctrlKey;
      const step = a.steps[active];
      if (mod && e.key === "z" && !e.shiftKey && undo) {
        e.preventDefault();
        restore();
      } else if (mod && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
        e.preventDefault();
        moveStep(active, active + (e.key === "ArrowUp" ? -1 : 1));
      } else if (!mod && (e.key === "j" || e.key === "k")) {
        jump(Math.min(a.steps.length - 1, Math.max(0, active + (e.key === "j" ? 1 : -1))));
      } else if (!mod && e.key === "z" && step) {
        setStepById(step.id, { zoomed: !step.zoomed });
      }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  });

  if (error) {
    return (
      <>
        <TopBar title="" />
        <div className="notice"><h1>Can't open this article</h1><p>{error}. Check that the Stepcast server is running.</p></div>
      </>
    );
  }
  if (!a) return <TopBar title="" />;
  if (a.status === "processing") return (<><TopBar title="New article" /><Progress a={a} /></>);
  const confirmDelete = (
    <ConfirmDelete articles={confirming ? [a] : null} onClose={() => setConfirming(false)}
      onDeleted={() => { location.hash = "#/"; }} />
  );

  if (a.status === "failed") {
    return (
      <>
        <TopBar title="Untitled" />
        <div className="notice">
          <h1>{a.source === "upload" ? "This video couldn't become an article" : "This recording couldn't become an article"}</h1>
          <p className="error-text">{a.error}</p>
          <p>{a.source === "upload"
            ? "Upload a screen recording where you click or type at least once."
            : "Record the flow again from the Stepcast extension. Click or type at least once while recording."}</p>
          <div className="notice-actions">
            <a className="button" href="#/">Back to articles</a>
            <button className="button quiet-danger" onClick={() => setConfirming(true)}>Delete</button>
          </div>
        </div>
        {confirmDelete}
      </>
    );
  }

  const status = {
    saved: <span className="save-status">Saved</span>,
    saving: <span className="save-status">Saving…</span>,
    error: (
      <span className="save-status is-error">
        Not saved. <button className="link" onClick={() => { setSaveState("saving"); persist(); }}>Try again</button>
      </span>
    ),
  }[saveState];

  const stale = a.stale[lang] ?? [];
  const updateStale = (ids: string[]) => {
    updateTranslation(a.id, lang, ids).then(() => setVideo(lang, { status: "rendering", stage: "Translating", error: "" }))
      .catch(() => {});
  };
  const make = () => {
    makeVideo(a.id).then(() => setVideo(a.lang, { status: "rendering", stage: "Writing the narration", error: "" }))
      .catch(() => {});
  };
  const retry = () => {
    if (source && a.steps.some((s) => !s.narration)) return make();
    if (!source && !tr) {
      addLanguage(a.id, lang).then(() => setVideo(lang, { status: "rendering", stage: "Translating", error: "" })).catch(() => {});
      return;
    }
    renderVideo(a.id, lang).then(() => setVideo(lang, { status: "rendering", stage: "Updating the video", error: "" })).catch(() => {});
  };
  const translating = !source && !tr; // just added: the translation hasn't arrived yet
  const langVideo = a.videos[lang] ?? NO_VIDEO;

  return (
    <>
      <TopBar title={tr?.title ?? a.title}>
        {status}
        <div className="views" role="tablist" aria-label="View">
          {(["article", "video"] as const).map((v) => (
            <button key={v} role="tab" aria-selected={view === v} className={view === v ? "is-on" : ""} onClick={() => setView(v)}>
              {v === "article" ? "Article" : "Video"}
            </button>
          ))}
        </div>
        <LanguageMenu a={a} lang={lang} onPick={(l) => setPickedLang(l === a.lang ? null : l)}
          onAdd={(l) => {
            addLanguage(a.id, l).then(() => {
              setVideo(l, { status: "rendering", stage: "Translating", error: "", version: 0 });
              setPickedLang(l);
            }).catch(() => {});
          }}
          onRemove={(l) => {
            removeLanguage(a.id, l).then(() => {
              setA((cur) => {
                if (!cur) return cur;
                const rest = <T,>(o: Record<string, T>) => Object.fromEntries(Object.entries(o).filter(([k]) => k !== l));
                return { ...cur, translations: rest(cur.translations), videos: rest(cur.videos), stale: rest(cur.stale) };
              });
              setPickedLang(null);
            }).catch(() => {});
          }} />
        <button className="button more" popoverTarget="more-menu">More</button>
        <div id="more-menu" popover="auto" className="menu">
          <button className="menu-item" onClick={() => { document.getElementById("more-menu")?.hidePopover(); setSettingsOpen(true); }}>
            Settings…
            <span className="menu-hint">Your voice, and words not to translate</span>
          </button>
          <hr />
          <button className="menu-item danger" onClick={() => {
            document.getElementById("more-menu")?.hidePopover();
            setConfirming(true);
          }}>
            Delete article…
          </button>
        </div>
        <ShareMenu a={a} lang={lang} flush={persist} />
      </TopBar>

      {translating ? (
        <div className="progress">
          <h1>Making the {lang} version</h1>
          {langVideo.status === "failed" ? (
            <p className="error-text" role="alert">{langVideo.error} <button className="link" onClick={retry}>Try again</button></p>
          ) : (
            <ol className="stages" aria-live="polite"><li className="now">{langVideo.stage || "Translating"}</li></ol>
          )}
        </div>
      ) : (
        <div className="workspace">
          <StepRail articleId={a.id} steps={a.steps} active={active} onJump={(i) => { setView("article"); requestAnimationFrame(() => jump(i)); }}
            onMove={moveStep} />
          <main className="doc">
            {a.source === "upload" && !noteHidden && view === "article" && (
              <p className="ai-note" role="note">
                Stepcast found these steps, and what to blur, in your uploaded video. Check each screenshot before you share.
                <button className="link" onClick={() => setNoteHidden(true)}>Got it</button>
              </p>
            )}
            {stale.length > 0 && (
              <p className="ai-note stale-note" role="note">
                {stale.length === 1 ? "1 step changed" : `${stale.length} steps changed`} in the original since this was translated.
                <button className="link" onClick={() => updateStale(stale)}>Update {stale.length === 1 ? "it" : "them"}</button>
              </p>
            )}

            {view === "video" ? (
              <VideoView
                key={settingsRound}
                a={a}
                lang={lang}
                onNarration={(stepId, text) => (source
                  ? setStepById(stepId, { narration: text })
                  : editTranslation(lang, (t) => t.steps[stepId]
                    ? { ...t, steps: { ...t.steps, [stepId]: { ...t.steps[stepId], narration: text } } } : t))}
                onStep={setStepById}
                onVoice={(voice) => edit((cur) => ({ ...cur, voice }))}
                onMerge={(stepId) => {
                  const order = [...a.steps].sort((x, y) => x.event_ids[0] - y.event_ids[0]);
                  const next = order[order.findIndex((s) => s.id === stepId) + 1];
                  if (next) structural("Scenes merged.", mergeIds(a.steps, stepId, next.id));
                }}
                onDelete={(stepId) => structural("Scene deleted.", a.steps.filter((s) => s.id !== stepId))}
                onMake={make}
                onRetry={retry}
                onSettings={() => setSettingsOpen(true)}
              />
            ) : (
              <>
                <TitleField value={tr ? tr.title : a.title}
                  onChange={(title) => (tr ? editTranslation(lang, (t) => ({ ...t, title })) : edit((cur) => ({ ...cur, title })))} />
                <RichText key={`intro-${lang}`} label="Introduction" className="intro" value={tr ? tr.intro : a.intro} placeholder="Add an introduction"
                  onChange={(intro) => (tr ? editTranslation(lang, (t) => ({ ...t, intro })) : edit((cur) => ({ ...cur, intro })))} />

                {a.steps.map((s, i) => {
                  const ts = tr?.steps[s.id];
                  return (
                    <section
                      key={s.id}
                      ref={(el) => { stepEls.current[i] = el; }}
                      data-index={i}
                      tabIndex={-1}
                      aria-label={`Step ${i + 1}`}
                      className={`step${i === active ? " is-active" : ""}`}
                      onFocus={() => setActive(i)}
                    >
                      <span className="step-num" aria-hidden="true">{i + 1}</span>
                      {tr && !ts ? (
                        <p className="step-text is-untranslated">
                          {s.text}
                          <span className="scene-flag">Not translated yet. <button className="link" onClick={() => updateStale([s.id])}>Translate this step</button></span>
                        </p>
                      ) : (
                        <RichText key={`${s.id}-${lang}`} label={`Step ${i + 1}`} className="step-text" value={ts ? ts.text : s.text}
                          placeholder="Describe this step"
                          onChange={(text) => (tr
                            ? editTranslation(lang, (t) => ({ ...t, steps: { ...t.steps, [s.id]: { ...t.steps[s.id], text } } }))
                            : setStepById(s.id, { text }))} />
                      )}
                      {tr && ts && stale.includes(s.id) && (
                        <p className="scene-flag">The original changed. <button className="link" onClick={() => updateStale([s.id])}>Update this step</button></p>
                      )}
                      <button
                        className={`shot${s.zoomed ? " is-zoomed" : ""}`}
                        onClick={() => setStepById(s.id, { zoomed: !s.zoomed })}
                        title={s.zoomed ? "Show the full page" : "Zoom in on the element"}
                        aria-label={s.zoomed ? `Step ${i + 1} screenshot, zoomed in. Show the full page` : `Step ${i + 1} screenshot, full page. Zoom in on the element`}
                      >
                        <img src={imageUrl(a.id, s)} alt="" />
                      </button>
                      {source && (
                        <div className="step-tools">
                          <button onClick={() => moveStep(i, i - 1)} disabled={i === 0}>Move up</button>
                          <button onClick={() => moveStep(i, i + 1)} disabled={i === a.steps.length - 1}>Move down</button>
                          <button onClick={() => structural("Steps merged.", mergeNext(a.steps, i))} disabled={i === a.steps.length - 1}>
                            Merge with next
                          </button>
                          <button className="danger" onClick={() => structural("Step deleted.", remove(a.steps, i))}>Delete</button>
                        </div>
                      )}
                    </section>
                  );
                })}

                <RichText key={`outro-${lang}`} label="Closing line" className="outro" value={tr ? tr.outro : a.outro} placeholder="Add a closing line"
                  onChange={(outro) => (tr ? editTranslation(lang, (t) => ({ ...t, outro })) : edit((cur) => ({ ...cur, outro })))} />
              </>
            )}
          </main>
        </div>
      )}
      {undo && (
        <div className="toast" role="status">
          {undo.message}
          <button onClick={restore}>Undo</button>
        </div>
      )}
      {confirmDelete}
      <SettingsDialog open={settingsOpen} onClose={() => { setSettingsOpen(false); setSettingsRound((n) => n + 1); }} />
    </>
  );
}
