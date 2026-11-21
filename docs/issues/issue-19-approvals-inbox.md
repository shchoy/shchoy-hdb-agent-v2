# Issue #19: Approvals inbox screen

## What was built

An **Approvals inbox** at `/approvals` in the web app. A PLG officer sees every action waiting for their decision, across all their conversations. For each one they can:

- read the letter exactly as it would be sent (sandboxed HTML preview), its slot values, open slots and personal-data flags;
- **edit slots** inline, with each change shown diff-style against the proposal (`<del>` old, `<ins>` new);
- **approve and send** a complete letter, **send the edited letter** once every open slot is filled, or **reject** it with a reason;
- see the **result** straight away (outbox item ID and the version sent, or "nothing was sent");
- see their **audit trail** ("Decided"): who decided, their role, when, the reason, the edits, the outbox item with the letter as sent, and the run's LangSmith `run_id`.

Approve and edit are hidden from roles that can't send the action type (for example analysts), who can still reject. plg-api's refusals (403/409/422) and run failures are shown on the card with plg-api's reason. A failure arriving after the action's result doesn't hide that result. A failed reload keeps the inbox on screen.

To support this, plg-api gained `GET /audit`, which returns the officer's own decisions, newest first, each with the outbox item it sent. Audit entries now also carry the action `title` and `thread_id`.

## How it fits

Issue #18 made every outbound action a `ProposedAction` that waits on a LangGraph `interrupt()`. Until now, deciding on one meant calling the API by hand. #19 gives officers the human-in-the-loop surface promised by user stories 51 to 57 of #1:

- one inbox, so nothing waits forgotten;
- a clear preview of what will happen;
- an accountable decision with a reason;
- visible proof of what was sent and when.

The browser still never talks to plg-api: every call goes through the BFF.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/api/app.py` | modified | `GET /audit` → `list[AuditRecord]` (AuditEntry + `sent: OutboxItem \| None`). Builds the `LocalOutbox` / `AuditLog` once and shares them with the graph |
| `src/plg/actions/audit.py` | modified | `AuditEntry.title`, `thread_id` (defaults keep older log lines readable). `AuditLog.decided_by(staff_id)` |
| `src/plg/actions/outbox.py` | modified | `Outbox.item(item_id)` |
| `src/plg/graph/build.py` | modified | `execute_action` records the title and thread ID in the audit entry |
| `tests/test_approvals_api.py` | modified | Audit trail content (edit + reject, with what was sent) and ownership (own only, 401 without user) |
| `scripts/record_sse_fixtures.py` | modified | Records the approvals flow: two letters in two threads → `pending.json`, `edit.sse`, `reject.sse`, `audit.json` |
| `web/src/app/approvals/page.tsx` | new | Server page: signed-in user, banner, passes the role to the screen |
| `web/src/app/approvals/ApprovalsScreen.tsx` | new | Inbox, action cards (preview, slot diff, decisions), results, audit trail |
| `web/src/app/approvals/approvals.module.css` | new | Card, slot table and diff styles |
| `web/src/app/approvals/ApprovalsScreen.test.tsx` | new | Component tests replaying the recorded fixtures through MSW |
| `web/src/app/LetterFrame.tsx` | new | Sandboxed letter iframe, shared with `DraftPreview` |
| `web/src/app/DraftPreview.tsx` | modified | Uses `LetterFrame` |
| `web/src/app/dates.ts` | modified | `when()` timestamp formatting (Singapore time) |
| `web/src/app/api/approvals/route.ts` | new | BFF `GET /api/approvals` → plg-api `GET /approvals?status=pending` |
| `web/src/app/api/audit/route.ts` | new | BFF `GET /api/audit` → plg-api `GET /audit` |
| `web/src/app/api/threads/[id]/resume/route.ts` | new | BFF `POST` decision (zod-validated) → plg-api `/threads/{id}/resume`; streams SSE through, relays refusals |
| `web/src/app/api/approvals/routes.test.ts` | new | BFF tests (user forwarding, 401, 400, refusal relay, stream through) |
| `web/src/lib/server/plg-api.ts` | modified | `listApprovals`, `getAuditTrail`, `resumeThread`, and `relaySse` (shared SSE pass-through, now used by runs, runs/latest and resume) |
| `web/src/app/page.tsx`, `web/src/app/memory/page.tsx` | modified | "Approvals" nav link |
| `web/openapi.json`, `web/src/lib/api/schema.d.ts` | regenerated | `AuditRecord`, `GET /audit` |
| `web/src/test/sse.ts`, `web/src/test/fixtures/approvals/*` | modified / new | `approvalsFixture()` + recorded fixtures |

## Workflow

```
/approvals (ApprovalsScreen)
  ├─ GET /api/approvals ──BFF──> GET /approvals?status=pending ──> checkpoint interrupts of the officer's threads
  ├─ GET /api/audit     ──BFF──> GET /audit ──> AuditLog.decided_by(staff) + Outbox.item(outbox_id)
  └─ decision ─ POST /api/threads/{thread}/resume ──BFF (relaySse)──> POST /threads/{id}/resume
                                                         │  refusal 403/409/422 → shown on the card
                                                         └─ RunRegistry.start(ApprovalDecision)
                                                              → approval (interrupt resumed) → execute_action
                                                                  → Outbox.send (approve/edit) + AuditLog.record
                                                                  → SSE: action_result, done
       action_result → result banner; inbox + audit trail reloaded
```

## Notes and next steps

- **Diff of the letter text.** The diff compares slot values (proposed vs. what will be sent). The preview frame shows the proposed letter, and the re-composed edited letter is visible afterwards under "Letter as sent". A live re-rendered preview while editing would need a plg-api endpoint that composes a draft from slot edits without sending it.
- **Ticket payloads.** Only `send_letter` exists. i-EMS ticket actions (AC1) will need their own payload preview in `ActionCard`.
- **Trace link.** The audit trail shows the `run_id` as text. Turning it into a LangSmith link needs the project URL in configuration. The conversation (`thread_id`) is stored but not linked yet; the Ask screen opens threads through sessionStorage, not a URL.
- **Stale card after a 409.** A refused decision keeps its card with the reason; the list refreshes on the next decision or page load.
- The Ask screen still ignores `proposed_action` / `interrupt` events. A "waiting for your approval → Approvals" hint under the draft would join the two screens.
