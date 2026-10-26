import type { ReactNode } from "react";

export function TopBar({ title, children }: { title?: string; children?: ReactNode }) {
  return (
    <header className="topbar">
      <a href="#/" className="wordmark">
        <span className="mark" aria-hidden="true" />
        <span className="wordmark-text">Walkie</span>
      </a>
      {title !== undefined && (
        <>
          <span className="crumb-sep" aria-hidden="true">/</span>
          <span className="crumb">{title || "Untitled"}</span>
        </>
      )}
      <div className="topbar-end">{children}</div>
    </header>
  );
}
