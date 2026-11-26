"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { ConversationHit, SearchResults } from "@/lib/events";
import { CloseIcon, SearchIcon } from "./icons";
import styles from "./shell.module.css";

/** How long typing pauses before the search is sent. */
const DEBOUNCE_MS = 120;

type Found =
  | { status: "idle" }
  | { status: "done"; q: string; conversations: ConversationHit[] }
  | { status: "failed" };

/**
 * The search dialog (#107, opened by the sidebar's search box or Ctrl/⌘K): the officer's own conversations by
 * keyword, as they type. A combobox over a listbox of results: arrows move through them (wrapping), Enter opens the
 * selected one, Escape (or Close) closes it. Focus stays in the dialog; the shell returns it to where it was.
 */
export function SearchDialog({ onClose, onOpen }: { onClose(): void; onOpen(hit: ConversationHit): void }) {
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Found>({ status: "idle" });
  const [selected, setSelected] = useState(0);
  const field = useRef<HTMLInputElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const id = useId();

  useEffect(() => field.current?.focus(), []);

  useEffect(() => {
    if (!q.trim()) return; // nothing to search: shown as idle (below)
    const abort = new AbortController();
    const timer = setTimeout(() => {
      fetch(`/api/search?q=${encodeURIComponent(q)}`, { signal: abort.signal })
        .then(async (response) => {
          if (!response.ok) throw new Error(String(response.status));
          const body = (await response.json()) as SearchResults;
          setFound({ status: "done", q, conversations: body.conversations });
          setSelected(0);
        })
        .catch(() => !abort.signal.aborted && setFound({ status: "failed" }));
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [q]);

  // Results of an earlier query aren't shown as this one's (e.g. while it waits out the debounce).
  const shown: Found = !q.trim() || (found.status === "done" && found.q !== q) ? { status: "idle" } : found;
  const hits = shown.status === "done" ? shown.conversations : [];
  const optionId = (i: number) => `${id}-result-${i}`;

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation(); // the drawer's Escape must not act too
      onClose();
    } else if (event.key === "Tab") {
      // Two stops (the field and Close): keep focus inside.
      event.preventDefault();
      (document.activeElement === field.current ? close : field).current?.focus();
    }
  }

  function onFieldKey(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!hits.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setSelected((i) => (i + step + hits.length) % hits.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      onOpen(hits[Math.min(selected, hits.length - 1)]);
    }
  }

  const status =
    shown.status === "done"
      ? hits.length === 0
        ? `No conversations match “${shown.q}”`
        : `${hits.length} conversation${hits.length === 1 ? "" : "s"} found`
      : "";

  return (
    <>
      <div className={styles.searchBackdrop} onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        className={styles.searchDialog}
        onKeyDown={onKeyDown}
      >
        <div className={styles.searchHeader}>
          <h2 id={`${id}-title`} className={styles.visuallyHidden}>
            Search conversations
          </h2>
          <SearchIcon />
          <input
            ref={field}
            type="search"
            role="combobox"
            aria-label="Search conversations"
            aria-expanded={hits.length > 0}
            aria-controls={`${id}-results`}
            aria-autocomplete="list"
            aria-activedescendant={hits.length ? optionId(Math.min(selected, hits.length - 1)) : undefined}
            placeholder="Search your conversations"
            autoComplete="off"
            spellCheck={false}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onFieldKey}
          />
          <button ref={close} type="button" className={styles.iconButton} onClick={onClose}>
            <CloseIcon />
            <span className={styles.visuallyHidden}>Close search</span>
          </button>
        </div>
        <p role="status" className={styles.searchStatus}>
          {status}
        </p>
        {shown.status === "failed" && (
          <p role="alert" className={styles.rowError}>
            Search isn&apos;t available right now. Try again.
          </p>
        )}
        <h3 id={`${id}-conversations`} className={styles.groupHeading} hidden={!hits.length}>
          Conversations
        </h3>
        <ul
          id={`${id}-results`}
          role="listbox"
          aria-labelledby={`${id}-conversations`}
          className={styles.searchResults}
          hidden={!hits.length}
        >
          {hits.map((hit, i) => (
            <li
              key={hit.thread_id}
              id={optionId(i)}
              role="option"
              aria-selected={i === selected}
              className={styles.searchResult}
              onMouseMove={() => i !== selected && setSelected(i)}
              onClick={() => onOpen(hit)}
            >
              <span className={styles.searchTitle}>{hit.title}</span>
              <span className={styles.searchSnippet}>
                {hit.snippet.map((part, n) => (part.match ? <mark key={n}>{part.text}</mark> : <span key={n}>{part.text}</span>))}
              </span>
              <span className={styles.searchMeta}>
                {/* A pinned conversation shows only under Pinned in the sidebar (unpinned: back in its group). */}
                <span>
                  {hit.pinned != null
                    ? `Pinned${hit.group_name ? ` · group ${hit.group_name}` : ""}`
                    : `In ${hit.group_name ?? "Recent"}`}
                </span>
                <span> · Found in the {hit.matched}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
