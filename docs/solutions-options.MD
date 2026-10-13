# PLG "Super-Librarian": Architecture Solution Options (POC)

> Input: `docs/REQ.md` · Date: 2026-10-10 · Status: Draft for discussion

---

## 1. Shared Understanding (from interview)

| Topic | Agreed position | Design implication |
|---|---|---|
| Hosting | **Undecided** (GCC vs on-prem not fixed) | Keep infra portable: containers, no hard dependency on one cloud's managed services |
| Data classification | **Not yet known** | Model layer must be pluggable so Claude can be swapped for a self-hosted open-weight model if data is classified Sensitive-High |
| Engagement type | **POC / prototype** | Optimise for speed and demonstrability, not scale or HA |
| LLM stack | **Claude (Anthropic API)** | Use Claude tool use, Citations, and the Claude Agent SDK; Bedrock/Vertex can serve the same models later inside GCC |
| POC scope | **All four areas**: RAG Q&A with citations, NL-to-SQL/Excel analysis, document drafting, agentic workflows | Multi-agent design is justified; each area becomes a specialist |
| Integrations | **Mock everything** (SharePoint, Lotus Notes, i-EMS) | Synthetic corpus (via `poc-artifact-generator`) on the local filesystem plus SQLite/DuckDB; i-EMS is a stub |
| Interface | **CLI / notebook** | No web UI; human-in-the-loop (HITL) approvals happen as CLI prompts or notebook cells |
| Team / time | **Python, 2–4 weeks** | Prefer few moving parts; avoid heavyweight platforms |

### Assumptions (please challenge)
- Corpus size for the POC: hundreds to low thousands of documents, and a few tables with ≤100k rows.
- English-only content.
- "High-risk / high-impact" actions = anything that **leaves the system**: sending email or letters to tenants, creating an i-EMS ticket, or changing a record. These always require human approval.
- "Learn from user interactions" means, for the POC, capturing feedback and reusing successful query→answer/SQL pairs as few-shot examples. It does not mean model fine-tuning.

---

## 2. Requirement → Capability Map

| # | Requirement (REQ.md) | Capability / component |
|---|---|---|
| DC1 | Draft standardised documents | **Drafting agent** + approved template library |
| DC2 | Retrieve & analyse historical records (policies, SOPs, emails) | **Knowledge (RAG) agent** with hybrid search |
| DC3 | Interpret policies, articulate PLG's stance | Knowledge agent with a "policy stance" answer format plus citations |
| DC4 | Retrieve precedent cases | Knowledge agent with a **case index** (metadata-filtered retrieval) |
| DC5 | NL queries over structured data | **Data agent** (NL-to-SQL) |
| DC6 | Analyse DB/Excel with business logic, show reasoning | Data agent + **semantic layer / glossary** + visible plan → SQL → result trace |
| DC7 | Regular refresh; SharePoint & Lotus Notes interfaces | **Ingestion pipeline** with connectors (mocked) + incremental sync |
| AC1 | Classify defects, route to i-EMS | **Workflow agent**: classify → propose ticket → HITL → i-EMS stub |
| AC2 | Notify & prioritise outstanding tasks | **Task service** + priority scoring + scheduled digest |
| AC3 | Categorise similar documents, summarise per category | Offline **clustering/classification job** + category summaries |
| AC4 | Find conflicts, duplicates, gaps; recommend enhancements | Offline **corpus-audit job** (near-dup detection + LLM conflict check) |
| AC5 | Check submitted documents complete; notify tenants | **Document-checklist workflow** + drafted notice → HITL |
| SYS | "AI front door" routing to specialised bots; guardrails; HITL; learning | **Router/orchestrator**, policy guardrails, approval queue, feedback store |

---

## 3. Recommended Architecture Approaches

Four approaches, ordered from simplest to most production-shaped. **Recommendation for this POC: Approach B, with integrations wrapped as in Approach D where it is cheap to do so.**

### Approach A: Single Agent with a Toolbox

```
User (CLI) ──► Claude agent (one system prompt)
                 ├─ tool: search_documents
                 ├─ tool: run_sql / query_excel
                 ├─ tool: render_template
                 ├─ tool: create_iems_ticket  (approval-gated)
                 └─ tool: list_tasks
```
One Claude model with all tools; the model decides which tool to call (a ReAct-style loop).

| Pros | Cons |
|---|---|
| Fastest to build (days); least code | Does not literally satisfy the "front door → specialised bots" requirement |
| Easy to debug: one transcript | Prompt and tool list grow large; tool-selection accuracy drops as tools grow |
| Lowest latency and cost per simple query | Hard to give different guardrails or models to different domains |
| Good baseline to measure others against | Weak story for scaling to production teams/ownership |

**References**
- Anthropic, *Building Effective Agents*: https://www.anthropic.com/engineering/building-effective-agents (advice to start with the simplest pattern)
- Claude tool use: https://docs.claude.com/en/docs/agents-and-tools/tool-use/overview
- Yao et al., *ReAct: Synergizing Reasoning and Acting in Language Models* (2022): https://arxiv.org/abs/2210.03629

---

### Approach B: Front-Door Router + Specialist Sub-Agents (Orchestrator–Workers) ★ Recommended

```
                       ┌──────────────────────────────┐
User (CLI/notebook) ─► │ Front Door / Orchestrator     │  Claude Sonnet
                       │  - intent classify & route    │
                       │  - decompose multi-part asks  │
                       │  - guardrails, HITL gate      │
                       └──────┬───────┬───────┬───────┬┘
                              ▼       ▼       ▼       ▼
                     Knowledge  Data     Drafting  Workflow
                     agent      agent    agent     agent
                     (RAG +     (NL→SQL, (templates (defects→i-EMS,
                     citations) Excel)   + facts)  doc checks, tasks)
                        │         │         │          │
                  Hybrid index  SQLite/   Template   Mock i-EMS,
                  (vector+BM25) DuckDB +  library    task store,
                                glossary             approval queue
       ── offline jobs: ingestion/sync · categorisation · corpus audit ──
```
The orchestrator classifies intent, delegates to one or more specialists (in parallel when it can), and merges their results. Each specialist has a narrow prompt, its own tools, and can use its own model tier. All side-effecting tools pass through one approval gate.

| Pros | Cons |
|---|---|
| Maps directly to the REQ's "AI front door + specialised bots in a multi-agent architecture" | More moving parts than A; more tokens per query (orchestrator overhead) |
| Narrow prompts → better accuracy per domain; easier evaluation per agent | Routing errors become a new failure mode (needs a routing eval set) |
| Per-agent model tiering (Haiku for routing/classification, Sonnet for reasoning, Opus for hard analysis) | Context passing between agents needs care (summaries vs full context) |
| Fuses structured + unstructured results (e.g. "policy says X, data shows Y") | Debugging needs tracing across agents |
| Achievable in 2–4 weeks with the Claude Agent SDK or a thin custom loop | |

**References**
- Anthropic, *Building Effective Agents*: routing and orchestrator-workers patterns: https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, *How we built our multi-agent research system*: https://www.anthropic.com/engineering/multi-agent-research-system
- Claude Agent SDK (subagents, tools, permissions/hooks): https://docs.claude.com/en/api/agent-sdk/overview
- Claude Citations: https://docs.claude.com/en/docs/build-with-claude/citations

---

### Approach C: Graph-Orchestrated Workflows (State Machine + Agents)

```
LangGraph StateGraph
  [route] ─► [rag_subgraph] ─────────────► [answer]
     ├────► [sql_subgraph: plan→gen→validate→exec→explain]
     ├────► [draft_subgraph: pick_template→fill→review]
     └────► [defect_flow: classify→propose_ticket→⏸ interrupt(HITL)→submit_iems]
  Checkpointer (SQLite) persists state; HITL = graph interrupt/resume
```
Agentic flows are explicit graphs with deterministic edges. The LLM decides inside nodes, not the overall control flow.

| Pros | Cons |
|---|---|
| Deterministic, auditable control flow, which suits a government compliance setting | More upfront design; less flexible for open-ended questions |
| Built-in checkpointing and **interrupt/resume for HITL** | Framework learning curve; abstraction overhead; version churn |
| Easy to show "reasoning steps" (DC6) as graph trace | Graph explosion as workflows multiply |
| Model-agnostic (Claude now, open-weight later) | Two paradigms (graph + agent) to maintain |

**References**
- LangGraph documentation (human-in-the-loop, persistence): https://langchain-ai.github.io/langgraph/
- LangChain Anthropic integration: https://python.langchain.com/docs/integrations/chat/anthropic/
- Anthropic, *Building Effective Agents* (workflows vs agents distinction): https://www.anthropic.com/engineering/building-effective-agents

---

### Approach D: Tool-Server (MCP) Platform with Event-Driven Agents

```
                    ┌───────── Agent host (orchestrator + specialists) ─────────┐
User / Scheduler ─► │  Claude Agent SDK / any MCP-capable client                │
                    └───┬──────────┬──────────┬──────────┬──────────┬───────────┘
                        │ MCP      │ MCP      │ MCP      │ MCP      │ MCP
                  sharepoint-  lotus-     iems-      plg-db-    templates-
                  mcp (mock)   notes-mcp  mcp(mock)  mcp        mcp
                                (mock)
  Event bus / scheduler (cron, file-watch) ─► ingestion, task digests, doc-check triggers
```
Every enterprise system sits behind a **Model Context Protocol** server. Agents are thin, and the scheduler and events trigger the proactive capabilities (AC2, AC5, DC7).

| Pros | Cons |
|---|---|
| Swap a mock for the real SharePoint/Lotus/i-EMS without touching agent code | Extra process boundaries; more setup for a 2–4 week POC |
| Standard protocol; tools are reusable by other clients (e.g. Claude Desktop, IDEs) | MCP auth/permissions for real systems still need design |
| Clear security boundary per system (least privilege per server) | Event-driven parts are over-engineering if only a CLI demo is needed |
| Closest to the production target architecture | |

**References**
- Model Context Protocol specification: https://modelcontextprotocol.io
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk
- Claude Agent SDK, MCP integration: https://docs.claude.com/en/api/agent-sdk/overview

---

### Comparison Summary

| Criterion | A Single agent | B Router + specialists ★ | C Graph workflows | D MCP platform |
|---|---|---|---|---|
| Fits "front door + specialised bots" | ◐ | ● | ● | ● |
| Build effort (2–4 wk, Python) | ● very low | ● low–med | ◐ medium | ◐ medium–high |
| Auditability / deterministic HITL | ◐ | ◐ (via hooks/gate) | ● | ◐ |
| Swap-to-real integrations | ○ | ◐ | ◐ | ● |
| Model portability (on-prem path) | ◐ | ◐ | ● | ● |
| Demo impact | ◐ | ● | ● | ● |

● strong ◐ partial ○ weak

**Recommended POC blend:** Approach **B** as the backbone. Make the **agentic workflows (AC1, AC5)** deterministic step sequences inside the Workflow agent, which borrows C's discipline without the framework. Put the **i-EMS stub and the mock document store behind MCP-style interfaces** (D) only where it costs little.

---

## 4. Design Tree

```
PLG Super-Librarian POC
├── D1 Orchestration topology ............ A single | B router+specialists ★ | C graph | D MCP platform
├── D2 Agent framework .................... Claude Agent SDK ★ | raw Anthropic SDK loop | LangGraph | PydanticAI
├── D3 Model strategy ..................... single model | tiered Haiku/Sonnet/Opus ★ | + abstraction (LiteLLM)
├── Knowledge (unstructured)
│   ├── D4 Retrieval method ............... vector | hybrid BM25+vector+rerank ★ | +contextual retrieval | GraphRAG
│   ├── D5 Index/store .................... Chroma | LanceDB ★ | pgvector | Qdrant/OpenSearch
│   ├── D6 Chunking ....................... fixed | structure-aware ★ | +contextual headers
│   └── D7 Citations ...................... prompt-based | Claude Citations API ★ | post-hoc verification
├── Structured data
│   ├── D8 Query approach ................. raw NL→SQL | NL→SQL + semantic layer ★ | pandas code-exec | text→metrics API
│   └── D9 Excel handling ................. load to DuckDB ★ | pandas per-file | LLM reads sheet directly
├── D10 Drafting .......................... free-form | template + slot-fill ★ | template + LLM prose sections
├── Agentic
│   ├── D11 HITL / guardrails ............. prompt-only | tool-level approval gate ★ | policy engine (OPA)
│   ├── D12 Defect classification ......... zero-shot LLM | few-shot LLM + taxonomy ★ | trained classifier
│   ├── D13 Task prioritisation ........... LLM scoring | rules matrix ★ | hybrid rules + LLM rationale
│   └── D14 Doc-completeness check ........ checklist + LLM extraction ★ | pure LLM | IDP/OCR service
├── Corpus intelligence
│   ├── D15 Categorisation ................ embedding clustering ★ | LLM labelling | hybrid
│   └── D16 Conflict/dup detection ........ near-dup hashing + embedding + LLM judge ★ | LLM only
├── D17 Integration layer ................. direct file/DB access | adapter interfaces ★ | MCP servers
├── D18 Data refresh ...................... manual rebuild | incremental hash-based sync ★ | event-driven
├── D19 Learning loop ..................... none | feedback + few-shot memory ★ | fine-tuning
└── D20 Evaluation & observability ........ ad-hoc | golden set + RAGAS-style metrics ★ | + tracing (Langfuse/OTel)
```
★ = recommended for the POC

---

### D1 Orchestration Topology
See Section 3. **Recommend B.**

### D2 Agent Framework

| Option | Pros | Cons |
|---|---|---|
| **Claude Agent SDK** ★ | Built-in agent loop, subagents, tool permissions and hooks (good for the HITL gate), MCP support | Claude-centric; swapping to an open-weight model later needs an adapter |
| Raw Anthropic Python SDK + own loop | Full control, minimal dependencies, transparent | You write the loop, retries, parallel tool calls and tracing yourself |
| LangGraph | Graph control, checkpoints, interrupts, model-agnostic | Heavier abstraction; churn; slower to start |
| PydanticAI | Typed outputs, model-agnostic, light | Smaller ecosystem for multi-agent patterns |

Refs: https://docs.claude.com/en/api/agent-sdk/overview · https://github.com/anthropics/anthropic-sdk-python · https://langchain-ai.github.io/langgraph/ · https://ai.pydantic.dev

### D3 Model Strategy

| Option | Pros | Cons |
|---|---|---|
| Single model (Sonnet 5.5) | Simple; consistent behaviour | Overpays for routing/classification |
| **Tiered** ★: Haiku 4.5 for routing/classification, Sonnet 5.5 for agents, Opus 5.5 for hard analysis/audit | Cost/latency optimised; good quality where it matters | More config; evaluate each tier |
| Tiered + abstraction layer (LiteLLM / interface) | Keeps the on-prem open-weight path open (classification unknown) | Lowest-common-denominator features (e.g. native Citations unavailable elsewhere) |

**Note:** Because the data classification is unknown, keep a thin internal `LLMClient` interface even if you use Claude directly. Claude is also available through Amazon Bedrock and Google Vertex AI, which matters if the system lands in GCC.
Refs: https://docs.claude.com/en/docs/about-claude/models/overview · https://docs.litellm.ai

### D4 Retrieval Method

| Option | Pros | Cons |
|---|---|---|
| Dense vector only | Simple | Misses exact terms: block/unit numbers, policy codes, tenant names |
| **Hybrid BM25 + vector + reranker** ★ | Strong on both semantic and exact-match queries; standard best practice | Two indexes plus a reranker to manage |
| + Contextual Retrieval (LLM-generated chunk context) | Anthropic reports large reductions in retrieval failures | Ingestion cost (cheap with prompt caching); adds a preprocessing step |
| GraphRAG / knowledge graph | Good for "global" questions and cross-document relations (precedent chains) | Expensive to build; overkill for a 2–4 week POC |

Refs: Lewis et al., RAG (2020) https://arxiv.org/abs/2005.11401 · Anthropic Contextual Retrieval https://www.anthropic.com/news/contextual-retrieval · Microsoft GraphRAG https://microsoft.github.io/graphrag/

### D5 Index / Vector Store

| Option | Pros | Cons |
|---|---|---|
| Chroma | Easiest Python start | Hybrid search is weaker; scaling limits |
| **LanceDB** ★ | Embedded (no server), built-in full-text + vector hybrid, runs on-prem | Younger ecosystem |
| Postgres + pgvector (+ tsvector) | One DB for structured + vectors; production-familiar | Needs a Postgres instance; hybrid needs hand-rolled fusion |
| Qdrant / OpenSearch | Production-grade, hybrid, filtering | Server to run; heavier for a POC |

Refs: https://lancedb.github.io/lancedb/ · https://github.com/pgvector/pgvector · https://qdrant.tech/documentation/ · https://docs.trychroma.com

### D6 Chunking

| Option | Pros | Cons |
|---|---|---|
| Fixed-size token windows | Trivial | Splits policy clauses and email threads mid-thought |
| **Structure-aware** ★ (policy section/clause, email message, case record) | Citable units align with how officers cite ("Policy X §3.2") | Needs a parser per document type |
| + Contextual headers (doc title, date, policy version prepended) | Better retrieval and disambiguation of superseded versions | Slight ingestion overhead |

Ref: https://www.anthropic.com/news/contextual-retrieval

### D7 Citations

| Option | Pros | Cons |
|---|---|---|
| Prompt "cite your sources" | Simple | Citations can be hallucinated |
| **Claude Citations API** ★ | Grounded, character-level spans pointing back to source documents | Claude-specific (portability trade-off, see D3) |
| Post-hoc verification (check each claim against its source) | Model-agnostic; catches unsupported claims | Extra LLM call and latency |

Ref: https://docs.claude.com/en/docs/build-with-claude/citations

### D8 Structured-Data Query Approach (DC5, DC6)

| Option | Pros | Cons |
|---|---|---|
| Raw NL→SQL from schema | Quick | Business definitions ("vacant", "arrears", "active tenancy") get misinterpreted |
| **NL→SQL + semantic layer** ★: a glossary of business terms, metric definitions, curated example queries, read-only connection, SQL validation | Encodes PLG business logic; shows a plan → SQL → result → explanation trace (meets "outline reasoning steps") | Glossary must be curated |
| Code execution (pandas) in a sandbox | Flexible analysis and charts | Sandboxing; harder to audit than SQL |
| Text→metrics API (dbt semantic layer, Cube) | Strongest governance | Too heavy for the POC |

Refs: BIRD text-to-SQL benchmark https://bird-bench.github.io · Vanna (RAG for SQL) https://github.com/vanna-ai/vanna · DuckDB https://duckdb.org · Cube semantic layer https://cube.dev/docs

### D9 Excel Handling

| Option | Pros | Cons |
|---|---|---|
| **Load into DuckDB tables at ingestion** ★ | One SQL interface across DB and Excel; joins across sources | Messy sheets (merged cells, multi-header) need cleaning rules |
| pandas per file at query time | Flexible | Each query re-parses; no cross-source joins |
| Paste sheet into LLM context | No code | Fails on large sheets; arithmetic errors |

### D10 Document Drafting (DC1, AC5 notices)

| Option | Pros | Cons |
|---|---|---|
| Free-form LLM drafting | Flexible | Inconsistent tone and legal wording; violates "approved templates" |
| **Approved template + slot-fill** ★ (Jinja2/docx-template; the LLM extracts and validates slot values from records) | Wording stays exactly as approved; auditable; fast to review | Only as good as the template library |
| Template + LLM-written variable sections | Personalised explanations (e.g. feedback replies) within a fixed frame | Needs review of the generated sections |

Refs: https://docxtpl.readthedocs.io · https://jinja.palletsprojects.com

### D11 HITL & Guardrails

| Option | Pros | Cons |
|---|---|---|
| Prompt-only instructions ("ask before acting") | Zero effort | Not enforceable; unsafe |
| **Tool-level approval gate** ★: every side-effecting tool (send, create ticket, update record) is tagged `risk=high` and needs CLI `y/n` approval; all actions logged | Enforced in code, not by the model; simple; demonstrable | Approval fatigue if over-applied |
| Policy engine (OPA/Cedar) with risk scoring | Fine-grained, central rules | Over-engineered for the POC |

Also: input guardrails (prompt-injection screening on ingested emails), output checks (PII redaction in drafts), read-only DB credentials.
Refs: Claude Agent SDK permissions/hooks https://docs.claude.com/en/api/agent-sdk/overview · OWASP Top 10 for LLM Applications https://owasp.org/www-project-top-10-for-large-language-model-applications/ · Anthropic, mitigating jailbreaks & prompt injections https://docs.claude.com/en/docs/test-and-evaluate/strengthen-guardrails/mitigate-jailbreaks

### D12 Defect Classification → i-EMS (AC1)

| Option | Pros | Cons |
|---|---|---|
| Zero-shot LLM | No data needed | Inconsistent categories |
| **Few-shot LLM + fixed taxonomy + structured output** ★ (category, severity, responsible team, confidence, rationale) | Consistent; explainable; low-confidence → human | Needs a taxonomy from PLG |
| Trained classifier | Cheap at scale | Needs labelled history; no rationale |

Flow: complaint/feedback → classify (Haiku) → propose i-EMS payload → **approval gate** → mock i-EMS → reference number stored.

### D13 Task Prioritisation & Notification (AC2)

| Option | Pros | Cons |
|---|---|---|
| LLM scores priority | Handles nuance | Non-deterministic; hard to justify |
| **Rules matrix** ★ (urgency = SLA/due date; impact = safety, revenue, tenant count) | Transparent, auditable | Misses nuance in free text |
| Hybrid: rules score + LLM extracts factors and writes the rationale | Best of both | Slightly more work |

For the POC: a scheduled (cron/CLI command) digest printed to the console or written to a file.

### D14 Document-Completeness Check (AC5)

| Option | Pros | Cons |
|---|---|---|
| **Checklist per application type + LLM extraction/classification of submitted docs** ★ | Deterministic "what's missing"; LLM only identifies document types and key fields | Checklists must be defined |
| Pure LLM judgement | Fast to build | Unreliable for compliance |
| Dedicated IDP/OCR service (Textract, Azure Doc Intelligence) | Strong on scans/forms | Cloud dependency; overkill with mocked data |

Claude reads PDFs and images natively, which covers the POC.
Ref: https://docs.claude.com/en/docs/build-with-claude/pdf-support

### D15 Document Categorisation (AC3)

| Option | Pros | Cons |
|---|---|---|
| **Embedding clustering (HDBSCAN/k-means) + LLM-named clusters** ★ | Discovers categories; cheap | Clusters can be noisy |
| LLM labels each document to a given taxonomy | Precise, business-aligned | Cost per document; needs a taxonomy |
| Hybrid (cluster to propose the taxonomy, then classify) | Good long-term | Two passes |

Refs: BERTopic https://maartengr.github.io/BERTopic/ · HDBSCAN https://hdbscan.readthedocs.io

### D16 Conflict, Duplication & Gap Detection (AC4)

| Option | Pros | Cons |
|---|---|---|
| **Pipeline** ★: MinHash/hash for near-duplicates → embedding similarity for same-topic pairs → LLM judge (Opus) for "conflicting / superseded / consistent" → report with citations | Scales; LLM only on candidate pairs; produces an actionable report | Pairwise candidate generation needs thresholds tuned |
| LLM-only over the whole corpus | Simple | Cost and context-limit prohibitive |

Gaps: compare the category coverage (D15) against question logs. Topics users ask about with low retrieval scores are "areas requiring further development".
Ref: datasketch MinHash https://ekzhu.com/datasketch/

### D17 Integration Layer (SharePoint, Lotus Notes, i-EMS)

| Option | Pros | Cons |
|---|---|---|
| Direct file/DB access in agent code | Fastest | Rewrite needed for real systems |
| **Adapter interfaces** ★ (`DocumentSource`, `TicketSystem` Python protocols; mock implementations) | Cheap; real adapters plug in later (Graph API, Lotus Notes DXL/Domino REST) | Not reusable outside this app |
| MCP servers per system | Standard, reusable, least-privilege boundary | More setup for the POC |

Refs: Microsoft Graph (SharePoint) https://learn.microsoft.com/en-us/graph/api/resources/sharepoint · HCL Domino REST API https://opensource.hcltechsw.com/Domino-rest-api/ · MCP https://modelcontextprotocol.io

### D18 Data Refresh (DC7)

| Option | Pros | Cons |
|---|---|---|
| Manual full rebuild | Simplest | Not a "regular update" story |
| **Incremental sync by content hash / modified date** ★ (CLI `sync` command; schedulable) | Demonstrates freshness; cheap | Deletions need tombstones |
| Event-driven (webhooks, change notifications) | Near real-time | Requires real systems |

### D19 Learning from Interactions

| Option | Pros | Cons |
|---|---|---|
| None | — | Fails a stated requirement |
| **Feedback capture + few-shot memory** ★ (👍/👎 in the CLI; store verified Q→SQL and Q→answer pairs; retrieve as examples) | Visible improvement in a demo; no training | Memory curation needed |
| Fine-tuning | Deep adaptation | Data, cost, governance; not suitable for a POC |

### D20 Evaluation & Observability

| Option | Pros | Cons |
|---|---|---|
| Ad-hoc manual testing | Fast | No evidence for stakeholders |
| **Golden question set per agent + automated metrics** ★ (routing accuracy, retrieval recall@k, faithfulness, SQL execution accuracy, classification F1) | Objective POC success criteria | Needs ~30–50 questions per area |
| + Tracing (Langfuse / OpenTelemetry) | Debug multi-agent runs; latency and cost visibility | Extra service |

Refs: RAGAS https://docs.ragas.io · Langfuse https://langfuse.com/docs · Anthropic, define success criteria & build evals https://docs.claude.com/en/docs/test-and-evaluate/develop-tests

---

## 5. Recommended POC Blueprint

```
agent-hdb/
├── data/                # synthetic corpus (poc-artifact-generator) + plg.duckdb
├── ingest/              # parsers, chunking, contextual headers, LanceDB index, sync
├── adapters/            # DocumentSource (SharePoint/Lotus mocks), TicketSystem (i-EMS mock)
├── agents/
│   ├── orchestrator.py  # front door: route / decompose / merge
│   ├── knowledge.py     # hybrid RAG + Citations (policies, SOPs, emails, precedents)
│   ├── data.py          # NL→SQL + glossary + reasoning trace
│   ├── drafting.py      # templates + slot fill
│   └── workflow.py      # defect→i-EMS, doc checks, task digest
├── guardrails/          # approval gate, injection screen, PII redaction, audit log
├── jobs/                # categorise, corpus_audit, task_digest
├── evals/               # golden sets + runners
└── cli.py / demo.ipynb
```

| Stack element | Choice |
|---|---|
| Language | Python 3.12 |
| LLM | Claude: Haiku 4.5 (routing/classification), Sonnet 5.5 (agents), Opus 5.5 (audit/hard analysis) |
| Agent runtime | Claude Agent SDK (or a raw SDK loop if a thinner core is wanted) |
| Embeddings | Voyage AI (https://docs.voyageai.com) or local `bge-m3` for on-prem portability |
| Index | LanceDB (hybrid) + cross-encoder reranker |
| Structured | DuckDB (DB extracts + Excel), read-only |
| Templates | docxtpl / Jinja2 |
| Eval | pytest + RAGAS-style metrics |

### Indicative 4-Week Plan
| Week | Deliverable |
|---|---|
| 1 | Synthetic corpus + DuckDB; ingestion + hybrid index; Knowledge agent with citations; golden set v1 |
| 2 | Data agent (NL→SQL + glossary + trace); Drafting agent; orchestrator routing |
| 3 | Workflow agent (defect→i-EMS with approval gate; doc-completeness; task digest); feedback memory |
| 4 | Offline jobs (categorise, conflict/dup audit); evals and metrics report; demo notebook |

### Key Risks & Open Questions
1. **Data classification**: if it comes out as Sensitive-High, the Claude API is not allowed and the system moves to on-prem open-weight models. Keep the `LLMClient` seam and local embeddings ready.
2. **Taxonomies and checklists** (defect categories, application document checklists, priority rules) are needed from PLG; the POC will use invented versions.
3. **Policy versioning**: answers must not cite superseded policies. Index the effective dates and filter on them.
4. **Lotus Notes**: real extraction (DXL export / Domino REST) is a known production risk; flag it early.
5. **Success criteria**: agree target metrics (e.g. ≥90% routing accuracy, ≥85% answer faithfulness, ≥80% SQL execution accuracy) before the demo.
