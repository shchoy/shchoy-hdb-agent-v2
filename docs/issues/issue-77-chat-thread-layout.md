# Issue #77: Chat thread layout and composer

Parent: #74 · Blocked by: #75 (design tokens, font, app shell)

## What was built

The Ask screen is now a proper chat:

- **One scrolling thread.** A `Conversation` region holds the earlier turns ("Earlier in this conversation") and then the live turn. Each question is a right-aligned bubble with a teal tint (`--color-primary-tint`). Each answer sits below its question as full-width prose and keeps its `## ` sections (AnswerText). The visible "You asked:" / "Answer:" labels are now screen-reader-only text.
- **Pinned composer.** The form is `position: sticky; bottom: 0` in the window, so the shell layout is unchanged.
  - The textarea grows with its content: a layout effect sets the height from `scrollHeight`, and CSS caps it at `max-height: 12rem`, past which it scrolls.
  - Enter sends (ignored while an IME is composing) and Shift+Enter adds a new line.
  - Nothing can be sent while a run is answering: the button is disabled and `onSubmit` guards too.
- **Follow the answer.** While the officer is at the bottom (within 48px), each update scrolls an end sentinel into view.
  - Scrolling up stops following at once, before the next token can pull the view back down. That covers the mouse wheel, touch drags, and the ArrowUp, PageUp and Home keys outside the composer.
  - On a page too short to scroll, scrolling up does nothing.
  - Scrolling back to the bottom resumes following.
  - While not following, a floating "Jump to latest" button above the composer brings the view back.
  - Asking a question always jumps to the latest.
- **Status line.** One `role="status"` (`aria-live="polite"`) paragraph is always present, so its changes are announced.
  - While a run is answering, it says in plain words what the latest running node is doing: `DOING`, e.g. "Searching the library…", "Querying PLG Records…", "Drafting the letter…". It falls back to "Working…".
  - It is empty once the run is over.
  - The always-visible trajectory list is gone.
- **Show steps.** After the run, a collapsed `<details>` "Show steps" holds the Trajectory and, for data answers, the ReasoningPanel. It also appears on a failed run, so the officer can see how far the run got.
- **Unchanged:** reconnect via Last-Event-ID, refresh recovery and Retry still work.

## How it contributes

The officer's main screen now reads as a conversation, so follow-up questions are natural. The process noise is reduced to one status line, with the full trajectory and SQL reasoning one click away for anyone checking how an answer was reached. The composer is always reachable on phone and desktop. Screen-reader users hear progress through one polite status line instead of a changing list.

## Modules

| Path | New / modified | Role |
| --- | --- | --- |
| `web/src/app/AskScreen.tsx` | Modified | Chat layout (`Bubble`, `Trajectory`); status line (`DOING`, `statusLine`); follow / Jump to latest (`setFollowing`, `atBottom`, scroll/wheel/touch/key listeners); auto-growing composer; "Show steps" |
| `web/src/app/ask.module.css` | Modified | `.thread`, `.turn`, `.bubble`, `.reply`, `.status`, `.steps`, sticky `.composer` / `.composerRow`, floating `.jump`; history no longer muted; old form/label styles removed |
| `web/src/app/AskScreen.test.tsx` | Modified | Trajectory and reasoning tests open "Show steps" first. New "Chat layout" suite: bubbles then answer, Enter / Shift+Enter / growth, no send while answering, polite status line ("Querying PLG Records…" on a held-open stream), Show steps contents, following + Jump to latest (stubbed `scrollIntoView`), PageUp and short-page cases |
| `web/e2e/journeys.spec.ts` | Modified | Phone-width journey: bubbles, folded steps, Shift+Enter growth, composer in view after scrolling up, Jump to latest, axe |
| `CLAUDE.md`, `START.md` | Modified | Ask screen description |

## Workflow map

```
officer types ─▶ composer (sticky; Enter → requestSubmit) ─▶ ask() ─▶ jumpToLatest()
                                                             │
                                  POST /api/threads/{id}/runs (BFF → plg-api SSE)
                                                             │
                     follow(): parseRunEvents ─▶ acc (trajectory, tokens, citations, traces, …) ─▶ setRun
                                                             │
            ┌────────────────────────────────────────────────┼──────────────────────────────┐
   status line (role=status)             Answer region (bubble + prose,          effect on [run, history]:
   statusLine(trajectory) while           sources, cards, feedback)              following? → end.scrollIntoView
   running; empty after                                                          window scroll/wheel/touch/key
            │                                                                     → setFollowing → Jump to latest
   done/failed ─▶ <details> Show steps: Trajectory + ReasoningPanel (data)
   dropped stream ─▶ /runs/latest with Last-Event-ID (3 tries); refresh ─▶ sessionStorage thread ─▶ open()
```
