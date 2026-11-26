"use client";

import { useEffect, useRef } from "react";
import type { components } from "@/lib/api/schema";
import { Badge } from "./Card";
import { PolicyStanceCard } from "./PolicyStanceCard";
import { SourceViewer } from "./SourceViewer";
import styles from "./ask.module.css";

/** A source an answer cites; `index` is the number of its `[n]` marker. A `citation` event is one too. */
export type Cited = components["schemas"]["NumberedCitation"];
export type Stance = components["schemas"]["PolicyLineage"];

/** One answer's sources: what its `[n]` markers open. */
export type AnswerSources = { citations: Cited[]; stances: Stance[] };

export const NO_SOURCES: AnswerSources = { citations: [], stances: [] };

/** Marks a source from the asker's own uploads (#103), not the shared Library. */
export const YOUR_UPLOAD = "Your upload";

/** Marks a cited upload the officer has deleted since (#106): the answer keeps the citation, the source is gone. */
export const REMOVED = "Removed";

/** The accessible name of an `[n]` marker: its visible text, then the source it opens (and whether it is your upload). */
export function markerLabel(citation: Cited): string {
  return `[${citation.index}] ${citation.title}${citation.upload ? ", your upload" : ""}${citation.removed ? ", removed" : ""}`;
}

/**
 * The sources of one answer beside the conversation (a bottom sheet on narrow screens): its policy stances first,
 * then every cited source with its version and location, the quote to expand and the document to open with the span
 * highlighted. Opens at source `index`, which takes focus; Escape or Close closes it (focus then goes back to the
 * marker that opened it, which the caller does in `onClose`). `openCount` changes each time a marker is activated, so
 * activating another (or the same) marker while it is open moves to that source again.
 */
export function SourcesPanel({
  sources,
  index,
  openCount,
  onClose,
}: {
  sources: AnswerSources;
  index: number;
  openCount: number;
  onClose: () => void;
}) {
  const items = useRef(new Map<number, HTMLLIElement>());
  const closeButton = useRef<HTMLButtonElement>(null);

  // Focus goes to source `index`, or to the panel's Close when there is no such source (only a policy stance).
  useEffect(() => {
    const item = items.current.get(index);
    item?.scrollIntoView?.({ block: "start" });
    (item ?? closeButton.current)?.focus({ preventScroll: true });
  }, [index, openCount]);

  // Escape closes it wherever focus is (opening a document replaces its button, leaving focus on the page), unless
  // something nearer handled it first (the shell's drawer).
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      close.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  return (
    <aside aria-labelledby="sources-heading" className={styles.panel}>
      <header className={styles.panelHeader}>
        <h2 id="sources-heading">Sources</h2>
        <button type="button" ref={closeButton} onClick={onClose}>
          Close sources
        </button>
      </header>
      {sources.stances.map((stance) => (
        <PolicyStanceCard key={stance.policy_id} stance={stance} />
      ))}
      <ol aria-labelledby="sources-heading" className={styles.sources}>
        {sources.citations.map((c) => (
          <li
            key={c.index}
            tabIndex={-1}
            aria-current={c.index === index ? "true" : undefined}
            className={styles.source}
            ref={(el) => {
              if (el) items.current.set(c.index, el);
              else items.current.delete(c.index);
            }}
          >
            <h3 className={styles.sourceTitle}>
              <span className={styles.marker}>[{c.index}]</span> {c.title}
              {c.upload && (
                <>
                  {" "}
                  <Badge>{YOUR_UPLOAD}</Badge>
                </>
              )}
              {c.removed && (
                <>
                  {" "}
                  <Badge tone="warning">{REMOVED}</Badge>
                </>
              )}
            </h3>
            <p className={styles.location}>
              {c.version && <>Version {c.version} · </>}
              {c.location}
            </p>
            <details className={styles.quote}>
              <summary>Quote</summary>
              <blockquote>{c.quote}</blockquote>
            </details>
            {c.removed ? (
              <p className={styles.sourceNote}>You deleted this upload, so it can&apos;t be opened.</p>
            ) : (
              <SourceViewer citation={c} />
            )}
          </li>
        ))}
      </ol>
    </aside>
  );
}
