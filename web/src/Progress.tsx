import { useRef } from "react";
import { type Article, frameUrl } from "./api";

const FINDING = "Finding the steps in your video";
const NARRATION = "Listening to your narration";
const STAGES = ["Preparing the recording", FINDING, "Capturing screenshots", NARRATION, "Writing the steps", "Writing the title and intro"];

/** Shown while the server writes the article: the stages, and each screenshot as it's captured. */
export function Progress({ a }: { a: Article }) {
  const narrated = useRef(false);
  if (a.stage === NARRATION) narrated.current = true;
  const stages = STAGES.filter((s) => (s !== NARRATION || narrated.current) && (s !== FINDING || a.source === "upload"));
  const current = Math.max(0, stages.indexOf(a.stage));
  const shots = a.stage_total ? `${a.frames.length} of ${a.stage_total} screenshots` : "";

  return (
    <div className="progress">
      <h1>Writing your article</h1>
      <ol className="stages" aria-live="polite">
        {stages.map((s, i) => (
          <li key={s} className={i < current ? "done" : i === current ? "now" : ""}>
            {s}
            {s === "Capturing screenshots" && i <= current && shots && <span className="stage-count">{shots}</span>}
          </li>
        ))}
      </ol>
      {a.frames.length > 0 && (
        <ul className="captures" aria-label="Screenshots captured so far">
          {a.frames.map((f) => (
            <li key={f}><img src={frameUrl(a.id, f)} alt="" /></li>
          ))}
        </ul>
      )}
    </div>
  );
}
