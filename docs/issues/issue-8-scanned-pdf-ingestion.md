# Issue #8 — Scanned PDF ingestion

Parent: #1 · Blocked by: #5 (corpus ingestion and hybrid search)

## What was built

Image-only PDFs in the library are read by Claude (PDF input) during `plg sync`, so they are searchable and citable by
page and open in the source viewer.

- **Reading**: a PDF with no text layer is sent to `LLMClient.complete` (node `ingest_scan`, Sonnet) as a base64 `document`
  block with a forced `record_transcript` tool. Claude returns the title, any document-control fields and the text per page,
  which is also the document identification. A listing title, if any, still wins over Claude's.
- **Page locations**: each page becomes a level-1 `Page N` heading block, so chunks are located "Page 2 (p. 2)".
- **No reprocessing**: the transcript is saved as JSON named by the scan's SHA-256 in `Settings.transcripts_dir`
  (`<search_db>-transcripts`). Unchanged scans are skipped by the content-hash check; `--full` and the source viewer reuse the
  saved transcript. The viewer never calls Claude.
- **Failures**: if Claude fails or returns nothing, the scan is skipped (`scan could not be read: ...`) and retried next sync.
- `LLMClient.complete` gained an optional `max_tokens` (transcripts use 16000); `ScriptedLLMClient` keys on the text block of
  a document + text message.

## Scope decision

The issue says 9 image-only PDFs; the corpus has **8** (the precedent compendium has a text layer). Only the library scan
`pdfs/Scan_TA_TA-2024-00451_HengAnn.pdf` is ingested. The 7 scans under `pdfs/submissions/` stay excluded
(Tenant Submissions, checked per application by the doc-check flow, #21). This deviates from the literal first acceptance
criterion, by the user's decision.

## Module map

| Module | Role |
|---|---|
| `ingest/scans.py` (new) | `ScanReader` (Claude PDF input, caches), `TranscriptStore`, `SavedScans` (read-only, for the viewer), `Transcript`, `ScanError` |
| `ingest/extract.py` | `extract(path, scans?)`: an image-only PDF takes its blocks from `scans`; `ScanSource` protocol |
| `ingest/sync.py` | `sync(..., scans?)`; `ScanError` becomes a `Skipped` entry |
| `documents.py`, `api/app.py` | viewer reads scan blocks from `SavedScans` |
| `cli.py`, `config.py`, `llm.py` | `plg sync` builds the `ScanReader`; `transcripts_dir`; `max_tokens` override |
| `tests/test_scan_ingest.py` (new) | scripted-LLM tests: indexing and pages, PDF input sent, no reprocessing, `--full` reuse, unreadable scan, source viewer |

## Next steps

- Transcripts are keyed by file hash only; a prompt or model change does not invalidate them.
- No test yet that a knowledge answer cites a scan chunk end to end.
- #21 (document completeness) will need to read the submission scans, including the illegible one.
- Record the 8-vs-9 deviation on issue #8.
