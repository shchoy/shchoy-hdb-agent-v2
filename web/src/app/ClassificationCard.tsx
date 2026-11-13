import { useId } from "react";
import type { ClassificationEvent } from "@/lib/events";
import styles from "./ask.module.css";

/** What the classifier decided about a piece of feedback (the event's fields, or a proposed ticket's). */
export type Classification = Omit<ClassificationEvent, "type" | "seq">;

function percent(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

function days(n: number): string {
  return `${n} day${n === 1 ? "" : "s"}`;
}

/**
 * The classification's details: category, severity, routing team and vendor, the i-EMS SLA (defects only),
 * confidence with a flag when an officer should check it, the other plausible categories and the rationale.
 */
export function ClassificationDetails({ found }: { found: Classification }) {
  const others = found.candidates.filter((c) => c.code !== found.category_code);
  return (
    <>
      {found.low_confidence && (
        <p className={styles.lowConfidence}>Low confidence — please check</p>
      )}
      <dl aria-label="Classification" className={styles.classificationFields}>
        <dt>Category</dt>
        <dd>
          {found.category} ({found.category_code})
        </dd>
        <dt>Severity</dt>
        <dd>{found.severity}</dd>
        <dt>Team</dt>
        <dd>{found.team}</dd>
        <dt>Vendor</dt>
        <dd>{found.vendor ?? "No vendor (handled by the team)"}</dd>
        {found.is_defect && found.sla_days !== null && (
          <>
            <dt>i-EMS SLA</dt>
            <dd>{days(found.sla_days)}</dd>
          </>
        )}
        <dt>Confidence</dt>
        <dd>{percent(found.confidence)}</dd>
      </dl>
      {!found.is_defect && <p>Not a maintenance defect — no i-EMS ticket. {found.team} handles it.</p>}
      {others.length > 0 && (
        <>
          <h4>Also plausible</h4>
          <ul aria-label="Other plausible categories">
            {others.map((c) => (
              <li key={c.code}>
                {c.category} ({c.code}), {c.severity}, {percent(c.confidence)}
              </li>
            ))}
          </ul>
        </>
      )}
      <p>
        <strong>Rationale:</strong> {found.rationale}
      </p>
    </>
  );
}

/** Feedback classified into the defect taxonomy, under the answer. A ticket, if any, waits in Approvals. */
export function ClassificationCard({ found }: { found: Classification }) {
  const heading = useId();
  return (
    <section aria-labelledby={heading} className={styles.classification}>
      <h3 id={heading}>Feedback classification</h3>
      <ClassificationDetails found={found} />
    </section>
  );
}
