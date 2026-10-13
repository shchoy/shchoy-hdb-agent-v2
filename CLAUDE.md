## Rules

- **Never refer to `docs/` for any context.** Do not read, search or cite anything under `docs/` to understand the app, its design or its conventions. Use the code, this file and the GitHub issues instead.

## Application map

PLG "Super-Librarian" POC: a LangGraph agent that answers PLG officers' questions, exposed through a CLI (`plg`), an HTTP API (`plg-api`) and a Next.js web app (`web/`) whose BFF proxies to `plg-api`. Python 3.12 managed with `uv` (src layout); TypeScript with npm. Runs locally with no Docker.

```
src/plg/
├── config.py        Settings: model ID per tier (haiku/sonnet/opus), max tokens, SSE heartbeat, API host/port,
│                    records_db (PLG Records SQLite, default poc-data/plg_records.db).
│                    Every field can be overridden with a PLG_<FIELD> env var (e.g. PLG_MODEL_SONNET).
├── llm.py           LLMClient protocol: the ONLY path to Claude.
│                    AnthropicLLMClient (real, traced with LangSmith @traceable) and
│                    ScriptedLLMClient (test double, replies keyed by (node, latest user message);
│                    `sent` records the messages of each call).
├── identity.py      UserCtx (staff_id, name, title, dept, role) loaded read-only from the `staff` table;
│                    role is derived from the job title (role_for). POC identity, replaced by OIDC later.
├── graph/
│   ├── state.py     PLGState (messages = completed exchanges only, question, user, answer) and PLGGraph.
│                    A turn joins `messages` only when merge answers it, so a failed run leaves no trace.
│   └── build.py     build_graph(llm): StateGraph START → merge → END. `merge` is the only node that
│                    streams tokens (via the LangGraph stream writer). In-memory checkpointer.
├── events.py        Pydantic run events: node (started/finished), token, done (run_id), error (run_id).
├── runs.py          stream_run(graph, thread_id, message, user?): runs the graph, yields numbered RunEvents,
│                    turns any failure into an error event. Shared by the API and the CLI.
├── api/app.py       create_app(settings, llm): FastAPI. GET /personas, GET /me, POST /threads,
│                    POST /threads/{id}/runs (SSE with heartbeat comments). All but /personas need the
│                    X-PLG-User header (staff ID) → UserCtx, else 401. RunEvent schemas are injected into
│                    the OpenAPI 3.1 document. serve() is the plg-api entry point.
└── cli.py           Typer app: `plg ask <question>`, `plg serve`, `plg openapi` (prints the OpenAPI JSON,
                     no API key needed). make_llm() builds the real LLMClient.

tests/               HTTP-seam tests: in-process FastAPI TestClient + ScriptedLLMClient (conftest.py; requests
                     carry USER = X-PLG-User S05). test_anthropic_client.py runs the real client against a
                     fake Anthropic endpoint.
scripts/record_sse_fixtures.py
                     Records real SSE streams from the in-process API into web/src/test/fixtures/*.sse.
web/                 Next.js App Router app (presentation only) + BFF route handlers under src/app/api/
                     (Node runtime, no buffering): /api/session (mock sign-in, httpOnly `plg_user` cookie),
                     /api/threads, /api/threads/[id]/runs (forwards X-PLG-User, streams SSE through).
                     Pages: /sign-in, / (Ask screen: streamed answer, node trajectory, error + Retry).
                     openapi.json + src/lib/api/schema.d.ts are GENERATED (`npm run gen:api`); SSE frames
                     are parsed and zod-validated in src/lib/events.ts. Server-only code in src/lib/server/.
                     Tests: Vitest + RTL + MSW replaying the recorded fixtures.
.github/workflows/ci.yml
                     api job (mypy, pytest) and web job (regen OpenAPI types, fail on drift, typecheck,
                     lint, test, build, bundle credential check).
poc-data/            Synthetic corpus, plg_records.db and _master ground truth (tests/evals only).
.claude/skills/      Project skills (implement, tdd, code-review, post-implement, ...).
```

Flow: browser → BFF `/api/threads/{id}/runs` (adds X-PLG-User from the cookie) → `POST /threads/{id}/runs` (or `plg ask`) → `stream_run` → graph → `merge` → `LLMClient.stream_text` → events → stdout / SSE.

### Commands

- Install: `uv sync`
- Tests: `uv run pytest` (single file: `uv run pytest tests/test_runs_api.py`)
- Typecheck: `uv run mypy` (strict)
- Ask: `uv run plg ask "hello"` · Serve: `uv run plg serve` (http://127.0.0.1:8000)
- Web (in `web/`): `npm ci` · `npm run dev` (http://localhost:3000) · `npm test` · `npm run typecheck` · `npm run lint`
- After changing any API model: `npm run gen:api` in `web/` and commit the regenerated files (CI fails on drift);
  re-record fixtures with `uv run python scripts/record_sse_fixtures.py` if the SSE stream changed.
- API keys (`ANTHROPIC_API_KEY`, `LANGSMITH_API_KEY`, ...) live in `.env` at the repo root, loaded by the CLI and `plg-api`.

### Conventions

- Claude is only ever called through `LLMClient`; tests never hit the network and use `ScriptedLLMClient`.
- Test at the HTTP seam and assert on received SSE events, not on internals. Web tests assert on rendered UI
  and BFF responses, with MSW standing in for plg-api.
- The browser never talks to plg-api and holds no credentials: PLG_API_URL is server-only, never NEXT_PUBLIC_*.
- `wrap_anthropic` is not used for streaming: langsmith 0.14.8's stream reducer crashes with anthropic 1.13.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for shchoy/shchoy-hdb-agent-v2, via the `gh` CLI. Read with `gh issue view <n> --comments`, list with `gh issue list --state open`, comment with `gh issue comment <n> --body "..."`, and label with `gh issue edit <n> --add-label "..."`. Issue #1 is the tracking spec; implementation tickets are its children and declare their blockers.
