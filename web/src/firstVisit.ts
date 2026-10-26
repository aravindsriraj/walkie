export const GITHUB_URL = "https://github.com/aravindsriraj/walkie";

export type View = { name: "landing" } | { name: "library" } | { name: "editor"; id: string };

const KEY = "walkie.landingSeen";

/** The landing page greets a first visit to the root; links to an article, or a returning visitor, skip it. */
export function pickView(hash: string, seen: boolean): View {
  const id = hash.match(/^#\/a\/([0-9a-f]{12})$/)?.[1];
  if (id) return { name: "editor", id };
  if (hash === "#/welcome" || !seen) return { name: "landing" };
  return { name: "library" };
}

// Storage can be blocked (private windows, disabled site data): then the page shows again, which is harmless.
export function landingSeen(storage?: Storage): boolean {
  try {
    return (storage ?? localStorage).getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function markLandingSeen(storage?: Storage): void {
  try {
    (storage ?? localStorage).setItem(KEY, "1");
  } catch {
    // remembered for this visit only (App keeps it in state)
  }
}
