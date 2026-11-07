# Issue #16: Conversations persist and resume

## What was built
Officers can ask follow-ups, leave, and reopen past conversations. Threads and checkpoints are stored in SQLite (`threads_db`), so they survive a `plg-api` restart. Each user sees only their own threads (others get 404). Long histories are folded into a summary by Haiku (`summarise_history`), with entity IDs kept verbatim. Runs continue in the background and buffer their events, so a dropped connection or refresh resumes from the last event sequence number.

## How it fits
Before this, threads were an in-memory set and the checkpointer was `InMemorySaver`. Conversation state now lives in the LangGraph checkpoint. The web app gains a conversation list and resume behaviour.

## Modules
- New `src/plg/threads.py`: `ThreadStore`, `RunBuffer`, `RunRegistry`.
- New `src/plg/graph/summary.py`: `fold`, `transcript`, `with_ids`, `estimate_tokens`.
- `graph/build.py`: conditional START edge, `summarise_history` node, `checkpointer` and `settings` params, `conversation()` uses summary plus the unsummarised tail.
- `graph/state.py`: `summary` and `summarised` fields.
- `config.py`: `threads_db`, `history_token_threshold`, `history_keep_messages`.
- `api/app.py`: lifespan with `AsyncSqliteSaver`, `GET /threads`, `GET /threads/{id}`, `GET /threads/{id}/runs/latest`, ownership checks, 409 while a run is active.
- Web: BFF routes `/api/threads` (GET), `/api/threads/[id]`, `/api/threads/[id]/runs/latest`; `AskScreen.tsx` has a conversation list, history, reconnect and refresh recovery. OpenAPI types regenerated.
- Tests: `tests/test_threads_api.py`; Vitest tests in `AskScreen.test.tsx` and `conversations.test.ts`. The `make_api` fixture now uses a temp `threads_db`.
- Dependency: `langgraph-checkpoint-sqlite`.

## Workflow
```
browser ─POST /api/threads/{id}/runs─▶ BFF ─▶ plg-api: ownership check ─▶ RunRegistry.start (background task)
   │                                                      │ stream_run → graph: [summarise_history] → route → specialists → merge
   │◀──────────── SSE from RunBuffer.follow ◀─────────────┘ events buffered; checkpoint written to threads_db
   └─ drop/refresh ─GET …/runs/latest (Last-Event-ID)─▶ replay events with seq > id
 GET /threads, GET /threads/{id} ─▶ ThreadStore (own threads) + graph.aget_state (history, summary)
```

## Review follow-ups
Fixed: a run's buffer is always closed (`finally`), so followers never hang. Open, not fixed:
- Run buffers are in memory and never evicted. A run in flight at restart can't be resumed.
- `graph.checkpointer` is set in the lifespan, so an app used without the lifespan falls back to in-memory.
- An invalid `Last-Event-ID` replays from 0.
- The `plg ask` CLI is still in-memory.
- The token estimate is characters / 4.
- The 409 guard, `running` field and sessionStorage auto-reopen go beyond the ticket text.

## Verification
mypy clean. pytest 276 passed (before the final `finally` fix, after which the thread and run tests were re-run and passed). Web: Vitest, typecheck, lint and build pass; one AskScreen test was flaky once under load and passed on re-run.
