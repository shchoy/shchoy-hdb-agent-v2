"use client";

import { useEffect, useRef } from "react";
import { OpenedSource } from "@/app/SourceViewer";
import type { DocumentHit } from "@/lib/events";
import styles from "./shell.module.css";

/**
 * A document search result (#108), opened over the screen in the source viewer at its matching chunk with the match
 * highlighted (a title match: from the top). Modal: the rest of the shell is inert; Escape, Close or the backdrop
 * close it and the shell puts focus back where search was opened from.
 */
export function SourceDialog({ hit, onClose }: { hit: DocumentHit; onClose(): void }) {
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => dialog.current?.focus(), []);

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
    }
  }

  return (
    <>
      <div className={styles.searchBackdrop} onClick={onClose} aria-hidden="true" />
      <div
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-label={`Search result: ${hit.title}`}
        tabIndex={-1}
        className={styles.sourceDialog}
        onKeyDown={onKeyDown}
      >
        <OpenedSource docId={hit.doc_id} chunkId={hit.chunk_id} span={hit.span ?? null} onClose={onClose} />
      </div>
    </>
  );
}
