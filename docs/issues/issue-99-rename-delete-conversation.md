# Issue #99: Rename and delete a conversation

Parent: #98 (Conversation workspace: uploads, groups, pins and search). This is the first ticket of the sidebar track (rename/delete → groups → drag / pins).

## What's been built

- **Rename.** Each conversation in the sidebar has an Options (⋯) menu with **Rename** and **Delete**.
  - Rename opens an inline title field: Enter saves, Escape cancels.
  - The title is stored server-side in `plg_threads`, so it survives a reload and shows in every browser.
  - Later questions keep the officer's title. Before this, titles were fixed to the first 80 characters of the first question.
- **Delete.** Delete opens an inline confirmation ("Delete <title>?"); focus starts on Cancel.
  - Once confirmed, the conversation goes from the sidebar. Its `plg_threads` row, the buffer of its latest run and its LangGraph checkpoint are all removed.
  - Afterwards the thread is 404 on every endpoint: history, runs, replay, cancel, resume, trace and feedback. It also drops out of `/approvals`.
  - Audit entries are kept.
  - Deleting the conversation that is open on the Ask screen starts a new conversation.
- **Refusals.**
  - Delete returns 409, with a plain reason, while the conversation is answering or has an action awaiting approval. The sidebar shows that reason as an alert.
  - Another officer's conversation is 404 for both rename and delete.
- **Accessibility.**
  - The menu is a proper ARIA menu: arrow keys, Home and End move between items, and Escape returns focus to the Options button. Escape closes only the menu, never the phone drawer.
  - Renames and deletions are announced through a polite status region.
  - axe passes with the menu, the rename field and the confirmation open, in both themes and in the phone drawer.

## How it contributes

Officers can now keep their conversation list tidy and meaningful, and remove conversations they no longer need. Delete keeps the approval and audit guarantees intact: it can't remove a thread that is mid-run or holding a pending action, and audit records always outlive the thread. Server-side titles and a deletion that is 404 everywhere are also the base the next sidebar tickets build on: groups, pins and the search index, which has to drop deleted threads.

## Module breakdown

| Path | New / Modified | Role |
|---|---|---|
| `src/plg/threads.py` | Modified | `ThreadStore.rename` / `delete`; `RunRegistry.running` / `forget` (`start` uses `running`) |
| `src/plg/api/app.py` | Modified | `RenameRequest` (whitespace collapsed, 1–80 chars); `PATCH /threads/{id}`; `DELETE /threads/{id}` (409 checks, row, run buffer and checkpoint removal via `adelete_thread`) |
| `tests/test_rename_delete_api.py` | New | HTTP-seam tests for every acceptance criterion |
| `web/openapi.json`, `web/src/lib/api/schema.d.ts` | Modified (generated) | New endpoints and `RenameRequest` |
| `web/src/lib/server/plg-api.ts` | Modified | `renameThread`, `deleteThread` |
| `web/src/app/api/threads/[id]/route.ts` | Modified | BFF `PATCH` and `DELETE` (refusals relayed, 401 / 502) |
| `web/src/app/api/threads/[id]/route.test.ts` | New | BFF tests with MSW |
| `web/src/app/shell/ConversationItem.tsx` | New | Sidebar row: open button, Options menu, inline rename, delete confirmation, refusal alert |
| `web/src/app/shell/ConversationItem.test.tsx` | New | Keyboard menu, rename, cancel, confirm delete, refusal, drawer Escape |
| `web/src/app/shell/AppShell.tsx` | Modified | Renders `ConversationItem`; announcement region; after a delete: focus moves to the list heading, the active thread is cleared and a new conversation starts |
| `web/src/app/shell/icons.tsx`, `shell.module.css` | Modified | `MoreIcon`; row, menu, rename and confirm styles (tokens) |
| `web/e2e/helpers.ts`, `journeys.spec.ts`, `accessibility.spec.ts` | Modified | `openConversation`; rename → other browser → delete journey; axe on the menu states |
| `CLAUDE.md`, `START.md` | Modified | Map and usage |

## Workflow map

```
Sidebar (AppShell → ConversationItem)
  Options ▸ Rename ─ PATCH /api/threads/{id} {title} ─▶ BFF route.ts ─ renameThread ─▶ plg-api PATCH /threads/{id}
                                                                                       owned() → ThreadStore.rename → ThreadSummary
  Options ▸ Delete ▸ confirm ─ DELETE /api/threads/{id} ─▶ BFF route.ts ─ deleteThread ─▶ plg-api DELETE /threads/{id}
        owned() (else 404)
        RunRegistry.running? ─ 409 "still answering"
        waiting() (checkpoint interrupts) non-empty? ─ 409 "awaiting approval"
        ThreadStore.delete → RunRegistry.forget → checkpointer.adelete_thread
        AuditLog untouched
  ◀─ 204 → list updated, "Deleted …" announced, open conversation → AskScreen.startNew()
  ◀─ 409 detail → role=alert in the confirmation

After delete: every /threads/{id}/… endpoint, plus /feedback → owned() → 404; resume by a curator → waiting() empty → 404;
/approvals (threads.all_asked) no longer lists it.
```

## Next steps

- Groups, pins, and drag with a keyboard "Move to group…" item, which can join this Options menu (#98 sidebar track).
- When conversation search lands, deleting a thread must also remove its search entries.
- Possible follow-ups:
  - Disable Delete in the menu while the open conversation is answering. The server already refuses it with a clear message.
  - `GET /drafts/{id}/file` still serves a deleted conversation's DOCX to its owner, because drafts are checked by owner, not by thread.
  - A thread that was created but never asked can be renamed, and then gets listed.
