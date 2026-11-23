# Issue #79: Welcome screen with role-aware starter prompts

Parent: #74 · Blocked by: #77 (chat thread layout)

## What's been built

A new or empty conversation on the Ask screen no longer opens blank. It shows:

- a greeting naming the signed-in officer ("Good to see you, Siti Aishah Yusof");
- a `Starter prompts` list of cards (title + the exact question), curated in the web app and filtered by the persona's role;
- choosing a card (click, or Enter/Space by keyboard) asks its question at once; the answer streams as for a typed question and the welcome gives way to the conversation.

A conversation with turns (restored after a refresh, or opened from the sidebar) never shows it, and the welcome waits until any saved thread has been looked for, so it doesn't flash over a restored conversation. "New conversation" brings it back. No backend change.

| Prompt | Question | Roles |
|---|---|---|
| Ask about a policy | How far can a tenant display goods beyond the shopfront? | all |
| Query PLG Records | Which tenancies have arrears above 3 months' rent? | all |
| Draft a letter | Draft a first reminder letter for Golden Leaf Minimart Pte Ltd's overdue rent | send_letter (not analysts) |
| Classify feedback | Classify: 'Ceiling near the shop wet and lights flickering, …' | raise_ticket (not analysts or legal) |
| Check an application's documents | Is application APP-2026-0294 complete? … | send_letter (its notice) |
| Look up a definition | How is a vacant unit defined, and has the definition changed? | analysts only |
| My top tasks | What are my top 5 tasks this week and why? | all |

Officers, managers, estate managers and directors get 6 prompts, legal gets 5 and analysts get 4.

## How it contributes

Officers find out what the Super-Librarian can do without being told, and each starter runs one specialist (knowledge, data, drafting, defect, doc_check, tasks, glossary) on data the POC corpus and PLG Records can answer. The role filter uses the same approver rules plg-api applies (`APPROVER_ROLES`), so nobody is offered a letter or ticket they couldn't approve.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `web/src/app/Welcome.tsx` | New | Greeting, curated STARTERS with role lists (SEND_LETTER / RAISE_TICKET mirror APPROVER_ROLES), cards that call `onAsk` |
| `web/src/app/AskScreen.tsx` | Modified | `user` prop; `showWelcome` (no history, idle run, saved thread checked); a chosen prompt goes through `ask()` |
| `web/src/app/(shell)/page.tsx` | Modified | Passes `currentUser()` to AskScreen |
| `web/src/lib/events.ts` | Modified | Exports `ROLES` (the zod role enum's options) |
| `web/src/app/ask.module.css` | Modified | Welcome and starter card styles (tokens only) |
| `web/src/app/Welcome.test.tsx` | New | Vitest + MSW: greeting, prompts per role (officer, analyst, legal), keyboard and click ask with streamed answer, hidden with turns |
| `web/e2e/accessibility.spec.ts` | Modified | Axe runs on the welcome in light and dark themes |

## Workflow

```
(shell)/page.tsx ── currentUser() (BFF → plg-api GET /me) ──► AskScreen user={name, role}
AskScreen: on load, saved thread? ── yes → open() → history (welcome hidden)
                                  └─ no  → showWelcome → Welcome (STARTERS filtered by role)
Welcome card chosen ─► AskScreen.ask(question) ─► POST /api/threads → POST /api/threads/{id}/runs (SSE)
                     ─► stream as usual (bubble, answer, cards); welcome hidden
Sidebar "New conversation" ─► startNew() ─► welcome shown again
```

## Next steps

- "My top tasks" is offered to every role, but in the POC data the directors, analyst (S08), legal (S09) and S11 have no tasks and get "No open tasks". Leads could be offered a team-member variant instead.
- The role lists copy plg-api's `APPROVER_ROLES` by hand, and no test ties the two together. If the approver rules change, update `Welcome.tsx` as well.
