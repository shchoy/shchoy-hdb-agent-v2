# #105 Excel uploads queryable by the data agent

Parent: #98 (Conversation workspace). Blocked by #103 (uploads).

## What was built

- Officers can upload `.xlsx` workbooks (composer paperclip and drag-and-drop accept them).
- An uploaded workbook is cleaned **exactly like the Excel trackers** (`data.trackers.read_workbook`). Merged two-row headers become one name per column. Title and note rows are kept as notes. Dates typed as text are read day-first. Formula columns, formula-only (TOTAL) rows and mostly-formula sheets are not loaded; their formulas are shown so the agent can compute the figures in SQL.
- Every title, note and text cell is screened for prompt injection. A planted span is replaced by the ingestion marker in the data itself, and the upload carries an `InjectionFlag` with the rules that matched.
- Each workbook's tables get names unique among that officer's workbooks (a second copy's table gets `_2`). They are stored in the upload's folder (`tables.duckdb` + `workbook.json`). All of an officer's workbooks are combined into one `uploads_dir/<staff>/workbooks.duckdb`, rebuilt and replaced atomically after every add or delete.
- In that officer's data runs, the warehouse opens a connection of its own (`Warehouse.scoped`) that attaches the combined file **read-only** as `uploads`. The data agent sees the workbooks described like the trackers (a new UPLOADS prompt section) and queries them as `uploads.<table>`, joined with PLG Records and the trackers if needed. The validator only allows tables of the attached catalog. Another officer's tables, a staff-ID schema or `uploads.main.x` from another officer are all rejected.
- SQL traces are unchanged: `sql_trace` events carry every row fetched, so the reasoning panel and CSV export work for upload queries.
- `DELETE /uploads/{id}` (204; another officer's upload or an unknown ID gets 404) removes the file, its search passages and its tables. A failed upload is undone the same way.
- Routing: an attached workbook sends the question to the data agent; any other attached file still goes to knowledge. The router prompt also lists the officer's uploaded spreadsheets under `data`.

## How it fits

This completes the "Excel" part of the private library (#98). Officers can bring their own spreadsheet figures into a conversation, and the agent queries them with the same validation, glossary and trace guarantees as PLG Records. The figures never leave the officer's own runs.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/uploads/workbooks.py` | New | Read, screen, rename and save a workbook's tables; combine an officer's workbooks into `workbooks.duckdb`; describe a workbook as a document |
| `src/plg/uploads/library.py` | Modified | Accepts `.xlsx`; `_add_workbook`; `Upload.tables`; `delete`; `_discard` on failure; per-officer catalog locks; `workbooks_db(owner)` |
| `src/plg/data/trackers.py` | Modified | `SheetTable` (public), `write_workbook`, `create_catalog`, `sql_text` shared with uploads |
| `src/plg/data/warehouse.py` | Modified | `scoped(uploads_db)`, `uploads`, `close()`; generic read-only `_attach` |
| `src/plg/data/sqlcheck.py` | Modified | `UPLOADS` schema and `SCHEMAS` (trackers, uploads) |
| `src/plg/agents/data.py` | Modified | `UPLOADS_PROMPT`: the officer's workbooks in the system prompt |
| `src/plg/graph/build.py` | Modified | `attached_intents` (workbook → data); `data_node` runs on the scoped warehouse and closes it; router prompt |
| `src/plg/api/app.py` | Modified | `DELETE /uploads/{upload_id}` |
| `src/plg/documents.py` | Modified | `xlsx` document kind |
| `web/src/app/uploads.ts`, `web/openapi.json`, `web/src/lib/api/schema.d.ts` | Modified | Accept `.xlsx`; regenerated types (`Upload.tables`, `xlsx` kind, DELETE) |
| `tests/test_upload_workbooks_api.py` | New | HTTP-seam tests for every acceptance criterion |

## Workflow

```
POST /uploads (xlsx) → UploadLibrary.add → _add_workbook [officer lock]
    → workbooks.read (trackers.read_workbook + injection.screen, unique names)
    → workbooks.save (<id>/tables.duckdb, workbook.json)
    → _index_parsed (description chunks → LanceUploadIndex, upload.json)
    → workbooks.combine (<staff>/workbooks.duckdb, atomic)

POST /threads/{id}/runs → route (attached workbook → data)
    → data_node → warehouse.scoped(uploads.workbooks_db(staff))   # ATTACH … AS uploads (READ_ONLY), locked
    → data.answer (UPLOADS_PROMPT = describe(workbooks, "uploads"))
    → run_sql → check_sql (uploads.<table> allowed) → EXPLAIN → execute → sql_trace event
    → scoped.close()

DELETE /uploads/{id} → UploadLibrary.delete [officer lock] → index.remove, rmtree, combine
```

## Next steps

- #106 (My documents) should use `DELETE /uploads/{id}` and add its BFF route and UI.
- Not yet tested: that workbook rows in LangSmith traces are masked. The data path uses the same masking client as #103.
- Every data run by an officer with workbooks opens a new DuckDB connection. Cache it per officer if this becomes slow.
