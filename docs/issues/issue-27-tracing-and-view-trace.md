# Issue #27 — Tracing and "View trace" link

## What was built

- **One LangSmith trace per run.** Every question and every approval decision (resume) through `plg-api` or `plg ask` is a root run `plg_run` whose ID is the run ID reported in the `done` / `error` event (the same ID feedback already uses).
  - **Root metadata:** `thread_id`, `user_id`, `user_role`, `channel` (`api` | `cli`), `git_sha`, `kind` (`question` | `resume` + `action_id`, `decision`), and the routed `intents` (added when `route` finishes).
  - **Approval interrupts:** a run that stops for approval is marked `interrupted` and lists the pending actions in its outputs (`awaiting_approval`).
- **Everything nests under that root.** Child runs inherit the thread, user, channel and git SHA:
  - LangGraph nodes and `Send()` branches
  - Claude calls: `AnthropicLLMClient` now uses `wrap_anthropic`; each call has `node` and `tier` metadata and `ls_model_name`
  - Tool calls (`@traceable`, run type `tool`)
  - Searches (`Searcher.search` is `@traceable`, run type `retriever`, hits shown as documents)
- **PII masking before upload.** Every trace goes through `tracing_client`, a `langsmith.Client` with an anonymizer. It masks NRIC/FIN numbers, emails, phone numbers and the tenant contact names from PLG Records in inputs, outputs, errors and metadata. `install_tracer` also makes that client LangSmith's default, so traces made outside a graph run (`plg sync` scans, `plg graph lineage`) are masked too.
- **Developer personas and the "View trace" link.**
  - A new `developers` setting (default `S08`; set with `PLG_DEVELOPERS`) sets `UserCtx.developer`.
  - `GET /threads/{id}/runs/{run_id}/trace` returns the trace URL only for a developer's own answered runs:
    - 403 for anyone who isn't a developer
    - 404 for another user's thread or an unknown run
    - 503 when tracing is off
    - 502 when LangSmith can't be reached
  - In the web app, the BFF route redirects to that URL, and developers see a **View trace** link (new tab) under each answer.

## How it fits the whole

A developer can open any answer they got and see what happened: the route decision, which specialists ran in parallel, every Claude call with its model tier, every SQL or search tool call, and any interrupt or resume, all filtered by thread or user in LangSmith. Officers' feedback (#26) already points at the same run ID, so 👎 runs in the annotation queue open on the same trace. Tenant PII never leaves the process unmasked.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/tracing.py` | New | PII masker, masking `tracing_client`, `git_sha`, `Tracer` (root run + trace URL), `open_tracer` / `install_tracer` |
| `src/plg/runs.py` | Modified | `stream_run(..., tracer, channel)`: wraps the run in the root trace; intents, interrupt and answer recorded; run ID carried in `configurable` only |
| `src/plg/llm.py` | Modified | `AnthropicLLMClient` via `wrap_anthropic`; node and tier metadata per call; untraced streams use a bare client (langsmith 0.14.8 limitation) |
| `src/plg/agents/runtime.py` | Modified | Tool calls are `@traceable` tool runs |
| `src/plg/search/rerank.py` | Modified | `Searcher.search` is a `@traceable` retriever run |
| `src/plg/threads.py` | Modified | `RunRegistry(tracer)` passes the tracer to each run |
| `src/plg/config.py` | Modified | `developers` setting + `developer_ids` |
| `src/plg/identity.py` | Modified | `UserCtx.developer` |
| `src/plg/api/app.py` | Modified | `create_app(tracer=...)`; `GET /threads/{id}/runs/{run_id}/trace`; feedback reuses the tracer's client; `serve()` installs the tracer |
| `src/plg/cli.py` | Modified | `make_tracer`; `plg ask` traced on channel `cli`; `sync` / `graph lineage` install the masking client |
| `web/src/app/api/threads/[id]/runs/[runId]/trace/route.ts` | New | BFF: 307 to the trace URL (http(s) only), relays refusals |
| `web/src/lib/server/plg-api.ts` | Modified | `getTraceLink` |
| `web/src/app/TraceLink.tsx` | New | "View trace" link |
| `web/src/app/AskScreen.tsx`, `page.tsx`, `ask.module.css` | Modified | `developer` prop; link under live and earlier answers |
| `tests/test_tracing_api.py`, `tests/conftest.py` (`LangSmithApi`), `tests/test_anthropic_client.py` | New / modified | HTTP-seam tests against a recording LangSmith API |
| `web/src/app/AskScreen.test.tsx`, `.../trace/route.test.ts` | Modified / new | UI and BFF tests |

## Workflow

```
browser (developer) ── "View trace" ─▶ BFF /api/threads/{id}/runs/{run}/trace ─▶ plg-api GET /threads/{id}/runs/{run}/trace
                                                                                   │ owner? developer? answered run? tracer?
                                                                                   └▶ Tracer.url → LangSmith project URL + /r/{run}
                                      ◀──────────── 307 redirect ─────────────────┘

POST /threads/{id}/runs | /resume ─▶ RunRegistry(tracer) ─▶ stream_run(tracer, channel="api")   (plg ask: channel="cli")
   └▶ Tracer.run(run_id) ── root plg_run {thread_id, user_id, user_role, channel, git_sha, kind, intents, interrupted}
         └▶ graph.astream ─▶ node runs (screen_input, route, Send branches: knowledge/data/…, merge, approval, execute_action)
               ├▶ AnthropicLLMClient (wrap_anthropic) ─ llm runs {node, tier, model}
               ├▶ run_agent tools (@traceable tool) ─▶ Searcher.search (@traceable retriever)
               └▶ all uploads via tracing_client ─ anonymizer masks NRIC / email / phone / tenant contacts
```

## Next steps

- Real identity (OIDC) should replace the `developers` staff-ID list with a group or role claim.
- Masking covers identity numbers, emails, phones and tenant contact names. Tenant company names and free-text names that aren't in PLG Records are not masked.
- Resume runs are traced but have no answer turn, so they have no "View trace" link; open them from the thread in LangSmith (metadata `thread_id`).
- `git_sha` is HEAD; a run from a dirty working tree is not marked as such.
- `plg ask` has no signed-in user, so CLI traces carry no `user_id`.
