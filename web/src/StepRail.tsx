import { useState } from "react";
import { type Step, frameUrl } from "./api";

/** Slim outline of the article: a thumbnail per step. Click to jump, drag to reorder. */
export function StepRail({ articleId, steps, active, onJump, onMove }: {
  articleId: string;
  steps: Step[];
  active: number;
  onJump: (i: number) => void;
  onMove: (from: number, to: number) => void;
}) {
  const [dragging, setDragging] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);

  return (
    <nav className="rail" aria-label="Steps">
      <ol>
        {steps.map((s, i) => (
          <li
            key={s.id}
            draggable
            onDragStart={(e) => {
              setDragging(i);
              e.dataTransfer.effectAllowed = "move";
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(i);
            }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => {
              e.preventDefault();
              if (dragging !== null) onMove(dragging, i);
              setDragging(null);
              setOver(null);
            }}
            onDragEnd={() => {
              setDragging(null);
              setOver(null);
            }}
            className={[i === active && "active", i === dragging && "dragging", i === over && i !== dragging && "drop-target"]
              .filter(Boolean).join(" ")}
          >
            <button onClick={() => onJump(i)} aria-current={i === active ? "step" : undefined} aria-label={`Step ${i + 1}`}>
              <span className="rail-num">{i + 1}</span>
              <img src={frameUrl(articleId, s.frame)} alt="" loading="lazy" draggable={false} />
            </button>
          </li>
        ))}
      </ol>
      <button className="rail-keys" popoverTarget="shortcuts">Shortcuts</button>
      <div id="shortcuts" popover="auto" className="menu shortcuts">
        <dl>
          <dt><kbd>J</kbd> <kbd>K</kbd></dt><dd>Next or previous step</dd>
          <dt><kbd>⌘</kbd><kbd>↑</kbd> <kbd>⌘</kbd><kbd>↓</kbd></dt><dd>Move the step up or down</dd>
          <dt><kbd>Z</kbd></dt><dd>Zoom in or show the full page</dd>
          <dt><kbd>⌘</kbd><kbd>Z</kbd></dt><dd>Undo delete or merge</dd>
          <dt><kbd>⌘</kbd><kbd>B</kbd> <kbd>⌘</kbd><kbd>E</kbd></dt><dd>Bold, or format as a value to type</dd>
          <dt><kbd>Esc</kbd></dt><dd>Stop editing text</dd>
        </dl>
      </div>
    </nav>
  );
}
