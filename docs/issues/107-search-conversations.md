# #107 — Search conversations (sidebar box + Ctrl/⌘K)

Parent: #98 (search track, first ticket). Blocked by #99 (rename/delete) and #102 (pins), both merged.

## What was built

- **Keyword index of conversations.** An SQLite FTS5 table, `plg_search`, sits in `threads.sqlite` next to `plg_threads`.
  - Each conversation has one row for its title, plus one row per answered turn (the question and the answer).
  - Answers are indexed without `[n]` markers or markdown symbols.
  - The index is kept up to date when the first question is asked, when a conversation is renamed, and when it is deleted (its rows go at once).
  - At the end of every run, the turns are read from the checkpoint and re-indexed. This happens before the client sees `done`, so a search straight after finds the new answer.
  - A `threads.sqlite` from before this ticket is back-filled when plg-api starts.
- **`GET /search?q=`** returns `SearchResults {conversations: ConversationHit[]}`.
  - Every word is matched as a prefix, so results come as the officer types.
  - Words are quoted, so FTS operators in a query are treated as plain words.
  - Results are ranked by bm25 and only the officer's own conversations are searched.
  - Each conversation appears once, at its best-matching turn.
  - A hit carries the current title, group (ID and name), pin place, where it matched (title, question or answer), the turn's question index, and a snippet split into parts, with the matched words flagged.
  - No Claude or Voyage call is made.
- **BFF** `GET /api/search`: a relay that adds `X-PLG-User`.
- **Search dialog** (`shell/SearchDialog.tsx`), opened by the field-shaped "Search conversations" button at the top of the sidebar or by Ctrl/⌘K from anywhere.
  - It is a modal dialog: a combobox over a "Conversations" listbox.
  - Arrow keys move through the results (wrapping), Enter opens one, and Escape returns focus to where search was opened from.
  - Each result shows the title, a highlighted snippet (`<mark>`), and its pin or group status ("Pinned · group X" or "In X/Recent").
  - The result count is announced in a status line.
- **Opening a result.**
  - The conversation's group is expanded, its row is scrolled into view and marked current in the sidebar.
  - The Ask screen opens the conversation at the matching turn: that question is outlined, labelled "Search match", scrolled to and focused once.
  - This works from any screen: the thread and turn are handed over in sessionStorage.

## How it fits

This is the first part of #98's search capability. Officers can find past answers without scrolling through the sidebar. It builds on #99's titles and deletion (renamed titles are found, deleted conversations drop out) and #102's pins (shown in each result). The `SearchResults` shape is grouped by type, so later tickets can add documents, uploads, approvals, audit and memory next to `conversations`.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/thread_search.py` | New | FTS5 schema, title and turn indexing, query building, ranking, one hit per conversation, snippet parts |
| `src/plg/threads.py` | Modified | ThreadStore keeps the index up to date (`asked`, `rename`, `delete`) and adds `index_turns`, `search` and `unindexed`; `RunRegistry.start`'s `observe` is now async and awaited |
| `src/plg/api/app.py` | Modified | `GET /search`, `SearchResults`, `index_on_done` observer for question and resume runs, back-fill in lifespan |
| `tests/test_search_conversations_api.py` | New | HTTP-seam tests for the acceptance criteria |
| `web/src/app/api/search/route.ts` (+ test) | New | BFF relay |
| `web/src/lib/server/plg-api.ts`, `web/src/lib/events.ts` | Modified | `search()` client; `ConversationHit` and `SearchResults` types |
| `web/openapi.json`, `web/src/lib/api/schema.d.ts` | Regenerated | API types |
| `web/src/app/shell/SearchDialog.tsx` (+ test) | New | The dialog (combobox, listbox, debounce, status, keyboard) |
| `web/src/app/shell/AppShell.tsx` | Modified | Search box, Ctrl/⌘K, inert shell while open, focus return, opening a result (expand group, reveal row) |
| `web/src/app/shell/ShellContext.tsx`, `runClient.ts` | Modified | `open(threadId, turn?)`; `ACTIVE_TURN` session key |
| `web/src/app/AskScreen.tsx`, `ask.module.css` | Modified | Opens at a turn, highlights and focuses it once |
| `web/src/app/shell/ConversationItem.tsx`, `icons.tsx`, `shell.module.css` | Modified | `data-thread-id`, `SearchIcon`, styles (tokens only) |
| `web/e2e/journeys.spec.ts`, `web/e2e/accessibility.spec.ts` | Modified | Keyboard journey; axe in both themes, desktop and phone drawer |

## Workflow

```
Officer types (Ctrl/⌘K or sidebar box)
  → SearchDialog (debounced 120 ms) → BFF GET /api/search?q= (cookie → X-PLG-User)
  → plg-api GET /search → ThreadStore.search → thread_search.search (FTS5 MATCH, joined to plg_threads/plg_groups on staff_id)
  ← ConversationHit list → options (title, <mark> snippet, pin/group)
Enter → AppShell.found → expand group, reveal row → ConversationControl.open(id, turn)
      (other screen: sessionStorage plg_active_thread/plg_active_turn → "/")
  → AskScreen.open → GET /api/threads/{id} → history → turn <li data-found> focused

Indexing:
  POST /threads/{id}/runs → ThreadStore.asked → title row
  PATCH /threads/{id}      → rename → title row
  RunRegistry pump → observe(done) → index_on_done → graph.aget_state().turns → ThreadStore.index_turns
  DELETE /threads/{id}     → ThreadStore.delete → rows dropped
  plg-api start (pre-#107 file) → every asked thread indexed from its checkpoint
```

## Verification

- `uv run pytest`: 586 passed, 31 skipped.
- `uv run mypy`: clean.
- Web: vitest 367 passed (before the review fixes, plus the shell, Ask screen and search re-run after them); typecheck and lint clean.
- Playwright: the #107 journey and the axe tests in both themes pass. The full e2e suite was not run.

## Next steps

- The rest of #98's search: Library documents (LanceDB FTS), own uploads, pending approvals, audit decisions and memories, as more groups in `SearchResults`.
- Results are capped at 20 with no "more" indicator. The pre-cap row limit (500) could hide conversations if a few threads are very long.
- Words are matched only within one row (a title row or a single turn), so a query with a word from the title and another from an answer finds nothing.
- Shotgun-surgery smell: title-row upkeep is hand-written in three ThreadStore methods. SQLite triggers on `plg_threads` could centralise it.
