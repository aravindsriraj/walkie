import { expect, test } from "vitest";
import { landingSeen, markLandingSeen, pickView } from "./landing";

test("first visit at the root shows the landing page, later visits the library", () => {
  expect(pickView("", false)).toEqual({ name: "landing" });
  expect(pickView("#/", false)).toEqual({ name: "landing" });
  expect(pickView("", true)).toEqual({ name: "library" });
  expect(pickView("#/", true)).toEqual({ name: "library" });
});

test("deep links never show the landing page", () => {
  expect(pickView("#/a/0123456789ab", false)).toEqual({ name: "editor", id: "0123456789ab" });
});

test("#/welcome always shows it", () => {
  expect(pickView("#/welcome", true)).toEqual({ name: "landing" });
});

test("seen is remembered, and blocked storage doesn't throw", () => {
  const mem = new Map<string, string>();
  const s = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v) } as Storage;
  expect(landingSeen(s)).toBe(false);
  markLandingSeen(s);
  expect(landingSeen(s)).toBe(true);
  const blocked = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } } as unknown as Storage;
  expect(landingSeen(blocked)).toBe(false);
  expect(() => markLandingSeen(blocked)).not.toThrow();
});
