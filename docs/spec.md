# Spec: PLG "Super-Librarian" POC

> Source: `docs/solution.MD` (selected solution), `docs/REQ.md`, POC corpus in `poc-data/` (`_report.md`, `_scenario.md`, `_manifest.csv`, `_database.md`).

## Problem Statement

Officers in HEB's Properties & Land Group (PLG) manage about 1,500 commercial units: leasing, renewals, arrears, change-of-trade, A&A works, inspections, public feedback and defects. The information they need is spread across SharePoint (policies, SOPs, circulars, reports, templates), Lotus Notes (email), i-EMS (defect tickets), the PLG Records database and many Excel trackers.

Today, an officer who wants to answer "when do we issue a letter of demand?", "how many units were vacant at end-August?" or "what did we do last time a tenant asked to switch to bubble tea?" has to search several systems by hand. They then have to work out which document is current, because policies are superseded, SOPs go stale and circulars override clauses. They also have to reconcile figures that disagree because they were computed with different definitions.

Routine work is also manual: drafting reminder letters and missing-documents notices, classifying public feedback and raising i-EMS tickets, checking that application bundles are complete, and deciding which of many open tasks to do first. Answers are slow, inconsistent and hard to cite. Mistakes such as quoting a superseded policy, using the wrong vacancy definition or billing from a mistyped rent cause real harm to tenants and to PLG.

## Solution

A "super-librarian" assistant that officers use through a CLI or notebook. It has a single front door. An officer asks a question or makes a request in plain English. The system works out what kind of request it is, sends it to one or more specialist agents and returns one merged answer, with:

- **Citations** to the exact source passages for policy and records questions. It states PLG's *current* stance, the effective date and what was superseded.
- **A visible reasoning trace** for data questions (plan → SQL → result → explanation), naming the business definition used (e.g. "vacant per glossary v2, effective 15 Apr 2026").
- **Drafts** of standard letters and emails filled from approved templates and live records.
- **Proposed actions** (send a letter, raise an i-EMS ticket, update a record) that never happen automatically. The officer approves, edits or rejects each one, and only approved actions are executed and audited.

Behind the front door, background jobs keep the knowledge current (incremental sync from SharePoint and Lotus Notes mocks), categorise documents, audit the corpus for conflicts, duplicates and rule violations, and produce prioritised task digests.

The assistant remembers each user's preferences and past work across sessions, never leaks one user's memory to another, and never lets memory override a cited policy or a SQL result. All runs are traced in LangSmith and scored against golden datasets built from the corpus ground truth.

## User Stories

### Front door and routing

1. As a PLG officer, I want to ask any question in plain English in one place, so that I don't need to know which system or bot holds the answer.
2. As a PLG officer, I want a question that spans policy and data (e.g. "what's the arrears policy and which tenants breach it?") answered in one reply, so that I don't have to ask twice and stitch the results together.
3. As a PLG officer, I want the assistant to ask me a clarifying question when my request is ambiguous, so that it doesn't guess wrongly and waste my time.
4. As a PLG officer, I want to ask follow-ups such as "and for Cendana?" in the same session, so that I don't have to restate context.
5. As a PLG officer, I want a long session to keep working without losing the key facts (entity IDs, pending approvals), so that I can work a case end to end in one thread.
6. As a PLG officer, I want to resume a paused session (e.g. a pending approval) in a later CLI invocation or notebook cell, so that I'm not forced to finish everything in one sitting.

### Policy and knowledge retrieval (DC2, DC3)

7. As a leasing officer, I want to ask "when does PLG issue a letter of demand?" and be told 60 days (POL-003 v2.0) with citations, so that I apply the current policy.
8. As a leasing officer, I want to be warned when an SOP or guide contradicts current policy (e.g. SOP-014 still says 45 days), so that I don't follow outdated procedure.
9. As an estate manager, I want PLG's current stance on display areas to say 1.0 m for NC units from 1 Aug 2026 (Circular 07/2026) but 0.6 m for void-deck shops, so that enforcement is correct for each unit type.
10. As a leasing officer, I want to be told the security deposit is 3 months' rent per POL-002, with a note that the Tenant FAQ's 2 months is outdated, so that I quote tenants correctly.
11. As a leasing officer, I want to know the renewal lead time is at least 6 months (with 3–6 months discretionary), and that the onboarding guide and a past email say 3 months, so that I correct earlier misinformation.
12. As a policy officer, I want every policy answer laid out as current position, effective date, superseded versions and sources, so that I can see the policy's history at a glance.
13. As a PLG officer, I want to ask what a policy said *before* a given date (e.g. the LOD trigger before April 2026), so that I can judge historical cases by the rules that applied then.
14. As a PLG officer, I want every factual claim to link to the passage it came from, so that I can verify it and quote it in correspondence.
15. As a PLG officer, I want to search past emails (Lotus Notes) and reports alongside policies, so that I can find what was actually said and done.
16. As a PLG officer, I want to ask about internal audit findings (e.g. IA-02 on rent master data), so that I can follow up on issues found by audit.
17. As a PLG officer, I want abbreviations and synonyms ("LOD", "void-deck shop", "ceiling leak") understood, so that I can use my everyday words.
18. As a PLG officer, I want to ask "what did we do last time with this tenant?" and see the tenant's tenancies, units, open feedback, tickets and who handled them, so that I have full context before acting.
19. As a PLG officer, I want to ask "what does *vacant* mean?" or "how was vacancy defined in Q1?" and get the definition, effective dates, what it superseded and a citation, so that my reports use the right definition.

### Precedents (DC4)

20. As a leasing officer, I want precedents for converting a provision shop to bubble tea in an NC (PC-2024-009 rejected; PC-2025-014 approved), so that my recommendation is consistent with past decisions.
21. As an estate manager, I want precedents matched by trade, NC and issue type, so that the cases I see are relevant, not just keyword hits.
22. As an estate manager, I want to know how a past partial sublet (hair salon to nail salon) was resolved (PC-2024-021: S$500 composition fee, 14 days to regularise), so that I can deal with Lucky Star the same way.
23. As a manager, I want the assistant to say when a precedent does *not* apply (e.g. Sin Hock's fire was tenant-caused, unlike PC-2025-019), so that I don't grant a rebate that isn't justified.

### Structured data queries and analysis (DC5, DC6)

24. As a data analyst, I want to ask "how many vacant units at 31 Aug 2026, by town?" and get 47 using the current glossary definition, so that figures match the official report.
25. As a data analyst, I want to see that the QBR's 52 used the old definition, which counted 5 units under tender, so that I can explain the discrepancy to management.
26. As a finance manager, I want to list tenancies with arrears above 3 months' rent as at 30 Sep 2026 and see the SQL, so that I can verify the logic and act on termination candidates.
27. As a finance manager, I want a single tenant's current arrears (e.g. Golden Leaf: S$22,672.00, 121 days, 4.0 months), so that I can respond to that tenant's queries accurately.
28. As a maintenance coordinator, I want i-EMS SLA attainment by team for a quarter, so that I can manage vendor performance.
29. As an estate manager, I want to count outlets of a trade in an NC (e.g. bubble tea in NC-PI-1 = 2), so that I can apply the trade-mix limit.
30. As a leasing officer, I want renewal applications submitted less than 6 months before expiry flagged, so that I can treat them as late under policy.
31. As a manager, I want the total monthly rent roll by town, so that I can see revenue exposure.
32. As a data analyst, I want every data answer to show the plan, the SQL, the result and a plain-English explanation, so that I can audit the reasoning.
33. As a data analyst, I want the explanation to name the business definition and version it applied, so that the numbers are interpretable and reproducible.
34. As a data analyst, I want historical questions to use the definition that was in effect at the time unless I ask otherwise, so that period comparisons are fair.
35. As a data analyst, I want the Excel trackers (vacancy report, arrears ageing, task tracker, inspection tracker, …) to be queryable alongside the database, so that I don't have to merge them by hand.
36. As a data analyst, I want known data-quality problems (duplicate tenants, NULLs, outlier rents, impossible dates, duplicated payments) to be flagged rather than silently counted, so that I trust the results.
37. As a PLG officer, I want data queries to be read-only, so that asking a question can never change a record.
38. As a PLG officer, I want policy and data combined in one answer ("the policy says X, the data shows Y"), so that I can make a decision straight away.

### Drafting documents (DC1)

39. As a leasing officer, I want a missing-documents notice for an application (e.g. APP-2026-0256 missing LAYOUT) drafted from TPL-DOC-02, so that I can notify the tenant quickly and consistently.
40. As a finance officer, I want a first arrears reminder drafted from TPL-REM-01 with the tenant's oldest unpaid invoice filled in, so that reminders are accurate and on-template.
41. As a customer relations officer, I want a reply to a feedback provider (e.g. FB-2026-00707) drafted from TPL-FBK-03, citing the i-EMS ticket and the repair done, so that the public gets a factual update.
42. As a PLG officer, I want every slot in a draft filled from live records, and to be told about any slot that couldn't be filled, so that no letter goes out with blanks or wrong figures.
43. As a PLG officer, I want drafts to use PLG's preferred terms, so that correspondence is consistent.
44. As a PLG officer, I want drafts checked for PII problems before I approve them, so that I don't leak personal data.
45. As a PLG officer, I want sending a drafted letter or email to always need my explicit approval, so that nothing is sent on the assistant's own initiative.
46. As a PLG officer, I want to edit a draft before approving it, so that I can adjust the wording without starting over.

### Defect classification and i-EMS routing (AC1)

47. As a customer relations officer, I want a feedback text classified into PLG's defect taxonomy (category, severity, team, vendor) with a confidence score and rationale, so that routing is fast and consistent.
48. As a maintenance coordinator, I want a burst pipe classified as PLB → M&E (Sunrise M&E), Medium, 7-day SLA, and an i-EMS ticket proposed, so that the defect is fixed promptly.
49. As a maintenance coordinator, I want ambiguous feedback (e.g. a wet ceiling with flickering lights: SEP vs ELE) to default to the higher severity and be sent to me for review, so that safety risks aren't under-classified.
50. As a maintenance coordinator, I want non-defect complaints recognised as such and not ticketed, so that i-EMS isn't flooded with noise.
51. As a maintenance coordinator, I want the i-EMS ticket created only after I approve the proposal, so that no wrong ticket reaches a vendor.
52. As a maintenance coordinator, I want each approved ticket recorded with a link to the reasoning behind it, so that routing decisions can be audited.

### Application document completeness (AC5)

53. As a leasing officer, I want to ask "is APP-2026-0293 complete?" and be told the insurance certificate expires before the new term, so that I catch problems beyond missing files.
54. As a leasing officer, I want to ask "what is APP-2026-0228 missing?" and be told INS and GIRO, so that I can chase the tenant.
55. As a leasing officer, I want each submitted file identified by document type (including scanned PDFs), so that misnamed files (e.g. `IMG_2458.pdf`) are still recognised.
56. As a leasing officer, I want documents for the wrong unit flagged by checking application → unit → tenancy, so that wrong-unit submissions are caught.
57. As a leasing officer, I want illegible scans flagged as needing resubmission, so that I don't accept unreadable documents.
58. As a leasing officer, I want each application checked against the checklist for its type (NEW_TENANCY, RENEWAL, ASSIGNMENT, CHANGE_OF_TRADE, ALTERATION), so that the rules match the application.
59. As a leasing officer, I want a missing-documents notice drafted automatically when gaps are found, and sent only after I approve it, so that the tenant is told promptly and correctly.

### Task prioritisation and notification (AC2)

60. As an estate manager, I want to ask "what are my top 5 tasks and why?" and get a ranking by urgency (due or overdue) × impact (safety, revenue, tenants affected), so that critical work is done first.
61. As an estate manager, I want to know whether a specific follow-up (e.g. TSK-2026-0452 for Lucky Star) is overdue, so that I can act at once.
62. As an estate manager, I want a scheduled digest of my outstanding tasks, prioritised and explained, so that I'm told without having to ask.
63. As a director, I want the priority rules to be explicit and explainable, so that the team trusts the ranking.

### Categorisation and summaries (AC3)

64. As a PLG officer, I want documents grouped into named categories automatically, so that I can browse by topic.
65. As a PLG officer, I want to ask "summarise all documents about rental arrears" and get a summary covering policy v1/v2, SOP-014, the circular, the training deck, the LOD, the ageing report and the emails, so that I can catch up on a topic quickly.
66. As a PLG officer, I want category filters to improve search results, so that retrieval is more precise.

### Corpus audit: conflicts, duplicates and gaps (AC4)

67. As a policy officer, I want a report of documents that conflict (C1–C6), each with both sides cited and the expected resolution, so that I can fix the outdated sources.
68. As a policy officer, I want near-duplicates and copies detected (SOP-011 v1.0/v1.1, the two FAQs, the circular PDF and its txt copy), so that I can retire redundant versions.
69. As a data analyst, I want domain-rule violations found in the data (overlapping tenancies, two current policy versions, an SOP implementing a superseded policy, a trade not allowed for its unit type, duplicate tenants), so that data quality improves.
70. As a finance manager, I want record-vs-source mismatches surfaced (e.g. Heng Ann rent S$4,850 in the DB vs S$4,580 in the agreement), so that over-billing is corrected.
71. As a policy officer, I want reports that use a superseded definition flagged (e.g. the QBR vacancy figure), so that management reporting stays consistent.
72. As a manager, I want gaps found from questions the assistant answered poorly, so that I know which knowledge areas need more documentation.

### Data refresh and integration (DC7)

73. As a system owner, I want `sync` to pull only new and changed content from SharePoint and Lotus Notes (by content hash), so that the index stays current without full rebuilds.
74. As a system owner, I want sync to be schedulable from the CLI, so that it can run unattended.
75. As a system owner, I want superseded and effective-date metadata set correctly at ingestion, so that answers never cite superseded clauses as current.
76. As a system owner, I want source integrations behind adapters, so that the mocks can be replaced by real SharePoint, Lotus Notes and i-EMS connectors without changing the agents.

### Guardrails and human-in-the-loop (SYS)

77. As a system owner, I want prompt injections in user input *and* in ingested emails detected and refused (e.g. the planted refund-request email), so that attackers can't trigger actions.
78. As a system owner, I want specialist agents limited to read-only tools, so that the model cannot cause side effects even if it is manipulated.
79. As a system owner, I want every side-effecting action to go through an explicit approve / edit / reject step, so that riskier actions always get human review.
80. As an auditor, I want every approval, rejection and executed action written to an audit log linked to the trace, so that decisions are accountable.
81. As an auditor, I want proof that no action was ever executed without a matching approval, so that the control is verifiable.

### Memory (SYS learning)

82. As a PLG officer, I want the assistant to remember my role, towns and preferred output format across sessions, so that I don't repeat myself.
83. As a PLG officer, I want to be reminded of my unfinished work from earlier sessions (e.g. an LOD awaiting approval), so that nothing falls through the cracks.
84. As a PLG officer, I want to list, view, edit and forget what the assistant remembers about me, so that I stay in control of my data.
85. As a PLG officer, I want to ask "why do you think that?" about a remembered fact and see where it came from, so that I can trust it or correct it.
86. As a PLG officer, I want my memories to be invisible to other users, so that my work stays private.
87. As a curator, I want proposed team-wide facts and examples to need my approval before they go live, so that shared knowledge stays correct.
88. As a system owner, I want memories extracted only from users' own turns and verified outputs, never from ingested documents or emails, so that memory can't be poisoned.
89. As a system owner, I want any memory that conflicts with current policy to lose and be flagged for retirement, so that stale memories never override cited sources.

### Learning loop and glossary governance (D19, D22)

90. As a PLG officer, I want to give thumbs up or down and corrections on answers, so that the assistant improves.
91. As a curator, I want thumbs-down answers queued for review and corrected answers promoted to examples and datasets, so that fixes stick.
92. As a glossary owner, I want to propose, approve and version changes to business terms, with the old version kept as superseded, so that definitions change in a controlled, auditable way.
93. As a glossary owner, I want each term's SQL binding validated against the database when the term changes, so that a definition change can't break queries.

### Evaluation and observability (D20)

94. As a developer, I want every graph run, node, Claude call, tool call and approval traced, so that I can debug and explain behaviour.
95. As a developer, I want golden datasets for each capability and end to end, seeded from `_master` ground truth and the 28 sample questions, so that quality is measured, not guessed.
96. As a developer, I want experiments comparing models, prompts and retrieval settings side by side, so that I can choose the best configuration on evidence.
97. As a developer, I want a pytest regression gate on every change, so that regressions are caught before demo.
98. As a sponsor, I want a metrics report (accuracy by capability, latency p95, cost per query, guardrail results), so that I can judge whether the POC meets its targets.
99. As a system owner, I want PII masked in traces, so that tenant data isn't exposed in the tracing platform.

### Future migration

100. As a platform owner, I want search and graph storage behind interfaces with contract tests, so that moving from embedded LanceDB/networkx to Amazon OpenSearch/Neptune is a configuration change plus a new adapter.
101. As a platform owner, I want all LLM calls behind one client seam, so that Claude can be swapped for an on-prem open-weight model if the data is classified Sensitive-High.

## Implementation Decisions

### Architecture

- **Orchestration:** a LangGraph `StateGraph` is the single front door. It handles deterministic routing edges, `Send()` fan-out to specialists, fan-in merge, `interrupt()` for approval, and a checkpointer thread per session (SQLite for the POC).
- **Agent runtime:** each specialist is a LangGraph node that runs a native Anthropic SDK tool-use loop through one shared `run_agent(system, tools, messages, model)` helper. It loops on `tool_use`, runs read-only tools (in parallel where possible), prompt-caches the system prompt and tools, and returns a compact `AgentResult`. Agents are leaf nodes and never orchestrate each other.
- **Model tiers (configurable per node):** Haiku 5.5 for screening, routing, defect classification, summarisation and memory extraction. Sonnet 5.5 for the knowledge, data and drafting agents, merge and PDF document identification. Opus 5.5 for hard analysis, the corpus-audit judge and the eval judge.

### Graph nodes

`screen_input` → `load_memory` → `summarise_history` (conditional) → `route` → fan-out to `knowledge` | `data` | `drafting` | `defect_flow` (subgraph) | `doc_check_flow` (subgraph) | `tasks` → `merge` → `write_memory` (background) → `approval` (interrupt, only if there are proposed actions) → `execute_action`.

- `route` returns structured output: one or more intents from `knowledge`, `data`, `drafting`, `defect`, `doc_check`, `tasks`, `category_summary`, with sub-task decomposition. Low confidence leads to a clarifying question.
- `knowledge` answers in "policy stance" format with Claude Citations, passing retrieved chunks as `document` blocks with citations enabled.
- `data` emits a `SqlTrace`: plan → SQL → result summary → explanation, including the glossary concept ID and version applied.
- `drafting` selects an approved template, fills slots with read-only lookups, validates them and renders the document. Sending becomes a `ProposedAction`.
- `defect_flow`: classify (taxonomy code, severity, team, vendor, confidence, rationale) → build i-EMS payload → `ProposedAction`. Ambiguous cases take the higher severity and are escalated for low confidence.
- `doc_check_flow`: load the application and its type's checklist → identify each submitted file (Claude PDF input, including scans) → diff against the checklist, with expiry, wrong-unit (via application → unit → tenancy) and legibility checks → draft a TPL-DOC-02 notice → `ProposedAction`.
- `tasks`: a deterministic rules matrix (urgency × impact) over the tasks table, with a short Haiku-written rationale.

### Graph state (shape from the solution sketch)

```python
class PLGState(TypedDict):
    messages: Annotated[list, add_messages]
    user: UserCtx
    intents: list[Intent]
    results: Annotated[list[AgentResult], operator.add]   # parallel fan-in
    citations: list[Citation]
    sql_traces: list[SqlTrace]
    proposed_actions: list[ProposedAction]
    approvals: list[ApprovalDecision]
    answer: str | None
    history_summary: str | None
    memory: MemoryContext
```

### Application facade (main test seam)

A single `PLGApp` facade wraps the compiled graph and the jobs. The CLI (`plg ask | approve | sync | digest | audit | categorise | memory | glossary`), the demo notebook, the pytest suite and the LangSmith evals all go through it.

- `ask(question, user, thread_id)` → `Response` (answer, citations, sql_traces, proposed_actions, status `answered | needs_clarification | awaiting_approval`, visited nodes, run_id)
- `resume(thread_id, decision)`, where decision is approve / edit(payload) / reject per action → `Response`
- `run_job(name, **opts)`, where name is `sync | categorise | corpus_audit | task_digest` → a job report
- The facade is built from injected dependencies: `LLMClient`, `Embedder`, `SearchStore`, `GraphStore`, `DocumentSource`s, `TicketSystem`, `Outbox`, `MemoryStore` and config. The default wiring uses the real embedded stores and the mock adapters.

### Safety boundary (enforced in code)

- Specialist tools are read-only: hybrid search, SQL over a read-only DuckDB connection with a validator, fixed `GraphStore` methods over a frozen graph, template render to a draft, and record lookup.
- Side effects (send email or letter, create an i-EMS ticket, update a record) exist only as `ProposedAction`s in state. They are executed only by `execute_action`, which is reachable only through the `approval` interrupt. Those tools are not in any model's toolset.
- Input screening covers user text and ingested email content. Drafts get a PII check before approval. Approvals and executions are written to an audit log with the LangSmith `run_id`.

### Knowledge stores

- **Search (`SearchStore`):** LanceDB embedded, in `.plg/lancedb/`, git-ignored and rebuilt by `sync`. Tables:
  - `chunks`: structure-aware chunks with a contextual header and metadata: `doc_id`, `doc_type`, `policy_id`, `version`, `effective_from/to`, `status`, `town`, `nc`, `trade`, `category`, `entity_ids`, `source_system`, `content_hash`.
  - `entities`: name variants mapped to graph node ids.
  - `memory`

  Hybrid FTS + vector search with a linear-combination reranker and metadata pre-filters, then a cross-encoder rerank. Embeddings come from the Voyage AI `Embedder`. The `_master/` folder is never indexed.
- **Graph (`GraphStore`):** networkx `MultiDiGraph` loaded from canonical CSVs in Neptune openCypher bulk-load format under `.plg/graph/`, frozen for readers.
  - Fixed read methods: `policy_lineage(policy_id)`, `find_precedents(trade, nc, issue)`, `entity_context(id, hops≤2)`, `resolve_entities(text)` (with the `entities` table).
  - All writes go through a single `GraphWriter`. It validates against the ontology allow-list, appends to delta CSVs under a file lock and swaps in a newly frozen graph.
  - The graph holds entities, relationships and document links only. Counts and aggregates always come from DuckDB.
- Each `GraphStore` method has a matching parameterised openCypher template for the future `NeptuneGraphStore`. Neptune data rules (string business IDs as `~id`, scalar properties, one label per node, `UPPER_SNAKE` edge types, plain openCypher) are lint-checked.

### Structured data

- DuckDB attaches `poc-data/plg_records.db` read-only and loads `poc-data/sheets/*.xlsx` as tables at ingestion, with cleaning rules for merged headers, notes rows, text-typed dates and formula cells without cached values. The `_database.md` conventions (TEXT dates, REAL money, 1/0 booleans) go into table notes.
- A semantic layer binds glossary concept IDs to SQL predicates and metrics (e.g. `plg:Vacant_v2` → not Not Lettable / Under Tender and no active tenancy at `:as_of`, defaulting to 2026-09-30), plus example queries.

### Ontology and glossary

- A LinkML ontology (about 25 classes and 30 relations, with domain/range and cardinality) and SKOS-style vocabularies (trades, 8 defect categories with team, vendor and default severity, document types, application types with their required documents, unit statuses, letter types). These are seeded from `poc-data/_master/taxonomy_and_checklists.json`.
- The business glossary is part of the ontology as versioned `GlossaryTerm` instances (id, labels, definition, source citation, owner, effective dates, supersedes, status). Seed terms include: vacant, occupied, lettable, under tender, active tenancy, renewal window, arrears and age buckets, LOD, termination threshold, security deposit, display area, change of trade, A&A works, trade-mix limit, SLA breach, outstanding task, priority and complete application.
- A build step generates Pydantic models and extraction schemas, JSON Schemas for tools, the graph allow-list, the vocabulary/synonym index, the glossary index and a compact ontology card for system prompts. Validation checks unique labels, valid supersedes chains, and SQL bindings that pass a dry-run `EXPLAIN`.
- The ontology rule checker (overlapping tenancies, two current policy versions, an SOP implementing a superseded policy, a disallowed trade for a unit type, duplicate tenants) is used by `corpus_audit`.

### Memory

- **Short-term:** a checkpointer thread per session. `summarise_history` runs above a token threshold (about 40k) and always keeps entity IDs, open proposed actions and approval status verbatim. Agent scratchpads are discarded and full chunks and result sets go to traces only.
- **Long-term:** a `MemoryStore` implementing LangGraph `BaseStore` on the LanceDB `memory` table.
  - Kinds: profile, episodes, team facts, examples, plus `WORKED_ON` graph edges.
  - Each item carries provenance, confidence, expiry and status.
  - User namespaces are private. Team facts and examples need curator approval through the approval interrupt.
  - Memory is passed as a labelled context block and never used as a source.
  - Extraction uses only the user's own turns and verified outputs.
  - Episodes expire after 180 days, near-duplicates are merged and PII is masked.

### Adapters

`DocumentSource` (SharePoint mock over `poc-data/docs|pdfs|sheets|decks|…`, Lotus Notes mock over `poc-data/emails`), `TicketSystem` (i-EMS mock) and `Outbox` (mail and letters) are Python `Protocol`s. The mocks write tickets and outbox items to local files or tables so that tests can observe them.

### Background jobs

- `sync`: incremental by content hash, through the `DocumentSource` adapters. It sets effective-date and status metadata and rebuilds the affected graph edges.
- `categorise`: embedding clustering (HDBSCAN) plus LLM-named clusters. It writes the `category` metadata and `IN_CATEGORY` edges.
- `corpus_audit`: MinHash → vector-similarity candidate pairs → graph lineage checks → ontology rule check → Opus judge. It writes `CONFLICTS_WITH`/`DUPLICATE_OF` edges and a cited report. Gaps come from low-score question logs.
- `task_digest`: the rules-matrix ranking per officer, written to the console or a file.

### Tracing and evaluation

- LangSmith tracing is on from day one: graph spans automatically, Claude calls via `wrap_anthropic`, and tools and retrievers via `@traceable`. Runs carry metadata (`thread_id`, user, intents, model tier, git sha), and PII is masked through hide hooks.
- Feedback is recorded against the `run_id`. Thumbs-down runs go to an annotation queue.

## Testing Decisions

### What makes a good test

- Tests exercise **external behaviour only**: a question or command goes in through the public facade, and assertions are made on the observable response and the side effects the mock adapters record. Tests never assert on prompts, internal node functions, intermediate state shapes or private helpers. Refactoring inside the graph must not break them.
- Assertions use corpus ground truth (`poc-data/_master/*`, `_report.md` §2–§5), not hand-invented expectations.
- LLM-dependent quality is measured by **evals with scores and thresholds**, not brittle exact-string asserts.

### Seams (agreed)

1. **`PLGApp` facade (main seam).** Behind it, the real embedded stores (LanceDB, networkx, DuckDB over `plg_records.db` and the sheets), the checkpointer and the ontology run against the real `poc-data`. Only `LLMClient` and `Embedder` are swapped, and the mock adapters are inspected.
   - **Deterministic tier (pytest, every change):** scripted or recorded `LLMClient` and a fake `Embedder`. Covers:
     - routing and fan-out (the expected nodes are visited)
     - the approval gate (no `TicketSystem`/`Outbox` write without an approve decision; reject leaves nothing written; edit executes the edited payload)
     - pause and resume across separate facade instances on the same checkpoint
     - the SQL-trace shape and that it names the glossary version
     - read-only enforcement (write SQL rejected)
     - the planted injection email leading to no proposed actions and a flag
     - memory isolation between users, and no memory written from ingested emails
     - the summarisation threshold keeping open actions verbatim
     - job outputs (`sync` is idempotent on unchanged content; `corpus_audit` and `task_digest` reports have the expected structure)
     - deterministic numeric answers where the SQL is fixed by example queries, e.g. vacancy 47, Golden Leaf arrears S$22,672.00, bubble tea in NC-PI-1 = 2
   - **Eval tier (LangSmith, real Claude, same facade):** per-capability and end-to-end datasets seeded from the 28 sample questions, `_master/planned_conflicts.json`, `submission_bundles_ground_truth.json`, `key_entities.json` and `data_quality_issues.json`. Targets:
     - route ≥ 90% multi-label accuracy
     - knowledge ≥ 85% faithfulness, recall@5 against gold chunks, superseded-version avoidance
     - data ≥ 80% execution accuracy, and the explanation names the correct definition
     - drafting ≥ 90% slot accuracy
     - defect ≥ 85% macro-F1 for category and team, severity accuracy, low-confidence escalation
     - doc_check ≥ 90% missing-document recall
     - corpus_audit ≥ 80% recall of C1–C6
     - guardrails 100% (injection blocked; zero `execute_action` spans without an approval span)
     - glossary ≥ 90%
     - ontology: 100% validity, ≥ 80% rule recall
     - memory: 100% isolation

     End to end: trajectory check, answer correctness with citations, and latency p95 and cost per query. Judges use `openevals` with Opus 5.5, and the rubrics are pinned in the repo. A small subset runs as the pytest regression gate via the LangSmith pytest integration.
2. **`GraphStore` contract (second seam, because of the Neptune migration).** One contract suite of inputs and expected outputs per method, from `_master` ground truth (POL-003 lineage v1.0 → v2.0, Circular 07/2026 overriding POL-001 cl. 7.3 for NCs, the Mutiara/bubble-tea precedents, Golden Leaf's entity context). It runs against `LocalGraphStore` in CI and against `NeptuneGraphStore` at migration. It sits alongside the lint tests for the canonical CSVs and Cypher templates, and the ontology validation of every CSV row and extracted relation.

### Modules covered

Through the facade: front-door graph, all specialist nodes and subgraphs, guardrails, memory, adapters, jobs, semantic layer, ontology-derived artefacts. Through the contract suite: graph store backends. Nothing else gets its own test seam.

### Prior art

There's no existing test code in the repo (greenfield). Patterns to follow:

- `poc-data/_generator/verify.py`: ground-truth-driven checks over the corpus.
- LangSmith `evaluate()` and pytest integration patterns.
- LangGraph's documented interrupt and resume testing with a checkpointer.

## Out of Scope

- AWS infrastructure (OpenSearch domain, Neptune, S3, IAM, CDK) and running against the AWS backends. Only the interfaces, Cypher templates and contract tests are built.
- Real SharePoint, Lotus Notes (DXL / Domino REST) and i-EMS integrations. Mocks only.
- Actually sending email or letters or creating real tickets. The outbox and ticket mocks record intent only.
- An RDF triple store, SPARQL, OWL reasoning, or importing upper ontologies.
- Multi-user concurrent deployment, authentication/SSO, and a web UI. The POC is a single-process CLI and notebook.
- Self-hosted LangSmith or Langfuse for production, and PII handling for real tenant data.
- An on-prem open-weight model. Only the `LLMClient` seam that allows it is in scope.
- PLG validation of the invented artefacts (ontology, taxonomy, checklists, priority rules, glossary, templates). These are POC stand-ins.
- Fixing the source data. The assistant reports conflicts and data-quality issues but does not change records except through approved actions on mocks.

## Further Notes

- **Timeline (4 weeks):**
  - W1: ontology v1, glossary seed, generators; store interfaces, LanceDB store, LLM seam and agent loop; tracing; ingestion; knowledge node with citations; route → knowledge; datasets v1.
  - W2: graph build, Cypher templates, contract tests, graph tools; DuckDB, semantic layer, data node; drafting; fan-out and merge.
  - W3: approval, execute and adapters; defect_flow, doc_check_flow, tasks; memory; feedback.
  - W4: sync, categorise and corpus_audit jobs; full experiments and metrics report; online evaluators; demo notebook.
- **Key risks:**
  - Effective-date metadata must be correct at ingestion.
  - Routing errors (mitigated by the routing dataset and clarification).
  - Differences between the local and AWS backends (mitigated by contract tests and retuning).
  - LLM-extracted graph edges (mitigated by deterministic ID edges plus evidence chunks).
  - Single-process limits.
  - Memory staleness.
  - Ontology scope creep (time-box v1 to 2–3 days).
  - Trace data leaving the environment.
- **Corpus quirks to handle explicitly:**
  - xlsx formula cells have no cached values.
  - 9 image-only PDFs.
  - Duplicate tenant `T-19807`/`T-10514`.
  - Duplicated payment row `PAY-00001235`.
  - Inspection dated 2099.
  - Outlier rent on `TA-2022-00400`.
  - Duplicated ERP invoice rows.
  - Messy CRM names.
- `_master/` is ground truth for tests and evals only and must never be ingested into the retrieval index.
