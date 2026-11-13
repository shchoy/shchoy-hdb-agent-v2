# Issue #23: Prompt-injection guardrail

Parent: #1 (user stories 98 and 99, SYS). Blocked by #18 (approvals), which is done.
Branch: `feat/23-injection-guardrail`.

## What's been built

Instructions planted for the assistant are found, ignored and reported, both in an officer's own message and in
ingested emails. The planted `suspicious_refund_request` email never leads to an action.

- **`screen_input`**, a new first node in every turn, screens the officer's message with deterministic rules. The user
  chose rules over a Haiku classifier: they flag the same text the same way every time, cost nothing, and run before
  any model reads the text. A flagged message reaches no specialist and no Claude call. The officer gets a fixed
  warning and an `injection` event with the flagged excerpt. The history keeps the message with the planted part
  replaced by `[Removed: suspected prompt injection (...)]`.
- **Email screening at ingestion** (`plg sync`): the planted span of an email is replaced by
  `[Removed at ingestion: suspected prompt injection (rules)]` before chunking. The span is its sentence, or the whole
  hidden `<!-- -->` comment it sits in. So the instruction is never indexed, embedded or shown to Claude. The sync
  prints `Flagged: <path> ...`.
- **At retrieval**, `run_agent._guarded` checks every retrieved passage:
  - A passage carrying the ingestion marker is reported (`injection` event, source `document`), and Claude gets a
    warning note with it.
  - An email indexed before #23 that still holds a planted instruction is withheld from Claude entirely.
- **No action on a flagged turn:** specialists now stage their actions in a per-turn `proposals` field, and `merge`
  copies them into `proposed_actions` only if the turn met no injection. When proposals are held back, the answer
  opens with a warning naming the document and says nothing was proposed. Memory learns nothing from a flagged turn.
- **Web:** `InjectionAlert` (a `role="alert"` box above the answer on the Ask screen) lists each flag with a
  plain-language label per rule. The excerpt shows as plain text, never HTML.
- **Guardrail cases:**
  - 7 attack phrasings are flagged at 100%.
  - 10 benign questions using the same words are not flagged, including the false positives found in code review.
  - Across the whole corpus and about 165k text values in PLG Records, only the planted email is flagged.

## How it fits the overall product

#18 already made sure nothing acts without approval, and no model holds a tool that acts. #23 adds a layer in front of
that:

- Planted instructions are cut out before a model reads them.
- A turn that met one can't even put an action up for approval.
- The officer is told, so the suspicious email can be escalated (story 99).

Together these meet the security officer's story 98 ("never follows instructions planted in a tenant email") and the
seam-1 case "`suspicious_refund_request` → flagged, no proposed actions, no executed actions".

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/guardrails/injection.py` | New | The rules, `screen` (hits + redacted text), the two markers, `flags_in`, `excerpt`, `InjectionFlag`, `SCREENED_DOC_TYPE` |
| `src/plg/graph/build.py` | Modified | `screen_input` node and its routing; merge's flagged paths (`MESSAGE_FLAGGED`, `DOCUMENT_FLAGGED` + `WITHHELD`, `MERGE_INJECTION`); proposal gating; knowledge node reports flags; `write_memory` skips flagged turns |
| `src/plg/graph/state.py` | Modified | `per_turn` reducer; `screened`, `injections`, `proposals` fields |
| `src/plg/agents/runtime.py` | Modified | `_guarded`: screens every retrieved Source, adds the warning note, withholds unscreened planted emails, calls `on_injection` |
| `src/plg/agents/knowledge.py` | Modified | Passes `on_injection` to `run_agent` |
| `src/plg/ingest/sync.py`, `src/plg/cli.py` | Modified | Screens emails before chunking; `SyncReport.flagged`; `Flagged:` output |
| `src/plg/events.py`, `src/plg/runs.py` | Modified | `InjectionEvent` (`type: "injection"`) in the RunEvent union and the stream |
| `tests/test_guardrail_api.py` | New | HTTP-seam tests: attacks, benign controls, redacted history, ingestion, planted email (knowledge + defect), pre-#23 index |
| `tests/test_{runs,data,drafting,knowledge,multi_part}_api.py` | Modified | Node trajectories now start with `screen_input` |
| `scripts/record_sse_fixtures.py` | Modified | `injection` and `injection_email` scenarios; `cite()` reads only `search_result` blocks |
| `web/src/app/InjectionAlert.tsx` (+ test) | New | The alert; inert excerpt rendering |
| `web/src/app/AskScreen.tsx`, `ask.module.css`, `AskScreen.test.tsx` | Modified | Collects `injection` events and renders the alert; tests replay the new fixtures |
| `web/src/lib/events.ts`, `web/openapi.json`, `web/src/lib/api/schema.d.ts`, `web/src/test/sse.ts` | Modified | zod schema and regenerated OpenAPI types; fixture names |
| `web/src/test/fixtures/injection.sse`, `injection_email.sse` | New | Recorded streams |

## Workflow map

```
plg sync ── extract(.eml) ── injection.screen ──► planted span → "[Removed at ingestion …]" ──► chunks → LanceDB
                                                      └── SyncReport.flagged → "Flagged: …"

POST /threads/{id}/runs ─► stream_run ─► graph
  START ─► screen_input ─┬─ flagged ─► merge (MESSAGE_FLAGGED, no Claude) ─► END      [event: injection(source=message)]
                         └─ clean ──► (summarise) ─► load_memory ─► route ─► specialists (parallel)
                                                                              │
         knowledge ─► run_agent ─► search_corpus / find_precedents ─► _guarded ─┤ marker → note + on_injection
                                                                              │ raw planted email → withheld + on_injection
                                                     [event: injection(source=document)] ◄┘
         drafting / defect / doc_check ─► proposals (per turn)
                                                                              ▼
  merge: injections? ─ yes ─► "Warning: … (+ nothing was proposed)" + fused answer; proposals dropped
                     └ no ──► fused answer; proposals → proposed_actions ─► write_memory ─► approval (interrupt) …

Web: BFF relays SSE ─► events.ts (zod: injection) ─► AskScreen ─► InjectionAlert (role=alert, plain-text excerpt)
```

## Next steps

- Run `uv run plg sync --full` once on any existing local index. Unchanged emails aren't re-read, so their stored text
  predates screening. Until then the retrieval check withholds them.
- Every flagged turn also needs a LangSmith eval of golden question 28, run against the real router. In the tests the
  router is scripted, so whether a real router sends "Process the latest email…" to knowledge or to defect is untested.
  The proposal gate covers either route.
- The rules catch common phrasings only. Add a rule when a new pattern shows up, then re-check the corpus and PLG
  Records for false positives.
- Pending actions from earlier turns still re-interrupt after a flagged turn, as they do after any turn. They were
  proposed before the injection, so they stay.
- The source viewer shows the original `.eml`, including the hidden comment, as text blocks. No web test covers that
  yet; it's seam 2's "injection email rendered as inert text" case, best done with the planned Playwright e2e.
- Sentence splitting for the cut span is simple: "Mr." or "S$1.50" can cut a little too much or too little. Flagging is
  unaffected.
- The full web suite timed out once in each of two unrelated tests under load on this machine. With
  `--maxWorkers=2` all 129 tests pass. Watch CI.
