import type { PolicyStanceEvent } from "@/lib/events";
import { day, period as span } from "./dates";
import styles from "./ask.module.css";

type Stance = PolicyStanceEvent;

function period(from: string | null, to: string | null): string {
  return span(from, to, "dates not recorded");
}

function Evidence({ quote }: { quote: string }) {
  return (
    <details>
      <summary>Evidence</summary>
      <blockquote>{quote}</blockquote>
    </details>
  );
}

/**
 * Where a policy stands today: the version in force, the versions it superseded, and the circulars that override
 * one of its clauses. An override's scope (e.g. "NC units only") is shown apart from the dates because the policy
 * still applies unchanged to every other unit type.
 */
export function PolicyStanceCard({ stance }: { stance: Stance }) {
  const heading = `stance-${stance.policy_id.replace(/\W+/g, "-")}`;
  const current = stance.versions.find((v) => v.id === stance.current);
  const superseded = stance.versions.filter((v) => v.status === "superseded");
  const evidenceFor = (older: string) => stance.supersessions.find((s) => s.older === older);
  return (
    <section aria-labelledby={heading} className={styles.stance}>
      <h4 id={heading}>
        Policy stance: {stance.title} <span className={styles.location}>({stance.policy_id})</span>
      </h4>
      <p>
        {current ? (
          <>
            <strong>In force:</strong> version {current.version}, {period(current.effective_from, current.effective_to)}.
          </>
        ) : (
          <strong>No version of this policy is in force.</strong>
        )}
      </p>

      {superseded.length > 0 && (
        <>
          <h5>Superseded versions</h5>
          <ul aria-label="Superseded versions">
            {superseded.map((v) => {
              const evidence = evidenceFor(v.id);
              return (
                <li key={v.id} className={styles.stanceSuperseded}>
                  <span className={styles.stanceName}>Version {v.version}</span> (superseded
                  {v.effective_to ? `, ended ${day(v.effective_to)}` : ""})
                  {evidence && <Evidence quote={evidence.evidence_quote} />}
                </li>
              );
            })}
          </ul>
        </>
      )}

      {stance.overrides.length > 0 && (
        <>
          <h5>Overriding circulars</h5>
          <ul aria-label="Overriding circulars">
            {stance.overrides.map((o) => (
              <li key={`${o.circular_id}-${o.clause_id}`}>
                {o.circular_id} overrides clause {o.clause_number} of version {o.policy_version},{" "}
                {period(o.effective_from, o.effective_to)}.{" "}
                {o.scope ? (
                  <>
                    Applies to: <span className={styles.scope}>{o.scope}</span>. Other unit types keep the policy as written.
                  </>
                ) : (
                  "Applies to all units."
                )}
                <Evidence quote={o.evidence_quote} />
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
