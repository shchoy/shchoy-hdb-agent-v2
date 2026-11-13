# Issue #22: Top tasks and task digest

GitHub: https://github.com/shchoy/shchoy-hdb-agent-v2/issues/22 (parent #1, user stories 71-75; ground truth Q23/Q24 of `poc-data/_report.md`).

## What was built

- **The rules matrix** (`src/plg/tasks/rules.py`): an officer's open tasks from PLG Records `tasks` (anything not Done)
  are ranked by urgency × impact. It is deterministic and calls no Claude.

  | Urgency | Score | Impact | Score |
  |---|---|---|---|
  | overdue (due date passed or status Overdue) | 4 | high: safety-related, S$50,000+ rent at risk, or 5+ tenants affected | 3 |
  | due this week (within 7 days) | 3 | medium: S$10,000+ at risk, or 2+ tenants | 2 |
  | due within 30 days | 2 | low | 1 |
  | later | 1 | | |

  Score = urgency × impact (1-12). Ties go to the earlier due date, then the larger rent at risk, then the task ID.
  Each task carries its reasons, e.g. "Overdue by 283 days (due 21 Dec 2025)", "Safety-related",
  "S$53,520 rent at risk", "11 tenants affected". Overdue tasks are marked with `overdue` and `days_overdue`.
- **"Today"** is the `tasks_today` setting (`PLG_TASKS_TODAY`, default 2026-09-30), the date of the PLG Records
  snapshot. Ranked against the real date, nearly every task would be overdue.
- **Role check** (`can_view`, `team`):
  - everyone sees their own tasks;
  - directors (Director, Deputy Director) see everyone's;
  - managers and estate managers see their own department's staff who are not leads themselves.
  - The `staff` table has no region, so Estate Manager East and West both see S06 and S10.
- **Conversation:** a new `tasks` intent and `tasks` node.
  - It works out whose tasks are meant: a full name, a staff ID, or a first name only one colleague has, used
    possessively ("Daniel's"). Otherwise it is the asker.
  - It reads how many from "top N" (default 5, at most 50).
  - It role-checks, then streams the ranking as a `tasks` SSE event. Its finding asks merge (Claude) for one short
    sentence per task, which is the LLM-written rationale.
  - A refusal is a finding stating the officer isn't allowed, and no tasks are read.
- **API:**
  - `GET /tasks/digest?staff_id&limit` returns a `TaskDigest`. Errors: 401 no user, 404 unknown staff, 403 not allowed.
  - `GET /tasks/team` lists the staff the caller may view.
- **CLI:** `plg digest [--user] [--limit] [--out]` writes the digest to the console or a file, so it can be scheduled.
  Without `--user` it covers every officer with open tasks. It is an admin job, so there is no role check.
- **Web:**
  - Tasks screen (`/tasks`): own top tasks, an Officer picker for team leads, a Show 5/10/20/50 control, and a message
    for 403.
  - BFF routes `/api/tasks/digest` and `/api/tasks/team`.
  - A shared `TaskList` table, also shown under the answer on the Ask screen.
  - A Tasks link in the top bar.
- **Tests:**
  - `tests/test_tasks_api.py` (14) checks the ranking, overdue marking, role checks, chat, name matching and the CLI.
    No ranking test needs Claude.
  - Web: Tasks screen, BFF routes, and the Ask screen replaying `tasks.sse`.
  - The recorded fixtures are `tasks.sse` and `tasks/*.json`.

## How it fits the whole

It answers AC2 ("which tasks matter most this week"), the last specialist of Week 3 in the plan. The front door now
routes to six specialists. Like data and doc-check, the tasks specialist grounds merge in a deterministic result rather
than citations, so its findings are `traced`. The digest is the scheduled job of user story 74/85, next to `plg sync`.

Q23 (Benjamin Ho's top 5): three overdue fire-safety follow-ups (score 12), then the oldest overdue follow-ups.
Q24 (Lucky Star): TSK-2026-0452 is marked overdue by 92 days. It is Daniel Ong's 43rd task, so it shows in his full
list, not in a top 5. The yes/no question itself is still answered by the knowledge/data specialists.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/tasks/rules.py` | new | Matrix, reasons, ranking, `digest`, `render`, `can_view` / `team` |
| `src/plg/tasks/ask.py` | new | Whose tasks and how many, from the question; refusal and rationale texts |
| `src/plg/config.py` | modified | `tasks_today` |
| `src/plg/graph/state.py` | modified | `tasks` intent |
| `src/plg/graph/build.py` | modified | Route prompt and enum, `tasks_node`, edges |
| `src/plg/events.py`, `src/plg/runs.py` | modified | `TasksEvent` and its mapping from the graph stream |
| `src/plg/api/app.py` | modified | `GET /tasks/digest`, `GET /tasks/team` |
| `src/plg/cli.py` | modified | `plg digest` |
| `scripts/record_sse_fixtures.py` | modified | `tasks` stream, `tasks_api` JSON fixtures |
| `tests/test_tasks_api.py` | new | HTTP-seam and CLI tests |
| `web/src/app/tasks/` | new | Tasks screen and its test |
| `web/src/app/TaskList.tsx` | new | Shared ranked-task table |
| `web/src/app/api/tasks/{digest,team}/route.ts` | new | BFF relays (+ `routes.test.ts`) |
| `web/src/lib/server/plg-api.ts`, `web/src/lib/events.ts` | modified | plg-api helpers; zod `tasks` event |
| `web/src/app/AskScreen.tsx` (+ test), nav in `page.tsx`, `approvals/`, `memory/`, `doc-check/` | modified | Task list under the answer; Tasks link |
| `web/openapi.json`, `web/src/lib/api/schema.d.ts` | regenerated | API types |

## Workflow

```
Conversation
  browser ─► BFF /api/threads/{id}/runs ─► POST /threads/{id}/runs ─► stream_run ─► graph
     route (Haiku: intent "tasks")
       └─► tasks_node ── ask.whose / how_many ── rules.can_view ──(refused)──► finding "not allowed"
                     └── rules.digest(records_db, officer, tasks_today, N) ─► `tasks` event (TaskList under the answer)
                                                                         └─► finding = render() + RATIONALE
     merge (Sonnet) ─► tokens: one-line rationale per task

Tasks screen
  /tasks ─► BFF /api/tasks/team ─► GET /tasks/team ─► rules.team
        └► BFF /api/tasks/digest?staff_id&limit ─► GET /tasks/digest ─► can_view (403) ─► rules.digest ─► TaskList

Scheduled digest
  plg digest [--user] [--out] ─► load_personas ─► rules.digest per officer ─► render ─► console | file
```

## Next steps

- The Tasks screen and `plg digest` show the rule-based reasons only. If a Claude-written rationale is wanted there too,
  it would cost a Haiku call per request.
- Thresholds (S$50k/10k, 5/2 tenants, 7/30 days) are POC choices, not checked against `exports/plg_tasks_open.csv`.
  Tune them with the business.
- The role check is department-based, because staff have no region or reporting line. Use the real org chart when OIDC
  arrives.
- There is no LangSmith evaluation of the merge rationale yet.
