# Issue #5: Corpus ingestion and hybrid search

Issue: https://github.com/shchoy/shchoy-hdb-agent-v2/issues/5 (parent: #1, blocked by: #4)
Branch: `feat/5-corpus-search` (built on top of `feat/4-ontology-glossary`). Commit: `91ce53b`.

## What was built

A system administrator runs `plg sync`. The command takes the text documents in the corpus (DOCX, text PDFs, PPTX,
emails, Markdown and text notes) and loads them into a LanceDB `SearchStore`. Each document is split by its
structure into chunks, and every chunk carries full metadata. `plg search` (and the `Searcher` class that the
`knowledge` node will use) finds chunks in three steps:

1. It applies the metadata filters first.
2. It ranks what is left by a linear combination of full-text and vector scores.
3. It re-scores the top candidates with a cross-encoder model that runs locally.

### Acceptance criteria

| Criterion | Status | Where |
|---|---|---|
| `SearchStore` interface with a LanceDB implementation (`chunks`, `entities`, `memory` tables); `Embedder` interface with Voyage AI | Done | `search/store.py`, `search/lance.py`, `search/embed.py` |
| Chunks carry a contextual header, FTS text, a vector and the full metadata | Done (`category` stays empty until the `categorise` job fills it) | `search/models.py`, `ingest/sync.py` |
| POL-003 v1.0/v2.0 and SOP-011 v1.0/v1.1 have the right effective dates and status | Done (see below) | `ingest/metadata.py`, `tests/test_sync.py` |
| Hybrid search (FTS + vector, linear combination) with metadata pre-filters, then a local cross-encoder rerank | Done | `search/lance.py`, `search/rerank.py`, `tests/test_search.py` |
| Generator ground truth (`_master/`) is never indexed | Done (any path part starting with `_` is refused) | `ingest/sources.py`, `tests/test_sync.py` |
| `SearchStore` contract tests that a future OpenSearch adapter can run | Done (suite runs over a `STORES` registry) | `tests/test_search_store_contract.py` |

### Policy lifecycle at ingestion

Each version's start date comes from the document-control block. Within a policy ID, the highest version is
current. Every earlier version is marked superseded and ends the day before its successor starts. This is the same
convention as the glossary.

| Document | Effective from | Effective to | Status |
|---|---|---|---|
| PLG-POL-003 v1.0 | 2024-03-01 | 2026-03-31 | superseded |
| PLG-POL-003 v2.0 | 2026-04-01 | (none) | current |
| PLG-SOP-011 v1.0 | 2025-03-03 | 2025-11-30 | superseded |
| PLG-SOP-011 v1.1 | 2025-12-01 | (none) | current |

Circular 07/2026 keeps the period it states itself: 2026-08-01 to 2027-07-31.

### Results on the real corpus (Voyage `voyage-3.5`)

- A full sync indexes 63 documents as 311 chunks in about 1m45s. Running it again with nothing changed
  re-embeds nothing.
- "When does PLG issue a Letter of Demand?" with `--status current` puts POL-003 v2.0 §4.5 first.
  Circular 03/2026 and SOP-014 v1.2 follow.
- The same question with `--in-force-on 2025-06-01` returns POL-003 v1.0 §4.4 instead.

### Design decisions

- **Sources:** two mocks of the `DocumentSource` adapter.
  - `SharePointSource` reads `exports/sharepoint_document_listing.json`. Its document IDs are the SharePoint
    item IDs.
  - `LotusNotesSource` reads `emails/**/*.eml`. Its document IDs are `LN-` plus a hash of the Message-ID.
- **What is excluded:**
  - Application bundles (`pdfs/submissions/`) are left out, because doc-check handles them per application.
  - Spreadsheets are ignored, because they go to DuckDB.
  - Image-only scans are skipped and listed in the sync report.
- **Incremental sync:** a document is re-processed only when its SHA-256 content hash changes. A new version marks
  the previous one superseded without re-embedding it. `--full` drops the index and rebuilds it.
- **Entities:** the `entities` table and the tagger use the same name variants. They cover towns, NCs, tenants
  (with and without "Pte Ltd"), staff, and trades from the vocabulary. Chunks also pick up IDs that match the
  strict ID patterns, and unit IDs map to their NC and town through `blocks`. A name that belongs to several
  tenants tags every one of them; for example "Golden Leaf Minimart" is both T-11962 and T-11108.
- **Memory:** `put/get/delete/search_memory` stores items by namespace and key, with status and expiry. It is
  ready for the memory ticket.
- **Tests stay mostly offline:**
  - Embeddings in tests come from `HashingEmbedder`.
  - The Voyage client is tested against a fake HTTP endpoint (`httpx2.MockTransport`).
  - The exception is the cross-encoder in `test_search.py`, which is real and downloads once into `.plg/models`.
    CI caches that folder.

## Map of the new modules

```
src/plg/
├── config.py         + corpus_dir, search_db (.plg/lancedb), embed_model/embed_dim (voyage-3.5, 1024),
│                       voyage_base_url, rerank_model (Xenova/ms-marco-MiniLM-L-6-v2), model_cache (.plg/models),
│                       search_candidates, vector_weight. Each can be overridden with PLG_<FIELD>.
├── cli.py            + `plg sync [--full]`, `plg search <q> [--status] [--type] [--in-force-on] [--k]`,
│                       make_embedder() (needs VOYAGE_API_KEY), make_reranker().
├── search/           The retrieval index, behind interfaces.
│   ├── models.py     DocumentMeta, Chunk (header, text, location, town/nc/trade/entity_ids, vector; fts_text),
│   │                 SearchFilter (doc_ids, doc_type, policy_id, status, source_system, category, town, nc,
│   │                 trade, entity_ids, in_force_on), SearchHit, EntityRecord, MemoryItem.
│   ├── store.py      SearchStore protocol: replace_document, documents, set_lifecycle, chunks, get_chunk,
│   │                 search (hybrid, pre-filtered); replace_entities, find_entities;
│   │                 put/get/delete/search_memory.
│   ├── lance.py      LanceSearchStore: chunks, entities and memory tables. FTS index plus cosine vectors,
│   │                 LinearCombinationReranker, filters turned into SQL with prefilter=True, optimize().
│   ├── embed.py      Embedder protocol; VoyageEmbedder (REST over httpx2, batches of 64, document/query input
│   │                 types); HashingEmbedder (deterministic, offline, for tests).
│   └── rerank.py     Reranker protocol; CrossEncoderReranker (fastembed ONNX, runs locally);
│                     Searcher (embed the query, hybrid-search the store, rerank, top k).
└── ingest/           `plg sync`.
    ├── sources.py    DocumentSource protocol, SourceDocument, Skipped; SharePointSource, LotusNotesSource;
    │                 generator_artefact() keeps `_master/` and other `_*` paths out.
    ├── extract.py    Format → Blocks (headings and body) plus control fields: DOCX (heading styles and tables),
    │                 PDF (per page, letterheads and page numbers removed, numbered and ID-style headings),
    │                 PPTX (per slide, tables, speaker notes), EML (headers, body, attachment names, disclaimer
    │                 dropped), Markdown, TXT.
    ├── chunking.py   Body text grouped under its heading trail; sections over 1800 chars split at line breaks;
    │                 location string (section path, page or slide).
    ├── metadata.py   doc_type_for (plg:document_types notations), parse_date, control_meta (policy_id, version,
    │                 effective period), lifecycle (current/superseded from version order), EntityTagger and
    │                 load_entity_spine (PLG Records plus trade vocabulary → EntityRecords).
    └── sync.py       sync(): hash → extract → chunk → tag → embed → replace_document; then lifecycle updates,
                      entities refresh, optimize. Returns a SyncReport (added, updated, unchanged, skipped,
                      superseded, chunks_written).

tests/
├── conftest.py                   + session-wide synced poc-data index (CountingEmbedder, run_sync via CLI).
├── test_search_store_contract.py SearchStore contract, run over every backend in STORES (LanceDB today).
├── test_sync.py                  `plg sync`: corpus coverage against _manifest.csv, policy lifecycle, headers and
│                                 metadata, entities, _master exclusion, incremental and --full behaviour.
├── test_search.py                Hybrid search plus the cross-encoder, on questions from _report.md §5.
└── test_voyage_embedder.py       VoyageEmbedder against a fake endpoint.

.github/workflows/ci.yml          + cache .plg/models (cross-encoder) in the api job.
pyproject.toml                    + lancedb, fastembed, python-docx, pypdf, python-pptx; mypy ignores for untyped libs.
```

## Flow

```
plg sync → SharePointSource + LotusNotesSource → (skip if content hash unchanged) → extract → sections/split
        → contextual header + EntityTagger → Embedder.embed_documents → SearchStore.replace_document
        → lifecycle() → set_lifecycle (mark superseded) → replace_entities → optimize

Searcher.search(q, filters) → Embedder.embed_query → SearchStore.search (pre-filter, FTS + vector, linear
        combination, top 50) → Reranker (cross-encoder) → top k SearchHits
```

## Open points (from the code review)

- **Removed documents stay indexed.** A document removed from its source keeps its chunks as `current`. So does a
  changed file that no longer yields any text.
- **The search tests use the network once.** `test_search.py` downloads the cross-encoder model on a cold cache,
  which conflicts with the "tests never hit the network" rule. Options: use a fake reranker by default and make
  the real one an opt-in test.
- **`plg search` has no CLI test.**
- **`lifecycle()` ignores each document's own Status field.** Two copies of the same version would compete to be
  current.
- **Small cleanups:**
  - the store is built the same way in two CLI commands;
  - `optimize()` is called around the `SearchStore` protocol instead of through it;
  - the memory namespace is joined with "/" and split again, so a namespace containing "/" breaks.
- **Not in this ticket:** checking emails for prompt injection at ingestion; reading image-only scans with Claude
  PDF input; filling `category` (the `categorise` job).
