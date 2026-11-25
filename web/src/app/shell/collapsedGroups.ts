/**
 * Which conversation groups (#100) are collapsed in this browser: a JSON list of group IDs in localStorage, read
 * with useSyncExternalStore (subscribeCollapsed / collapsedSnapshot, "[]" on the server) so first paint matches.
 */

export const COLLAPSED_GROUPS = "plg_collapsed_groups";

const collapsedListeners = new Set<() => void>();

/** Saved collapsed groups as stored (a string, so the snapshot is stable); "[]" on the server and without storage. */
export function collapsedSnapshot(): string {
  try {
    return localStorage.getItem(COLLAPSED_GROUPS) ?? "[]";
  } catch {
    return "[]";
  }
}

export function subscribeCollapsed(onChange: () => void): () => void {
  collapsedListeners.add(onChange);
  window.addEventListener("storage", onChange); // another tab
  return () => {
    collapsedListeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function parseCollapsed(saved: string): Set<string> {
  try {
    const ids: unknown = JSON.parse(saved);
    return new Set(Array.isArray(ids) ? ids.filter((id): id is string => typeof id === "string") : []);
  } catch {
    return new Set();
  }
}

export function saveCollapsed(next: Set<string>) {
  try {
    localStorage.setItem(COLLAPSED_GROUPS, JSON.stringify([...next]));
  } catch {
    return; // storage unavailable: nothing is remembered
  }
  collapsedListeners.forEach((notify) => notify());
}
