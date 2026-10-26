import { useEffect, useRef, useState } from "react";
import { type Article, deleteArticle } from "./api";

/**
 * "Delete N articles?" — permanent, so it always asks first. Renders nothing until `articles` is set.
 * `all` is true when the selection is the whole library, so the wording says so.
 */
export function ConfirmDelete({ articles, all = false, onClose, onDeleted }: {
  articles: Article[] | null;
  all?: boolean;
  onClose: () => void;
  onDeleted: (ids: string[]) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (articles?.length) {
      setError("");
      ref.current?.showModal();
    } else {
      ref.current?.close();
    }
  }, [articles]);

  const n = articles?.length ?? 0;
  const one = n === 1 ? articles![0] : null;

  const confirm = async () => {
    if (!articles) return;
    setBusy(true);
    const results = await Promise.allSettled(articles.map((a) => deleteArticle(a.id)));
    setBusy(false);
    const done = articles.filter((_, i) => results[i].status === "fulfilled").map((a) => a.id);
    const failed = results.filter((r): r is PromiseRejectedResult => r.status === "rejected");
    if (done.length) onDeleted(done);
    if (failed.length) {
      setError(n === 1 ? failed[0].reason.message : `${failed.length} of ${n} couldn't be deleted: ${failed[0].reason.message}`);
    }
  };

  const title = one ? "Delete this article?" : all ? `Delete all ${n} articles?` : `Delete ${n} articles?`;
  const body = one
    ? `“${one.title || "Untitled"}” will be removed along with its recording and screenshots.`
    : `${all ? "Every article in your library" : `These ${n} articles`} will be removed along with their recordings and screenshots.`;

  return (
    <dialog ref={ref} className="dialog confirm" onClose={onClose} aria-labelledby="confirm-title">
      <h2 id="confirm-title">{title}</h2>
      <p>{body} This can't be undone.</p>
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="dialog-actions">
        <button className="button" onClick={onClose} autoFocus>Cancel</button>
        <button className="button danger" onClick={confirm} disabled={busy}>
          {busy ? "Deleting…" : one ? "Delete article" : all ? "Delete all" : `Delete ${n} articles`}
        </button>
      </div>
    </dialog>
  );
}
