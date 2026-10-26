import { expect, test } from "vitest";
import type { Step } from "./api";
import { mergeIds, mergeNext, moveTo, remove } from "./stepOps";

const s = (id: string, frame: number): Step => ({
  id, event_ids: [frame], text: id, frame, zoomed: true, narration: `Say ${id}.`, hold_ms: 0, video_zoom: true,
});
const steps = [s("a", 0), s("b", 1), s("c", 2)];
const ids = (xs: Step[]) => xs.map((x) => x.id);

test("moveTo drags a step to any position and ignores out-of-range moves", () => {
  expect(ids(moveTo(steps, 0, 2))).toEqual(["b", "c", "a"]);
  expect(ids(moveTo(steps, 2, 0))).toEqual(["c", "a", "b"]);
  expect(ids(moveTo(steps, 1, 0))).toEqual(["b", "a", "c"]);
  expect(moveTo(steps, 0, -1)).toBe(steps);
  expect(moveTo(steps, 2, 3)).toBe(steps);
});

test("remove drops one step", () => {
  expect(ids(remove(steps, 1))).toEqual(["a", "c"]);
});

test("mergeNext joins ids and text, keeps first frame", () => {
  const m = mergeNext(steps, 0);
  expect(m).toHaveLength(2);
  expect(m[0]).toMatchObject({ id: "a", event_ids: [0, 1], text: "a b", frame: 0 });
  expect(mergeNext(steps, 2)).toBe(steps);
});

test("mergeNext joins narration too and keeps the longer hold", () => {
  const merged = mergeNext([{ ...s("a", 0), hold_ms: 0 }, { ...s("b", 1), hold_ms: 2000 }], 0);
  expect(merged).toHaveLength(1);
  expect(merged[0].narration).toBe("Say a. Say b.");
  expect(merged[0].hold_ms).toBe(2000);
});

test("mergeIds merges a later step into an earlier one wherever they sit", () => {
  const out = mergeIds([s("c", 2), s("a", 0), s("b", 1)], "a", "b");
  expect(ids(out)).toEqual(["c", "a"]);
  expect(out[1].event_ids).toEqual([0, 1]);
  expect(out[1].narration).toBe("Say a. Say b.");
});
