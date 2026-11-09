# Issue #13: Excel tracker querying

Branch `feat/13-excel-trackers`. Parent: #1. Blocked by #12 (data questions over PLG Records, closed).

## What's been built

PLG officers can now ask data questions that need the hand-maintained Excel trackers (vacancy report, arrears ageing, rent roll, renewals pipeline, inspection tracker, officer task tracker, trade mix, feedback statistics), alongside PLG Records.

- **Loaded at ingestion.** `plg sync` cleans every `*.xlsx` in the corpus (outside `_` folders) into `.plg/trackers.duckdb`. On `poc-data` that is 8 workbooks loaded into 14 tables. The file is rebuilt from scratch on every sync and replaced in one atomic step. A `_workbooks` catalog table records what was loaded and how.
- **Cleaning:**
  - A two-row header with merged cells becomes one snake_case name per column (`Units › Total` → `units_total`, `Non-tenanted › Vacant` → `non_tenanted_vacant`). Column names that are SQL reserved words get a `_` suffix (`end_`).
  - Title rows above the table and text rows below it (`Notes`, `Static check: 135 tenancies in arrears, total S$962,688.00.`) are kept as notes.
  - Dates typed as text (`'30/09/26'`) are read day-first; 65 of them in the officer task tracker.
  - Tabs of one workbook with the same header (one tab per officer) become one table, with a `sheet` column naming the tab.
- **Formula cells are not trusted.** The workbooks were never opened in Excel, so formula cells hold no saved values. The loader leaves out:
  - formula columns; their formula is kept and rewritten in column names, e.g. `months_of_rent = arrears_incl_gst/(monthly_rent*1.09)`;
  - rows that are only formulas (TOTAL rows);
  - sheets that are mostly formulas (the summary and pivot sheets).

  The data agent computes these figures in SQL from the loaded data sheets, and can check its result against the preparer's "Static check" notes.
- **Querying.** The Warehouse attaches the trackers database read-only as catalog `trackers`. The SQL validator accepts `trackers.<table>` (not the `_workbooks` catalog), so tracker tables can be joined with PLG Records tables. The data agent's system prompt lists every tracker: its tables and columns, the formulas that were not loaded, notes, and the cleaning applied. The router now sends tracker questions to the data agent.

Ground truth from `_report.md`, checked through plg-api with scripted SQL:

| Question | Answer |
|---|---|
| Q9 | 47 vacant and 5 under tender at 31 Aug 2026 |
| Q10 | 22 tenancies with arrears above 3 months' rent |
| Q11 | Golden Leaf: S$22,672.00, 121 days, 4.0 months |
| Q13 | 2 bubble tea outlets in NC-PI-1 |
| Q24 | Lucky Star follow-up due 30 Jun 2026 |

## How it fits the project

The data agent (#12) could only see PLG Records. Many figures officers quote, such as the vacancy report's 47, the arrears ageing buckets and the renewal "LATE" flags, live in team spreadsheets. With the trackers loaded:

- the data agent answers "per the vacancy report…" questions from the tracker itself;
- it can join tracker rows to PLG Records to cross-check them;
- every query still goes through the same validator, EXPLAIN dry run and `sql_trace` event.

The agent is told to prefer PLG Records unless the question is about a tracker, and to say when the two disagree.

## Module breakdown

| Path | New / Modified | Role |
|---|---|---|
| `src/plg/data/trackers.py` | New | Reads the workbooks with openpyxl and cleans them: headers, notes, text dates, combined tabs, formula columns/rows/sheets left out. Writes the DuckDB file and the `_workbooks` catalog (`Workbook`, `TrackerTable` models). `describe()` renders the trackers for the agent's prompt. |
| `src/plg/data/warehouse.py` | Modified | `Warehouse(records_db, trackers_db)`: attaches the trackers read-only as catalog `trackers` before locking the connection. Its `trackers` property returns the loaded workbooks. |
| `src/plg/data/sqlcheck.py` | Modified | Allows `trackers.<table>` and `trackers.main.<table>`; still rejects other catalogs, `staff` and `_workbooks`. |
| `src/plg/agents/data.py` | Modified | `TRACKERS_PROMPT` section added to the system prompt when trackers are loaded. It says to compute formulas in SQL and to round ratios before comparing them with thresholds. |
| `src/plg/graph/build.py` | Modified | The router's description of the data specialist now names the trackers. |
| `src/plg/config.py` | Modified | `trackers_db` setting (`.plg/trackers.duckdb`, `PLG_TRACKERS_DB`). |
| `src/plg/cli.py` | Modified | `plg sync` loads the trackers and reports the counts. `plg ask` passes `trackers_db` to the Warehouse. |
| `src/plg/api/app.py` | Modified | plg-api passes `trackers_db` to the Warehouse. |
| `pyproject.toml`, `uv.lock` | Modified | `openpyxl` (runtime) and `types-openpyxl` (dev). |
| `tests/test_trackers_api.py` | New | HTTP-seam tests: Q9, Q10, Q11, Q13 and Q24 answers; formula columns rejected; text dates; tabs combined; joins with PLG Records; access boundaries; no trackers loaded. |
| `tests/conftest.py`, `tests/test_sync.py` | Modified | The session sync also loads the trackers (`trackers_db` fixture). `make_api` defaults to having no trackers. A test checks the sync output. |
| `CLAUDE.md`, `START.md` | Modified | Map, conventions, `PLG_TRACKERS_DB`, sync notes. |

## Workflow map

```
Ingestion
  plg sync ──► ingest/sync.py (search index, unchanged)
           └─► data/trackers.load_trackers(corpus_dir, trackers_db)
                 openpyxl ─► _Sheet (titles | header rows + merges | body | notes)
                          ─► _Table (drop formula rows/columns, type columns, text dates, combine tabs)
                          ─► .plg/trackers.duckdb  (tables + _workbooks catalog, atomic replace)

Question
  browser ─► BFF ─► POST /threads/{id}/runs ─► graph: route (data) ─► data node
     agents/data.answer
        warehouse.trackers ─► describe() ─► system prompt (tables, formulas not loaded, notes)
        run_sql ─► Warehouse.run
                     check_sql (rec tables | trackers.<table>) ─► EXPLAIN ─► execute
                     DuckDB :memory:  ATTACH rec (SQLite, READ_ONLY) + ATTACH trackers (DuckDB, READ_ONLY)
                ─► sql_trace event ─► merge ─► tokens ─► SSE
```

## Review outcome and next steps

- Fixed after review: comparing an unrounded computed ratio with a threshold counted 25 tenancies instead of 22, because four owe exactly 3.00 months and floating-point error pushes them over. The prompt now says to round ratios first, and a Q10 test checks it. Two naming cleanups were also made.
- Open:
  - A running plg-api only sees newly synced trackers after a restart. Reopening the Warehouse when the file changes would fix that.
  - The inspection tracker spells officer names in 10 ways for 4 people. Only the preparer's note is passed to the agent; a name → staff ID mapping during cleaning would let it report by officer.
  - A date column with any non-date text stays as text, with no note about it. It would be better to keep the dates and flag the cells that don't parse.
  - Standards smells left as they are: `trackers.py` mixes reading, cleaning, loading and prompt rendering, and `warehouse.py` loads openpyxl just to import it; `_column_type` and `_convert` repeat the same type branching; `Warehouse(records_db, trackers_db)` is repeated at two call sites.
  - The tests script the SQL, so they show the tables can answer the questions, not that Claude will write that SQL. A live eval run would cover that.
