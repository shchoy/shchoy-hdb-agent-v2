import { ROLES, type UserCtx } from "@/lib/events";
import styles from "./ask.module.css";

type Role = UserCtx["role"];

/**
 * Who may approve what each kind of prompt leads to, mirroring plg-api's APPROVER_ROLES (src/plg/actions/model.py):
 * a letter or notice (send_letter) not analysts; an i-EMS ticket (raise_ticket) neither analysts nor legal.
 */
const SEND_LETTER = ROLES.filter((r) => r !== "analyst");
const RAISE_TICKET = ROLES.filter((r) => r !== "analyst" && r !== "legal");

type Starter = { title: string; question: string; roles: readonly Role[] };

/**
 * The curated starter prompts, one per thing the Super-Librarian does. Each question is one the corpus and PLG
 * Records answer. The glossary prompt fills the analysts' welcome, who see none of the prompts that lead to an action.
 */
const STARTERS: readonly Starter[] = [
  { title: "Ask about a policy", question: "How far can a tenant display goods beyond the shopfront?", roles: ROLES },
  { title: "Query PLG Records", question: "Which tenancies have arrears above 3 months' rent?", roles: ROLES },
  {
    title: "Draft a letter",
    question: "Draft a first reminder letter for Golden Leaf Minimart Pte Ltd's overdue rent",
    roles: SEND_LETTER,
  },
  {
    title: "Classify feedback",
    question: "Classify: 'Ceiling near the shop wet and lights flickering, scared got short circuit'",
    roles: RAISE_TICKET,
  },
  {
    title: "Check an application's documents",
    question: "Is application APP-2026-0294 complete? Check the submitted documents.",
    roles: SEND_LETTER,
  },
  { title: "Look up a definition", question: "How is a vacant unit defined, and has the definition changed?", roles: ["analyst"] },
  { title: "My top tasks", question: "What are my top 5 tasks this week and why?", roles: ROLES },
];

function startersFor(role: Role): Starter[] {
  return STARTERS.filter((s) => s.roles.includes(role));
}

/** A new conversation's welcome: a greeting naming the officer and starter prompts for their role. Choosing one asks it. */
export function Welcome({ user, onAsk }: { user: Pick<UserCtx, "name" | "role">; onAsk: (question: string) => void }) {
  return (
    <section aria-labelledby="welcome-heading" className={styles.welcome}>
      <h2 id="welcome-heading">Good to see you, {user.name}</h2>
      <p className={styles.welcomeLead}>Ask anything about PLG&apos;s policies, records and cases, or start with one of these.</p>
      <ul aria-label="Starter prompts" className={styles.starters}>
        {startersFor(user.role).map((s) => (
          <li key={s.title}>
            <button type="button" className={styles.starter} onClick={() => onAsk(s.question)}>
              <span className={styles.starterTitle}>{s.title}</span>
              <span className={styles.starterQuestion}>{s.question}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
