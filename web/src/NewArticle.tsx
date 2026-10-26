import { useRef, useState } from "react";
import { uploadVideo } from "./api";

const MAX_BYTES = 2 * 1024 ** 3;

function Upload() {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");

  const send = async (file: File | undefined) => {
    if (!file) return;
    setError("");
    if (!file.type.startsWith("video/")) return setError("That isn't a video file. Choose an MP4, MOV or WebM screen recording.");
    if (file.size > MAX_BYTES) return setError("This file is over 2 GB. Trim or compress it and try again.");
    setProgress(0);
    try {
      const { id } = await uploadVideo(file, setProgress);
      location.hash = `#/a/${id}`; // the editor shows live progress while the steps are found
    } catch (e) {
      setError((e as Error).message);
      setProgress(null);
    }
  };

  return (
    <div
      className={`dropzone${over ? " is-over" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); send(e.dataTransfer.files[0]); }}
    >
      {progress === null ? (
        <>
          <svg className="dropzone-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 15V4m0 0L7.5 8.5M12 4l4.5 4.5" />
            <path d="M4 14v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" />
          </svg>
          <p className="dropzone-main">Drop a video here, or <button className="link" onClick={() => input.current?.click()}>choose a file</button></p>
          <p className="dropzone-hint">MP4, MOV or WebM, up to 10 minutes</p>
          <input ref={input} type="file" accept="video/*" hidden onChange={(e) => send(e.target.files?.[0])} />
        </>
      ) : (
        <>
          <p className="dropzone-main">Uploading {Math.round(progress * 100)}%</p>
          <progress max={1} value={progress} aria-label="Upload progress" />
        </>
      )}
      {error && <p className="error-text" role="alert">{error}</p>}
    </div>
  );
}

/** The two ways to make an article. Used in the New article dialog and on the empty library. */
export function NewArticleOptions() {
  return (
    <div className="choices">
      <section className="choice">
        <h3>Record in Chrome</h3>
        <p>Best for your own product. Walkie logs every click precisely and blurs passwords and emails as you go.</p>
        <ol>
          <li>Open the page you want to document.</li>
          <li>Click the Walkie icon in the toolbar, then <strong>Start recording</strong>.</li>
          <li>Walk through the task, then <strong>Stop &amp; create article</strong>.</li>
        </ol>
        <p className="choice-note">
          No recorder yet? Open <code>chrome://extensions</code>, turn on Developer mode, choose Load unpacked and pick
          the <code>extension</code> folder.
        </p>
      </section>
      <section className="choice choice-upload">
        <h3>Upload a video</h3>
        <p>Already have a screen recording? Walkie finds the steps and blurs the personal data it can spot.</p>
        <Upload />
      </section>
    </div>
  );
}

export function NewArticleButton() {
  const dialog = useRef<HTMLDialogElement>(null);
  return (
    <>
      <button className="button primary" onClick={() => dialog.current?.showModal()}>New article</button>
      <dialog ref={dialog} className="dialog new-article" aria-labelledby="new-title">
        <div className="dialog-head">
          <h2 id="new-title">New article</h2>
          <button className="dialog-close" onClick={() => dialog.current?.close()} aria-label="Close">×</button>
        </div>
        <NewArticleOptions />
      </dialog>
    </>
  );
}
