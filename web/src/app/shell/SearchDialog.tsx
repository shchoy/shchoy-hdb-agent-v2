"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Badge } from "@/app/Card";
import type { ConversationHit, DocumentHit, SearchResults } from "@/lib/events";
import { CloseIcon, SearchIcon } from "./icons";
import styles from "./shell.module.css";

/** How long typing pauses before the search is sent. */
const DEBOUNCE_MS = 120;

type Found =
  | { status: "idle" }
  | { status: "done"; q: string; results: Result[] }
  | { status: "failed" };

/** One option of the results listbox: a conversation, a Library document or one of the officer's uploads. */
type Result =
  | { kind: "conversation"; key: string; hit: ConversationHit }
  | { kind: "document" | "upload"; key: string; hit: DocumentHit };

const GROUPS = [
  { kind: "conversation", label: "Conversations", one: "conversation", many: "conversations" },
  { kind: "document", label: "Documents", one: "document", many: "documents" },
  { kind: "upload", label: "My uploads", one: "upload", many: "uploads" },
] as const;

function resultsOf(body: SearchResults): Result[] {
  return [
    ...body.conversations.map((hit) => ({ kind: "conversation" as const, key: `c:${hit.thread_id}`, hit })),
    ...(body.documents ?? []).map((hit) => ({ kind: "document" as const, key: `d:${hit.doc_id}`, hit })),
    ...(body.uploads ?? []).map((hit) => ({ kind: "upload" as const, key: `u:${hit.doc_id}`, hit })),
  ];
}

/** "2 conversations and 1 document found". */
function summary(results: Result[]): string {
  const counts = GROUPS.map((g) => [g, results.filter((r) => r.kind === g.kind).length] as const)
    .filter(([, n]) => n > 0)
    .map(([g, n]) => `${n} ${n === 1 ? g.one : g.many}`);
  const listed = counts.length > 1 ? `${counts.slice(0, -1).join(", ")} and ${counts.at(-1)}` : counts[0];
  return `${listed} found`;
}

function Snippet({ parts }: { parts: ConversationHit["snippet"] }) {
  return (
    <span className={styles.searchSnippet}>
      {parts.map((part, n) => (part.match ? <mark key={n}>{part.text}</mark> : <span key={n}>{part.text}</span>))}
    </span>
  );
}

/**
 * The search dialog (#107, opened by the sidebar's search box or Ctrl/⌘K): the officer's own conversations, Library
 * documents and their own uploads (#108) by keyword, as they type, grouped by type. A combobox over one listbox of
 * results: arrows move through all of them (wrapping, across groups), Enter opens the selected one, Escape (or Close)
 * closes it. Focus stays in the dialog; the shell returns it to where it was.
 */
export function SearchDialog({
  onClose,
  onOpen,
  onOpenDocument,
}: {
  onClose(): void;
  onOpen(hit: ConversationHit): void;
  onOpenDocument(hit: DocumentHit): void;
}) {
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
          setFound({ status: "done", q, results: resultsOf(body) });
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
  const results = shown.status === "done" ? shown.results : [];
  const current = Math.min(selected, results.length - 1);
  const optionId = (i: number) => `${id}-result-${i}`;

  function open(result: Result) {
    if (result.kind === "conversation") onOpen(result.hit);
    else onOpenDocument(result.hit);
  }

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
    if (!results.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setSelected((i) => (i + step + results.length) % results.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      open(results[current]);
    }
  }

  const status =
    shown.status === "done" ? (results.length === 0 ? `Nothing matches “${shown.q}”` : summary(results)) : "";

  function option(result: Result, i: number) {
    const props = {
      id: optionId(i),
      role: "option",
      "aria-selected": i === current,
      className: styles.searchResult,
      onMouseMove: () => i !== selected && setSelected(i),
      onClick: () => open(result),
    };
    if (result.kind === "conversation") {
      const hit = result.hit;
      return (
        <li key={result.key} {...props}>
          <span className={styles.searchTitle}>{hit.title}</span>
          <Snippet parts={hit.snippet} />
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
      );
    }
    const hit = result.hit;
    return (
      <li key={result.key} {...props}>
        <span className={styles.searchTitle}>
          {hit.title}
          {hit.version && <span className={styles.searchVersion}> v{hit.version}</span>}
          {hit.status === "superseded" && (
            <>
              {" "}
              <Badge tone="warning">Superseded</Badge>
            </>
          )}
        </span>
        <Snippet parts={hit.snippet} />
        <span className={styles.searchMeta}>
          <span>{hit.upload ? "Your upload" : hit.doc_type}</span>
          {hit.matched === "content" && hit.location && <span> · {hit.location}</span>}
          <span> · Found in the {hit.matched}</span>
        </span>
      </li>
    );
  }

  // Results arrive in group order, so a group's first option is the index of its first result.
  const grouped = GROUPS.map((group) => ({
    group,
    members: results.filter((r) => r.kind === group.kind),
    first: results.findIndex((r) => r.kind === group.kind),
  })).filter((g) => g.members.length > 0);

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
            Search
          </h2>
          <SearchIcon />
          <input
            ref={field}
            type="search"
            role="combobox"
            aria-label="Search"
            aria-expanded={results.length > 0}
            aria-controls={`${id}-results`}
            aria-autocomplete="list"
            aria-activedescendant={results.length ? optionId(current) : undefined}
            placeholder="Search conversations and documents"
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
        <ul
          id={`${id}-results`}
          role="listbox"
          aria-label="Search results"
          className={styles.searchResults}
          hidden={!results.length}
        >
          {grouped.map(({ group, members, first }) => (
            <li key={group.kind} role="presentation">
              <ul role="group" aria-labelledby={`${id}-${group.kind}`} className={styles.searchGroup}>
                <li role="presentation" id={`${id}-${group.kind}`} className={styles.groupHeading}>
                  {group.label}
                </li>
                {members.map((result, n) => option(result, first + n))}
              </ul>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
