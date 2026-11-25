"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import type { Group } from "@/lib/events";
import { ChevronIcon, MoreIcon, PlusIcon } from "./icons";
import { MENU_ITEMS, onMenuKey, refusalDetail, tidy } from "./menu";
import { useShell } from "./ShellContext";
import styles from "./shell.module.css";

type Mode = "idle" | "menu" | "rename" | "confirm";

/**
 * One of the officer's conversation groups (#100) in the sidebar: a disclosure button (name and count) that collapses
 * or expands its conversations, and its Options menu (Rename group, Delete group). Deleting asks first; the group's
 * conversations go back to Recent, none is deleted.
 */
export function GroupSection({
  group,
  count,
  expanded,
  onToggle,
  onRenamed,
  onDeleted,
  children,
}: {
  group: Group;
  count: number;
  expanded: boolean;
  onToggle(): void;
  onRenamed(name: string): void;
  onDeleted(): void;
  /** Its conversations (ConversationItems), newest first. */
  children: ReactNode;
}) {
  const shell = useShell();
  const [mode, setMode] = useState<Mode>("idle");
  const [name, setName] = useState(group.name);
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const options = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLUListElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const refocus = useRef(false);
  const id = useId();

  useEffect(() => {
    if (mode === "menu") menu.current?.querySelector<HTMLElement>(MENU_ITEMS)?.focus();
    else if (mode === "rename") {
      field.current?.focus();
      field.current?.select();
    } else if (mode === "confirm") cancel.current?.focus();
    else if (refocus.current) {
      refocus.current = false;
      options.current?.focus();
    }
  }, [mode]);

  const url = `/api/groups/${encodeURIComponent(group.group_id)}`;

  function close() {
    refocus.current = true;
    setMode("idle");
  }

  function cancelChange() {
    setError(null);
    close();
  }

  function onEscape(event: KeyboardEvent) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    cancelChange();
  }

  async function rename(event: FormEvent) {
    event.preventDefault();
    const next = tidy(name);
    if (!next) return setError("Give the group a name.");
    if (next === group.name) return close();
    setWorking(true);
    try {
      const response = await fetch(url, {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: next }),
      });
      if (!response.ok) {
        if (response.status === 404) shell.refresh(); // deleted elsewhere: the sidebar catches up
        return setError(await refusalDetail(response, "The group couldn't be renamed."));
      }
      setError(null);
      onRenamed(next);
      close();
    } catch {
      setError("The group couldn't be renamed. Try again.");
    } finally {
      setWorking(false);
    }
  }

  async function remove() {
    setWorking(true);
    try {
      const response = await fetch(url, { method: "DELETE" });
      // 404: already deleted (in another browser), which is what was asked.
      if (!response.ok && response.status !== 404)
        return setError(await refusalDetail(response, "The group couldn't be deleted."));
      onDeleted();
    } catch {
      setError("The group couldn't be deleted. Try again.");
    } finally {
      setWorking(false);
    }
  }

  const listId = `${id}-list`;

  return (
    <li className={styles.group}>
      {mode === "rename" ? (
        <form className={styles.renameForm} onSubmit={rename} onKeyDown={onEscape}>
          <label className={styles.visuallyHidden} htmlFor={`${id}-name`}>
            Group name
          </label>
          <input
            ref={field}
            id={`${id}-name`}
            value={name}
            maxLength={80}
            onChange={(e) => setName(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${id}-error` : undefined}
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
            <p id={`${id}-error`} role="alert" className={styles.rowError}>
              {error}
            </p>
          )}
        </form>
      ) : (
        <div className={styles.row}>
          <h3 className={styles.groupName}>
            <button
              type="button"
              className={styles.toggle}
              aria-expanded={expanded}
              aria-controls={expanded ? listId : undefined}
              onClick={onToggle}
            >
              <ChevronIcon />
              {/* Named "<name>, <n> conversations" by one hidden text, so the name begins with what is shown. */}
              <span className={styles.groupTitle} aria-hidden="true">
                {group.name}
              </span>
              <span className={styles.count} aria-hidden="true">
                {count}
              </span>
              <span className={styles.visuallyHidden}>{`${group.name}, ${count} conversation${count === 1 ? "" : "s"}`}</span>
            </button>
          </h3>
          <button
            ref={options}
            type="button"
            className={styles.options}
            aria-haspopup="menu"
            aria-expanded={mode === "menu"}
            aria-controls={mode === "menu" ? `${id}-menu` : undefined}
            onClick={() => {
              setError(null);
              setMode(mode === "menu" ? "idle" : "menu");
            }}
          >
            <MoreIcon />
            <span className={styles.visuallyHidden}>Options for group {group.name}</span>
          </button>
        </div>
      )}
      {mode === "menu" && (
        <ul
          ref={menu}
          id={`${id}-menu`}
          role="menu"
          aria-label={`Group ${group.name}`}
          className={styles.menu}
          onKeyDown={(e) => onMenuKey(e, close, () => setMode("idle"))}
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget) && e.relatedTarget !== options.current) setMode("idle");
          }}
        >
          <li role="none">
            <button type="button" role="menuitem" tabIndex={-1} onClick={() => (setName(group.name), setMode("rename"))}>
              Rename group
            </button>
          </li>
          <li role="none">
            <button type="button" role="menuitem" tabIndex={-1} onClick={() => setMode("confirm")}>
              Delete group
            </button>
          </li>
        </ul>
      )}
      {mode === "confirm" && (
        <div role="group" aria-labelledby={`${id}-confirm`} className={styles.confirm} onKeyDown={onEscape}>
          <p id={`${id}-confirm`} className={styles.confirmText}>
            Delete group {group.name}?
          </p>
          <p className={styles.confirmNote}>Its conversations go back to Recent. None of them is deleted.</p>
          <div className={styles.rowActions}>
            <button type="button" data-variant="danger-solid" disabled={working} onClick={() => void remove()}>
              Delete group
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
      {expanded &&
        (count === 0 ? (
          <p id={listId} className={styles.empty}>
            No conversations in this group.
          </p>
        ) : (
          <ul id={listId} aria-label={group.name} className={styles.groupList}>
            {children}
          </ul>
        ))}
    </li>
  );
}

/** "New group": a button that opens an inline name field; Enter creates, Escape cancels; focus returns to the button. */
export function NewGroup({ onCreated }: { onCreated(group: Group): void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [working, setWorking] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const refocus = useRef(false);
  const id = useId();

  useEffect(() => {
    if (open) field.current?.focus();
    else if (refocus.current) {
      refocus.current = false;
      button.current?.focus();
    }
  }, [open]);

  function close() {
    refocus.current = true;
    setError(null);
    setName("");
    setOpen(false);
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    const next = tidy(name);
    if (!next) return setError("Give the group a name.");
    setWorking(true);
    try {
      const response = await fetch("/api/groups", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: next }),
      });
      if (!response.ok) return setError(await refusalDetail(response, "The group couldn't be created."));
      onCreated((await response.json()) as Group);
      close();
    } catch {
      setError("The group couldn't be created. Try again.");
    } finally {
      setWorking(false);
    }
  }

  if (!open)
    return (
      <button ref={button} type="button" className={styles.newGroup} onClick={() => setOpen(true)}>
        <PlusIcon />
        New group
      </button>
    );

  return (
    <form
      className={styles.renameForm}
      onSubmit={create}
      onKeyDown={(e) => {
        if (e.key !== "Escape") return;
        e.preventDefault();
        close();
      }}
    >
      <label className={styles.visuallyHidden} htmlFor={`${id}-name`}>
        Group name
      </label>
      <input
        ref={field}
        id={`${id}-name`}
        value={name}
        maxLength={80}
        placeholder="Group name"
        onChange={(e) => setName(e.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
      />
      <div className={styles.rowActions}>
        <button type="submit" disabled={working}>
          Create
        </button>
        <button type="button" onClick={close}>
          Cancel
        </button>
      </div>
      {error && (
        <p id={`${id}-error`} role="alert" className={styles.rowError}>
          {error}
        </p>
      )}
    </form>
  );
}
