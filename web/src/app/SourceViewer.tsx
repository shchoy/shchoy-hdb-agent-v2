"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import type { components } from "@/lib/api/schema";
import type { CitationEvent } from "@/lib/events";
import styles from "./ask.module.css";

type DocumentView = components["schemas"]["DocumentView"];
type ChunkLocation = components["schemas"]["ChunkLocation"];
type Highlight = components["schemas"]["Highlight"];

type Source =
  | { status: "closed" }
  | { status: "loading" }
  | { status: "failed" }
  | { status: "open"; document: DocumentView; location: ChunkLocation };

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as T;
}

/**
 * Opens the cited document in place with the cited span highlighted. Document text is only ever
 * rendered as React text nodes (and `<mark>`s around them), so markup in a source stays inert text.
 */
export function SourceViewer({ citation }: { citation: CitationEvent }) {
  const [source, setSource] = useState<Source>({ status: "closed" });
  const doc = encodeURIComponent(citation.doc_id);

  async function open() {
    setSource({ status: "loading" });
    const span = new URLSearchParams({ start: String(citation.span.start), end: String(citation.span.end) });
    try {
      const [document, location] = await Promise.all([
        getJson<DocumentView>(`/api/documents/${doc}`),
        getJson<ChunkLocation>(`/api/documents/${doc}/chunks/${encodeURIComponent(citation.chunk_id)}?${span}`),
      ]);
      setSource({ status: "open", document, location });
    } catch {
      setSource({ status: "failed" });
    }
  }

  return (
    <>
      {source.status !== "open" && (
        <button type="button" onClick={() => void open()} disabled={source.status === "loading"}>
          Open source
        </button>
      )}
      {source.status === "failed" && (
        <p role="alert" className={styles.sourceError}>
          The source could not be loaded.
        </p>
      )}
      {source.status === "open" && (
        <Document
          document={source.document}
          location={source.location}
          onClose={() => setSource({ status: "closed" })}
        />
      )}
    </>
  );
}

function Document({
  document,
  location,
  onClose,
}: {
  document: DocumentView;
  location: ChunkLocation;
  onClose: () => void;
}) {
  const first = useRef<HTMLElement | null>(null);
  useEffect(() => {
    first.current?.scrollIntoView?.({ block: "center" });
  }, []);

  const byBlock = new Map<number, Highlight[]>();
  for (const h of location.highlights) byBlock.set(h.block, [...(byBlock.get(h.block) ?? []), h]);
  const firstBlock = location.highlights.length ? Math.min(...location.highlights.map((h) => h.block)) : -1;
  const file = `/api/documents/${encodeURIComponent(document.doc_id)}/file`;
  const paged = document.blocks.some((b) => b.page !== null);

  return (
    <section aria-label={`Source: ${document.title}`} className={styles.viewer}>
      <header className={styles.viewerHeader}>
        <strong>{document.title}</strong>
        {document.version && <span className={styles.location}> v{document.version}</span>}
        {document.kind === "pdf" ? (
          <a href={`${file}#page=${location.page ?? 1}`} target="_blank" rel="noopener noreferrer">
            Open original PDF{location.page ? ` (page ${location.page})` : ""}
          </a>
        ) : (
          <a href={file} download={document.filename}>
            Download original ({document.filename})
          </a>
        )}
        <button type="button" onClick={onClose}>
          Close source
        </button>
      </header>
      {location.highlights.length === 0 && (
        <p role="note" className={styles.sourceNote}>
          The cited text is no longer found in the file. It read: <q>{location.quote}</q>
        </p>
      )}
      <div className={styles.document}>
        {document.blocks.map((block, i) => {
          const newPage = paged && block.page !== null && block.page !== document.blocks[i - 1]?.page;
          return (
            <Fragment key={i}>
              {newPage && <h4>{`Page ${block.page}`}</h4>}
              <p
                className={block.level > 0 ? styles.blockHeading : undefined}
                ref={(el) => {
                  if (i === firstBlock) first.current = el;
                }}
              >
                {withHighlights(block.text, byBlock.get(i) ?? [])}
              </p>
            </Fragment>
          );
        })}
      </div>
    </section>
  );
}

function withHighlights(text: string, highlights: Highlight[]) {
  const parts: React.ReactNode[] = [];
  let at = 0;
  for (const h of [...highlights].sort((a, b) => a.start - b.start)) {
    parts.push(text.slice(at, h.start), <mark key={h.start}>{text.slice(h.start, h.end)}</mark>);
    at = h.end;
  }
  parts.push(text.slice(at));
  return parts;
}
