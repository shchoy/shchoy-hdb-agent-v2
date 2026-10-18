# Getting started

How to set up and run the PLG "Super-Librarian" POC locally. Everything runs on your machine: one API process and the web dev server, with no Docker.

## What there is to run

| Part | Status | How to run |
|---|---|---|
| Backend: `plg` CLI and `plg-api` (Python, FastAPI, LangGraph) | Available: policy Q&A with citations | `uv run plg sync`, then `uv run plg ask "..."` / `uv run plg serve` |
| Frontend: web app (TypeScript, Next.js) with a BFF | Available: sign-in and Ask screen with citation chips | `cd web && npm run dev` |

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
| `PLG_API_HOST` | `127.0.0.1` | `plg-api` bind address |
| `PLG_API_PORT` | `8000` | `plg-api` port |
| `PLG_RECORDS_DB` | `poc-data/plg_records.db` | PLG Records SQLite database (read-only; source of the staff personas) |
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

### Ask from the command line

```bash
uv run plg ask "When do we issue a letter of demand?"
```

The answer streams to the terminal, then its sources: each `[n]` in the answer is listed with its document, section and the quoted sentence. Policy and records questions are answered only from the indexed documents (current versions unless you ask about an earlier date). If the sources don't cover the question, the answer says so. If the run fails partway, the CLI prints an error to stderr and exits with code 1.

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

Each SSE event has a sequence number (`id:`) and a JSON payload of type `node`, `token`, `done` (with `run_id`) or `error`. Heartbeat comments (lines starting with `:`) keep long runs alive. Interactive API docs are at http://127.0.0.1:8000/docs.

Threads are held in memory for now, so they are lost when the server restarts.

### Business glossary

```bash
uv run plg glossary list           # every term at its current version
uv run plg glossary list --all     # every version, including superseded ones
uv run plg glossary show LOD       # current definition, source, owner, then history; accepts IDs, labels, synonyms
```

### Ontology

The ontology, vocabularies and glossary are edited in `ontology/`. After changing them, regenerate the artefacts the app reads and commit them (CI fails if they drift):

```bash
make ontology
```

It validates everything first (including that each glossary term's `supersedes` chain is unbroken) and, on any problem, lists them and exits 1 without writing anything.

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

Open http://localhost:3000. You're sent to the sign-in page. Pick any staff persona (mock sign-in: the persona is kept in an httpOnly cookie). Then ask a question on the Ask screen. The answer streams in, with the graph nodes it passes through shown as it runs (route → knowledge → merge for a policy question). Under the answer, a Sources list has a chip for each `[n]` marker; open a chip to read the exact quoted span. If the run fails partway, an alert says the answer is incomplete and offers a Retry.

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
