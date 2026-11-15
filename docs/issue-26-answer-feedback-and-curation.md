# Issue #26: Answer feedback and curation

## What was built

- **👍/👎 on every answer.** `POST /feedback` takes `{thread_id, run_id, score, comment, correction, team_fact}`. It records the feedback in an append-only log (`.plg/feedback.jsonl`) and sends it to LangSmith with `create_feedback(run_id, "user_score", score=1|0, comment, correction)`, with the text PII-masked. A 👎 run is added to the `PLG thumbs-down review` annotation queue, which is created on first use. Without `LANGSMITH_API_KEY` the feedback is still recorded and the receipt says `forwarded: false`.
- **Answers named by run ID.** `merge` appends an `AnsweredTurn` to the graph state for every answer: the run ID, message index, question, intents, answer, the SQL that ran, and whether the turn was flagged. `GET /threads/{id}` returns these as `turns`, so the UI can offer feedback on earlier answers too.
- **Curation with `pending_review`.** Feedback can propose three things:
  - a 👍 on an answer whose query ran proposes its **question → SQL** pair;
  - a 👎 with a correction proposes a **corrected-answer example**;
  - a team-fact text proposes a **team fact**.

  Each proposal is a `ProposedAction` (`approve_sql_example`, `approve_example`, `approve_team_fact`), stored in the team namespace of the LanceDB memory table with status `pending_review`. A flagged turn proposes nothing.
- **Curators.**
  - Team leads (director, managers, estate managers) approve all three kinds. Data analysts also approve SQL examples.
  - The officer whose feedback made the proposal can withdraw it but never approve it, even when no other curator exists.
  - `GET /curation` is the queue. `POST /curation/decide` takes the same approve / edit / reject body as resume. The decision is checked by `ApprovalDecision.refusal`; edited SQL is dry-run through the validator; every decision is written to the `AuditLog` with the answer's run ID.
- **What approval changes.**
  - An approved SQL pair becomes a few-shot example in the data agent's per-run context for similar questions (nearest 3).
  - An approved team fact (nearest 5) and the nearest approved corrected answers (2) join the memory block in merge's prompt. They are labelled as guidance, never a source.
- **Web.**
  - `AnswerFeedback.tsx` under each answer: Helpful / Not helpful, with "Correct this", "Team fact" and a comment.
  - The **Curator queue** on the Memory screen (`CuratorQueue.tsx`): approve, edit then approve, and reject or withdraw with a reason.
  - BFF routes `/api/feedback`, `/api/curation` and `/api/curation/decide`.

## How it fits the project

This covers stories 92, 105 and 106 of the tracking spec (#1).
- Officers' verdicts reach LangSmith against the exact trace, which feeds evaluation and review.
- Fixes and team knowledge reach other officers only through a curator. One person's mistake doesn't spread, and every promotion is audited.
- The data agent gets better at recurring questions from SQL that has been verified, while still checking each business term against the glossary.

## Modules

| Path | New/Modified | Role |
|---|---|---|
| `src/plg/feedback/model.py` | New | `AnsweredTurn`, `Feedback`, `FeedbackLog` (JSONL) |
| `src/plg/feedback/langsmith.py` | New | `LangSmithFeedback`: `create_feedback`, annotation queue, PII masking, best-effort |
| `src/plg/feedback/curation.py` | New | Proposals from feedback, `Curation` store (team memory), decisions, edit rules, retrieval |
| `src/plg/actions/model.py` | Modified | New action types, curator roles (`LEADS`, + analyst for SQL), curated payloads |
| `src/plg/graph/state.py` | Modified | `turns` state, `Finding.sql` |
| `src/plg/graph/build.py` | Modified | `merge` records `AnsweredTurn`; `data_node` passes verified SQL examples; `curation` parameter |
| `src/plg/agents/data.py` | Modified | `verified` examples shown in the per-run context |
| `src/plg/memory/service.py` | Modified | Team facts and corrections in the memory block |
| `src/plg/memory/store.py` | Modified | `put_curated`, `nearest` for the team namespace |
| `src/plg/api/app.py` | Modified | `POST /feedback`, `GET /curation`, `POST /curation/decide`, `ThreadView.turns`, `langsmith` parameter |
| `src/plg/config.py` | Modified | `feedback_log`, `annotation_queue` |
| `tests/test_feedback_api.py`, `tests/conftest.py` | New / Modified | 12 HTTP-seam tests; `make_api(langsmith=...)` |
| `scripts/record_sse_fixtures.py` | Modified | `feedback` scenario → `web/src/test/fixtures/feedback/*.json` |
| `web/src/app/AnswerFeedback.tsx`, `AskScreen.tsx` | New / Modified | Feedback controls on live and history answers |
| `web/src/app/memory/CuratorQueue.tsx`, `memory/page.tsx` | New / Modified | Curator queue |
| `web/src/app/api/feedback`, `api/curation`, `lib/server/plg-api.ts` | New / Modified | BFF relays |
| `web/src/lib/events.ts`, `approvals/ApprovalsScreen.tsx` | Modified | New action types in schemas and audit labels |

## Workflow

```
Ask screen ── run ──► plg-api /threads/{id}/runs ──► graph … merge ──► state.turns += AnsweredTurn(run_id, sql, …)
     │                                                                      ▲
     └─ 👍/👎 ─► BFF /api/feedback ─► POST /feedback ─► find turn by run_id ─┘
                                          ├─► FeedbackLog (.plg/feedback.jsonl)
                                          ├─► LangSmithFeedback.send ─► create_feedback(run_id)
                                          ├─► (👎) LangSmithFeedback.queue ─► annotation queue
                                          └─► curation.proposals ─► Curation (memory/team/*, pending_review)

Memory screen ─ Curator queue ─► BFF /api/curation(/decide) ─► GET /curation · POST /curation/decide
                                          └─► refusal checks ─► Curation.decide (active | retired) ─► AuditLog

Later runs:  data_node ─► Curation.sql_examples(question) ─► data agent context (few-shot)
             load_memory ─► MemoryService.context ─► team facts + corrections ─► merge system prompt
```

## Next steps

- A 👎 with no correction goes only to the LangSmith queue. Consider a local review list for when LangSmith isn't configured.
- The UI offers the team-fact field only on 👎, although the API accepts it with a 👍.
- SQL in the examples isn't PII-masked, since masking would break the queries. Curators should check literals before approving.
- Edited SQL is dry-run with `tasks_today` (2026-09-30). Switch to the semantic layer's `as_of_default` if the two ever differ.
- Smells from the review: the payload `isinstance` switches, `EDITABLE` duplicated in `CuratorQueue.tsx`, and the `thread_id`/`run_id`/`feedback_id` fields that every payload repeats.
- Two `AskScreen` reconnect tests failed once under parallel load and passed in every later run. Watch them in CI.
