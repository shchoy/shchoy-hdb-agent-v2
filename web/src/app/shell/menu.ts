import type { DragEvent, KeyboardEvent } from "react";

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

/** Moves a conversation into a group (null: back to Recent) through the BFF. Resolves to null once moved, else the
 * refusal to show; `stale` when the sidebar should reload (404: the group or conversation went elsewhere). */
export async function moveThread(threadId: string, groupId: string | null): Promise<{ refused: string; stale: boolean } | null> {
  try {
    const response = await fetch(`/api/threads/${encodeURIComponent(threadId)}/group`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ group_id: groupId }),
    });
    if (response.ok) return null;
    return { refused: await refusalDetail(response, "The conversation couldn't be moved."), stale: response.status === 404 };
  } catch {
    return { refused: "The conversation couldn't be moved. Try again.", stale: false };
  }
}

/** The drag data type of a sidebar row (#101): not text, so a row dropped on a text field types nothing there. */
export const DRAG_TYPE = "application/x-plg-sidebar-row";

/** What a sidebar row needs to be dragged (#101): set on its button; the shell tracks what is being dragged. */
export type DragHandle = {
  onDragStart(event: DragEvent<HTMLElement>): void;
  onDragEnd(): void;
};

/** What a drop zone gets (#101): data-drop = none | available (somewhere the dragged row can go) | over (it would go here). */
export type DropZone = {
  "data-drop": "none" | "available" | "over";
  onDragEnter(event: DragEvent<HTMLElement>): void;
  onDragOver(event: DragEvent<HTMLElement>): void;
  onDragLeave(event: DragEvent<HTMLElement>): void;
  onDrop(event: DragEvent<HTMLElement>): void;
};
