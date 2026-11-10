"use client";

import { memo, useState } from "react";
import type { SqlTraceEvent } from "@/lib/events";
import { day, period } from "./dates";
import styles from "./ask.module.css";

type Result = NonNullable<SqlTraceEvent["result"]>;
type Cell = Result["rows"][number][number];
type Concept = SqlTraceEvent["concepts"][number];

/** Rows shown in a query's result table; the CSV export has them all. */
const TABLE_ROWS = 10;

function inForce({ effective_from: from, effective_to: to }: Concept): string {
  return `in force ${period(from, to, "since before records began")}`;
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

/** Copies the SQL; says so, or says to copy it by hand when the clipboard is unavailable (e.g. plain HTTP). */
function CopySql({ sql }: { sql: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  async function copy() {
    try {
      await navigator.clipboard.writeText(sql);
      setState("copied");
    } catch {
      setState("failed");
    }
  }
  return (
    <>
      <button type="button" onClick={() => void copy()} onBlur={() => setState("idle")}>
        {state === "copied" ? "Copied" : "Copy SQL"}
      </button>
      <span role="status" className={styles.hint}>
        {state === "failed" && " Could not copy. Select the SQL and copy it by hand."}
      </span>
    </>
  );
}

/** Memoised: a trace's result never changes, so the CSV is built once, not on every streamed token. */
const ResultTable = memo(function ResultTable({ result, queryNumber }: { result: Result; queryNumber: number }) {
  const shown = result.rows.slice(0, TABLE_ROWS);
  const total = `${result.row_count}${result.truncated ? "+" : ""} rows`;
  const csv = csvHref(result);
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
          Showing the first {shown.length} of {total}. Export CSV for all of them.
        </p>
      )}
      <a href={csv} download={`query-${queryNumber}.csv`}>
        Export CSV
      </a>
    </>
  );
});

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
              <p className={styles.queryStatus}>
                As of {day(t.as_of)} · {t.status === "ok" ? "Ran" : "Rejected"}
              </p>
              <figure aria-label="SQL" className={styles.sqlFigure}>
                <pre className={styles.sql}>
                  <code>{t.sql}</code>
                </pre>
              </figure>
              <CopySql sql={t.sql} />
              {t.error && <p className={styles.queryError}>{t.error}</p>}
              {t.status === "ok" && t.concepts.length > 0 && (
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
              {t.result && <ResultTable result={t.result} queryNumber={i + 1} />}
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
