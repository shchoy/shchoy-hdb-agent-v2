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
│                    transcripts_dir (saved scan transcripts, beside search_db). submissions_dir (corpus_dir/pdfs/submissions, property). threads_db (.plg/threads.sqlite: checkpoints + thread owners),
│                    history_token_threshold / history_keep_messages (when older turns are folded into a summary).
│                    route_min_confidence (0.6: weaker routing labels are dropped; none left → clarifying question).
│                    outbox_dir (.plg/outbox, local Outbox), audit_log (.plg/audit.jsonl, append-only) and iems_dir (.plg/iems, i-EMS mock).
│                    tasks_today (2026-09-30, the PLG Records snapshot date the tasks are ranked on).
│                    glossary_changes (.plg/glossary_changes.jsonl: approved glossary changes, append-only).
│                    feedback_log (.plg/feedback.jsonl, append-only), annotation_queue (LangSmith queue for 👎 runs).
│                    categories_file (.plg/categories.json, written by `plg categorise`), category_min_size (3: HDBSCAN min_cluster_size).
│                    audit_reports_dir (.plg/audit, one JSON per `plg audit`), question_log (.plg/questions.jsonl), gap_min_score (0.3, Voyage rerank scale),
│                    audit_max_pairs (40 pairs judged), audit_duplicate_jaccard (0.5), audit_concurrency (4 Opus calls at once).
│                    developers ("S08": comma-separated staff IDs of developer personas → UserCtx.developer, "View trace"; developer_ids).
│                    uploads_dir (.plg/uploads: officers' private libraries + their own LanceDB `index/`), upload_max_bytes (20 MB),
│                    upload_max_files (5 per message), upload_quota_bytes (200 MB per officer) (#103).
│                    Every field can be overridden with a PLG_<FIELD> env var (e.g. PLG_MODEL_SONNET).
├── llm.py           LLMClient protocol: the ONLY path to Claude. stream_text (merge's streamed answer) and
│                    complete (one whole reply that may call tools; system/tools passed as blocks with cache marks;
│                    returns AgentTurn = Messages API content blocks + stop_reason; optional max_tokens override; messages may carry
│                    document blocks, e.g. PDF input).
│                    A forced tool_choice (tool/any) that the model rejects (Sonnet/Opus 5.5: 400) falls back to "auto" + a system line
│                    insisting on the tool, re-asked once on a text reply; the model is remembered so later calls skip the 400.
│                    AnthropicLLMClient (real, wrap_anthropic: each call an `llm` run with node + tier metadata via tracing_context;
│                    untraced streams use a bare client, see Conventions) and ScriptedLLMClient (test double:
│                    script() for streamed replies, script_turns() for complete() turns, keyed by (node, latest plain-
│                    text user message, or the text block of a block message without tool results); a turn may be a callable of the messages, e.g. to cite a search result it was
│                    shown; `sent` records messages, `requests` system+tools). Turn builders: turn, text, tool_call.
├── actions/         Approvals (issue #18). model.py: ProposedAction (stable action_id + version, action_type send_letter|raise_ticket|approve_glossary_term, title,
│   │                payload LetterPayload | TicketPayload | GlossaryPayload (`kind` letter|ticket|glossary), preview HTML, approver_roles, proposed_by, approvers (staff IDs who approve instead
│   │                of the proposer: a glossary change's term owner; deciders(), may_decide(): the proposer can always reject/withdraw), status pending|approved|rejected), APPROVER_ROLES (send_letter:
│   │                not analysts; raise_ticket: not analysts or legal; approve_glossary_term: any role, `approvers` gates it), ApprovalDecision (+ approver, approver_role; refusal(action): wrong id/version/not pending, not a
│   │                decider, not the named approver, role can't approve (reject needs no role)), upsert_actions reducer, pending().
│   │                glossary.py (#25): ChangeRequest; propose_change (term must exist with a current version, start after it, new SQL dry-run; a
│   │                re-ask in the thread revises the pending proposal) → approve_glossary_term with a `proposed` GlossaryVersion v+1, approvers=[owned_by];
│   │                edit_errors/edited (EDITABLE definition, value, effective_from), preview HTML (now vs proposed, binding, owner). letters.py: propose_letter
│   │                (a draft of the same template revises the thread's pending letter: same ID, version+1), edited (slot edits re-composed
│   │                and PII-checked → next version), unknown_slots. outbox.py: Outbox protocol + LocalOutbox (one JSON per item, id
│   │                `<action_id>-v<version>`, overwrite = idempotent; item(id)). audit.py: AuditLog (JSONL, append-only, one entry per action ID:
│   │                title, thread_id, decision, edits, reason, approver + role, at, run_id, outbox_id, ticket_id, term_id; decided_by(staff_id) newest first).
│   │                Curated kinds (#26): approve_team_fact / approve_example (LEADS: director, manager, estate_manager) and approve_sql_example
│   │                (+ analyst); payloads TeamFactPayload / ExamplePayload / SqlExamplePayload (CurationPayload); decided over REST, not an interrupt.
│   │                tickets.py (#20): propose_ticket(Classification → raise_ticket), edit_errors/edited (EDITABLE: category_code (i-EMS only;
│   │                re-routes team/vendor), severity (resets SLA), unit_id, description, feedback_id), to_ticket (ticket_id IEMS-<yymm>-<action id>), preview HTML.
├── defects/         Defect classification (issue #20). taxonomy.py: Taxonomy (load_taxonomy(vocab): the 11 feedback categories with
│   │                team, vendor, default severity, iems flag), SLA_DAYS (Critical 1, High 3, Medium 7, Low 14). classify.py: classify (Haiku,
│   │                node `defect`, forced classify_feedback tool: scored categories + rationale + the feedback text) → resolve: categories
│   │                >= 0.3 are plausible; several → low confidence (capped 0.5) and the most severe wins; severity = category default.
│   │                flow.py: `defect_flow` subgraph classify_feedback (+ a named FB case read from PLG Records) → propose_ticket
│   │                (i-EMS categories only, needs a user; pasted feedback gets a new FB-NEW-… case ID). tickets.py: TicketSystem
│   │                protocol + LocalTicketSystem (one JSON per ticket, overwrite = idempotent; ticket(id), for_feedback(id)).
├── doccheck/        Document completeness check (issue #21). checklists.py: Checklists (load_checklists(vocab): per application
│   │                type, its required documents (code, label, description, mandatory) from plg:application_types +
│   │                plg:submission_document_types). identify.py (NODE "doc_check"): each file by CONTENT: text-layer PDFs by printed title
│   │                (SIGNATURES regexes); scans (no text layer) or unmatched PDFs read by Claude (Sonnet, PDF input, forced record_document:
│   │                document_type, legible, title, text; prompt identify_prompt(app, file) names the file, so tests script per file). Not cached.
│   │                rules.py: Application (from PLG Records) + check(): BIZ vs BIZ2 (assignee) by company name; problems illegible_scan >
│   │                wrong_unit (another unit ID or Blk/#unit address; not for BIZ2/NRIC) > expired (BIZ > 3 months old; INS not in force at
│   │                the new term start (renewal: tenancy end + 1 day) else on submission; LIC/CON lapsed). Line status ok|missing|problem|
│   │                not_submitted. model.py: DocCheck, ChecklistLine, FileCheck, Submission. notice.py: TPL-DOC-02 filled from the check
│   │                (letter_ref left open), submit by +14 days. flow.py: `doc_check_flow` load_application (APP ID in the question; bundle =
│   │                settings.submissions_dir/<APP-ID>/*.pdf) → identify_files (parallel) → check_bundle → propose_notice (incomplete + user);
│   │                submissions() lists applications with a bundle. 3 renewals deviate from the GT by design (KNOWN_GT_DEVIATIONS).
├── tasks/           Top tasks (issue #22). rules.py: Task / RankedTask / TaskDigest; deterministic matrix urgency (overdue 4, due <7 days 3,
│   │                <=30 days 2, later 1) × impact (high 3: safety, S$50k+ at risk or 5+ tenants; medium 2: S$10k+ or 2+ tenants; low 1),
│   │                ties by due date then rent at risk; reasons per task; clamp (DEFAULT_LIMIT 5, MAX_LIMIT 50); load_tasks (records, read-only);
│   │                digest(); render() (plain text: console, file, merge finding); can_view / team (self; directors all; manager/estate_manager
│   │                their dept's non-lead staff). ask.py (NODE "tasks"): whose (full name, staff ID or a possessive unique first name, else the
│   │                asker), how_many ("top N"), NOT_ALLOWED / RATIONALE (asks merge for one sentence per task).
├── audit/           Corpus audit (issue #30, `plg audit`). candidates.py (deterministic, no Claude): Corpus (index documents + chunks),
│   │                MinHash (numpy, word shingles) + LSH bands → duplicate pairs (est. Jaccard >= audit_duplicate_jaccard), confirmed/added by
│   │                document-vector cosine; conflict PairCandidates from chunk similarity + a claim index (same quantity kind, same nearby
│   │                words, different value: days/months/metres/S$/units), lineage (stale_documents: current SOPs naming a PLG-POL whose current
│   │                version starts after them; index metadata only) and records (record_pairs: rent stated for a tenancy ≠ tenancies.monthly_rent →
│   │                chunk vs `record:<TA>` passage); definition_candidates: report/deck chunks naming a glossary concept with a superseded version
│   │                near a number. Copies, superseded docs and other versions of the same policy are never conflict pairs. Thresholds.
│   │                judge.py (Opus, node `audit`, forced tools; opening request text pair_request / duplicate_request / definition_request):
│   │                judge_pair, judge_duplicate, judge_definition; a quote must be a verbatim span of a chunk shown, else the item is dropped
│   │                (AuditReport.dropped); model wording PII-masked. rules.py: check_rules over PLG Records (read-only) + index:
│   │                overlapping_tenancies, two_current_policy_versions, trade_not_allowed (vocab plg:trades allowed_unit_types), duplicate_tenants (BRN).
│   │                questions.py: QuestionLog (append-only JSONL, PII-masked: run_id, question, intents, top_score, not_covered), written by merge
│   │                (plg-api only). gaps.py: find_gaps (not_covered / top_score < gap_min_score / 👎 in the feedback log, joined by run_id; grouped).
│   │                audit.py: run_audit → candidates → judge (semaphore) → CONFLICTS_WITH (non-prevailing → prevailing doc; none for a records side) /
│   │                DUPLICATE_OF (copy → original) between LibraryDocument nodes via GraphWriter (append-only, idempotent) → rules → gaps → save.
│   │                model.py: AuditReport {generated_at, documents, conflicts, duplicates, stale, superseded_definitions, rule_violations, gaps, dropped}
│   │                (Conflict a/b Side, Duplicate, DocRef, StaleDocument, SupersededDefinition, RuleViolation, Gap); saved per run, latest = newest.
├── evals/           Golden datasets and quality evals (issue #31, `plg eval`). golden.py: Golden (stable id `<dataset>-<key>`, question, user
│   │                staff ID, reference, source, gate flag) built from poc-data ground truth: samples() parses _report.md §5 (28 questions);
│   │                DATASETS route (§5 → intents + also_ok, greeting), knowledge (§5 knowledge + C1–C6 questions + key_entities; must_mention),
│   │                data (§5 9/10/11/13 + data_quality_issues: values / total / row_count), drafting (template + expected slot values),
│   │                defect (3 clear feedback.json cases per category + §5 19/20), doc_check (20 bundles; INSURANCE_CORRECTIONS = the 3
│   │                KNOWN_GT_DEVIATIONS renewals expect INS:expired), tasks, glossary (every term version on a day in force), guardrails
│   │                (§5 28 + message attacks + benign controls), audit (CONFLICT_SIDES source-path pairs for C1–C6, §2 DUPLICATE_PAIRS,
│   │                duplicate_tenants rule), e2e (all 28 §5, reference answer). harness.py: Harness(llm, retriever, settings, entities?) builds
│   │                the graph like `plg ask` with scratch threads/outbox/audit/iems dirs, no memory; ask(question, user, route_only?) →
│   │                Outcome (specialists started = intents, answer, citations, sql, drafts, classification, doc_check, tasks, injections,
│   │                proposed, error; route_only stops at the fan-out); audit(store) = run_audit with edges into a graph copy → path pairs.
│   │                evaluators.py: TARGETS (route intent_accuracy .9, knowledge faithfulness .85 (uncited = 0), data execution_accuracy .8,
│   │                drafting slot_accuracy .9, defect macro_f1 .85, doc_check recall .9, audit conflict_recall .8, glossary correctness .9,
│   │                guardrails guarded 1.0, tasks .9, e2e correctness .8); row evaluators + summary ones (macro_f1, doc_check_recall);
│   │                Judge (Opus, node eval_judge, forced `grade` tool: FAITHFULNESS / CORRECTNESS rubrics). runner.py: seed(client, names)
│   │                mirrors datasets into LangSmith `plg-<name>` (example id uuid5 of the golden id: create / update / delete stale);
│   │                run(name, harness, judge, gate?, limit?, client?, label?) → EvalReport (offline loop, or aevaluate experiment with
│   │                metadata: model per tier, rerank backend, git SHA, label) with means vs the target.
├── categories/      Library document categories (issue #29). model.py: Categorisation (categorised_at, categories, uncategorised;
│   │                overlay(documents): live titles/status, docs indexed since → uncategorised), Category (id CAT-<hash of member doc_ids>,
│   │                name, description, summary, documents: CategoryDocument), load_/save_categorisation (atomic JSON). categorise.py
│   │                (`plg categorise`): document vector = normalised mean of chunk vectors; HDBSCAN (min_size; -1 = uncategorised);
│   │                one Haiku call (node categorise, forced name_categories; user message = NAME_REQUEST + listing of titles and
│   │                central excerpts) names/describes/summarises every cluster; writes the file, store.set_category per chunk and
│   │                DocumentCategory nodes + IN_CATEGORY edges from LibraryDocument nodes via GraphWriter (append-only: existing ones
│   │                kept). ask.py (NODE "category_summary", no Claude): match(question) by name words (x2) + description words;
│   │                answer() = summary + documents, or the category list, or NOT_CATEGORISED.
├── feedback/        Answer feedback and curation (issue #26). model.py: AnsweredTurn (run_id, started_at?, message_index, question, intents, answer,
│   │                sql?, flagged, citations: NumberedCitation (Citation + index = its [n], as streamed; removed (#106): the cited upload was deleted since, set by GET /threads/{id}), stances: PolicyLineage (#81: a reopened
│   │                thread's [n] markers open them); kept in graph state `turns`), Feedback + FeedbackLog (JSONL, append-only). langsmith.py: LangSmithFeedback
│   │                (Client or stand-in; none opened without LANGSMITH_API_KEY): send() = create_feedback(run_id, "user_score", score 1/0,
│   │                PII-masked comment/correction; + session_id (project UUID, read_project once) and start_time for a traced turn), async queue() =
│   │                annotation_queues.items.create (SmithDB items API: RUN item with run_id, project_id, start_time; queue found or created by name;
│   │                an untraced turn has no start time → not queued). Best-effort.
│   │                curation.py: proposals(turn, feedback, user, staff, existing): 👍 + ran SQL → approve_sql_example (ID sql-<hash>-<rand>; not
│   │                again while one is pending/approved), 👎 + correction → approve_example, team_fact → approve_team_fact; none for a flagged
│   │                turn; approvers = qualifying staff minus the proposer. Curation: ProposedActions stored in MemoryStore namespace
│   │                ("memory","team","fact"|"example"|"sql") with status pending_review → active (approved) / retired (rejected); decide(),
│   │                edit_errors (EDITABLE per type), sql_examples(question) (data agent few-shot), corrections(question), team_facts(question).
├── guardrails/      Prompt injection (issue #23). injection.py: rule-based (no Claude, user decision) screen(text, marker) → Screening
│   │                (hits: rule override|ai_address|approval_bypass|authority_claim|concealment|prompt_leak|role_change + span = its sentence or
│   │                the whole hidden <!-- --> comment; text with spans replaced by MARKER "[Removed at ingestion: ..." or MESSAGE_MARKER
│   │                "[Removed: ..."), flags_in(text) (rules recorded in an ingestion marker), excerpt, InjectionFlag (source message|document,
│   │                rules, doc_id, title, excerpt), SCREENED_DOC_TYPE "email". Rules are tuned so the corpus and PLG Records flag only the
│   │                planted suspicious_refund_request email; officer questions about approvals/rules must not trip them.
├── uploads/         Officers' private libraries (#103). library.py: UploadLibrary(uploads_dir, embedder, limits): add(owner, filename, bytes)
│   │                → Upload {upload_id `upload-<16 hex>` (= doc_id), filename, title, kind, size, chunks, injection: InjectionFlag?, tables (#105)}
│   │                or UploadRefused(413 size/space (images: 3.75 MB, 5 MB base64), 415 type (.pdf .docx .xlsx .txt .md .eml .png .jpg .jpeg), 422 unreadable /
│   │                not a real image / scan over SCAN_MAX_PAGES 100 / Claude couldn't read it (reason in the detail)); add is async.
│   │                Scans (PDF without a text layer) and images (#104): transcribed by ingest/scans.transcribe (PDF input / vision,
│   │                node ingest_scan; IMAGE_PROMPT for images) once, saved by file hash in <dir>/transcripts (TranscriptStore; one
│   │                asyncio lock per hash, so the same file sent twice at once is read once); view/locate read the saved transcript,
│   │                never Claude; a scan's chunks are located by page ("Page n", p. n), an image's have no pages (kind "image").
│   │                file + upload.json under <dir>/<staff>/<id>/; every block screened (ingest.sync.screened: ingestion
│   │                marker) before chunking; space reserved under a lock so parallel uploads can't overrun it. of(owner), get,
│   │                scope(owner, attached) → UploadScope, rename (#106: upload.json + passages' title/header re-written, vectors kept; LanceUploadIndex.retitle) / delete (#106: index rows first, then folder; the saved transcript too unless another upload is the same file or an upload is in flight), view/file/locate (owner only, blocks screened so spans line up).
│   │                index.py: LanceUploadIndex (own `uploads` table: chunk schema + owner; every read filtered on the owner;
│   │                writes serialised). Chunks: doc_type "upload", source_system "upload". The shared Library index is never written.
│   │                keyword_search(owner, q) (#108; a pre-#108 uploads table gets its keyword indexes once, under the write lock).
│   │                delete(owner, id) (#105: file, passages, tables; under the officer's catalog lock; a failed add is discarded the same way).
│   │                workbooks.py (#105): an .xlsx is cleaned by trackers.read_workbook, every text cell/title/note screened (marker in the
│   │                data itself; rules → Upload.injection), tables renamed apart from the officer's others (`_2`), saved as <id>/tables.duckdb
│   │                + workbook.json; combine() rebuilds <dir>/<staff>/workbooks.duckdb (atomic) after each add/delete; workbooks_db(owner).
│   │                Indexed and shown as its describe() text. The data agent queries it as `uploads.<table>` in that officer's runs only.
├── identity.py      UserCtx (staff_id, name, title, dept, role, developer) loaded read-only from the `staff` table (developer: settings.developer_ids);
│                    role is derived from the job title (role_for). POC identity, replaced by OIDC later.
├── agents/
│   ├── runtime.py   run_agent(llm, node, system, context, tools, messages, tier): the shared tool-use loop. Loops
│                    while stop_reason == tool_use (max 8 rounds), runs a round's tool calls in parallel, marks system
│                    prompt + tools for prompt caching, returns AgentResult(text with [n] markers, citations).
│                    Tools are read-only `Tool`s; search tools return `Source`s, sent as search_result blocks (one
│                    text block per sentence, citations enabled). Citation = doc_id, chunk_id, title, version,
│                    location, quote, span (offsets into the chunk text). Citations of chunks the run didn't
│                    retrieve are dropped. A tool may also return plain-text notes next to its Sources (shown, never citable).
│                    _guarded screens every Source before Claude sees it: a chunk carrying the ingestion marker gets an INJECTION_NOTE
│                    warning; an email chunk still carrying a planted instruction (indexed before #23) is withheld; each flagged doc →
│                    on_injection(InjectionFlag) (knowledge.answer passes it through).
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
│   ├── glossary.py  (#25) glossary_definitions tool (knowledge agent; glossary read per call): every approved version of a term as one citable
│   │                passage `glossary:<concept>` (dates, definition, value, source document + quote, owner). read_change (NODE "glossary", Sonnet,
│   │                forced propose_glossary_change: concept, definition, value?, effective_from?, reason, source?, sql?) → ChangeRequest.
│   └── knowledge.py The knowledge agent: search_corpus (+ glossary_definitions when given the live glossary, + the entity tools and find_precedents when a GraphStore is given)(query, as_of?, doc_types?). Defaults to current
│                    documents; as_of = in force on that date (superseded versions included). Queries are expanded
│                    with the preferred labels of PLG terms (VocabIndex.find_terms), which are also listed in the
│                    agent's per-run context. uploads (UploadScope) / attached (Upload list, named in the context) (#103): searches also
│                    cover the asker's uploads, titled "(Your upload)"; Citation.upload marks them.
├── data/            Data questions over PLG Records and the Excel trackers. warehouse.py: Warehouse (DuckDB, SQLite attached READ_ONLY,
│   │                trackers_db attached READ_ONLY as catalog `trackers` when present; scoped(uploads_db) (#105) = a connection of its own adding one officer's workbooks READ_ONLY as `uploads` (close() after the run); opened on first use, then locked: no external
│   │                access; `trackers` = loaded Workbooks); run() = check_sql → EXPLAIN dry run → execute (MAX_ROWS), raises
│   │                SqlRejected. sqlcheck.py: check_sql parses with DuckDB json_serialize_sql (SELECT only), rejects several
│   │                statements, table functions, other catalogs, `staff`, `trackers._workbooks`; tracker tables are `trackers.<table>`, uploaded workbooks `uploads.<table>` (SCHEMAS). semantic.py: SemanticLayer (load_semantic_layer;
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
│   ├── state.py     PLGState (messages = completed exchanges only, question, user, attachments (#103: upload IDs sent with this question), intents, findings, answer) and
│                    PLGGraph. A turn joins `messages` only when merge answers it, so a failed run leaves no trace.
│                    Finding.stances = the policy stances knowledge read (copied to AnsweredTurn with its numbered citations by merge).
│                    findings fan in by appending (per_turn reducer: an empty update resets, so specialists never send []); screen_input and route reset them each turn.
│                    screened (flags in the officer's message), injections (flagged documents read this turn), proposals (this turn's
│                    actions: merge commits them to proposed_actions only if the turn met no injection). `clarification` = route's question back (reset each turn). `memory` = this turn's labelled notes block.
│                    proposed_actions (upserted by action ID), decision (what `approval` received). turns (AnsweredTurn per answer, appended
│                    by merge with the run_id; Finding.sql = the data finding's last query that ran), for feedback by run ID. RUN_ID = configurable key carrying the run_id to nodes; RUN_STARTED = a traced run's root start time (→ AnsweredTurn.started_at).
│   ├── summary.py   summarise_history: fold(llm, older messages, previous summary) (Haiku, node summarise_history); entity IDs missing from the reply are re-appended verbatim.
│   └── build.py     build_graph(llm, retriever, ..., *, warehouse, checkpointer?, settings?, memory?): START → screen_input (flagged message → merge:
│                    fixed MESSAGE_FLAGGED, no Claude; streams `injection`; history gets the redacted message) → (summarise_history if history > threshold) → load_memory → route → knowledge, data, drafting, defect, doc_check and/or tasks (if intended) → merge → write_memory → (any pending action: approval → execute_action, looping while some are pending) → END
│                    (load_memory/write_memory only when a MemoryService is given: plg-api yes, `plg ask` no). The memory block is appended to merge's system prompt.
│                    route = Haiku, forced `route` tool → scored intents [{intent, confidence}] (knowledge, data, drafting, defect, doc_check, tasks, glossary, category_summary) + optional
│                    clarifying_question (RouteDecision). Labels below route_min_confidence are dropped; if none is left but some were
│                    named (or a question was given), `clarification` is set: no fan-out, merge streams it word by word with no Claude
│                    call, and it joins `messages` so the officer's reply is routed with it. Otherwise fan_out sends one
│                    Send(intent, state) per intent (run in parallel); none = merge answers directly, told not to state PLG facts without sources. knowledge streams `citation` chunks, data
│                    streams `sql_trace` chunks.
│                    A turn whose knowledge run read a flagged document: knowledge streams `injection` once per doc, merge opens with
│                    DOCUMENT_FLAGGED (+ WITHHELD when proposals were dropped), adds MERGE_INJECTION to its system prompt, commits no
│                    proposals; write_memory learns nothing from a flagged turn.
│                    merge fuses findings keeping [n] markers (with 2+ supported findings, cited or traced, in one `## ` section per part); findings with neither a citation nor a successful query (Finding.traced) → fixed NOT_COVERED
│                    answer with no Claude call. merge is the only node that streams tokens. Checkpointer: InMemorySaver by default (CLI); plg-api swaps in AsyncSqliteSaver (threads_db) in its lifespan. State keeps the full `messages` plus `summary`/`summarised` (offset folded).
│                    uploads (#103, build_graph(uploads=UploadLibrary)): route adds knowledge (no clarifying question) when files are
│                    attached (data instead for attached workbooks, #105; data_node runs on warehouse.scoped(the asker's workbooks_db)); knowledge_node passes the asker's UploadScope + attached Uploads.
│                    curation (#26): data_node passes approved question → SQL pairs (Curation.sql_examples, best-effort) to data.answer
│                    (`verified`: shown in the per-run context as few-shot examples).
│                    category_summary_node (#29): reads settings.categories_file each run → category_ask.answer, traced finding.
│                    glossary_node (#25): read_change → propose_change over the live glossary (GlossaryChanges overlay); traced finding; proposal = approve_glossary_term.
│                    data and knowledge read the live glossary/semantic layer each run, so an approval takes effect at once. execute_action for
│                    approve_glossary_term: GlossaryChanges.approve (old version superseded, never deleted), action_result/audit carry term_id.
│                    drafting_node turns its draft into a ProposedAction (letters.propose_letter). defect_node runs the `defect_flow` subgraph (ainvoke: its
│                    custom writes don't reach the parent stream), streams `classification`, its finding is traced, its ticket is a raise_ticket action. tasks_node (deterministic, no Claude) ranks the asker's or a named colleague's tasks (role-checked: a refusal is a traced finding, nothing read), streams `tasks`, finding = render() + RATIONALE. doc_check_node runs `doc_check_flow`, streams `doc_check`, its finding is traced; an incomplete bundle's notice is stored (DraftStore), streamed as `draft` and proposed (propose_sending, shared with drafting_node). approval = LangGraph interrupt() carrying every pending
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
│   │                Given a Curation (#26), context() also lists approved team facts and corrected answers nearest the question
│   │                (guidance, never a source). store.put_curated / nearest serve the team namespace.
├── threads.py       ThreadStore (SQLite plg_threads: owner + title + group_id; plg_groups (#100): an officer's flat groups (create/rename/delete_group: members back to Recent; position (#101): groups(staff) in the officer's order, a new one last, reorder_groups(staff, ids) must name each of their groups once, else StaleGroupOrder (one locked transaction); a pre-#101 file gets the column filled from creation order; move(thread, group|None) one atomic UPDATE, GroupNotFound for another's/unknown; an old threads.sqlite gains the column; pins (#102): a `pinned` INTEGER column on plg_threads and plg_groups = the item's place in Pinned, one sequence per officer across both (pin(thread, staff, bool) / pin_group: pinning appends under BEGIN IMMEDIATE, a pinned item keeps its place, unpin = NULL; ThreadNotFound / GroupNotFound; a pinned conversation keeps its group_id; ThreadSummary.pinned / Group.pinned)); a thread is listed once asked; rename (#99: kept by later questions) / delete; all_asked() only for curators' approvals), RunBuffer (every event of a run, follow(after=seq)) and
│                    plg_upload_uses (#106: upload_id × thread_id, record_uses on attach + on an upload citation event; uses(staff) joins live threads, so a deleted conversation drops out and its uploads stay), RunRegistry(tracer?) (start(..., observe?) sees each event; latest run per thread, runs as background tasks so they outlive the client; 409 while one is answering). cancel(thread_id) (#80): only a question
│                    still being answered (RunBuffer.stoppable: not a decision run, merge not yet finished) else NothingToStop; cancels the task,
│                    awaits it; pump then appends a `cancelled` event (the checkpoint holds no turn/proposal, as with a failed run).
├── thread_search.py (#107) Keyword search over the officer's own conversations: SQLite FTS5 table `plg_search` in threads.sqlite
│                    (unicode61; one row per title (message_index NULL) + one per answered turn: question, answer without [n] markers/markdown).
│                    ThreadStore keeps it in step (asked/rename → set_title, delete → drop, index_turns(thread, AnsweredTurns) → set_turns,
│                    search(staff, q)). search(): every word quoted as a prefix ("w"*: FTS operators are plain words), bm25 (title 2, question 1.5,
│                    answer 1), each conversation once at its best turn (title only when no turn matches), LIMIT 20 → ConversationHit {thread_id,
│                    title, updated_at, group_id/group_name, pinned, matched title|question|answer, message_index = the turn's QUESTION index in
│                    ThreadView.messages (None: title), snippet: SnippetPart {text, match} (control-char markers, stripped from indexed text)}.
├── tracing.py       (#27) LangSmith tracing. pii_masker(records_db) (NRIC/FIN, email, phone, tenants.contact_person → "[tenant contact]"),
│                    tracing_client(records_db, **Client kwargs) (langsmith Client with that anonymizer: inputs, outputs, errors, metadata),
│                    git_sha() (PLG_GIT_SHA or git rev-parse HEAD), Tracer(client, project).run(run_id, thread_id, user, channel api|cli, inputs,
│                    extra) → root RunTree `plg_run` (id = the run ID of done/error; tracing_context metadata thread_id/user_id/user_role/
│                    channel/git_sha inherited by every child run), Tracer.url(run_id) (read_project(...).url + /r/<id>, project looked up once).
│                    open_tracer(settings) (None unless LANGSMITH_API_KEY and LANGSMITH_TRACING), install_tracer (also langsmith.configure:
│                    default client for traces outside a run: plg sync scans, lineage). Tools (runtime._call) are @traceable run_type tool,
│                    Searcher.search run_type retriever (hits as documents).
├── events.py        Pydantic run events: node (started/finished), token, citation (NumberedCitation: Citation + index = its [n]; upload: from the asker's private library, #103), sql_trace (SqlTrace), policy_stance (PolicyLineage: card data), classification (Classification), doc_check (DocCheck), tasks (TaskDigest), injection (InjectionFlag),
│                    draft (Draft: html preview, unfilled slots, pii flags), proposed_action (ProposedAction), interrupt (action_id, version,
│                    approver_roles), action_result (action_id, version sent, decision, outbox_id|null, ticket_id|null, term_id|null), done (run_id), error (run_id), cancelled (run_id: stopped by the officer, #80).
├── runs.py          stream_run(graph, thread_id, message, user?, *, decision?, tracer?, channel, run_id?): runs the graph (or resumes it with Command(resume=decision)),
│                    yields numbered RunEvents (an interrupted task → proposed_action + interrupt per pending action), turns any failure into an error event. Shared by the API and the CLI.
│                    With a tracer: one root trace (kind question|resume + action_id/decision; intents added when route finishes; outputs
│                    answer + awaiting_approval, metadata interrupted). The run ID rides in configurable[RUN_ID], not as LangGraph's run_id.
├── ingest/          `plg sync`: DocumentSource mocks (SharePoint, Lotus Notes) over corpus_dir, text extraction,
│                    structure-aware chunking with contextual headers, metadata + entity tagging from PLG Records,
│                    incremental by content hash; superseded versions are marked, never deleted. Schedulable (#28): sync_lock
│                    (one run per index, `<search_db>.sync.lock`, a second run → SyncRunning, exit 1); sync(full=True) re-processes
│                    in place (never drops the index: it holds memory too; re-indexed chunks keep their prior status and category); SyncReport.failed (unreadable doc/scan: run continues,
│                    exit 1) and .missing (indexed docs no source listed: kept, printed `No longer available from its source (kept)`). Emails (doc_type email) are screened
│                    (guardrails.injection) before chunking: planted spans → ingestion marker; SyncReport.flagged, printed `Flagged: ...`.
│                    lineage.py: `plg graph lineage` - Policy/Sop/Circular/Clause/Precedent nodes from index metadata; Haiku (node extract_lineage,
│                    forced record_edges tool built from generated/extraction/*.json) proposes SUPERSEDES/OVERRIDES/APPLIES; an edge is kept only with a
│                    verbatim quote from a chunk of the batch read and known, allowed endpoints; written via GraphWriter. Idempotent.
│                    Precedent nodes are parsed deterministically from the compendium chunks (decided_on, category, town, facts,
│                    decision, reasoning, outcome, chunk_id, location) with CONCERNS_TRADE / IN_NC edges from the chunk tags.
│                    scans.py: image-only PDFs (no text layer) are read by Claude PDF input through LLMClient (transcribe(llm, path):
│                    also PNG/JPEG via vision, shared with uploads #104; media_block; Transcript.parsed(paged=False) for photos)
│                    (node ingest_scan, forced record_transcript tool: title, control fields, text per page); the
│                    Transcript is saved by file hash (TranscriptStore) so unchanged scans, --full re-syncs and the
│                    source viewer (SavedScans, read-only) never call Claude again. Page headings give page locations.
│                    A scan Claude can't read is skipped with a reason. Application-bundle scans stay excluded.
├── search/          SearchStore protocol (store.py; set_lifecycle, set_category, keyword_search) and LanceSearchStore (lance.py): chunks / entities / memory,
│                    hybrid FTS + vector search with metadata pre-filters (SearchFilter); connected with read_consistency_interval=0
│                    so a running plg-api sees a later `plg sync` (another process) without a restart. Embedder (Voyage; hashing
│                    embedder for tests). rerank.py: Reranker protocol; VoyageReranker (hosted, falls back to the hybrid order on any error or
│                    unreadable reply), CrossEncoderReranker (local fastembed); make_reranker(settings) picks by rerank_backend;
│                    Searcher (embed → hybrid
│                    → rerank; given an UploadScope (#103: PrivateIndex + owner + boost doc IDs) the officer's own upload candidates are
│                    reranked together with the Library's, and `boosted` keeps the attached files' best passages in up to half of k), Retriever protocol, open_searcher(settings) and LazySearcher (opened on first search,
│                    so plg-api starts and prints OpenAPI without the index or VOYAGE_API_KEY).
│                    keyword.py (#108, the search dialog's Documents / My uploads; no embedding, no Claude): FTS indexes on `title` and `text`
│                    (2–3 char n-grams, apart from the stemmed `fts_text` one) give candidates (CANDIDATES 500); each word must start a word in the
│                    title or text (checked in Python); DocumentHit {doc_id, chunk_id (best chunk: most words in its text), title, doc_type, version,
│                    status, location, upload, matched title|content, snippet: SnippetPart list, span: MatchSpan in the chunk text (None: title)}; one
│                    per document, current first, then titles naming every word, LIMIT 10. build_indexes in LanceSearchStore.optimize (plg sync)
│                    and after every LanceUploadIndex write; the shared index is never written by plg-api (indexed() false → no documents).
│                    starts / whole / excerpt are shared with items.py.
│                    items.py (#109, the dialog's Approvals / Decisions / Memories; no index, no Claude): matched in Python as read, every word the
│                    start of a word in some field; approvals(q, decidable actions) (title, preview as text) → ApprovalHit, decisions(q,
│                    AuditLog.decided_by) (title, reason, edits, reference = outbox/ticket/term/action ID) → DecisionHit, memories(q, own
│                    MemoryViews) → MemoryHit; hit names the first field matched + its snippet; title matches first, LIMIT 10 per group.
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
│   ├── changes.py   (#25) GlossaryChanges: approved changes (GlossaryChange: new current GlossaryVersion + the superseded previous one with
│   │                effective_to = day before, sql?, action_id, approved_by) appended to settings.glossary_changes; glossary(base) / layer(base)
│   │                overlay them at run time (a change's own SQL binding, else it joins its predecessor's binding); approve() refuses a stale
│   │                predecessor or broken supersedes chain. GlossaryVersion = API mirror of GlossaryTerm (of()/term()).
│   ├── validate.py  supersedes_errors(terms): glossary chain rules (linear, contiguous dates, one current,
│                    proposals supersede the current version; only v1 may lack effective_from).
│   └── generated/   GENERATED by `make ontology`, committed: models.py (LinkML Pydantic, mypy-ignored),
│                    plg.schema.json (tool I/O), extraction/{supersedes,overrides,applies}.json, allow_list.json
│                    (node labels + typed edges), vocab_index.json, glossary_index.json, semantic_layer.json, ontology_card.md.
├── api/app.py       create_app(settings, llm, searcher): FastAPI. GET /personas, GET /me, POST /threads, GET /threads (own only), GET /threads/{id} (history, summary, `running` question), PUT /threads/{id}/group {group_id|null} (#100) → ThreadSummary (404 not your thread / not your group), GET/POST /groups, PUT /groups/order {group_ids} (#101: every one of your groups once, new order → Group list; 409 stale/duplicate/another's), PATCH/DELETE /groups/{id} (#100: Group {group_id, name}; name tidied like a title (`Name` type); DELETE 204, its conversations back to Recent; another officer's group 404), PUT /threads/{id}/pin and PUT /groups/{id}/pin {pinned: bool} (#102) → ThreadSummary / Group (404 not yours), PATCH /threads/{id} {title} (#99: whitespace collapsed, 1–80 chars, else 422) → ThreadSummary, DELETE /threads/{id} (#99: 204; 409 with a reason while answering (RunRegistry.running) or with a pending action; removes the plg_threads row, the run buffer (RunRegistry.forget) and the checkpoint (adelete_thread); audit entries kept; then 404 everywhere),
│                    POST /threads/{id}/runs (SSE with heartbeat comments; 409 if still answering), GET /threads/{id}/runs/latest (SSE replay after Last-Event-ID); other users' threads are 404, GET /drafts/{id}/file (DOCX; owner only, else 404). All but /personas need the
│                    X-PLG-User header (staff ID) → UserCtx, else 401. RunEvent schemas are injected into
│                    the OpenAPI 3.1 document. serve() is the plg-api entry point (uvicorn timeout_keep_alive=KEEP_ALIVE_SECONDS 75, also in scripts/e2e_server.py: longer than the BFF fetch pool's idle timeout, else a pooled connection could meet ECONNRESET → 502).
│                    POST /uploads?filename= (#103; body = the file's bytes, read until over upload_max_bytes → 413) → 201 Upload;
│                    413/415/422 with a detail (UploadLibrary gets create_app's llm for scans/images). GET /uploads: own, newest first. GET /my-documents (#106) → MyDocuments {uploads: MyDocument (Upload + conversations: UploadUse {thread_id, title}), used_bytes, quota_bytes}; PATCH /uploads/{id} (#106) {title: 1–120 chars, tidied} → Upload; DELETE /uploads/{id} (#105/#106): 204 (passages, folder, a workbook's tables, the transcript unless shared), 404 not yours (BFF /api/uploads/[id]). POST /threads/{id}/runs {message, attachments?}: more
│                    than upload_max_files → 422, an ID not yours → 404. /documents/{upload-…}[/file|/chunks/…]: owner only, else 404
│                    (DocumentView.upload). create_app(..., embedder?) (uploads + memory; tests pass HashingEmbedder).
│                    GET /memory (own memories, profile seeded on first look), GET/PATCH/DELETE /memory/{id} (PATCH: text and/or status
│                    active|retired; a policy-flagged note can't be set active (409, FlaggedByPolicy): rewording it clears the flag;
│                    other users' memories are 404).
│                    POST /threads/{id}/runs/latest/cancel (#80, Stop): 204 once stopped (stream ends `cancelled`), 404 non-owner, 409 nothing to stop
│                    (none running, already answered by merge, or a decision run: its side effect and audit entry are never split).
│                    POST /threads/{id}/resume {action_id, version, decision approve|edit|reject, edits?, reason?} (SSE): 404 non-owner, 409 not the
│                    pending action/version (replay), 403 role can't approve/edit, 422 reject without reason / unknown or blanked slot / open slots
│                    left; then RunRegistry.start(decision). GET /approvals?status=pending: pending actions the caller may decide across threads (PendingApproval =
│                    ProposedAction + thread_id/title), read from checkpoint interrupts so they survive a restart. ThreadView.pending likewise.
│                    Curators (#25): a glossary term owner sees changes to their terms proposed in anyone's thread (title "Proposed by <ID>"), and may
│                    resume that thread only to decide (else 404; the thread itself stays 404); their resume stream drops other actions' events.
│                    Glossary resume: 403 not the term owner (the proposer can only reject), 422 bad edits, 409 the term changed since proposed.
│                    GET /categories (#29): Categorisation (saved file overlaid with the index's current documents).
│                    GET /audit/reports/latest (#30): the newest AuditReport (any signed-in user; 404 before the first `plg audit`).
                    GET /submissions: applications with a submission bundle (Submission list, newest first).
│                    GET /tasks/digest?staff_id&limit (TaskDigest; default own; 404 unknown staff, 403 role can't view), GET /tasks/team (UserCtx list the caller may view, self first).
                    GET /search?q= (#107) → SearchResults {conversations: ConversationHit list, documents + uploads (#108): DocumentHit lists from
                    the Library index's keyword_search and the asker's own LanceUploadIndex.keyword_search; approvals / decisions / memories (#109,
                    search/items.py: what the caller's Approvals inbox lists (decidable(), shared with GET /approvals), their own audit entries
                    and their own memories; nothing of another officer's); each best-effort: a failure logs, the rest stand}: no model call. Indexed by
                    index_on_done (RunRegistry.start observe, now async: awaited before `done` is buffered, so a search right after finds the
                    answer; also for resume runs; best-effort) from the checkpoint's turns; a pre-#107 threads.sqlite is back-filled in lifespan.
                    GET /threads/{id}/runs/{run_id}/trace (#27) → TraceLink {url}: 404 not your thread / not one of its answered runs, 403 not a
                    developer, 503 no tracer, 502 LangSmith unreachable. create_app(..., tracer?) (serve() passes install_tracer); feedback reuses its client.
                    POST /feedback (#26) {thread_id, run_id, score up|down, comment, correction, team_fact} → FeedbackReceipt (forwarded,
                    queued, proposals); 404 not your thread / not one of its runs. ThreadView.turns lists answered turns by run ID.
                    GET /curation: pending curated proposals you may decide (curators; the proposer sees their own to withdraw).
                    POST /curation/decide (ResumeRequest body) → decided ProposedAction; 404 not visible, 403 the proposer approving or a
                    role that can't, 409 not the pending version, 422 bad edits / SQL rejected by the dry run; each decision → AuditLog.
                    GET /audit: own decisions, newest first (AuditRecord = AuditEntry + `sent`: the OutboxItem, `ticket`: the i-EMS Ticket; null when not applicable).
│                    Resume edits for a ticket are validated by tickets.edit_errors (422).
└── cli.py           Typer app: `plg ask <question>` (prints the answer, then its Sources), `plg sync [--full]` (also loads the trackers), `plg categorise` (after sync; same index lock), `plg audit` (#30; after sync, same lock; Opus; prints counts + items + report path),
                     `plg eval list | seed [names] | run [names] [--gate] [--limit N] [--offline] [--label X] [--model tier=id]` (#31; run exits 1 below a target; make_eval_client = tracing_client, make_eval_index),
                     `plg search <query>`, `plg graph build | lineage | show <entity>`, `plg serve`, `plg openapi` (prints the OpenAPI JSON, no API key needed),
                     `plg glossary list [--all] | show <term>` (with approved changes), `plg memory list | show | edit | forget --user <staff ID>`,
                     `plg digest [--user S12] [--limit N] [--out file]` (task digest to console or file; no --user = every officer with open tasks; no role check). make_llm() builds the real LLMClient.

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
                     test_guardrail_api.py (#23): ATTACKS (guardrail cases, 100%) / BENIGN controls, redacted history, ingestion screening of the synced
                     corpus (only the planted email), the planted email via knowledge + defect → flagged, no proposed/executed action, and a pre-#23 index chunk withheld.
                     test_feedback_api.py (#26): feedback → FakeLangSmith (create_feedback, annotation queue), proposals, curator visibility/decisions/audit, no self-approval, few-shot SQL in the data agent's prompt, team facts/corrections in merge's memory block (make_api(langsmith=...)).
                     test_glossary_api.py (#25): definitions with citations, propose → owner-only approval → superseded/new version used by get_definition and run_sql, edits, withdraw, stale 409, curator privacy. test_tasks_api.py: ranking, overdue marking (Lucky Star TSK-2026-0452), role checks via GET /tasks/digest (no Claude), the `tasks` event in a conversation and `plg digest`. test_trackers_api.py queries them through plg-api (make_api(trackers_db=...); without it there are none). test_voyage_reranker.py: VoyageReranker against a fake /rerank endpoint. test_sync.py (#28): small corpora (make_corpus) through `plg sync`: incremental, superseded/missing docs kept, --full keeps memory, a store opened before a sync sees it, a failed doc → exit 1, an overlapping sync refused. test_categories_api.py (#29): `plg categorise` over a copy of the synced index (HDBSCAN real, naming scripted: cluster named after its first title) → GET /categories, chunk category + filter, graph IN_CATEGORY, idempotent re-run, category_summary findings. test_evals.py (#31): `plg eval` offline (ScriptedLLMClient, FakeLangSmith datasets API): datasets from the ground truth, idempotent seed, route pass/fail (route-only stop), doc_check recall over 20 bundles, defect macro-F1, the Opus judge request, failed runs never pass. tests/evals/test_quality_gate.py: the regression gate, every dataset's gate subset (not audit) with real Claude over the session's synced index, `@pytest.mark.langsmith(test_suite_name="plg-quality-gate")` (masking client configured), each case must meet its target; skipped unless PLG_EVALS=1 and ANTHROPIC_API_KEY. test_audit_api.py (#30): candidate recall over the synced corpus (C1–C6 + the 3 planted duplicates, SOP-014 stale), `plg audit` with scripted Opus → GET /audit/reports/latest, graph edges, unverified quotes dropped, idempotent, rules, question log + gaps. test_upload_workbooks_api.py (#105): xlsx → `uploads.<table>` queries (merged header, text dates, TOTAL row, formula column computed), described in the data prompt, joins PLG Records, other officer rejected, read-only, `_2` names, delete removes tables, planted cell/note screened, broken file 422. test_my_documents_api.py (#106): listing + space, conversations that attached/cited an upload, rename (also new citations), delete (search, 404s, space, owner only), removed citations in history, a deleted scan's transcript kept while shared, deleting a conversation keeps its uploads. test_uploads_api.py (#103): types (txt/md/docx/pdf/eml), 415/413/422 refusals, per-officer space (also parallel uploads), 5 per message, own uploads only, cited as upload with span located, later searches include uploads, attached boosted, invisible to another officer (search + 404s), shared index unchanged, injection marker + event, masked traces; scans/images (#104): transcribed once (also re-upload, viewer, two at once), page-located citations, >100 pages / fake image / too-large image / broken PDF refused before Claude, unreadable → 422 reason, transcript screened. test_search_items_api.py (#109): pending actions by title and preview, another officer's not found, a term owner finds changes to their term, decisions by reason/edits/what was sent (no longer pending), own memories only, no Claude call. test_search_documents_api.py (#108): content + title matches, current before superseded, every word needed, the span located by the chunk endpoint, uploads owner-only (renamed found, deleted gone), odd queries, no Claude call, a pre-#108 index found only after optimize (plg-api never writes it); make_api defaults search_db to tmp (never .plg/). test_search_conversations_api.py (#107): prefix matches in answers/questions/titles, the matching turn, renamed titles + new answers, group/pin, own only, deleted drops out, operator/punctuation queries, no Claude call, pre-#107 file back-filled on restart. test_pins_api.py (#102): pin order across conversations and groups, re-pin keeps place, unpin keeps the group, delete drops the pin, privacy 404s, restart, pre-#102 DB upgraded. test_groups_api.py (#100): create/rename/delete groups, reorder (#101: stored, new group last, survives restart; 409 for a stale/duplicate/another's order; pre-#101 file keeps creation order), move in/between/out, recency kept, delete returns members to Recent, privacy 404s, restart, pre-#100 threads.sqlite upgraded. test_rename_delete_api.py (#99): rename kept across questions/restart, 422/404, delete → 404 on every endpoint + checkpoint rows gone, audit kept, 409 while answering / pending action, other officer 404. test_cancel_api.py (#80): Stop mid-answer → `cancelled` last, no history, no pending action, next question runs; 404 other user, 409 nothing running; traced root marked cancelled. test_tracing_api.py (#27): conftest LangSmithApi (records posted runs, answers project lookups; .tracer() = plg's masking client)
                     → root metadata, nodes/Send branch/tool children, PII masked, resume + interrupt, trace URL role/ownership, CLI channel. test_anthropic_client.py runs the real client against a
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
                     threads + a ticket → fixtures/approvals/pending.json, edit.sse, reject.sse, ticket_edit.sse, audit.json), and defect.sse (ambiguous feedback → ELE, low confidence), doc_check.sse (APP-2026-0294), doc_check_problem.sse (APP-2026-0288,
                     illegible scan scripted), submissions.json, tasks.sse and tasks/{digest,digest_S06,team}.json (S04; `tasks_api`), injection.sse (flagged message), injection_email.sse (planted email via knowledge), approvals/glossary_{pending.json,approve.sse,audit.json} (`glossary`: S02 proposes, S08 approves), feedback/{thread,receipt_up,receipt_down,curation,decided}.json (`feedback`: S05 rates, S03 curates; a recording LangSmith stand-in), categories.json (`categories`: real categorise over the temp index, naming scripted from titles), audit_report.json (`audit`: run_audit over the temp index, Opus scripted), cancelled.sse (`cancelled`: a slow merge stopped part way, no index). Optional scenario names record only those.
scripts/e2e_server.py
                     plg-api for the Playwright suite (#32): create_app + uvicorn (default :8100) with ReplayingLLMClient (a node's scripted turns
                     restart on its first call of each run, so a question can be asked again) over the corpus synced into a temp index; scratch stores
                     (deleted on exit); scripts: QUESTION + FOLLOW_UP (knowledge, cited), two TPL-REM-01 reminders (Golden Leaf,
                     Hometown), the planted refund email (INBOX_QUESTION). Reuses record_sse_fixtures helpers. Question texts mirror web/e2e/helpers.ts.
web/                 Next.js App Router app (presentation only) + BFF route handlers under src/app/api/
                     (Node runtime, no buffering): /api/session (mock sign-in, httpOnly `plg_user` cookie),
                     /api/threads (POST create, GET list), /api/threads/[id] (GET history, PATCH rename, DELETE; refusals relayed), /api/threads/[id]/group (PUT move), /api/threads/[id]/pin and /api/groups/[id]/pin (PUT, #102; 422 without a boolean `pinned`), /api/groups (GET, POST), /api/groups/order (PUT reorder, #101), /api/groups/[id] (PATCH, DELETE), /api/threads/[id]/runs (forwards X-PLG-User, streams SSE through), /[id]/runs/latest (resume; forwards Last-Event-ID), /[id]/runs/latest/cancel (POST, Stop; refusals relayed),
                     /api/documents/[id], /[id]/chunks/[chunkId], /[id]/file (relay of the plg-api document endpoints), /api/drafts/[id]/file (DOCX relay),
                     /api/uploads (POST streams the file to plg-api /uploads?filename=, GET list; #103), /api/uploads/[id] (PATCH rename, DELETE; #106), /api/my-documents (GET, #106), /api/search (GET ?q=, #107), /api/memory (GET list), /api/submissions (GET), /api/categories (GET, #29), /api/audit/reports/latest (GET, #30), /api/tasks/digest (GET; staff_id, limit), /api/tasks/team (GET), /api/memory/[id] (PATCH, DELETE), /api/approvals (GET pending), /api/audit (GET),
                     /api/threads/[id]/resume (POST decision, SSE through; refusals relayed), /api/feedback (POST), /api/threads/[id]/runs/[runId]/trace (GET: 307 to the plg-api trace URL, http(s) only; refusals relayed), /api/curation (GET),
                     /api/curation/decide (POST). SSE pass-through = relaySse (src/lib/server/plg-api.ts).
                     App shell (#75): every signed-in page lives in the `(shell)` route group, whose layout.tsx (currentUser, else redirect /sign-in)
                     wraps it in shell/AppShell.tsx: a left sidebar with the product name, New conversation, sections (Ask, Approvals, Tasks,
                     Document check, Library, Memory; inline SVG icons in shell/icons.tsx; aria-current on the current one), a red count of
                     /api/approvals (hidden at 0), a Pinned section (#102, hidden when empty; list named "Pinned"): pinned conversations and groups (a pinned group with its unpinned conversations) in pin order; Pin / Unpin in a conversation's menu, Pin group / Unpin group in a group's (menu.ts setPinned), announced, focus on the item's Options in its new place; a pinned conversation shows only there (not draggable; Move to group… still sets where unpinning returns it, announced "… It stays pinned."); a pinned group has no Move up/down and isn't dragged (reorder keeps pinned groups' slots in the order sent), groups from /api/groups (#100, shell/GroupSection.tsx: heading "Groups", one disclosure button per group named "<name>, <n> conversations" with its own Options menu (Rename group, Move up / Move down (#101, the keyboard reorder; announced "Moved group X to position n of m", focus back on Options), Delete group with confirmation: members back to Recent), New group inline field; collapsed state in localStorage via shell/collapsedGroups.ts (useSyncExternalStore); a 404 refreshes the sidebar; shell/menu.ts = shared menu keys, refusalDetail, tidy; ungrouped ones under "Recent conversations", newest first everywhere); drag and drop (#101, AppShell: native HTML5 DnD; rows (conversation, group) are draggable divs carrying menu.ts DRAG_TYPE, never text; the shell tracks what is dragged; a group's <li> and the Recent box are drop zones with data-drop none|available|over (outlined / tinted); a conversation dropped on a group or Recent → menu.ts moveThread (shared with Move to group…), a group dropped on another takes its place → PUT /api/groups/order; a refused drop is a role=alert; a drag never opens a conversation), recent conversations from /api/threads (picking one opens it on Ask; each a shell/ConversationItem.tsx (#99): an Options menu button (aria-haspopup menu: Rename, Move to group… (#100: a menu of menuitemradio groups + No group, current one checked; PUT, announced "Moved X to G|Recent", focus follows the moved item), Delete; arrows/Home/End, Escape back to the button, never closes the drawer) → inline rename field (Enter saves, Escape cancels) or an inline confirm group 'Delete <title>?' (focus on Cancel; danger-solid Delete; plg-api's refusal shown as role=alert); a polite status 'Conversation updates' announces Renamed/Deleted; deleting the open conversation starts a new one), theme toggle (shell/ThemeToggle.tsx, #76), persona + sign-out.
                     Search (#107): a field-shaped "Search" button at the top of the sidebar (⌘K / Ctrl K hint, aria-keyshortcuts) and
                     Ctrl/⌘K anywhere open shell/SearchDialog.tsx (role=dialog aria-modal; rest of the shell inert; from the phone drawer the drawer
                     closes and focus returns to Menu): a combobox "Search" (aria-activedescendant) over one "Search results" listbox of role=group sections
                     Conversations, Documents, My uploads (#108), Approvals, Decisions, Memories (#109; arrows wrap across groups), fetch /api/search debounced
                     120 ms (stale results hidden); an approval or decision opens /approvals?item=<action ID>, a memory /memory?item=<id>
                     (foundParam.ts FOUND_PARAM / foundHref; the server page passes `found` to the screen; found.tsx useFound: that item outlined,
                     "Search match" description, scrolled into view and focused once; AppShell openScreen refocuses it when already there); each option: title, snippet with <mark>, "Pinned[ · group G]" or "In G|Recent", where it matched;
                     arrows wrap, Enter/click opens, Escape/Close/backdrop → focus back to the opener; status "N conversations found" / "No
                     conversations match", failure role=alert. Opening: its group expanded, row scrolled into view (li data-thread-id), current
                     in the sidebar; ConversationControl.open(id, turn) (or sessionStorage plg_active_thread + plg_active_turn (runClient
                     ACTIVE_TURN, cleared once opened) → "/"); AskScreen scrolls to the turn's question <li data-found> ("Search match" label,
                     outlined), focuses it once, stops following the end. A document/upload option (#108: title, vN, warning 'Superseded' Badge,
                     snippet <mark>s, doc type or 'Your upload', location, where it matched) opens shell/SourceDialog.tsx: a modal over the screen
                     (shell inert) holding SourceViewer.tsx OpenedSource (loads at once: chunk located at the hit's span, match highlighted; title
                     match from the top); Escape/backdrop/Close → focus back to where search was opened; Ctrl/⌘K from it reopens search. Refused while the open conversation is answering (announced).
                     Below 48rem it is a drawer (Menu button, role=dialog, focus moved in and trapped, Escape → focus back to Menu; top bar
                     and main inert while open). Screens never repeat the nav. shell/ShellContext.tsx: useShell().refresh() (after a run or a
                     decision: count + conversations), useConversationControl (AskScreen hands the sidebar open/startNew and reports its
                     active/busy thread). Tests render screens inside it with src/test/shell.tsx inShell().
                     Design tokens (globals.css): HDB-inspired palette (teal primary, HDB red for badges/danger only, Bootstrap-style greys)
                     exposed as --color-* roles, plus type (--text-*, --weight-*), spacing, radius and shadow scales; screens' CSS uses only
                     the tokens (the sandboxed letter frame, LetterFrame.tsx, keeps its own: paper-white in both themes). Font: self-hosted Hanken Grotesk
                     (src/app/fonts/HankenGrotesk-Variable.woff2 + OFL licence, next/font/local in layout.tsx → --font-hanken class on <html>; no network).
                     Result cards (#78): src/app/Card.tsx + card.module.css: Card (header = heading h2|h3|h4 (h2: a Library category) + status badges, body; a region
                     named by its heading (as="article" for an item in a screen's list), or role=alert with tone danger), Badge (tone neutral|success|warning|danger, words always; as="strong"),
                     TableScroll (named, focusable, positioned region: tables scroll sideways on a phone; visually hidden cell text stays inside it), tableClass / fieldsClass (card table, dl fields;
                     missing/problem/overdue rows get a red inset accent), cardListClass (a screen's list of cards). Used by ClassificationCard, DocCheckCard, TaskList, DraftPreview,
                     InjectionAlert, PolicyStanceCard and the Approvals / Memory screens (#84). HDB red only for alerts, overdue, problems and
                     destructive buttons (globals.css: button data-variant="danger" outlined opens/does Reject, Withdraw, Forget; "danger-solid" confirms).
                     Dark mode (#76): every --color-* role is light-dark(light, dark) (dark palette --dark-*: teal/red lightened), picked by
                     color-scheme: the OS (prefers-color-scheme) by default; Light/Dark/System radios in the sidebar (ThemeToggle) set
                     <html data-theme> + the plain `plg_theme` cookie (System clears both); the root layout renders data-theme from that
                     cookie (lib/server/theme.ts currentTheme; lib/theme.ts THEME_COOKIE, savedTheme), so first paint is right, no inline
                     script; viewport colorScheme "light dark". src/app/tokens.test.ts: every role has a dark value and every text role meets
                     AA on every background role in both themes. e2e: accessibility.spec.ts runs in light and dark (colorScheme emulated);
                     theme.spec.ts: OS default, toggle + persistence, first paint with JS off.
                     Pages: /library (#29, #85: library/LibraryScreen.tsx: tabs Categories | Audit findings | My documents (#106, library/MyDocuments.tsx: space <meter> 'X of 200 MB used', Upload files (uploads.ts XHR, progress, refusal alert), each upload a Card article (h2 title, type Badge, file, size, date, 'Instructions removed' badge, 'Used in' conversation links via sessionStorage plg_active_thread), Open (DocumentViewer), inline Rename (Enter/Escape, 422 shown), Delete with inline confirm (focus on Cancel); polite status announces; a removed citation in SourcesPanel shows a 'Removed' Badge and no Open source, its marker named '…, removed'; SourceViewer says an upload was deleted on 404) (#30, library/AuditFindings.tsx: every finding a Card article in a cardListClass list under an h2 section with its count; conflicts (danger 'Conflict' badge) with both sides A/B quoted, prevailing side framed green + 'Prevails' badge, resolution; near-duplicates, stale documents, superseded definitions, data rule violations, gaps; 'None found'; 404 → run `plg audit`; document sides open in SourceViewer.tsx QuoteViewer, which locates the quote in the chunk to highlight it); categories from /api/categories as Card articles (h2 = disclosure button + count) with description; expand → summary +
                     documents (shared AuditFindings `Doc` line: type Badge, warning 'Superseded' Badge) opening in DocumentViewer (SourceViewer.tsx: whole document, no highlight); Uncategorised last;
                     not-yet-categorised message), /doc-check (doc-check/DocCheckScreen.tsx, #85: pick an application from /api/submissions (framed TableScroll table; the picked row aria-current + 'Checking…/Checked/Check failed') → new thread + run
                     "Is application <ID> complete? ..." (shared helpers in runClient.ts), DocCheckCard + notice preview + links styled as buttons (Approvals primary) to Approvals and
                     to the conversation; failures a danger alert Card (sessionStorage plg_active_thread)), /tasks (tasks/TasksScreen.tsx: own top tasks via TaskList.tsx; Officer picker when /api/tasks/team has more than one; Show 5/10/20/50 as a wrapping filter bar; 403 as a danger alert Card with 'Show my tasks'), /sign-in, /approvals (Approvals inbox, approvals/ApprovalsScreen.tsx: pending actions across threads as a scannable list (#84: each a Card article whose h3 is a disclosure button opening its detail, kept mounted while closed so typed edits survive; type Badge, conversation (not the curator title "Proposed by <ID>"), Proposed by + age), the detail = approvals/ActionCard.tsx, shared with the chat: ActionCard (no frame/heading of its own: the inbox item or the chat card names it), canDecide, describe, decidedLabel, KIND_LABEL, Proposed (proposer + ago() with the exact time on hover); letters, glossary changes (GlossaryCard: now vs proposed definition/value/effective date, reason, SQL binding, owner; approve/edit only for `approvers`, the proposer can only withdraw) and i-EMS tickets: TicketCard with classification details, editable category/priority/unit/description/case, 'Approve and raise') with letter preview,
                     open slots, PII flags, editable slots shown as <del>/<ins> diff, approve / send edited / reject with reason, approve+edit
                     hidden for roles that can't send or while open slots are blank; then the result (outbox ID, version sent) and the audit
                     trail (cards with type + decision badges: who, role, when, reason, edits, outbox item + letter as sent, run_id)), /memory (Memory screen, section "Your memories": own memories as cards (kind heading, "Not in use" warning badge + amber note when flagged by policy) with provenance, edit (textarea), forget (danger); flagged notes can only be edited or forgotten; memory/CuratorQueue.tsx: pending team facts, corrected answers and SQL examples as cards with Proposed by + age, approve / edit then approve (only for `approvers`) / reject or withdraw with a reason), / (Ask screen, a chat (#77): one scrolling `Conversation` region, each question a right-aligned teal-tint bubble (`data-bubble`, SR prefix "You asked:") above its full-width answer (earlier turns in "Earlier in this conversation", the live one in the `Answer` region); a new conversation (nothing asked, once any saved thread was looked for) shows Welcome.tsx (#79): "Good to see you, <name>" + a `Starter prompts` list of cards, curated STARTERS filtered by the persona's role (AskScreen `user` prop from currentUser) mirroring APPROVER_ROLES: letter + document check need send_letter (not analysts), classify feedback needs raise_ticket (not analysts/legal), analysts get a glossary definition prompt instead; choosing one asks it at once; composer sticky at the window's bottom (#103: paperclip "Attach files" (uploads.ts ACCEPT, incl. .png/.jpg/.jpeg since #104; an image source opens as "Open original image" in a new tab) + dropping files anywhere on the screen (only drags carrying Files; outlined drop target) → Attachments.tsx chips (name, size, XHR progress via uploads.ts, Ready / "Instructions removed" + InjectionAlert / refusal detail as role=alert, "Remove <name>" aborts), at most 5 (MAX_ATTACHMENTS), Ask disabled while uploading; ready uploads go as the run's `attachments`, listed in the live question bubble; an upload's [n] marker is named "…, your upload", the sources panel and SourceViewer show a 'Your upload' Badge) (auto-grows to 12rem then scrolls; Enter sends, Shift+Enter new line; no send while answering; while answering Stop replaces Ask (#80): POST cancel, the `cancelled` event shows the turn as "Stopped." (partial answer dropped, not added to history), composer refocused); the window follows the answer until the officer scrolls up (wheel/touch/PageUp stop it at once; scroll back to the bottom resumes), then "Jump to latest"; while answering one polite role=status line in plain words (DOING: node → "Searching the library…", "Querying PLG Records…"…), after the run a collapsed "Show steps" holding the Trajectory and the ReasoningPanel; the conversation the sidebar opened (or a new one), reconnect via Last-Event-ID (3 tries), refresh recovery via sessionStorage; AnswerActions.tsx (#82): the action bar ending each answer with a run_id (live: `done`; history: ThreadView.turns by message_index), a role=toolbar "Answer actions" (one Tab stop, arrows/Home/End): Copy (copyText.ts answerAsText: markdown dropped, [n] kept, then a "Sources" list; a role=status beside the bar says "Copied" or to copy by hand), 👍 Helpful / 👎 Not helpful (Correct this, Team fact, comment form below the bar; once sent focus moves to Copy), TraceLink.tsx "View trace" (new tab, only when AskScreen's `developer` prop, from currentUser); streamed answer (AnswerText.tsx: split at `## ` headings outside code fences into labelled sections, live and in history; a rehype plugin turns
                     each `[n]` outside code into a CitationMarker button named "[n] <source title>" (n with no known source stays text)), sources panel (#81,
                     SourcesPanel.tsx: opened by a marker or the "Sources (n)" button under the answer, at source n, which takes focus; that answer's
                     policy stances (PolicyStanceCard) on top, then each source: title, version, location, expandable Quote, SourceViewer "Open source" with
                     the span highlighted; Escape (document-level, unless already handled, e.g. the drawer) or Close sources → focus back to the opener;
                     a sticky column beside the conversation from 64rem (never over the composer), a bottom sheet below; live answer: citation/
                     policy_stance events, history: ThreadView.turns citations/stances by message_index), TaskList under the answer (`tasks` event: ranked table, 'Overdue · N days' marker, urgency × impact = score, reasons), DocCheckCard under the answer (✓/✗/– checklist table, problem + reason, files identified, scan marker), ClassificationCard under the answer (category, severity, team, vendor, SLA or 'not a maintenance defect', confidence + low-confidence flag, other candidates, rationale), ApprovalCard.tsx under the answer (#83: one "Awaiting approval" Card per pending action wrapping the embedded ActionCard: live from `proposed_action` events once the run is done, after reload from ThreadView.pending under the last answer; non-deciders see "Sent to approvers: <roles | term owner>"; a decision resumes the thread and the card shows the outcome (outbox/ticket/term ID, version) + shell.refresh() for the sidebar count), DraftPreview under the answer (sandboxed HTML preview via LetterFrame.tsx, unfilled slots, PII flags, DOCX download), PolicyStanceCard at the top of the sources panel (current version, struck-through superseded versions, circular overrides with unit scope and evidence), ReasoningPanel in Show steps for a data answer (collapsible; per sql_trace: plan, as-of date, status, SQL + Copy SQL, rejection reason, glossary definitions used with dates in force (ok queries only), data-quality warnings, result table (first 10 rows) + Export CSV (every row, client-side data: URL, formula-injection guarded), then the explanation), error + Retry; InjectionAlert.tsx: role="alert" above the answer for `injection` events, rule labels, excerpt as plain text).
                     dates.ts: day() / period() / when() / dateOf() (a timestamp's day in SGT) / ago() ("3 h ago", then "on 13 Nov 2026" after a week) shared by the cards.
                     openapi.json + src/lib/api/schema.d.ts are GENERATED (`npm run gen:api`); SSE frames
                     are parsed and zod-validated in src/lib/events.ts. Server-only code in src/lib/server/.
                     Tests: Vitest + RTL + MSW replaying the recorded fixtures.
                     e2e/ (#32, `npm run e2e`, playwright.config.ts: starts scripts/e2e_server.py and `next dev` on :3100 with
                     PLG_NEXT_DIST_DIR=.next-e2e (next.config distDir) beside a developer's dev server; baseURL localhost (dev assets
                     are served to localhost only); one worker: shared server state). helpers.ts: signIn (POST /api/session, retried),
                     visit (goto + networkidle = hydrated), ask, seriousViolations (axe WCAG 2.1 A/AA, serious|critical; iframes off +
                     legacy mode: the sandboxed letter frame can't take axe). journeys.spec.ts: Ctrl+K finds a waiting letter (by its preview), then the officer's decision on it and a memory, each opening its screen at the item, focused (#109); Ctrl+K → 'structurally unsaf' → SOP-011 v1.1 before the superseded v1.0, Enter → source viewer with the match marked; own upload under My uploads, another officer's /api/search never has it (#108); Ctrl+K from Library, type a prefix of a follow-up's answer, arrow + Enter → the conversation open at that turn (focused, data-found), current in the sidebar, Escape → focus back (#107); attach a text file with the paperclip, cited 'Your upload' answer + source opened, another officer 404 (#103); pin a conversation and a group by keyboard, seen pinned in another browser, unpin (#102); drag a conversation into a group (targets highlighted, axe mid-drag, Welcome stays open), drag a group onto another, Move down by keyboard (#101); group a conversation by keyboard (New group, Move to group…, collapse remembered, seen in another browser, delete group → Recent) (#100); rename by keyboard, seen in another browser, then delete (#99); cited answer ([n] marker → sources panel beside the composer, source opened, Escape → marker; reopened answer's markers;
                     phone bottom sheet), approve / reject letters from the chat's approval cards (#83; then none left in /api/approvals), Copy from the answer action bar by keyboard (clipboard text + "Copied"), follow-up, approve /
                     reject letters (+ /api/audit), injection email as inert text, cross-user thread 404s. accessibility.spec.ts: every screen (the search dialog with an approval result and Approvals opened at it (#109); the search dialog with results, also from the phone drawer (#107); the Pinned section with a pinned conversation and group, also in the drawer (#102); conversation groups' new group field, group menu, rename, delete confirmation and Move to group…, also in the drawer (#100); a conversation's Options menu, rename field and delete confirmation, also in the phone drawer; approvals with a letter opened; the inbox + opened letter in edit mode and /memory fit a phone; Library (category opened, audit tab), Tasks and Document check fit a phone).
.github/workflows/ci.yml
                     Runs on pull requests and pushes to main (feature-branch pushes run nothing; workflow_dispatch by hand); a newer push cancels its PR's run.
                     api-checks job (make ontology + fail on generated/ drift, mypy), api job (pytest in 3 parallel groups via pytest-split, balanced by the
                     committed .test_durations), evals job (needs both; PLG_EVALS=1 + ANTHROPIC/LANGSMITH secrets → tests/evals; skipped without the key) and web job (regen OpenAPI types, fail on drift, typecheck,
                     lint, test, build, bundle credential check) and e2e job (#32: Playwright chromium, `npm run e2e -- --shard=n/2` in 2 parallel shards, each with its own servers; split by spec file; report artefact per shard on failure).
poc-data/            Synthetic corpus, plg_records.db and _master ground truth (tests/evals only).
.claude/skills/      Project skills (implement, tdd, code-review, post-implement, ...).
```

Flow: browser → BFF `/api/threads/{id}/runs` (adds X-PLG-User from the cookie) → `POST /threads/{id}/runs` (or `plg ask`) → `stream_run` → graph: `route` → `knowledge` (`run_agent` → `search_corpus` → Searcher) → `merge` → `LLMClient.stream_text` → events (node, citation, token, done/error) → stdout / SSE.

### Commands

- Install: `uv sync`
- Tests: `uv run pytest` (single file: `uv run pytest tests/test_runs_api.py`)
- After adding or reshaping slow tests: `uv run pytest --store-durations` and commit `.test_durations` (balances CI's 3 pytest groups).
- Typecheck: `uv run mypy` (strict)
- Index the corpus (needs VOYAGE_API_KEY): `uv run plg sync [--full]` · check it: `uv run plg search "<query>"`
- Categorise the Library (after a sync; needs ANTHROPIC_API_KEY): `uv run plg categorise`
- Evals (#31): `uv run plg eval list` · `uv run plg eval seed` (LANGSMITH_API_KEY) · `uv run plg eval run route --gate [--offline]` · gate: `PLG_EVALS=1 uv run pytest tests/evals`
- Ask: `uv run plg ask "hello"` · Serve: `uv run plg serve` (http://127.0.0.1:8000). Knowledge answers need the index.
- Web (in `web/`): `npm ci` · `npm run dev` (http://localhost:3000) · `npm test` · `npm run typecheck` · `npm run lint`
- E2E (in `web/`; once: `npx playwright install chromium`): `npm run e2e` (starts plg-api with scripted Claude on :8100 and the web dev server on :3100; reuses running ones locally)
- After editing anything under `ontology/`: `make ontology` and commit `src/plg/ontology/generated/` (CI fails on drift).
- Glossary: `uv run plg glossary list [--all]` · `uv run plg glossary show <id|label|synonym>`
- After changing any API model: `npm run gen:api` in `web/` and commit the regenerated files (CI fails on drift);
  re-record fixtures with `uv run python scripts/record_sse_fixtures.py` if the SSE stream changed.
- API keys (`ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `LANGSMITH_API_KEY`, ...) live in `.env` at the repo root, loaded by the CLI and `plg-api`.

### Conventions

- Claude is only ever called through `LLMClient`; tests never hit the network and use `ScriptedLLMClient`.
- Test at the HTTP seam and assert on received SSE events, not on internals. Web tests assert on rendered UI
  and BFF responses, with MSW standing in for plg-api. Browser e2e tests (web/e2e) drive the real web app and plg-api, with
  only Claude scripted (scripts/e2e_server.py) and assert on what the officer sees, plus BFF responses.
- The browser never talks to plg-api and holds no credentials: PLG_API_URL is server-only, never NEXT_PUBLIC_*.
- The data agent only runs one read-only SELECT over PLG Records (not `staff`) and the Excel trackers (`trackers.<table>`), validated and EXPLAIN-dry-run first; business
  terms use the glossary version in force on the reporting date. The DuckDB `sqlite` extension is downloaded on first use.
- Side effects (letters to the Outbox, tickets to i-EMS via `TicketSystem`) exist only as `ProposedAction`s; `execute_action` runs only after the `approval` interrupt, and no model
  toolset holds a tool that acts. Curated team items from feedback (#26) are `ProposedAction`s too, decided by a curator over `POST /curation/decide` (they change only
  team memory), audited the same way. Feedback sent to LangSmith is telemetry, not an action. Outbox and audit writes go through the `Outbox` / `AuditLog` adapters.
- Every claim in a knowledge answer is cited through the Messages API search_result citations; an answer
  with no surviving citation becomes the fixed "not covered" answer. Agent tools are read-only.
- AnthropicLLMClient uses `wrap_anthropic`, but langsmith 0.14.8's wrapped stream only works through `text_stream` while tracing (untraced it
  looks for a missing run; iterating events crashes on `json_bufs`), so untraced streams use a second, bare SDK client (wrapping is in place).
- Everything uploaded to LangSmith goes through `tracing_client` (PII masked); never open a plain `langsmith.Client` for tracing.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for shchoy/shchoy-hdb-agent-v2, via the `gh` CLI. Read with `gh issue view <n> --comments`, list with `gh issue list --state open`, comment with `gh issue comment <n> --body "..."`, and label with `gh issue edit <n> --add-label "..."`. Issue #1 is the tracking spec; implementation tickets are its children and declare their blockers.
