# Issue #83: Inline approval card in chat

Parent: #74 · Blocked by #77 (chat layout) and #78 (card style), both done.

## What was built

Before this change, an answer that proposed an action (a letter to send, an i-EMS ticket to raise, a glossary change) said "It waits for your approval" and nothing else. The officer had to open the Approvals inbox to act on it.

Each pending action now appears in the answer as an **Awaiting approval** card. It holds the Approvals inbox's own card: the same preview, the same rules and the same edit forms.

- **Live and after reload:**
  - In a live run, the cards come from the `proposed_action` events and appear once the run is `done` (resuming before then would get a 409). A revised version replaces the earlier one.
  - In a reopened conversation, the cards come from `ThreadView.pending` and sit under the last answer.
- **Deciding:** approve, edit then send/raise/adopt, or reject/withdraw with a reason. The card calls `POST /api/threads/{id}/resume` and reads the resumed stream for its `action_result`.
  - The card then shows the outcome: the outbox ID, ticket ID or glossary term, and the version.
  - It also shows a badge: Sent, Raised, Adopted or Rejected.
  - `shell.refresh()` updates the sidebar's pending count. Because the action is decided, it is also gone from the Approvals inbox.
- **Refusals:** plg-api's 403, 409 and 422 details appear as an alert in the card, and the controls stay. Open slots are blocked before sending, as in the inbox.
- **Roles:**
  - Someone who can't decide gets no approve or edit controls. They see "Sent to approvers: …", listing the approver roles or, for a glossary change, the term owner.
  - The proposer of a glossary change can only withdraw it.
  - `canDecide` is the one rule, shared by both screens.

## How it fits

This builds on the approval flow (#18), and the inbox screen does not change. Officers can now decide where the action was proposed, so the loop is propose, decide, see the result, all in one turn. The inbox remains the place to decide across conversations (curators, term owners) and to read the audit trail. Both screens use the same component and send the same decisions to plg-api, so they cannot drift apart.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `web/src/app/approvals/ActionCard.tsx` | New (code moved from ApprovalsScreen) | Letter, ticket and glossary cards with their decision controls. `embedded` mode drops the card's own frame and heading. Also holds `canDecide`, `describe`, `decidedLabel` and `decide` (resume plus reading the stream). |
| `web/src/app/approvals/ApprovalsScreen.tsx` | Modified | The inbox. It now imports the cards from `ActionCard.tsx`. |
| `web/src/app/approvals/approvals.module.css` | Modified | Adds the `.embedded` spacing. |
| `web/src/app/ApprovalCard.tsx` | New | The chat card: Card plus an "Awaiting approval" badge, "Sent to approvers" for non-deciders, the embedded ActionCard, then the outcome. |
| `web/src/app/AskScreen.tsx` | Modified | Collects `proposed_action` events (`Answer.actions`) and `ThreadView.pending`, and renders `PendingActions` under the answer. `user` now includes `staff_id`. |
| `web/src/app/ApprovalCard.test.tsx` | New | Vitest tests driven by the recorded approvals fixtures: live card, reload, edit, reject, ticket, 409/403 refusals, analyst, glossary proposer, sidebar count. |
| `web/e2e/journeys.spec.ts` | Modified | New journey: approve one letter and reject another from the chat, then check the inbox no longer lists them and the audit entry is there. |
| `web/e2e/accessibility.spec.ts` | Modified | axe runs on the chat with an approval card (light and dark themes). |

## Workflow

```
plg-api run ──proposed_action/interrupt──▶ AskScreen (Answer.actions)      GET /api/threads/{id} ──pending──▶ AskScreen (pending)
                                                    └──────────────┬───────────────────────────────────────────┘
                                                                   ▼
                                                     PendingActions → ApprovalCard (Card + badge)
                                                                   │  embedded
                                                                   ▼
                                                     approvals/ActionCard (Letter/Ticket/GlossaryCard, canDecide)
                                                                   │ decide()
                                                                   ▼
                                    BFF POST /api/threads/{id}/resume ──▶ plg-api resume → approval → execute_action
                                                                   │ SSE action_result (outbox_id | ticket_id | term_id)
                                                                   ▼
                                     ApprovalCard outcome (status + badge) ──▶ shell.refresh() → sidebar count
                                                                              (Approvals inbox reads /api/approvals afresh)
```

## Known limits / next steps

- A decided outcome lives only in the card's state. After a reload or a follow-up question it no longer shows in the chat; the inbox's Decided list and `/api/audit` keep it.
- Pending actions sit on the newest answer: every interrupted run re-sends all of the thread's pending actions, and nothing maps an action to the answer that proposed it. Mapping them would need plg-api to record the proposing `run_id` on the ProposedAction.
- A resume reads only its own action's result. If that run revised a sibling action, the sibling's card keeps its old version until the next run, and deciding it returns a 409, which is shown in the card.
