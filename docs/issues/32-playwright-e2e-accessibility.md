# Issue #32: Playwright e2e and accessibility checks

GitHub: https://github.com/shchoy/shchoy-hdb-agent-v2/issues/32 (parent #1; blocked by #7, #19, #23)

## What's been built

- **A browser end-to-end suite** (`web/e2e/journeys.spec.ts`, Playwright) that drives the real web app (BFF) and the real
  plg-api with only Claude scripted:
  1. Ask with citations: the answer streams with `[1]`, the citation chip expands to its quote, and the source viewer opens.
  2. A follow-up in the same conversation: the earlier turn is listed in the history, the thread holds both turns, and they survive a reload.
  3. Approve and reject arrears letters: two TPL-REM-01 drafts (the corpus has no Letter of Demand template; this letter
     warns of one) proposed in two conversations. In the Approvals inbox one is approved ("sent as …") and the other rejected
     with a reason. The audit trail shows an Outbox item for the approved letter and none for the rejected one.
  4. Injection email as inert text: the planted refund email raises the "Suspicious document" alert. Its hidden
     `<!-- SYSTEM NOTE ... -->` shows as literal text in the source viewer: no DOM comment, no link to the planted portal,
     and no proposed action.
  5. User A blocked from user B's thread: another officer's session gets 404 on the thread, a new run and the replay. The
     conversation isn't in their list, and pointing the screen at it shows nothing.
- **Accessibility checks** (`web/e2e/accessibility.spec.ts`, `@axe-core/playwright`, WCAG 2.1 A/AA): sign-in, Ask (a cited
  answer with its source open, history, a flagged document, a draft letter), Approvals with a pending letter, Memory, Tasks,
  Document check, Library. Any serious or critical violation fails the run. Zero remain.
- **An e2e API process** (`scripts/e2e_server.py`): `create_app` + uvicorn with a replaying `ScriptedLLMClient`, over the
  poc-data corpus synced into a temporary index. All stores are in scratch space. No API keys, no Docker.
- **Fixes found by the checks**:
  - The source viewer's scrollable document text wasn't reachable by keyboard (axe `scrollable-region-focusable`, serious).
    It is now a focusable, labelled region.
  - Long conversation titles widened the Conversations column under the question form, so the label covered the
    **New conversation** button. The columns are now `minmax(0, 1fr)` and titles ellipsize.
- **CI**: a new `e2e` job (Playwright chromium; the report is uploaded on failure).

## How it contributes

Until now the web tests replayed recorded SSE fixtures through MSW, and the API tests stopped at HTTP. Nothing exercised
browser → BFF → plg-api → graph → SSE → rendered UI together. This suite covers that path for the POC's critical paths:
cited answers, conversation continuity, human approval of side effects, the prompt-injection guardrail and thread
ownership. The axe checks give the app a WCAG 2.1 AA baseline that CI keeps.

## Module breakdown

| Path | New / modified | Role |
|---|---|---|
| `scripts/e2e_server.py` | New | plg-api for e2e: `ReplayingLLMClient` (a node's scripted turns restart with each run), the scripted questions, corpus synced into a temp index, scratch stores, uvicorn on :8100 |
| `web/playwright.config.ts` | New | Starts the e2e API and `next dev` on :3100 (`PLG_NEXT_DIST_DIR=.next-e2e`), baseURL `localhost`, one worker, reuses running servers locally |
| `web/e2e/helpers.ts` | New | Personas, scripted question texts (mirror the server), `signIn`, `visit`, `ask`, `threadId`, `seriousViolations` (axe) |
| `web/e2e/journeys.spec.ts` | New | The five acceptance journeys |
| `web/e2e/accessibility.spec.ts` | New | axe on every screen in the states officers see |
| `web/next.config.ts` | Modified | Optional `distDir` from `PLG_NEXT_DIST_DIR` (e2e dev server beside a developer's) |
| `web/src/app/SourceViewer.tsx` | Modified | Document text is a focusable `region` ("Document text") so keyboard users can scroll it |
| `web/src/app/ask.module.css` | Modified | Conversations column can't overflow under the question form |
| `web/package.json`, `package-lock.json` | Modified | `@playwright/test`, `@axe-core/playwright`; `npm run e2e` |
| `web/eslint.config.mjs`, `web/.gitignore`, `web/tsconfig.json` | Modified | Ignore `.next-e2e/`, `test-results/`, `playwright-report/`; Next's own `.next-e2e` type includes |
| `.github/workflows/ci.yml` | Modified | `e2e` job |
| `CLAUDE.md`, `START.md` | Modified | Map, commands, conventions, how to run |

## Workflow map

```
npm run e2e (web/)
  └─ playwright.config.ts
       ├─ webServer 1: uv run python scripts/e2e_server.py --port 8100
       │     searcher(): sync poc-data → temp LanceDB (HashingEmbedder) + CrossEncoderReranker
       │     create_app(scratch_settings, llm=ReplayingLLMClient, searcher, store, scratch memory, RecordingLangSmith)
       │     uvicorn → plg-api (real routes, graph, guardrails, approvals, outbox/audit in scratch)
       └─ webServer 2: next dev --port 3100  (PLG_API_URL=http://127.0.0.1:8100, distDir .next-e2e)

Chromium (Playwright) ──► Next.js pages + BFF /api/* (session cookie → X-PLG-User)
                                   │
                                   ▼
                     plg-api :8100 ──► stream_run → graph: screen_input → route → knowledge / drafting → merge
                                   │        (Claude = ReplayingLLMClient, keyed by node + question)
                                   │        approval interrupt ◄── POST /threads/{id}/resume (Approvals inbox)
                                   ▼
                     SSE events ──► AskScreen / ApprovalsScreen / SourceViewer / InjectionAlert
                                   │
                     assertions: rendered UI + BFF responses (/api/threads, /api/approvals, /api/audit)
                     axe-core (WCAG 2.1 A/AA) on each screen → zero serious/critical
```

## Next steps

- The scripted question texts live in both `scripts/e2e_server.py` and `web/e2e/helpers.ts`. A mismatch fails loudly (no
  scripted turn), but a shared JSON file would remove the duplication.
- axe doesn't look inside the sandboxed letter preview iframe (no scripts can run there). Its contents are escaped
  paragraphs. A static check of the preview HTML (e.g. axe on `preview` rendered in a plain page) would close the gap.
- More states could be scanned: decided/editing approval cards, ticket and glossary cards, doc-check and task results in a
  conversation.
- The suite shares one server and runs on a single worker. Per-test personas or threads would allow parallel runs.
