# Issue #21: Document completeness check

## What's been built

A leasing officer picks an application on the **Document check** screen (or asks "Is application APP-2026-0294
complete?") and gets a checklist for its application type, with ✓ / ✗ / – for each document.

- **Identified by content, not file name.**
  - A PDF with a text layer is recognised by its printed title. For example, `scan_0006.pdf` is the Letter of Offer
    acceptance.
  - Image-only scans (and PDFs matching no known title) are read by Claude (Sonnet, PDF input). Claude transcribes
    the page, says whether it is legible and names the document type.
- **Flagged documents.**
  - **Expired:**
    - business profile more than 3 months old;
    - insurance not in force when the new term starts (renewals) or on the submission date;
    - lapsed licence or contractor registration.
  - **Wrong unit:** the document names another unit ID or address.
  - **Illegible scan.**
- **Missing-documents notice.** An incomplete bundle gets the approved template TPL-DOC-02, filled from the check and
  PLG Records. It lists every missing or rejected document with the reason. It is proposed as a `send_letter` action
  and goes through the existing approval flow (interrupt → Approvals inbox → resume). Nothing reaches the Outbox until
  the officer approves. The letter reference is left open for the officer to fill in.
- **Checklists per type.** New tenancy, renewal, assignment, change of trade and A&A, from the ontology vocabularies.
- **Ground truth.** All 20 bundles in `poc-data/pdfs/submissions` match `submission_bundles_ground_truth.json` on:
  - the checklist (expected and optional documents);
  - the documents present and each file's identification;
  - missing documents;
  - wrong-unit and illegible flags;
  - every ground-truth "expired".

  **Agreed deviation:** the ground truth marks the insurance of renewals APP-2026-0278, -0288 and -0268 as valid,
  although it ends before the new term starts. Their dates are indistinguishable from the two renewals it marks
  expired (a generator quirk). The check follows the documented rule and flags all of them. The test lists them as
  `KNOWN_GT_DEVIATIONS`.

## How it fits the whole

It is the specialist for issue #1's AC5 (user stories 65 to 70), on the same pattern as `defect_flow`:
- `route` sends the question to `doc_check`;
- the subgraph produces a deterministic, traced finding for `merge`;
- its side effect (sending the notice) exists only as a `ProposedAction` behind the `approval` interrupt;
- every decision is audited.

It reuses the drafting stack (templates, compose, PII check, DOCX, DraftStore), the approvals and outbox adapters, and
the ontology vocabularies. Scan reading builds on the Claude PDF input path introduced for scanned PDF ingestion (#8).

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/doccheck/checklists.py` | New | Checklists per application type, from the vocabularies |
| `src/plg/doccheck/identify.py` | New | Identify each file: title signatures for text PDFs, Claude (Sonnet, PDF input) for scans |
| `src/plg/doccheck/rules.py` | New | The application from PLG Records; the rules (BIZ vs BIZ2, wrong unit, expiry, illegible); builds the `DocCheck` |
| `src/plg/doccheck/model.py` | New | `DocCheck`, `ChecklistLine`, `FileCheck`, `Submission` |
| `src/plg/doccheck/notice.py` | New | TPL-DOC-02 filled from the check |
| `src/plg/doccheck/flow.py` | New | `doc_check_flow` subgraph, finding summary, `submissions()` listing |
| `src/plg/graph/build.py` | Modified | `doc_check` intent in the route prompt and tool, `doc_check_node`, shared `propose_sending` |
| `src/plg/graph/state.py` | Modified | `Intent` gains `doc_check` |
| `src/plg/events.py`, `src/plg/runs.py` | Modified | `DocCheckEvent` (`doc_check`) in the SSE stream |
| `src/plg/config.py` | Modified | `submissions_dir` property |
| `src/plg/api/app.py` | Modified | `GET /submissions`; checklists wired into the graph |
| `tests/test_doc_check_api.py` | New | HTTP-seam tests: ground truth for the 20 bundles, checklist, identification, flags, notice + approval, listing |
| `scripts/record_sse_fixtures.py` | Modified | `doc_check`, `doc_check_problem` and `submissions` fixtures; optional scenario names |
| `web/src/app/DocCheckCard.tsx` | New | Checklist card (table, ✓ / ✗ / –, reasons, files, scan marker) |
| `web/src/app/doc-check/` | New | Document check screen (pick, stream, card, notice, links) and its tests |
| `web/src/app/api/submissions/` | New | BFF relay of `GET /submissions` |
| `web/src/app/runClient.ts` | New | Thread and run helpers shared by the Ask and Document check screens |
| `web/src/app/AskScreen.tsx` (+ test) | Modified | Renders `DocCheckCard` for `doc_check` events |
| `web/src/lib/events.ts`, `web/src/lib/server/plg-api.ts`, `web/openapi.json`, `web/src/lib/api/schema.d.ts` | Modified | zod schema, `listSubmissions`, regenerated types |
| `web/src/app/{page,approvals/page,memory/page}.tsx` | Modified | "Document check" nav link |

## Workflow

```
/doc-check ──GET /api/submissions──▶ BFF ──X-PLG-User──▶ GET /submissions ──▶ flow.submissions() (PLG Records + bundle folders)
    │ pick APP-ID
    ▼
POST /api/threads + /api/threads/{id}/runs ──▶ plg-api POST /threads/{id}/runs ──▶ stream_run ──▶ graph
graph: route (Haiku) ─▶ doc_check_node ─▶ doc_check_flow:
          load_application (APP ID → PLG Records: tenant, unit address, tenancy end; bundle = submissions_dir/APP-ID)
          ─▶ identify_files (parallel: pypdf title ─or─ LLMClient.complete Sonnet + PDF ─▶ record_document)
          ─▶ check_bundle (Checklists + rules ─▶ DocCheck)
          ─▶ propose_notice (incomplete: TPL-DOC-02 via drafting.compose ─▶ Draft + DOCX)
       doc_check_node: stream `doc_check` (+ `draft`), DraftStore.add, letters.propose_letter ─▶ send_letter action
       ─▶ merge (streams the answer from the traced finding) ─▶ write_memory ─▶ approval (interrupt)
SSE: doc_check, draft, token, proposed_action, interrupt ─▶ DocCheckCard + DraftPreview + "Review the notice in Approvals"
Approvals inbox ─▶ POST /threads/{id}/resume (edit letter_ref / approve / reject)
       ─▶ execute_action ─▶ LocalOutbox item + AuditLog entry ─▶ action_result
```

## Next steps

- **Upload a bundle** (story 65's "or upload its bundle"): not built. Picking an application is the only way in.
- **Run without the router:** a pick on the Document check screen still goes through the Haiku `route`. A
  low-confidence routing would return a clarifying question instead of a checklist. Consider a direct doc-check run
  endpoint, or a forced intent.
- **Cache scan readings by file hash**, like the transcripts of #8, so re-checking doesn't call Claude again.
- **GraphStore lookups:** the spec asks for the doc-check lookups on `GraphStore` with matching openCypher templates.
  The lookups here read PLG Records directly.
- **Reconnect:** `/doc-check` reads its stream once (no Last-Event-ID reconnect). "Open the conversation" hands the
  run over to the Ask screen.
- **Flaky web test:** "Reasoning panel > copies a query's SQL to the clipboard" failed once in a full run (an existing
  test, not changed here).
