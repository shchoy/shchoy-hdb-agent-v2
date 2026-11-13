"use client";

import { useEffect, useState } from "react";
import type { components } from "@/lib/api/schema";
import { parseRunEvents, roleLabel, type RunEvent, type UserCtx } from "@/lib/events";
import { ClassificationDetails } from "../ClassificationCard";
import { day, when } from "../dates";
import { LetterFrame } from "../LetterFrame";
import styles from "./approvals.module.css";

type PendingApproval = components["schemas"]["PendingApproval"];

type AuditRecord = components["schemas"]["AuditRecord"];
type Ticket = components["schemas"]["Ticket"];
type Decision = "approve" | "edit" | "reject";
type ActionResult = Extract<RunEvent, { type: "action_result" }>;
/** What a decision did, for the officer to see straight away. */
type Outcome = { title: string; kind: Kind; result: ActionResult };
type Kind = PendingApproval["payload"]["kind"];
type LetterPayload = components["schemas"]["LetterPayload"];
type TicketPayload = components["schemas"]["TicketPayload"];

/** The officer's pending actions across conversations, with decision controls, then the decisions already made. */
export function ApprovalsScreen({ role }: { role: UserCtx["role"] }) {
  const [pending, setPending] = useState<PendingApproval[] | null>(null);
  const [audit, setAudit] = useState<AuditRecord[]>([]);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
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

  function decided(outcome: Outcome) {
    setOutcomes((o) => [outcome, ...o]);
    setVersion((v) => v + 1);
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
          <ul aria-label="Pending approvals" className={styles.list}>
            {pending.map((action) => (
              <li key={`${action.action_id}-v${action.version}`}>
                <ActionCard action={action} role={role} onDecided={decided} />
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

function describe({ title, kind, result }: Outcome): string {
  const ticket = kind === "ticket";
  if (result.decision === "reject") return `${title}: rejected; nothing was ${ticket ? "raised" : "sent"}.`;
  const edited = result.decision === "edit";
  if (ticket) return `${title}: ${edited ? "raised with your edits" : "raised"} as ${result.ticket_id} (version ${result.version}).`;
  return `${title}: ${edited ? "sent with your edits" : "sent"} as ${result.outbox_id} (version ${result.version}).`;
}

type DecisionBody = { decision: Decision; edits?: Record<string, string>; reason?: string };

/** Sends the decision and reads the resumed run until the action's result (or the reason it was refused). */
async function decide(action: PendingApproval, body: DecisionBody): Promise<ActionResult | string> {
  let response: Response;
  try {
    response = await fetch(`/api/threads/${encodeURIComponent(action.thread_id)}/resume`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action_id: action.action_id, version: action.version, ...body }),
    });
  } catch {
    return "Could not reach the server. Try again.";
  }
  if (!response.ok || !response.body) {
    const detail = ((await response.json().catch(() => null)) as { detail?: unknown } | null)?.detail;
    return typeof detail === "string" ? detail : "That decision did not go through.";
  }
  // Read to the end: the run may go on to pause on the thread's other pending actions.
  let result: ActionResult | string = "No result came back. Reload to check.";
  try {
    for await (const event of parseRunEvents(response.body)) {
      // Once the action's result is in, it was carried out: a later failure of the run doesn't undo it.
      if (typeof result !== "string") continue;
      if (event.type === "action_result" && event.action_id === action.action_id) result = event;
      else if (event.type === "error") result = `It failed: ${event.message}`;
    }
  } catch {
    if (typeof result === "string") return "The connection dropped before the result arrived. Reload to check.";
  }
  return result;
}

type CardProps<P> = {
  action: PendingApproval & { payload: P };
  role: UserCtx["role"];
  onDecided: (outcome: Outcome) => void;
};

/** A pending letter or i-EMS ticket, with its decision controls. */
function ActionCard({ action, role, onDecided }: CardProps<PendingApproval["payload"]>) {
  const { payload } = action;
  return payload.kind === "ticket" ? (
    <TicketCard action={{ ...action, payload }} role={role} onDecided={onDecided} />
  ) : (
    <LetterCard action={{ ...action, payload }} role={role} onDecided={onDecided} />
  );
}

/** Edits as the proposal ↔ the officer's values, the decision in flight and why plg-api refused it. */
function useDecision(action: PendingApproval, kind: Kind, original: Record<string, string>, onDecided: (o: Outcome) => void) {
  const [edits, setEdits] = useState<Record<string, string> | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const changes = edits ? Object.fromEntries(Object.entries(edits).filter(([field, value]) => value !== original[field])) : {};

  async function submit(body: DecisionBody) {
    setBusy(true);
    setRefusal(null);
    const result = await decide(action, body);
    if (typeof result === "string") {
      setBusy(false);
      return setRefusal(result);
    }
    // Stays busy: the card leaves the inbox when it reloads.
    onDecided({ title: action.title, kind, result });
  }

  return { edits, setEdits, rejecting, setRejecting, reason, setReason, busy, refusal, changes, submit };
}

type Decider = ReturnType<typeof useDecision>;

/** Approve, edit (then send the edits) or reject with a reason. */
function Controls({
  d,
  original,
  toSend,
  canSend,
  canApprove,
  blocked,
  labels,
}: {
  d: Decider;
  original: Record<string, string>;
  /** The edits sent when sending the edited version. */
  toSend: Record<string, string>;
  canSend: boolean;
  canApprove: boolean;
  blocked: boolean;
  labels: { approve: string; edit: string; sendEdited: string };
}) {
  const { edits, busy, submit } = d;
  return (
    <div className={styles.actions}>
      {edits ? (
        <>
          <button
            type="button"
            disabled={busy || Object.keys(toSend).length === 0 || blocked}
            onClick={() => submit({ decision: "edit", edits: toSend })}
          >
            {labels.sendEdited}
          </button>
          <button type="button" disabled={busy} onClick={() => d.setEdits(null)}>
            Cancel edits
          </button>
        </>
      ) : d.rejecting ? (
        <>
          <label>
            Reason for rejecting
            <textarea value={d.reason} onChange={(e) => d.setReason(e.target.value)} />
          </label>
          <button
            type="button"
            disabled={busy || !d.reason.trim()}
            onClick={() => submit({ decision: "reject", reason: d.reason.trim() })}
          >
            Reject
          </button>
          <button type="button" disabled={busy} onClick={() => d.setRejecting(false)}>
            Cancel
          </button>
        </>
      ) : (
        <>
          {canSend && canApprove && (
            <button type="button" disabled={busy} onClick={() => submit({ decision: "approve" })}>
              {labels.approve}
            </button>
          )}
          {canSend && (
            <button type="button" disabled={busy} onClick={() => d.setEdits(original)}>
              {labels.edit}
            </button>
          )}
          <button type="button" disabled={busy} onClick={() => d.setRejecting(true)}>
            Reject…
          </button>
        </>
      )}
    </div>
  );
}

function Refusal({ refusal }: { refusal: string | null }) {
  return (
    refusal && (
      <p role="alert" className={styles.alert}>
        {refusal}
      </p>
    )
  );
}

function LetterCard({ action, role, onDecided }: CardProps<LetterPayload>) {
  const { payload } = action;
  const heading = `action-${action.action_id}`;
  const canSend = action.approver_roles.includes(role);
  const original: Record<string, string> = {
    ...Object.fromEntries(payload.unfilled.map((u) => [u.slot, ""])),
    ...payload.slots,
  };
  const d = useDecision(action, "letter", original, onDecided);
  const { edits, changes } = d;
  const stillOpen = edits ? payload.unfilled.map((u) => u.slot).filter((slot) => !edits[slot]?.trim()) : [];

  return (
    <article aria-labelledby={heading} className={styles.card}>
      <h3 id={heading}>{action.title}</h3>
      <p>
        {payload.template_title} ({payload.template_id} v{payload.template_version}) · version {action.version} ·
        To: {payload.recipient}
      </p>
      <p className={styles.muted}>From the conversation: {action.thread_title}</p>
      {payload.unfilled.length > 0 && (
        <div>
          <h4>Still to fill</h4>
          <ul aria-label="Unfilled slots">
            {payload.unfilled.map((u) => (
              <li key={u.slot}>
                <code>{u.slot}</code>: {u.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
      {payload.pii.length > 0 && (
        <div role="alert" className={styles.alert}>
          <h4>Personal data to remove</h4>
          <ul aria-label="Personal data flags">
            {payload.pii.map((p, i) => (
              <li key={i}>
                <code>{p.slot}</code>: {p.message}
              </li>
            ))}
          </ul>
        </div>
      )}
      <table className={styles.slots}>
        <caption>{edits ? "Slot values: your changes are shown against the proposal" : "Slot values"}</caption>
        <thead>
          <tr>
            <th scope="col">Slot</th>
            <th scope="col">{edits ? "Proposed → will send" : "Value"}</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(original).map(([slot, value]) => (
            <tr key={slot}>
              <th scope="row">
                <code>{slot}</code>
              </th>
              <td>
                {edits ? (
                  <>
                    <input
                      aria-label={slot}
                      value={edits[slot]}
                      onChange={(e) => d.setEdits({ ...edits, [slot]: e.target.value })}
                    />
                    <Diff before={value} after={changes[slot]} changed={slot in changes} />
                  </>
                ) : (
                  value || <em>not filled</em>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <LetterFrame title={`Letter to send: ${action.title}`} html={action.preview} />
      <Refusal refusal={d.refusal} />
      {!canSend && <p>Your role can&apos;t send this letter. You can reject it with a reason.</p>}
      {canSend && !edits && payload.unfilled.length > 0 && (
        <p>Fill the open slots (Edit slots) before the letter can be sent.</p>
      )}
      {stillOpen.length > 0 && <p>Fill {stillOpen.join(", ")} before sending.</p>}
      <Controls
        d={d}
        original={original}
        toSend={changes}
        canSend={canSend}
        canApprove={payload.unfilled.length === 0}
        blocked={stillOpen.length > 0}
        labels={{ approve: "Approve and send", edit: "Edit slots", sendEdited: "Send edited letter" }}
      />
    </article>
  );
}

function Diff({ before, after, changed }: { before: string; after: string | undefined; changed: boolean }) {
  return (
    changed && (
      <p>
        {before && <del>{before}</del>} <ins>{after}</ins>
      </p>
    )
  );
}

/** The i-EMS defect categories a ticket can be raised under (team, vendor and default severity follow from it). */
const IEMS_CATEGORIES: Record<string, string> = {
  STR: "Structural",
  SEP: "Water Seepage / Leak",
  PLB: "Plumbing & Sanitary",
  ELE: "Electrical",
  FIR: "Fire Safety",
  PST: "Pest",
};
const SEVERITIES = ["Low", "Medium", "High", "Critical"] as const;
const SLA_DAYS: Record<(typeof SEVERITIES)[number], number> = { Critical: 1, High: 3, Medium: 7, Low: 14 };
const TICKET_FIELDS: { field: keyof TicketPayload & string; label: string; required: boolean }[] = [
  { field: "category_code", label: "Category", required: true },
  { field: "severity", label: "Priority", required: true },
  { field: "unit_id", label: "Unit", required: false },
  { field: "description", label: "Description", required: true },
  { field: "feedback_id", label: "Feedback case", required: true },
];

function TicketField({
  field,
  label,
  value,
  onChange,
}: {
  field: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  if (field === "category_code")
    return (
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        {Object.entries(IEMS_CATEGORIES).map(([code, name]) => (
          <option key={code} value={code}>
            {name} ({code})
          </option>
        ))}
      </select>
    );
  if (field === "severity")
    return (
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}>
        {SEVERITIES.map((s) => (
          <option key={s} value={s}>
            {s} (SLA {SLA_DAYS[s]} day{SLA_DAYS[s] === 1 ? "" : "s"})
          </option>
        ))}
      </select>
    );
  if (field === "description")
    return <textarea aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} />;
  return <input aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} />;
}

function TicketCard({ action, role, onDecided }: CardProps<TicketPayload>) {
  const { payload } = action;
  const heading = `action-${action.action_id}`;
  const canSend = action.approver_roles.includes(role);
  const original: Record<string, string> = Object.fromEntries(
    TICKET_FIELDS.map(({ field }) => [field, String(payload[field] ?? "")]),
  );
  const d = useDecision(action, "ticket", original, onDecided);
  const { edits, changes } = d;
  const blank = edits
    ? TICKET_FIELDS.filter(({ field, required }) => required && !edits[field]?.trim()).map(({ label }) => label)
    : [];
  // plg-api gives a new category its default priority unless one is sent: send the priority the officer sees.
  const toSend = edits && "category_code" in changes ? { ...changes, severity: edits.severity } : changes;
  const shown = (field: string, value: string) =>
    field === "category_code" && IEMS_CATEGORIES[value] ? `${IEMS_CATEGORIES[value]} (${value})` : value;

  return (
    <article aria-labelledby={heading} className={styles.card}>
      <h3 id={heading}>{action.title}</h3>
      <p>
        i-EMS ticket · version {action.version} · Feedback case {payload.feedback_id}
      </p>
      <p className={styles.muted}>From the conversation: {action.thread_title}</p>
      <h4>Classification</h4>
      <ClassificationDetails found={{ ...payload, is_defect: true }} />
      <table className={styles.slots}>
        <caption>{edits ? "Ticket fields: your changes are shown against the proposal" : "Ticket fields"}</caption>
        <thead>
          <tr>
            <th scope="col">Field</th>
            <th scope="col">{edits ? "Proposed → will raise" : "Value"}</th>
          </tr>
        </thead>
        <tbody>
          {TICKET_FIELDS.map(({ field, label }) => (
            <tr key={field}>
              <th scope="row">{label}</th>
              <td>
                {edits ? (
                  <>
                    <TicketField
                      field={field}
                      label={label}
                      value={edits[field]}
                      onChange={(value) => d.setEdits({ ...edits, [field]: value })}
                    />
                    <Diff
                      before={shown(field, original[field])}
                      after={changes[field] === undefined ? undefined : shown(field, changes[field])}
                      changed={field in changes}
                    />
                  </>
                ) : (
                  shown(field, original[field]) || <em>not given</em>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {edits && (
        <p className={styles.muted}>
          A new category routes the ticket to that category&apos;s team and vendor. The SLA follows the priority.
        </p>
      )}
      <LetterFrame title={`Ticket to raise: ${action.title}`} html={action.preview} />
      <Refusal refusal={d.refusal} />
      {!canSend && <p>Your role can&apos;t raise this ticket. You can reject it with a reason.</p>}
      {blank.length > 0 && <p>Fill {blank.join(", ")} before raising.</p>}
      <Controls
        d={d}
        original={original}
        toSend={toSend}
        canSend={canSend}
        canApprove
        blocked={blank.length > 0}
        labels={{ approve: "Approve and raise", edit: "Edit ticket", sendEdited: "Raise edited ticket" }}
      />
    </article>
  );
}

const DECIDED: Record<Decision, string> = { approve: "Approved and sent", edit: "Sent with edits", reject: "Rejected" };
const DECIDED_TICKET: Record<Decision, string> = { approve: "Approved and raised", edit: "Raised with edits", reject: "Rejected" };

/** Every decision the officer made: who, when, why, what changed, what went to the outbox and the run's trace. */
function AuditTrail({ entries }: { entries: AuditRecord[] }) {
  return (
    <ul aria-label="Audit trail" className={styles.list}>
      {entries.map((e) => {
        const heading = `audit-${e.action_id}`;
        return (
          <li key={e.action_id}>
            <article aria-labelledby={heading} className={styles.card}>
              <h3 id={heading}>{e.title || e.action_id}</h3>
              <p>
                {(e.action_type === "raise_ticket" ? DECIDED_TICKET : DECIDED)[e.decision]} by {e.approver} ({roleLabel(e.approver_role)}) on {when(e.at)}, deciding on
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
              ) : (
                <p>Nothing was {e.action_type === "raise_ticket" ? "raised" : "sent"}.</p>
              )}
              <p className={styles.muted}>Trace {e.run_id}</p>
              {e.sent && (
                <details>
                  <summary>Letter as sent</summary>
                  <LetterFrame title={`Letter sent: ${e.title}`} html={e.sent.html} />
                </details>
              )}
            </article>
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
      <dl aria-label="Raised ticket" className={styles.ticket}>
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
