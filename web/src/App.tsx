import { useEffect, useState } from "react";
import { type Article, listArticles } from "./api";
import { Editor } from "./Editor";

function useHash() {
  const [hash, setHash] = useState(location.hash);
  useEffect(() => {
    const on = () => setHash(location.hash);
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return hash;
}

function List() {
  const [articles, setArticles] = useState<Article[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    listArticles().then(setArticles, (e) => setError(`${e.message}. Is the server running on port 8000?`));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!articles) return <p className="muted">Loading…</p>;
  if (!articles.length)
    return (
      <div className="empty">
        <h2>No articles yet</h2>
        <p>Open the Stepcast extension on any page, press <b>Start recording</b>, walk through the flow, then press <b>Stop</b>.</p>
      </div>
    );
  return (
    <ul className="list">
      {articles.map((a) => (
        <li key={a.id}>
          <a href={`#/a/${a.id}`}>
            <span className="list-title">{a.title || (a.status === "processing" ? "Writing your article…" : "Untitled")}</span>
            <span className={`badge ${a.status}`}>{a.status}</span>
            <span className="muted">{new Date(a.created_at).toLocaleString()}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}

export default function App() {
  const hash = useHash();
  const id = hash.match(/^#\/a\/([0-9a-f]{12})$/)?.[1];
  return (
    <>
      <header className="top">
        <a href="#/" className="logo">Stepcast</a>
        {id && <a href="#/" className="muted">← All articles</a>}
      </header>
      <main>{id ? <Editor key={id} id={id} /> : <List />}</main>
    </>
  );
}
