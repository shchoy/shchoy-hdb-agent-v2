"use client";

import { useEffect, useState } from "react";
import type { components } from "@/lib/api/schema";
import { parseRunEvents, roleLabel, type RunEvent, type UserCtx } from "@/lib/events";
import { when } from "../dates";
import { LetterFrame } from "../LetterFrame";
import styles from "./approvals.module.css";

type PendingApproval = components["schemas"]["PendingApproval"];

type AuditRecord = components["schemas"]["AuditRecord"];
type Decision = "approve" | "edit" | "reject";
type ActionResult = Extract<RunEvent, { type: "action_result" }>;
/** What a decision did, for the officer to see straight away. */
type Outcome = { title: string; result: ActionResult };

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
          {outcomes.map(({ title, result }) => (
            <p key={`${result.action_id}-v${result.version}`}>
              {title}: {describe(result)}
            </p>
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

function describe(result: ActionResult): string {
  if (result.decision === "reject") return "rejected; nothing was sent.";
  const how = result.decision === "edit" ? "sent with your edits" : "sent";
  return `${how} as ${result.outbox_id} (version ${result.version}).`;
}

/** Sends the decision and reads the resumed run until the action's result (or the reason it was refused). */
async function decide(action: PendingApproval, body: { decision: Decision; edits?: Record<string, string>; reason?: string }): Promise<ActionResult | string> {
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

function ActionCard({
  action,
  role,
  onDecided,
}: {
  action: PendingApproval;
  role: UserCtx["role"];
  onDecided: (outcome: Outcome) => void;
}) {
  const { payload } = action;
  const heading = `action-${action.action_id}`;
  const canSend = action.approver_roles.includes(role);
  const original: Record<string, string> = {
    ...Object.fromEntries(payload.unfilled.map((u) => [u.slot, ""])),
    ...payload.slots,
  };
  const [edits, setEdits] = useState<Record<string, string> | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const stillOpen = edits ? payload.unfilled.map((u) => u.slot).filter((slot) => !edits[slot]?.trim()) : [];
  const changes = edits ? Object.fromEntries(Object.entries(edits).filter(([slot, value]) => value !== original[slot])) : {};

  async function submit(body: Parameters<typeof decide>[1]) {
    setBusy(true);
    setRefusal(null);
    const result = await decide(action, body);
    if (typeof result === "string") {
      setBusy(false);
      return setRefusal(result);
    }
    // Stays busy: the card leaves the inbox when it reloads.
    onDecided({ title: action.title, result });
  }

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
                      onChange={(e) => setEdits({ ...edits, [slot]: e.target.value })}
                    />
                    {slot in changes && (
                      <p>
                        {value && <del>{value}</del>} <ins>{changes[slot]}</ins>
                      </p>
                    )}
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
      {refusal && (
        <p role="alert" className={styles.alert}>
          {refusal}
        </p>
      )}
      {!canSend && <p>Your role can&apos;t send this letter. You can reject it with a reason.</p>}
      {canSend && !edits && payload.unfilled.length > 0 && (
        <p>Fill the open slots (Edit slots) before the letter can be sent.</p>
      )}
      {stillOpen.length > 0 && <p>Fill {stillOpen.join(", ")} before sending.</p>}
      <div className={styles.actions}>
        {edits ? (
          <>
            <button
              type="button"
              disabled={busy || Object.keys(changes).length === 0 || stillOpen.length > 0}
              onClick={() => submit({ decision: "edit", edits: changes })}
            >
              Send edited letter
            </button>
            <button type="button" disabled={busy} onClick={() => setEdits(null)}>
              Cancel edits
            </button>
          </>
        ) : rejecting ? (
          <>
            <label>
              Reason for rejecting
              <textarea value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            <button
              type="button"
              disabled={busy || !reason.trim()}
              onClick={() => submit({ decision: "reject", reason: reason.trim() })}
            >
              Reject
            </button>
            <button type="button" disabled={busy} onClick={() => setRejecting(false)}>
              Cancel
            </button>
          </>
        ) : (
          <>
            {canSend && payload.unfilled.length === 0 && (
              <button type="button" disabled={busy} onClick={() => submit({ decision: "approve" })}>
                Approve and send
              </button>
            )}
            {canSend && (
              <button type="button" disabled={busy} onClick={() => setEdits(original)}>
                Edit slots
              </button>
            )}
            <button type="button" disabled={busy} onClick={() => setRejecting(true)}>
              Reject…
            </button>
          </>
        )}
      </div>
    </article>
  );
}

const DECIDED: Record<Decision, string> = { approve: "Approved and sent", edit: "Sent with edits", reject: "Rejected" };

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
                {DECIDED[e.decision]} by {e.approver} ({roleLabel(e.approver_role)}) on {when(e.at)}, deciding on
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
              {e.sent ? (
                <p>
                  Outbox item {e.sent.item_id} (version {e.sent.version}) to {e.sent.recipient}, sent {when(e.sent.sent_at)}
                </p>
              ) : (
                <p>Nothing was sent.</p>
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
