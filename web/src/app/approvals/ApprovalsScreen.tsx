"use client";

import { useEffect, useId, useState } from "react";
import type { components } from "@/lib/api/schema";
import { roleLabel, type UserCtx } from "@/lib/events";
import { Badge, Card, cardListClass, fieldsClass } from "../Card";
import { day, when } from "../dates";
import { LetterFrame } from "../LetterFrame";
import { useShell } from "../shell/ShellContext";
import { ActionCard, describe, KIND_LABEL, Proposed, type Outcome } from "./ActionCard";
import styles from "./approvals.module.css";

type PendingApproval = components["schemas"]["PendingApproval"];

type AuditRecord = components["schemas"]["AuditRecord"];
type Ticket = components["schemas"]["Ticket"];
type Decision = "approve" | "edit" | "reject";

/** The officer's pending actions across conversations, with decision controls, then the decisions already made. */
export function ApprovalsScreen({ role, staffId }: { role: UserCtx["role"]; staffId: string }) {
  const [pending, setPending] = useState<PendingApproval[] | null>(null);
  const [audit, setAudit] = useState<AuditRecord[]>([]);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  // Which items show their detail view: kept by action ID across reloads after a decision.
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set());
  const shell = useShell();
  const failed = version === 0 ? "Could not load your approvals." : "Could not reload your approvals.";

  useEffect(() => {
    let current = true;
    Promise.all([fetch("/api/approvals"), fetch("/api/audit")])
      .then(async ([approvals, trail]) => {
        if (!current) return;
        if (!approvals.ok || !trail.ok) return setError(failed);
        const [nextPending, nextAudit] = [(await approvals.json()) as PendingApproval[], (await trail.json()) as AuditRecord[]];
        if (!current) return;
        setError(null);
        setPending(nextPending);
        setAudit(nextAudit);
      })
      .catch(() => current && setError(failed));
    return () => {
      current = false;
    };
  }, [version, failed]);

  function toggle(actionId: string) {
    setOpened((o) => {
      const next = new Set(o);
      if (!next.delete(actionId)) next.add(actionId);
      return next;
    });
  }

  function decided(outcome: Outcome) {
    setOutcomes((o) => [outcome, ...o]);
    setVersion((v) => v + 1);
    shell.refresh(); // the sidebar's pending count
  }

  if (!pending) return error ? <p role="alert">{error}</p> : <p>Loading…</p>;

  return (
    <>
      {error && <p role="alert">{error}</p>}
      {outcomes.length > 0 && (
        <div role="status" aria-label="Results">
          {outcomes.map((outcome) => (
            <p key={`${outcome.result.action_id}-v${outcome.result.version}`}>{describe(outcome)}</p>
          ))}
        </div>
      )}
      <section aria-labelledby="pending-heading">
        <h2 id="pending-heading">Waiting for you</h2>
        {pending.length === 0 ? (
          <p>Nothing is waiting for your approval.</p>
        ) : (
          <ul aria-label="Pending approvals" className={cardListClass}>
            {pending.map((action) => (
              <li key={`${action.action_id}-v${action.version}`}>
                <PendingItem
                  action={action}
                  open={opened.has(action.action_id)}
                  onToggle={() => toggle(action.action_id)}
                  role={role}
                  staffId={staffId}
                  onDecided={decided}
                />
              </li>
            ))}
          </ul>
        )}
      </section>
      <section aria-labelledby="audit-heading">
        <h2 id="audit-heading">Decided</h2>
        {audit.length === 0 ? <p>No decisions yet.</p> : <AuditTrail entries={audit} />}
      </section>
    </>
  );
}

/**
 * One pending action as a line of the inbox (type, title, conversation, who proposed it and when); its title opens
 * the detail view below it: the preview, the diff of edits and the decision controls.
 */
function PendingItem({
  action,
  open,
  onToggle,
  role,
  staffId,
  onDecided,
}: {
  action: PendingApproval;
  open: boolean;
  onToggle: () => void;
  role: UserCtx["role"];
  staffId: string;
  onDecided: (outcome: Outcome) => void;
}) {
  const detail = useId();
  // A curator deciding on someone else's thread sees it titled "Proposed by <ID>": that is said once already.
  const conversation = action.thread_title && action.thread_title !== `Proposed by ${action.proposed_by}` ? action.thread_title : null;
  return (
    <Card
      as="article"
      heading={
        <button type="button" className={styles.toggle} aria-expanded={open} aria-controls={detail} onClick={onToggle}>
          {action.title}
        </button>
      }
      badges={<Badge>{KIND_LABEL[action.payload.kind]}</Badge>}
    >
      <p className={styles.meta}>
        {conversation && <span>Conversation: {conversation}</span>}
        <Proposed by={action.proposed_by} at={action.proposed_at} />
      </p>
      {/* Kept mounted while collapsed: half-typed edits, a reason or a refusal survive closing it. */}
      <div id={detail} hidden={!open} className={styles.opened}>
        <ActionCard action={action} role={role} staffId={staffId} onDecided={onDecided} />
      </div>
    </Card>
  );
}

const DECIDED: Record<AuditRecord["action_type"], Record<Decision, string>> = {
  send_letter: { approve: "Approved and sent", edit: "Sent with edits", reject: "Rejected" },
  raise_ticket: { approve: "Approved and raised", edit: "Raised with edits", reject: "Rejected" },
  approve_glossary_term: { approve: "Approved and adopted", edit: "Adopted with edits", reject: "Rejected" },
  approve_team_fact: { approve: "Approved", edit: "Approved with edits", reject: "Rejected" },
  approve_example: { approve: "Approved", edit: "Approved with edits", reject: "Rejected" },
  approve_sql_example: { approve: "Approved", edit: "Approved with edits", reject: "Rejected" },
};
const NOTHING_DONE: Record<AuditRecord["action_type"], string> = {
  send_letter: "Nothing was sent.",
  raise_ticket: "Nothing was raised.",
  approve_glossary_term: "Nothing was changed.",
  approve_team_fact: "Nothing was taught to the team.",
  approve_example: "Nothing was taught to the team.",
  approve_sql_example: "Nothing was taught to the team.",
};

const KIND_OF: Record<AuditRecord["action_type"], string> = {
  send_letter: KIND_LABEL.letter,
  raise_ticket: KIND_LABEL.ticket,
  approve_glossary_term: KIND_LABEL.glossary,
  approve_team_fact: KIND_LABEL.team_fact,
  approve_example: KIND_LABEL.example,
  approve_sql_example: KIND_LABEL.sql_example,
};

const CURATED = new Set<AuditRecord["action_type"]>(["approve_team_fact", "approve_example", "approve_sql_example"]);

/** Every decision the officer made: who, when, why, what changed, what went to the outbox and the run's trace. */
function AuditTrail({ entries }: { entries: AuditRecord[] }) {
  return (
    <ul aria-label="Audit trail" className={cardListClass}>
      {entries.map((e) => {
        return (
          <li key={e.action_id}>
            <Card
              as="article"
              heading={e.title || e.action_id}
              badges={
                <>
                  <Badge>{KIND_OF[e.action_type]}</Badge>
                  <Badge tone={e.decision === "reject" ? "neutral" : "success"}>{DECIDED[e.action_type][e.decision]}</Badge>
                </>
              }
            >
              <p>
                {DECIDED[e.action_type][e.decision]} by {e.approver} ({roleLabel(e.approver_role)}) on {when(e.at)}, deciding on
                version {e.version}.
              </p>
              {e.reason && <p>Reason: {e.reason}</p>}
              {Object.keys(e.edits).length > 0 && (
                <ul aria-label="Edits">
                  {Object.entries(e.edits).map(([slot, value]) => (
                    <li key={slot}>
                      {slot}: {value}
                    </li>
                  ))}
                </ul>
              )}
              {e.ticket ? (
                <RaisedTicket ticket={e.ticket} />
              ) : e.sent ? (
                <p>
                  Outbox item {e.sent.item_id} (version {e.sent.version}) to {e.sent.recipient}, sent {when(e.sent.sent_at)}
                </p>
              ) : e.term_id ? (
                <p>Adopted as glossary term {e.term_id}.</p>
              ) : e.decision !== "reject" && CURATED.has(e.action_type) ? (
                <p>Taught to the team.</p>
              ) : (
                <p>{NOTHING_DONE[e.action_type]}</p>
              )}
              <p className={styles.muted}>Trace {e.run_id}</p>
              {e.sent && (
                <details>
                  <summary>Letter as sent</summary>
                  <LetterFrame title={`Letter sent: ${e.title}`} html={e.sent.html} />
                </details>
              )}
            </Card>
          </li>
        );
      })}
    </ul>
  );
}

/** The i-EMS ticket a decision raised, as i-EMS holds it. */
function RaisedTicket({ ticket: t }: { ticket: Ticket }) {
  return (
    <>
      <p>
        i-EMS ticket {t.ticket_id} (version {t.version}) raised {when(t.raised_at)}, status {t.status}
      </p>
      <dl aria-label="Raised ticket" className={fieldsClass}>
        <dt>Feedback case</dt>
        <dd>{t.feedback_id}</dd>
        <dt>Category</dt>
        <dd>
          {t.category} ({t.category_code})
        </dd>
        <dt>Priority</dt>
        <dd>{t.severity}</dd>
        <dt>Team</dt>
        <dd>{t.team}</dd>
        <dt>Vendor</dt>
        <dd>{t.vendor ?? "No vendor (handled by the team)"}</dd>
        <dt>SLA</dt>
        <dd>
          {t.sla_days} day{t.sla_days === 1 ? "" : "s"}, due {day(t.due_date)}
        </dd>
        <dt>Unit</dt>
        <dd>{t.unit_id ?? "Not given"}</dd>
      </dl>
    </>
  );
}
