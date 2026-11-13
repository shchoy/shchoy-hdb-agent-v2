# Issue #20: Defect classification and i-EMS ticket proposal

## What was built

A customer relations officer pastes feedback, or names a feedback case. They get back a classification: category,
severity, routing team, vendor, SLA, confidence and rationale. Maintenance defects also get a proposed i-EMS ticket
for the right team and vendor, with the SLA for the ticket's severity. The officer approves, edits or rejects the
ticket in the Approvals inbox. Nothing reaches the i-EMS mock until they approve it.

- **Routing.** A new `defect` intent: `route` sends feedback-classification requests to the `defect` specialist.
- **`defect_flow` subgraph.** It has two steps:
  - `classify_feedback`: Haiku with a forced `classify_feedback` tool. If the question names a feedback case, the case as held in PLG Records is added to the context.
  - `propose_ticket`: runs for i-EMS categories only.
- **Classification rules** (deterministic, in `resolve`):
  - Every category named with confidence ≥ 0.3 is plausible.
  - If several are plausible, the result is low confidence (capped at 0.5) and the **most severe** category wins. For example, a wet ceiling with flickering lights resolves to Electrical (High) over Water Seepage (Medium).
  - Severity is the category's default from the taxonomy.
- **Taxonomy.** The 11 feedback categories of the ontology vocabulary, each with its team, vendor, default severity and i-EMS flag:
  - 6 are i-EMS defects: STR, SEP, PLB, ELE, FIR, PST.
  - 5 are non-defects (HYG, ENC, NOI, CMN, OTH). They get a classification but no ticket, and are never routed to maintenance.
  - The issue says "8-category taxonomy", but the ontology and `_master` ground truth have 11. The extra non-defect categories are what make "non-defect complaints are recognised" possible.
- **SLA by severity**, as applied by every ticket in PLG Records: Critical 1 day, High 3, Medium 7, Low 14.
- **`raise_ticket` proposed action** (`TicketPayload`), approved through the #18 approval interrupt:
  - Editable fields: category (re-routes the team and vendor), severity (resets the SLA), unit, description and feedback case.
  - Analysts and Legal can't raise tickets.
- **`TicketSystem` adapter.** The `LocalTicketSystem` i-EMS mock writes one JSON file per ticket under `.plg/iems`.
  - Writes are idempotent by ticket ID.
  - Each ticket links back to its feedback case (`feedback_id`); `for_feedback(id)` lists a case's tickets.
  - The audit log records `ticket_id`, and `GET /audit` returns the raised `ticket`.
- **Web.**
  - `ClassificationCard` under the answer.
  - `TicketCard` in the Approvals inbox: classification details, ticket preview, editable fields shown as a diff, and approve and raise / raise edited / reject.
  - The audit trail shows the raised ticket.

## How it contributes

This covers AC1 of the tracking spec (user stories 60–64): feedback is classified and routed consistently, safety
issues aren't under-classified, and non-defects stay out of maintenance. It is the second action type behind the
approval interrupt, after letters, so the proposed-action model now carries more than one kind of side effect. The
Outbox and `TicketSystem` are separate adapters, which can be swapped for real connectors.

## Modules

| Path | New / Modified | Role |
|---|---|---|
| `src/plg/defects/taxonomy.py` | New | Taxonomy from the vocab (team, vendor, default severity, i-EMS flag), `SLA_DAYS`, severity rank |
| `src/plg/defects/classify.py` | New | Haiku classifier (`defect` node, `classify_feedback` tool) and the `resolve` rules; `Classification` model |
| `src/plg/defects/flow.py` | New | `defect_flow` subgraph: classify_feedback → propose_ticket; feedback case lookup (PLG Records, read-only) |
| `src/plg/defects/tickets.py` | New | `Ticket`, `TicketSystem` protocol, `LocalTicketSystem` (i-EMS mock) |
| `src/plg/actions/tickets.py` | New | `propose_ticket`, `edit_errors`, `edited`, `to_ticket`, ticket preview HTML |
| `src/plg/actions/model.py` | Modified | `raise_ticket` action type and approver roles, `TicketPayload`, payload union with `kind` |
| `src/plg/actions/letters.py`, `audit.py` | Modified | Letter code ignores ticket payloads; `AuditEntry.ticket_id` |
| `src/plg/graph/build.py`, `state.py` | Modified | `defect` intent and route prompt, `defect_node`, `execute_action` raises tickets via `TicketSystem` |
| `src/plg/events.py`, `runs.py` | Modified | `classification` event; `action_result.ticket_id` |
| `src/plg/api/app.py`, `config.py` | Modified | Ticket edit validation on resume (422); `AuditRecord.ticket`; `iems_dir` setting |
| `tests/test_defect_api.py`, `tests/conftest.py` | New / Modified | HTTP-seam tests: classification, ambiguity, non-defect, approve/reject/edit, roles, case link |
| `web/src/lib/events.ts`, `openapi.json`, `schema.d.ts` | Modified | zod schemas and generated types for the new event and payload union |
| `web/src/app/ClassificationCard.tsx`, `AskScreen.tsx` | New / Modified | Classification card under the answer |
| `web/src/app/approvals/ApprovalsScreen.tsx` | Modified | `TicketCard`, ticket result line and audit trail; letters unchanged |
| `scripts/record_sse_fixtures.py`, `web/src/test/fixtures/*` | Modified / New | `defect.sse`, `approvals/ticket_edit.sse`, ticket in pending/audit fixtures |

## Workflow

```
officer (web Ask / POST /threads/{id}/runs)
  → route (Haiku) ── intent "defect"
  → defect node ── defect_flow.ainvoke
        classify_feedback: [FB case from PLG Records] → Haiku classify_feedback → resolve (most severe plausible)
        propose_ticket (i-EMS category + signed-in user) → ProposedAction raise_ticket (team, vendor, SLA)
     streams `classification`; finding → merge (streamed answer)
  → approval interrupt ── proposed_action + interrupt events → Approvals inbox (TicketCard)
officer decides (POST /threads/{id}/resume: approve | edit fields | reject + reason)
  → execute_action: edit → tickets.edited (re-route / new SLA); approve/edit → TicketSystem.raise_ticket (.plg/iems)
     → AuditLog entry (ticket_id, run_id) → action_result (ticket_id) → GET /audit shows the raised ticket
```

## Next steps

- Pasted feedback without a case gets a new `FB-NEW-…` ID that exists only on the ticket. A real feedback-case
  record (or a CRM adapter) would make that link resolvable. There is also no endpoint yet listing a case's tickets
  (`for_feedback` is adapter-only).
- Severity is always the category default. The classifier could be allowed to escalate it, e.g. for "sparks".
- Ambiguity depends on Haiku naming both categories at ≥ 0.3. LangSmith evals (defect ≥ 85% macro-F1) should check
  this on `feedback.json`'s ambiguous cases.
- The code tells letters and tickets apart by `action_type` in some places and by payload type in others (build.py,
  app.py, ApprovalsScreen). A per-action-type handler would put this in one place as more action types arrive.
- `plg ask` has no signed-in user, so it classifies but never proposes a ticket.
