# Issue #100: Conversation groups (create, rename, delete, and move by menu)

Parent: #98 (Conversation workspace). Blocked by: #99 (rename/delete a conversation).

## What's been built

- **Server-side groups per officer.** `plg_groups` sits beside `plg_threads` in `threads.sqlite`. Each thread row gains a nullable `group_id`. An older `threads.sqlite` is upgraded in place by `ALTER TABLE`.
- **REST API.**
  - `GET /groups` lists your groups, oldest first.
  - `POST /groups {name}` → 201.
  - `PATCH /groups/{id} {name}` renames a group.
  - `DELETE /groups/{id}` → 204. Its conversations go back to Recent; none is deleted.
  - `PUT /threads/{id}/group {group_id | null}` moves a conversation.
  - `GET /threads` now carries each conversation's `group_id`.
  - Names are tidied and limited to 1–80 characters, like titles (`Name` type, 422 otherwise).
  - Another officer's group, or an unknown one, is 404.
  - A move is one atomic UPDATE, so a group deleted at the same moment can't leave a dangling `group_id`.
- **BFF relays.**
  - `/api/groups` (GET, POST)
  - `/api/groups/[id]` (PATCH, DELETE)
  - `/api/threads/[id]/group` (PUT)
- **Sidebar.**
  - A "Groups" section: one disclosure button per group, named "<name>, <n> conversations", with its own Options menu (Rename group, Delete group with an inline confirmation).
  - A **New group** inline field.
  - The ungrouped conversations under "Recent conversations".
  - Each conversation's Options menu gains **Move to group…**. It opens a menu of `menuitemradio` items: the officer's groups plus "No group", with the current one checked.
  - A move is announced in the polite "Conversation updates" status ("Moved X to Arrears" / "… to Recent"). Focus follows the moved conversation, and a collapsed destination group is expanded.
  - Collapsed or expanded state is remembered per browser: localStorage `plg_collapsed_groups`, read through `useSyncExternalStore` so server and first paint agree.
  - A 404 on a stale group (deleted in another browser) refreshes the sidebar. Deleting a group that is already gone counts as done.
- **Tests.**
  - `tests/test_groups_api.py` (HTTP seam).
  - `web/src/app/api/groups/route.test.ts` (BFF).
  - `web/src/app/shell/ConversationGroups.test.tsx` (sidebar, MSW).
  - An e2e journey: keyboard-only grouping, collapse remembered across reload, the same groups in another browser, deleting a group.
  - axe checks in light and dark themes, including the phone drawer.

## How it fits

This is the first step of the sidebar track in #98 (rename/delete → **groups** → drag and pins). Officers can now organise their conversations, and the organisation follows them across browsers. Drag and drop and pins (later tickets) will reuse `PUT /threads/{id}/group` and the group sections; Move to group… stays as their keyboard equivalent. Group reordering (#98) isn't part of this ticket: groups are listed in creation order.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/threads.py` | modified | `Group`, `GroupNotFound`; `ThreadSummary.group_id`; `plg_groups` table and migration; `move`, `groups`, `create_group`, `rename_group`, `delete_group` |
| `src/plg/api/app.py` | modified | `Name` type (shared with `RenameRequest`), `GroupRequest`, `MoveRequest`; group endpoints; `group_found()` → 404 |
| `tests/test_groups_api.py` | new | API behaviour, privacy, restart, upgrade of an old DB |
| `web/src/lib/server/plg-api.ts` | modified | `moveThread`, `listGroups`, `createGroup`, `renameGroup`, `deleteGroup` |
| `web/src/app/api/groups/route.ts`, `[id]/route.ts` | new | BFF: list/create, rename/delete |
| `web/src/app/api/threads/[id]/group/route.ts` | new | BFF: move |
| `web/src/app/shell/GroupSection.tsx` | new | Group disclosure, group menu, rename, delete confirmation; `NewGroup` |
| `web/src/app/shell/ConversationItem.tsx` | modified | Move to group… menu, focus after a move |
| `web/src/app/shell/AppShell.tsx` | modified | Fetches groups; splits conversations by group; announcements; collapse/expand |
| `web/src/app/shell/collapsedGroups.ts` | new | localStorage-backed external store of collapsed group IDs |
| `web/src/app/shell/menu.ts` | new | Shared menu keyboard handling, `refusalDetail`, `tidy` |
| `web/src/app/shell/shell.module.css`, `icons.tsx` | modified | Group styles (tokens only), chevron icon |
| `web/src/lib/events.ts`, `openapi.json`, `schema.d.ts` | modified | `Group` type, regenerated API types |
| `web/src/test/msw.ts` | modified | Default "no groups" handler that survives `resetHandlers` |
| `scripts/e2e_server.py`, `serve()` in `src/plg/api/app.py` | modified | uvicorn `timeout_keep_alive` 75 s (`KEEP_ALIVE_SECONDS`): fixes intermittent BFF 502s (ECONNRESET on a pooled connection that uvicorn's 5 s default had just closed), seen more often once the sidebar also fetched `/api/groups` |
| `web/e2e/*` | modified | Journey + axe checks; `openConversation` picks the innermost item |

## Workflow

```
Sidebar (AppShell)
 ├─ refresh() ── GET /api/threads ──► plg-api GET /threads  (ThreadSummary + group_id)
 │            └─ GET /api/groups  ──► plg-api GET /groups   (Group[])
 ├─ GroupSection ── PATCH/DELETE /api/groups/[id] ──► plg-api /groups/{id} ──► ThreadStore.rename_group / delete_group
 ├─ NewGroup ────── POST /api/groups ──► plg-api POST /groups ──► ThreadStore.create_group
 ├─ ConversationItem "Move to group…" ── PUT /api/threads/[id]/group ──► plg-api PUT /threads/{id}/group ──► ThreadStore.move
 └─ collapsedGroups (localStorage, per browser) ── expand/collapse
ThreadStore ── threads.sqlite: plg_threads(group_id) + plg_groups(staff_id)
```

## Next steps

- Drag and drop into groups, and pins (sidebar track of #98); group reordering.
- Review suggestion (deferred): share a row-menu hook or inline name form between `ConversationItem` and `GroupSection`, which still duplicate their mode/focus handling.
