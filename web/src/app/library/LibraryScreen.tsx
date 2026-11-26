"use client";

import { useEffect, useState } from "react";
import type { Categorisation, CategoryDocument } from "@/lib/events";
import { Card, cardListClass } from "../Card";
import { when } from "../dates";
import { AuditFindings, Doc } from "./AuditFindings";
import styles from "./library.module.css";
import { MyDocuments } from "./MyDocuments";

type Loaded = { status: "loading" } | { status: "failed"; error: string } | { status: "ok"; view: Categorisation };

function failure(status: number): string {
  if (status === 401) return "You are no longer signed in. Sign in again.";
  return "Could not load the library.";
}

function count(n: number): string {
  return `${n} ${n === 1 ? "document" : "documents"}`;
}

/** A group of documents: a category (with its description and summary) or the uncategorised remainder. */
type Group = { id: string; name: string; description: string; summary: string | null; documents: CategoryDocument[] };

type View = "categories" | "audit" | "mine";
const VIEWS: { id: View; label: string }[] = [
  { id: "categories", label: "Categories" },
  { id: "audit", label: "Audit findings" },
  { id: "mine", label: "My documents" },
];

/** The Library: its document categories, the findings of the latest corpus audit, or the officer's own uploads (#106), one tab each. */
export function LibraryScreen() {
  const [view, setView] = useState<View>("categories");

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    const at = VIEWS.findIndex((v) => v.id === view);
    const next = VIEWS[(at + (event.key === "ArrowRight" ? 1 : VIEWS.length - 1)) % VIEWS.length];
    setView(next.id);
    document.getElementById(`library-tab-${next.id}`)?.focus();
  }

  return (
    <>
      <div role="tablist" aria-label="Library views" className={styles.tabs} onKeyDown={onKeyDown}>
        {VIEWS.map((v) => (
          <button
            key={v.id}
            id={`library-tab-${v.id}`}
            type="button"
            role="tab"
            aria-selected={view === v.id}
            aria-controls={`library-panel-${v.id}`}
            tabIndex={view === v.id ? 0 : -1}
            onClick={() => setView(v.id)}
          >
            {v.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`library-panel-${view}`} aria-labelledby={`library-tab-${view}`}>
        {view === "categories" ? <Categories /> : view === "audit" ? <AuditFindings /> : <MyDocuments />}
      </div>
    </>
  );
}

/**
 * The document categories `plg categorise` found, each expandable to its summary and documents; each
 * document opens in place. Documents no category took (or indexed since the last run) are listed last.
 */
function Categories() {
  const [loaded, setLoaded] = useState<Loaded>({ status: "loading" });
  const [open, setOpen] = useState<Set<string>>(new Set());

  useEffect(() => {
    let current = true;
    fetch("/api/categories")
      .then(async (response) => {
        if (!current) return;
        if (!response.ok) return setLoaded({ status: "failed", error: failure(response.status) });
        const view = (await response.json()) as Categorisation;
        if (current) setLoaded({ status: "ok", view });
      })
      .catch(() => current && setLoaded({ status: "failed", error: "Could not load the library." }));
    return () => {
      current = false;
    };
  }, []);

  if (loaded.status === "loading") return <p role="status">Loading the library…</p>;
  if (loaded.status === "failed") return <p role="alert">{loaded.error}</p>;

  const { view } = loaded;
  const groups: Group[] = view.categories.map((c) => ({ ...c, summary: c.summary || null }));
  if (view.uncategorised.length) {
    groups.push({
      id: "uncategorised",
      name: "Uncategorised",
      description: view.categorised_at
        ? "Documents no category took, or indexed since the last categorisation."
        : "Every indexed document.",
      summary: null,
      documents: view.uncategorised,
    });
  }

  function toggle(id: string) {
    setOpen((was) => {
      const next = new Set(was);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <>
      {view.categorised_at ? (
        <p className={styles.meta}>Categorised on {when(view.categorised_at)}</p>
      ) : (
        <p role="note" className={styles.meta}>
          The documents haven&apos;t been categorised yet. An administrator runs <code>plg categorise</code> to group
          them.
        </p>
      )}
      <ul className={cardListClass} aria-label="Document categories">
        {groups.map((group) => {
          const expanded = open.has(group.id);
          const panel = `category-${group.id}`;
          return (
            <li key={group.id}>
              <Card
                as="article"
                level={2}
                heading={
                  <>
                    <button
                      type="button"
                      className={styles.toggle}
                      aria-expanded={expanded}
                      aria-controls={panel}
                      onClick={() => toggle(group.id)}
                    >
                      {group.name}
                    </button>{" "}
                    <span className={styles.count}>({count(group.documents.length)})</span>
                  </>
                }
              >
                {group.description && <p className={styles.description}>{group.description}</p>}
                {expanded && (
                  <section id={panel} aria-label={group.name} className={styles.panel}>
                    {group.summary && (
                      <>
                        <h3>Summary</h3>
                        <p>{group.summary}</p>
                      </>
                    )}
                    <h3>Documents</h3>
                    <ul className={styles.documents} aria-label={`Documents in ${group.name}`}>
                      {group.documents.map((doc) => (
                        <li key={doc.doc_id} className={`${styles.document} ${styles.docLine}`}>
                          <Doc doc={doc} />
                        </li>
                      ))}
                    </ul>
                  </section>
                )}
              </Card>
            </li>
          );
        })}
      </ul>
    </>
  );
}
