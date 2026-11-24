# Issue #82: Answer action bar (copy, feedback, trace)

Parent: #74 · Blocked by: #77 (chat thread layout and composer)

## What was built

Every finished answer with a run ID now ends with one action bar, named **Answer actions** (`role="toolbar"`). It looks the same on the live answer and on earlier answers in the conversation:

- **Copy** puts the answer on the clipboard as plain text. Markdown headings, emphasis, inline code, links and code fences are removed (code stays as written). The `[n]` markers stay, and a `Sources` list follows them: `[n] title (vX), location`, one line per number, in number order. The version is added only when the title doesn't already include it. A visible `role="status"` beside the bar says **Copied**. It is cleared before each copy, so a second copy is announced again. When the clipboard is unavailable (e.g. plain HTTP), it says to select the answer and copy it by hand. The button keeps its name, "Copy", so screen readers don't hear "Copied" twice.
- **👍 Helpful / 👎 Not helpful** work as before (issue #26). A 👎 opens the Correct this / Team fact / comment form below the bar, so arrow keys in its text boxes don't move along the toolbar. The receipt is shown as before ("Thanks — sent for review. N proposals waiting for a curator."). Once feedback is sent, the two buttons leave the bar and focus moves to Copy instead of dropping to the page.
- **View trace** shows only for developer personas, as before (#27), and now sits inside the bar.

Keyboard: the bar follows the ARIA toolbar pattern. It is one Tab stop (the item last focused, else Copy), and Arrow Left/Right (wrapping), Home and End move along it. Visible focus comes from the global `:focus-visible` outline. axe passes on the Ask screen in both themes.

## How it fits the product

The bar collects everything an officer can do with an answer in one place. Copy lets an officer paste an answer, with what it relied on, into an email or minute without losing the citations. Feedback still sends answers to LangSmith and the curator queue. Developers keep their trace link. The bar only appears when a run ID exists, because feedback and traces are keyed by run.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `web/src/app/AnswerActions.tsx` | New (replaces `AnswerFeedback.tsx`) | The bar: Copy + status, 👍/👎 with the feedback form and receipt, View trace; roving-tabindex toolbar keys |
| `web/src/app/copyText.ts` | New | `answerAsText(markdown, citations)`: plain text for the clipboard, plus the Sources list |
| `web/src/app/copyText.test.ts` | New | Unit tests: markers kept, sources deduped and ordered, version only when missing, markdown → text |
| `web/src/app/AnswerFeedback.tsx` | Deleted | Folded into `AnswerActions.tsx` |
| `web/src/app/AskScreen.tsx` | Modified | Renders `AnswerActions` for history turns (`answeredBy[i]`) and the live run (`done` + `runId`), passing the answer's markdown and citations |
| `web/src/app/TraceLink.tsx` | Modified | Unstyled link; the bar lays it out |
| `web/src/app/ask.module.css` | Modified | `.actions`, `.actionRow`, `.actionBar`, `.feedbackSent` (tokens only); `.feedback` / `.traceLink` removed |
| `web/src/app/AskScreen.test.tsx` | Modified | "Answer action bar" tests: order, copy text + status, failure, arrow/Home/End keys, earlier answer copy, focus after feedback, no bar without a run; trace link inside the bar |
| `web/e2e/journeys.spec.ts` | Modified | Copy by keyboard in a real browser: clipboard text, "Copied", no trace link for an officer |

## Workflow map

```
SSE run (plg-api → BFF /api/threads/{id}/runs)
  ├─ token events ─────────► run.answer (markdown)
  ├─ citation events ──────► run.citations (NumberedCitation[])
  └─ done {run_id} ────────► run.runId
                                   │
ThreadView (GET /api/threads/{id}) │  history: messages + turns[{message_index, run_id, citations}]
                                   ▼
AskScreen ── per answer with a run_id ──► AnswerActions(threadId, runId, markdown, citations, developer)
                                            ├─ Copy ──► copyText.answerAsText ──► navigator.clipboard ──► status "Copied"
                                            ├─ 👍/👎 ──► POST /api/feedback (BFF) ──► plg-api POST /feedback
                                            │             └─ FeedbackReceipt ──► "Thanks — sent for review…" (focus → Copy)
                                            └─ View trace (developer) ──► /api/threads/{id}/runs/{run_id}/trace ──► 307 LangSmith
```

## Verification

- `npm run typecheck` and `npm run lint` are clean.
- `npm test` after the review fixes: 241 of 243 passed. The 2 failures were timeouts in screens this change doesn't touch (Library tabs, Document check). Both files pass when re-run on their own (20 tests). Before the fixes, the full run passed 242 of 242.
- `npm run e2e`: 32 passed, including the new copy journey and axe on the Ask screen in light and dark. One earlier run had a one-off 502 from the BFF in the cross-user test; it passed on both re-runs.

## Next steps

- The copy and clipboard-fallback logic is the same as `ReasoningPanel`'s Copy SQL. A shared `useCopy` hook could serve both.
- `answerAsText` leaves `_x_` emphasis and markdown tables as written. Add those if officers paste tables often.
- The version shown in the copied Sources list follows a different rule from the one in the Sources panel ("Version X" always). Consider one shared source label.
