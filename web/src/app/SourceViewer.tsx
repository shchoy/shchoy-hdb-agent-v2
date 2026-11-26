"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import type { components } from "@/lib/api/schema";
import { Badge } from "./Card";
import styles from "./ask.module.css";

type DocumentView = components["schemas"]["DocumentView"];
type ChunkLocation = components["schemas"]["ChunkLocation"];
type Highlight = components["schemas"]["Highlight"];
/** What locates a cited span: a `citation` event, or a source kept with an earlier answer. */
type Citation = Pick<components["schemas"]["NumberedCitation"], "doc_id" | "chunk_id" | "span">;

type Source =
  | { status: "closed" }
  | { status: "loading" }
  | { status: "failed"; gone: boolean }
  | { status: "open"; document: DocumentView; location: ChunkLocation | null };

class HttpError extends Error {
  constructor(readonly status: number) {
    super(`HTTP ${status}`);
  }
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new HttpError(response.status);
  return (await response.json()) as T;
}

/** An officer's upload (#103) that is no longer there: they deleted it (#106). */
function deletedUpload(docId: string, error: unknown): boolean {
  return docId.startsWith("upload-") && error instanceof HttpError && error.status === 404;
}

/** Why a document didn't open: a deleted upload says so, anything else is a plain failure. */
function Failed({ gone, what }: { gone: boolean; what: string }) {
  return (
    <p role="alert" className={styles.sourceError}>
      {gone ? "This upload was deleted, so it can't be opened." : `The ${what} could not be loaded.`}
    </p>
  );
}

/**
 * Opens the cited document in place with the cited span highlighted. Document text is only ever
 * rendered as React text nodes (and `<mark>`s around them), so markup in a source stays inert text.
 */
export function SourceViewer({ citation }: { citation: Citation }) {
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
    } catch (error) {
      setSource({ status: "failed", gone: deletedUpload(citation.doc_id, error) });
    }
  }

  return (
    <>
      {source.status !== "open" && (
        <button type="button" onClick={() => void open()} disabled={source.status === "loading"}>
          Open source
        </button>
      )}
      {source.status === "failed" && <Failed gone={source.gone} what="source" />}
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

/**
 * Opens a whole document in place (no cited span), e.g. from the Library. `label` names the button, so a list of
 * documents gets one distinct "Open" button each.
 */
export function DocumentViewer({ docId, label }: { docId: string; label: string }) {
  const [source, setSource] = useState<Source>({ status: "closed" });

  async function open() {
    setSource({ status: "loading" });
    try {
      const document = await getJson<DocumentView>(`/api/documents/${encodeURIComponent(docId)}`);
      setSource({ status: "open", document, location: null });
    } catch (error) {
      setSource({ status: "failed", gone: deletedUpload(docId, error) });
    }
  }

  return (
    <>
      {source.status !== "open" && (
        <button type="button" onClick={() => void open()} disabled={source.status === "loading"} aria-label={label}>
          Open
        </button>
      )}
      {source.status === "failed" && <Failed gone={source.gone} what="document" />}
      {source.status === "open" && (
        <Document document={source.document} location={null} onClose={() => setSource({ status: "closed" })} />
      )}
    </>
  );
}

/**
 * Opens a document in place with a quoted passage of one of its chunks highlighted, e.g. a side of an audit conflict:
 * the whole chunk is located first, then narrowed to the quote when it appears verbatim in the chunk's text (else the
 * whole chunk stays highlighted).
 */
export function QuoteViewer({
  docId,
  chunkId,
  quote,
  label,
}: {
  docId: string;
  chunkId: string;
  quote: string;
  label: string;
}) {
  const [source, setSource] = useState<Source>({ status: "closed" });

  async function open() {
    setSource({ status: "loading" });
    const chunk = `/api/documents/${encodeURIComponent(docId)}/chunks/${encodeURIComponent(chunkId)}`;
    try {
      const [document, whole] = await Promise.all([
        getJson<DocumentView>(`/api/documents/${encodeURIComponent(docId)}`),
        getJson<ChunkLocation>(chunk),
      ]);
      let location = whole;
      const start = quote ? whole.quote.indexOf(quote) : -1;
      if (start >= 0) {
        const span = new URLSearchParams({ start: String(start), end: String(start + quote.length) });
        location = await getJson<ChunkLocation>(`${chunk}?${span}`).catch(() => whole);
      }
      setSource({ status: "open", document, location });
    } catch (error) {
      setSource({ status: "failed", gone: deletedUpload(docId, error) });
    }
  }

  return (
    <>
      {source.status !== "open" && (
        <button type="button" onClick={() => void open()} disabled={source.status === "loading"} aria-label={label}>
          Open
        </button>
      )}
      {source.status === "failed" && <Failed gone={source.gone} what="document" />}
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
  location: ChunkLocation | null;
  onClose: () => void;
}) {
  const first = useRef<HTMLElement | null>(null);
  useEffect(() => {
    first.current?.scrollIntoView?.({ block: "center" });
  }, []);

  const byBlock = new Map<number, Highlight[]>();
  const highlights = location?.highlights ?? [];
  for (const h of highlights) byBlock.set(h.block, [...(byBlock.get(h.block) ?? []), h]);
  const firstBlock = highlights.length ? Math.min(...highlights.map((h) => h.block)) : -1;
  const file = `/api/documents/${encodeURIComponent(document.doc_id)}/file`;
  const paged = document.blocks.some((b) => b.page !== null);

  return (
    <section aria-label={`Source: ${document.title}`} className={styles.viewer}>
      <header className={styles.viewerHeader}>
        <strong>{document.title}</strong>
        {document.version && <span className={styles.location}> v{document.version}</span>}
        {document.upload && <Badge>Your upload</Badge>}
        {document.kind === "pdf" ? (
          <a href={`${file}#page=${location?.page ?? 1}`} target="_blank" rel="noopener noreferrer">
            Open original PDF{location?.page ? ` (page ${location.page})` : ""}
          </a>
        ) : document.kind === "image" ? (
          <a href={file} target="_blank" rel="noopener noreferrer">
            Open original image
          </a>
        ) : (
          <a href={file} download={document.filename}>
            Download original ({document.filename})
          </a>
        )}
        <button type="button" onClick={onClose}>
          {location ? "Close source" : "Close document"}
        </button>
      </header>
      {location && highlights.length === 0 && (
        <p role="note" className={styles.sourceNote}>
          The cited text is no longer found in the file. It read: <q>{location.quote}</q>
        </p>
      )}
      {/* Scrolls on its own, so it takes keyboard focus: arrow keys scroll it. */}
      <div className={styles.document} tabIndex={0} role="region" aria-label="Document text">
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
