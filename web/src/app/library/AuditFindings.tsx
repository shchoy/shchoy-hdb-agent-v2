"use client";

import { useEffect, useState, type ReactNode } from "react";
import type { components } from "@/lib/api/schema";
import type { AuditDocRef, AuditReport, AuditSide } from "@/lib/events";
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
    <section aria-labelledby={heading} className={styles.auditSection}>
      <h2 id={heading} className={styles.heading}>
        {title} <span className={styles.count}>({count})</span>
      </h2>
      {count === 0 ? <p className={styles.meta}>None found</p> : children}
    </section>
  );
}

function Doc({ doc }: { doc: AuditDocRef }) {
  return (
    <span>
      <span className={styles.title}>{doc.title}</span> <span className={styles.docType}>{doc.doc_type}</span>
      {doc.version && <span className={styles.location}> v{doc.version}</span>}
      {doc.status === "superseded" && <span className={styles.superseded}>Superseded</span>}{" "}
      <DocumentViewer docId={doc.doc_id} label={`Open ${doc.title}`} />
    </span>
  );
}

function Side({ name, side, prevails }: { name: "A" | "B"; side: AuditSide; prevails: boolean }) {
  return (
    <div role="group" aria-label={`Side ${name}: ${side.title}`} className={styles.side}>
      <p>
        <span className={styles.title}>{side.title}</span>
        {side.version && <span className={styles.location}> v{side.version}</span>}
        {prevails && <span className={styles.prevails}>Prevails</span>}
      </p>
      {side.location && <p className={styles.location}>{side.location}</p>}
      <blockquote className={styles.quote}>{side.quote}</blockquote>
      {side.doc_id === null ? (
        <p className={styles.record}>PLG Records</p>
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
        <ul className={styles.groups}>
          {conflicts.map((c) => (
            <li key={c.id} className={styles.group}>
              <article aria-label={c.topic}>
                <h3 className={styles.findingTitle}>{c.topic}</h3>
                <div className={styles.sides}>
                  <Side name="A" side={c.a} prevails={c.prevails === "a"} />
                  <Side name="B" side={c.b} prevails={c.prevails === "b"} />
                </div>
                <p>
                  <strong>Expected resolution:</strong> {c.resolution}
                </p>
              </article>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="duplicates" title="Near-duplicates" count={duplicates.length}>
        <ul className={styles.groups}>
          {duplicates.map((d) => (
            <li key={`${d.a.doc_id}-${d.b.doc_id}`} className={styles.group}>
              <p>
                <span className={styles.docType}>{DUPLICATE_KIND[d.kind]}</span>{" "}
                <span className={styles.count}>{Math.round(d.similarity * 100)}% similar</span>
              </p>
              <p className={styles.document}>
                <Doc doc={d.a} />
              </p>
              <p className={styles.document}>
                <Doc doc={d.b} />
              </p>
              <p className={styles.description}>{d.note}</p>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="stale" title="Stale documents" count={stale.length}>
        <ul className={styles.groups}>
          {stale.map((s) => (
            <li key={`${s.doc.doc_id}-${s.policy_id}`} className={styles.group}>
              <Doc doc={s.doc} />
              <blockquote className={styles.quote}>{s.quote}</blockquote>
              <p>
                Relies on {s.relies_on}. Current: {s.current_version}
                {since(s.current_from)}.
              </p>
              <p className={styles.description}>{s.reason}</p>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="definitions" title="Reports using superseded definitions" count={definitions.length}>
        <ul className={styles.groups}>
          {definitions.map((d) => (
            <li key={`${d.chunk_id}-${d.concept}`} className={styles.group}>
              <p>
                <span className={styles.title}>{d.doc.title}</span>{" "}
                <span className={styles.docType}>{d.doc.doc_type}</span>{" "}
                <QuoteViewer docId={d.doc.doc_id} chunkId={d.chunk_id} quote={d.quote} label={`Open ${d.doc.title}`} />
              </p>
              <p className={styles.location}>{d.location}</p>
              <blockquote className={styles.quote}>{d.quote}</blockquote>
              <p>
                Uses {d.used_version}; current: {d.current_version}
                {since(d.current_from)}.
              </p>
              <p className={styles.description}>{d.explanation}</p>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="rules" title="Data rule violations" count={violations.length}>
        <ul className={styles.groups}>
          {violations.map((v) => (
            <li key={`${v.rule}-${v.entity_ids.join(",")}`} className={styles.group}>
              <p>
                <span className={styles.title}>{RULE[v.rule] ?? v.rule}</span>{" "}
                {v.entity_ids.map((id) => (
                  <code key={id} className={styles.entity}>
                    {id}
                  </code>
                ))}
              </p>
              <p className={styles.description}>{v.detail}</p>
            </li>
          ))}
        </ul>
      </Section>

      <Section id="gaps" title="Gaps" count={gaps.length}>
        <ul className={styles.groups}>
          {gaps.map((g) => (
            <li key={g.question} className={styles.group}>
              <p className={styles.title}>{g.question}</p>
              <p className={styles.meta}>
                Asked {times(g.asked)}, last {when(g.last_asked)} ·{" "}
                {g.reasons.map((r) => gapReason(r, g.top_score ?? null)).join(", ")}
              </p>
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
