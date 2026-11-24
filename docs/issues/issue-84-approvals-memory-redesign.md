# Issue #84: Redesign Approvals and Memory screens

Parent: #74 (UI redesign). Built on #75 (tokens, font, app shell) and #78 (unified card style).

## What was built

- **Approvals inbox as a scannable list.** Each pending action (letter, i-EMS ticket, glossary change) is one card:
  - a type badge (Letter, i-EMS ticket, Glossary change)
  - the title, which is a disclosure button (`aria-expanded`)
  - the conversation it came from
  - who proposed it, and how long ago (`<time>`, with the exact time on hover)

  Opening an item shows its detail view: preview, slot or field table with the `<del>`/`<ins>` diff of edits, and decision controls. The detail stays mounted while the item is closed, so half-typed edits, a reject reason or a refusal survive closing it.
- **A readable audit trail.** Each decision is a card with a type badge and a decision badge (green for done, grey for rejected), then who, when, reason, edits and outcome. A raised ticket's fields use the card's field layout.
- **Memory screen.** Each memory is a card headed by its kind (Profile, Preference, Past work), with:
  - its provenance and expiry date (SGT)
  - for a note flagged by policy, a **Not in use** warning badge and an amber note
  - Edit, which uses a textarea
  - Forget, in the danger style
- **Curator queue.** It uses the same cards, the same "Proposed by … ago" line and the same danger style. Proposals are short, so they show expanded rather than as disclosures.
- **Danger style for destructive actions.** In `globals.css`:
  - `data-variant="danger"` (red outline) is for buttons that open or do Reject, Withdraw or Forget.
  - `data-variant="danger-solid"` (filled red) confirms.
- **Mobile.** Approval tables use a fixed layout with full-width inputs and wrap long values. Controls and reason fields wrap. A new e2e test checks that the inbox, with a letter opened in edit mode, and `/memory` don't overflow at 390 px, and that axe passes in both themes.

Behaviour and role rules are unchanged: `canDecide`, approvers, the reject/withdraw rules, the requests sent and the refusal messages are the same. The only change to existing tests is opening an inbox item before using its controls, plus one selector for the raised-ticket `dl`.

## How it fits the project

Approvals is where every side effect (a letter to the Outbox, an i-EMS ticket, a glossary change) gets a human decision. Memory is where officers see and correct what the agent learnt about them, and where curators vet what feedback proposes to teach the team.

The redesign makes the inbox quick to scan when many actions pile up across conversations, and keeps the full review (preview, diff, controls) one click away. Both screens now share the card, badge and token system used by in-chat results. The in-chat "Awaiting approval" card (#83) reuses the same `ActionCard` detail.

## Module breakdown

| Path | New / Modified | Role |
|---|---|---|
| `web/src/app/approvals/ApprovalsScreen.tsx` | Modified | Inbox as a list of `PendingItem` cards (disclosure + kept-mounted detail); audit trail as cards with type and decision badges |
| `web/src/app/approvals/ActionCard.tsx` | Modified | Always unframed `Detail` (the `embedded` prop is removed); `KIND_LABEL`; `Proposed` (proposer + age); danger variants on Reject/Withdraw |
| `web/src/app/approvals/approvals.module.css` | Modified | Toggle heading, meta line, detail divider, responsive slot tables and reason fields |
| `web/src/app/ApprovalCard.tsx` | Modified | Drops the removed `embedded` prop |
| `web/src/app/Card.tsx`, `card.module.css` | Modified | `as="article"` for list items; `cardListClass` (shared list of cards) |
| `web/src/app/dates.ts` (+ `dates.test.ts`, new) | Modified | `ago()` relative age; `dateOf()` a timestamp's day in SGT |
| `web/src/app/globals.css` | Modified | `danger` / `danger-solid` button variants |
| `web/src/app/memory/MemoryScreen.tsx` | Modified | Memory cards: kind heading, Not in use badge, provenance, Edit / Forget (danger) |
| `web/src/app/memory/CuratorQueue.tsx` | Modified | Curator proposals as cards with Proposed + age, danger reject/withdraw |
| `web/src/app/memory/memory.module.css` | New | Memory and curator card internals (text, meta, flag note, forms, actions) |
| `web/src/app/(shell)/memory/page.tsx` | Modified | "Your memories" section heading above the list |
| `web/src/app/{approvals,memory}/*.test.tsx` | Modified | List and detail, badges, age, danger, keeping typed input across close and open |
| `web/e2e/journeys.spec.ts`, `accessibility.spec.ts` | Modified | Open inbox items before deciding; axe on the opened detail; phone overflow check |

## Workflow map

```
/approvals (AppShell)
  └─ ApprovalsScreen ──GET /api/approvals, /api/audit──▶ BFF ──▶ plg-api
       ├─ PendingItem (Card article)
       │    header: [▸ title button] [type Badge]
       │    meta:   Conversation · Proposed by <ID> <time ago>
       │    detail (hidden until opened, kept mounted)
       │      └─ ActionCard ─▶ LetterCard | TicketCard | GlossaryCard
       │            └─ Controls ──POST /api/threads/{id}/resume (SSE)──▶ plg-api approval interrupt
       │                  └─ onDecided ─▶ results status + reload + shell.refresh() (sidebar count)
       └─ AuditTrail: Card articles [type Badge][decision Badge] + RaisedTicket fields / outbox item / letter as sent

Chat (AskScreen) ─▶ ApprovalCard ("Awaiting approval" Card) ─▶ the same ActionCard detail

/memory (AppShell)
  ├─ MemoryScreen ──GET/PATCH/DELETE /api/memory──▶ plg-api memory
  │    └─ Card article per memory [kind][Not in use?] → Edit | Forget (danger)
  └─ CuratorQueue ──GET /api/curation, POST /api/curation/decide──▶ plg-api curation
       └─ Card article per proposal → Approve | Edit | Reject/Withdraw (danger) → Confirm (danger-solid)
```

## Notes and next steps

- The inbox hides the conversation name when plg-api's curator title is `Proposed by <ID>`, because the meta line already says who proposed it. This copies a server-side string. A `curator_view` flag on `PendingApproval` would remove that dependency.
- Forget still deletes at once, with no confirmation, as before. It is worth considering a confirm step now that the button is styled as destructive.
- The e2e persona has no memories or curator items, so axe doesn't see the memory cards in their filled or flagged states. Seeding a memory in `scripts/e2e_server.py` would cover them.
- Two e2e tests failed once each under load (Ask-screen source viewer; the approvals phone test). Both passed on rerun, and the approvals tests passed 8 of 8 when repeated.
