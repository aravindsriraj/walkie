import { useEffect, useRef, useState } from "react";
import { type Article, getLanguages } from "./api";

/** Which language you're editing, and adding or removing one. */
export function LanguageMenu({ a, lang, onPick, onAdd, onRemove }: {
  a: Article;
  lang: string;
  onPick: (lang: string) => void;
  onAdd: (lang: string) => void;
  onRemove: (lang: string) => void;
}) {
  const [names, setNames] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState("");
  const [removing, setRemoving] = useState<string | null>(null);
  const adder = useRef<HTMLDialogElement>(null);
  const confirm = useRef<HTMLDialogElement>(null);

  useEffect(() => { getLanguages().then(setNames).catch(() => {}); }, []);
  useEffect(() => { if (removing) confirm.current?.showModal(); else confirm.current?.close(); }, [removing]);

  const name = (code: string) => names[code] ?? code;
  const have = [a.lang, ...Object.keys(a.videos).filter((l) => l !== a.lang),
    ...Object.keys(a.translations).filter((l) => !(l in a.videos))];
  const choices = Object.keys(names).filter((l) => !have.includes(l) &&
    name(l).toLowerCase().includes(filter.trim().toLowerCase()));
  const close = () => document.getElementById("lang-menu")?.hidePopover();

  return (
    <>
      <button className="button lang" popoverTarget="lang-menu" aria-label={`Language: ${name(lang)}`}>
        {name(lang)}{Object.values(a.stale).some((ids) => ids.length > 0) && <span className="stale-dot" aria-hidden="true" />}
      </button>
      <div id="lang-menu" popover="auto" className="menu">
        {have.map((l) => (
          <button key={l} className={`menu-item${l === lang ? " is-current" : ""}`} aria-current={l === lang}
            onClick={() => { close(); onPick(l); }}>
            {name(l)}
            {(a.stale[l]?.length ?? 0) > 0 && <span className="stale-dot" aria-label="has changes to update" />}
            <span className="menu-hint">
              {l === a.lang ? "Original" : a.videos[l]?.status === "rendering" ? a.videos[l].stage || "Working…"
                : a.videos[l]?.status === "failed" ? "Didn't work" : "Translation"}
            </span>
          </button>
        ))}
        <hr />
        <button className="menu-item" onClick={() => { close(); setFilter(""); adder.current?.showModal(); }}>
          Add language…
          <span className="menu-hint">Translated article, voiceover, captions and video</span>
        </button>
        {lang !== a.lang && (
          <button className="menu-item danger" onClick={() => { close(); setRemoving(lang); }}>
            Remove {name(lang)}…
          </button>
        )}
      </div>

      <dialog ref={adder} className="dialog add-language" aria-labelledby="add-lang-title">
        <div className="dialog-head">
          <h2 id="add-lang-title">Add a language</h2>
          <button className="dialog-close" onClick={() => adder.current?.close()} aria-label="Close">×</button>
        </div>
        <input type="search" className="search" placeholder="Find a language" aria-label="Find a language"
          value={filter} onChange={(e) => setFilter(e.target.value)} autoFocus />
        <ul className="lang-list">
          {choices.map((l) => (
            <li key={l}>
              <button onClick={() => { adder.current?.close(); onAdd(l); }}>{name(l)}</button>
            </li>
          ))}
          {!choices.length && <li className="no-results">No more languages match.</li>}
        </ul>
        <p className="settings-note">Names in your "Don't translate" list stay as they are. Change it in Settings.</p>
      </dialog>

      <dialog ref={confirm} className="dialog confirm" onClose={() => setRemoving(null)} aria-labelledby="rm-lang-title">
        <h2 id="rm-lang-title">Remove {removing && name(removing)}?</h2>
        <p>The translated article, voiceover and video will be removed. The original stays as it is.</p>
        <div className="dialog-actions">
          <button className="button" onClick={() => setRemoving(null)} autoFocus>Cancel</button>
          <button className="button danger" onClick={() => { if (removing) onRemove(removing); setRemoving(null); }}>
            Remove {removing && name(removing)}
          </button>
        </div>
      </dialog>
    </>
  );
}
