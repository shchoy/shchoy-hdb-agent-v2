# #78 Unified card style for in-chat results

Parent: #74 · Blocked by: #75 (design tokens, font, app shell)

## What was built

All six results shown inside an answer now use one card style built from the design tokens:

- **Card**: a header (an h3 or h4 heading plus optional status badges) above a body, with a light border, a raised header strip and a small shadow. A card with a heading is a region named by that heading, so roles are unchanged. The injection alert is a `role="alert"` card in the danger tone (red frame).
- **Badge**: a status shown in words on a tinted background. Tones: neutral (grey), success (green), warning (amber, for low-confidence classifications) and danger (HDB red). Colour is never the only signal.
- **TableScroll**: wraps each table in a named region that keyboard users can focus, so the table scrolls sideways inside the card on a phone instead of widening the page.
- **Card table and fields styles**: missing and problem checklist lines and overdue tasks get a red inset accent at the start of the row, always next to words (a "Problem" or "Missing" mark, a problem badge such as "Expired", or "Overdue · N days"). Submitted lines are green; optional lines not sent are grey.

HDB red is used only for alerts, overdue markers and problems: the "Incomplete" badge, problem badges, overdue badges and the injection alert. "Complete" is green. Scan markers and other neutral states are grey.

## How it fits the project

The cards appear under answers on the Ask screen, on the Tasks and Document check screens (TaskList, DocCheckCard, DraftPreview) and in Approvals (ClassificationDetails). Results now look the same on every screen and in both themes, and they need no layout changes when the chat thread (#77) changes around them. Content, roles and every existing test are unchanged.

## Modules

| Path | New/Modified | Role |
|---|---|---|
| `web/src/app/Card.tsx` | New | Card, Badge, TableScroll, `tableClass`, `fieldsClass` |
| `web/src/app/card.module.css` | New | Card, badge, table, field and row-accent styles (tokens only) |
| `web/src/app/Card.test.tsx` | New | Card structure, alert form, focusable table region; doc check, tasks and injection alert on the card |
| `web/src/app/ClassificationCard.tsx` | Modified | Card; low confidence shown as a warning badge |
| `web/src/app/DocCheckCard.tsx` | Modified | Card with a Complete/Incomplete badge, scrolling checklist, problem and scan badges |
| `web/src/app/TaskList.tsx` | Modified | Card, scrolling ranked table, overdue danger badge |
| `web/src/app/DraftPreview.tsx` | Modified | Card |
| `web/src/app/InjectionAlert.tsx` | Modified | `role="alert"` card in the danger tone |
| `web/src/app/PolicyStanceCard.tsx` | Modified | Card at level 4 (it sits inside the Sources panel) |
| `web/src/app/ask.module.css` | Modified | Removed the per-card styles (`.checklist` kept for the Document check applications table) |
| `web/e2e/accessibility.spec.ts` | Modified | At phone width the tasks table scrolls inside its card, the page does not overflow, and axe passes in both themes |
| `CLAUDE.md` | Modified | Map entry for the result cards |

## Workflow

```
SSE event (classification | doc_check | tasks | draft | injection | policy_stance)
  → AskScreen (or TasksScreen / DocCheckScreen / ApprovalsScreen)
    → ClassificationCard / DocCheckCard / TaskList / DraftPreview / InjectionAlert / PolicyStanceCard
      → Card (header: heading + Badge, body)
          ├─ Badge(tone) → card.module.css [data-tone] → globals.css --color-* tokens (light-dark)
          └─ TableScroll → table (tableClass) → row accents via data-status / data-overdue
```

## Next steps

- The PII alert inside DraftPreview and the Document check applications table still use the older `ask.module.css` styles (`.alert`, `.checklist`). Moving them to Badge/Card and `tableClass` would leave one danger style and one table style.
- `tokens.test.ts` does not check that badge borders reach 3:1 against their tinted backgrounds. The badges' words carry their meaning, so the risk is low.
- The new phone-width e2e test covers the tasks table only. The document check checklist inside a chat answer is not covered there.
