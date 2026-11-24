"use client";

import { useState } from "react";
import { roleLabel, type UserCtx } from "@/lib/events";
import { ActionCard, canDecide, decidedLabel, describe, type Approvable, type Outcome } from "./approvals/ActionCard";
import { Badge, Card } from "./Card";

/** Who decides the action, in words: a glossary change's term owner, else the roles that may approve it. */
function approversOf(action: Approvable): string {
  if (action.payload.kind === "glossary") return `${action.payload.owner_name} (term owner)`;
  const roles = action.approver_roles.map(roleLabel).join(", ");
  return roles.charAt(0).toUpperCase() + roles.slice(1);
}

/**
 * An action the answer proposed, waiting in the chat: the Approvals inbox's card (same preview, rules and edit
 * forms) inside an "Awaiting approval" card. A persona who can't approve sees who it was sent to; once decided,
 * the card shows what happened (outbox item, ticket or glossary term, and the version).
 */
export function ApprovalCard({
  action,
  user,
  onDecided,
}: {
  action: Approvable;
  user: Pick<UserCtx, "role" | "staff_id">;
  /** After a decision: the sidebar's pending count and the inbox change. */
  onDecided: () => void;
}) {
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  if (outcome) {
    const rejected = outcome.result.decision === "reject";
    return (
      <Card heading={action.title} badges={<Badge tone={rejected ? "neutral" : "success"}>{decidedLabel(outcome)}</Badge>}>
        <p role="status">{describe(outcome)}</p>
      </Card>
    );
  }

  return (
    <Card heading={action.title} badges={<Badge tone="warning">Awaiting approval</Badge>}>
      {!canDecide(action, user.role, user.staff_id) && <p>Sent to approvers: {approversOf(action)}.</p>}
      <ActionCard
        action={action}
        role={user.role}
        staffId={user.staff_id}
        embedded
        onDecided={(decided) => {
          setOutcome(decided);
          onDecided();
        }}
      />
    </Card>
  );
}
