import { useState } from "react";
import { type Article, downloadUrl, shareUrl, videoDownloadUrl } from "./api";

/** One Share button; everything that sends the article somewhere lives in its menu. */
export function ShareMenu({ a, lang, flush }: { a: Article; lang: string; flush: () => Promise<void> }) {
  const [copied, setCopied] = useState(false);
  const link = shareUrl(a.id);
  const videoReady = a.videos[lang]?.status === "ready" || (a.videos[lang]?.version ?? 0) > 0;

  // Make sure the latest edits are saved before anything leaves the editor.
  const open = async (url: string) => {
    await flush();
    window.open(url, "_blank", "noopener");
  };
  const download = async (url: string) => {
    await flush();
    location.href = url;
  };

  return (
    <>
      <button className="button primary" popoverTarget="share-menu">Share</button>
      <div id="share-menu" popover="auto" className="menu" onToggle={() => setCopied(false)}>
        <button className="menu-item" onClick={() => download(downloadUrl(a.id, "md.zip"))}>
          Export for docs
          <span className="menu-hint">Article, screenshots, video and captions in every language, as a zip</span>
        </button>
        {videoReady && (
          <>
            <button className="menu-item" onClick={() => download(videoDownloadUrl(a.id, lang, "mp4"))}>
              Download video
              <span className="menu-hint">MP4, with captions as a separate file</span>
            </button>
            <button className="menu-item" onClick={() => download(videoDownloadUrl(a.id, lang, "mp4", true))}>
              Download video with captions
              <span className="menu-hint">Captions drawn into the picture, for players without caption support</span>
            </button>
            <button className="menu-item" onClick={() => download(videoDownloadUrl(a.id, lang, "srt"))}>
              Download captions
              <span className="menu-hint">SRT file, for YouTube and most video players</span>
            </button>
          </>
        )}
        <hr />
        <button
          className="menu-item"
          onClick={async () => {
            await flush();
            await navigator.clipboard.writeText(link);
            setCopied(true);
          }}
        >
          {copied ? "Link copied" : "Copy link"}
          <span className="menu-hint">{copied ? "Paste it anywhere" : "Anyone who can reach this Stepcast can open it"}</span>
        </button>
        <button className="menu-item" onClick={() => download(downloadUrl(a.id, "html"))}>
          Download HTML
          <span className="menu-hint">One file with the images inside</span>
        </button>
        <button className="menu-item" onClick={() => open(`${link}?print=1`)}>
          Save as PDF
          <span className="menu-hint">Opens the print dialog</span>
        </button>
      </div>
    </>
  );
}
