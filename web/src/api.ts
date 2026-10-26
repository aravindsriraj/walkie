// Same origin: the server serves the built app, and in development Vite forwards these paths to it.
export const API = "";

export type Step = {
  id: string;
  event_ids: number[];
  text: string;
  frame: number;
  zoomed: boolean;
  narration: string; // what the video says for this step
  hold_ms: number; // extra time on this scene after the narration
  video_zoom: boolean;
};

export type VideoState = {
  status: "none" | "rendering" | "ready" | "failed";
  stage: string;
  updating: string[]; // step ids whose scenes are being regenerated
  error: string;
  note: string;
  version: number; // bumps on every finished render
};

export type TStep = { text: string; narration: string; src: string };
export type Translation = { title: string; intro: string; outro: string; steps: Record<string, TStep> };

export type Article = {
  id: string;
  status: "processing" | "ready" | "failed";
  error: string;
  title: string;
  intro: string;
  outro: string;
  steps: Step[];
  created_at: string;
  source: "extension" | "upload"; // uploads: Gemini found the steps and the blurring
  stage: string; // live progress while processing
  stage_total: number; // screenshots to capture
  frames: number[]; // screenshots captured so far (event indices)
  lang: string; // the language the presenter spoke
  voice: string; // "" = default voice, "mine" = the user's own
  videos: Record<string, VideoState>;
  translations: Record<string, Translation>;
  stale: Record<string, string[]>; // per language: steps changed since they were translated
};

export const NO_VIDEO: VideoState = { status: "none", stage: "", updating: [], error: "", note: "", version: 0 };

const failure = async (res: Response) =>
  new Error((await res.json().catch(() => null))?.detail ?? `Request failed (${res.status})`);

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(API + path, init);
  if (!res.ok) throw await failure(res);
  return res.json();
}

export const listArticles = () => call<Article[]>("/articles");
export const getArticle = (id: string) => call<Article>(`/articles/${id}`);
export const saveArticle = (a: Article) =>
  call<Article>(`/articles/${a.id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: a.title, intro: a.intro, outro: a.outro, steps: a.steps, voice: a.voice }),
  });

const post = (path: string, body?: unknown) =>
  fetch(API + path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  }).then(async (res) => { if (!res.ok) throw await failure(res); });

// Video
export const makeVideo = (id: string) => post(`/articles/${id}/video`);
export const renderVideo = (id: string, lang: string) => post(`/articles/${id}/videos/${lang}`);
export const getVoices = () => call<{ voices: { id: string; label: string }[]; mine: boolean }>("/voices");

// Languages
export const getLanguages = () => call<Record<string, string>>("/languages");
export const addLanguage = (id: string, lang: string) => post(`/articles/${id}/translations/${lang}`);
export const updateTranslation = (id: string, lang: string, stepIds: string[]) =>
  post(`/articles/${id}/translations/${lang}/update`, { step_ids: stepIds });
export const saveTranslation = (id: string, t: Translation, lang: string) =>
  call<Article>(`/articles/${id}/translations/${lang}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: t.title, intro: t.intro, outro: t.outro,
      steps: Object.fromEntries(Object.entries(t.steps).map(([k, s]) => [k, { text: s.text, narration: s.narration }])),
    }),
  });
export async function removeLanguage(id: string, lang: string): Promise<void> {
  const res = await fetch(`${API}/articles/${id}/translations/${lang}`, { method: "DELETE" });
  if (!res.ok) throw await failure(res);
}

// Settings
export const getMyVoice = () => call<{ ready: boolean }>("/my-voice");
export async function setUpMyVoice(sample: Blob, consent: Blob): Promise<void> {
  const form = new FormData();
  form.append("sample", sample, "sample.webm");
  form.append("consent", consent, "consent.webm");
  const res = await fetch(`${API}/my-voice`, { method: "POST", body: form });
  if (!res.ok) throw await failure(res);
}
export async function forgetMyVoice(): Promise<void> {
  const res = await fetch(`${API}/my-voice`, { method: "DELETE" });
  if (!res.ok) throw await failure(res);
}
export const getGlossary = () => call<{ words: string[] }>("/settings/glossary");
export const saveGlossary = (words: string[]) =>
  call<{ words: string[] }>("/settings/glossary", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ words }),
  });
export const getPronunciations = () => call<{ words: Record<string, string> }>("/settings/pronunciations");
export const savePronunciations = (words: Record<string, string>) =>
  call<{ words: Record<string, string> }>("/settings/pronunciations", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ words }),
  });

export async function deleteArticle(id: string): Promise<void> {
  const res = await fetch(`${API}/articles/${id}`, { method: "DELETE" });
  // 405: a server started before delete existed. Say so, rather than "Method Not Allowed".
  if (res.status === 405) throw new Error("The Walkie server is out of date. Restart it, then try again.");
  if (!res.ok) throw await failure(res);
}

/** Upload a screen recording; XHR rather than fetch because only XHR reports upload progress. */
export function uploadVideo(file: File, onProgress: (fraction: number) => void): Promise<{ id: string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API}/uploads`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let body: { id?: string; detail?: string } = {};
      try { body = JSON.parse(xhr.responseText); } catch { /* not JSON: fall through to the generic message */ }
      if (xhr.status < 300 && body.id) resolve({ id: body.id });
      else reject(new Error(body.detail ?? `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Couldn't reach the Walkie server. Check that it's running."));
    const form = new FormData();
    form.append("video", file);
    xhr.send(form);
  });
}

export const frameUrl = (id: string, frame: number, zoomed = true) =>
  `${API}/files/${id}/frames/${frame}_${zoomed ? "zoom" : "full"}.png`;
export const imageUrl = (id: string, s: Step) => frameUrl(id, s.frame, s.zoomed);
export const shareUrl = (id: string) => `${API}/a/${id}`;
export const downloadUrl = (id: string, kind: "md.zip" | "html") => `${API}/articles/${id}/export.${kind}`;
export const videoDownloadUrl = (id: string, lang: string, kind: "mp4" | "srt" | "vtt", burned = false) =>
  `${API}/articles/${id}/videos/${lang}.${kind}${burned ? "?captions=burned" : ""}`;
export const videoUrl = (id: string, lang: string, version: number) => `${API}/files/${id}/video.${lang}.mp4?v=${version}`;
export const captionsUrl = (id: string, lang: string, version: number) =>
  `${API}/files/${id}/captions.${lang}.vtt?v=${version}`;
