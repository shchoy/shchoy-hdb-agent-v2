# Issue #85: Redesign Library, Tasks and Document check screens

Parent: #74 · Blocked by: #75 (tokens, shell), #78 (card style)

## What was built

The last three screens still in the pre-#75 style now use the shared Card/Badge/TableScroll components and the design tokens, the same way #84 did for Approvals and Memory.

- **Library: categories.** Each category is a Card article. Its h2 is the disclosure button plus the document count, and the description sits in the body. Expanding it shows the summary and the documents. Each document line shows a type badge, an amber **Superseded** badge where it applies, and the DocumentViewer.
- **Library: audit findings.** Each section (Conflicts, Near-duplicates, Stale documents, Reports using superseded definitions, Data rule violations, Gaps) has an h2 with its count and holds a list of Card articles:
  - Conflicts carry a red **Conflict** badge. They show sides A and B side by side, both quoted. The prevailing side has a green frame and a **Prevails** badge in words. A PLG Records side gets a badge and has no viewer.
  - Near-duplicates show the kind and a "% similar" badge, and both documents can be opened.
  - Stale documents and superseded definitions get warning badges.
  - Gap reasons are shown as badges.
  - The tabs now style cleanly over the global button rules.
- **Tasks.** The Officer and Show pickers form a wrapping filter bar, with the labels wrapping the selects. A refusal (403/404/401) is a red alert Card. When a colleague was picked, it offers **Show my tasks** to go back to your own list. The ranked table with the urgency × impact score and the "Overdue · N days" marker comes unchanged from TaskList (#78).
- **Document check.**
  1. The applications table is framed and scrolls sideways on a phone. Each status is a badge, and the picked row is highlighted with `aria-current`. Its label reads "Checking…", "Checked" or "Check failed".
  2. The result section holds the answer, the DocCheckCard and the notice preview. A failure is a red alert Card with Retry.
  3. Next steps are links styled as buttons. **Review the notice in Approvals** is the primary one, followed by **Open the conversation**.
- **Shared changes.**
  - `Card` accepts `level={2}` (a heading lookup, no cast).
  - `TableScroll` is `position: relative`. Before this, a visually hidden header cell, which is absolutely positioned, escaped the scroll box and widened the page on a phone. The new phone e2e test caught this.

## How it fits

These screens are where officers browse the corpus (Library, #29/#30), plan their work (Tasks, #22) and check application bundles (Document check, #21). They now look like the rest of the shell, work in both themes and fit a phone. No API, event or behaviour contract changed, and every existing test passes unchanged.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `web/src/app/Card.tsx` | modified | `level` 2 \| 3 \| 4 through a `HEADINGS` lookup |
| `web/src/app/card.module.css` | modified | `.tableScroll` positioned, so hidden cell text stays inside |
| `web/src/app/library/LibraryScreen.tsx` | modified | Category Card articles (h2 disclosure + count), document lines through `Doc` |
| `web/src/app/library/AuditFindings.tsx` | modified | Findings as Card articles; Side A/B with the Prevails badge and frame; exported `Doc` document line |
| `web/src/app/library/library.module.css` | modified | Disclosure toggle, section headings, `docLine`, prevailing-side frame, tab styles; dead classes removed |
| `web/src/app/tasks/TasksScreen.tsx` | modified | Filter bar, alert Card refusal with "Show my tasks" |
| `web/src/app/tasks/tasks.module.css` | new | Filter bar and field styles |
| `web/src/app/doc-check/DocCheckScreen.tsx` | modified | Framed picker table, picked-row marker (`CHECK_STATUS_LABEL`), alert Cards, next-step links |
| `web/src/app/doc-check/doc-check.module.css` | new | Frame, picked row, result and next-step link styles |
| `web/src/app/{library,tasks,doc-check}/*.test.tsx` | modified | Added assertions: category and finding cards named by heading, Show my tasks, picked row |
| `web/e2e/accessibility.spec.ts` | modified | Library (category opened, audit tab), Tasks and Document check fit a phone; axe in both themes |
| `CLAUDE.md` | modified | Map updated |

## Workflow

```
/library ── LibraryScreen ── GET /api/categories ──▶ Card article per category ──▶ Doc ──▶ DocumentViewer (/api/documents/…)
        └── tab Audit findings ── AuditFindings ── GET /api/audit/reports/latest ──▶ Section ▸ Card articles
                                                                                     ├─ Side A/B ──▶ QuoteViewer (highlighted quote)
                                                                                     └─ Doc ──▶ DocumentViewer
/tasks ── TasksScreen ── GET /api/tasks/team (Officer picker) ── GET /api/tasks/digest?staff_id&limit
                     ├─ ok  ──▶ TaskList (Card: ranked table, urgency × impact, Overdue badge)
                     └─ 4xx ──▶ alert Card (+ Show my tasks → own digest)
/doc-check ── DocCheckScreen ── GET /api/submissions ──▶ picker table (TableScroll)
                            └─ Check ▶ POST /api/threads + /runs (SSE) ──▶ DocCheckCard + DraftPreview
                                                                       └─ links: /approvals, / (ACTIVE_THREAD)
```

## Verification

- `npm run typecheck` and `npm run lint` are clean.
- `vitest`: 255/255 pass.
- `e2e/accessibility.spec.ts` passes in light and dark, including the new phone test.
- The full `npm run e2e` run had 36 passed and 1 failed: the Ask screen's copy-by-keyboard journey. That screen is untouched by this change, and the journey passed twice when rerun on its own.

## Next steps

- Possible follow-ups from the review:
  - The `.toggle` disclosure-heading CSS is duplicated between approvals and library.
  - `.visuallyHidden` is copied in four CSS modules.
  - Both could become shared utilities in `card.module.css` or `globals.css`.
