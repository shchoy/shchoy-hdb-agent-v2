"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import type { Group, ThreadSummary } from "@/lib/events";
import { MoreIcon } from "./icons";
import { MENU_ITEMS, moveThread, onMenuKey, refusalDetail, setPinned, tidy, type DragHandle } from "./menu";
import { useShell } from "./ShellContext";
import styles from "./shell.module.css";

type Mode = "idle" | "menu" | "move" | "rename" | "confirm";

/**
 * One conversation in the sidebar: the button that opens it, and its Options menu (Rename, Pin / Unpin (#102), Move to
 * group…, Delete).
 * Rename edits the title in place; Move to group… lists the officer's groups and No group (the keyboard path for
 * moving it, #100); Delete asks first, and shows plg-api's reason when it is refused (answering, awaiting approval).
 * Its row can also be dragged onto a group or Recent (#101; a drag never opens it).
 */
export function ConversationItem({
  thread,
  groups,
  current,
  disabled,
  focusOptions = false,
  onFocused,
  onPick,
  onRenamed,
  onMoved,
  onPinned,
  onDeleted,
  drag,
}: {
  thread: ThreadSummary;
  groups: Group[];
  current: boolean;
  disabled: boolean;
  /** Focus its Options button once shown (it has just been moved here, so the old one went). */
  focusOptions?: boolean;
  /** Its Options button has taken the focus `focusOptions` asked for. */
  onFocused?(): void;
  onPick(): void;
  onRenamed(title: string): void;
  onMoved(groupId: string | null): void;
  /** Pinned (its new place in Pinned) or unpinned (null) (#102). */
  onPinned(pinned: number | null): void;
  onDeleted(): void;
  /** Makes its row draggable (#101). */
  drag?: DragHandle;
}) {
  const shell = useShell();
  const [mode, setMode] = useState<Mode>("idle");
  const [title, setTitle] = useState(thread.title);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const options = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLUListElement>(null);
  const moveMenu = useRef<HTMLUListElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const refocus = useRef(false);
  const menuId = useId();
  const confirmId = useId();

  useEffect(() => {
    if (!focusOptions) return;
    options.current?.focus();
    onFocused?.();
  }, [focusOptions, onFocused]);

  useEffect(() => {
    if (mode === "menu") menu.current?.querySelector<HTMLElement>(MENU_ITEMS)?.focus();
    else if (mode === "move")
      (moveMenu.current?.querySelector<HTMLElement>('[aria-checked="true"]') ?? moveMenu.current?.querySelector<HTMLElement>(MENU_ITEMS))?.focus();
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

  function menuKey(event: KeyboardEvent<HTMLUListElement>) {
    onMenuKey(event, close, () => setMode("idle"));
  }

  async function rename(event: FormEvent) {
    event.preventDefault();
    const next = tidy(title);
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

  async function move(groupId: string | null) {
    if (groupId === (thread.group_id ?? null)) return close();
    setWorking(true);
    const refusal = await moveThread(thread.thread_id, groupId);
    setWorking(false);
    if (refusal) {
      if (refusal.stale) shell.refresh(); // e.g. the group was deleted elsewhere: the sidebar catches up
      setError(refusal.refused);
      return close();
    }
    setError(null);
    setMode("idle"); // a pinned one stays where it is (#102), so its menu must close
    onMoved(groupId);
  }

  async function pin() {
    setWorking(true);
    const result = await setPinned("threads", thread.thread_id, thread.pinned == null);
    setWorking(false);
    if ("refused" in result) {
      if (result.stale) shell.refresh();
      setError(result.refused);
      return close();
    }
    setError(null);
    setMode("idle");
    onPinned(result.pinned); // it moves (into or out of Pinned): the shell puts the focus on its Options there
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
    <li className={styles.conversation} data-thread-id={thread.thread_id}>
      {/* The row, not its button, is dragged: browsers don't reliably start a drag from a button. */}
      <div className={styles.row} draggable={drag && !disabled ? true : undefined} {...(drag && !disabled ? drag : {})}>
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
          aria-expanded={mode === "menu" || mode === "move"}
          aria-controls={mode === "menu" || mode === "move" ? menuId : undefined}
          onClick={() => {
            setError(null);
            setMode(mode === "menu" || mode === "move" ? "idle" : "menu");
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
          onKeyDown={menuKey}
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
            <button type="button" role="menuitem" tabIndex={-1} disabled={working} onClick={() => void pin()}>
              {thread.pinned == null ? "Pin" : "Unpin"}
            </button>
          </li>
          <li role="none">
            <button type="button" role="menuitem" tabIndex={-1} aria-haspopup="menu" onClick={() => setMode("move")}>
              Move to group…
            </button>
          </li>
          <li role="none">
            <button type="button" role="menuitem" tabIndex={-1} onClick={() => setMode("confirm")}>
              Delete
            </button>
          </li>
        </ul>
      )}
      {mode === "move" && (
        <ul
          ref={moveMenu}
          id={menuId}
          role="menu"
          aria-label={`Move ${thread.title} to`}
          aria-busy={working || undefined}
          className={styles.menu}
          onKeyDown={menuKey}
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget) && e.relatedTarget !== options.current) setMode("idle");
          }}
        >
          {[...groups.map((g) => ({ id: g.group_id as string | null, name: g.name })), { id: null, name: "No group" }].map(
            (choice) => (
              <li role="none" key={choice.id ?? ""}>
                <button
                  type="button"
                  role="menuitemradio"
                  tabIndex={-1}
                  aria-checked={choice.id === (thread.group_id ?? null)}
                  disabled={working}
                  onClick={() => void move(choice.id)}
                >
                  {choice.name}
                </button>
              </li>
            ),
          )}
        </ul>
      )}
      {mode === "idle" && error && (
        <p role="alert" className={styles.rowError}>
          {error}
        </p>
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
