# Issue #24: Personal long-term memory

## What was built
The assistant now remembers each officer across sessions. It knows their profile (seeded from the `staff` table), the towns and preferences they mention, and what they have been working on (episodes, which expire after 180 days). Each turn, `load_memory` recalls the officer's active notes and builds a labelled `<memory>` block for the answer. The block says the notes are private, are not a source, and lose to policy. After the answer, `write_memory` starts a background Haiku extraction (`extract_memory`). It reads only the officer's question and the verified findings. It masks personal data, merges near-duplicates, and flags notes that a verified answer contradicts (`pending_review`, left out of recall). It also records `WORKED_ON` edges for entity IDs the officer asked about, via `GraphWriter`. Officers can list, view, edit and forget their notes, each with its provenance, through `GET/PATCH/DELETE /memory`, `plg memory`, and a Memory screen in the web app. Another officer's notes look like they don't exist (404). A flagged note can't be switched back on over policy (409). The officer can reword it, which clears the flag so later turns check it again, or forget it.

## How it fits
Memory tailors answers without becoming evidence. It only reaches merge's system prompt, never produces citations, and so never satisfies the "every claim is cited" rule. The `WORKED_ON` edges link the entity graph (#9) to the officers who touched each entity. Conversations (#16) stay per-thread; memory carries context across threads.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/memory/store.py` | New | `MemoryStore` (LangGraph `BaseStore` over the LanceDB `memory` table): remember / items / find / edit / forget / seed_profile / recall, PII masking, near-duplicate merge, 180-day episode expiry, `FlaggedByPolicy` (a flagged note is only reworded or forgotten), `MemoryView` |
| `src/plg/memory/service.py` | New | `MemoryService`: labelled context block, background extraction (forced `record_memory` tool), conflict flagging, `WORKED_ON` linking, `drain()` on shutdown |
| `src/plg/graph/build.py` | Modified | `load_memory` and `write_memory` nodes around route…merge (only when a `MemoryService` is given); memory block appended to merge's system prompt |
| `src/plg/graph/state.py` | Modified | `memory` field (this turn's notes block) |
| `src/plg/entities/open.py` | Modified | `LazyGraph.writer()`, `work_linker()` (WORKED_ON edges; IDs the graph can't link are skipped) |
| `src/plg/search/store.py`, `lance.py` | Modified | `list_memory(prefix, now)`: every unexpired item of a namespace, any status |
| `src/plg/search/embed.py` | Modified | `LazyEmbedder` (Voyage on first use, so `plg-api` starts without a key) |
| `src/plg/api/app.py` | Modified | `/memory` endpoints, `MemoryEdit`, wiring of `MemoryStore`/`MemoryService`, drain in lifespan |
| `src/plg/cli.py` | Modified | `plg memory list | show | edit | forget --user` |
| `src/plg/llm.py` | Modified | `ScriptedLLMClient.streamed` (merge's system + messages per call) |
| `web/src/app/memory/` | New | Memory screen (list with provenance, edit, forget; flagged notes say to edit or forget them) |
| `web/src/app/api/memory/` | New | BFF routes: GET list, PATCH / DELETE one |
| `web/src/lib/server/plg-api.ts`, `web/src/app/page.tsx` | Modified | memory client calls; header link to `/memory` |
| `tests/test_memory_api.py` | New | HTTP-seam tests: seeding, background learning, expiry, labelled block, PII, dedup, conflict flag, privacy, edit/forget, no citations, WORKED_ON, recall with many notes, retired notes stay retired |
| `tests/conftest.py`, `scripts/record_sse_fixtures.py` | Modified | temp memory store, `graph_dir` and threads DB so tests and recordings never write to `.plg/` |

## Workflow
```
POST /threads/{id}/runs ─► stream_run ─► graph
  START ─► (summarise_history) ─► load_memory ──► MemoryService.context ─► MemoryStore.seed_profile / recall ─► LanceDB memory
         ─► route ─► knowledge | data | drafting ─► merge (system += <memory> block; streams tokens)
         ─► write_memory ─► MemoryService.learn_in_background (asyncio task, answer not held up)
                               ├─ work_linker ─► GraphWriter ─► WORKED_ON edges (.plg/graph/delta)
                               ├─ LLMClient.complete(extract_memory, Haiku, record_memory tool)
                               └─ MemoryStore.remember (mask, merge) / edit(status=pending_review) for conflicts
Browser /memory ─► BFF /api/memory[/id] ─► GET/PATCH/DELETE /memory[/id] (X-PLG-User) ─► MemoryStore (scoped to staff ID)
plg memory … --user S05 ─► MemoryStore
```

## Next steps
- Flagging relies on Haiku spotting a conflict in a turn that touches the topic. Nothing re-checks stored notes against current policy.
- Masking covers NRIC/FIN, phone numbers and emails. Tenant and person names are not masked yet.
- `plg ask` doesn't use memory (it has no signed-in user).
- `MemoryStore`'s `BaseStore` ops are implemented, but the graph isn't compiled with `store=`. `ListNamespacesOp` returns `[]`, and `SearchOp` ignores filters.
