"use client";

import { useEffect, useState } from "react";
import type { components } from "@/lib/api/schema";
import { Proposed } from "../approvals/ActionCard";
import { Card, cardListClass } from "../Card";
import styles from "./memory.module.css";

type ProposedAction = components["schemas"]["ProposedAction"];
type TeamFact = components["schemas"]["TeamFactPayload"];
type Example = components["schemas"]["ExamplePayload"];
type SqlExample = components["schemas"]["SqlExamplePayload"];
type Curated = ProposedAction & { payload: TeamFact | Example | SqlExample };
type Kind = Curated["payload"]["kind"];
type Decision = "approve" | "edit" | "reject";

const LABEL: Record<Kind, string> = { team_fact: "Team fact", example: "Corrected answer", sql_example: "SQL example" };

/** What a curator may change before approving, per kind (plg-api's EDITABLE), with its field label. */
const EDITABLE: Record<Kind, [field: string, label: string][]> = {
  team_fact: [["fact", "Fact"]],
  example: [
    ["question", "Question"],
    ["answer", "Corrected answer"],
  ],
  sql_example: [
    ["question", "Question"],
    ["sql", "SQL"],
  ],
};

function isCurated(action: ProposedAction): action is Curated {
  const { kind } = action.payload;
  return kind === "team_fact" || kind === "example" || kind === "sql_example";
}

/**
 * What answer feedback proposes to teach the team (team facts, corrected answers, question → SQL examples), waiting
 * for a curator. Only the named approvers may approve or edit; the officer who proposed one may only withdraw it.
 */
export function CuratorQueue({ staffId }: { staffId: string }) {
  const [queue, setQueue] = useState<Curated[] | null>(null);
  const [results, setResults] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    fetch("/api/curation")
      .then(async (response) => {
        if (!current) return;
        if (!response.ok) return setError("Could not load the curator queue.");
        const actions = (await response.json()) as ProposedAction[];
        if (current) setQueue(actions.filter(isCurated));
      })
      .catch(() => current && setError("Could not load the curator queue."));
    return () => {
      current = false;
    };
  }, []);

  function decided(action: Curated, result: string) {
    setQueue((q) => q?.filter((a) => a.action_id !== action.action_id) ?? null);
    setResults((r) => [result, ...r]);
  }

  return (
    <section aria-labelledby="curator-heading">
      <h2 id="curator-heading">Curator queue</h2>
      {results.length > 0 && (
        <div role="status" aria-label="Results">
          {results.map((r, i) => (
            <p key={i}>{r}</p>
          ))}
        </div>
      )}
      {error ? (
        <p role="alert">{error}</p>
      ) : !queue ? (
        <p>Loading…</p>
      ) : queue.length === 0 ? (
        <p>Nothing from answer feedback is waiting for review.</p>
      ) : (
        <ul aria-label="Curator queue" className={cardListClass}>
          {queue.map((action) => (
            <li key={`${action.action_id}-v${action.version}`}>
              <ProposalCard action={action} staffId={staffId} onDecided={decided} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ProposalCard({
  action,
  staffId,
  onDecided,
}: {
  action: Curated;
  staffId: string;
  onDecided: (action: Curated, result: string) => void;
}) {
  const { payload } = action;
  const canApprove = action.approvers.includes(staffId);
  const [edits, setEdits] = useState<Record<string, string> | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const original = payload as unknown as Record<string, string>;

  async function decide(decision: Decision, extra: { edits?: Record<string, string>; reason?: string } = {}) {
    setBusy(true);
    setRefusal(null);
    try {
      const response = await fetch("/api/curation/decide", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ action_id: action.action_id, version: action.version, decision, ...extra }),
      });
      if (!response.ok) {
        const detail = ((await response.json().catch(() => null)) as { detail?: unknown } | null)?.detail;
        setRefusal(typeof detail === "string" ? detail : "That decision did not go through.");
        return;
      }
      const verb =
        decision === "reject" ? (canApprove ? "rejected" : "withdrawn") : decision === "edit" ? "approved with your edits" : "approved";
      onDecided(action, `${action.title}: ${verb}.`);
    } catch {
      setRefusal("Could not reach the server. Try again.");
    } finally {
      setBusy(false);
    }
  }

  function approveEdited() {
    if (!edits) return;
    const changed = Object.fromEntries(Object.entries(edits).filter(([field, value]) => value !== original[field]));
    void (Object.keys(changed).length > 0 ? decide("edit", { edits: changed }) : decide("approve"));
  }

  const rejectLabel = canApprove ? "Reject" : "Withdraw";
  return (
    <Card as="article" heading={LABEL[payload.kind]}>
      {edits ? (
        <div className={styles.form}>
          {EDITABLE[payload.kind].map(([field, label]) => (
            <label key={field}>
              {label}
              <textarea
                rows={field === "sql" ? 6 : 3}
                value={edits[field] ?? ""}
                onChange={(e) => setEdits({ ...edits, [field]: e.target.value })}
              />
            </label>
          ))}
        </div>
      ) : (
        <Proposal payload={payload} />
      )}
      <p className={styles.meta}>
        <Proposed by={action.proposed_by} at={action.proposed_at} />
      </p>
      {refusal && (
        <p role="alert" className={styles.alert}>
          {refusal}
        </p>
      )}
      {rejecting ? (
        <div className={styles.form}>
          <label>
            Reason
            <textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <div className={styles.actions}>
            <button
              type="button"
              data-variant="danger-solid"
              disabled={busy || !reason.trim()}
              onClick={() => void decide("reject", { reason: reason.trim() })}
            >
              Confirm {rejectLabel.toLowerCase()}
            </button>
            <button type="button" disabled={busy} onClick={() => setRejecting(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className={styles.actions}>
          {edits ? (
            <>
              <button
                type="button"
                disabled={busy || Object.values(edits).some((v) => !v.trim())}
                onClick={approveEdited}
              >
                Approve edited
              </button>
              <button type="button" disabled={busy} onClick={() => setEdits(null)}>
                Cancel
              </button>
            </>
          ) : (
            <>
              {canApprove && (
                <>
                  <button type="button" disabled={busy} onClick={() => void decide("approve")}>
                    Approve
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => setEdits(Object.fromEntries(EDITABLE[payload.kind].map(([f]) => [f, original[f] ?? ""])))}
                  >
                    Edit
                  </button>
                </>
              )}
              <button type="button" data-variant="danger" disabled={busy} onClick={() => setRejecting(true)}>
                {rejectLabel}
              </button>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

/** The proposal as plain text: never rendered as HTML. */
function Proposal({ payload }: { payload: Curated["payload"] }) {
  return (
    <div className={styles.proposal}>
      <p>Question: {payload.question}</p>
      {payload.kind === "team_fact" && <p>Proposed fact: {payload.fact}</p>}
      {payload.kind === "example" && (
        <>
          <p>Corrected answer: {payload.answer}</p>
          <p>Answer given: {payload.original}</p>
        </>
      )}
      {payload.kind === "sql_example" && <pre>{payload.sql}</pre>}
    </div>
  );
}
