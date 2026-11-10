# Issue #14: Reasoning panel with SQL copy and CSV export

Branch `feat/14-reasoning-panel`. Parent: #1. Blocked by #12 (data questions), which is done.

## What was built

When an officer asks a data question, a collapsible **Reasoning** panel appears under the answer. It shows how the answer was reached:

- One entry per `sql_trace` event (each query the data agent ran), with:
  - the plan
  - the reporting date
  - whether the query ran or was rejected
  - the SQL, with a **Copy SQL** button. If the clipboard is unavailable (e.g. plain HTTP), the panel tells the officer to copy the SQL by hand.
  - the rejection reason, for a rejected query
  - the **glossary definitions used**, each with its version and the dates it is in force (e.g. "Arrears v1 (plg:Arrears_v1), in force from 15 Apr 2026"). These are shown only for queries that ran, because a rejected query applied nothing.
  - any data-quality warnings
  - the **result table** (the first 10 rows and the total row count)
  - an **Export CSV** link
- The agent's explanation, below the queries.

The CSV export works as follows:

- It holds every fetched row (up to 500), not just the 10 shown.
- It follows RFC 4180, with CRLF line endings and a UTF-8 BOM so Excel reads it correctly.
- Text cells that a spreadsheet would run as a formula (starting `=`, `+`, `-`, `@`) get a leading apostrophe.
- It is built in the browser as a `data:` URL, so there is no new endpoint and the browser still never talks to plg-api.

### Back-end change

Before this change, `ResultSummary.sample` held only the first 10 rows of a result, which would have made the export incomplete. It is replaced by `ResultSummary.rows`: every fetched row, up to the warehouse's `MAX_ROWS` (500), with `truncated` still marking larger results.

This was agreed with the user. The OpenAPI document and the TypeScript types were regenerated.

## How it fits the project

Issue #12 made the data agent stream an `sql_trace` for every query, but the web app ignored those events. This ticket closes that gap: a data answer is now as traceable as a knowledge answer is through its citation chips. An officer can:

- check which definition version produced a figure, and the dates it is in force (e.g. why the count is 47 vacant units rather than 52)
- re-run or adapt the SQL
- take the full result into Excel

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/data/trace.py` | Modified | `ResultSummary.rows` (every fetched row) replaces the 10-row `sample` |
| `src/plg/agents/data.py` | Modified | `run_sql` puts all fetched rows in the trace; `SAMPLE_ROWS` removed |
| `tests/test_data_api.py`, `tests/test_trackers_api.py` | Modified | Assert that the arrears trace carries all 22 rows (ground truth) |
| `scripts/record_sse_fixtures.py` | Modified | New `data` script: a rejected query, then the arrears query over the semantic-layer binding |
| `web/src/test/fixtures/data.sse` | New | Recorded data-answer stream (2 `sql_trace` events, a warning, 22 rows) |
| `web/src/app/ReasoningPanel.tsx` | New | The panel: per-trace rendering, Copy SQL, result table, CSV export |
| `web/src/app/dates.ts` | New | `day()` / `period()` shared by `PolicyStanceCard` and `ReasoningPanel` |
| `web/src/app/AskScreen.tsx` | Modified | Collects `sql_trace` events into `traces`; renders `ReasoningPanel`; `emptyAnswer()` |
| `web/src/app/PolicyStanceCard.tsx` | Modified | Uses the shared date helpers |
| `web/src/app/ask.module.css` | Modified | Panel, SQL block, result table and warning styles |
| `web/src/lib/events.ts` (+ test) | Modified | Zod `result.rows`; exports `SqlTraceEvent` |
| `web/openapi.json`, `web/src/lib/api/schema.d.ts` | Regenerated | `ResultSummary.rows` |
| `web/src/app/AskScreen.test.tsx` | Modified | 6 Reasoning panel tests replaying `data.sse` |

## Workflow

```
officer asks a numeric question
  → BFF /api/threads/{id}/runs → plg-api POST /threads/{id}/runs → graph: route → data
      data agent: get_definition → run_sql (check_sql → EXPLAIN → execute, ≤500 rows)
        → SqlTrace(plan, sql, as_of, status, result{columns,row_count,truncated,rows}, concepts, warnings, explanation)
        → streamed as sql_trace events → merge streams the answer tokens
  → SSE through the BFF → events.ts (zod) → AskScreen accumulates traces
  → ReasoningPanel
       ├─ Copy SQL → navigator.clipboard.writeText (failure → "copy it by hand")
       ├─ result table (first 10 rows)
       └─ Export CSV → data:text/csv URL built from every row (memoised per result)
```

## Verification

- `uv run pytest`: 315 passed
- `uv run mypy`: clean
- web: `npm test` 76 passed; `npm run typecheck`, `npm run lint` and `npm run build` all clean

## Next steps

- **Reopened conversations:** thread history (`GET /threads/{id}`) stores only messages. An earlier data answer in a reopened thread therefore has no Reasoning panel, and earlier knowledge answers have no citation chips either. Persisting run events per turn would fix both and is worth its own ticket.
- **Results over 500 rows:** the export holds the first 500 rows, and the caption says so. A full export would need a server-side re-run endpoint that is owner-checked and re-validated.
- **Test coverage:** no test yet covers a results table over 500 rows or a run where every query is rejected.
