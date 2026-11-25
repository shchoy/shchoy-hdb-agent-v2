import type { KeyboardEvent } from "react";

/** The menu items of an open menu (role menuitem or menuitemradio). */
export const MENU_ITEMS = '[role="menuitem"], [role="menuitemradio"]';

/** plg-api's refusal reason, else a plain fallback. */
export async function refusalDetail(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  return typeof body?.detail === "string" ? body.detail : fallback;
}

/**
 * Keyboard for an open menu: arrows, Home and End move between its items, Escape closes it (back to its button),
 * Tab leaves it. A handled key is preventDefault-ed, which also tells the drawer (Escape closes the menu, not it).
 */
export function onMenuKey(event: KeyboardEvent<HTMLElement>, close: () => void, leave: () => void) {
  const items = [...event.currentTarget.querySelectorAll<HTMLElement>(MENU_ITEMS)];
  const at = items.indexOf(document.activeElement as HTMLElement);
  const go = (i: number) => items[(i + items.length) % items.length]?.focus();
  if (event.key === "ArrowDown") go(at + 1);
  else if (event.key === "ArrowUp") go(at - 1);
  else if (event.key === "Home") go(0);
  else if (event.key === "End") go(items.length - 1);
  else if (event.key === "Escape") close();
  else if (event.key === "Tab") return leave();
  else return;
  event.preventDefault();
}

/** Spaces tidied as plg-api tidies them: runs of whitespace become one space. */
export function tidy(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ");
}
