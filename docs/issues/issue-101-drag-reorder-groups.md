# Issue #101: Drag conversations into groups and reorder groups

Parent: #98 (sidebar track: rename/delete #99 → groups #100 → **drag / reorder #101** → pins). Blocked by #100.

## What's been built

- **Stored group order.** `plg_groups` has a `position` column. `ThreadStore.groups()` lists an officer's groups in their order, and a new group goes last. `reorder_groups(staff_id, group_ids)` sets a new order in one locked transaction. The list must name each of the officer's groups exactly once; otherwise it raises `StaleGroupOrder`. A `threads.sqlite` from before #101 is upgraded in place, and its groups keep their creation order.
- **API.** `PUT /groups/order {group_ids}` returns the reordered `Group` list. It returns 409 when the order is stale (a group was created or deleted in another browser), repeats an ID, or names another officer's group.
- **BFF.** `PUT /api/groups/order` checks the body (422 unless it is a list of strings), forwards `X-PLG-User` and relays plg-api's reply or refusal.
- **Sidebar drag and drop** (native HTML5):
  - A conversation dropped on a group moves into it; dropped on Recent, it leaves its group.
  - A group dropped on another group takes that group's place, and the new order is saved server-side.
  - While a row is dragged, every place it can go is outlined (dashed) and the one under the pointer is tinted. Its current place is not a target.
  - A drag never opens a conversation. The drag data uses a private MIME type, so dropping a row on a text field types nothing.
  - A refused drop shows a `role=alert`.
- **Keyboard equivalents.**
  - Each group's menu has **Move up** and **Move down**, hidden at the ends. Focus returns to the group's Options button.
  - Conversations already have **Move to group…** (#100).
  - Every move is announced in the polite "Conversation updates" status: "Moved X to G" / "Moved X to Recent", or "Moved group X to position n of m".

## How it contributes

It finishes the grouping part of #98's sidebar. Officers can now organise conversations by direct manipulation or entirely by keyboard. The order of their groups is stored server-side, so it follows them across browsers like the group names and memberships do. Pins come next and build on the same drop-zone and ordering pattern.

## Modules

| Path | New / modified | Role |
| --- | --- | --- |
| `src/plg/threads.py` | modified | `position` column + migration, `reorder_groups`, `StaleGroupOrder`, ordered `groups()`, new group last |
| `src/plg/api/app.py` | modified | `GroupOrderRequest`, `PUT /groups/order` (409 on a stale order) |
| `tests/test_groups_api.py` | modified | reorder persisted across a restart, new group last, 409 cases, pre-#101 DB upgrade |
| `web/src/app/api/groups/order/route.ts` | new | BFF relay for the reorder |
| `web/src/lib/server/plg-api.ts` | modified | `reorderGroups` |
| `web/src/app/api/groups/route.test.ts` | modified | BFF reorder: forwarded body/user, 401/422/409 |
| `web/src/app/shell/menu.ts` | modified | `moveThread` (shared by the menu and drops), `DRAG_TYPE`, `DragHandle` / `DropZone` types |
| `web/src/app/shell/AppShell.tsx` | modified | drag state, `dropZone()` / `dragHandle()`, `dropThread`, `reorder`, Recent drop box, drop error alert |
| `web/src/app/shell/GroupSection.tsx` | modified | drop zone on the group, draggable row, Move up / Move down, inline refusal |
| `web/src/app/shell/ConversationItem.tsx` | modified | draggable row, uses `moveThread` |
| `web/src/app/shell/shell.module.css` | modified | `data-drop` available/over styles, `.recent` box |
| `web/src/app/shell/ConversationGroups.test.tsx` | modified | Move up/down, refused reorder, drag into a group / to Recent without opening, highlight, group drag up and down, drag carries no text |
| `web/e2e/journeys.spec.ts` | modified | real-browser drag into a group (highlight + axe mid-drag), group drag, keyboard Move down |
| `web/openapi.json`, `web/src/lib/api/schema.d.ts` | regenerated | new endpoint types |

## Workflow

```
drag a conversation row ──dragstart──▶ AppShell.dragged = {thread}
   over a group <li> / the Recent box: dropZone(zone) → data-drop available | over
   drop ─▶ menu.moveThread ─▶ PUT /api/threads/{id}/group ─▶ plg-api ThreadStore.move
          ok  → threads state updated, group expanded, "Moved X to G" announced
          404 → sidebar refresh + alert

drag a group row onto another group           group menu → Move up / Move down
                 └──────────────┬──────────────┘
                 AppShell.reorder(group, index)
                 ─▶ PUT /api/groups/order {group_ids} (BFF) ─▶ PUT /groups/order
                 ─▶ ThreadStore.reorder_groups (BEGIN IMMEDIATE; exact set check)
          ok  → groups state = response, "Moved group X to position n of m"
          409 → sidebar refresh + alert (in the group row, or the sidebar for a drop)
```

## Next steps

- Pins (#98, the next ticket in the sidebar track) can reuse `DropZone` and the server-side order pattern.
- HTML5 drag and drop doesn't work on most touch browsers. On a phone the menus (Move to group…, Move up/down) are the way to move things.
- A group dropped on another takes that group's index. There is no "drop between" position marker.
