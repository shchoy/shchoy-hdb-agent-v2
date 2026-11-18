# Issue #28 — Incremental sync from mocked SharePoint and Lotus Notes

## What was built

Most of the issue was already in place from #5, and is kept as is:

- **Adapters:** the `DocumentSource` Protocol and the SharePoint and Lotus Notes mocks (`src/plg/ingest/sources.py`).
- **Incremental sync:** re-indexing is decided by content hash.
- **Superseded versions:** marked, never deleted.

This issue makes `plg sync` safe to run **on a schedule** (cron, launchd or a systemd timer):

- **One run at a time.** `sync_lock` takes a non-blocking `flock` on `<search_db>.sync.lock` for the whole run, including the Excel trackers.
  - A sync started while another holds the index prints `another plg sync is running on …; not starting another.`
  - It then exits 1 and writes nothing.
- **A bad file doesn't stop the run.** A document that can't be read (a corrupt export, or a scan Claude couldn't read) goes into `SyncReport.failed`.
  - It is printed as `Failed: <path> (<reason>)` and retried on the next run.
  - The other documents are still ingested.
  - The run exits 1 so the scheduler can alert.
  - The summary line now counts `failed`.
- **Nothing leaves the index.**
  - **Documents gone from their source:** a document no source lists any more stays indexed with its status, and is reported as `No longer available from its source (kept): <path>`.
  - **`--full`:** it now re-reads and re-embeds every listed document in place. It no longer runs `rmtree` on the index. That used to delete superseded versions that had left the source, and the `memory` table: officers' personal memories and curated team items.
- **No flapping mid-sync.** A re-indexed document keeps the status it already had (a superseded version is never briefly `current`), and `--full` doesn't re-report old versions as newly superseded.
- **A running plg-api sees a sync without a restart.**
  - `LanceSearchStore` connects with `read_consistency_interval=0`.
  - Before this, LanceDB's default meant a long-lived plg-api never saw rows written by another process.

## How it fits the whole

An administrator can schedule `uv run plg sync` nightly:

- **Searches:** officers' questions search tonight's documents the next morning, with no restart of `plg-api`.
- **Historical questions:** "what was the policy on <date>" still finds the superseded versions, even after a source drops them.
- **Memories:** personal memories and curated team items survive a `--full` rebuild.
- **Real connectors:** a real SharePoint or Lotus Notes connector implements `DocumentSource` and replaces a mock in the `plg sync` command.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/ingest/sync.py` | Modified | `sync(..., full=)` in place; `SyncReport.failed` / `.missing`; per-document read failures caught; `sync_lock` + `SyncRunning` |
| `src/plg/cli.py` | Modified | `plg sync` holds the lock; no more `rmtree`; prints `Failed:` / `Not in any source (kept):`; exit 1 on failures or a held lock |
| `src/plg/search/lance.py` | Modified | `read_consistency_interval=0`; dimension-mismatch message no longer points at `--full` |
| `tests/test_sync.py` | Modified | Missing documents kept; `--full` keeps history and memory; a store opened before a sync sees it; unreadable document → exit 1; an overlapping sync is refused |
| `tests/test_scan_ingest.py`, `tests/conftest.py` | Modified | An unreadable scan now fails the run; `run_sync(..., exit_code=)` |
| `START.md`, `CLAUDE.md` | Modified | Scheduled sync section (cron example); map updated |

## Workflow

```
cron / launchd ─▶ plg sync [--full]
                   └▶ sync_lock(<search_db>.sync.lock) ── held? → "another plg sync is running", exit 1
                        ├▶ DocumentSource.documents()  (SharePointSource, LotusNotesSource; real connectors later)
                        │     └▶ per doc: sha256 == indexed? → unchanged
                        │                 else extract (ScanReader for scans) → chunk → embed → store.replace_document
                        │                 read error → report.failed (others continue)
                        ├▶ lifecycle(): mark superseded (effective_to), never delete; indexed docs not listed → report.missing (kept)
                        ├▶ entities + FTS optimize
                        └▶ load_trackers (DuckDB)
                   report printed; exit 1 if any failed

plg-api (long-running) ─▶ LanceSearchStore(read_consistency_interval=0) ─▶ sees the new table version on the next search
```

## Next steps

- **Selecting connectors:** the source list is still fixed in `plg sync`. A real deployment would choose connectors from settings, with credentials.
- **Excel trackers:** they are rebuilt and swapped atomically, but plg-api still needs a restart to see them (its DuckDB attaches the file once).
- **Deletion as a signal:** a document removed at the source is only reported, never marked. If removal should mean "withdrawn", that needs a lifecycle status of its own.
- **Embedder changes:** changing the embedder dimension still means moving the index aside, and that loses memories. Moving memory to its own LanceDB folder would decouple the two.
- A document gone from its source stays `current` (only reported), so knowledge search still treats it as in force.
- Only file bytes are hashed: a listing-only change (title, library) with the same file is not re-indexed.
- A changed document that now fails to read, or yields no text, keeps its previous chunks with no stale marker.
- The per-document `except Exception` reports any extractor error (including a code bug) as "could not be read"; the repr names the exception type.
- `sync_lock` uses `fcntl` (POSIX only); it guards the trackers DB too, but is keyed on `search_db`.
