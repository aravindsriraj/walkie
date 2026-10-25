export const API = "http://127.0.0.1:8000";

export type Step = {
  id: string;
  event_ids: number[];
  text: string;
  frame: number;
  zoomed: boolean;
  clip: string | null;
};

export type Article = {
  id: string;
  status: "processing" | "ready" | "failed";
  error: string;
  title: string;
  intro: string;
  outro: string;
  steps: Step[];
  clips_status: "none" | "rendering" | "ready" | "failed";
  created_at: string;
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API + path, init);
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Request failed (${res.status})`);
  return res.json();
}

export const listArticles = () => call<Article[]>("/articles");
export const getArticle = (id: string) => call<Article>(`/articles/${id}`);
export const renderClips = (id: string) => call<unknown>(`/articles/${id}/clips`, { method: "POST" });
export const saveArticle = (a: Article) =>
  call<Article>(`/articles/${a.id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: a.title, intro: a.intro, outro: a.outro, steps: a.steps }),
  });

export const imageUrl = (id: string, s: Step) => `${API}/files/${id}/frames/${s.frame}_${s.zoomed ? "zoom" : "full"}.png`;
export const fileUrl = (id: string, path: string) => `${API}/files/${id}/${path}`;
