# Issue #18: Approve, edit or reject a proposed action

## What's been built

Anything that would leave the system is now only **proposed**. A drafted letter (issue #17) becomes a `send_letter`
`ProposedAction` with a stable `action_id` and a `version`. The graph pauses at an `approval` node using LangGraph `interrupt()`, and the
run's SSE stream ends with `proposed_action` and `interrupt` events. The officer decides with
`POST /threads/{id}/resume {action_id, version, decision, edits?, reason?}`:

- **approve**: `execute_action` writes the letter to the local **Outbox** (`.plg/outbox/<action_id>-v<version>.json`).
- **edit**: the slot edits are re-composed into the next version (re-rendered and PII-checked), and that edited letter is what's sent.
- **reject** (a reason is required): nothing is sent.

Every decision appends exactly one entry to the **audit log** (`.plg/audit.jsonl`). Each entry has the approver and their role, the time, the
decision, any edits or reason, the outbox item, and the LangSmith `run_id` of the run that carried it out. The resume stream reports
`action_result` and then `done`.

Guards (all leave the outbox and audit log untouched):

| Case | Result |
|---|---|
| Not the thread's owner | 404 |
| Wrong version, unknown action ID, or a replay of an already-decided action | 409 |
| Approve/edit by a role that can't approve `send_letter` (analysts) | 403 (they can still reject their own proposal) |
| Reject without a reason; an edit naming unknown slots or blanking a slot; open slots left unfilled | 422 |

The same decision checks run again inside the graph (`ApprovalDecision.refusal`), so `execute_action` can't act on a stale
or forged resume value. It's the only node with side effects, and no model toolset contains a tool that acts.

`GET /approvals?status=pending` lists the officer's own pending actions across all their threads. `GET /threads/{id}` now includes
`pending`. Both are read from the checkpoint's interrupts, so a pending approval survives a `plg-api` restart.
Asking for the same template again in a thread revises the pending letter (same ID, version + 1), and approving the old
version then gets a 409. A thread can hold several pending actions, and any of them can be decided first.

## How it fits the whole

This delivers the spec's human-in-the-loop guarantee (#1 user stories 50, 53, 54, 56–59, and "SYS HITL"): high-impact
actions are always reviewed, are bound to the exact version the approver saw, and are audited with a link to the trace.
It is the backend that the Approvals inbox screen (#19) builds on. Defect tickets (#20), document-check notices (#21) and
glossary changes (#25) will add new `ActionType`s and payloads on the same `approval` → `execute_action` path.

## Module breakdown

| Path | New / modified | Role |
|---|---|---|
| `src/plg/actions/model.py` | New | `ProposedAction`, `LetterPayload`, `ApprovalDecision` (+ `refusal`), `APPROVER_ROLES`, `upsert_actions` reducer |
| `src/plg/actions/letters.py` | New | Draft → `send_letter` proposal (revises a pending one of the same template); edits → next version |
| `src/plg/actions/outbox.py` | New | `Outbox` protocol + `LocalOutbox` (JSON per item, idempotent overwrite) |
| `src/plg/actions/audit.py` | New | `AuditLog`: append-only JSONL, one entry per decided action |
| `src/plg/drafting/compose.py` | New | Slot values → `Draft` + DOCX; shared by `submit_draft` and approval edits |
| `src/plg/agents/drafting.py` | Modified | Uses `compose`; docstring: drafting sends nothing |
| `src/plg/graph/state.py` | Modified | `proposed_actions`, `decision`, `RUN_ID` |
| `src/plg/graph/build.py` | Modified | Drafting proposes; `approval` (interrupt) and `execute_action` nodes; conditional edge after the answer |
| `src/plg/events.py` | Modified | `proposed_action`, `interrupt`, `action_result` events |
| `src/plg/runs.py` | Modified | Resume via `Command(resume=decision)`; interrupts → `proposed_action` + `interrupt` events; run ID passed to nodes |
| `src/plg/threads.py` | Modified | `RunRegistry.start(..., decision)` so resumes are background runs that can be followed (409 while running) |
| `src/plg/api/app.py` | Modified | `POST /threads/{id}/resume`, `GET /approvals`, `ThreadView.pending` |
| `src/plg/config.py` | Modified | `outbox_dir`, `audit_log` |
| `tests/test_approvals_api.py` | New | 15 HTTP-seam tests (outbox and audit log as observable outcomes) |
| `tests/conftest.py`, `tests/test_drafting_api.py` | Modified | `Api.resume`, temp outbox/audit; trajectory now ends at `approval` |
| `scripts/record_sse_fixtures.py`, `web/src/test/fixtures/*.sse` | Modified | Outbox/audit in scratch dirs; `draft.sse` now carries `proposed_action` + `interrupt` |
| `web/src/lib/events.ts`, `web/openapi.json`, `web/src/lib/api/schema.d.ts` | Modified | zod schemas for the new events; regenerated types |

## Workflow map

```
POST /threads/{id}/runs  "Draft a reminder for …"
  → stream_run → graph: route → drafting (submit_draft → Draft) ──► letters.propose_letter → state.proposed_actions
               → merge → write_memory → after_answer: pending? ──► approval: interrupt([pending actions])
  ◄ SSE: … draft, token…, node approval, proposed_action, interrupt, done           (checkpoint in threads.sqlite)

GET /approvals?status=pending  → ThreadStore.list(owner) → graph.aget_state → interrupts → PendingApproval[]

POST /threads/{id}/resume {action_id, version, decision, edits?, reason?}
  → owner? (404) → pending id+version? (409) → role? (403) → slots/reason? (422)
  → RunRegistry.start(decision) → stream_run(Command(resume=ApprovalDecision))
  → approval: refusal re-checked → execute_action:
        approve → Outbox.send(item)            edit → letters.edited → next version → Outbox.send
        reject  → nothing sent
        every decision → AuditLog.record(approver, role, at, run_id, outbox_id)
  → after_answer: more pending? → approval (interrupt again) : END
  ◄ SSE: node…, action_result, done(run_id = audit entry's run_id)
```

## Next steps

- **#19 Approvals inbox screen.** Record a resume fixture (`action_result`) in `scripts/record_sse_fixtures.py`, then build the
  inbox, diff preview, editable slots and audit trail. The web app currently validates the new events but doesn't render them.
- **Audit trail endpoint.** Nothing serves past decisions or the outbox result over HTTP yet; #19 will need something like
  `GET /approvals?status=decided` or `GET /approvals/{id}`.
- **Failure window.** `execute_action` writes the outbox and then the audit entry. A crash between the two leaves an item with no
  audit entry, and the interrupt has already been consumed. Consider auditing first, or a recovery check at startup.
- **Edited-letter PII.** An edit re-runs the PII check, but the findings only go into the outbox. They don't stop the send, and
  the approver doesn't see the result before it goes.
- **Repeated reminders.** While an action is pending, every later turn in that thread ends with `proposed_action` + `interrupt` again.
  This is intentional, but the UI should treat it as a reminder, not a new proposal.
- **CLI.** `plg ask` stops silently at a proposal. The spec's `plg approve` command isn't built yet.
- **Concurrency.** The 409 for a concurrent resume relies on the single-worker `RunRegistry`. That's fine for the POC, but more than
  one worker would need a lock.
