# Getting started

How to set up and run the PLG "Super-Librarian" POC locally. Everything runs on your machine: one API process and the web dev server, with no Docker.

## What there is to run

| Part | Status | How to run |
|---|---|---|
| Backend: `plg` CLI and `plg-api` (Python, FastAPI, LangGraph) | Available: policy Q&A with citations, data questions over PLG Records and the Excel trackers, letter drafting | `uv run plg sync`, then `uv run plg ask "..."` / `uv run plg serve` |
| Frontend: web app (TypeScript, Next.js) with a BFF | Available: sign-in, Ask, Approvals, Document check, Tasks and Memory screens | `cd web && npm run dev` |

## 1. Prerequisites

- [uv](https://docs.astral.sh/uv/) 0.8 or later. It installs Python 3.12 for you (pinned in `.python-version`).
- Node.js 22 or later and npm, for the web app.
- An Anthropic API key, for live answers, and a Voyage AI API key, to index the corpus and embed questions. Tests need neither.

## 2. Install

From the repo root:

```bash
uv sync
```

This creates `.venv/` with the `plg` package (editable) and the dev tools (pytest, mypy, LinkML for `make ontology`).

Then install the web app's dependencies:

```bash
cd web && npm ci
```

## 3. Environment variables

Create a `.env` file at the repo root. It is git-ignored and loaded automatically by `plg` and `plg-api` (they search upward from the current directory).

```dotenv
# Required for live answers
ANTHROPIC_API_KEY=sk-ant-...
# Required to index the corpus (`plg sync`) and to search it when answering
VOYAGE_API_KEY=pa-...

# Optional: LangSmith tracing of graph runs and Claude calls
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=plg-poc
```

Optional `PLG_*` overrides (defaults shown):

| Variable | Default | Purpose |
|---|---|---|
| `PLG_MODEL_HAIKU` | `claude-haiku-5-5` | Model for screening, routing, classification, summaries |
| `PLG_MODEL_SONNET` | `claude-sonnet-5-5` | Model for agents and the streamed answer |
| `PLG_MODEL_OPUS` | `claude-opus-5-5` | Model for hard analysis and judges |
| `PLG_MAX_TOKENS` | `2048` | Max tokens per Claude reply |
| `PLG_HEARTBEAT_SECONDS` | `15` | Interval between SSE heartbeat comments |
| `PLG_ROUTE_MIN_CONFIDENCE` | `0.6` | Below this routing confidence (0-1) a specialist is dropped; with none left, the assistant asks a clarifying question |
| `PLG_API_HOST` | `127.0.0.1` | `plg-api` bind address |
| `PLG_API_PORT` | `8000` | `plg-api` port |
| `PLG_RECORDS_DB` | `poc-data/plg_records.db` | PLG Records SQLite database (read-only; source of the staff personas) |
| `PLG_TRACKERS_DB` | `.plg/trackers.duckdb` | The Excel trackers (`poc-data/sheets/*.xlsx`), cleaned into DuckDB tables by `plg sync`; the data agent queries them as `trackers.<table>` |
| `PLG_THREADS_DB` | `.plg/threads.sqlite` | Conversations: LangGraph checkpoints and thread owners; they survive a `plg-api` restart (so do pending approvals) |
| `PLG_OUTBOX_DIR` | `.plg/outbox` | Local Outbox: one JSON file per approved letter (nothing is delivered) |
| `PLG_IEMS_DIR` | `.plg/iems` | i-EMS mock: one JSON file per approved defect ticket (`IEMS-<yymm>-<id>`, linked to its feedback case) |
| `PLG_AUDIT_LOG` | `.plg/audit.jsonl` | Append-only audit log: one line per decided action (approver, time, LangSmith `run_id`) |
| `PLG_HISTORY_TOKEN_THRESHOLD` | `6000` | Above this (estimated) many tokens, older turns are folded into a summary |
| `PLG_HISTORY_KEEP_MESSAGES` | `4` | Recent messages kept verbatim when folding |
| `PLG_RERANK_BACKEND` | `voyage` | `voyage` reranks with Voyage's hosted reranker (uses `VOYAGE_API_KEY`); `local` runs a cross-encoder on this machine (no document text leaves it) |
| `PLG_VOYAGE_RERANK_MODEL` | `rerank-2.5` | Voyage rerank model (e.g. `rerank-2.5-lite` for lower latency) |

The web app reads one server-only variable (set it in `web/.env.local` if you need to change it). It is never sent to the browser:

| Variable | Default | Purpose |
|---|---|---|
| `PLG_API_URL` | `http://127.0.0.1:8000` | Where the BFF reaches `plg-api` |

## 4. Run the backend

### Index the corpus (once, then after the corpus changes)

```bash
uv run plg sync                      # incremental; --full drops the index and re-ingests everything
uv run plg search "letter of demand" # check what was indexed
```

This reads `poc-data/` through the SharePoint and Lotus Notes mocks into `.plg/lancedb`. Image-only scanned PDFs are transcribed by Claude (needs `ANTHROPIC_API_KEY`) the first time; the transcript is saved in `.plg/lancedb-transcripts/` and reused, so re-syncs and `--full` don't call Claude again for them. Delete that folder to force a re-read. With `PLG_RERANK_BACKEND=local`, the first search downloads the local cross-encoder into `.plg/models`.

`plg sync` also loads the Excel trackers into `.plg/trackers.duckdb`, rebuilt from scratch on every run, which needs no API key. Their formulas have no saved values, so formula columns and summary sheets are not loaded; the data agent computes those figures in SQL. Restart `plg-api` after a sync to query the new tables.

### Entity graph (tenants, units, tenancies)

```
uv run plg graph build                      # PLG Records -> Neptune-format CSVs in .plg/graph/spine (also built on first use)
uv run plg graph show "Golden Leaf Minimart Pte Ltd"   # resolve a name, unit number or ID, then print its context
uv run plg graph lineage                    # Haiku extracts SUPERSEDES/OVERRIDES/APPLIES edges; precedent cases for find_precedents (needs ANTHROPIC_API_KEY and a synced index: `plg sync` first)
```

No API key needed. Override the location with `PLG_GRAPH_DIR`.

### Ask from the command line

```bash
uv run plg ask "When do we issue a letter of demand?"
```

The answer streams to the terminal, then its sources: each `[n]` in the answer is listed with its document, section and the quoted sentence. Policy and records questions are answered only from the indexed documents (current versions unless you ask about an earlier date). If the sources don't cover the question, the answer says so. If the run fails partway, the CLI prints an error to stderr and exits with code 1.

### Draft a letter (issue #17)

```bash
uv run plg ask "Draft a first reminder letter for Golden Leaf Minimart Pte Ltd's overdue rent"
```

Requests for a standard letter go to the `drafting` agent. It picks an approved template (`poc-data/docs/TPL-REM-01`, `TPL-DOC-02`, `TPL-FBK-03`), fills the slots from PLG Records with read-only lookups, lists the slots it couldn't fill (e.g. `letter_ref`) and flags personal data. Only `ANTHROPIC_API_KEY` is needed, no index. In the web app the draft appears under the answer: an HTML preview, the open slots, any personal-data flags and a **Download DOCX** link (`GET /drafts/{id}/file`, only for the officer who asked). Nothing is sent until you approve it (see below). Drafts live in memory, so they are lost when `plg-api` restarts. In `plg ask` (CLI) the draft is not shown, only the answer. Where it lives: `src/plg/drafting/`, `src/plg/agents/drafting.py`, `tests/test_drafting_api.py`.

### Approve, edit or reject a proposed action (issue #18)

A drafted letter is only *proposed*: the run ends with a `proposed_action` event (the letter, its slots, who may approve) and an `interrupt` event (`action_id` + `version`), and the thread waits. Decide on it with `/resume`, which streams the rest of the run (`action_result`, then `done`):

```bash
curl -s 'http://127.0.0.1:8000/approvals?status=pending' -H 'X-PLG-User: S05'     # your pending actions, all threads
curl -N -X POST http://127.0.0.1:8000/threads/<id>/resume -H 'X-PLG-User: S05' -H 'content-type: application/json' \
  -d '{"action_id":"<action_id>","version":1,"decision":"approve"}'
#  edit:   {"action_id":"…","version":1,"decision":"edit","edits":{"pay_by_date":"21 October 2026"}}
#  reject: {"action_id":"…","version":1,"decision":"reject","reason":"Tenant paid yesterday"}
```

Only the thread's owner can decide (another officer gets 404), and only on the exact pending version (otherwise 409, including a replay). Approving or editing needs an approver role for the action type (`send_letter`: not analysts; 403); anyone can reject their own proposal, with a reason. A letter with open slots can't be sent until an edit fills them (422). Approve/edit writes the letter to `PLG_OUTBOX_DIR` (nothing is delivered); every decision appends one line to `PLG_AUDIT_LOG` with the approver, time and the run's `run_id`. Asking for the same template again in the thread revises the pending letter (same ID, next version). Pending approvals survive a `plg-api` restart. `plg ask` stops at the proposal, with no way to approve from the CLI yet. Where it lives: `src/plg/actions/`, `src/plg/graph/build.py` (`approval`, `execute_action`), `tests/test_approvals_api.py`.

### Approvals inbox (issue #19)

In the web app, **Approvals** in the top bar (`/approvals`) lists every action waiting for you across your conversations: the letter as it would be sent, its slot values, open slots and personal-data flags. **Edit slots** turns the slots into inputs and shows each change against the proposal (struck-through old value, new value); **Send edited letter** is enabled once the open slots are filled. **Approve and send** appears only for a complete letter and a role that can send it; **Reject…** asks for a reason. After a decision you see its result (outbox item ID and version sent, or that nothing was sent), and the **Decided** section shows your audit trail from `GET /audit`: who decided, role, when, reason, edits, the outbox item with the letter as sent, and the run's `run_id`.

```bash
curl -s http://127.0.0.1:8000/audit -H 'X-PLG-User: S05'   # your decisions, newest first
```

Where it lives: `web/src/app/approvals/`, BFF `web/src/app/api/{approvals,audit}/`, `web/src/app/api/threads/[id]/resume/`, `src/plg/api/app.py` (`/audit`).

### Classify feedback and raise an i-EMS ticket (issue #20)

Paste public or tenant feedback (or name a case, e.g. `FB-2025-00003`) and ask for it to be classified:

```bash
curl -N -X POST http://127.0.0.1:8000/threads/$T/runs -H 'X-PLG-User: S11' -H 'Content-Type: application/json' \
  -d '{"message": "Classify: Ceiling near the shop wet and lights flickering, scared got short circuit"}'
```

The `defect` specialist (Haiku) streams a `classification` event: category, severity, team, vendor, SLA, confidence and
rationale. When the feedback could belong to several categories, the result is flagged low confidence and the most
severe category is chosen. In this example that is Electrical (High) over Water Seepage (Medium). A maintenance defect
(STR, SEP, PLB, ELE, FIR, PST) gets a proposed `raise_ticket` action for the category's team and vendor. Its SLA comes
from the severity: Critical 1 day, High 3, Medium 7, Low 14.

Non-defects (hygiene, encroachment, noise, common area, enquiries) get no ticket.

The ticket appears in the Approvals inbox. You can edit its category (which re-routes the team and vendor), priority
(which resets the SLA), unit, description and feedback case. Analysts and Legal can't raise tickets. Nothing is
written to `PLG_IEMS_DIR` until you approve. The raised ticket carries its feedback case ID. Pasted feedback without
a case gets a new `FB-NEW-…` ID. `GET /audit` shows the raised ticket.

Where it lives: `src/plg/defects/` (taxonomy, classify, `defect_flow`, `TicketSystem`), `src/plg/actions/tickets.py`,
`web/src/app/ClassificationCard.tsx`, `web/src/app/approvals/`, `tests/test_defect_api.py`.

### Check an application's documents (issue #21)

In the web app, **Document check** in the top bar (`/doc-check`) lists the applications that have a submission bundle
(`poc-data/pdfs/submissions/<APP-ID>/`, from `GET /submissions`). Pick one, or ask on the Ask screen:

```bash
uv run plg ask "Is application APP-2026-0294 complete? Check the submitted documents."
```

The `doc_check` specialist runs the `doc_check_flow` subgraph. It identifies each file by its content, not its name:
- a PDF with a text layer is identified by its printed title;
- a scan (no text layer), or a PDF matching no known title, is read by Claude (Sonnet, PDF input). Claude
  transcribes it, says whether it's legible and names the document type.

The application type's checklist (new tenancy, renewal, assignment, change of trade, A&A; from the ontology
vocabularies) is then ticked off. Flags:
- **Expired:**
  - business profile more than 3 months old;
  - insurance not in force when the new term starts (renewals) or on the submission date;
  - lapsed licence or contractor registration.
- **Wrong unit:** the document names another unit ID or address.
- **Illegible scan.**

The `doc_check` event carries the checklist (✓ / ✗ / – per document) and every file with what it was identified as.
An incomplete bundle also gets the missing-documents notice (`TPL-DOC-02`), listing each missing or rejected document
with the reason, as a `send_letter` action. The letter reference is left open: fill it in with **Edit slots** in
Approvals before sending. Only `ANTHROPIC_API_KEY` is needed; scans are read again on every check (not cached yet).

The renewals APP-2026-0278, -0288 and -0268 are flagged for expired insurance (it ends before the new term starts)
although `_master/submission_bundles_ground_truth.json` marks them valid; see `tests/test_doc_check_api.py`.

Where it lives: `src/plg/doccheck/`, `web/src/app/doc-check/`, `web/src/app/DocCheckCard.tsx`,
BFF `web/src/app/api/submissions/`, `tests/test_doc_check_api.py`.

### Top tasks and the task digest (issue #22)

In the web app, **Tasks** in the top bar (`/tasks`) shows your top open tasks. A team lead also gets an **Officer**
picker (from `GET /tasks/team`). **Show** sets how many tasks are listed: 5, 10, 20 or 50. You can also ask on the Ask
screen:

```bash
uv run plg ask "What are my top 5 tasks this week and why?"   # plg ask has no signed-in officer: use the web app or API
uv run plg digest --user S12                 # Benjamin Ho's top 5, to the console
uv run plg digest --limit 10 --out .plg/digest.txt   # every officer with open tasks, to a file (for a scheduled job)
```

Open tasks (PLG Records `tasks`, not Done) are ranked by a fixed rules matrix, with no Claude call:
- **Urgency:** overdue 4, due within 7 days 3, due within 30 days 2, later 1.
- **Impact:** high 3 (safety-related, S$50,000+ rent at risk or 5+ tenants affected), medium 2 (S$10,000+ or 2+
  tenants), low 1.
- **Score:** urgency × impact. Ties go to the earlier due date, then the larger rent at risk.

Each task comes with its reasons, e.g. "Overdue by 283 days (due 21 Dec 2025)", "Safety-related", "S$53,520 rent at
risk". Overdue tasks are marked. "Today" is `PLG_TASKS_TODAY`, which defaults to 2026-09-30, the date of the PLG
Records snapshot.

- **In a conversation:** the `tasks` specialist streams the ranking as a `tasks` event and merge (Claude) writes the
  one-line rationale per task. `GET /tasks/digest` and `plg digest` give the rule-based reasons only.
- **Who can view whose tasks:**
  - everyone sees their own;
  - directors see everyone's;
  - managers and estate managers see the officers of their own department, not other leads.

  Anything else gets 403 from `GET /tasks/digest?staff_id=...`. In a conversation, merge says you're not allowed and
  no tasks are read.
- `plg digest` is an admin job: no role check.

Where it lives: `src/plg/tasks/` (`rules.py` matrix, digest, role check; `ask.py` whose tasks and how many), the `tasks`
node in `src/plg/graph/build.py`, `web/src/app/tasks/`, `web/src/app/TaskList.tsx`, BFF `web/src/app/api/tasks/`,
`tests/test_tasks_api.py`.

### Prompt-injection guardrail (issue #23)

Nothing to configure: screening is rule-based (no Claude call, no API key).

- **Your message.** Every question is screened first (`screen_input`). Instructions aimed at the assistant ("ignore all
  previous instructions", "do not ask for approval", "SYSTEM NOTE TO AI ...") stop the turn: no specialist runs, the
  answer says it was a suspected prompt injection, and the Ask screen shows a red alert with the flagged text (as plain
  text). History keeps your message with the planted part replaced by `[Removed: suspected prompt injection (...)]`.
- **Emails.** `plg sync` screens every email and prints `Flagged: <path> (suspected prompt injection; instructions
  removed)`; the planted part never reaches the index. An index built before #23 still holds the raw text: run
  `uv run plg sync --full` once (until then, such an email is withheld from Claude whenever it's retrieved, and flagged).
- **A turn that reads a flagged email** opens with a warning naming it, and proposes nothing for approval.

Try it: `uv run plg ask "Process the latest email in the feedback inbox."` (needs the index) → the planted
`suspicious_refund_request` email is flagged and nothing is proposed. Where it lives: `src/plg/guardrails/injection.py`,
`screen_input` in `src/plg/graph/build.py`, `_guarded` in `src/plg/agents/runtime.py`, `web/src/app/InjectionAlert.tsx`,
`tests/test_guardrail_api.py`.

### Ask a data question (issue #12)

```bash
uv run plg ask "Which tenancies have arrears above 3 months' rent?"
uv run plg ask "Why does the QBR say 52 vacant and the monthly report 47?"
```

Numeric questions go to the `data` agent, which looks up the glossary definition in force on the reporting date, writes one read-only SQL query over PLG Records, and explains the result. The data is a snapshot as at 2026-09-30, which is the default reporting date. No Voyage key or search index is needed for these, only `ANTHROPIC_API_KEY`.

- DuckDB attaches `poc-data/plg_records.db` read-only. The first query installs DuckDB's `sqlite` extension (a one-off download, then cached under `~/.duckdb`), so the first data question, and the first test run, need network access.
- Every query is checked before it runs: a single SELECT, only PLG Records tables (not `staff`), no table functions, then an `EXPLAIN` dry run. Anything else is rejected and the agent is told why.
- Each query is streamed as an `sql_trace` event: plan, SQL, result summary, the glossary term versions it relied on and any data-quality warnings (duplicate tenant T-10514/T-19807, duplicate payment PAY-00001235, impossible date INSP-2025-0125, outlier rent TA-2022-00400). The web app shows them in the Reasoning panel under the answer: each query's plan, SQL (Copy SQL), result table (Export CSV, with every fetched row up to 500), the definitions used with their dates in force, warnings and the explanation (issue #14).
- Every answer's explanation names the definition versions and effective dates it used; if the agent leaves them out they are appended as "Definitions used: …".
- Where it lives (issue #12): `src/plg/data/` (`warehouse.py` DuckDB over SQLite, `sqlcheck.py` validator, `semantic.py` semantic layer and warnings, `trace.py` trace models), `src/plg/agents/data.py` (the agent and its `get_definition` / `run_sql` tools), the `data` node in `src/plg/graph/build.py`, `SqlTraceEvent` in `src/plg/events.py`, and tests in `tests/test_data_api.py`.
- The semantic layer (SQL bindings per glossary term version, table notes, example queries, known data-quality issues) is `ontology/semantic.yaml`. `make ontology` dry-runs every binding and writes `src/plg/ontology/generated/semantic_layer.json`.

Each search is reranked by Voyage by default, which sends the candidate chunks' text to Voyage. If Voyage is unreachable, search keeps the unreranked hybrid order and logs a warning. With `PLG_RERANK_BACKEND=local` a knowledge answer takes 30 to 60 seconds, because each search is reranked on your CPU.

### Start the API

```bash
uv run plg serve        # or: uv run plg-api
```

Then, in another terminal:

```bash
# List the staff personas
curl -s http://127.0.0.1:8000/personas

# Create a thread, as staff member S05 (the BFF sends this header for the signed-in persona)
curl -s -X POST http://127.0.0.1:8000/threads -H 'X-PLG-User: S05'
# → {"thread_id":"<id>"}

# Ask a question; the answer streams back as Server-Sent Events
curl -N -X POST http://127.0.0.1:8000/threads/<id>/runs \
  -H 'X-PLG-User: S05' \
  -H 'content-type: application/json' \
  -d '{"message":"hello"}'
```

Every endpoint except `/personas` needs an `X-PLG-User` header with a known staff ID (`S01`–`S12`), or it returns 401. `GET /me` shows the user, including the role, that `plg-api` builds from that header.

This is POC identity: `plg-api` trusts the header because only the BFF calls it, over loopback. Keep `PLG_API_HOST` at `127.0.0.1`. Binding it to a network address would let anyone on the network claim to be any staff member.

Each SSE event has a sequence number (`id:`) and a JSON payload of type `node`, `token`, `citation`, `sql_trace`, `policy_stance`, `draft`, `proposed_action`, `interrupt`, `action_result`, `done` (with `run_id`) or `error`. Heartbeat comments (lines starting with `:`) keep long runs alive. Interactive API docs are at http://127.0.0.1:8000/docs.

Threads are checkpointed in `PLG_THREADS_DB`, so they survive a server restart.

### Personal memory (issue #24)

Through `plg-api` and the web app, the assistant remembers each officer across sessions: the profile from the `staff` table, the towns and preferences they mention, and what they're working on (episodes, kept 180 days). After each answer, Haiku reads only the officer's own question and the verified findings, in the background. It masks NRIC/FIN, phone numbers and emails, and merges near-duplicates. Notes are private to the officer, are never cited, and lose to policy: a note that a verified answer contradicts is flagged (`pending_review`) and left out of the prompt. Asking about an entity ID (e.g. `T-19807`) also records a `WORKED_ON` edge in the entity graph (`.plg/graph/delta`). Memory lives in the LanceDB `memory` table beside the search index, so embedding a note needs `VOYAGE_API_KEY`. If the key is missing, memory is skipped and the answer still works. `plg ask` neither reads nor writes memory.

```bash
uv run plg memory list --user S05                # what's remembered, where each note came from, flagged notes
uv run plg memory show <id> -u S05
uv run plg memory edit <id> "Prefers short bullet lists" -u S05
uv run plg memory forget <id> -u S05

curl -s http://127.0.0.1:8000/memory -H 'X-PLG-User: S05'
curl -s -X PATCH http://127.0.0.1:8000/memory/<id> -H 'X-PLG-User: S05' -H 'content-type: application/json' -d '{"status":"retired"}'
curl -s -X DELETE http://127.0.0.1:8000/memory/<id> -H 'X-PLG-User: S05'
```

In the web app, the **Memory** link in the header opens `/memory`: list, edit and forget your notes. A flagged note can't be switched back on: edit it to make the exception clear (e.g. "for NC units, 1.0 m under Circular 07/2026"), which clears the flag, or forget it. `PATCH` with `{"status":"active"}` on a flagged note returns 409. Another officer's notes return 404.

### Business glossary

```bash
uv run plg glossary list           # every term at its current version
uv run plg glossary list --all     # every version, including superseded ones
uv run plg glossary show LOD       # current definition, source, owner, then history; accepts IDs, labels, synonyms
```

Both commands include changes approved since `make ontology` (read from `.plg/glossary_changes.jsonl`, or `PLG_GLOSSARY_CHANGES`).

#### Glossary questions and definition changes (issue #25)

- **Ask what a term means** ("What does vacant mean now, and before April 2026?"). The knowledge agent reads every approved version of the term with its dates and source document, and cites them. No search index is needed for this.
- **Propose a change** in conversation ("Propose a glossary change: from 1 Oct 2026 units under tender count as vacant again"). The `glossary` specialist turns it into a `proposed` version (v+1) inside an `approve_glossary_term` action. The change is refused if the term is unknown, if it starts on or before the date the current version took effect, or if new SQL fails the validator's dry run.
- **Who decides:**
  - Only the term owner (`owned_by`, e.g. S08 Kelvin Goh for `plg:Vacant`) approves or edits the change: `definition`, `value`, `effective_from`.
  - The owner sees it in their Approvals inbox (`GET /approvals`), labelled "Proposed by S02" and not with the proposer's question.
  - The proposer can only withdraw it.
- **On approval:**
  - The old version gets `effective_to` (the day before) and status `superseded`. Nothing is deleted.
  - The new version becomes current, and the data agent uses it, with its own SQL binding or its predecessor's, from its effective date.
  - The decision is audited with the `term_id`.
- **Stale proposals:** a second proposal against a version that has since been superseded gets 409 and can only be rejected.

### Ontology

The ontology, vocabularies and glossary are edited in `ontology/`. After changing them, regenerate the artefacts the app reads and commit them (CI fails if they drift):

```bash
make ontology
```

It validates everything first (including that each glossary term's `supersedes` chain is unbroken, and that every SQL binding in `ontology/semantic.yaml` names a glossary term and dry-runs against PLG Records) and, on any problem, lists them and exits 1 without writing anything.

#### Browsing the ontology

- **Quick overview:** `src/plg/ontology/generated/ontology_card.md` lists every node label, every relation (`Tenancy -OF_UNIT-> Unit [1]`), the vocabulary codes and the current glossary definitions. It's the same card the agent gets in its prompts.
- **Documentation site:** one page per class, relation and enum, cross-linked. Open `/tmp/plg-docs/index.md` in VS Code's Markdown preview and click through.

  ```bash
  uv run gen-doc ontology/plg.yaml -d /tmp/plg-docs
  ```

- **ER diagram:** a Mermaid diagram of the classes, their attributes and relations. View it in VS Code's Markdown preview (Mermaid support may need an extension) or paste it into https://mermaid.live. Run `uv run gen-erdiagram --help` for options to focus on part of the model.

  ```bash
  uv run gen-erdiagram ontology/plg.yaml > /tmp/plg-er.md
  ```

- **Vocabularies and synonyms:** the vocabularies are plain YAML in `ontology/vocab/`. To see which concepts a word or abbreviation maps to:

  ```bash
  uv run python -c "from plg.ontology.vocab import load_vocab; print(load_vocab().resolve('ceiling leak'))"
  ```

- **Glossary:** `uv run plg glossary list --all` and `uv run plg glossary show <term>` (see above).

## 5. Run the frontend

Start `plg-api` first (section 4), then in another terminal:

```bash
cd web
npm run dev        # http://localhost:3000
```

Open http://localhost:3000. You're sent to the sign-in page. Pick any staff persona (mock sign-in: the persona is kept in an httpOnly cookie). Then ask a question on the Ask screen. The answer streams in, with the graph nodes it passes through shown as it runs (route → knowledge → merge for a policy question). Under the answer, a Sources list has a chip for each `[n]` marker; open a chip to read the exact quoted span. If the run fails partway, an alert says the answer is incomplete and offers a Retry. A question with several parts (e.g. "How many vacant units are there in Bayshore Vale, and how is vacancy defined?") runs the specialists it needs in parallel (knowledge and data side by side in the trajectory) and comes back as one answer with a section per part. If the router can't tell what you mean, you get a clarifying question instead of an answer; reply to it in the same conversation.

The browser only talks to the Next.js BFF (`/api/...`). The BFF forwards your persona to `plg-api` as `X-PLG-User`. No API keys ever reach the browser.

For a production build: `npm run build && npm run start`.

## 6. Tests and typecheck

```bash
uv run pytest                          # full suite; no API key or network needed
uv run pytest tests/test_runs_api.py   # a single file
uv run mypy                            # strict typecheck
```

Tests drive the API in-process with a scripted `LLMClient`, so they are deterministic and never call Claude.

Web app (from `web/`):

```bash
npm test               # Vitest + React Testing Library + MSW; no back end needed
npm run typecheck
npm run lint
npm run gen:api        # regenerate openapi.json and TypeScript types from plg-api
```

The web tests replay SSE streams recorded from the real API. After changing the API's models, run `npm run gen:api` and commit the result (CI fails if the generated types drift). If the stream changed, re-record the fixtures with `uv run python scripts/record_sse_fixtures.py`.

CI (`.github/workflows/ci.yml`) runs the API checks and the web checks, including the OpenAPI drift check and a scan of the client bundle for credentials.
