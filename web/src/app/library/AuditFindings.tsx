"use client";

import { useEffect, useState, type ReactNode } from "react";
import type { components } from "@/lib/api/schema";
import type { AuditDocRef, AuditReport, AuditSide } from "@/lib/events";
import { Badge, Card, cardListClass } from "../Card";
import { day, when } from "../dates";
import { DocumentViewer, QuoteViewer } from "../SourceViewer";
import styles from "./library.module.css";

type Schemas = components["schemas"];
type Loaded =
  | { status: "loading" }
  | { status: "none" }
  | { status: "failed"; error: string }
  | { status: "ok"; report: AuditReport };

const DUPLICATE_KIND: Record<Schemas["Duplicate"]["kind"], string> = {
  near_duplicate: "Near-duplicate",
  same_content: "Same content",
  earlier_version: "Earlier version",
};

const RULE: Record<Schemas["RuleViolation"]["rule"], string> = {
  overlapping_tenancies: "Overlapping tenancies",
  two_current_policy_versions: "Two current policy versions",
  trade_not_allowed: "Trade not allowed",
  duplicate_tenants: "Duplicate tenants",
};

function gapReason(reason: string, score: number | null): string {
  if (reason === "not_covered") return "Not covered";
  if (reason === "low_score") return score === null ? "Low search score" : `Low search score (${score})`;
  if (reason === "thumbs_down") return "Rated not helpful";
  return reason;
}

function since(from: string | null): string {
  return from ? ` from ${day(from)}` : "";
}

function times(n: number): string {
  return n === 1 ? "once" : `${n} times`;
}

/** A findings section: its heading carries the count; an empty one says so. */
function Section({ id, title, count, children }: { id: string; title: string; count: number; children: ReactNode }) {
  const heading = `audit-${id}`;
  return (
    <section aria-labelledby={heading} className={styles.section}>
      <h2 id={heading} className={styles.sectionHeading}>
        {title} <span className={styles.count}>({count})</span>
      </h2>
      {count === 0 ? <p className={styles.meta}>None found</p> : children}
    </section>
  );
}

/** A Library document: an audit finding's or a category's. */
type LibraryDoc = Pick<AuditDocRef, "doc_id" | "title" | "doc_type"> & {
  version?: string | null;
  status?: AuditDocRef["status"];
};

/** A document (place it in a `docLine` container): its title (unless the card's heading already names it), type, version, status and viewer. */
export function Doc({ doc, titled = true }: { doc: LibraryDoc; titled?: boolean }) {
  return (
    <>
      {titled && <span className={styles.title}>{doc.title}</span>} <Badge>{doc.doc_type}</Badge>
      {doc.version && <span className={styles.location}> v{doc.version}</span>}
      {doc.status === "superseded" && (
        <>
          {" "}
          <Badge tone="warning">Superseded</Badge>
        </>
      )}{" "}
      <DocumentViewer docId={doc.doc_id} label={`Open ${doc.title}`} />
    </>
  );
}

function Side({ name, side, prevails }: { name: "A" | "B"; side: AuditSide; prevails: boolean }) {
  return (
    <div
      role="group"
      aria-label={`Side ${name}: ${side.title}`}
      className={styles.side}
      data-prevails={prevails || undefined}
    >
      <p className={styles.sideHead}>
        <span className={styles.sideName}>{name}</span>
        <span className={styles.title}>{side.title}</span>
        {side.version && <span className={styles.location}>v{side.version}</span>}
        {prevails && (
          <Badge tone="success" as="strong">
            Prevails
          </Badge>
        )}
      </p>
      {side.location && <p className={styles.location}>{side.location}</p>}
      <blockquote className={styles.quote}>{side.quote}</blockquote>
      {side.doc_id === null ? (
        <p className={styles.record}>
          <Badge>PLG Records</Badge>
        </p>
      ) : (
        side.chunk_id && (
          <QuoteViewer docId={side.doc_id} chunkId={side.chunk_id} quote={side.quote} label={`Open ${side.title}`} />
        )
      )}
    </div>
  );
}

/**
 * The latest corpus audit (`plg audit`): conflicting statements, near-duplicates, stale documents, reports using
 * superseded definitions, PLG Records rule violations and unanswered questions. Quotes are plain text.
 */
export function AuditFindings() {
  const [loaded, setLoaded] = useState<Loaded>({ status: "loading" });

  useEffect(() => {
    let current = true;
    fetch("/api/audit/reports/latest")
      .then(async (response) => {
        if (!current) return;
        if (response.status === 404) return setLoaded({ status: "none" });
        if (!response.ok) {
          const error =
            response.status === 401
              ? "You are no longer signed in. Sign in again."
              : "Could not load the audit findings.";
          return setLoaded({ status: "failed", error });
        }
        const report = (await response.json()) as AuditReport;
        if (current) setLoaded({ status: "ok", report });
      })
      .catch(() => current && setLoaded({ status: "failed", error: "Could not load the audit findings." }));
    return () => {
      current = false;
    };
  }, []);

  if (loaded.status === "loading") return <p role="status">Loading the audit findings…</p>;
  if (loaded.status === "failed") return <p role="alert">{loaded.error}</p>;
  if (loaded.status === "none")
    return (
      <p role="note" className={styles.meta}>
        No corpus audit has run yet. A policy owner runs <code>plg audit</code> to check the corpus.
      </p>
    );

  const { report } = loaded;
  const conflicts = report.conflicts ?? [];
  const duplicates = report.duplicates ?? [];
  const stale = report.stale ?? [];
  const definitions = report.superseded_definitions ?? [];
  const violations = report.rule_violations ?? [];
  const gaps = report.gaps ?? [];
  const dropped = report.dropped ?? [];

  return (
    <>
      <p className={styles.meta}>
        Audit of {report.documents} documents on {when(report.generated_at)}
      </p>

      <Section id="conflicts" title="Conflicts" count={conflicts.length}>
        <ul className={cardListClass}>
          {conflicts.map((c) => (
            <li key={c.id}>
              <Card as="article" heading={c.topic} badges={<Badge tone="danger">Conflict</Badge>}>
                <div className={styles.sides}>
                  <Side name="A" side={c.a} prevails={c.prevails === "a"} />
                  <Side name="B" side={c.b} prevails={c.prevails === "b"} />
                </div>
                <p className={styles.resolution}>
                  <strong>Expected resolution:</strong> {c.resolution}
                </p>
              </Card>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="duplicates" title="Near-duplicates" count={duplicates.length}>
        <ul className={cardListClass}>
          {duplicates.map((d) => (
            <li key={`${d.a.doc_id}-${d.b.doc_id}`}>
              <Card
                as="article"
                heading={
                  <>
                    {DUPLICATE_KIND[d.kind]}
                    <span className={styles.visuallyHidden}>: {d.a.title}</span>
                  </>
                }
                badges={<Badge>{Math.round(d.similarity * 100)}% similar</Badge>}
              >
                <p className={`${styles.document} ${styles.docLine}`}>
                  <Doc doc={d.a} />
                </p>
                <p className={`${styles.document} ${styles.docLine}`}>
                  <Doc doc={d.b} />
                </p>
                <p className={styles.description}>{d.note}</p>
              </Card>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="stale" title="Stale documents" count={stale.length}>
        <ul className={cardListClass}>
          {stale.map((s) => (
            <li key={`${s.doc.doc_id}-${s.policy_id}`}>
              <Card as="article" heading={s.doc.title} badges={<Badge tone="warning">Stale</Badge>}>
                <p className={styles.docLine}>
                  <Doc doc={s.doc} titled={false} />
                </p>
                <blockquote className={styles.quote}>{s.quote}</blockquote>
                <p>
                  Relies on {s.relies_on}. Current: {s.current_version}
                  {since(s.current_from)}.
                </p>
                <p className={styles.description}>{s.reason}</p>
              </Card>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="definitions" title="Reports using superseded definitions" count={definitions.length}>
        <ul className={cardListClass}>
          {definitions.map((d) => (
            <li key={`${d.chunk_id}-${d.concept}`}>
              <Card as="article" heading={d.doc.title} badges={<Badge tone="warning">Superseded definition</Badge>}>
                <p className={styles.docLine}>
                  <Badge>{d.doc.doc_type}</Badge>{" "}
                  <QuoteViewer docId={d.doc.doc_id} chunkId={d.chunk_id} quote={d.quote} label={`Open ${d.doc.title}`} />
                </p>
                <p className={styles.location}>{d.location}</p>
                <blockquote className={styles.quote}>{d.quote}</blockquote>
                <p>
                  Uses {d.used_version}; current: {d.current_version}
                  {since(d.current_from)}.
                </p>
                <p className={styles.description}>{d.explanation}</p>
              </Card>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="rules" title="Data rule violations" count={violations.length}>
        <ul className={cardListClass}>
          {violations.map((v) => (
            <li key={`${v.rule}-${v.entity_ids.join(",")}`}>
              <Card as="article" heading={RULE[v.rule] ?? v.rule}>
                <p className={styles.entities}>
                  {v.entity_ids.map((id) => (
                    <code key={id} className={styles.entity}>
                      {id}
                    </code>
                  ))}
                </p>
                <p className={styles.description}>{v.detail}</p>
              </Card>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="gaps" title="Gaps" count={gaps.length}>
        <ul className={cardListClass}>
          {gaps.map((g) => (
            <li key={g.question}>
              <Card
                as="article"
                heading={g.question}
                badges={g.reasons.map((r) => (
                  <Badge key={r}>{gapReason(r, g.top_score ?? null)}</Badge>
                ))}
              >
                <p className={styles.meta}>
                  Asked {times(g.asked)}, last {when(g.last_asked)}
                </p>
              </Card>
            </li>
          ))}
        </ul>
      </Section>

      {dropped.length > 0 && (
        <details className={styles.dropped}>
          <summary>Findings dropped for lack of verbatim evidence ({dropped.length})</summary>
          <ul>
            {dropped.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
