"use client";

import { useState } from "react";
import type { SqlTraceEvent } from "@/lib/events";
import { day } from "./dates";
import styles from "./ask.module.css";

type Result = NonNullable<SqlTraceEvent["result"]>;
type Cell = Result["rows"][number][number];
type Concept = SqlTraceEvent["concepts"][number];

/** Rows shown in a query's result table; the CSV export has them all. */
const SHOWN_ROWS = 10;

function inForce({ effective_from: from, effective_to: to }: Concept): string {
  if (from && to) return `in force from ${day(from)} to ${day(to)}`;
  if (from) return `in force from ${day(from)}`;
  if (to) return `in force until ${day(to)}`;
  return "in force since before records began";
}

/**
 * One CSV field (RFC 4180). Text that a spreadsheet would run as a formula (=, +, -, @, tab, CR) is prefixed
 * with an apostrophe, so opening the export never executes a value from the records.
 */
function csvField(cell: Cell): string {
  if (cell === null) return "";
  let text = String(cell);
  if (typeof cell === "string" && /^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

/** Every fetched row as CSV (with a BOM so Excel reads it as UTF-8), as a data URL to download. */
function csvHref(result: Result): string {
  const lines = [result.columns, ...result.rows].map((row) => row.map(csvField).join(","));
  return `data:text/csv;charset=utf-8,${encodeURIComponent(`﻿${lines.join("\r\n")}\r\n`)}`;
}

function CopySql({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() =>
        void navigator.clipboard.writeText(sql).then(
          () => setCopied(true),
          () => setCopied(false),
        )
      }
    >
      {copied ? "Copied" : "Copy SQL"}
    </button>
  );
}

function ResultTable({ result, n }: { result: Result; n: number }) {
  const shown = result.rows.slice(0, SHOWN_ROWS);
  const total = `${result.row_count}${result.truncated ? "+" : ""} rows`;
  return (
    <>
      <div className={styles.resultScroll}>
        <table className={styles.result}>
          <caption>
            Result: {total}
            {result.truncated && " (more rows than are fetched; the export has the first ones)"}
          </caption>
          <thead>
            <tr>
              {result.columns.map((c) => (
                <th key={c} scope="col">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, i) => (
              <tr key={i}>
                {row.map((cell, j) => (
                  <td key={j}>{cell ?? ""}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {result.rows.length > shown.length && (
        <p className={styles.hint}>
          Showing the first {shown.length} of {result.row_count}
          {result.truncated ? "+" : ""} rows. Export CSV for all of them.
        </p>
      )}
      <a href={csvHref(result)} download={`query-${n}.csv`}>
        Export CSV
      </a>
    </>
  );
}

/**
 * How a data answer was reached: each query the data agent ran (plan, SQL, result or the reason it was rejected,
 * the glossary definitions it relied on with their dates in force, data-quality warnings) and its explanation.
 */
export function ReasoningPanel({ traces }: { traces: SqlTraceEvent[] }) {
  const explanation = traces.at(-1)?.explanation ?? "";
  return (
    <details className={styles.reasoning}>
      <summary>Reasoning</summary>
      <section aria-label="Reasoning">
        <ol aria-label="Queries" className={styles.queries}>
          {traces.map((t, i) => (
            <li key={t.seq}>
              <h4>
                Query {i + 1}: {t.plan}
              </h4>
              <p className={styles.location}>
                As of {day(t.as_of)} · {t.status === "ok" ? "Ran" : "Rejected"}
              </p>
              <figure aria-label="SQL" className={styles.sqlFigure}>
                <pre className={styles.sql}>
                  <code>{t.sql}</code>
                </pre>
              </figure>
              <CopySql sql={t.sql} />
              {t.error && <p className={styles.queryError}>{t.error}</p>}
              {t.concepts.length > 0 && (
                <>
                  <h5>Definitions used</h5>
                  <ul aria-label="Definitions used">
                    {t.concepts.map((c) => (
                      <li key={c.id}>
                        {c.label} v{c.version} (<code>{c.id}</code>), {inForce(c)}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              {t.warnings.length > 0 && (
                <ul aria-label="Data-quality warnings" className={styles.warnings}>
                  {t.warnings.map((w, k) => (
                    <li key={k}>{w}</li>
                  ))}
                </ul>
              )}
              {t.result && <ResultTable result={t.result} n={i + 1} />}
            </li>
          ))}
        </ol>
        {explanation && (
          <>
            <h4>Explanation</h4>
            <p className={styles.explanation}>{explanation}</p>
          </>
        )}
      </section>
    </details>
  );
}
