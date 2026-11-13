import { useId } from "react";
import type { DocCheckEvent } from "@/lib/events";
import styles from "./ask.module.css";
import { day } from "./dates";

/** A document check's result (the event's fields). */
export type DocCheck = Omit<DocCheckEvent, "type" | "seq">;
type Line = DocCheck["checklist"][number];
type Problem = NonNullable<Line["problem"]>;

const PROBLEMS: Record<Problem, string> = {
  expired: "Expired",
  wrong_unit: "Wrong unit",
  illegible_scan: "Illegible scan",
};

/** The tick or cross for a checklist line, with its text alternative. An optional document not sent gets neither. */
const MARKS: Record<Line["status"], { mark: string; label: string }> = {
  ok: { mark: "✓", label: "Submitted" },
  missing: { mark: "✗", label: "Missing" },
  problem: { mark: "✗", label: "Problem" },
  not_submitted: { mark: "–", label: "Not submitted (optional)" },
};

/**
 * An application's submitted documents against its type's checklist: ✓ / ✗ per document, the files behind each,
 * and why a submitted document can't be accepted; then every file of the bundle and what it was identified as.
 */
export function DocCheckCard({ check }: { check: DocCheck }) {
  const heading = useId();
  return (
    <section aria-labelledby={heading} className={styles.docCheck}>
      <h3 id={heading}>Document check</h3>
      <p className={check.complete ? styles.complete : styles.incomplete}>
        {check.complete ? "Complete" : "Incomplete"}
      </p>
      <dl aria-label="Application" className={styles.classificationFields}>
        <dt>Application</dt>
        <dd>
          {check.application_id} ({check.app_type_label})
        </dd>
        <dt>Tenant</dt>
        <dd>{check.tenant_name}</dd>
        <dt>Unit</dt>
        <dd>
          {check.unit_address} ({check.unit_id})
        </dd>
        <dt>Submitted</dt>
        <dd>{day(check.submitted_date)}</dd>
      </dl>
      <table className={styles.checklist}>
        <caption>Checklist</caption>
        <thead>
          <tr>
            <th scope="col">Status</th>
            <th scope="col">Document</th>
            <th scope="col">Files</th>
            <th scope="col">Problem</th>
          </tr>
        </thead>
        <tbody>
          {check.checklist.map((line) => {
            const { mark, label } = MARKS[line.status];
            return (
              <tr key={line.doc_code} data-status={line.status}>
                <td>
                  <span role="img" aria-label={label} title={label}>
                    {mark}
                  </span>
                </td>
                <th scope="row">
                  {line.label}
                  {!line.mandatory && " (optional)"}
                </th>
                <td>{line.files.length > 0 ? line.files.join(", ") : "None"}</td>
                <td>
                  {line.problem && (
                    <>
                      <strong>{PROBLEMS[line.problem]}</strong>
                      {line.reason && `: ${line.reason}`}
                    </>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <h4>Files submitted</h4>
      <ul aria-label="Files submitted" className={styles.files}>
        {check.files.map((f) => (
          <li key={f.file}>
            <code>{f.file}</code>: {f.doc_label ?? "Not on the checklist"}
            {f.read_by === "scan" && (
              <>
                {" "}
                <span className={styles.scan}>scan</span>
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
