import type { InjectionEvent } from "@/lib/events";
import styles from "./ask.module.css";

/** One prompt-injection flag: in the officer's own message, or in a document the assistant read. */
export type InjectionFlag = Omit<InjectionEvent, "type" | "seq">;

/** What each detection rule means, for the officer. */
const RULE_LABELS: Record<InjectionFlag["rules"][number], string> = {
  override: "tries to override the assistant's instructions",
  ai_address: "addresses the assistant directly",
  approval_bypass: "tries to skip human approval",
  authority_claim: "claims authority it doesn't have",
  concealment: "asks to hide itself",
  prompt_leak: "asks for the assistant's hidden instructions",
  role_change: "tries to change the assistant's role",
};

function Flag({ flag }: { flag: InjectionFlag }) {
  const fromMessage = flag.source === "message";
  return (
    <div className={styles.injectionFlag}>
      <p>
        <strong>
          {fromMessage
            ? "Possible prompt injection in your message"
            : `Suspicious document: ${flag.title ?? flag.doc_id ?? "a document the assistant read"}`}
        </strong>
      </p>
      {flag.rules.length > 0 && (
        <ul aria-label="What was detected">
          {flag.rules.map((rule) => (
            <li key={rule}>{RULE_LABELS[rule]}</li>
          ))}
        </ul>
      )}
      {/* The planted text is shown as plain text only: React escapes it, so no markup in it ever renders. */}
      {flag.excerpt && <blockquote className={styles.injectionExcerpt}>{flag.excerpt}</blockquote>}
      <p>
        {fromMessage
          ? "It was ignored; nothing was done. Report it as suspicious."
          : "Its planted instructions were removed and ignored; no action was proposed. Report it as suspicious."}
      </p>
    </div>
  );
}

/** Instructions planted for the assistant this turn (prompt injection), all listed in one alert above the answer. */
export function InjectionAlert({ flags }: { flags: InjectionFlag[] }) {
  if (flags.length === 0) return null;
  return (
    <div role="alert" className={`${styles.alert} ${styles.injection}`}>
      {flags.map((flag, i) => (
        <Flag key={i} flag={flag} />
      ))}
    </div>
  );
}
