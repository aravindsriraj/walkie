import { expect, test } from "vitest";
import type { Step } from "./api";
import { mergeNext, move, remove } from "./stepOps";

const s = (id: string, frame: number): Step => ({ id, event_ids: [frame], text: id, frame, zoomed: true });
const steps = [s("a", 0), s("b", 1), s("c", 2)];
const ids = (xs: Step[]) => xs.map((x) => x.id);

test("move swaps neighbours and ignores out-of-range moves", () => {
  expect(ids(move(steps, 1, -1))).toEqual(["b", "a", "c"]);
  expect(ids(move(steps, 2, 1))).toEqual(["a", "b", "c"]);
  expect(ids(move(steps, 0, -1))).toEqual(["a", "b", "c"]);
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
