"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { ThreadSummary } from "@/lib/events";
import { MoreIcon } from "./icons";
import styles from "./shell.module.css";

type Mode = "idle" | "menu" | "rename" | "confirm";

/** plg-api's refusal reason, else a plain fallback. */
async function refusalDetail(response: Response, fallback: string): Promise<string> {
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  return typeof body?.detail === "string" ? body.detail : fallback;
}

/**
 * One conversation in the sidebar: the button that opens it, and its Options menu (Rename, Delete). Rename edits the
 * title in place; Delete asks first, and shows plg-api's reason when it is refused (answering, awaiting approval).
 */
export function ConversationItem({
  thread,
  current,
  disabled,
  onPick,
  onRenamed,
  onDeleted,
}: {
  thread: ThreadSummary;
  current: boolean;
  disabled: boolean;
  onPick(): void;
  onRenamed(title: string): void;
  onDeleted(): void;
}) {
  const [mode, setMode] = useState<Mode>("idle");
  const [title, setTitle] = useState(thread.title);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const options = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLUListElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const refocus = useRef(false);
  const menuId = useId();
  const confirmId = useId();

  useEffect(() => {
    if (mode === "menu") menu.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    else if (mode === "rename") {
      field.current?.focus();
      field.current?.select();
    }
    else if (mode === "confirm") cancel.current?.focus();
    else if (refocus.current) {
      refocus.current = false;
      options.current?.focus();
    }
  }, [mode]);

  const url = `/api/threads/${encodeURIComponent(thread.thread_id)}`;

  /** Back to the plain row, focus on its Options button. */
  function close() {
    refocus.current = true;
    setMode("idle");
  }

  /** Cancel a rename or a deletion: nothing changes. */
  function cancelChange() {
    setError(null);
    close();
  }

  function onMenuKey(event: KeyboardEvent<HTMLUListElement>) {
    const items = [...(menu.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];
    const at = items.indexOf(document.activeElement as HTMLElement);
    const go = (i: number) => items[(i + items.length) % items.length]?.focus();
    if (event.key === "ArrowDown") go(at + 1);
    else if (event.key === "ArrowUp") go(at - 1);
    else if (event.key === "Home") go(0);
    else if (event.key === "End") go(items.length - 1);
    else if (event.key === "Escape") close();
    else if (event.key === "Tab") return setMode("idle");
    else return;
    event.preventDefault(); // also tells the drawer the key is handled (Escape closes the menu, not the drawer)
  }

  async function rename(event: FormEvent) {
    event.preventDefault();
    const next = title.split(/\s+/).filter(Boolean).join(" ");
    if (!next) return setError("Give the conversation a title.");
    if (next === thread.title) return close();
    setWorking(true);
    try {
      const response = await fetch(url, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ title: next }),
      });
      if (!response.ok) return setError(await refusalDetail(response, "The conversation couldn't be renamed."));
      setError(null);
      onRenamed(next);
      close();
    } catch {
      setError("The conversation couldn't be renamed. Try again.");
    } finally {
      setWorking(false);
    }
  }

  async function remove() {
    setWorking(true);
    try {
      const response = await fetch(url, { method: "DELETE" });
      if (!response.ok) return setError(await refusalDetail(response, "The conversation couldn't be deleted."));
      onDeleted();
    } catch {
      setError("The conversation couldn't be deleted. Try again.");
    } finally {
      setWorking(false);
    }
  }

  function onEscape(event: KeyboardEvent) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    cancelChange();
  }

  if (mode === "rename")
    return (
      <li className={styles.conversation}>
        <form className={styles.renameForm} onSubmit={rename} onKeyDown={onEscape}>
          <label className={styles.visuallyHidden} htmlFor={`${menuId}-title`}>
            Conversation title
          </label>
          <input
            ref={field}
            id={`${menuId}-title`}
            value={title}
            maxLength={80}
            onChange={(e) => setTitle(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${menuId}-error` : undefined}
          />
          <div className={styles.rowActions}>
            <button type="submit" disabled={working}>
              Save
            </button>
            <button type="button" onClick={cancelChange}>
              Cancel
            </button>
          </div>
          {error && (
            <p id={`${menuId}-error`} role="alert" className={styles.rowError}>
              {error}
            </p>
          )}
        </form>
      </li>
    );

  return (
    <li className={styles.conversation}>
      <div className={styles.row}>
        <button
          type="button"
          className={styles.pick}
          disabled={disabled}
          aria-current={current ? "true" : undefined}
          onClick={onPick}
        >
          {thread.title}
        </button>
        <button
          ref={options}
          type="button"
          className={styles.options}
          aria-haspopup="menu"
          aria-expanded={mode === "menu"}
          aria-controls={mode === "menu" ? menuId : undefined}
          onClick={() => {
            setError(null);
            setMode(mode === "menu" ? "idle" : "menu");
          }}
        >
          <MoreIcon />
          <span className={styles.visuallyHidden}>Options for {thread.title}</span>
        </button>
      </div>
      {mode === "menu" && (
        <ul
          ref={menu}
          id={menuId}
          role="menu"
          aria-label={thread.title}
          className={styles.menu}
          onKeyDown={onMenuKey}
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget) && e.relatedTarget !== options.current) setMode("idle");
          }}
        >
          <li role="none">
            <button type="button" role="menuitem" tabIndex={-1} onClick={() => (setTitle(thread.title), setMode("rename"))}>
              Rename
            </button>
          </li>
          <li role="none">
            <button type="button" role="menuitem" tabIndex={-1} onClick={() => setMode("confirm")}>
              Delete
            </button>
          </li>
        </ul>
      )}
      {mode === "confirm" && (
        <div role="group" aria-labelledby={confirmId} className={styles.confirm} onKeyDown={onEscape}>
          <p id={confirmId} className={styles.confirmText}>
            Delete {thread.title}?
          </p>
          <p className={styles.confirmNote}>Its history goes for good. Audit records of decisions are kept.</p>
          <div className={styles.rowActions}>
            <button type="button" data-variant="danger-solid" disabled={working} onClick={() => void remove()}>
              Delete
            </button>
            <button ref={cancel} type="button" onClick={cancelChange}>
              Cancel
            </button>
          </div>
          {error && (
            <p role="alert" className={styles.rowError}>
              {error}
            </p>
          )}
        </div>
      )}
    </li>
  );
}
