# Getting started

How to set up and run the PLG "Super-Librarian" POC locally. Everything runs on your machine; no Docker or servers are needed.

## What there is to run

| Part | Status | How to run |
|---|---|---|
| Backend: `plg` CLI and `plg-api` (Python, FastAPI, LangGraph) | Available | `uv run plg ask "..."` / `uv run plg serve` |
| Frontend: web app (TypeScript, Next.js) | Not built yet (issue #3) | — |

## 1. Prerequisites

- [uv](https://docs.astral.sh/uv/) 0.8 or later. It installs Python 3.12 for you (pinned in `.python-version`).
- An Anthropic API key, for live answers. Tests don't need one.

## 2. Install

From the repo root:

```bash
uv sync
```

This creates `.venv/` with the `plg` package (editable) and the dev tools (pytest, mypy).

## 3. Environment variables

Create a `.env` file at the repo root. It is git-ignored and loaded automatically by `plg` and `plg-api` (they search upward from the current directory).

```dotenv
# Required for live answers
ANTHROPIC_API_KEY=sk-ant-...

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

## 4. Run the backend

### Ask from the command line

```bash
uv run plg ask "When do we issue a letter of demand?"
```

The answer streams to the terminal. If the run fails partway, the CLI prints an error to stderr and exits with code 1.

### Start the API

```bash
uv run plg serve        # or: uv run plg-api
```

Then, in another terminal:

```bash
# Create a thread
curl -s -X POST http://127.0.0.1:8000/threads
# → {"thread_id":"<id>"}

# Ask a question; the answer streams back as Server-Sent Events
curl -N -X POST http://127.0.0.1:8000/threads/<id>/runs \
  -H 'content-type: application/json' \
  -d '{"message":"hello"}'
```

Each SSE event has a sequence number (`id:`) and a JSON payload of type `node`, `token`, `done` (with `run_id`) or `error`. Heartbeat comments (lines starting with `:`) keep long runs alive. Interactive API docs are at http://127.0.0.1:8000/docs.

Threads are held in memory for now, so they are lost when the server restarts.

## 5. Run the frontend

Not available yet. The web app (Ask screen with mock persona sign-in) is issue #3; this section will be filled in when it lands.

## 6. Tests and typecheck

```bash
uv run pytest                          # full suite; no API key or network needed
uv run pytest tests/test_runs_api.py   # a single file
uv run mypy                            # strict typecheck
```

Tests drive the API in-process with a scripted `LLMClient`, so they are deterministic and never call Claude.
