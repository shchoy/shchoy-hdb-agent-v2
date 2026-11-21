# Issue #17: Draft a standard letter from an approved template

An officer asks for an arrears reminder, a missing-documents notice or a feedback update reply. The `drafting` agent
picks the approved template (`TPL-REM-01`, `TPL-DOC-02`, `TPL-FBK-03`), fills its slots from PLG Records, lists what it
couldn't fill and flags personal data. The web app shows an HTML preview with a DOCX download. Nothing is sent and no
outbox item is created (there is no outbox yet; the agent's tools are read-only plus `submit_draft`).

## What was built

- Router: new `drafting` intent. `drafting` node in the graph; its finding goes to `merge` like the others.
- Agent tools: `get_template`, `lookup_records` (one read-only SELECT through the Warehouse validator), `submit_draft`.
  A later submission replaces an earlier one; only the last is stored.
- Slots with no value are listed with a reason (the agent's, or "No value was supplied."), and show as highlighted
  `«slot»` in the preview and DOCX. Approved wording is never changed; `[guidance]` is removed.
- PII check (deterministic): NRIC/FIN, phone or email that isn't the signing officer's, and, for replies to the public
  (`TPL-FBK-03`), tenant and contact-person names. Findings name the slot, not the value.
- API: `draft` SSE event; `GET /drafts/{id}/file` returns the DOCX, 404 for anyone but the requester.
- Web: `DraftPreview` (sandboxed iframe, no scripts), BFF `/api/drafts/[id]/file`, zod `draft` event, recorded `draft.sse`.

## Module map

| Path | Role |
|---|---|
| `src/plg/drafting/templates.py` | Load approved templates from `corpus_dir/docs/TPL-*.docx` |
| `src/plg/drafting/render.py` | Fill slots, HTML preview, DOCX |
| `src/plg/drafting/pii.py` | PII check |
| `src/plg/drafting/model.py`, `store.py` | `Draft` models; in-memory owner-checked `DraftStore` |
| `src/plg/agents/drafting.py` | The agent and its tools |
| `src/plg/graph/build.py`, `state.py` | `drafting` node and intent |
| `src/plg/events.py`, `runs.py`, `api/app.py` | `DraftEvent`, event mapping, download endpoint |
| `web/src/app/DraftPreview.tsx`, `api/drafts/[id]/file/route.ts` | Preview and download relay |
| `tests/test_drafting_api.py`, `web/src/app/api/drafts/routes.test.ts`, `AskScreen.test.tsx` | Tests |

## Next steps and known limits

- No test asserts "no outbox item": add when the outbox exists (#18).
- Editing slot values before approval and the approvals inbox are #18/#19. Drafts are in memory only.
- The agent's lookups aren't traced for the officer (no per-slot provenance).
- `officer_contacts` / `tenant_names` read `staff`/`tenants` with sqlite directly because the Warehouse blocks `staff`; consider a fixed read-only accessor.
- The phone regex can false-positive on unseparated 8-digit numbers; the tenant-name check is a substring match.
- `plg ask` doesn't print drafts.
