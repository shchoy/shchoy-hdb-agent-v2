# Issue #80: Stop generating — cancel a running answer

Parent: #74 · Blocked by: #77 (chat thread layout and composer)

## What's been built

While an answer is being written, **Stop** replaces **Ask** in the composer. Pressing it really cancels the run in plg-api, not just in the browser:

- **plg-api**: `POST /threads/{id}/runs/latest/cancel`, owner-checked. It cancels the run's background task, waits until it has stopped and returns 204. The run's SSE stream ends with a new `cancelled` event (`{type, seq, run_id}`), part of the `RunEvent` schema.
  - Refusals: another user's thread (or an unknown one) is 404. There is nothing to stop (409) when no run is in progress, merge has already answered, or the run is carrying out an approval decision.
- **No trace of the turn**: the stop lands before merge commits anything, so the checkpoint holds no message, turn or proposed action, as with a failed run. The next question on the thread runs at once (no 409).
- **Tracing**: a traced run's root gets `cancelled: true` metadata and the partial answer as its output; the trace records the `CancelledError`.
- **Web**:
  - The BFF route `POST /api/threads/[id]/runs/latest/cancel` relays plg-api's 204/404/409, and returns 502 when plg-api is unreachable.
  - On the `cancelled` event the Ask screen shows the turn as **"Stopped."** and drops the partial answer, which is never added to the conversation. The status line says "Answer stopped.", the composer is focused again and the sidebar refreshes.
  - The Approvals and Document check screens read a `cancelled` stream as "stopped", not as a dropped connection.
- **CLI**: unchanged (`plg ask` never cancels; `stream_run` only gained an optional `run_id`).

## How it contributes

Officers are no longer stuck waiting for an answer they no longer want: a wrong or over-broad question can be stopped and rephrased at once. Because the cancel happens in plg-api, the Claude calls and the graph actually stop. The rules for when a run can be stopped keep the system's guarantees:
- An answer that has already been committed is never reported as "nothing kept".
- An approval decision can't be cut off between its side effect (Outbox, i-EMS, glossary) and its audit entry.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/events.py` | Modified | `CancelledEvent` added to the `RunEvent` union |
| `src/plg/threads.py` | Modified | `RunBuffer.task` / `answered` / `stoppable`; `RunRegistry.cancel` (raises `NothingToStop`); `pump` appends `cancelled` on `CancelledError` |
| `src/plg/runs.py` | Modified | `stream_run(..., run_id?)`; a cancelled traced run's root is marked `cancelled` |
| `src/plg/api/app.py` | Modified | `POST /threads/{id}/runs/latest/cancel` (204 / 404 / 409) |
| `tests/test_cancel_api.py` | New | HTTP-seam tests with ScriptedLLMClient: `cancelled` ends the stream, no history, no pending action, next question runs, owner-only, 409 cases, traced as cancelled |
| `scripts/record_sse_fixtures.py` | Modified | `cancelled` scenario (a slow merge stopped part way) |
| `web/src/test/fixtures/cancelled.sse` | New | Recorded stopped run |
| `web/openapi.json`, `web/src/lib/api/schema.d.ts` | Regenerated | Cancel endpoint + `CancelledEvent` |
| `web/src/lib/events.ts` | Modified | zod `cancelled` frame (OpenAPI drift check) |
| `web/src/lib/server/plg-api.ts` | Modified | `cancelRun(staffId, threadId)` |
| `web/src/app/api/threads/[id]/runs/latest/cancel/route.ts` (+ test) | New | BFF relay of the cancel |
| `web/src/app/AskScreen.tsx` | Modified | Stop button, `stopped` run state, "Stopped." note, refocus, sidebar refresh |
| `web/src/app/ask.module.css` | Modified | `.stopped` note style (tokens only) |
| `web/src/app/AskScreen.test.tsx` | Modified | Stop flow tests; Ask is replaced by Stop while answering |
| `web/src/app/approvals/ApprovalsScreen.tsx`, `web/src/app/doc-check/DocCheckScreen.tsx` | Modified | Read a `cancelled` stream as "stopped" |
| `web/src/test/sse.ts` | Modified | `cancelled` fixture name |

## Workflow

```
Officer presses Stop (AskScreen, while running)
  → POST /api/threads/{id}/runs/latest/cancel  (BFF: plg_user cookie → X-PLG-User)
    → POST /threads/{id}/runs/latest/cancel     (plg-api: owned() else 404)
      → RunRegistry.cancel(thread_id)
          RunBuffer.stoppable? (a question, merge not finished, not finished) else 409
          task.cancel() → CancelledError inside stream_run / graph.astream (tracer root marked cancelled)
          pump: append CancelledEvent(seq+1, run_id) → buffer closes
          await the task → 204
  ← the open SSE stream (POST /runs or GET /runs/latest) delivers `cancelled`
AskScreen.follow: `cancelled` → run status "stopped" → "Stopped." note, Ask re-enabled, composer focused, sidebar refresh
Next question → POST /runs → a fresh run (no 409; the checkpoint holds nothing from the stopped turn)
```

## Next steps

- If the officer presses Stop just as a new conversation is being created or the run is being registered, plg-api answers 409 and the answer goes on. Stop is disabled until the conversation exists, but the officer gets no message for that 409.
- Optional: a Playwright journey for Stop (scripts/e2e_server.py would need a slow merge script).
- A stop that lands after merge has finished gets a 409 and the answer completes normally. The UI just carries on and doesn't explain why.
