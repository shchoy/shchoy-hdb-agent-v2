# Issue #109: Search approvals, audit and memory

Parent: #98. Blocked by: #107.

## What's been built

The search dialog (Ctrl/⌘K, the sidebar's Search box) now has three more result groups besides Conversations, Documents and My uploads:

- **Approvals**: pending actions the officer may decide, matched on their title and on their content (the letter, ticket or glossary-change preview).
- **Decisions**: the officer's own past decisions (their audit trail), matched on the title, their reason, their edits and what the decision produced (outbox item, i-EMS ticket, glossary term ID).
- **Memories**: the officer's own memories, matched on their text.

Choosing an approval or a decision opens the Approvals screen at that item (`/approvals?item=<action ID>`), and choosing a memory opens the Memory screen at that note (`/memory?item=<memory ID>`). The item is outlined, described as "Search match", scrolled into view and focused.

## How it contributes

Until now, search covered conversations (#107) and documents (#108). Officers can now find work waiting for them, check what they decided earlier and find what the assistant remembers about them, all from the same keyboard-first dialog and without opening each screen and scanning its list. No model is called, so results come as the officer types.

Privacy is unchanged. An officer sees only what their Approvals inbox already shows them, which includes a term owner's view of changes to their terms proposed in other officers' conversations. Decisions and memories are their own.

## Module breakdown

| Path | New / modified | Role |
|---|---|---|
| `src/plg/search/items.py` | New | `approvals` / `decisions` / `memories` keyword matching in Python; `ApprovalHit`, `DecisionHit`, `MemoryHit`; title matches first, 10 per group |
| `src/plg/search/keyword.py` | Modified | `starts`, `whole`, `excerpt` made public and shared with `items.py` |
| `src/plg/api/app.py` | Modified | `SearchResults` gains `approvals`, `decisions`, `memories`; `decidable(user)` shared by `GET /approvals` and search; each group best-effort |
| `tests/test_search_items_api.py` | New | HTTP-seam tests: matching, privacy, term owner, decisions, memories, no Claude call |
| `web/src/app/shell/SearchDialog.tsx` | Modified | Approvals / Decisions / Memories groups and options; opens screens via `onOpenScreen` |
| `web/src/app/shell/AppShell.tsx` | Modified | `openScreen(href)`: closes search/drawer, navigates, or refocuses the item if already there |
| `web/src/app/foundParam.ts` | New | `FOUND_PARAM` (`item`), `foundHref`, `foundParam` (shared by server pages and client) |
| `web/src/app/found.tsx` | New | `useFound` (outline, focus once, scroll) and `FoundLabel` ("Search match") |
| `web/src/app/(shell)/approvals/page.tsx`, `(shell)/memory/page.tsx` | Modified | Read `?item=` and pass `found` to the screen |
| `web/src/app/approvals/ApprovalsScreen.tsx`, `ActionCard.tsx` | Modified | Open the found pending item or audit entry; `DECIDED_LABEL` / `ACTION_KIND` shared with search |
| `web/src/app/memory/MemoryScreen.tsx` | Modified | Mark and focus the found memory |
| `web/src/app/card.module.css` | Modified | `found` outline and `foundLabel` styles |
| `web/src/lib/events.ts`, `web/openapi.json`, `web/src/lib/api/schema.d.ts` | Modified | New hit types (generated schema) |
| `web/e2e/journeys.spec.ts`, `web/e2e/accessibility.spec.ts` | Modified | Find a waiting letter, its decision and a memory, then open each; axe on the dialog and the opened item |

## How it works

1. `GET /search?q=` runs all six searches at once (`asyncio.gather`). Each new one is best-effort, so a failure is logged and the other groups still return.
2. **Approvals:** `decidable(user)` reads the pending interrupts of every asked thread and keeps the actions `may_decide(staff_id)` allows, with the inbox's thread title ("Proposed by <ID>" for a curator). This is the same code path `GET /approvals` uses. An empty query reads no checkpoints.
3. **Decisions:** `AuditLog.decided_by(staff_id)`, newest first. **Memories:** `MemoryStore.items(staff_id)` as `MemoryView`s.
4. `items.match` checks that every query word begins a word in at least one field. The hit names the first field that holds a match and shows it as a snippet: a short field whole, a long one as the passage around the first match, with `<mark>` parts. Items whose title holds every word come first.
5. In the browser, picking a result calls `foundHref(...)` and `AppShell.openScreen`. The page reads `?item=`, the screen applies `useFound` props to the matching card, and that card gets focus once.

## Workflow map

```
SearchDialog (Ctrl/⌘K) ──GET /api/search?q=──► BFF ──X-PLG-User──► plg-api GET /search
                                                                     ├─ threads.search          (conversations, #107)
                                                                     ├─ keyword_search          (documents / uploads, #108)
                                                                     ├─ decidable(user) ─► checkpoint interrupts ─► items.approvals
                                                                     ├─ AuditLog.decided_by ─────────────────────► items.decisions
                                                                     └─ MemoryStore.items ───────────────────────► items.memories
                     ◄──────────── SearchResults {…, approvals, decisions, memories} ─┘
pick approval/decision ─► AppShell.openScreen("/approvals?item=<action ID>") ─► ApprovalsPage(found) ─► useFound → focused card
pick memory            ─► AppShell.openScreen("/memory?item=<id>")           ─► MemoryPage(found)    ─► useFound → focused card
```
