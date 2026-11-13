## Rules

- **Never refer to `docs/` for any context.** Do not read, search or cite anything under `docs/` to understand the app, its design or its conventions. Use the code, this file and the GitHub issues instead.

## Application map

PLG "Super-Librarian" POC: a LangGraph agent that answers PLG officers' questions, exposed through a CLI (`plg`), an HTTP API (`plg-api`) and a Next.js web app (`web/`) whose BFF proxies to `plg-api`. Python 3.12 managed with `uv` (src layout); TypeScript with npm. Runs locally with no Docker.

```
src/plg/
├── config.py        Settings: model ID per tier (haiku/sonnet/opus), max tokens, SSE heartbeat, API host/port,
│                    records_db (PLG Records SQLite), trackers_db (.plg/trackers.duckdb, Excel trackers), corpus_dir, search_db (LanceDB, default .plg/lancedb),
│                    Voyage embed model/dim, rerank_backend (voyage|local), Voyage rerank model, local rerank model,
│                    search_candidates, vector_weight.
│                    transcripts_dir (saved scan transcripts, beside search_db). threads_db (.plg/threads.sqlite: checkpoints + thread owners),
│                    history_token_threshold / history_keep_messages (when older turns are folded into a summary).
│                    route_min_confidence (0.6: weaker routing labels are dropped; none left → clarifying question).
│                    outbox_dir (.plg/outbox, local Outbox), audit_log (.plg/audit.jsonl, append-only) and iems_dir (.plg/iems, i-EMS mock).
│                    Every field can be overridden with a PLG_<FIELD> env var (e.g. PLG_MODEL_SONNET).
├── llm.py           LLMClient protocol: the ONLY path to Claude. stream_text (merge's streamed answer) and
│                    complete (one whole reply that may call tools; system/tools passed as blocks with cache marks;
│                    returns AgentTurn = Messages API content blocks + stop_reason; optional max_tokens override; messages may carry
│                    document blocks, e.g. PDF input).
│                    AnthropicLLMClient (real, traced with LangSmith @traceable) and ScriptedLLMClient (test double:
│                    script() for streamed replies, script_turns() for complete() turns, keyed by (node, latest plain-
│                    text user message, or the text block of a block message without tool results); a turn may be a callable of the messages, e.g. to cite a search result it was
│                    shown; `sent` records messages, `requests` system+tools). Turn builders: turn, text, tool_call.
├── actions/         Approvals (issue #18). model.py: ProposedAction (stable action_id + version, action_type send_letter|raise_ticket, title,
│   │                payload LetterPayload | TicketPayload (`kind` letter|ticket), preview HTML, approver_roles, proposed_by, status pending|approved|rejected), APPROVER_ROLES (send_letter:
│   │                not analysts; raise_ticket: not analysts or legal), ApprovalDecision (+ approver, approver_role; refusal(action): wrong id/version/not pending, not the
│   │                proposer, role can't approve (reject needs no role)), upsert_actions reducer, pending(). letters.py: propose_letter
│   │                (a draft of the same template revises the thread's pending letter: same ID, version+1), edited (slot edits re-composed
│   │                and PII-checked → next version), unknown_slots. outbox.py: Outbox protocol + LocalOutbox (one JSON per item, id
│   │                `<action_id>-v<version>`, overwrite = idempotent; item(id)). audit.py: AuditLog (JSONL, append-only, one entry per action ID:
│   │                title, thread_id, decision, edits, reason, approver + role, at, run_id, outbox_id, ticket_id; decided_by(staff_id) newest first).
│   │                tickets.py (#20): propose_ticket(Classification → raise_ticket), edit_errors/edited (EDITABLE: category_code (i-EMS only;
│   │                re-routes team/vendor), severity (resets SLA), unit_id, description, feedback_id), to_ticket (ticket_id IEMS-<yymm>-<action id>), preview HTML.
├── defects/         Defect classification (issue #20). taxonomy.py: Taxonomy (load_taxonomy(vocab): the 11 feedback categories with
│   │                team, vendor, default severity, iems flag), SLA_DAYS (Critical 1, High 3, Medium 7, Low 14). classify.py: classify (Haiku,
│   │                node `defect`, forced classify_feedback tool: scored categories + rationale + the feedback text) → resolve: categories
│   │                >= 0.3 are plausible; several → low confidence (capped 0.5) and the most severe wins; severity = category default.
│   │                flow.py: `defect_flow` subgraph classify_feedback (+ a named FB case read from PLG Records) → propose_ticket
│   │                (i-EMS categories only, needs a user; pasted feedback gets a new FB-NEW-… case ID). tickets.py: TicketSystem
│   │                protocol + LocalTicketSystem (one JSON per ticket, overwrite = idempotent; ticket(id), for_feedback(id)).
├── identity.py      UserCtx (staff_id, name, title, dept, role) loaded read-only from the `staff` table;
│                    role is derived from the job title (role_for). POC identity, replaced by OIDC later.
├── agents/
│   ├── runtime.py   run_agent(llm, node, system, context, tools, messages, tier): the shared tool-use loop. Loops
│                    while stop_reason == tool_use (max 8 rounds), runs a round's tool calls in parallel, marks system
│                    prompt + tools for prompt caching, returns AgentResult(text with [n] markers, citations).
│                    Tools are read-only `Tool`s; search tools return `Source`s, sent as search_result blocks (one
│                    text block per sentence, citations enabled). Citation = doc_id, chunk_id, title, version,
│                    location, quote, span (offsets into the chunk text). Citations of chunks the run didn't
│                    retrieve are dropped. A tool may also return plain-text notes next to its Sources (shown, never citable).
│   ├── entities.py  Knowledge agent's graph tools: resolve_entities, entity_context, policy_lineage(policy_id, as_of?) (read-only; lineage is one
│   │                citable passage `lineage:<policy_id>`; on_lineage callback feeds the policy_stance event). Context comes back as
│   │                citable record passages (Chunk doc_type "record", source_system "plg_records", chunk_id `record:<id>`).
│   │                precedent_tool (find_precedents(trade?, nc?, issue?), needs the Retriever): a note per match (what it shares
│   │                with the case, how it differs; no decision text) + each case's compendium page and the emails naming its PC ID
│   │                (search filtered on entity_ids), so precedents are cited to the page or email.
│   ├── data.py      The data agent: tools get_definition (glossary version in force on as_of, or `version`, with its SQL
│   │                binding) and run_sql (plan, sql with $as_of, glossary term IDs, as_of; default as_of = semantic layer's
│   │                as_of_default 2026-09-30). Each run_sql leaves a SqlTrace; the last carries the agent's explanation, which always ends by naming the
│   │                definition versions and effective dates used (with_definitions appends them if the agent left them out).
│   ├── drafting.py  The drafting agent (its draft becomes a proposed send_letter action in the graph): tools get_template, lookup_records (read-only SELECT through the Warehouse) and submit_draft
│   │                (records a Draft; the last submission wins and is stored for download). Unfilled slots are listed with reasons, never
│   │                invented; the draft gets a PII check. Signing officer's email/phone come from `staff`, read directly (the Warehouse blocks it).
│   └── knowledge.py The knowledge agent: search_corpus (+ the entity tools and find_precedents when a GraphStore is given)(query, as_of?, doc_types?). Defaults to current
│                    documents; as_of = in force on that date (superseded versions included). Queries are expanded
│                    with the preferred labels of PLG terms (VocabIndex.find_terms), which are also listed in the
│                    agent's per-run context.
├── data/            Data questions over PLG Records and the Excel trackers. warehouse.py: Warehouse (DuckDB, SQLite attached READ_ONLY,
│   │                trackers_db attached READ_ONLY as catalog `trackers` when present, opened on first use, then locked: no external
│   │                access; `trackers` = loaded Workbooks); run() = check_sql → EXPLAIN dry run → execute (MAX_ROWS), raises
│   │                SqlRejected. sqlcheck.py: check_sql parses with DuckDB json_serialize_sql (SELECT only), rejects several
│   │                statements, table functions, other catalogs, `staff`, `trackers._workbooks`; tracker tables are `trackers.<table>`. semantic.py: SemanticLayer (load_semantic_layer;
│   │                bindings keyed by versioned glossary term, table notes, examples, quality_issues → warnings(sql, result)),
│   │                semantic_errors for `make ontology`. trace.py: SqlTrace (plan, sql, as_of, status ok|rejected, result
│   │                summary: columns, row_count, truncated, every fetched row (<= MAX_ROWS 500, for the CSV export), ConceptUsed glossary versions, warnings, explanation).
│   │                trackers.py: load_trackers(corpus_dir, db) (`plg sync`): every *.xlsx outside `_` folders → typed tables in a fresh
│   │                DuckDB file (replaced atomically) + `_workbooks` catalog (Workbook JSON). Merged multi-row headers → one snake_case
│   │                name per column (reserved words get `_`); title/note rows ("Static check: ...") kept as notes; text dates read
│   │                day-first; same-header tabs combined with a `sheet` column. Formula cells have no cached values: formula columns
│   │                (formula kept, in column names), formula-only rows (TOTAL) and mostly-formula sheets are NOT loaded. describe()
│   │                renders them for the data agent's system prompt (which says to compute formulas in SQL, rounding ratios before thresholds).
├── drafting/        Letter drafting from approved templates. templates.py (TemplateLibrary: the approved `docs/TPL-*.docx` of corpus_dir; slots
│   │                `{{ name }}`, [guidance] dropped, wording never changed), render.py (fill → paragraphs; open slots show as «slot»; to_html
│   │                escapes everything; to_docx reuses the template file, open slots highlighted), pii.py (NRIC/FIN, non-officer phone/email,
│   │                tenant names in replies to the public; findings point at slots, never repeat values), model.py (Draft, UnfilledSlot,
│   │                PiiFinding), store.py (DraftStore: in memory, owner-checked), compose.py (slot values →
│   │                Draft + DOCX; shared by submit_draft and approval edits). Drafting sends nothing: sending is a ProposedAction (actions/).
├── graph/
│   ├── state.py     PLGState (messages = completed exchanges only, question, user, intents, findings, answer) and
│                    PLGGraph. A turn joins `messages` only when merge answers it, so a failed run leaves no trace.
│                    findings fan in by appending; route's empty update resets them each turn. `clarification` = route's question back (reset each turn). `memory` = this turn's labelled notes block.
│                    proposed_actions (upserted by action ID), decision (what `approval` received). RUN_ID = configurable key carrying the run_id to nodes.
│   ├── summary.py   summarise_history: fold(llm, older messages, previous summary) (Haiku, node summarise_history); entity IDs missing from the reply are re-appended verbatim.
│   └── build.py     build_graph(llm, retriever, ..., *, warehouse, checkpointer?, settings?, memory?): START → (summarise_history if history > threshold) → load_memory → route → knowledge, data, drafting and/or defect (if intended) → merge → write_memory → (any pending action: approval → execute_action, looping while some are pending) → END
│                    (load_memory/write_memory only when a MemoryService is given: plg-api yes, `plg ask` no). The memory block is appended to merge's system prompt.
│                    route = Haiku, forced `route` tool → scored intents [{intent, confidence}] (knowledge, data, drafting, defect) + optional
│                    clarifying_question (RouteDecision). Labels below route_min_confidence are dropped; if none is left but some were
│                    named (or a question was given), `clarification` is set: no fan-out, merge streams it word by word with no Claude
│                    call, and it joins `messages` so the officer's reply is routed with it. Otherwise fan_out sends one
│                    Send(intent, state) per intent (run in parallel); none = merge answers directly, told not to state PLG facts without sources. knowledge streams `citation` chunks, data
│                    streams `sql_trace` chunks.
│                    merge fuses findings keeping [n] markers (with 2+ supported findings, cited or traced, in one `## ` section per part); findings with neither a citation nor a successful query (Finding.traced) → fixed NOT_COVERED
│                    answer with no Claude call. merge is the only node that streams tokens. Checkpointer: InMemorySaver by default (CLI); plg-api swaps in AsyncSqliteSaver (threads_db) in its lifespan. State keeps the full `messages` plus `summary`/`summarised` (offset folded).
│                    drafting_node turns its draft into a ProposedAction (letters.propose_letter). defect_node runs the `defect_flow` subgraph (ainvoke: its
│                    custom writes don't reach the parent stream), streams `classification`, its finding is traced, its ticket is a raise_ticket action. approval = LangGraph interrupt() carrying every pending
│                    action (JSON list); the resume value is an ApprovalDecision, re-checked (refusal) before execute_action, the only side-effecting
│                    node: approve/edit → Outbox item for a letter (edit = re-composed next version) or i-EMS ticket via TicketSystem, every decision → one AuditLog entry with the run_id; emits
│                    `action_result`. A new question on an interrupted thread runs afresh and re-interrupts at the end while actions stay pending.
├── memory/          Personal long-term memory (issue #24). store.py: MemoryStore, a LangGraph BaseStore over the LanceDB `memory`
│   │                table (namespace ("memory", staff_id, profile|preference|episode)); typed API remember (PII masked with
│   │                drafting/pii.py patterns; near-duplicates (cosine >= 0.9 or same key) merged; a retired note is never revived),
│   │                items/find/edit/forget (always scoped to one staff ID), seed_profile (from `staff`, provenance "Staff records"),
│   │                recall (active profile + preferences + nearest episodes); episodes expire after 180 days. MemoryView = API shape.
│   │                service.py: MemoryService. context() → labelled <memory> block (private, never a source, policy wins);
│   │                learn_in_background() after a turn: Haiku (node extract_memory, forced record_memory tool) reads only the
│   │                officer's question + verified findings, saves notes and flags `conflicts` (status pending_review, dropped from
│   │                recall); WORKED_ON edges for IDs in the question via a WorkLinker (entities/open.py work_linker → GraphWriter).
│   │                drain() awaits pending writes (plg-api lifespan shutdown). Memory never yields citations.
├── threads.py       ThreadStore (SQLite plg_threads: owner + title; a thread is listed once asked), RunBuffer (every event of a run, follow(after=seq)) and
│                    RunRegistry (latest run per thread, runs as background tasks so they outlive the client; 409 while one is answering).
├── events.py        Pydantic run events: node (started/finished), token, citation (Citation + index = its [n]), sql_trace (SqlTrace), policy_stance (PolicyLineage: card data), classification (Classification),
│                    draft (Draft: html preview, unfilled slots, pii flags), proposed_action (ProposedAction), interrupt (action_id, version,
│                    approver_roles), action_result (action_id, version sent, decision, outbox_id|null, ticket_id|null), done (run_id), error (run_id).
├── runs.py          stream_run(graph, thread_id, message, user?, *, decision?): runs the graph (or resumes it with Command(resume=decision)),
│                    yields numbered RunEvents (an interrupted task → proposed_action + interrupt per pending action), turns any failure into an error event. Shared by the API and the CLI.
├── ingest/          `plg sync`: DocumentSource mocks (SharePoint, Lotus Notes) over corpus_dir, text extraction,
│                    structure-aware chunking with contextual headers, metadata + entity tagging from PLG Records,
│                    incremental by content hash; superseded versions are marked, never deleted.
│                    lineage.py: `plg graph lineage` - Policy/Sop/Circular/Clause/Precedent nodes from index metadata; Haiku (node extract_lineage,
│                    forced record_edges tool built from generated/extraction/*.json) proposes SUPERSEDES/OVERRIDES/APPLIES; an edge is kept only with a
│                    verbatim quote from a chunk of the batch read and known, allowed endpoints; written via GraphWriter. Idempotent.
│                    Precedent nodes are parsed deterministically from the compendium chunks (decided_on, category, town, facts,
│                    decision, reasoning, outcome, chunk_id, location) with CONCERNS_TRADE / IN_NC edges from the chunk tags.
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
│                    new frozen graph; no agent tool reaches it; memory's write_memory adds WORKED_ON staff → entity edges), open.py (open_graph builds the spine on first use; LazyGraph).
│                    Holds entities/relationships only, no aggregates. graph_dir setting (.plg/graph).
│                    policy.py: PolicyLineage (versions with effective dates, supersessions, circular overrides with scope + evidence) and
│                    build_lineage; GraphStore.policy_lineage(policy_id, as_of?) + cypher POLICY_* templates (LocalGraphStore scans in memory).
│                    Edge.props (scalars, typed CSV columns) carry evidence_chunk_id / evidence_quote / scope on extracted edges.
│                    precedent.py: Precedent / PrecedentMatch (case fields + matched_on trade|nc|issue|town), rank_precedents (shared by
│                    both stores: trade, NC, issue weigh 2, same town 1 as tie-break; issue = word overlap with the case category);
│                    GraphStore.find_precedents(trade?, nc?, issue?, limit) resolves names, cypher FIND_PRECEDENTS + NC_TOWN.
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
├── api/app.py       create_app(settings, llm, searcher): FastAPI. GET /personas, GET /me, POST /threads, GET /threads (own only), GET /threads/{id} (history, summary, `running` question),
│                    POST /threads/{id}/runs (SSE with heartbeat comments; 409 if still answering), GET /threads/{id}/runs/latest (SSE replay after Last-Event-ID); other users' threads are 404, GET /drafts/{id}/file (DOCX; owner only, else 404). All but /personas need the
│                    X-PLG-User header (staff ID) → UserCtx, else 401. RunEvent schemas are injected into
│                    the OpenAPI 3.1 document. serve() is the plg-api entry point.
│                    GET /memory (own memories, profile seeded on first look), GET/PATCH/DELETE /memory/{id} (PATCH: text and/or status
│                    active|retired; a policy-flagged note can't be set active (409, FlaggedByPolicy): rewording it clears the flag;
│                    other users' memories are 404).
│                    POST /threads/{id}/resume {action_id, version, decision approve|edit|reject, edits?, reason?} (SSE): 404 non-owner, 409 not the
│                    pending action/version (replay), 403 role can't approve/edit, 422 reject without reason / unknown or blanked slot / open slots
│                    left; then RunRegistry.start(decision). GET /approvals?status=pending: own pending actions across threads (PendingApproval =
│                    ProposedAction + thread_id/title), read from checkpoint interrupts so they survive a restart. ThreadView.pending likewise.
│                    GET /audit: own decisions, newest first (AuditRecord = AuditEntry + `sent`: the OutboxItem, `ticket`: the i-EMS Ticket; null when not applicable).
│                    Resume edits for a ticket are validated by tickets.edit_errors (422).
└── cli.py           Typer app: `plg ask <question>` (prints the answer, then its Sources), `plg sync [--full]` (also loads the trackers),
                     `plg search <query>`, `plg graph build | lineage | show <entity>`, `plg serve`, `plg openapi` (prints the OpenAPI JSON, no API key needed),
                     `plg glossary list [--all] | show <term>`, `plg memory list | show | edit | forget --user <staff ID>`. make_llm() builds the real LLMClient.

ontology/            SOURCE of the ontology (semantic.yaml = the semantic layer: SQL bindings per glossary term version, table
                     notes, examples, known data-quality issues; `make ontology` dry-runs every binding): plg.yaml (LinkML, ~25 node classes annotated `node`, ~30 relation
                     slots annotated `edge`, `extracted` for Haiku-extracted edges, `vocabulary` for coded values),
                     vocab/*.yaml (SKOS-style schemes seeded from _master taxonomy/checklists + PLG Records, with
                     hand-curated alt_labels; place_types = NC / void deck), glossary.yaml (versioned GlossaryTerms; never delete, supersede).

tests/               HTTP-seam tests: in-process FastAPI TestClient + ScriptedLLMClient (conftest.py; requests
                     carry USER = X-PLG-User S05; route(llm, question, *intents) scripts the router; make_api gives each test
                     a temp threads_db, graph_dir and HashingEmbedder memory store). `llm.streamed` records merge's system + messages
                     (use it, not `sent[-1]`, which the background extract_memory call can win).
                     make_api also puts outbox_dir/audit_log/iems_dir in tmp_path; test_defect_api.py reads LocalTicketSystem there; Api.resume(thread, decision, headers) returns the SSE stream or the
                     refusal status; test_approvals_api.py reads LocalOutbox/AuditLog there as the observable outcome. The poc-data
                     corpus is synced once per session (hashing embedder) for search and knowledge_api tests
                     (real local cross-encoder; each search costs seconds). That sync also loads the trackers (`trackers_db` fixture);
                     test_trackers_api.py queries them through plg-api (make_api(trackers_db=...); without it there are none). test_voyage_reranker.py: VoyageReranker against a fake /rerank endpoint. test_anthropic_client.py runs the real client against a
                     fake Anthropic endpoint. Ontology tests check the committed generated/ artefacts against
                     _master / PLG Records (never re-running the generator, except test_make_ontology's failure case).
scripts/build_ontology.py
                     `make ontology` (Makefile): validates vocab + glossary against the generated models,
                     references, supersedes chains and glossary owners (staff table) BEFORE writing; on any
                     problem lists them, exits 1, writes nothing. --source/--out for testing. Needs dev deps (linkml).
scripts/record_sse_fixtures.py
                     Records real SSE streams (answer with citations, not_covered, error, draft, policy_stance, data: a rejected then a successful run_sql, multi_part: knowledge + data fused in sections) from the in-process API,
                     with the corpus synced into a temp index (threads, memory, graph, outbox and audit writes in scratch dirs, never .plg/), into web/src/test/fixtures/*.sse, plus the source
                     viewer's document + span-location responses per file type into fixtures/documents/*.json, and the approvals flow (two letters in two
                     threads + a ticket → fixtures/approvals/pending.json, edit.sse, reject.sse, ticket_edit.sse, audit.json), and defect.sse (ambiguous feedback → ELE, low confidence).
web/                 Next.js App Router app (presentation only) + BFF route handlers under src/app/api/
                     (Node runtime, no buffering): /api/session (mock sign-in, httpOnly `plg_user` cookie),
                     /api/threads (POST create, GET list), /api/threads/[id] (history), /api/threads/[id]/runs (forwards X-PLG-User, streams SSE through), /[id]/runs/latest (resume; forwards Last-Event-ID),
                     /api/documents/[id], /[id]/chunks/[chunkId], /[id]/file (relay of the plg-api document endpoints), /api/drafts/[id]/file (DOCX relay),
                     /api/memory (GET list), /api/memory/[id] (PATCH, DELETE), /api/approvals (GET pending), /api/audit (GET),
                     /api/threads/[id]/resume (POST decision, SSE through; refusals relayed). SSE pass-through = relaySse (src/lib/server/plg-api.ts).
                     Pages: /sign-in, /approvals (Approvals inbox, approvals/ApprovalsScreen.tsx: pending actions across threads (letters and i-EMS tickets: TicketCard with classification details, editable category/priority/unit/description/case, 'Approve and raise') with letter preview,
                     open slots, PII flags, editable slots shown as <del>/<ins> diff, approve / send edited / reject with reason, approve+edit
                     hidden for roles that can't send or while open slots are blank; then the result (outbox ID, version sent) and the audit
                     trail (who, role, when, reason, edits, outbox item + letter as sent, run_id)), /memory (Memory screen: list own memories with provenance, edit, forget; flagged notes can only be edited or forgotten), / (Ask screen: Conversations list + New conversation, earlier turns, reconnect via Last-Event-ID (3 tries), refresh recovery via sessionStorage; streamed answer (AnswerText.tsx: split at `## ` headings outside code fences into labelled sections, live and in history), node trajectory, citation chips under the
                     answer (expand to read the quoted span; SourceViewer opens the document with the span highlighted), ClassificationCard under the answer (category, severity, team, vendor, SLA or 'not a maintenance defect', confidence + low-confidence flag, other candidates, rationale), DraftPreview under the answer (sandboxed HTML preview via LetterFrame.tsx, unfilled slots, PII flags, DOCX download), PolicyStanceCard at the top of the Sources panel (current version, struck-through superseded versions, circular overrides with unit scope and evidence), ReasoningPanel under a data answer (collapsible; per sql_trace: plan, as-of date, status, SQL + Copy SQL, rejection reason, glossary definitions used with dates in force (ok queries only), data-quality warnings, result table (first 10 rows) + Export CSV (every row, client-side data: URL, formula-injection guarded), then the explanation), error + Retry).
                     dates.ts: day() / period() / when() date formatting shared by the cards.
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
- The data agent only runs one read-only SELECT over PLG Records (not `staff`) and the Excel trackers (`trackers.<table>`), validated and EXPLAIN-dry-run first; business
  terms use the glossary version in force on the reporting date. The DuckDB `sqlite` extension is downloaded on first use.
- Side effects (letters to the Outbox, tickets to i-EMS via `TicketSystem`) exist only as `ProposedAction`s; `execute_action` runs only after the `approval` interrupt, and no model
  toolset holds a tool that acts. Outbox and audit writes go through the `Outbox` / `AuditLog` adapters.
- Every claim in a knowledge answer is cited through the Messages API search_result citations; an answer
  with no surviving citation becomes the fixed "not covered" answer. Agent tools are read-only.
- `wrap_anthropic` is not used for streaming: langsmith 0.14.8's stream reducer crashes with anthropic 1.13.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for shchoy/shchoy-hdb-agent-v2, via the `gh` CLI. Read with `gh issue view <n> --comments`, list with `gh issue list --state open`, comment with `gh issue comment <n> --body "..."`, and label with `gh issue edit <n> --add-label "..."`. Issue #1 is the tracking spec; implementation tickets are its children and declare their blockers.
