import type { Step } from "./api";

/** Move the step at `from` so it ends up at index `to` (drag-and-drop and ⌘↑/⌘↓). */
export function moveTo(steps: Step[], from: number, to: number): Step[] {
  if (from === to || to < 0 || to >= steps.length || from < 0 || from >= steps.length) return steps;
  const out = [...steps];
  out.splice(to, 0, ...out.splice(from, 1));
  return out;
}

export const remove = (steps: Step[], i: number): Step[] => steps.filter((_, k) => k !== i);

/** Merge step `bId` into step `aId`, keeping a's place (the video merges scenes in recorded order). */
export function mergeIds(steps: Step[], aId: string, bId: string): Step[] {
  const a = steps.find((x) => x.id === aId);
  const b = steps.find((x) => x.id === bId);
  if (!a || !b || a === b) return steps;
  const merged = {
    ...a,
    event_ids: [...a.event_ids, ...b.event_ids],
    text: `${a.text} ${b.text}`,
    narration: [a.narration, b.narration].filter(Boolean).join(" "),
    hold_ms: Math.max(a.hold_ms, b.hold_ms),
  };
  return steps.filter((x) => x !== b).map((x) => (x === a ? merged : x));
}

export function mergeNext(steps: Step[], i: number): Step[] {
  if (i < 0 || i >= steps.length - 1) return steps;
  return mergeIds(steps, steps[i].id, steps[i + 1].id);
}
