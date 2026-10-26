// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { GITHUB_URL } from "./firstVisit";
import { Landing } from "./Landing";

const FIXTURE = {
  said: ["Uh so we should click this button"],
  script: ["Click New deal to start creating a deal."],
  samples: { en: "Click Save to finish.", es: "Haz clic en Guardar para finalizar." },
};

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let box: HTMLDivElement;

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(FIXTURE))));
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.reject(new Error("autoplay refused")));
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
  box = document.createElement("div");
  document.body.append(box);
});

afterEach(() => {
  act(() => root.unmount());
  box.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function show(onStart = () => {}) {
  root = createRoot(box);
  await act(async () => root.render(<Landing onStart={onStart} />));
}

const buttons = (name: string) => [...box.querySelectorAll("button")].filter((b) => b.textContent?.trim() === name);

test("the hero says what Walkie does and the main button calls onStart", async () => {
  const onStart = vi.fn();
  await show(onStart);
  expect(box.textContent).toContain("Walk through it once. Walkie does the talking.");
  expect(box.textContent).toContain("A narrated tutorial video and help article, in 20 languages, ready for your docs site.");
  await act(async () => buttons("Start your first walkthrough")[0].click());
  expect(onStart).toHaveBeenCalledTimes(1);
});

test("star links go to the GitHub repo", async () => {
  await show();
  const stars = [...box.querySelectorAll("a")].filter((a) => a.textContent?.includes("Star on GitHub"));
  expect(stars.length).toBeGreaterThanOrEqual(2);
  for (const a of stars) expect(a.getAttribute("href")).toBe(GITHUB_URL);
});

test("choosing a language switches the video and captions, even if play() is refused", async () => {
  await show();
  await act(async () => buttons("Español")[0].click());
  expect(box.querySelector("video")?.getAttribute("src")).toMatch(/\/landing\/es\.mp4$/);
  expect(box.querySelector("video track")?.getAttribute("src")).toMatch(/\/landing\/es\.vtt$/);
});

test("the rough take and the script come from landing.json", async () => {
  await show();
  expect(box.textContent).toContain(FIXTURE.said[0]);
  expect(box.textContent).toContain(FIXTURE.script[0]);
});
