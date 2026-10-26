import { expect, test } from "vitest";
import { type Article, NO_VIDEO, type Step, type Translation } from "./api";
import { affectsTranslationVideo, affectsVideo, serverCopy } from "./videoEdits";

const step = (id: string, patch: Partial<Step> = {}): Step => ({
  id, event_ids: [0], text: `Click ${id}.`, frame: 0, zoomed: true, narration: `Click ${id}.`, hold_ms: 0,
  video_zoom: true, ...patch,
});
const article = (steps: Step[]): Article => ({
  id: "a", status: "ready", error: "", title: "T", intro: "", outro: "", steps, created_at: "", source: "extension",
  stage: "", stage_total: 0, frames: [], lang: "en", voice: "", videos: { en: NO_VIDEO }, translations: {}, stale: {},
});
const withStep = (a: Article, i: number, patch: Partial<Step>): Article =>
  ({ ...a, steps: a.steps.map((s, k) => (k === i ? { ...s, ...patch } : s)) });

test("narration, hold, zoom, voice and order affect the video; article text does not", () => {
  const a = article([step("a", { narration: "Hi" }), step("b")]);
  expect(affectsVideo(a, { ...a, title: "New" })).toBe(false);
  expect(affectsVideo(a, withStep(a, 0, { text: "Changed" }))).toBe(false);
  expect(affectsVideo(a, withStep(a, 0, { zoomed: false }))).toBe(false); // the screenshot's zoom, not the video's
  expect(affectsVideo(a, withStep(a, 0, { narration: "Hello" }))).toBe(true);
  expect(affectsVideo(a, withStep(a, 1, { hold_ms: 1000 }))).toBe(true);
  expect(affectsVideo(a, withStep(a, 1, { video_zoom: false }))).toBe(true);
  expect(affectsVideo(a, { ...a, voice: "Sulafat" })).toBe(true);
  expect(affectsVideo(a, { ...a, steps: [a.steps[1], a.steps[0]] })).toBe(true);
  expect(affectsVideo(a, { ...a, steps: [a.steps[0]] })).toBe(true);
});

test("only narration changes affect a translated video", () => {
  const t: Translation = { title: "T", intro: "", outro: "", steps: { a: { text: "x", narration: "Hola", src: "1" } } };
  expect(affectsTranslationVideo(t, { ...t, title: "Nuevo" })).toBe(false);
  expect(affectsTranslationVideo(t, { ...t, steps: { a: { ...t.steps.a, text: "y" } } })).toBe(false);
  expect(affectsTranslationVideo(t, { ...t, steps: { a: { ...t.steps.a, narration: "Buenas" } } })).toBe(true);
});

test("a title edit after the server writes the narration doesn't count as a video change", () => {
  // The editor opened before the narration existed; a poll then brought it in.
  const opened = article([step("a", { narration: "" })]);
  const fromServer = article([step("a", { narration: "Click a." })]);
  const known = serverCopy(opened, fromServer, false);
  const edited = { ...fromServer, title: "New title" };
  expect(affectsVideo(known, edited)).toBe(false);
  // With unsaved edits in flight, only server-owned fields are taken.
  const pending = serverCopy(opened, fromServer, true);
  expect(pending.steps[0].narration).toBe("");
  expect(pending.videos).toBe(fromServer.videos);
});
