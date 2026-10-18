## Rules

- **Never refer to `docs/` for any context.** Do not read, search or cite anything under `docs/` to understand the app, its design or its conventions. Use the code, this file and the GitHub issues instead.

## Application map

PLG "Super-Librarian" POC: a LangGraph agent that answers PLG officers' questions, exposed through a CLI (`plg`), an HTTP API (`plg-api`) and a Next.js web app (`web/`) whose BFF proxies to `plg-api`. Python 3.12 managed with `uv` (src layout); TypeScript with npm. Runs locally with no Docker.

```
src/plg/
├── config.py        Settings: model ID per tier (haiku/sonnet/opus), max tokens, SSE heartbeat, API host/port,
│                    records_db (PLG Records SQLite), corpus_dir, search_db (LanceDB, default .plg/lancedb),
│                    Voyage embed model/dim, rerank_backend (voyage|local), Voyage rerank model, local rerank model,
│                    search_candidates, vector_weight.
│                    transcripts_dir (saved scan transcripts, beside search_db).
│                    Every field can be overridden with a PLG_<FIELD> env var (e.g. PLG_MODEL_SONNET).
├── llm.py           LLMClient protocol: the ONLY path to Claude. stream_text (merge's streamed answer) and
│                    complete (one whole reply that may call tools; system/tools passed as blocks with cache marks;
│                    returns AgentTurn = Messages API content blocks + stop_reason; optional max_tokens override; messages may carry
│                    document blocks, e.g. PDF input).
│                    AnthropicLLMClient (real, traced with LangSmith @traceable) and ScriptedLLMClient (test double:
│                    script() for streamed replies, script_turns() for complete() turns, keyed by (node, latest plain-
│                    text user message, or the text block of a block message without tool results); a turn may be a callable of the messages, e.g. to cite a search result it was
│                    shown; `sent` records messages, `requests` system+tools). Turn builders: turn, text, tool_call.
├── identity.py      UserCtx (staff_id, name, title, dept, role) loaded read-only from the `staff` table;
│                    role is derived from the job title (role_for). POC identity, replaced by OIDC later.
├── agents/
│   ├── runtime.py   run_agent(llm, node, system, context, tools, messages, tier): the shared tool-use loop. Loops
│                    while stop_reason == tool_use (max 8 rounds), runs a round's tool calls in parallel, marks system
│                    prompt + tools for prompt caching, returns AgentResult(text with [n] markers, citations).
│                    Tools are read-only `Tool`s; search tools return `Source`s, sent as search_result blocks (one
│                    text block per sentence, citations enabled). Citation = doc_id, chunk_id, title, version,
│                    location, quote, span (offsets into the chunk text). Citations of chunks the run didn't
│                    retrieve are dropped.
│   ├── entities.py  Knowledge agent's graph tools: resolve_entities, entity_context (read-only). Context comes back as
│   │                citable record passages (Chunk doc_type "record", source_system "plg_records", chunk_id `record:<id>`).
│   ├── data.py      The data agent: tools get_definition (glossary version in force on as_of, or `version`, with its SQL
│   │                binding) and run_sql (plan, sql with $as_of, glossary term IDs, as_of; default as_of = semantic layer's
│   │                as_of_default 2026-09-30). Each run_sql leaves a SqlTrace, the last carries the agent's explanation.
│   └── knowledge.py The knowledge agent: search_corpus (+ the entity tools when a GraphStore is given)(query, as_of?, doc_types?). Defaults to current
│                    documents; as_of = in force on that date (superseded versions included). Queries are expanded
│                    with the preferred labels of PLG terms (VocabIndex.find_terms), which are also listed in the
│                    agent's per-run context.
├── data/            Data questions over PLG Records. warehouse.py: Warehouse (DuckDB, SQLite attached READ_ONLY, opened on first
│   │                use, then locked: no external access); run() = check_sql → EXPLAIN dry run → execute (MAX_ROWS), raises
│   │                SqlRejected. sqlcheck.py: check_sql parses with DuckDB json_serialize_sql (SELECT only), rejects several
│   │                statements, table functions, other catalogs, `staff`. semantic.py: SemanticLayer (load_semantic_layer;
│   │                bindings keyed by versioned glossary term, table notes, examples, quality_issues → warnings(sql, result)),
│   │                semantic_errors for `make ontology`. trace.py: SqlTrace (plan, sql, as_of, status ok|rejected, result
│   │                summary, ConceptUsed glossary versions, warnings, explanation).
├── graph/
│   ├── state.py     PLGState (messages = completed exchanges only, question, user, intents, findings, answer) and
│                    PLGGraph. A turn joins `messages` only when merge answers it, so a failed run leaves no trace.
│                    findings fan in by appending; route's empty update resets them each turn.
│   └── build.py     build_graph(llm, retriever): START → route → knowledge (if intended) → merge → END.
│                    route = Haiku, forced `route` tool → intents (knowledge, data; none = merge answers
│                    directly, told not to state PLG facts without sources). knowledge streams `citation` chunks, data
│                    streams `sql_trace` chunks.
│                    merge fuses findings keeping [n] markers; findings with neither a citation nor a successful query (Finding.traced) → fixed NOT_COVERED
│                    answer with no Claude call. merge is the only node that streams tokens. In-memory checkpointer.
├── events.py        Pydantic run events: node (started/finished), token, citation (Citation + index = its [n]), sql_trace (SqlTrace),
│                    done (run_id), error (run_id).
├── runs.py          stream_run(graph, thread_id, message, user?): runs the graph, yields numbered RunEvents,
│                    turns any failure into an error event. Shared by the API and the CLI.
├── ingest/          `plg sync`: DocumentSource mocks (SharePoint, Lotus Notes) over corpus_dir, text extraction,
│                    structure-aware chunking with contextual headers, metadata + entity tagging from PLG Records,
│                    incremental by content hash; superseded versions are marked, never deleted.
│                    scans.py: image-only PDFs (no text layer) are read by Claude PDF input through LLMClient
│                    (node ingest_scan, forced record_transcript tool: title, control fields, text per page); the
│                    Transcript is saved by file hash (TranscriptStore) so unchanged scans, --full rebuilds and the
│                    source viewer (SavedScans, read-only) never call Claude again. Page headings give page locations.
│                    A scan Claude can't read is skipped with a reason. Application-bundle scans stay excluded.
├── search/          SearchStore protocol (store.py) and LanceSearchStore (lance.py): chunks / entities / memory,
│                    hybrid FTS + vector search with metadata pre-filters (SearchFilter). Embedder (Voyage; hashing
│                    embedder for tests). rerank.py: Reranker protocol; VoyageReranker (hosted, falls back to the hybrid order on any error or
│                    unreadable reply), CrossEncoderReranker (local fastembed); make_reranker(settings) picks by rerank_backend;
│                    Searcher (embed → hybrid
│                    → rerank), Retriever protocol, open_searcher(settings) and LazySearcher (opened on first search,
│                    so plg-api starts and prints OpenAPI without the index or VOYAGE_API_KEY).
├── entities/        Entity graph over PLG Records. ids.py (strict ID regexes, find_ids, search_name), model.py (Node/Edge/
│                    GraphData), allow.py (ontology allow-list), csvio.py (Neptune openCypher bulk-load CSVs: nodes_<Label>.csv
│                    + edges.csv), spine.py (deterministic build from the records DB, skips malformed IDs), store.py (GraphStore
│                    protocol: resolve_entities, entity_context(id, hops<=2); EntityContext), cypher.py (matching parameterised
│                    openCypher templates; HUB_LABELS are listed but not walked through), local.py (LocalGraphStore: frozen
│                    networkx, swap()), writer.py (GraphWriter: allow-list validation, delta CSVs under a file lock, swaps in a
│                    new frozen graph; no agent tool reaches it), open.py (open_graph builds the spine on first use; LazyGraph).
│                    Holds entities/relationships only, no aggregates. graph_dir setting (.plg/graph).
├── ontology/        Runtime access to the GENERATED ontology artefacts (GENERATED = generated/ path).
│   ├── vocab.py     VocabIndex (load_vocab): SKOS concepts by scheme (`concepts(scheme, cls)` → generated
│                    model) and synonym/abbreviation lookup `resolve(text)` (LOD → letter of demand + plg:LodTrigger,
│                    ceiling leak → SEP); normalise() is shared with the generator.
│   ├── glossary.py  Glossary (load_glossary): versions/current/in_force(concept, date)/find(id|label|synonym).
│   ├── validate.py  supersedes_errors(terms): glossary chain rules (linear, contiguous dates, one current,
│                    proposals supersede the current version; only v1 may lack effective_from).
│   └── generated/   GENERATED by `make ontology`, committed: models.py (LinkML Pydantic, mypy-ignored),
│                    plg.schema.json (tool I/O), extraction/{supersedes,overrides,applies}.json, allow_list.json
│                    (node labels + typed edges), vocab_index.json, glossary_index.json, semantic_layer.json, ontology_card.md.
├── api/app.py       create_app(settings, llm, searcher): FastAPI. GET /personas, GET /me, POST /threads,
│                    POST /threads/{id}/runs (SSE with heartbeat comments). All but /personas need the
│                    X-PLG-User header (staff ID) → UserCtx, else 401. RunEvent schemas are injected into
│                    the OpenAPI 3.1 document. serve() is the plg-api entry point.
└── cli.py           Typer app: `plg ask <question>` (prints the answer, then its Sources), `plg sync [--full]`,
                     `plg search <query>`, `plg graph build | show <entity>`, `plg serve`, `plg openapi` (prints the OpenAPI JSON, no API key needed),
                     `plg glossary list [--all] | show <term>`. make_llm() builds the real LLMClient.

ontology/            SOURCE of the ontology (semantic.yaml = the semantic layer: SQL bindings per glossary term version, table
                     notes, examples, known data-quality issues; `make ontology` dry-runs every binding): plg.yaml (LinkML, ~25 node classes annotated `node`, ~30 relation
                     slots annotated `edge`, `extracted` for Haiku-extracted edges, `vocabulary` for coded values),
                     vocab/*.yaml (SKOS-style schemes seeded from _master taxonomy/checklists + PLG Records, with
                     hand-curated alt_labels; place_types = NC / void deck), glossary.yaml (versioned GlossaryTerms; never delete, supersede).

tests/               HTTP-seam tests: in-process FastAPI TestClient + ScriptedLLMClient (conftest.py; requests
                     carry USER = X-PLG-User S05; route(llm, question, *intents) scripts the router). The poc-data
                     corpus is synced once per session (hashing embedder) for search and knowledge_api tests
                     (real local cross-encoder; each search costs seconds). test_voyage_reranker.py: VoyageReranker against a fake /rerank endpoint. test_anthropic_client.py runs the real client against a
                     fake Anthropic endpoint. Ontology tests check the committed generated/ artefacts against
                     _master / PLG Records (never re-running the generator, except test_make_ontology's failure case).
scripts/build_ontology.py
                     `make ontology` (Makefile): validates vocab + glossary against the generated models,
                     references, supersedes chains and glossary owners (staff table) BEFORE writing; on any
                     problem lists them, exits 1, writes nothing. --source/--out for testing. Needs dev deps (linkml).
scripts/record_sse_fixtures.py
                     Records real SSE streams (answer with citations, not_covered, error) from the in-process API,
                     with the corpus synced into a temp index, into web/src/test/fixtures/*.sse, plus the source
                     viewer's document + span-location responses per file type into fixtures/documents/*.json.
web/                 Next.js App Router app (presentation only) + BFF route handlers under src/app/api/
                     (Node runtime, no buffering): /api/session (mock sign-in, httpOnly `plg_user` cookie),
                     /api/threads, /api/threads/[id]/runs (forwards X-PLG-User, streams SSE through),
                     /api/documents/[id], /[id]/chunks/[chunkId], /[id]/file (relay of the plg-api document endpoints).
                     Pages: /sign-in, / (Ask screen: streamed answer, node trajectory, citation chips under the
                     answer (expand to read the quoted span; SourceViewer opens the document with the span highlighted), error + Retry).
                     openapi.json + src/lib/api/schema.d.ts are GENERATED (`npm run gen:api`); SSE frames
                     are parsed and zod-validated in src/lib/events.ts. Server-only code in src/lib/server/.
                     Tests: Vitest + RTL + MSW replaying the recorded fixtures.
.github/workflows/ci.yml
                     api job (make ontology + fail on generated/ drift, mypy, pytest) and web job (regen OpenAPI types, fail on drift, typecheck,
                     lint, test, build, bundle credential check).
poc-data/            Synthetic corpus, plg_records.db and _master ground truth (tests/evals only).
.claude/skills/      Project skills (implement, tdd, code-review, post-implement, ...).
```

Flow: browser → BFF `/api/threads/{id}/runs` (adds X-PLG-User from the cookie) → `POST /threads/{id}/runs` (or `plg ask`) → `stream_run` → graph: `route` → `knowledge` (`run_agent` → `search_corpus` → Searcher) → `merge` → `LLMClient.stream_text` → events (node, citation, token, done/error) → stdout / SSE.

### Commands

- Install: `uv sync`
- Tests: `uv run pytest` (single file: `uv run pytest tests/test_runs_api.py`)
- Typecheck: `uv run mypy` (strict)
- Index the corpus (needs VOYAGE_API_KEY): `uv run plg sync [--full]` · check it: `uv run plg search "<query>"`
- Ask: `uv run plg ask "hello"` · Serve: `uv run plg serve` (http://127.0.0.1:8000). Knowledge answers need the index.
- Web (in `web/`): `npm ci` · `npm run dev` (http://localhost:3000) · `npm test` · `npm run typecheck` · `npm run lint`
- After editing anything under `ontology/`: `make ontology` and commit `src/plg/ontology/generated/` (CI fails on drift).
- Glossary: `uv run plg glossary list [--all]` · `uv run plg glossary show <id|label|synonym>`
- After changing any API model: `npm run gen:api` in `web/` and commit the regenerated files (CI fails on drift);
  re-record fixtures with `uv run python scripts/record_sse_fixtures.py` if the SSE stream changed.
- API keys (`ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `LANGSMITH_API_KEY`, ...) live in `.env` at the repo root, loaded by the CLI and `plg-api`.

### Conventions

- Claude is only ever called through `LLMClient`; tests never hit the network and use `ScriptedLLMClient`.
- Test at the HTTP seam and assert on received SSE events, not on internals. Web tests assert on rendered UI
  and BFF responses, with MSW standing in for plg-api.
- The browser never talks to plg-api and holds no credentials: PLG_API_URL is server-only, never NEXT_PUBLIC_*.
- The data agent only runs one read-only SELECT over PLG Records (not `staff`), validated and EXPLAIN-dry-run first; business
  terms use the glossary version in force on the reporting date. The DuckDB `sqlite` extension is downloaded on first use.
- Every claim in a knowledge answer is cited through the Messages API search_result citations; an answer
  with no surviving citation becomes the fixed "not covered" answer. Agent tools are read-only.
- `wrap_anthropic` is not used for streaming: langsmith 0.14.8's stream reducer crashes with anthropic 1.13.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for shchoy/shchoy-hdb-agent-v2, via the `gh` CLI. Read with `gh issue view <n> --comments`, list with `gh issue list --state open`, comment with `gh issue comment <n> --body "..."`, and label with `gh issue edit <n> --add-label "..."`. Issue #1 is the tracking spec; implementation tickets are its children and declare their blockers.
