## Rules

- **Never refer to `docs/` for any context.** Do not read, search or cite anything under `docs/` to understand the app, its design or its conventions. Use the code, this file and the GitHub issues instead.

## Application map

PLG "Super-Librarian" POC: a LangGraph agent that answers PLG officers' questions, exposed through a CLI (`plg`) and an HTTP API (`plg-api`). Python 3.12, managed with `uv`, src layout. Runs locally with no Docker.

```
src/plg/
├── config.py        Settings: model ID per tier (haiku/sonnet/opus), max tokens, SSE heartbeat, API host/port.
│                    Every field can be overridden with a PLG_<FIELD> env var (e.g. PLG_MODEL_SONNET).
├── llm.py           LLMClient protocol: the ONLY path to Claude.
│                    AnthropicLLMClient (real, traced with LangSmith @traceable) and
│                    ScriptedLLMClient (test double, replies keyed by (node, latest user message)).
├── graph/
│   ├── state.py     PLGState (messages, answer) and the PLGGraph type alias.
│   └── build.py     build_graph(llm): StateGraph START → merge → END. `merge` is the only node that
│                    streams tokens (via the LangGraph stream writer). In-memory checkpointer.
├── events.py        Pydantic run events: node (started/finished), token, done (run_id), error (run_id).
├── runs.py          stream_run(graph, thread_id, message): runs the graph, yields numbered RunEvents,
│                    turns any failure into an error event. Shared by the API and the CLI.
├── api/app.py       create_app(settings, llm): FastAPI. POST /threads, POST /threads/{id}/runs (SSE with
│                    heartbeat comments). serve() is the plg-api entry point.
└── cli.py           Typer app: `plg ask <question>`, `plg serve`. make_llm() builds the real LLMClient.

tests/               HTTP-seam tests: in-process FastAPI TestClient + ScriptedLLMClient (conftest.py).
                     test_anthropic_client.py runs the real client against a fake Anthropic endpoint.
poc-data/            Synthetic corpus, plg_records.db and _master ground truth (tests/evals only).
.claude/skills/      Project skills (implement, tdd, code-review, post-implement, ...).
```

Flow: `plg ask` / `POST /threads/{id}/runs` → `stream_run` → graph → `merge` → `LLMClient.stream_text` → events → stdout / SSE.

### Commands

- Install: `uv sync`
- Tests: `uv run pytest` (single file: `uv run pytest tests/test_runs_api.py`)
- Typecheck: `uv run mypy` (strict)
- Ask: `uv run plg ask "hello"` · Serve: `uv run plg serve` (http://127.0.0.1:8000)
- API keys (`ANTHROPIC_API_KEY`, `LANGSMITH_API_KEY`, ...) live in `.env` at the repo root, loaded by the CLI and `plg-api`.

### Conventions

- Claude is only ever called through `LLMClient`; tests never hit the network and use `ScriptedLLMClient`.
- Test at the HTTP seam and assert on received SSE events, not on internals.
- `wrap_anthropic` is not used for streaming: langsmith 0.14.8's stream reducer crashes with anthropic 1.13.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for shchoy/shchoy-hdb-agent-v2, via the `gh` CLI. Read with `gh issue view <n> --comments`, list with `gh issue list --state open`, comment with `gh issue comment <n> --body "..."`, and label with `gh issue edit <n> --add-label "..."`. Issue #1 is the tracking spec; implementation tickets are its children and declare their blockers.
