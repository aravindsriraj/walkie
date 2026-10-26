import { useEffect, useState } from "react";
import { type Article, frameUrl, listArticles } from "./api";
import { ConfirmDelete } from "./ConfirmDelete";
import { NewArticleButton, NewArticleOptions } from "./NewArticle";
import { SITE_URL } from "./links";
import { SettingsButton } from "./Settings";
import { TopBar } from "./TopBar";

const when = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" });

function thumbnail(a: Article): string | null {
  if (a.status === "ready" && a.steps.length) return frameUrl(a.id, a.steps[0].frame);
  if (a.status === "processing" && a.frames.length) return frameUrl(a.id, a.frames[a.frames.length - 1]);
  return null;
}

function meta(a: Article): string {
  if (a.status === "processing") return a.stage || "Starting…";
  if (a.status === "failed") return "Couldn't create this article";
  return `${a.steps.length} ${a.steps.length === 1 ? "step" : "steps"}, ${when(a.created_at)}`;
}

function Tile({ a, selecting, selected, onToggle, onDelete }: {
  a: Article;
  selecting: boolean;
  selected: boolean;
  onToggle: (id: string) => void;
  onDelete: (a: Article) => void;
}) {
  const src = thumbnail(a);
  const title = a.title || (a.status === "processing" ? "Writing your article…" : "Untitled");
  const body = (
    <>
      <div className="tile-shot">
        {src ? <img src={src} alt="" loading="lazy" /> : <span className="tile-empty">{a.status === "failed" ? "No screenshots" : ""}</span>}
      </div>
      <h2 className="tile-title">{title}</h2>
      <p className="tile-meta">{meta(a)}</p>
    </>
  );

  if (selecting) {
    const locked = a.status === "processing"; // the background job would write it back
    return (
      <li className="tile-wrap">
        <label className={`tile is-${a.status} is-selectable${selected ? " is-selected" : ""}${locked ? " is-locked" : ""}`}
          title={locked ? "Still being written. You can delete it once it's done." : undefined}>
          <input type="checkbox" className="tile-check" checked={selected} disabled={locked}
            onChange={() => onToggle(a.id)} aria-label={`Select “${title}”`} />
          {body}
        </label>
      </li>
    );
  }

  return (
    <li className="tile-wrap">
      <a className={`tile is-${a.status}`} href={`#/a/${a.id}`}>{body}</a>
      {a.status !== "processing" && (
        <button className="tile-delete" onClick={() => onDelete(a)} aria-label={`Delete “${title}”`}>Delete</button>
      )}
    </li>
  );
}

function FirstRun() {
  return (
    <div className="first-run">
      <h1>Make your first article</h1>
      <p>Show Walkie a task once, and it turns it into a step-by-step guide with screenshots.</p>
      <NewArticleOptions />
    </div>
  );
}

export function Library() {
  const [articles, setArticles] = useState<Article[] | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [deleting, setDeleting] = useState<Article[] | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Refresh while anything is still being written, so new articles fill in on their own.
  useEffect(() => {
    let stop = false;
    let timer = 0;
    const load = async () => {
      try {
        const list = await listArticles();
        if (stop) return;
        setArticles(list);
        setError("");
        if (list.some((a) => a.status === "processing")) timer = window.setTimeout(load, 2000);
      } catch {
        if (!stop) setError("Can't reach the Walkie server. Start it from the server folder, then reload this page.");
      }
    };
    load();
    document.title = "Articles – Walkie";
    return () => { stop = true; clearTimeout(timer); };
  }, []);

  const shown = (articles ?? []).filter((a) => a.title.toLowerCase().includes(query.trim().toLowerCase()));
  const deletable = (list: Article[]) => list.filter((a) => a.status !== "processing");
  const selectableShown = deletable(shown);
  const allShownSelected = selectableShown.length > 0 && selectableShown.every((a) => selected.has(a.id));
  const everything = selected.size > 0 && selected.size === deletable(articles ?? []).length;

  const toggle = (id: string) => setSelected((cur) => {
    const next = new Set(cur);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const exitSelecting = () => { setSelecting(false); setSelected(new Set()); };

  // Esc leaves selection mode (unless a dialog is open; it closes itself first).
  useEffect(() => {
    if (!selecting) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.querySelector("dialog[open]")) { setSelecting(false); setSelected(new Set()); }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [selecting]);

  return (
    <>
      <TopBar><a className="button" href={SITE_URL} target="_blank" rel="noopener noreferrer">About Walkie</a><SettingsButton />{articles && articles.length > 0 && <NewArticleButton />}</TopBar>
      <main className="library">
        {error && <div className="notice"><h1>Server not running</h1><p>{error}</p><p><code>uv run uvicorn app.api:app --host 127.0.0.1 --port 8000 --reload</code></p></div>}
        {articles && !articles.length && <FirstRun />}
        {articles && articles.length > 0 && (
          <>
            <div className={`library-head${selecting ? " is-selecting" : ""}`}>
              <h1>Articles <span className="count">{articles.length}</span></h1>
              <div className="library-tools">
                <input type="search" className="search" placeholder="Search by title" aria-label="Search articles by title"
                  value={query} onChange={(e) => setQuery(e.target.value)} />
                {selecting ? (
                  <div className="selection-bar" role="toolbar" aria-label="Selected articles">
                    <span className="selection-count" aria-live="polite">
                      {selected.size ? `${selected.size} selected` : "Choose articles to delete"}
                    </span>
                    <button className="button" onClick={() => setSelected(allShownSelected ? new Set() : new Set(selectableShown.map((a) => a.id)))}>
                      {allShownSelected ? "Clear selection" : "Select all"}
                    </button>
                    <button className="button" onClick={exitSelecting}>Cancel</button>
                    <button className="button danger" disabled={!selected.size}
                      onClick={() => setDeleting((articles ?? []).filter((a) => selected.has(a.id)))}>
                      {everything ? `Delete all ${selected.size}` : selected.size ? `Delete ${selected.size}` : "Delete"}
                    </button>
                  </div>
                ) : (
                  <button className="button" onClick={() => setSelecting(true)}>Select</button>
                )}
              </div>
            </div>
            {shown.length ? <ul className="grid">{shown.map((a) => (
                <Tile key={a.id} a={a} selecting={selecting} selected={selected.has(a.id)} onToggle={toggle}
                  onDelete={(one) => setDeleting([one])} />
              ))}</ul>
              : <p className="no-results">No articles match “{query.trim()}”.</p>}
          </>
        )}
      </main>
      <ConfirmDelete
        articles={deleting}
        all={selecting && everything}
        onClose={() => setDeleting(null)}
        onDeleted={(ids) => {
          const gone = new Set(ids);
          setArticles((list) => list?.filter((a) => !gone.has(a.id)) ?? null);
          setSelected((cur) => new Set([...cur].filter((id) => !gone.has(id))));
          if (deleting?.every((a) => gone.has(a.id))) {
            setDeleting(null);
            exitSelecting();
          }
        }}
      />
    </>
  );
}
