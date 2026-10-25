import type { Step } from "./api";

export function move(steps: Step[], i: number, dir: -1 | 1): Step[] {
  const j = i + dir;
  if (j < 0 || j >= steps.length) return steps;
  const out = [...steps];
  [out[i], out[j]] = [out[j], out[i]];
  return out;
}

export const remove = (steps: Step[], i: number): Step[] => steps.filter((_, k) => k !== i);

export function mergeNext(steps: Step[], i: number): Step[] {
  if (i < 0 || i >= steps.length - 1) return steps;
  const [a, b] = [steps[i], steps[i + 1]];
  const merged = { ...a, event_ids: [...a.event_ids, ...b.event_ids], text: `${a.text} ${b.text}` };
  return [...steps.slice(0, i), merged, ...steps.slice(i + 2)];
}
