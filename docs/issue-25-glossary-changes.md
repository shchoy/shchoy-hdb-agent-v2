# Issue #25: Glossary questions and controlled definition changes

## What was built

- **Glossary questions.** The knowledge agent has a read-only `glossary_definitions` tool. It returns every approved version of a business term (current and superseded) as one citable passage, `glossary:<concept>`. For each version the passage gives its effective dates, definition, value, source document and quote, plus the term owner. Answers about "what does vacant mean now, and what did it mean before" are therefore cited.
- **Proposing a change.** The router has a new `glossary` intent. The `glossary` node (Sonnet, forced `propose_glossary_change` tool) reads the officer's request. `actions/glossary.propose_change` then checks it in code:
  - the term exists and has a current version;
  - the new version starts after the current one took effect;
  - any new SQL binding passes the validator's dry run.

  If the checks pass, it becomes an `approve_glossary_term` `ProposedAction`. The payload holds the `proposed` term version (v+1, `supersedes` the current one) and `approvers = [term owner]`. Asking again in the same thread revises the pending proposal: same action ID, next version.
- **Approval through the same flow.** The term owner is the term's curator.
  - They see the proposal in `GET /approvals`, across anyone's threads, labelled "Proposed by &lt;staff ID&gt;".
  - They approve, edit (`definition`, `value`, `effective_from`) or reject it with `POST /threads/{id}/resume`, through the `approval` interrupt.
  - The proposer can only withdraw the proposal; anyone else gets 404.
  - A proposal whose predecessor has since been superseded gets 409.
- **Supersede, never delete.** `execute_action` writes the approved change to an append-only overlay, `.plg/glossary_changes.jsonl`:
  - The old version gets `effective_to` (the day before the new one starts) and status `superseded`.
  - The new version becomes `current`.
  - The new version either brings its own SQL binding or takes over its predecessor's.
  - The audit entry and the `action_result` event carry `term_id`.
- **The new version is used.** The data agent's `get_definition` and `run_sql`, the knowledge agent's glossary tool and `plg glossary list|show` all read the generated glossary with the overlay applied. An approval therefore takes effect at once and survives restarts.
- **Web.** The Approvals inbox has a `GlossaryCard`. It shows the current and proposed definitions as a diff, the reason, the SQL binding and the owner. Approve and edit appear only for `approvers`; the proposer gets Withdraw. The audit trail reads "adopted as …".

## How it fits the whole

Business definitions now change in a controlled, audited way, and SQL, retrieval and answers all keep using one versioned definition. The change reuses the approval machinery from #18 and #19 (ProposedAction, the interrupt, the audit log and the Approvals inbox). It generalises that machinery with `ProposedAction.approvers`, so an action can be decided by someone other than its proposer. Team-fact curation (#1, "Curators also see team-fact … proposals") can reuse the same mechanism.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/ontology/changes.py` | new | `GlossaryChanges` overlay (append-only JSONL), `GlossaryVersion` API model, `glossary()`/`layer()` overlays, `approve()` with stale and chain checks |
| `src/plg/actions/glossary.py` | new | `ChangeRequest`, `propose_change`, `edit_errors`/`edited`, preview HTML |
| `src/plg/agents/glossary.py` | new | `glossary_definitions` tool (citable passage), `read_change` (forced tool) |
| `src/plg/actions/model.py` | modified | `approve_glossary_term`, `GlossaryPayload`, `approvers`, `deciders()`/`may_decide()`, refusal rules |
| `src/plg/actions/audit.py`, `src/plg/events.py` | modified | `term_id` on the audit entry and on `action_result` |
| `src/plg/graph/build.py`, `graph/state.py` | modified | `glossary` intent and node; live glossary and layer for data and knowledge; execution of glossary changes |
| `src/plg/agents/knowledge.py` | modified | Adds the glossary tool and a prompt rule |
| `src/plg/api/app.py`, `src/plg/threads.py` | modified | Curator approvals across threads (`all_asked`), curator resume with a filtered stream, 403/409/422 for glossary changes |
| `src/plg/config.py` | modified | `glossary_changes` setting |
| `src/plg/cli.py` | modified | `plg glossary list/show` include approved changes |
| `web/src/app/approvals/*`, `web/src/lib/events.ts`, `web/src/test/sse.ts` | modified | GlossaryCard, zod schemas, fixtures helper |
| `scripts/record_sse_fixtures.py` | modified | `glossary` scenario → `web/src/test/fixtures/approvals/glossary_*` |
| `tests/test_glossary_api.py`, `tests/test_glossary_cli.py` | new / modified | HTTP-seam and CLI tests |

## Workflow

```
Officer (S02): "Propose a glossary change: vacant includes units under tender from 1 Oct 2026"
  → screen_input → route (glossary) → glossary node
       read_change (Claude, forced tool) → propose_change (checks; live glossary = generated + overlay)
  → merge (commits the proposal) → approval interrupt  ── proposed_action + interrupt events

Term owner (S08): GET /approvals  → sees it ("Proposed by S02")
  POST /threads/{id}/resume {approve | edit | reject}
       API checks: decider, owner-only approve, edits valid, predecessor still current
  → approval → execute_action → GlossaryChanges.approve (old: effective_to + superseded; new: current)
       → AuditLog (term_id) → action_result (term_id)   [stream shows only this action]

Anyone afterwards:
  data agent  get_definition / run_sql → in_force(date) → plg:Vacant_v3 + its binding
  knowledge   glossary_definitions → v3 current, v2/v1 superseded, cited
  CLI         plg glossary show vacant
```

## Next steps / known limits

- A pending proposal lives only in its action payload. It is not listed by `plg glossary list --all`, which says it shows proposed versions.
- An approved version with a future `effective_from` becomes `current` at once. Dated lookups (`in_force`) are still correct.
- Any signed-in officer may propose a change: there is no "policy owner" role check.
- Glossary and lineage citations (`doc_type` record) have no Sources-panel viewer. Opening one requests `/documents/<concept>`, which returns 404. This is pre-existing behaviour for `lineage:` citations too.
- `GET /approvals` reads every thread's checkpoint on each request, which is fine for the POC. An index of pending actions per decider would scale better.
