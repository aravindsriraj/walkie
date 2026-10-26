// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { SettingsDialog } from "./Settings";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let box: HTMLDivElement;
let release: () => void;

beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  // The saved lists arrive late, after the person has started typing.
  const late = new Promise<void>((r) => { release = r; });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (String(url).includes("/my-voice")) return new Response(JSON.stringify({ ready: false }));
    await late;
    return new Response(JSON.stringify({ words: String(url).includes("pronunciations") ? {} : [] }));
  }));
  box = document.createElement("div");
  document.body.append(box);
});

afterEach(() => {
  act(() => root.unmount());
  box.remove();
  vi.unstubAllGlobals();
});

function type(el: HTMLTextAreaElement, value: string) {
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(el, value);
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

test("typing before the saved lists load isn't wiped out when they arrive", async () => {
  root = createRoot(box);
  await act(async () => root.render(<SettingsDialog open onClose={() => {}} />));
  const say = box.querySelector<HTMLTextAreaElement>("textarea[aria-labelledby=say-h]")!;
  const keep = box.querySelector<HTMLTextAreaElement>("textarea[aria-labelledby=keep-h]")!;
  await act(async () => { type(say, "SQL = sequel"); type(keep, "Acmeflow"); });
  await act(async () => { release(); await Promise.resolve(); });
  expect(say.value).toBe("SQL = sequel");
  expect(keep.value).toBe("Acmeflow");
});
