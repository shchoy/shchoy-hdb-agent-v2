# Issue #75: HDB design tokens, font and left-sidebar app shell

Parent: #74

## What's been built

- **One shared app shell.** Every signed-in screen (Ask, Approvals, Tasks, Document check, Library, Memory) now sits in a
  Next.js `(shell)` route group. Its layout checks the session (redirecting to `/sign-in` when signed out) and wraps
  the screen in `AppShell`, a persistent left sidebar with:
  - the product name and **New conversation**;
  - the sections with inline SVG icons, the current one marked with `aria-current="page"`;
  - a red count of the approvals pending for the signed-in officer (the same `/api/approvals` list the Approvals
    inbox shows), hidden at zero;
  - recent conversations (picking one opens it on the Ask screen, from any screen);
  - the signed-in persona with **Sign out**.
- **Drawer on narrow screens.** Below 48rem the sidebar collapses behind a labelled **Menu** button and opens as a
  modal drawer (`role="dialog"`). Focus moves into the drawer and stays there on Tab, the top bar and screen are
  `inert` while it is open, and Escape or the backdrop closes it with focus back on Menu. It also closes once a
  section is picked or the window widens.
- **Design tokens.** `globals.css` defines an HDB-inspired palette: teal primary, HDB red only for badges and danger,
  and Bootstrap-style greys. These are exposed as semantic `--color-*` roles alongside type, weight, spacing, radius
  and shadow scales. All screen stylesheets (ask, approvals, library, sign-in, shell) use only these tokens. Text and
  focus colours meet WCAG 2.1 AA.
- **Self-hosted font.** Hanken Grotesk (variable woff2 + OFL licence) lives in `web/src/app/fonts/` and is loaded with
  `next/font/local`, so the build and e2e need no network.
- **Prefactor.** Screens no longer render their own banner, nav links or conversation list. Later UI tickets change
  only the screens' own content.

## How it contributes

The web app's sections were separate pages, each with its own copy of the header and nav. The shell turns them into a
single app: officers can move between sections, see at a glance what is waiting for their approval, and return to
any recent conversation from anywhere. The token set gives every screen one consistent, accessible visual language.
The drawer makes the app usable on tablets and phones. Accessibility is enforced by the axe checks in the Playwright
suite, now including the phone drawer.

## Module breakdown

| Path | New / modified | Role |
| --- | --- | --- |
| `web/src/app/(shell)/layout.tsx` | New | Route-group layout: session check, wraps every signed-in page in `AppShell` |
| `web/src/app/(shell)/{page,approvals,tasks,doc-check,library,memory}/page.tsx` | Moved + modified | Page entries, now only the screen (no banner or nav) |
| `web/src/app/shell/AppShell.tsx` | New | Sidebar: sections, pending count, recent conversations, persona, drawer with focus management |
| `web/src/app/shell/ShellContext.tsx` | New | `useShell().refresh()` for screens; `useConversationControl` links the Ask screen and sidebar |
| `web/src/app/shell/icons.tsx` | New | Inline SVG section icons |
| `web/src/app/shell/shell.module.css` | New | Sidebar, badge and drawer styles (tokens only) |
| `web/src/app/shell/AppShell.test.tsx` | New | Vitest: current section, count, conversations, new conversation, drawer focus/Escape/Tab |
| `web/src/test/shell.tsx` | New | `inShell()` test helper: renders a screen inside the shell |
| `web/src/app/fonts/HankenGrotesk-Variable.woff2`, `HankenGrotesk-OFL.txt` | New | Self-hosted font and licence |
| `web/src/app/layout.tsx` | Modified | Loads the local font (`--font-hanken`) |
| `web/src/app/globals.css` | Modified | Design tokens and base styles |
| `web/src/app/AskScreen.tsx` (+ test) | Modified | Conversation list moved to the sidebar; refreshes the shell after a run |
| `web/src/app/approvals/ApprovalsScreen.tsx`, `doc-check/DocCheckScreen.tsx` | Modified | Refresh the shell after a decision or run (pending count) |
| `web/src/app/{ask,approvals/approvals,library/library,sign-in/sign-in}.module.css` | Modified | Hard-coded colours replaced by tokens |
| `web/e2e/accessibility.spec.ts` | Modified | Phone drawer journey with axe checks |
| `web/next.config.ts` | Modified | `allowedDevOrigins` for 127.0.0.1 / Codespaces forwarded ports (dev only) |

## Workflow map

```
browser ──► (shell)/layout.tsx ── currentUser() ──► no session → redirect /sign-in
                    │
                    ▼
              AppShell (client) ─────────────── on mount and every route change ──► BFF GET /api/threads    ─► plg-api GET /threads
               │  sidebar / drawer                                           └────► BFF GET /api/approvals  ─► plg-api GET /approvals?status=pending
               │      │                                                                     (count = inbox length, hidden at 0)
               │      ├─ section links (aria-current) ──► Next router
               │      ├─ New conversation / recent conversation
               │      │      ├─ on "/": ShellContext control.open(id) / startNew() ──► AskScreen
               │      │      └─ elsewhere: sessionStorage plg_active_thread + router.push("/") ──► AskScreen reopens it
               │      └─ Sign out ──► BFF /api/session
               │
               └─ ShellProvider ──► screen (AskScreen, ApprovalsScreen, DocCheckScreen, ...)
                                       └─ after a run / decision: useShell().refresh() ──► sidebar reloads list + count
                                       └─ AskScreen: useConversationControl(open, startNew, active, busy)
                                             (sidebar marks the open conversation, won't switch while answering)

globals.css tokens ──► every *.module.css        layout.tsx next/font/local ──► fonts/HankenGrotesk-Variable.woff2
```
