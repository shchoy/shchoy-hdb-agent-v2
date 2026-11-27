"use client";

import { useState, type ReactNode } from "react";
import type { components } from "@/lib/api/schema";
import { parseRunEvents, type RunEvent, type UserCtx } from "@/lib/events";
import { ClassificationDetails } from "../ClassificationCard";
import { ago, day, period, when } from "../dates";
import { LetterFrame } from "../LetterFrame";
import styles from "./approvals.module.css";

type ActionType = components["schemas"]["ProposedAction"]["action_type"];

/** A pending action and the conversation it waits in (the chat leaves the conversation's title out: it is that one). */
export type Approvable = components["schemas"]["ProposedAction"] & { thread_id: string; thread_title?: string };
type Decision = "approve" | "edit" | "reject";
export type ActionResult = Extract<RunEvent, { type: "action_result" }>;
/** What a decision did, for the officer to see straight away. */
export type Outcome = { title: string; kind: Kind; result: ActionResult };
type Kind = Approvable["payload"]["kind"];
type LetterPayload = components["schemas"]["LetterPayload"];
type TicketPayload = components["schemas"]["TicketPayload"];
type GlossaryPayload = components["schemas"]["GlossaryPayload"];

/** One line saying what a decision did: sent / raised / adopted as what, or that nothing was done. */
export function describe({ title, kind, result }: Outcome): string {
  const ticket = kind === "ticket";
  if (result.decision === "reject") return `${title}: rejected; nothing was ${NOTHING[kind]}.`;
  const edited = result.decision === "edit";
  if (kind === "glossary")
    return `${title}: ${edited ? "adopted with your edits" : "adopted"} as ${result.term_id} (version ${result.version}).`;
  if (ticket) return `${title}: ${edited ? "raised with your edits" : "raised"} as ${result.ticket_id} (version ${result.version}).`;
  return `${title}: ${edited ? "sent with your edits" : "sent"} as ${result.outbox_id} (version ${result.version}).`;
}

/** The outcome in a word, for a badge. */
export function decidedLabel({ kind, result }: Outcome): string {
  if (result.decision === "reject") return "Rejected";
  return kind === "letter" ? "Sent" : kind === "ticket" ? "Raised" : kind === "glossary" ? "Adopted" : "Approved";
}

/**
 * Whether the persona may approve or edit the action (anyone may reject or withdraw what they proposed): their role
 * is an approver role and, when the action names its approvers (a glossary change's term owner), they are one.
 */
export function canDecide(action: Approvable, role: UserCtx["role"], staffId: string): boolean {
  // `approvers` defaults to none: recordings older than glossary changes leave it out.
  const approvers = action.approvers ?? [];
  return action.approver_roles.includes(role) && (approvers.length === 0 || approvers.includes(staffId));
}

/** What kind of action it is, in words (a badge in the inbox and the audit trail). */
export const KIND_LABEL: Record<Kind, string> = {
  letter: "Letter",
  ticket: "i-EMS ticket",
  glossary: "Glossary change",
  team_fact: "Team fact",
  example: "Corrected answer",
  sql_example: "SQL example",
};

/** What a decision did, by action type (the audit trail's badge). */
export const DECIDED_LABEL: Record<ActionType, Record<"approve" | "edit" | "reject", string>> = {
  send_letter: { approve: "Approved and sent", edit: "Sent with edits", reject: "Rejected" },
  raise_ticket: { approve: "Approved and raised", edit: "Raised with edits", reject: "Rejected" },
  approve_glossary_term: { approve: "Approved and adopted", edit: "Adopted with edits", reject: "Rejected" },
  approve_team_fact: { approve: "Approved", edit: "Approved with edits", reject: "Rejected" },
  approve_example: { approve: "Approved", edit: "Approved with edits", reject: "Rejected" },
  approve_sql_example: { approve: "Approved", edit: "Approved with edits", reject: "Rejected" },
};
/** An action type's label. */
export const ACTION_KIND: Record<ActionType, string> = {
  send_letter: KIND_LABEL.letter,
  raise_ticket: KIND_LABEL.ticket,
  approve_glossary_term: KIND_LABEL.glossary,
  approve_team_fact: KIND_LABEL.team_fact,
  approve_example: KIND_LABEL.example,
  approve_sql_example: KIND_LABEL.sql_example,
};

/** Who proposed an action and how long ago (the exact time on hover). */
export function Proposed({ by, at }: { by: string; at: string }) {
  return (
    <span>
      Proposed by {by}{" "}
      <time dateTime={at} title={when(at)}>
        {ago(at)}
      </time>
    </span>
  );
}

const NOTHING: Record<Kind, string> = {
  letter: "sent",
  ticket: "raised",
  glossary: "changed",
  team_fact: "taught",
  example: "taught",
  sql_example: "taught",
};

type DecisionBody = { decision: Decision; edits?: Record<string, string>; reason?: string };

/** Sends the decision and reads the resumed run until the action's result (or the reason it was refused). */
async function decide(action: Approvable, body: DecisionBody): Promise<ActionResult | string> {
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
      else if (event.type === "cancelled") result = "It was stopped before the result arrived. Reload to check.";
    }
  } catch {
    if (typeof result === "string") return "The connection dropped before the result arrived. Reload to check.";
  }
  return result;
}

type CardProps<P> = {
  action: Approvable & { payload: P };
  role: UserCtx["role"];
  staffId: string;
  onDecided: (outcome: Outcome) => void;
};

/** The action's detail: it sits inside a card that names it (the inbox item or the chat's "Awaiting approval" card). */
function Detail({ children }: { children: ReactNode }) {
  return <div className={styles.detail}>{children}</div>;
}

/** A pending letter, i-EMS ticket or glossary change, with its decision controls. */
export function ActionCard({ action, ...props }: CardProps<Approvable["payload"]>) {
  const { payload } = action;
  return payload.kind === "ticket" ? (
    <TicketCard action={{ ...action, payload }} {...props} />
  ) : payload.kind === "glossary" ? (
    <GlossaryCard action={{ ...action, payload }} {...props} />
  ) : payload.kind === "letter" ? (
    <LetterCard action={{ ...action, payload }} {...props} />
  ) : (
    // What answer feedback proposes is decided in the curator queue (Memory screen), never at a thread's interrupt.
    <p>{action.title}: decide it in the curator queue on the Memory screen.</p>
  );
}

/** Edits as the proposal ↔ the officer's values, the decision in flight and why plg-api refused it. */
function useDecision(action: Approvable, kind: Kind, original: Record<string, string>, onDecided: (o: Outcome) => void) {
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

/** Approve, edit (then send the edits) or reject (or withdraw) with a reason. */
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
  labels: { approve: string; edit: string; sendEdited: string; reject?: "Reject" | "Withdraw" };
}) {
  const { edits, busy, submit } = d;
  const reject = labels.reject ?? "Reject";
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
            {reject === "Reject" ? "Reason for rejecting" : "Reason for withdrawing"}
            <textarea rows={2} value={d.reason} onChange={(e) => d.setReason(e.target.value)} />
          </label>
          <button
            type="button"
            data-variant="danger-solid"
            disabled={busy || !d.reason.trim()}
            onClick={() => submit({ decision: "reject", reason: d.reason.trim() })}
          >
            {reject}
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
          <button type="button" data-variant="danger" disabled={busy} onClick={() => d.setRejecting(true)}>
            {reject}…
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

function LetterCard({ action, role, staffId, onDecided }: CardProps<LetterPayload>) {
  const { payload } = action;
  const canSend = canDecide(action, role, staffId);
  const original: Record<string, string> = {
    ...Object.fromEntries(payload.unfilled.map((u) => [u.slot, ""])),
    ...payload.slots,
  };
  const d = useDecision(action, "letter", original, onDecided);
  const { edits, changes } = d;
  const stillOpen = edits ? payload.unfilled.map((u) => u.slot).filter((slot) => !edits[slot]?.trim()) : [];

  return (
    <Detail>
      <p>
        {payload.template_title} ({payload.template_id} v{payload.template_version}) · version {action.version} ·
        To: {payload.recipient}
      </p>
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
    </Detail>
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

function TicketCard({ action, role, staffId, onDecided }: CardProps<TicketPayload>) {
  const { payload } = action;
  const canSend = canDecide(action, role, staffId);
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
    <Detail>
      <p>
        i-EMS ticket · version {action.version} · Feedback case {payload.feedback_id}
      </p>
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
    </Detail>
  );
}

const GLOSSARY_FIELDS = [
  { field: "definition", label: "Definition" },
  { field: "value", label: "Value" },
  { field: "effective_from", label: "Effective from" },
] as const;

/** A change to a business definition: the version in force against the proposed one. Only the term owner approves. */
function GlossaryCard({ action, role, staffId, onDecided }: CardProps<GlossaryPayload>) {
  const { payload } = action;
  const { term, previous } = payload;
  // Only a named approver (the term owner): a change always names one.
  const canApprove = (action.approvers ?? []).includes(staffId) && canDecide(action, role, staffId);
  const original: Record<string, string> = Object.fromEntries(
    GLOSSARY_FIELDS.map(({ field }) => [field, term[field] ?? ""]),
  );
  const d = useDecision(action, "glossary", original, onDecided);
  const { edits, changes } = d;
  const now = (field: (typeof GLOSSARY_FIELDS)[number]["field"]) =>
    field === "effective_from"
      ? period(previous.effective_from, previous.effective_to, "since before records began")
      : (previous[field] ?? "");
  const proposed = (field: string, value: string) => (field === "effective_from" && value ? day(value) : value);

  return (
    <Detail>
      <p>
        Glossary change · version {action.version} · {term.pref_label} ({term.concept})
      </p>
      <table className={styles.slots}>
        <caption>{edits ? "Definition: your changes are shown against the proposal" : "Definition"}</caption>
        <thead>
          <tr>
            <th scope="col">Field</th>
            <th scope="col">Now ({previous.id})</th>
            <th scope="col">{edits ? `Proposed → will adopt (${term.id})` : `Proposed (${term.id})`}</th>
          </tr>
        </thead>
        <tbody>
          {GLOSSARY_FIELDS.map(({ field, label }) => {
            const differs = now(field) !== proposed(field, original[field]);
            return (
              <tr key={field}>
                <th scope="row">{label}</th>
                <td>{differs && field !== "effective_from" ? <del>{now(field)}</del> : now(field) || <em>none</em>}</td>
                <td>
                  {edits ? (
                    <>
                      {field === "definition" ? (
                        <textarea
                          aria-label={label}
                          value={edits[field]}
                          onChange={(e) => d.setEdits({ ...edits, [field]: e.target.value })}
                        />
                      ) : (
                        <input
                          aria-label={label}
                          type={field === "effective_from" ? "date" : "text"}
                          value={edits[field]}
                          onChange={(e) => d.setEdits({ ...edits, [field]: e.target.value })}
                        />
                      )}
                      <Diff
                        before={proposed(field, original[field])}
                        after={changes[field] === undefined ? undefined : proposed(field, changes[field])}
                        changed={field in changes}
                      />
                    </>
                  ) : differs && field !== "effective_from" ? (
                    <ins>{original[field]}</ins>
                  ) : (
                    proposed(field, original[field]) || <em>none</em>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p>Reason: {payload.reason}</p>
      <p>
        On approval {previous.id} is superseded from the new version&apos;s effective date and kept.
      </p>
      <h4>SQL binding{payload.sql === null && payload.binding !== null ? ` (unchanged: ${previous.id}'s)` : ""}</h4>
      {payload.binding === null ? <p>No SQL binding.</p> : <pre aria-label="SQL binding">{payload.binding}</pre>}
      <p>
        Term owner: {payload.owner_name} ({term.owned_by})
      </p>
      <Refusal refusal={d.refusal} />
      {!canApprove && (
        <p>Waiting for {payload.owner_name} to approve. You can withdraw it with a reason.</p>
      )}
      {edits && !edits.definition?.trim() && <p>Fill Definition before adopting.</p>}
      <Controls
        d={d}
        original={original}
        toSend={changes}
        canSend={canApprove}
        canApprove
        blocked={!edits?.definition?.trim()}
        labels={{
          approve: "Approve change",
          edit: "Edit change",
          sendEdited: "Adopt edited change",
          reject: canApprove ? "Reject" : "Withdraw",
        }}
      />
    </Detail>
  );
}
