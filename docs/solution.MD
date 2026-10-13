# PLG "Super-Librarian": Selected Solution (POC)

> Inputs: `docs/REQ.md`, `docs/solutions-options.MD` · Date: 2026-10-13 · Status: Selected

## 1. Decision Summary

| Decision | Selection |
|---|---|
| Orchestration (D1) | **LangGraph `StateGraph` as the AI front door.** It routes each request, fans out to specialists, merges their results, and pauses for human approval. This keeps the topology of Approach B and the deterministic control flow and HITL of Approach C. |
| Agent runtime (D2) | **Native Anthropic Python SDK** inside each specialist. Every specialist is a LangGraph node that runs its own Claude tool-use loop, so native Claude features stay available: Citations, PDF input, structured outputs and prompt caching. |
| Vector store (D5) | **LanceDB (embedded, in-process)** for the POC: keyword (FTS) and vector search with metadata filters, stored in a local folder, with no server. **Amazon OpenSearch Service** is the target, behind the `SearchStore` interface (§2.5). |
| Knowledge graph (D5b, new) | **networkx in-process graph** for the POC, loaded from **CSV files in Neptune's bulk-load format**, with no server and no JVM. **Amazon Neptune** (openCypher) is the target, behind the `GraphStore` interface. It holds the relationships that flat chunks lose: policy supersession and overrides, SOP→policy links, precedent→trade/NC links, and the tenant–tenancy–unit–block–NC–town chain. This adds graph-expanded retrieval, a lighter form of GraphRAG (§2.5). |
| Memory (D21, new) | **Short-term:** a LangGraph checkpointer thread per session, with history summarisation and compact agent results. **Long-term:** a `MemoryStore` (LangGraph `BaseStore` backed by LanceDB) holding each user's profile and past sessions, curated team facts and few-shot examples, plus graph links to the entities each user worked on (§2.6). |
| Ontology (D22, new) | **A lightweight PLG ontology in LinkML (YAML) with a SKOS-style vocabulary**, used at design time. It is the single source from which graph labels and edges, extraction schemas, validation constraints and synonyms are generated. It is also the **single, versioned home of the business glossary** (§2.7.1). There is no triple store or OWL reasoner; the runtime stays a property graph (§2.7). |
| Tracing & evaluation (D20) | **LangSmith**, LangChain's platform for LangGraph. It traces every graph run and every Claude call, holds the golden datasets, and runs offline experiments and online evaluators (§6). |
| Front-end (D23, new) | **A TypeScript web app on Node.js: Next.js (App Router, React) as the UI plus a backend-for-frontend (BFF).** It calls a thin **FastAPI service (`plg serve`)** that wraps the LangGraph graph and streams results over Server-Sent Events. The browser never calls Claude, LanceDB or DuckDB directly. Python stays the only owner of the graph, the tools and the safety boundary. The CLI and notebook remain for jobs, evals and debugging (§2.8). |
| All other choices (D3–D19, except D5) | The ★ recommended option from `solutions-options.MD`, unchanged. |

**Why this blend:** LangGraph owns the parts that must be *deterministic and auditable*: routing edges, workflow steps, the approval interrupt, and checkpointed state. Claude owns the parts that need *judgement*: answering, querying, classifying and drafting. Calling the native SDK, rather than a LangChain chat wrapper, keeps the Citations API and Claude's PDF support available, and the agent loop stays a few dozen lines of transparent code. Only the specialist nodes call Claude, through one `LLMClient` seam. That seam keeps the on-prem open-weight path open if the data is later classified Sensitive-High.

## 2. Architecture

```
 Browser ─► Web front-end (TypeScript · Node.js · Next.js UI + BFF route handlers)          (§2.8)
                 │  HTTPS + SSE (typed client generated from OpenAPI)
                 ▼
            plg-api (FastAPI · `plg serve`): sessions · auth context · stream runs · resume approvals · memory · feedback
                 │  in-process call: graph.astream(...) / Command(resume=...)
                 ▼
                         ┌────────────────────── LangGraph StateGraph (front door) ─────────────────────┐
 Web / CLI / notebook ──►│ screen_input ─► load_memory ─► summarise_history ─► route (Haiku) ─► Send()   │
                         │                                              │                                │
                         │      ┌──────────────┬──────────────┬─────────┴─────┬───────────────────┐     │
                         │      ▼              ▼              ▼               ▼                   ▼     │
                         │  knowledge       data          drafting      defect_flow         doc_check_flow│
                         │  (agent node)    (agent node)  (agent node)  (subgraph)          (subgraph)    │
                         │      │              │              │               │                   │     │
                         │      └──────────────┴──────┬───────┴───────────────┴───────────────────┘     │
                         │                            ▼                                                  │
                         │                     merge / answer (Sonnet) ──► write_memory (async)          │
                         │                                    └─► proposed_actions?                      │
                         │                                                    │ yes                      │
                         │                                     ⏸ interrupt(): human approve / edit / reject│
                         │                                                    ▼                          │
                         │                                     execute_action (deterministic, audited)   │
                         │  Short-term: checkpointer (thread per session) · Long-term: MemoryStore (§2.6)│
                         └───────────────────────────────────────────────────────────────────────────────┘
   Agent node = native Anthropic SDK tool-use loop (read-only tools) ──► LLMClient seam ──► Claude API
   Adapters:  DocumentSource (SharePoint mock, Lotus Notes mock) · TicketSystem (i-EMS mock) · Outbox (mail/letters)
   Stores:    LanceDB (embedded; hybrid FTS + vector: chunks, entities, memory) · networkx graph (in-process, from canonical CSVs)
              → later: Amazon OpenSearch Service · Amazon Neptune (same interfaces)
              DuckDB (ATTACH plg_records.db + Excel sheets, read-only) · templates
   Offline:   sync (incremental) · categorise · corpus_audit · task_digest   (CLI commands, schedulable)
   Observability: LangSmith ◄── traces (graph nodes + wrap_anthropic Claude calls + @traceable tools) · feedback · experiments
```

### 2.1 Graph nodes

| Node | Kind | Model | Responsibility |
|---|---|---|---|
| `screen_input` | deterministic + LLM check | Haiku 5.5 | Screens for prompt injection, attaches user and session context |
| `route` | LLM, structured output | Haiku 5.5 | Classifies intent into one or more of `knowledge`, `data`, `drafting`, `defect`, `doc_check`, `tasks`, `category_summary`. Breaks multi-part questions into sub-tasks. Low confidence leads to a clarifying question. |
| `knowledge` | agent node | Sonnet 5.5 | Hybrid retrieval (LanceDB → OpenSearch) plus graph expansion (networkx → Neptune) over policies, SOPs, emails, precedents and circulars. Answers carry Claude Citations. Uses a "policy stance" format: current position, effective date, superseded versions, sources. |
| `data` | agent node | Sonnet 5.5 (Opus 5.5 for hard analysis) | NL→SQL over DuckDB with the semantic layer. Emits a **plan → SQL → result → explanation** trace (DC6). |
| `drafting` | agent node | Sonnet 5.5 | Selects an approved template, gathers slot values with read-only tools, validates them and renders the document. Sending is never done here; it becomes a `proposed_action`. |
| `defect_flow` | subgraph | Haiku 5.5 | classify (taxonomy, severity, team, confidence, rationale) → build i-EMS payload → `proposed_action` |
| `doc_check_flow` | subgraph | Sonnet 5.5 (PDF) | load application and checklist → identify each submitted document → diff against the checklist → draft missing-documents notice → `proposed_action` |
| `tasks` | deterministic | — (Haiku for the rationale text) | Rules-matrix priority over the `tasks` table, with a short explanation |
| `load_memory` | deterministic + vector search | — | Loads the user profile and the most relevant episodes, team facts and examples from long-term memory (§2.6) |
| `summarise_history` | conditional LLM | Haiku 5.5 | When the thread passes the token limit, compresses older turns into `history_summary`; the last N turns stay verbatim |
| `write_memory` | LLM, structured, runs in the background | Haiku 5.5 | Extracts candidate memories from the turn, deduplicates them, writes user-scoped items, and queues team-scoped items for curation |
| `merge` | LLM | Sonnet 5.5 | Fuses the specialist outputs ("policy says X, data shows Y"), keeping citations and SQL traces |
| `approval` | `interrupt()` | — | Shows each proposed side-effecting action. The human approves, edits or rejects it. The graph resumes from the checkpoint. |
| `execute_action` | deterministic | — | Calls the adapter (`TicketSystem.create`, `Outbox.send`, record update) and writes the audit log |

### 2.2 Safety boundary (D11, enforced in code)

- Specialist agents get **read-only tools only**: search, SQL on a read-only connection, graph lookups through fixed `GraphStore` methods over a **frozen** networkx graph (`nx.freeze`, so any mutation raises; on Neptune, an IAM role limited to `neptune-db:ReadDataViaQuery`), template render to a draft, and record lookup.
- Anything that leaves the system (send email or letter, create an i-EMS ticket, update a record) can only be **returned as a `ProposedAction`** in graph state. Only `execute_action` can perform it, and it is reachable **only through the `approval` interrupt**. The model cannot bypass this, because the tool does not exist in its toolset.
- Input screening covers user text and ingested emails (the corpus contains a planted prompt injection). Drafts get a PII check before approval. All approvals and actions go to the audit log.
- **Web front-end (§2.8):** the UI holds no tools and no model or data credentials. It can only ask a question, or send an approve, edit or reject decision for an `interrupt()` that is already pending. `plg-api` checks that the caller owns the thread, and that an approver has the right role for the action type, before resuming. An approval is accepted only for the exact `ProposedAction` ID and version shown, so an edited or replayed request cannot approve something else. Model output and document text are rendered as sanitised Markdown with no raw HTML, so a planted injection in a source email cannot run script in the browser.

### 2.3 Graph state (sketch)

```python
class PLGState(TypedDict):
    messages: Annotated[list, add_messages]
    user: UserCtx
    intents: list[Intent]                 # from route
    results: Annotated[list[AgentResult], operator.add]   # parallel fan-in
    citations: list[Citation]
    sql_traces: list[SqlTrace]
    proposed_actions: list[ProposedAction]
    approvals: list[ApprovalDecision]
    answer: str | None
    history_summary: str | None           # short-term: compressed older turns
    memory: MemoryContext                 # long-term: loaded by load_memory (profile, episodes, facts, examples)
```

### 2.4 Specialist agent loop (native SDK)

Each agent node calls one shared helper, `run_agent(system, tools, messages, model)`. It loops on `stop_reason == "tool_use"`, runs the read-only tools (in parallel where the model asks for several), uses prompt caching for the system prompt and tool definitions, and returns an `AgentResult` (text, citations, traces, proposed actions). The knowledge agent passes retrieved chunks as `document` content blocks with `citations: {enabled: true}`.

### 2.5 Knowledge stores: embedded locally, AWS later

The POC needs **no Docker, no servers and no JVM**. Everything runs inside the Python process: `pip install` plus local folders (`.plg/lancedb/`, `.plg/graph/`). Amazon OpenSearch Service and Amazon Neptune are the production targets. Agents only see the `SearchStore` and `GraphStore` interfaces, so migrating means a new adapter plus configuration (§2.5.2).

**Search: LanceDB (local) → Amazon OpenSearch Service (target)**

| Table | Contents | Used by |
|---|---|---|
| `chunks` | Structure-aware chunks (D6) with contextual header, text (FTS-indexed), vector, metadata: `doc_id`, `doc_type` (policy, sop, circular, email, precedent, report, template), `policy_id`, `version`, `effective_from/to`, `status` (current/superseded), `town`, `nc`, `trade`, `category`, `entity_ids`, `source_system`, `content_hash` | `knowledge`, `categorise`, `corpus_audit` |
| `entities` | One record per entity (tenant, unit, tenancy, policy, precedent, …) with name variants and its graph node `id` | Entity resolution before graph lookup |
| `memory` | Long-term memory items, namespaced: user profiles, episodes, team facts, few-shot examples (§2.6) | `load_memory`, `write_memory`, few-shot retrieval |

- **Hybrid search:** LanceDB `query_type="hybrid"` (full-text + vector) with a `LinearCombinationReranker`, which normalises and weights the two scores much like OpenSearch's `normalization-processor`, so the tuned weights carry over. Metadata filters are pre-filters in the same call (`.where("status = 'current' AND doc_type = 'precedent'")`). The top-k results are then reranked by a cross-encoder before they reach Claude.
- **Embeddings** are computed client-side through the `Embedder` interface (Voyage AI) and stored as fixed-size vectors. The same vectors can be bulk-copied into OpenSearch `knn_vector` fields at migration, with no re-embedding.
- **Location:** `.plg/lancedb/`, which is git-ignored and rebuilt by `plg sync`. It is kept separate from `poc-data/lancedb/`, which `poc-data/_generator/load_lancedb.py` uses for the structured tables.

**Knowledge graph: networkx (local) → Amazon Neptune (target)**

```
(:Town)<-[:IN_TOWN]-(:NC)<-[:IN_NC]-(:Block)<-[:IN_BLOCK]-(:Unit)<-[:LETS]-(:Tenancy)<-[:HOLDS]-(:Tenant)
(:Tenancy)-[:FOR_TRADE]->(:Trade)            (:Application)-[:FOR_TENANCY|FOR_UNIT]->(...)
(:PolicyVersion)-[:VERSION_OF]->(:Policy)     (:PolicyVersion)-[:SUPERSEDES]->(:PolicyVersion)
(:Circular)-[:OVERRIDES {clause}]->(:Clause)<-[:HAS_CLAUSE]-(:PolicyVersion)
(:SOP)-[:IMPLEMENTS]->(:Policy)               (:PrecedentCase)-[:ABOUT_TRADE|IN_NC|APPLIES]->(...)
(:Document)-[:HAS_CHUNK]->(:Chunk {chunk_id})-[:MENTIONS]->(entity)
(:FeedbackCase)-[:RAISED]->(:IEMSTicket)-[:ROUTED_TO]->(:Team)
(:Document)-[:IN_CATEGORY]->(:Category)       (:Chunk)-[:CONFLICTS_WITH|DUPLICATE_OF {score, run_id}]->(:Chunk)
(:User)-[:WORKED_ON {date, run_id}]->(entity)    # long-term memory links (§2.6)
```

- **What goes in the graph and what stays in DuckDB:** the graph holds entities, relationships and document links. Transactions (invoices, payments) and every count or aggregate stay in DuckDB, which is the source of truth for numbers (DC5/DC6). The graph never answers "how many".
- **Source of truth = canonical CSVs** in Neptune's openCypher bulk-load format (`~id`, `~label`, `~from`, `~to`, typed columns such as `effective_from:DateTime`) under `.plg/graph/`. Locally, `LocalGraphStore` loads them into a `networkx.MultiDiGraph` at startup. The corpus is about 10k nodes and 30k edges, so this takes seconds and under 100 MB. On AWS, the same files go to the Neptune bulk loader from S3.
- **Building the graph at ingestion:** most links are deterministic. The corpus uses strict ID formats (`TA-…`, `U-BV214-01-32`, `PLG-POL-003`, `PC-2024-009`), so regex extraction plus the `plg_records.db` reference tables produce the entity spine. Claude (Haiku, structured output) only extracts relations that need reading, such as `SUPERSEDES`, `OVERRIDES` and `APPLIES`, and each extracted relation keeps its source chunk as evidence. Node labels, edge types, allowed endpoints and the extraction schemas are all **generated from the ontology** (§2.7), so nothing outside the model can enter the graph.
- **Writes:** the `graph_build` job and the background writers (`write_memory` → `WORKED_ON`, `corpus_audit` → `CONFLICTS_WITH`) go through a single `GraphWriter`. It appends to delta CSVs under a file lock and then swaps in a newly frozen graph. Agents only ever hold the frozen, read-only graph.
- **Graph-expanded retrieval (knowledge agent tools):**
  1. `search_documents(query, filters)`: hybrid search through `SearchStore`.
  2. `resolve_entities(text)`: regex IDs plus `entities` table lookup.
  3. `policy_lineage(policy_id)`: follows `SUPERSEDES` and `OVERRIDES` to the current clause. This makes "PLG's current stance" correct by construction: Circular 07/2026 changes the display-area limit from 0.6 m to 1.0 m.
  4. `find_precedents(trade, nc, issue)`: precedents linked to the same trade or NC, plus related cases.
  5. `entity_context(id, hops≤2)`: the neighbourhood of an entity, e.g. a tenant's tenancies, units, open feedback, tickets, and who worked on them.

  Graph results return chunk IDs, and the chunk text is fetched from `SearchStore` and passed to Claude as citable documents. The LLM never writes graph queries; it can only call these fixed methods.
- **Other users of the graph:** `corpus_audit` uses `SUPERSEDES`/`IMPLEMENTS` edges to find stale SOPs (SOP-014 still says 45 days after POL-003 v2.0 moved the LOD to 60) and writes `CONFLICTS_WITH`/`DUPLICATE_OF` edges. `categorise` writes `IN_CATEGORY`. `doc_check_flow` uses `Application → Unit → Tenancy` to catch wrong-unit submissions.

#### 2.5.1 Keeping the local graph Neptune-ready

Locally there is no query language: each `GraphStore` method is written in Python against networkx. To keep the move to Neptune mechanical:

- **One method, two implementations:** every `GraphStore` method has a Python implementation (`LocalGraphStore`) and a matching **parameterised openCypher template** in `graph_store/cypher/<method>.cypher` for `NeptuneGraphStore`. Both are written in the same change.
- **Contract tests:** `tests/graph_contract/` defines inputs and expected outputs for every method, taken from `_master` ground truth such as the POL-003 lineage, the Mutiara precedents and Golden Leaf's context. The same tests run against `LocalGraphStore` in CI and against `NeptuneGraphStore` at migration. Optionally, they can also run against a temporary Neo4j (natively installed) to check the Cypher templates before AWS exists.
- **Neptune-compatible data rules** (checked by a lint test on the CSVs and templates, alongside ontology validation in §2.7):
  - Every node has a string business ID as `~id` (e.g. `TA-2024-00542`); there are no generated IDs.
  - Properties are scalars only: string, integer, float, boolean, datetime. No maps or lists; multi-valued facts become edges.
  - One label per node, and relationship types in `UPPER_SNAKE`.
  - Templates use plain openCypher (`MATCH`, `OPTIONAL MATCH`, `WHERE`, `WITH`, `UNWIND`, `RETURN`, `ORDER BY`, `LIMIT`, bounded variable-length paths `*1..3`), always take `$params`, never call vendor-specific procedures, and return property maps rather than raw node objects.
- **Alternatives considered:** Neo4j or OpenSearch run natively without Docker (each is a JVM of 1–2+ GB). Kùzu (embedded Cypher) was archived in 2025. Memgraph only runs in Docker on macOS.

#### 2.5.2 Migration to AWS (post-POC)

| Step | Search: LanceDB → OpenSearch | Graph: networkx → Neptune |
|---|---|---|
| 1. Provision | Amazon OpenSearch Service domain (2 × `r7g.large.search`) in a VPC | Amazon Neptune Serverless cluster in the same VPC |
| 2. Schema | `plg init-stores --search opensearch` creates the index mappings (`knn_vector`, keyword and date fields) and the hybrid search pipeline | Not needed (Neptune is schemaless and indexes automatically) |
| 3. Data | Export rows and existing vectors from LanceDB and bulk-index them (no re-embedding), or re-run `plg sync` | Upload the canonical CSVs to S3 → Neptune bulk loader |
| 4. Code | `SEARCH_BACKEND=opensearch` selects `OpenSearchStore` (`opensearch-py`, SigV4) | `GRAPH_BACKEND=neptune` selects `NeptuneGraphStore` (openCypher templates over HTTPS, SigV4) |
| 5. Verify | Re-run retrieval evals (§6.2); retune the hybrid weights in the normalization pipeline | Run the graph contract tests + graph and retrieval evals on Neptune |
| 6. Security | Fine-grained access control; IAM roles for ingest (write) and agents (read) | IAM data-access policies: agents get `neptune-db:ReadDataViaQuery` only |

AWS infrastructure (`infra/`, AWS CDK) is deferred until migration and is not part of the 4-week POC.

### 2.6 Memory (D21)

**Short-term memory (within a session)**

| Concern | Mechanism |
|---|---|
| Conversation and graph state | LangGraph checkpointer, one `thread_id` per web, CLI or notebook session (the web UI lists and reopens a user's threads, §2.8). The POC uses `SqliteSaver`; production uses `PostgresSaver` on Amazon Aurora PostgreSQL. Follow-ups ("and for Cendana?") and paused approvals resume from it. |
| Context-window limit | `summarise_history` runs when `messages` exceed a token threshold (e.g. 40k). Older turns are folded into `history_summary`, and the last N turns are kept verbatim. Entity IDs, open `ProposedAction`s and the approval status are always kept verbatim. |
| Specialist output size | Agents return compact `AgentResult`s: the answer, citation spans and the final SQL with its result summary. Full retrieved chunks and full result sets go to the LangSmith trace, not into graph state. |
| Agent scratchpad | The tool-use loop inside `run_agent()` is discarded when the node finishes, so only its result enters shared state. |

**Long-term memory (across sessions)**

A `MemoryStore` implements LangGraph's `BaseStore` interface, so nodes receive it through `store` injection. It is backed by the LanceDB `memory` table (namespace and metadata filters plus vector similarity search), and moves to an OpenSearch index on migration. Each item carries `namespace`, `kind`, `content`, `embedding`, provenance (`thread_id`, LangSmith `run_id`, source turn), `created_by`, `confidence`, `expires_at` and `status` (active, pending_review, retired).

| Kind | Namespace | Example | Written by | Read by |
|---|---|---|---|---|
| **Profile** (semantic, per user) | `("user", uid, "profile")` | "Estate Manager East: BV, CD, PI; prefers tables; default period = current quarter" | Seeded from `staff`, then updated by `write_memory` when the user states a preference | `load_memory` always; used for default filters and output format |
| **Episodes** (per user) | `("user", uid, "episodes")` | "2026-10-12: drafted LOD for Golden Leaf (TA-2024-00542), awaiting approval" | `write_memory`: a one-paragraph summary when a session ends or an action completes | `load_memory`, top-k by similarity, plus anything with an open action |
| **Team facts** (semantic, shared) | `("team", "plg", "facts")` | "'Vacant' means the April 2026 glossary definition" | `write_memory` proposes → **curation** → active | `load_memory`; also proposed as glossary changes through the glossary change process (§2.7.1) |
| **Examples** (procedural, D19) | `("examples", agent)` | A verified question → SQL pair; a 👍 answer pattern | Feedback + curation (§6.1 annotation queue) | `data` and `knowledge` few-shot selection |
| **Entity links** (episodic, graph) | `GraphStore` `(:User)-[:WORKED_ON {date, run_id}]->(entity)` | The user handled Mutiara's change of trade | `write_memory` | `entity_context` ("what did we do last time with this tenant?") |

**Rules**
- **Memory is context, never a source.** It is passed in a clearly labelled block. It can shape defaults, format and which entities to look up, but policy stances and numbers must still come from cited documents and SQL. A memory that conflicts with a current policy loses and is flagged for retirement.
- **Scope and isolation:** user namespaces are readable only by that user. Team facts and examples go live only after a curator approves them, using the same approval interrupt, reviewed with `plg memory review`.
- **Poisoning defence:** memories are only extracted from the user's own turns and the system's verified outputs, never from ingested emails or documents. This matters because the corpus contains a planted prompt injection.
- **Lifecycle:** episodes expire after 180 days, and profiles and facts are reviewed when stale. Near-duplicates are merged (similarity above a threshold → update the existing item instead of adding one). PII is masked before writing.
- **User control:** `plg memory list | show | forget <id> | edit <id>`. Every memory has its provenance, so "why do you think that?" can be answered.

### 2.7 Ontology (D22)

**Scope:** a lightweight, design-time domain model, limited to what the POC's questions and workflows use. It formalises what is otherwise spread across the graph schema, glossary, taxonomy, checklists and document types, so those stay consistent.

**Source:** `ontology/plg.yaml` (LinkML), version-controlled and reviewed like code.

| Part | Contents (POC size) |
|---|---|
| **Classes** (~25) | Place: `Town`, `NeighbourhoodCentre`, `Block`, `Unit` · Party: `Tenant`, `Staff`, `Vendor`, `Team` · Agreement: `Tenancy`, `Application`, `SubmittedDocument` · Governance: `Policy`, `PolicyVersion`, `Clause`, `SOP`, `Circular`, `Template` · Case: `PrecedentCase`, `FeedbackCase`, `IEMSTicket`, `Inspection`, `Task`, `Letter` · Content: `Document`, `Chunk`, `Category` · `User` |
| **Relations** (~30) | `LETS`, `HOLDS`, `IN_BLOCK`, `IN_NC`, `IN_TOWN`, `FOR_TRADE`, `VERSION_OF`, `SUPERSEDES`, `OVERRIDES`, `HAS_CLAUSE`, `IMPLEMENTS`, `APPLIES`, `MENTIONS`, `RAISED`, `ROUTED_TO`, `CONFLICTS_WITH`, `DUPLICATE_OF`, `IN_CATEGORY`, `WORKED_ON`, … each with a **domain → range** and **cardinality** |
| **Enumerations / vocabularies** (SKOS-style) | Trades (25), defect categories (8, with team, vendor and default severity), document types, application types and their required documents, unit statuses, letter types. Each concept has `prefLabel`, `altLabel` (synonyms and abbreviations: "LOD" → *letter of demand*, "void-deck shop" → *commercial unit*, "ceiling leak" → `SEP`) and `broader`/`narrower`. |
| **Business glossary** | Versioned business terms with definitions, sources and effective dates, e.g. `Vacant` ≡ no active tenancy ∧ not under tender ∧ lettable (from April 2026). See §2.7.1. |
| **Constraints** | Cardinality and rules, e.g. a `Tenancy` has exactly one `Unit` and one `Tenant`; at most one `PolicyVersion` per `Policy` is current on any date; `SUPERSEDES` is acyclic; a `Tenancy`'s trade must be allowed for its unit type; tenancies on the same unit must not overlap. |
| **External alignment** (light) | A few `exact_mappings` to schema.org (`Organization`, `Place`) and FIBO (`Contract`) for future interoperability. No upper ontology is imported. |

**Generated artefacts** (`make ontology` → `src/plg/ontology/_generated/`)

```
ontology/plg.yaml ──► gen-pydantic ──► Pydantic models ─► LLM extraction schemas (Haiku structured output), ingest validation
                 ├──► gen-json-schema ─► JSON Schema ────► tool input/output schemas
                 ├──► custom gen ──────► graph allow-list (labels, edge types, domain→range, cardinality) ─► GraphWriter + CSV lint
                 ├──► custom gen ──────► vocabulary index (labels + synonyms) ─► `entities` table, query expansion, defect few-shots
                 ├──► custom gen ──────► glossary index (current + historical definitions) ─► `knowledge`/`data` lookup, ontology card
                 ├──► custom gen ──────► ontology card (compact text summary) ─► knowledge / route system prompts (prompt-cached)
                 ├──► gen-shacl ───────► SHACL shapes (documentation; reused if an RDF view is added later)
                 └──► gen-owl / gen-doc ► OWL (Turtle) + HTML docs for PLG review
```

**Where it is used at runtime**
- **Graph build and writes:** `GraphWriter` rejects nodes and edges that are not in the allow-list or that break cardinality, so neither LLM-extracted relations nor background writers can corrupt the graph.
- **Entity resolution and retrieval:** synonyms expand queries (e.g. "LOD" also searches *letter of demand*), and `resolve_entities` matches alternative labels.
- **Defect classification (D12):** categories, definitions and synonyms come from the vocabulary, replacing a hand-written list in the prompt.
- **NL→SQL (D8):** the semantic layer binds glossary concept IDs to SQL predicates and metrics, so "vacant" means the same thing in SQL, retrieval and answers (§2.7.1).
- **Corpus audit (AC4):** `jobs/corpus_audit` runs an **ontology rule check** over the graph and DuckDB (overlapping tenancies, two current policy versions, an SOP implementing a superseded policy, a trade not allowed for its unit type, duplicate tenants). Violations are reported as findings with evidence, next to the LLM-judged conflicts.
- **Domain-expert behaviour:** a compact ontology card (classes, key relations, definitions) is part of the knowledge and router system prompts, so answers use PLG's terms.

#### 2.7.1 Business glossary

The glossary is part of the ontology, not a separate file. That gives **one definition** per term (ontology) and **one SQL implementation** (semantic layer), linked by concept ID.

**Where it lives**
- `ontology/vocab/glossary.yaml`: LinkML instances of a `GlossaryTerm` class, with SKOS-style fields.
- `src/plg/semantic/metrics.yaml`: SQL bindings only, keyed by concept ID. It holds no definitions of its own.

```yaml
# ontology/vocab/glossary.yaml
- id: plg:Vacant_v2
  pref_label: Vacant (unit)
  alt_labels: [vacant unit, empty shop, unlet]
  definition: >-
    A lettable commercial unit with no active tenancy that is not under tender.
  broader: plg:UnitStatus
  source: "Minutes_PLG_Management_Meeting_2026-04-15.docx §5"   # cited in answers
  owner: S08 (Ops Analytics)
  effective_from: 2026-04-15
  supersedes: plg:Vacant_v1          # QBR definition, counted units under tender
  status: current                     # current | superseded | proposed

# src/plg/semantic/metrics.yaml
plg:Vacant_v2:
  sql_predicate: >-
    u.status NOT IN ('Not Lettable', 'Under Tender')
    AND NOT EXISTS (SELECT 1 FROM tenancies t
                    WHERE t.unit_id = u.unit_id
                      AND t.start_date <= :as_of AND t.end_date >= :as_of)
  params: [as_of]                    # defaults to the snapshot date 2026-09-30
  tables: [units, tenancies]
  example_queries: [ex_vacancy_by_town]
```

**Term fields:** `id`, `pref_label`, `alt_labels`, `definition` (plain English), `broader`/`related`, `source` (a document and section in the corpus, so the definition can be cited), `owner`, `effective_from`/`effective_to`, `supersedes`, `status`, and optionally a `sql_binding` reference.

**Seed terms (POC):** vacant, occupied, lettable, under tender, active tenancy, renewal window (6 months), arrears and arrears age buckets, letter of demand (60 days, POL-003 v2.0), termination threshold (3 months' rent), security deposit (3 months' rent), display area (1.0 m from Circular 07/2026), change of trade, A&A works, trade-mix limit (2 per NC), SLA breach, outstanding task, priority (urgency × impact), and complete application.

**Where it is used**

| Consumer | Use |
|---|---|
| `data` (D8, DC6) | Maps business terms in the question to concept IDs, then applies the bound SQL predicate. The SqlTrace states which definition was used ("vacant per glossary v2, effective 15 Apr 2026"), meeting DC6's "business logic and definitions" requirement. Historical questions use the definition that was in effect at the time unless the user asks otherwise. |
| `knowledge` (DC3) | Answers "what does X mean?" or "how was X defined in Q1?" with the definition, its effective dates, what it superseded, and a citation to the source document. |
| `route` | Synonyms help detect domain terms and intents. |
| `drafting` | Letters use preferred labels, so terminology stays consistent. |
| `corpus_audit` (AC4) | Flags documents and reports that use a superseded definition (e.g. the QBR vacancy figure) as conflicts, with both definitions cited. |
| Ontology card | Current definitions of the most-used terms are included in the router and agent system prompts (prompt-cached). |

**Change process**
1. **Proposal:** a new or changed term arrives as a curated team fact from memory (§2.6), a user request (`plg glossary propose`), or a corpus-audit finding. It enters with `status: proposed`.
2. **Approval:** the term owner approves it through the same approval interrupt. On approval the new version is written, the old one gets `effective_to` and `status: superseded`, and nothing is deleted.
3. **Validation:** `make ontology` checks the term (unique labels, a valid `supersedes` chain, and that every SQL binding points to a current concept and passes a dry-run `EXPLAIN` on DuckDB).
4. **Audit:** every change is a git commit, so the definition history is auditable.

**Explicitly out of scope for the POC:** an RDF triple store or SPARQL (including Neptune's RDF mode), OWL reasoning, and importing whole upper ontologies. The runtime model stays one property graph (networkx → Neptune openCypher). Because the ontology is in LinkML, an RDF/OWL view can be generated later if PLG needs one.

### 2.8 Web front-end (D23)

**Goal:** give PLG staff a browser UI for the whole POC: ask questions, check cited sources, see the SQL reasoning, approve actions and manage memory. It does this without moving any AI logic out of Python.

**Split of responsibilities**

| Layer | Tech | Owns | Never does |
|---|---|---|---|
| **Web app** (`web/`) | TypeScript (strict), Node.js 24 LTS, Next.js App Router, React, Tailwind CSS + shadcn/ui, TanStack Query, zod | Pages and components, streaming rendering, citation viewer, approval UI, login session; **BFF route handlers** that attach the user identity and proxy to `plg-api` | Call Claude, Voyage, LanceDB, DuckDB or the graph; hold API keys; decide routing or approvals |
| **API** (`src/plg/api/`) | Python FastAPI + `sse-starlette`, one process with the graph | Thread lifecycle, `graph.astream(...)`, `Command(resume=…)`, permission checks, memory and feedback endpoints, file serving from `DocumentSource` | Business logic of its own: it only adapts HTTP to the graph and stores |
| **Graph** (`src/plg/graph/`) | LangGraph + native Anthropic SDK (unchanged) | Everything in §2.1–§2.7 | Know about HTTP |

**Why this shape:** the graph, `run_agent()`, Citations, the read-only tool boundary and LangSmith tracing are all Python. Rewriting them in LangGraph.js would duplicate the core. A thin HTTP layer keeps one implementation, and the CLI, notebook and web UI all drive the same graph. A Node BFF, rather than the browser calling `plg-api` directly, keeps the API off the public network and keeps session cookies httpOnly. It is also where SSO is added later. *Alternative considered:* the LangGraph Agent Server API (`langgraph dev`) with `@langchain/langgraph-sdk`'s `useStream` hook. It gives threads, runs and interrupts for free, but its dev server keeps state in memory rather than in the §2.6 `SqliteSaver`, self-hosted production use needs a LangSmith Deployment licence, and memory, feedback and file endpoints would still need custom routes. It is kept as an option if PLG adopts LangSmith Deployment.

**API contract (`plg-api`, OpenAPI 3.1)**

| Endpoint | Purpose |
|---|---|
| `POST /threads` · `GET /threads` · `GET /threads/{id}` | Create, list (own threads only) and reload a session from the checkpointer, including history, pending approvals and `history_summary` |
| `POST /threads/{id}/runs` → `text/event-stream` | Send a user turn and stream the run. Events: `node` (node entered/finished, for the trajectory view), `token` (merged answer text), `citation`, `sql_trace`, `proposed_action`, `interrupt`, `done` (with LangSmith `run_id`), `error` |
| `POST /threads/{id}/resume` → `text/event-stream` | Approve, edit or reject a pending `ProposedAction` (`{action_id, version, decision, edits?}`) → `Command(resume=…)`, then stream `execute_action` and the audit result |
| `GET /approvals?status=pending` | Approval inbox across the user's threads (and, for curators, team-fact and glossary proposals) |
| `GET /documents/{doc_id}` · `GET /documents/{doc_id}/chunks/{chunk_id}` | Source file or text via `DocumentSource`, plus the chunk's location so the cited span can be highlighted |
| `GET/PATCH/DELETE /memory/...` | `plg memory list / show / edit / forget` for the current user (§2.6) |
| `POST /feedback` | 👍/👎 and corrections → `client.create_feedback(run_id, …)` (§6.1) |
| `GET /tasks/digest` · `GET /audit/reports/latest` · `GET /categories` | Read-only views over the `tasks`, `corpus_audit` and `categorise` outputs |

- Event payloads are Pydantic models, and their JSON Schema goes into the OpenAPI document. The web app generates its types from it (`openapi-typescript` + `openapi-fetch`), so a schema change breaks the TypeScript build instead of the UI at runtime. SSE frames are validated with zod on arrival.
- Streaming uses `graph.astream(..., stream_mode=["updates", "messages", "custom"], subgraphs=True)`. Only the `merge` node's tokens are streamed to the user; specialist outputs arrive as finished `AgentResult` summaries, which matches §2.6's compact-results rule.
- Reconnection: every event has a sequence number, and a client that reconnects can call `GET /threads/{id}` to rebuild the view from the checkpoint. Approvals survive browser restarts because they live in the checkpointer, not in the UI.

**Screens**

| Screen | What it shows | Requirements |
|---|---|---|
| **Ask** (chat) | Streaming answer; live trajectory of graph nodes (route → knowledge + data → merge); multi-intent results as sections; follow-up questions in the same thread | SYS, DC2–DC5 |
| **Sources panel** | Each citation opens the source: PDF via `react-pdf` with the cited span highlighted, DOCX/email/MD as rendered text; "policy stance" cards with current version, effective date and superseded versions; glossary definitions with their version | DC2–DC4, DC6 |
| **Reasoning panel** | The `SqlTrace` (plan → SQL → result table → explanation, including the glossary definition used), with copy and CSV export | DC5, DC6 |
| **Approvals** | Inbox of pending `ProposedAction`s; diff-style preview of drafted letters and i-EMS payloads; editable slot fields; approve / edit / reject with a reason; audit trail per action | DC1, AC1, AC5, D11 |
| **Draft preview** | Rendered letter (HTML preview of the docxtpl output) plus a DOCX download | DC1 |
| **Document check** | Upload or pick an application bundle → checklist with ✓/✗ per required document → generated missing-documents notice → approval | AC5 |
| **Tasks** | Prioritised task list with rule explanations (from `tasks` / `task_digest`) | AC2 |
| **Library** | Categories with summaries; corpus-audit findings (conflicts, duplicates, stale SOPs) with both sides cited | AC3, AC4 |
| **Memory** | My profile, episodes and pending team-fact proposals, each with provenance; edit / forget; curator review queue | D21 |
| **Feedback** | 👍/👎 and "correct this" on every answer, linked to the LangSmith `run_id` | D19 |

**Identity and access**
- **POC:** a mock sign-in that picks a staff member from the `staff` table (e.g. Estate Manager East, Ops Analytics). The BFF stores the user in an httpOnly session cookie and sends `X-PLG-User` to `plg-api` on a private loopback port. `plg-api` builds `UserCtx` from it, so §2.6 memory isolation and approver roles can be demonstrated with several personas.
- **Production:** Microsoft Entra ID (OIDC) through Auth.js in the BFF. The BFF forwards a signed token that `plg-api` verifies; the role comes from directory groups, not the UI.

**Quality**
- **Unit and component tests:** Vitest + React Testing Library, with MSW replaying recorded SSE streams so the UI is tested without Claude.
- **End-to-end:** Playwright against `plg serve` with a recorded or stubbed `LLMClient` for determinism. Key journeys: ask with citations, follow-up in the same thread, approve and reject an LOD, planted-injection email rendered as inert text, user A cannot open user B's thread.
- **Contract:** CI regenerates the OpenAPI types and fails if the committed client differs.
- **Accessibility:** WCAG 2.1 AA (government users), checked with `axe-core` in Playwright.

**Running locally:** `plg serve` (uvicorn on `127.0.0.1:8001`, one worker, because of the single-process stores in §2.5) and `pnpm --dir web dev` (Next.js on `:3000`). There is still no Docker. On AWS the web app runs as a container on ECS Fargate (or App Runner) behind an ALB, and `plg-api` sits in a private subnet next to OpenSearch and Neptune.

## 3. Requirement Coverage

| Req | Delivered by |
|---|---|
| DC1 Draft standardised documents | `drafting` node + `templates/` (TPL-REM-01, TPL-DOC-02, TPL-FBK-03, …) via docxtpl/Jinja2 slot-fill |
| DC2 Retrieve/analyse historical records | `knowledge` node over the hybrid index (LanceDB → OpenSearch) (policies, SOPs, emails, reports) + `entity_context` graph lookups |
| DC3 Policy interpretation and stance | `knowledge` "policy stance" format; glossary definitions with effective dates; `policy_lineage` over graph `SUPERSEDES`/`OVERRIDES` edges + effective-date filters in the search index exclude superseded versions (POL-003 v1.0 → v2.0; Circular 07/2026 overrides POL-001's display-area clause) |
| DC4 Precedent cases | `find_precedents`: graph traversal (trade, NC, related cases) + `doc_type=precedent` hybrid search |
| DC5 NL queries over structured data | `data` node: NL→SQL on DuckDB |
| DC6 Analysis with business logic and reasoning steps | Versioned business glossary (§2.7.1) + semantic-layer SQL bindings (e.g. *vacant = no active tenancy AND not under tender AND lettable*) + visible SqlTrace that names the definition used |
| DC7 Regular refresh; SharePoint and Lotus Notes | `ingest sync` (content-hash incremental) through `DocumentSource` adapters (SharePoint mock, Lotus Notes mock) |
| AC1 Classify defects → i-EMS | `defect_flow` subgraph + approval interrupt + `TicketSystem` mock |
| AC2 Prioritise and notify tasks | `tasks` node + `jobs/task_digest` (rules matrix; console or file digest) |
| AC3 Categorise documents; category summaries | `jobs/categorise` (embedding clustering + LLM-named clusters) → `category` field in the search index + `IN_CATEGORY` edges in the graph → `category_summary` intent |
| AC4 Conflicts, duplicates, gaps | `jobs/corpus_audit` (MinHash → vector-similarity pairs + graph lineage checks + **ontology rule check** → Opus judge) → `CONFLICTS_WITH` edges + report with citations; gaps found from low-score question logs |
| AC5 Document completeness; notify tenants | `doc_check_flow` subgraph + TPL-DOC-02 notice + approval → `Outbox` |
| SYS Front door, guardrails, HITL, learning | LangGraph router + §2.2 boundary + `interrupt()` + short- and long-term memory (§2.6) + feedback few-shot examples; "interpret like a domain expert" supported by the ontology (§2.7) |
| SYS User interface | TypeScript/Node.js web front-end (§2.8): streaming chat with cited sources and SQL reasoning, approvals inbox, document check, tasks, library, memory and feedback; the CLI is kept for jobs and power users |

## 4. Design Tree (selected)

```
PLG Super-Librarian POC
├── D1  Orchestration topology ........ LangGraph StateGraph front door + specialist agent nodes   ◆ (B topology, C control)
├── D2  Agent framework ............... LangGraph (orchestration) + native Anthropic SDK (agents)    ◆ user choice
├── D3  Model strategy ................ tiered: Haiku 5.5 route/classify · Sonnet 5.5 agents · Opus 5.5 audit/hard analysis, behind an LLMClient seam   ★
├── Knowledge (unstructured)
│   ├── D4  Retrieval method .......... hybrid BM25 + vector + reranker, + graph expansion            ★ + ◆
│   ├── D5  Index/store ............... LanceDB embedded (hybrid FTS + vector) → Amazon OpenSearch Service later   ◆ user choice
│   ├── D5b Knowledge graph ........... networkx in-process from Neptune bulk-load CSVs → Amazon Neptune later      ◆ user choice
│   ├── D6  Chunking .................. structure-aware (clause / email message / case record)        ★
│   └── D7  Citations ................. Claude Citations API                                         ★
├── Structured data
│   ├── D8  Query approach ............ NL→SQL + semantic layer (SQL bindings to ontology glossary terms, metrics, example SQL, read-only, validation)  ★
│   └── D9  Excel handling ............ load sheets into DuckDB at ingestion (+ ATTACH plg_records.db) ★
├── D10 Drafting ...................... approved template + slot-fill                                ★
├── Agentic
│   ├── D11 HITL / guardrails ......... approval gate: ProposedAction → interrupt() → execute_action   ★ (via LangGraph)
│   ├── D12 Defect classification ..... few-shot LLM + fixed taxonomy + structured output            ★
│   ├── D13 Task prioritisation ....... rules matrix (urgency × impact)                               ★
│   └── D14 Doc-completeness check .... checklist per application type + LLM document identification ★
├── Corpus intelligence
│   ├── D15 Categorisation ............ embedding clustering (HDBSCAN) + LLM-named clusters            ★
│   └── D16 Conflict/dup detection .... MinHash → embedding similarity → LLM judge                    ★
├── D17 Integration layer ............. adapter interfaces (DocumentSource, TicketSystem, Outbox) with mocks  ★
├── D18 Data refresh .................. incremental content-hash sync (CLI `sync`, schedulable)       ★
├── D19 Learning loop ................. 👍/👎 feedback + few-shot memory (verified Q→SQL, Q→answer)    ★
├── D21 Memory
│   ├── Short-term .................... checkpointer thread + summarise_history + compact agent results   ◆ user choice
│   └── Long-term ..................... MemoryStore (LangGraph BaseStore on LanceDB): profile · episodes · team facts · examples (+ graph WORKED_ON)  ◆ user choice
├── D22 Ontology .................... LinkML + SKOS-style vocabulary, design-time; generates schemas, allow-list, synonyms, rules  ★ (recommended, accepted)
├── D23 Front-end ..................... TypeScript · Node.js · Next.js UI + BFF → FastAPI `plg-api` (SSE) → LangGraph      ◆ user choice
└── D20 Evaluation & observability .... LangSmith: tracing + datasets + offline experiments + online evaluators  ◆ user choice
```
◆ = user selection · ★ = recommended option accepted

### 4.1 Notes on the selected options

- **D3 models:** `claude-haiku-5-5`, `claude-sonnet-5-5` and `claude-opus-5-5`. The options doc listed Haiku 4.5; this uses the current Haiku 5.5. Model IDs live in config so each node can be retiered.
- **D4/D5 retrieval:** see §2.5. Graph expansion adds a lighter form of GraphRAG without the cost of full community summarisation. Embeddings: Voyage AI (`VOYAGE_API_KEY` is already in `.env`). For the on-prem path, `bge-m3` is the local fallback behind the same `Embedder` interface. Reranker: a local cross-encoder such as `bge-reranker-v2-m3` (Voyage rerank is an alternative).
- **D9 data:** `poc-data/plg_records.db` (SQLite, 17 tables) is attached read-only in DuckDB. `poc-data/sheets/*.xlsx` are loaded as DuckDB tables, with cleaning rules for merged or multi-row headers. The `_database.md` conventions (TEXT dates, REAL money, 1/0 booleans) go into the semantic layer's table notes.
- **D11 HITL:** this uses LangGraph `interrupt()` / `Command(resume=…)` with a `SqliteSaver` checkpointer instead of Agent SDK hooks, so an approval can be resumed in a later CLI invocation or notebook cell.
- **D12/D14 taxonomies:** seed the ontology's vocabularies (§2.7) from `poc-data/_master/taxonomy_and_checklists.json` (8 defect categories with team, vendor and default severity; checklists for NEW_TENANCY, RENEWAL, ASSIGNMENT, CHANGE_OF_TRADE, ALTERATION).
- **D17:** adapters are Python `Protocol`s. The POC's mocks read `poc-data/docs|emails|pdfs|…` and write i-EMS tickets and outbox items to local files or tables. An adapter can later be wrapped as an MCP server without changing the agents.

## 5. Project Layout

```
agent-hdb-v2/
├── poc-data/                 # existing synthetic corpus, plg_records.db, _master ground truth
├── ontology/                 # plg.yaml (LinkML source of truth), vocab/*.yaml (incl. glossary.yaml), rules/*.py, generated docs
├── src/plg/
│   ├── config.py             # model IDs, paths, thresholds
│   ├── llm.py                # LLMClient seam + run_agent() tool-use loop (native Anthropic SDK)
│   ├── graph/
│   │   ├── state.py          # PLGState, Intent, AgentResult, ProposedAction
│   │   ├── build.py          # StateGraph wiring, Send() fan-out, checkpointer
│   │   ├── route.py  merge.py  approval.py  execute.py
│   │   ├── defect_flow.py    # subgraph (AC1)
│   │   └── doc_check_flow.py # subgraph (AC5)
│   ├── agents/               # knowledge.py · data.py · drafting.py (prompts + read-only tools)
│   ├── retrieval/            # SearchStore protocol; LanceDBStore, OpenSearchStore (later); reranker, embedder
│   ├── graph_store/          # GraphStore protocol; LocalGraphStore (networkx), NeptuneGraphStore (later), GraphWriter;
│   │                         #   cypher/<method>.cypher templates, CSV/template lint
│   ├── ingest/graph_build.py # entity spine from plg_records.db + ID regex + LLM relation extraction → canonical bulk-load CSVs → graph store
│   ├── ontology/             # _generated/ (Pydantic, JSON Schema, allow-list, vocab index, ontology card), rule checker
│   ├── semantic/             # metrics.yaml (SQL bindings keyed by glossary concept ID), example_queries.yaml, SQL validator
│   ├── adapters/             # DocumentSource (sharepoint_mock, lotus_mock), TicketSystem (iems_mock), Outbox
│   ├── ingest/               # parsers per type (docx, pdf, eml, xlsx, pptx, md), chunking, sync
│   ├── guardrails/           # injection screen, PII check, audit log
│   ├── jobs/                 # categorise, corpus_audit, task_digest
│   ├── memory/               # MemoryStore (BaseStore on LanceDB), load/write/summarise nodes, extraction prompts, curation, CLI
│   ├── api/                  # FastAPI app: routes (threads, runs, resume, approvals, documents, memory, feedback), SSE event models, auth context
│   └── cli.py                # `plg ask | serve | sync | approve | digest | audit | categorise`
├── web/                      # TypeScript front-end (Node.js 24, pnpm)
│   ├── app/                  # Next.js App Router: (chat)/, approvals/, doc-check/, tasks/, library/, memory/, api/ (BFF route handlers)
│   ├── components/           # chat stream, citation + PDF viewer, SQL trace, approval card, draft preview (shadcn/ui)
│   ├── lib/                  # generated OpenAPI client + types, SSE parser (zod-validated), session/auth
│   └── tests/                # Vitest + MSW (unit/component), Playwright e2e + axe accessibility
├── templates/                # approved letter/email templates (docxtpl / Jinja2)
├── .plg/                     # git-ignored local state: lancedb/, graph/ (canonical CSVs), checkpoints.sqlite
├── infra/                    # (post-POC) AWS CDK: VPC, OpenSearch domain, Neptune Serverless, S3, IAM, ECS Fargate (web + plg-api), ALB
├── evals/
│   ├── datasets/             # golden sets per node (JSONL, version-controlled; synced to LangSmith datasets)
│   ├── evaluators/           # code evaluators + LLM-as-judge evaluators
│   ├── run_experiments.py    # langsmith evaluate() per node and end-to-end
│   └── test_*.py             # pytest regression suite (LangSmith pytest integration)
└── notebooks/demo.ipynb
```

**Core stack:** Python 3.12 · `langgraph` + `langgraph-checkpoint-sqlite` · `anthropic` · `lancedb` · `networkx` · `filelock` · later: `opensearch-py`, `boto3` / SigV4 for Amazon OpenSearch Service and Neptune · `voyageai` · `duckdb` · `docxtpl` / `jinja2` · `python-docx`, `pypdf`, `openpyxl`, `python-pptx` · `datasketch` · `hdbscan` · `langsmith` · `openevals` · `linkml` / `linkml-runtime` · `fastapi` + `uvicorn` + `sse-starlette` · `pytest`.

**Front-end stack:** Node.js 24 LTS · TypeScript (strict) · pnpm · Next.js (App Router) + React · Tailwind CSS + shadcn/ui · TanStack Query · zod · `openapi-typescript` + `openapi-fetch` · `react-markdown` (no raw HTML) · `react-pdf` · Auth.js (production SSO) · Vitest + React Testing Library + MSW · Playwright + `@axe-core/playwright` · ESLint + Prettier.

## 6. Tracing & Evaluation (D20, LangSmith)

### 6.1 Tracing

| What | How |
|---|---|
| Graph runs | LangGraph sends traces automatically when `LANGSMITH_TRACING=true`. Every node, `Send()` branch, interrupt and resume appears as a span in one run tree. |
| Claude calls | The native SDK client is created through `langsmith.wrappers.wrap_anthropic(Anthropic())` inside `LLMClient`, so each `messages.create` call in `run_agent()` is logged with its model, tokens, latency, cost, tool calls and cache hits. |
| Tools and retrieval | Read-only tools, hybrid search, reranking and SQL execution are decorated with `@traceable(run_type="tool" / "retriever")`, so retrieved chunk IDs and SQL text appear in the trace. |
| Metadata and tags | Each run carries `thread_id`, `user`, `intents`, `model_tier` and `git_sha` metadata, so traces can be filtered by session, user, agent or release. Projects: `plg-dev`, `plg-eval`, `plg-demo`. |
| Approvals and audit | `ProposedAction`, the approval decision and `execute_action` are traced spans. The audit log stores the LangSmith `run_id`, so every external action links back to the full reasoning trace. |
| Web requests | `plg-api` starts each run with LangSmith metadata `channel=web` and the BFF request ID, and returns the root `run_id` in the `done` event. The UI keeps it with each answer for feedback and "view trace" links (visible to developers only). |
| User feedback (D19) | Web and CLI 👍/👎 and corrections are recorded with `client.create_feedback(run_id, key="user_rating", …)`. Thumbs-down runs go to an **annotation queue** for review; corrected answers are promoted into datasets and few-shot memory. |
| Privacy | `hide_inputs` / `hide_outputs` hooks mask NRIC-like IDs, phone numbers and emails before upload. Configuration in `.env`: `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT` (pointed at self-hosted LangSmith in production). |

### 6.2 Evaluation

Ground truth already exists in `poc-data/_master/` (key entities, planned conflicts, submission-bundle ground truth, data-quality issues), and `poc-data/_scenario.md` §5 has example questions. These seed one **LangSmith dataset per node** plus an end-to-end dataset. The JSONL sources stay in `evals/datasets/` under git and are uploaded by `run_experiments.py`.

| Dataset / target | Evaluators (code ▸ LLM-as-judge) | POC target |
|---|---|---|
| `route` | ▸ multi-label intent accuracy; clarification on ambiguous inputs | ≥ 90% |
| `knowledge` | ▸ retrieval recall@5 against gold chunk IDs (hybrid alone vs hybrid + graph expansion); superseded-version avoidance; graph edge precision against `_master` (spot-checked) · ▸ faithfulness to cited spans, answer correctness | ≥ 85% faithfulness |
| `data` | ▸ SQL execution accuracy (result set equals the gold result); read-only and validator pass · ▸ explanation names and applies the correct (time-appropriate) glossary definition | ≥ 80% |
| `drafting` | ▸ template ID correct, all slots filled, slot values match DB · ▸ tone/PII check | ≥ 90% slot accuracy |
| `defect_flow` | ▸ category/team macro-F1, severity accuracy, low-confidence escalation | ≥ 85% F1 |
| `doc_check_flow` | ▸ missing-document precision/recall against bundle ground truth | ≥ 90% recall |
| `corpus_audit` | ▸ recall of `planned_conflicts.json` | ≥ 80% |
| Guardrails | ▸ planted prompt injection blocked; zero `execute_action` spans without an approval span | 100% |
| Glossary | ▸ definition questions (current and historical) answered with the correct version and citation; SQL for glossary terms uses the bound predicate; superseded-definition usage detected by `corpus_audit` | ≥ 90% |
| Ontology | ▸ 100% of graph CSVs and extracted relations valid against the ontology; rule-check recall of the planted issues in `data_quality_issues.json` and `planned_conflicts.json`; synonym expansion lift in retrieval recall@5 (with vs without) | 100% validity; ≥ 80% rule recall |
| Memory | ▸ cross-session recall of profile and episode facts; **zero cross-user leakage**; no memory overriding a current policy; poisoned-email test writes nothing; quality of answers after summarisation vs full history | 100% isolation |
| Web front-end | ▸ Playwright journeys (§2.8) pass with a stubbed `LLMClient`; zero approvals possible without a pending interrupt for that user; no script execution from rendered corpus text; axe: no serious WCAG 2.1 AA violations; time to first streamed token p95 | 100% journeys pass |
| End-to-end | ▸ trajectory check (expected nodes visited) · ▸ answer correctness with citations; latency p95 and cost per query from traces | Report |

**How it runs:**
- **Offline experiments:** `langsmith.evaluate(target, data=dataset, evaluators=[…], experiment_prefix=…)` per node, with the node invoked in isolation and the graph end to end. Experiments are compared side by side in LangSmith, e.g. Haiku vs Sonnet for `route`, reranker on vs off, prompt v1 vs v2.
- **Regression gate:** a small pytest suite uses the LangSmith pytest integration (`@pytest.mark.langsmith`). It runs on each change, and results are logged as an experiment.
- **LLM-as-judge:** `openevals` judges, with Claude Opus 5.5 as the judge model and the rubric pinned in `evals/evaluators/`. A sample of judge verdicts is spot-checked by hand.
- **Online evaluators:** during the demo or pilot, a sample of production traces is scored automatically (faithfulness, guardrail violations). Failures go to the annotation queue, and fixed examples are added back to the datasets.

## 7. Plan (4 weeks)

| Week | Deliverable |
|---|---|
| 1 | **Ontology v1** (`plg.yaml`, vocabularies seeded from `_master`, **business glossary seed terms**, generators, ontology card); `SearchStore`/`GraphStore` interfaces + LanceDB store; `llm.py` loop + seam; **LangSmith tracing on from day 1**; ingestion into the LanceDB hybrid index; `knowledge` node with Citations; minimal graph (`route` → `knowledge`); golden datasets v1 + `route`/`knowledge` experiments · **Web:** `plg serve` (threads, runs SSE) + OpenAPI type generation; Next.js skeleton, mock sign-in, Ask screen with streaming answer and Sources panel |
| 2 | Graph build (entity spine + relation extraction → canonical CSVs → `LocalGraphStore`), Cypher templates + contract tests + lint and graph tools (`policy_lineage`, `find_precedents`, `entity_context`); DuckDB + semantic-layer SQL bindings for glossary terms + `data` node with trace; `drafting` node; Send() fan-out and `merge` · **Web:** Reasoning panel (SqlTrace), node trajectory, Draft preview, PDF span highlighting |
| 3 | `approval` interrupt + `execute_action` + adapters; `defect_flow`, `doc_check_flow`, `tasks`; memory (`load_memory`, `write_memory`, `summarise_history`, MemoryStore, curation) + feedback · **Web:** `/resume` + Approvals inbox, Document check, Tasks, Memory screens, 👍/👎 |
| 4 | `sync`, `categorise`, `corpus_audit` jobs (incl. ontology rule check); full experiment run, per-model-tier comparison and metrics report from LangSmith; online evaluators; demo notebook · **Web:** Library screen (categories, audit findings), Playwright + axe suite, demo run through the web UI |

The web track adds about one developer's worth of effort alongside the Python work. If only one developer is available, the Week 1–2 web items stay and the Library and Memory screens fall back to the CLI.

## 8. Risks and Open Questions

1. **Data classification:** if it is Sensitive-High, swap Claude for an open-weight model behind `LLMClient`. Native Citations would then fall back to post-hoc citation verification (D7 option 3).
2. **Two paradigms:** a LangGraph graph plus hand-written agent loops. Mitigation: one `run_agent()` helper, and agents stay as leaf nodes that never orchestrate each other.
3. **Routing errors:** a new failure mode. Mitigation: a routing golden set, a clarifying question on low confidence, and multi-intent fan-out instead of a forced single choice.
4. **Policy versioning:** effective-date metadata must be right at ingestion, or answers will cite superseded clauses.
5. **Trace data leaves the environment:** LangSmith Cloud stores full prompts, retrieved documents and outputs. That is fine for the synthetic POC corpus, but production needs self-hosted LangSmith (or Langfuse self-hosted as an open-source fallback) inside GCC or on-prem, plus masking of tenant PII in traces.
6. **Local to AWS differences:** the local graph code is Python, not the Cypher Neptune will run, and LanceDB's hybrid scoring differs from OpenSearch's. Mitigation: the canonical CSVs, the graph contract tests that every backend must pass, Neptune-compatible data rules, and re-tuning the retrieval weights against the eval sets at migration. Budget a few days for that migration testing. The production target (GCC on AWS, Claude via Amazon Bedrock) is unchanged.
7. **Graph quality:** relations extracted by an LLM can be wrong. Mitigation: deterministic ID-based edges wherever possible, evidence chunks on every extracted edge, and checks against `_master` ground truth.
8. **Single-process limits:** an embedded LanceDB and an in-memory graph suit one process. The web UI therefore talks to a single `plg-api` worker, which is enough for a handful of demo users; concurrent writers are serialised with a file lock. Real multi-user use needs the AWS backends and several API workers.
9. **Lotus Notes extraction** (DXL / Domino REST) remains the main production integration risk.
10. **Memory risks:** stale or wrong memories, and over-personalisation. Mitigation: provenance on every item, expiry, curation of anything shared, a "memory never beats a cited source" rule, and user-visible `forget`.
11. **Ontology scope creep:** ontology work can grow without limit. Mitigation: cap it at the classes and relations used by the POC's example questions and workflows, keep it design-time only, and time-box v1 to 2–3 days.
12. **Two languages (Python + TypeScript):** more tooling and a contract that can drift. Mitigation: all AI logic stays in Python; the web app is presentation only; types are generated from OpenAPI and checked in CI.
13. **Streaming and long runs:** fan-out runs can take tens of seconds, and proxies may cut SSE connections. Mitigation: node-progress events, sequence numbers plus reload from the checkpoint, and heartbeat comments on the stream. The BFF route handlers use the Node.js runtime (not Edge) with buffering off.
14. **PLG artefacts:** the ontology, taxonomy, checklists, priority rules, glossary and templates are invented for the POC and need PLG validation.

## 9. Prior Art and References

**Agent patterns**
- Anthropic, *Building Effective Agents* (routing, orchestrator–workers, workflows vs agents): https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, *How we built our multi-agent research system*: https://www.anthropic.com/engineering/multi-agent-research-system
- Yao et al., *ReAct* (2022): https://arxiv.org/abs/2210.03629

**Orchestration and runtime**
- LangGraph: graphs, `Send` map-reduce, human-in-the-loop `interrupt`, persistence: https://langchain-ai.github.io/langgraph/
- Anthropic Python SDK: https://github.com/anthropics/anthropic-sdk-python
- Claude tool use: https://docs.claude.com/en/docs/agents-and-tools/tool-use/overview
- Claude Citations: https://docs.claude.com/en/docs/build-with-claude/citations
- Claude PDF support: https://docs.claude.com/en/docs/build-with-claude/pdf-support
- Prompt caching: https://docs.claude.com/en/docs/build-with-claude/prompt-caching
- Claude models: https://docs.claude.com/en/docs/about-claude/models/overview

**Front-end and API**
- Next.js App Router and route handlers: https://nextjs.org/docs/app · TypeScript: https://www.typescriptlang.org/docs/
- FastAPI: https://fastapi.tiangolo.com · sse-starlette: https://github.com/sysid/sse-starlette · Server-Sent Events (WHATWG): https://html.spec.whatwg.org/multipage/server-sent-events.html
- LangGraph streaming (`stream_mode`, subgraphs): https://langchain-ai.github.io/langgraph/how-tos/streaming/ · LangGraph JS SDK `useStream` (alternative considered): https://langchain-ai.github.io/langgraph/cloud/how-tos/use_stream_react/
- openapi-typescript / openapi-fetch: https://openapi-ts.dev · zod: https://zod.dev · TanStack Query: https://tanstack.com/query · shadcn/ui: https://ui.shadcn.com · react-pdf: https://github.com/wojtekmaj/react-pdf
- Auth.js (Microsoft Entra ID provider): https://authjs.dev · Playwright: https://playwright.dev · axe-core: https://github.com/dequelabs/axe-core · WCAG 2.1: https://www.w3.org/TR/WCAG21/

**Retrieval**
- Lewis et al., *Retrieval-Augmented Generation* (2020): https://arxiv.org/abs/2005.11401
- Anthropic, *Contextual Retrieval*: https://www.anthropic.com/news/contextual-retrieval
- Amazon OpenSearch Service, k-NN vector search: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/knn.html
- OpenSearch hybrid search and normalization processor: https://opensearch.org/docs/latest/search-plugins/hybrid-search/
- LanceDB hybrid search and rerankers: https://lancedb.github.io/lancedb/hybrid_search/hybrid_search/ · https://lancedb.github.io/lancedb/reranking/
- NetworkX: https://networkx.org/documentation/stable/
- openCypher: https://opencypher.org
- Amazon Neptune openCypher (and compliance/differences with Neo4j): https://docs.aws.amazon.com/neptune/latest/userguide/access-graph-opencypher.html · https://docs.aws.amazon.com/neptune/latest/userguide/feature-opencypher-compliance.html
- Neptune openCypher bulk-load format: https://docs.aws.amazon.com/neptune/latest/userguide/bulk-load-tutorial-format-opencypher.html
- Amazon Neptune Serverless: https://docs.aws.amazon.com/neptune/latest/userguide/neptune-serverless.html
- Neptune bulk loader: https://docs.aws.amazon.com/neptune/latest/userguide/bulk-load.html
- Neptune IAM data-access policies: https://docs.aws.amazon.com/neptune/latest/userguide/iam-dp-actions.html
- Microsoft GraphRAG (graph-augmented retrieval prior art): https://microsoft.github.io/graphrag/ · Edge et al., *From Local to Global: A Graph RAG Approach* (2024): https://arxiv.org/abs/2404.16130
- AWS, GraphRAG with Neptune and OpenSearch (graphrag-toolkit): https://github.com/awslabs/graphrag-toolkit
- Voyage AI embeddings: https://docs.voyageai.com
- LinkML (modelling language and generators): https://linkml.io/linkml/
- W3C SKOS reference: https://www.w3.org/TR/skos-reference/ · W3C SHACL: https://www.w3.org/TR/shacl/ · W3C OWL 2 overview: https://www.w3.org/TR/owl2-overview/
- schema.org: https://schema.org · FIBO (EDM Council): https://spec.edmcouncil.org/fibo/
- Pan et al., *Unifying Large Language Models and Knowledge Graphs: A Roadmap* (2023): https://arxiv.org/abs/2306.08302

**Structured data**
- BIRD text-to-SQL benchmark: https://bird-bench.github.io
- Vanna (RAG for SQL; few-shot SQL memory, prior art for D19): https://github.com/vanna-ai/vanna
- DuckDB (SQLite and Excel extensions): https://duckdb.org

**Corpus intelligence, drafting, integration**
- BERTopic (cluster + label prior art): https://maartengr.github.io/BERTopic/ · HDBSCAN: https://hdbscan.readthedocs.io
- datasketch MinHash: https://ekzhu.com/datasketch/
- docxtpl: https://docxtpl.readthedocs.io · Jinja2: https://jinja.palletsprojects.com
- Microsoft Graph (SharePoint): https://learn.microsoft.com/en-us/graph/api/resources/sharepoint · HCL Domino REST API: https://opensource.hcltechsw.com/Domino-rest-api/
- Model Context Protocol (future adapter wrapping): https://modelcontextprotocol.io

**Safety and evaluation**
- OWASP Top 10 for LLM Applications: https://owasp.org/www-project-top-10-for-large-language-model-applications/
- Anthropic, mitigating jailbreaks and prompt injections: https://docs.claude.com/en/docs/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks
- LangGraph memory (short-term threads, long-term `BaseStore`): https://langchain-ai.github.io/langgraph/concepts/memory/ · LangMem (memory extraction patterns): https://langchain-ai.github.io/langmem/
- Anthropic, *Effective context engineering for AI agents*: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents · Claude memory tool: https://docs.claude.com/en/docs/agents-and-tools/tool-use/memory-tool
- Packer et al., *MemGPT: Towards LLMs as Operating Systems* (2023): https://arxiv.org/abs/2310.08560 · Park et al., *Generative Agents* (memory stream, reflection; 2023): https://arxiv.org/abs/2304.03442
- LangSmith observability (tracing, `wrap_anthropic`, `@traceable`): https://docs.smith.langchain.com/observability
- LangSmith evaluation (datasets, `evaluate()`, experiments, online evaluators, pytest): https://docs.smith.langchain.com/evaluation
- openevals (prebuilt LLM-as-judge evaluators): https://github.com/langchain-ai/openevals
- Langfuse (open-source, self-hostable alternative): https://langfuse.com/docs
- RAGAS: https://docs.ragas.io · Anthropic, building evals: https://docs.claude.com/en/docs/test-and-evaluate/develop-tests
