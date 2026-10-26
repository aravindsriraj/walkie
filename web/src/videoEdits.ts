import type { Article, Translation } from "./api";

/** Whether an edit changes what the video shows or says (so it needs re-rendering). Article wording doesn't. */
export function affectsVideo(before: Article, after: Article): boolean {
  if (before.voice !== after.voice || before.steps.length !== after.steps.length) return true;
  return before.steps.some((s, i) => {
    const t = after.steps[i];
    return s.id !== t.id || s.narration !== t.narration || s.hold_ms !== t.hold_ms || s.video_zoom !== t.video_zoom ||
      s.event_ids.join() !== t.event_ids.join();
  });
}

export function affectsTranslationVideo(before: Translation, after: Translation): boolean {
  const ids = new Set([...Object.keys(before.steps), ...Object.keys(after.steps)]);
  return [...ids].some((id) => before.steps[id]?.narration !== after.steps[id]?.narration);
}

/** The editor's copy of what the server has, after a poll. With unsaved edits in flight only the fields the
 *  server owns are taken; otherwise the server's article is the truth (e.g. narration it just wrote). */
export function serverCopy(prev: Article | null, next: Article, pending: boolean): Article {
  if (!prev || !pending) return next;
  return { ...prev, videos: next.videos, lang: next.lang, translations: next.translations, stale: next.stale };
}
