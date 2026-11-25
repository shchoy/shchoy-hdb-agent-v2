# Issue #102: Pin conversations and groups

Parent: #98 (sidebar track: rename/delete → groups → drag / pins). Blocked by #100.

## What was built

Officers can pin their own conversations and groups. Pinned items appear in a **Pinned** section at the top of the
sidebar's Conversations navigation, in the order they were pinned (conversations and groups share one sequence).

- **Pin / Unpin** in each conversation's Options menu; **Pin group / Unpin group** in each group's menu. Each change is
  announced ("Pinned X", "Unpinned group Y") and focus follows the item to its Options button in its new place.
- A pinned conversation appears **only** in Pinned. It keeps its `group_id`, so unpinning puts it back in its group (expanded so
  it stays visible), or under Recent. "Move to group…" still works on a pinned conversation: it sets where unpinning will
  return it, and the announcement says "It stays pinned." Pinned conversations aren't draggable.
- A pinned group shows in Pinned with its (unpinned) conversations, collapsible as usual, and no longer under Groups. It has
  no Move up / Move down and can't be dragged: its place is its pin order. Reordering the other groups keeps the pinned
  groups' slots in the officer's group order, so an unpinned group returns to where it was.
- Pins are stored server-side (threads.sqlite), private per officer, survive restarts and follow the officer across
  browsers. Deleting a pinned conversation or group drops its pin. A threads.sqlite from before #102 is upgraded in place.
- The Pinned section is hidden when nothing is pinned. axe passes on it in both themes, including in the phone drawer.

## How it contributes

This completes the sidebar organisation in #98: rename/delete (#99), groups (#100) and drag/reorder (#101) are now joined by
pins. Officers can keep the conversations and groups they return to most at the top, whichever browser they use.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/threads.py` | modified | `pinned` INTEGER column on `plg_threads` and `plg_groups` (migration); `ThreadStore.pin`, `pin_group`, `_set_pin` (appends under `BEGIN IMMEDIATE`, keeps the place of an item already pinned); `ThreadNotFound`; `ThreadSummary.pinned`, `Group.pinned` |
| `src/plg/api/app.py` | modified | `PinRequest`; `PUT /threads/{id}/pin`, `PUT /groups/{id}/pin` (404 when not yours) |
| `tests/test_pins_api.py` | new | HTTP-seam tests: order, re-pin, unpin back to its group, deletion, privacy, restart, upgrade |
| `tests/test_groups_api.py` | modified | rename response now carries `pinned` |
| `web/openapi.json`, `web/src/lib/api/schema.d.ts` | regenerated | new endpoints and fields |
| `web/src/lib/server/plg-api.ts` | modified | `pinThread`, `pinGroup` |
| `web/src/app/api/threads/[id]/pin/route.ts`, `web/src/app/api/groups/[id]/pin/route.ts` | new | BFF relays (401 / 422 / refusal relayed) |
| `web/src/app/api/pins.test.ts` | new | BFF tests |
| `web/src/app/shell/menu.ts` | modified | `setPinned` (shared fetch + refusal handling) |
| `web/src/app/shell/ConversationItem.tsx` | modified | Pin / Unpin item; menu closes after a move (a pinned row stays mounted) |
| `web/src/app/shell/GroupSection.tsx` | modified | Pin group / Unpin group; `focusOptions`; optional `position` / `onMove` (none when pinned) |
| `web/src/app/shell/AppShell.tsx` | modified | Pinned section, pin handlers + announcements, reorder among unpinned groups, drag/drop rules for pinned items |
| `web/src/app/shell/shell.module.css` | modified | `.pinned` section style |
| `web/src/app/shell/Pins.test.tsx` | new | sidebar tests (MSW) |
| `web/src/app/shell/ConversationItem.test.tsx` | modified | menu now has Pin |
| `web/e2e/journeys.spec.ts`, `web/e2e/accessibility.spec.ts` | modified | pin journey (keyboard, another browser); axe on Pinned in light/dark + drawer |

## Workflow

```
Sidebar menu (Pin / Unpin)
  → menu.ts setPinned → fetch PUT /api/{threads|groups}/{id}/pin  (browser → BFF)
  → BFF route (session cookie → X-PLG-User) → plg-api.ts pinThread / pinGroup
  → plg-api PUT /threads/{id}/pin | /groups/{id}/pin (ownership checked → 404)
  → ThreadStore.pin / pin_group → _set_pin (threads.sqlite, pinned = next place | NULL)
  ← ThreadSummary / Group with `pinned`
  → AppShell updates state, announces, moves focus; GET /api/threads + /api/groups on later refreshes
    give `pinned`, and AppShell renders Pinned (sorted by place) above Groups and Recent.
```

## Next steps

- Pin order can't be changed except by unpinning and pinning again. If officers want it, add drag-and-drop with a
  keyboard equivalent in Pinned, as for groups.
- Search (#98, track 3) should show a conversation's pin status in its results.
