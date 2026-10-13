# Spec: PLG "Super-Librarian" POC

> Source design: `docs/solution.MD` (selected solution, decisions D1–D23) · Requirements: `docs/REQ.md` · Corpus: `poc-data/` (seed 42, `_report.md`, `_scenario.md`, `_manifest.csv`)
>
> Tracking issue: https://github.com/shchoy/shchoy-hdb-agent-v2/issues/1

## Problem Statement

Officers in the Properties & Land Group (PLG) of the Housing & Estates Board manage about 1,500 commercial units: void-deck shops, neighbourhood-centre (NC) shops, eating houses and kiosks. Their knowledge is spread across sources that don't connect:

- policies, SOPs, circulars and templates in SharePoint
- years of email threads in Lotus Notes
- a scanned precedent compendium and scanned tenancy agreements
- a relational PLG Records database (tenancies, invoices, payments, inspections, feedback, applications, tasks, letters)
- a set of hand-maintained Excel trackers whose formulas have no cached values
- defect tickets in i-EMS

To answer something simple, like "when do we issue a letter of demand?", an officer has to know which policy version is current. They also have to know that the SOP still says 45 days although policy v2.0 moved it to 60. And they have to know that the circular overrides a clause of another policy. Numbers disagree between reports: the QBR says 52 vacant units and the monthly report says 47, because "vacant" was redefined in April 2026. That knowledge lives only in meeting minutes. Precedents are buried in a 12-page PDF. Drafting a reminder letter, a missing-documents notice or a reply to a feedback provider means copying figures from several systems by hand. Classifying public feedback and routing it to the right i-EMS team is manual and inconsistent. Checking whether an application bundle is complete means opening every PDF against a checklist. Officers have no single, prioritised view of their outstanding tasks. Nobody can see which documents conflict, duplicate each other or have gone stale.

Officers need one place to ask in plain language. They need answers that are correct, current and citable, that show their reasoning, and that never take a high-impact action, such as sending a letter or raising a ticket, without a human's approval.

## Solution

A "super-librarian" assistant that PLG staff use through a web app (and, for power users and scheduled jobs, a CLI):

- An officer asks a question in natural language. An AI front door works out what kind of question it is, which may be several kinds at once. It sends the question to the right specialists (policy and records knowledge, structured-data analysis, drafting, defect classification, document checking, task prioritisation, category summaries) and fuses their results into one streamed answer.
- Policy answers give PLG's **current stance**: the effective date, which versions were superseded and which circular overrides which clause. Every claim cites the exact source span, which the officer can open and see highlighted.
- Data answers show their **reasoning**: plan → SQL → result table → explanation. They name the business definition used (e.g. "vacant per glossary v2, effective 15 Apr 2026").
- Precedent questions return related past cases, matched by trade, NC and issue.
- Drafts are filled from approved templates with values looked up in the records.
- **Anything that leaves the system** (sending a letter or email, raising an i-EMS ticket, updating a record) is only *proposed*. The officer sees a preview, can edit it, and approves or rejects it. Only then does it happen, and it is audited.
- The assistant remembers the officer's preferences and past work across sessions. It never treats memory as a source of truth, and one officer's memory is never visible to another.
- Scheduled jobs keep the index fresh from SharePoint and Lotus Notes (mocked), categorise the corpus, produce task digests, and audit the corpus for conflicts, duplicates, stale documents and rule violations.

The POC runs entirely on a laptop with no servers or Docker. Search and graph storage sit behind interfaces so they can move to Amazon OpenSearch Service and Amazon Neptune later.

## User Stories

### Asking questions (front door)

1. As a PLG officer, I want to ask a question in plain English in a chat screen, so that I don't need to know which system holds the answer.
2. As a PLG officer, I want the answer to stream in as it is generated, so that I'm not staring at a blank screen during long questions.
3. As a PLG officer, I want to see which steps the assistant is running (e.g. route → knowledge + data → merge), so that I understand what it's doing and roughly how long it will take.
4. As a PLG officer, I want to ask a question with several parts (e.g. "how many vacant units in Bayshore Vale and how is vacancy defined?"), so that I get one fused answer instead of asking twice.
5. As a PLG officer, I want multi-part answers shown as sections, so that I can tell which part answers which question.
6. As a PLG officer, I want the assistant to ask me a clarifying question when my request is ambiguous, so that it doesn't confidently answer the wrong thing.
7. As a PLG officer, I want to ask follow-ups in the same conversation (e.g. "and for Cendana?"), so that I don't have to repeat context.
8. As a PLG officer, I want to leave and later reopen my past conversations, so that I can continue work across days.
9. As a PLG officer, I want long conversations to keep working, so that the assistant doesn't fail or forget key entities after many turns.
10. As a PLG officer, I want the assistant to use PLG's own terms (LOD, NC, A&A, void-deck shop), so that answers read like they came from a colleague.
11. As a PLG officer, I want the assistant to understand synonyms and abbreviations (e.g. "LOD" = letter of demand, "ceiling leak" = seepage), so that I can phrase questions naturally.
12. As a PLG officer, I want an error to be shown clearly if something fails mid-answer, so that I know to retry instead of trusting a partial answer.
13. As a PLG officer, I want my browser to recover a conversation after a dropped connection or refresh, so that I don't lose an in-progress answer or pending approval.

### Policy and records knowledge (DC2, DC3)

14. As a PLG officer, I want to ask what PLG's current stance is on a topic, so that I apply the policy that is in force today.
15. As a PLG officer, I want policy answers to state the current position, its effective date, the superseded versions and the sources, so that I can see how the position evolved.
16. As a PLG officer, I want the assistant to answer "60 days" for the letter-of-demand trigger (POL-003 v2.0), not the superseded 45 days, so that I don't act on an outdated rule.
17. As a PLG officer, I want the assistant to warn me when an SOP or guide contradicts the current policy (e.g. SOP-014 still says day 45), so that I know which document to distrust.
18. As a PLG officer, I want the assistant to know that Circular 07/2026 raised the display-area limit to 1.0 m for NC units only from 1 Aug 2026, while void-deck shops stay at 0.6 m, so that I enforce the right limit for each unit type.
19. As a PLG officer, I want to ask what the rule *was* at an earlier date (e.g. "LOD trigger before April 2026"), so that I can judge historical cases correctly.
20. As a PLG officer, I want every factual claim to carry a citation to the exact span in the source, so that I can verify it before relying on it.
21. As a PLG officer, I want to click a citation and see the source document with the cited span highlighted (PDF, DOCX, email or note), so that checking a claim takes seconds.
22. As a PLG officer, I want answers to tell me when the sources don't cover my question, so that I'm not given an invented answer.
23. As a PLG officer, I want to ask about records such as audit findings or incident reports (e.g. "what did internal audit find about rent master data?"), so that I can retrieve historical facts without searching folders.
24. As a PLG officer, I want to ask what we know about a specific tenant, unit or tenancy (its tenancies, units, open feedback, tickets, letters, and who worked on it), so that I get a complete picture before calling them.
25. As a PLG officer, I want questions that use tenant names, unit numbers or IDs (e.g. `TA-2024-00542`, "Golden Leaf") to resolve to the right entity, so that I can refer to things however I remember them.
26. As a PLG officer, I want security-deposit and renewal-lead-time answers to follow the policy (3 months' rent; at least 6 months before expiry) and to flag the outdated FAQ, guide and email, so that I give tenants consistent answers.
27. As a PLG officer, I want to ask what a business term means (e.g. "vacant") and how it was defined in an earlier period, so that I understand why reports disagree.

### Precedents (DC4)

28. As a PLG officer, I want to ask for precedents for a situation (e.g. change of trade to bubble tea in an NC), so that I can decide consistently with past decisions.
29. As a PLG officer, I want precedents matched by trade, NC and issue, with their outcome and reasoning, so that I can see why each was approved or rejected.
30. As a PLG officer, I want the assistant to explain how my current case differs from a precedent (e.g. a tenant-caused fire vs. PC-2025-019), so that I don't apply a precedent that doesn't fit.
31. As a PLG officer, I want precedents to cite the compendium page or email they came from, so that I can quote them in a memo.

### Structured data and analysis (DC5, DC6)

32. As a PLG officer, I want to ask numeric questions in plain English (e.g. "which tenancies have arrears above 3 months' rent?"), so that I don't need SQL or an analyst.
33. As a PLG officer, I want to see the plan, the SQL, the result table and a plain-English explanation for every data answer, so that I can check the reasoning.
34. As a PLG officer, I want the explanation to name the business definition used and its effective date, so that I know what "vacant" or "in arrears" meant in the calculation.
35. As a PLG officer, I want historical questions to use the definition in force at that time unless I ask otherwise, so that comparisons with old reports make sense.
36. As a PLG officer, I want the assistant to explain why two reports disagree (47 vs 52 vacant units at 31 Aug 2026), so that I can answer management confidently.
37. As a PLG officer, I want to query both the PLG Records database and the Excel trackers, so that I can use data held outside the database.
38. As a PLG officer, I want to copy the SQL and export a result table to CSV, so that I can reuse it in my own reports.
39. As a PLG officer, I want tenant-level answers such as "what are Golden Leaf's arrears now?" (amount, days, months of rent), so that I can act on a single case quickly.
40. As a data analyst, I want the assistant to warn me about known data-quality issues it hits (duplicate tenants, duplicated payments, impossible dates, outlier rents), so that I don't report wrong numbers.
41. As a PLG officer, I want numbers to always come from the database, never from memory or prose, so that figures are reproducible.
42. As a data analyst, I want generated SQL to be read-only and validated before it runs, so that the assistant can never change records.

### Drafting (DC1)

43. As a PLG officer, I want to ask for a standard document (arrears reminder, missing-documents notice, feedback update reply), so that I don't have to fill templates by hand.
44. As a PLG officer, I want the assistant to choose the right approved template and fill every slot from the records, so that the draft is accurate and on-brand.
45. As a PLG officer, I want to be told when a slot can't be filled, so that I can supply the value instead of sending an incomplete letter.
46. As a PLG officer, I want to see an HTML preview of the draft and download it as DOCX, so that I can review and file it.
47. As a PLG officer, I want to edit slot values before approving, so that I can correct details without regenerating.
48. As a PLG officer, I want drafts checked for personal data that shouldn't be there before I approve them, so that we don't leak tenant information.
49. As a PLG officer, I want drafting never to send anything by itself, so that no letter reaches a tenant without my sign-off.

### Approvals and actions (SYS HITL, D11)

50. As a PLG officer, I want every outbound action (send email or letter, raise i-EMS ticket, update a record) to wait for my approval, so that high-impact actions are always reviewed by a human.
51. As a PLG officer, I want an approvals inbox listing all my pending actions across conversations, so that nothing waits forgotten.
52. As a PLG officer, I want a diff-style preview of each proposed action (letter text, ticket payload), so that I know exactly what will happen.
53. As a PLG officer, I want to approve, edit or reject a proposed action, with a reason for a rejection, so that my decision and rationale are recorded.
54. As a PLG officer, I want pending approvals to survive a browser restart or a server restart, so that I can approve tomorrow what was drafted today.
55. As a PLG officer, I want to see the result of an approved action (outbox item, ticket ID) and its audit trail, so that I can confirm it happened.
56. As an approver, I want only people with the right role to approve each action type, so that, for example, an officer without authority can't send a letter of demand.
57. As an auditor, I want every approval and every executed action logged with who, when, what and a link to the full reasoning trace, so that decisions are accountable.
58. As an auditor, I want it to be impossible for an action to execute without a matching approval, so that the human-in-the-loop guarantee holds.
59. As an approver, I want my approval to apply only to the exact version of the action I saw, so that a changed or replayed request can't approve something else.

### Defect classification and routing (AC1)

60. As a customer relations officer, I want to paste a feedback text and have it classified into the defect taxonomy (category, severity, team, confidence, rationale), so that routing is consistent.
61. As a customer relations officer, I want an i-EMS ticket payload prepared for the right team and vendor with the SLA for its severity, so that I only need to approve it.
62. As a customer relations officer, I want ambiguous or multi-category feedback (e.g. a wet ceiling plus flickering lights) flagged as low confidence and resolved to the higher-severity category, so that safety issues aren't under-classified.
63. As a customer relations officer, I want non-defect complaints recognised as such, so that they aren't sent to maintenance teams.
64. As a maintenance coordinator, I want raised tickets to appear in i-EMS (mock) with a link back to the feedback case, so that I can track them.

### Document completeness (AC5)

65. As a leasing officer, I want to pick an application (or upload its bundle) and see a checklist with ✓/✗ for each required document, so that I can tell at a glance whether it's complete.
66. As a leasing officer, I want the assistant to identify what each submitted file actually is, including scanned PDFs, so that misnamed files are still recognised.
67. As a leasing officer, I want expired documents (e.g. insurance ending before the new term), documents for the wrong unit and illegible scans flagged, so that I don't accept invalid submissions.
68. As a leasing officer, I want a missing-documents notice drafted from the approved template, listing exactly what's missing or invalid, so that I can notify the tenant promptly.
69. As a leasing officer, I want that notice to go through approval before it reaches the tenant, so that I can check it first.
70. As a leasing officer, I want checklists to follow the application type (new tenancy, renewal, assignment, change of trade, A&A), so that each type is checked against the right rules.

### Tasks (AC2)

71. As an estate manager, I want to ask "what are my top 5 tasks this week and why?", so that I focus on what matters most.
72. As an estate manager, I want tasks ranked by urgency × impact with a short explanation for each, so that I trust the ranking.
73. As an estate manager, I want overdue tasks clearly marked (e.g. the Lucky Star subletting follow-up), so that nothing critical slips.
74. As a PLG officer, I want a scheduled task digest written to a file or the console, so that I'm notified without opening the app.
75. As a team lead, I want to see another officer's top tasks if my role allows it, so that I can rebalance work.

### Categories and corpus audit (AC3, AC4)

76. As a PLG officer, I want documents grouped into named categories, so that I can browse related material.
77. As a PLG officer, I want to ask for a summary of all documents in a category (e.g. rental arrears), so that I can get up to speed on a topic quickly.
78. As a policy owner, I want a report of conflicting documents with both sides cited and the expected resolution, so that I can fix the outdated one.
79. As a policy owner, I want near-duplicate and copy documents identified (SOP-011 v1.0/v1.1, the two FAQs, the circular PDF and its text copy), so that we can retire redundant versions.
80. As a policy owner, I want SOPs that still implement a superseded policy flagged as stale, so that procedures are updated after policy changes.
81. As a data owner, I want ontology rule violations in the data reported (overlapping tenancies, two current policy versions, a trade not allowed for its unit type, duplicate tenants), so that data quality issues are visible.
82. As a policy owner, I want reports that use a superseded business definition flagged (e.g. the QBR vacancy figure), so that management sees consistent numbers.
83. As a policy owner, I want gaps highlighted (questions the corpus answers poorly), so that we know where documentation needs to be written.

### Data refresh and integration (DC7)

84. As a system administrator, I want an incremental sync from SharePoint and Lotus Notes (mocked) that only re-processes changed documents, so that the index stays current cheaply.
85. As a system administrator, I want sync, categorise, audit and digest to run as CLI commands that can be scheduled, so that freshness doesn't depend on someone remembering.
86. As a system administrator, I want superseded documents marked as superseded rather than deleted, so that historical questions still work.
87. As a system administrator, I want source systems behind adapters, so that real SharePoint, Lotus Notes and i-EMS connectors can replace the mocks without changing the agents.

### Memory (D21)

88. As a PLG officer, I want the assistant to remember my role, towns and output preferences (e.g. tables, current quarter by default), so that I don't restate them every time.
89. As a PLG officer, I want it to remember what I worked on before ("what did we do last time with this tenant?"), so that I can pick up where I left off.
90. As a PLG officer, I want to list, view, edit and forget my memories, and see where each came from, so that I stay in control of what it knows about me.
91. As a PLG officer, I want my memories to be private to me, so that colleagues can't see my sessions or preferences.
92. As a curator, I want team-wide facts and examples proposed by the system to wait for my review before they go live, so that one person's mistake doesn't spread.
93. As a PLG officer, I want a memory that conflicts with current policy to lose and be flagged, so that stale beliefs never override sources.
94. As a security officer, I want memories never extracted from ingested emails or documents, so that a planted instruction can't poison the assistant.

### Business glossary and ontology (D22)

95. As a policy owner, I want one versioned definition per business term, with source, owner and effective dates, so that "vacant" means the same thing in SQL, retrieval and answers.
96. As a policy owner, I want to propose a glossary change and have the term owner approve it through the same approval flow, so that definitions change in a controlled, audited way.
97. As a developer, I want graph labels, edge types, extraction schemas, synonyms and validation rules generated from one ontology, so that nothing outside the model can enter the graph.

### Safety and guardrails (SYS)

98. As a security officer, I want prompt-injection attempts in user text and in ingested emails detected and ignored, so that the assistant never follows instructions planted in a tenant email.
99. As a security officer, I want flagged injection attempts reported to the user, so that suspicious messages are escalated.
100. As a security officer, I want model output and document text rendered without raw HTML, so that a malicious email can't run script in an officer's browser.
101. As a security officer, I want the browser to hold no model, search or database credentials, so that a compromised client can't reach the back end directly.
102. As a security officer, I want user A to be unable to open user B's conversations, approvals or memories, so that isolation holds.
103. As a security officer, I want tenant personal data masked in traces, so that observability doesn't leak PII.

### Feedback and learning (D19)

104. As a PLG officer, I want to give 👍/👎 and corrections on any answer, so that the assistant improves.
105. As a curator, I want thumbs-down answers queued for review, and corrected answers promoted into examples, so that verified fixes feed future answers.
106. As a data analyst, I want verified question → SQL pairs reused as few-shot examples, so that similar questions get better SQL.

### Sign-in and personas (POC)

107. As a demo presenter, I want to sign in as any staff persona (e.g. Estate Manager East, Ops Analytics), so that I can show role-based approvals and memory isolation.
108. As a demo presenter, I want sign-in kept in an httpOnly session cookie, so that the demo reflects a realistic security posture.

### Observability and evaluation (D20)

109. As a developer, I want every run, node, model call, tool call, interrupt and resume traced with thread, user, intents and git SHA, so that I can debug any answer.
110. As a developer, I want a "view trace" link on each answer (developers only), so that I can jump from the UI to the reasoning.
111. As a developer, I want golden datasets per node and end-to-end, seeded from the corpus ground truth, so that I can measure quality and compare model tiers and prompts.
112. As a developer, I want a pytest regression gate that runs on each change, so that quality regressions are caught early.

### Accessibility and operability

113. As a PLG officer using assistive technology, I want the web app to meet WCAG 2.1 AA, so that I can use it fully.
114. As a developer, I want to run the whole POC locally with a single API process and the web dev server, with no Docker, so that setup is quick.
115. As a developer, I want the search and graph stores behind interfaces, with contract tests every backend must pass, so that migrating to OpenSearch and Neptune is mechanical.

## Implementation Decisions

### Architecture

- **Three layers, one owner of logic.** (1) A TypeScript Next.js web app with a backend-for-frontend (BFF), (2) a thin Python FastAPI service (`plg serve` / `plg-api`) and (3) a LangGraph `StateGraph` that owns all AI behaviour. The web app is presentation only. The API only adapts HTTP to the graph and stores. The graph knows nothing about HTTP. The CLI, notebook and web app all drive the same graph.
- **Front door graph:** `screen_input` → `load_memory` → `summarise_history` (conditional) → `route` → `Send()` fan-out to specialists → `merge` → `write_memory` (background) → if there are proposed actions, `approval` (`interrupt()`) → `execute_action`.
- **Specialists:** `knowledge`, `data` and `drafting` are agent nodes. `defect_flow` and `doc_check_flow` are subgraphs. `tasks` is deterministic, with an LLM-written rationale. `category_summary` is served from the categorisation output.
- **Agent runtime:** each agent node runs a native Anthropic SDK tool-use loop through one shared helper, `run_agent(system, tools, messages, model)`. It loops while `stop_reason == "tool_use"`, runs read-only tools (in parallel where asked), prompt-caches the system prompt and tools, and returns a compact `AgentResult` (text, citations, SQL traces, proposed actions). Its scratchpad is discarded when the node finishes.
- **Model tiers (config-driven):** Haiku 5.5 for screening, routing, defect classification, summarisation and memory extraction; Sonnet 5.5 for the agents, merge and PDF document identification; Opus 5.5 for hard analysis, the corpus-audit judge and LLM-as-judge evals. Model IDs live in config.
- **`LLMClient` seam:** the only path to Claude, created through LangSmith's `wrap_anthropic`. It is the test seam (scripted in tests) and the on-prem swap point.

### Graph state and core types

- `PLGState` holds: `messages` (append), `user` (`UserCtx`), `intents`, `results` (parallel fan-in, append), `citations`, `sql_traces`, `proposed_actions`, `approvals`, `answer`, `history_summary` and `memory` (`MemoryContext`).
- `Intent` is a multi-label set drawn from `knowledge`, `data`, `drafting`, `defect`, `doc_check`, `tasks` and `category_summary`, with confidence. Low confidence produces a clarifying question instead of a fan-out.
- `ProposedAction` has a stable ID and a **version**, an action type (send email, send letter, create i-EMS ticket, update record, approve glossary term, approve team fact), a payload, a preview and the required approver role.
- `ApprovalDecision` = `{action_id, version, decision: approve|edit|reject, edits?, reason?, approver}`.
- `SqlTrace` = plan, SQL, result summary, explanation, and the glossary concept IDs and versions used.
- `Citation` = document ID, chunk ID, cited span and location for highlighting.

### Safety boundary (enforced in code)

- Specialists receive **read-only tools only**: search, SQL on a read-only DuckDB connection, fixed `GraphStore` methods over a frozen graph, template render to a draft, and record lookup.
- Side effects exist only as `ProposedAction`s in state. `execute_action` is reachable only through the `approval` interrupt. No tool that performs a side effect is ever in a model's toolset.
- `plg-api` resumes an interrupt only if the caller owns the thread, holds the approver role for that action type, and supplies the exact `action_id` and `version` that are pending.
- `screen_input` screens user text, and ingested emails are screened at ingestion. Detected injections are flagged and their instructions are never followed. Drafts get a PII check before approval. Every approval and action goes to an append-only audit log that includes the LangSmith `run_id`.

### Knowledge stores

- **`SearchStore` interface.** The POC uses embedded LanceDB, with the OpenSearch adapter later. It has three tables:
  - `chunks`: structure-aware chunks with contextual header, FTS text, vector and metadata (`doc_id`, `doc_type`, `policy_id`, `version`, `effective_from/to`, `status` current/superseded, `town`, `nc`, `trade`, `category`, `entity_ids`, `source_system`, `content_hash`)
  - `entities`: name variants plus the graph node ID
  - `memory`: long-term memory items
- Hybrid search (FTS + vector, linear-combination reranking) with metadata pre-filters, then a local cross-encoder rerank. Embeddings come from Voyage AI behind an `Embedder` interface.
- **`GraphStore` interface.** The POC uses a frozen networkx `MultiDiGraph` loaded from canonical CSVs in Neptune's openCypher bulk-load format. The Neptune adapter comes later. Every method has a Python implementation and a matching parameterised openCypher template written in the same change. Fixed methods: `resolve_entities`, `policy_lineage`, `find_precedents`, `entity_context(id, hops ≤ 2)`, plus the lookups the doc-check and audit flows need. The LLM never writes graph queries.
- The graph holds entities, relationships and document links only. Every count and aggregate comes from DuckDB.
- All graph writes (`graph_build`, `write_memory` → `WORKED_ON`, `corpus_audit` → `CONFLICTS_WITH`/`DUPLICATE_OF`, `categorise` → `IN_CATEGORY`) go through one `GraphWriter`. It validates writes against the ontology allow-list, appends delta CSVs under a file lock, and swaps in a newly frozen graph.
- Graph build: a deterministic entity spine from PLG Records and the strict ID regexes. Haiku extracts only `SUPERSEDES`, `OVERRIDES` and `APPLIES` (structured output), with an evidence chunk kept on every extracted edge.
- Neptune-compatible data rules: a string business ID for every node, scalar properties only, one label per node, `UPPER_SNAKE` edge types, and plain openCypher templates. A lint test checks these rules.

### Structured data

- DuckDB attaches the PLG Records SQLite database read-only and loads the Excel trackers as tables at ingestion. Cleaning rules handle merged or multi-row headers and text-typed dates. Formula cells have no cached values, so derived figures are computed from data sheets or static check rows.
- Semantic layer: SQL bindings keyed by glossary concept ID (e.g. `plg:Vacant_v2` → predicate over `units` and `tenancies` with an `as_of` parameter defaulting to 2026-09-30), plus table notes (TEXT dates, REAL money, 1/0 booleans) and example queries.
- The `data` agent emits plan → SQL → result → explanation. SQL is validated (read-only, allowed tables, `EXPLAIN` dry-run) before it runs.

### Ontology and glossary

- One LinkML ontology (~25 classes, ~30 relations with domain → range and cardinality) and SKOS-style vocabularies: trades, 8 defect categories with team, vendor and default severity, document types, application types with required documents, unit statuses and letter types. Vocabularies are seeded from the taxonomy and checklist ground truth.
- The business glossary lives inside the ontology as versioned `GlossaryTerm`s (id, labels, definition, source citation, owner, effective dates, supersedes, status). Seed terms are listed in the design (vacant, arrears buckets, LOD 60 days, display area 1.0 m, etc.).
- `make ontology` generates Pydantic models and extraction schemas, JSON Schema for tool I/O, the graph allow-list, the vocabulary index (synonyms), the glossary index and a compact ontology card for system prompts. It validates the `supersedes` chains and dry-runs every SQL binding.
- Ontology rule check (used by corpus audit): overlapping tenancies on a unit, two current versions of one policy, an SOP implementing a superseded policy, a trade not allowed for its unit type, and duplicate tenants.
- Glossary changes are proposed (`status: proposed`), approved by the term owner through the approval interrupt, and never deleted. The old version gets `effective_to` and `superseded`.

### Memory

- **Short-term:** a LangGraph `SqliteSaver` checkpointer with one thread per session. When `messages` exceed a token threshold, `summarise_history` folds older turns into `history_summary`. Entity IDs, open proposed actions and approval status are always kept verbatim.
- **Long-term:** a `MemoryStore` implementing LangGraph's `BaseStore` on the LanceDB `memory` table. Kinds: user profile (seeded from `staff`), user episodes (expire after 180 days), team facts (curated), few-shot examples per agent (curated), and `WORKED_ON` graph links. Every item carries provenance, confidence, expiry and status (active, pending_review, retired).
- Memory is passed as a labelled context block. It is never a citable source, and it loses to current policy. It is extracted only from the user's own turns and verified system outputs. PII is masked and near-duplicates are merged.

### Adapters and jobs

- Python `Protocol` adapters: `DocumentSource` (SharePoint mock, Lotus Notes mock, reading the corpus folders), `TicketSystem` (i-EMS mock, writing to local storage) and `Outbox` (mail and letters, writing to local storage).
- CLI: `plg ask | serve | sync | approve | digest | audit | categorise | memory | glossary`.
- `sync`: incremental by content hash. Superseded versions are marked, never deleted.
- `categorise`: embedding clustering (HDBSCAN) with LLM-named clusters. It writes the category to chunk metadata and `IN_CATEGORY` edges.
- `corpus_audit`: MinHash → vector-similarity candidate pairs, plus graph lineage checks and the ontology rule check, judged by Opus. It writes `CONFLICTS_WITH`/`DUPLICATE_OF` edges and a report with citations on both sides. Gaps come from low-score question logs.
- `task_digest`: the rules matrix (urgency × impact) over `tasks`, written to console or file.

### API contract (`plg-api`, OpenAPI 3.1)

- `POST /threads`, `GET /threads` (own threads only), `GET /threads/{id}` (history, pending approvals and summary, rebuilt from the checkpoint).
- `POST /threads/{id}/runs` → SSE stream. Event types: `node`, `token` (merge node only), `citation`, `sql_trace`, `proposed_action`, `interrupt`, `done` (with `run_id`) and `error`. Every event carries a sequence number. The stream sends heartbeat comments.
- `POST /threads/{id}/resume` → SSE stream, taking `{action_id, version, decision, edits?, reason?}`.
- `GET /approvals?status=pending`. Curators also see team-fact and glossary proposals.
- `GET /documents/{doc_id}` and `GET /documents/{doc_id}/chunks/{chunk_id}` (source file and span location).
- `GET / PATCH / DELETE /memory/...`, `POST /feedback`, `GET /tasks/digest`, `GET /audit/reports/latest`, `GET /categories`.
- Event payloads are Pydantic models published in OpenAPI. The web app generates its TypeScript types and client from the OpenAPI document and validates SSE frames with zod.
- POC identity: the BFF's mock sign-in picks a `staff` persona, stores it in an httpOnly cookie and forwards `X-PLG-User` over loopback. `plg-api` builds `UserCtx` (including role) from it. Production uses Entra ID OIDC with a signed token.

### Web app

- Screens: Ask (streaming chat, node trajectory, sections), Sources panel (PDF span highlight, rendered DOCX/email/MD, policy-stance cards, glossary definitions), Reasoning panel (SqlTrace with copy and CSV export), Approvals inbox (diff preview, editable slots, approve/edit/reject with reason, audit trail), Draft preview (HTML + DOCX download), Document check, Tasks, Library (categories, audit findings), Memory (with curator queue) and Feedback (👍/👎, correct this).
- Markdown is rendered with no raw HTML. BFF route handlers use the Node runtime with buffering off.

### Tracing

- LangSmith traces every node, `Send()` branch, interrupt, resume, Claude call (`wrap_anthropic`) and tool or retriever call (`@traceable`). Metadata: thread, user, intents, model tier, git SHA, channel. PII is masked before upload. Feedback goes to `create_feedback(run_id, …)`, and thumbs-down runs go to an annotation queue.

## Testing Decisions

### What makes a good test

- A test exercises **external behaviour through a seam** and asserts on observable outcomes: the SSE events a client receives, items in the outbox, tickets in the i-EMS mock, audit-log entries, HTTP status codes, and rendered UI. It must not assert on internal node names (except where the trajectory is itself a product feature), prompt text, private helpers or how state is shaped internally.
- Tests are **deterministic**. The only test double at the primary seam is a **scripted `LLMClient`**: it returns pre-recorded or hand-written Claude responses (including tool-use turns) keyed by node and input. Everything else is real: LanceDB, networkx, DuckDB over `poc-data`, the checkpointer, and the adapter mocks writing to a temp directory.
- Expected values come from the corpus ground truth (`_master/`, `_report.md` §2–§5), not from re-running the code under test.
- One behaviour per test, named after the user-visible behaviour (e.g. "LOD question cites POL-003 v2.0 and flags SOP-014").

### Seams (agreed with the user)

1. **Primary: the `plg-api` HTTP contract.** In-process FastAPI test client, scripted `LLMClient`, stores built once per session from `poc-data`. This one seam covers routing and fan-out, specialists, merge, the safety boundary, approvals and resume, memory isolation, the injection guardrail, documents, feedback and the read-only views. Representative cases:
   - Multi-intent question → both sections present, `citation` and `sql_trace` events emitted, `done` carries a `run_id`.
   - Policy question → citations point at POL-003 v2.0 chunks, not v1.0. Display-area answer distinguishes NC from void-deck units.
   - Data question → `sql_trace` names glossary `Vacant_v2`, and the SQL executes on the read-only connection. An attempted write is rejected by the validator.
   - Drafting, defect and doc-check flows → `proposed_action` + `interrupt`, with nothing in the outbox or i-EMS mock until `/resume` approves. A reject leaves nothing. An edit sends the edited version.
   - `/resume` with a wrong version, a replayed action ID, a non-owner or the wrong role → rejected with no side effect. The audit log contains exactly one entry per executed action, each with an approval.
   - The planted injection email (`suspicious_refund_request`) → flagged, no proposed actions, no executed actions.
   - User A cannot list, read, resume or see memories of user B's threads.
   - A thread survives an API restart: `GET /threads/{id}` rebuilds history and the pending approval from the checkpoint.
   - Doc-check against the 20 submission bundles → the missing and problem documents match the bundle ground truth (with scripted document identification for scans).
   - Deterministic logic is exercised through this seam with no LLM involvement: task ranking, SQL validation and ontology rule checks.
2. **Web: the OpenAPI/SSE contract.** Vitest + React Testing Library with MSW replaying recorded SSE streams captured from seam 1, so the UI is tested with no back end. Playwright e2e against `plg serve` with the scripted `LLMClient` covers: ask with citations, follow-up in the same thread, approve and reject an LOD, the injection email rendered as inert text, user A blocked from user B's thread. `@axe-core/playwright` checks for zero serious WCAG 2.1 AA violations. CI regenerates the OpenAPI types and fails on drift.
3. **`GraphStore` contract tests.** For every method, inputs and expected outputs come from `_master` ground truth: POL-003 lineage, Circular 07/2026 overriding POL-001 cl. 7.3, the bubble-tea precedents for NC-PI-1, and Golden Leaf's entity context. The same suite runs against `LocalGraphStore` in CI and against `NeptuneGraphStore` at migration (optionally a local Neo4j). A lint test enforces the Neptune data rules and ontology validity on the CSVs and Cypher templates.
4. **Model quality: LangSmith evaluations** (not pass/fail unit tests). Golden datasets per node plus end-to-end, seeded from `_report.md` §5 (28 questions), `planned_conflicts`, `submission_bundles_ground_truth`, `data_quality_issues` and `key_entities`, running real Claude. POC targets: route ≥ 90% intent accuracy; knowledge ≥ 85% faithfulness; data ≥ 80% execution accuracy; drafting ≥ 90% slot accuracy; defect ≥ 85% macro-F1; doc-check ≥ 90% recall; corpus-audit ≥ 80% recall of C1–C6; glossary ≥ 90%; ontology 100% validity and ≥ 80% rule recall; guardrails and memory isolation 100%. A small subset runs as a pytest regression gate using the LangSmith pytest integration.

### Prior art

- There is no code in the repo yet, so there are no existing tests to copy. The corpus generator's verification checks (`_report.md` §6) are the closest precedent: they assert against ground truth rather than implementation. Test fixtures should reuse the same ground-truth sources.

## Out of Scope

- AWS infrastructure and migration: Amazon OpenSearch Service, Amazon Neptune, ECS Fargate, ALB, CDK. Only the interfaces, Cypher templates, contract tests and CSV format that make migration mechanical are in scope.
- Real SharePoint, Lotus Notes (DXL / Domino REST) and i-EMS integrations. Mocks only.
- Production SSO (Entra ID / Auth.js). The POC uses mock persona sign-in.
- Real delivery of emails and letters. The outbox writes to local storage.
- Amazon Bedrock, open-weight or on-prem models. The `LLMClient` seam is kept but no alternative is implemented.
- RDF triple store, SPARQL, OWL reasoning and importing upper ontologies.
- Multi-worker or multi-user scale. The POC uses one API worker and embedded stores.
- Self-hosted LangSmith. The POC uses LangSmith Cloud with the synthetic corpus.
- Indexing the generator's ground truth (`_master/`). It is used only for tests and evals and must stay out of the retrieval index.
- PLG validation of the invented ontology, taxonomy, checklists, priority rules, glossary and templates.
- Writing back to PLG Records (e.g. correcting the Heng Ann rent). Such changes can be proposed as actions, but the record adapter is a mock.

## Further Notes

- **Suggested delivery order (4 weeks, from the design):**
  - Week 1: ontology v1 and glossary seed, `SearchStore` + LanceDB, `LLMClient` and `run_agent`, tracing, ingestion, the `knowledge` node with citations, `route` → `knowledge`, and `plg serve` threads/runs with the Ask and Sources screens.
  - Week 2: graph build, contract tests and graph tools, DuckDB + semantic layer + `data` node, `drafting`, fan-out and `merge`, and the Reasoning and Draft screens.
  - Week 3: approval interrupt, `execute_action` and adapters, `defect_flow`, `doc_check_flow`, `tasks`, memory and feedback, and the Approvals, Document check, Tasks and Memory screens.
  - Week 4: `sync`, `categorise` and `corpus_audit`, full experiments, the Library screen, Playwright + axe, and the demo.
- If only one developer is available, the Library and Memory screens fall back to the CLI.
- **Corpus pitfalls to handle explicitly:**
  - 9 image-only scanned PDFs (they need Claude PDF input).
  - xlsx formula cells with no cached values.
  - Duplicate rows in exports and in `payments` (`PAY-00001235`).
  - Duplicate tenant `T-19807` / `T-10514`.
  - Impossible date `INSP-2025-0125` (2099).
  - Outlier rent `TA-2022-00400`.
  - The snapshot date is 2026-09-30, and the August vacancy figures are as at 2026-08-31.
- **Key risks:**
  - Policy effective-date metadata must be right at ingestion.
  - Routing errors are a new failure mode.
  - LLM-extracted graph edges can be wrong (mitigated by evidence chunks and ground-truth checks).
  - Long SSE runs behind proxies (mitigated by sequence numbers, reload from checkpoint and heartbeats).
  - The Python/TypeScript contract can drift (mitigated by OpenAPI-generated types checked in CI).
- The data classification is still open. If it is Sensitive-High, Claude must be swapped behind `LLMClient`, and native Citations fall back to post-hoc citation verification.
