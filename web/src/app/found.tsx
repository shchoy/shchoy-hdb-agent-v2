"use client";

import { useEffect, useRef } from "react";
import styles from "./card.module.css";

/**
 * The list item a search result opened (#109): once it is shown, scrolled into view and focused, once per item (so
 * it is read out first; it stays highlighted). Spread `props(key)` on each item: only the one whose key is `found`
 * gets anything.
 */
export function useFound<T extends HTMLElement>(found: string | null | undefined) {
  const ref = useRef<T>(null);
  const focused = useRef<string | null>(null);

  useEffect(() => {
    if (!found || focused.current === found || !ref.current) return;
    ref.current.scrollIntoView?.({ block: "start" });
    ref.current.focus();
    focused.current = found;
  });

  function props(key: string) {
    if (key !== found) return {};
    return { ref, "data-found": "", tabIndex: -1, "aria-describedby": "found-item", className: styles.found };
  }

  return props;
}

/** "Search match", inside the found item (naming it). */
export function FoundLabel({ found }: { found: boolean }) {
  return found ? (
    <span id="found-item" className={styles.foundLabel}>
      Search match
    </span>
  ) : null;
}
