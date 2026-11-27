/** The query parameter naming the item a search result opens a screen at (#109): `/approvals?item=<action ID>`.
 * A plain module (not "use client"), so the server pages can read it too. */
export const FOUND_PARAM = "item";

/** Where a search result opens: the screen, at the item. */
export function foundHref(path: "/approvals" | "/memory", id: string): string {
  return `${path}?${FOUND_PARAM}=${encodeURIComponent(id)}`;
}

/** The found item's ID from a page's search params (none, or a repeated parameter: no item). */
export function foundParam(params: Record<string, string | string[] | undefined>): string | null {
  const value = params[FOUND_PARAM];
  return typeof value === "string" && value ? value : null;
}
