# Issue #15: Multi-part questions (fan-out and merge)

Branch: `feat/15-multi-part`. Parent: #1. Blocked by #12 (data questions), which is merged.

## What's been built

- **Routing with confidence.** The `route` tool (Haiku) now returns a list of intents, each with a confidence between 0 and 1 (`[{intent, confidence}]`). It can also return a `clarifying_question`. The router prompt says a question can have several parts, and that when it can't tell what the officer means, it should give low confidence and write the question it would ask back.
- **Clarifying questions instead of guesses.**
  - Labels below `route_min_confidence` (default 0.6, set with `PLG_ROUTE_MIN_CONFIDENCE`) are dropped.
  - If the router named specialists but none is confident, or it named none but wrote a question, the turn becomes a clarifying question:
    - No specialist runs.
    - `merge` streams the router's question word by word, without calling Claude. If the router gave no question, a generic one is used.
    - The exchange joins the conversation, so the officer's reply is routed with that context.
  - A weak extra label (e.g. data 0.9, drafting 0.3) is simply dropped; the confident route still runs.
- **`Send()` fan-out.** `route` → one `Send(intent, state)` per confident intent, so the knowledge, data and drafting specialists run in parallel as separate tasks.
- **Sectioned merge.** When two or more findings are backed by a citation or a query that ran, `merge` is told to answer each part in its own `## ` section, in the order asked. `merge` is still the only node that streams `token` events. Unsupported findings don't count towards sections, and the existing NOT_COVERED rule is unchanged.
- **Ask screen sections.** The new `AnswerText` component splits the answer markdown at `## ` headings into labelled `<section>` regions with `<h3>` titles. Headings inside fenced code blocks are ignored. Sections are used both for the live answer and for earlier turns of a conversation. Sources and the Reasoning panel still sit under the whole answer.

## How it fits the overall product

Officers often ask compound questions, for example "How many vacant units in Bayshore Vale, and how is vacancy defined?". Before this change both specialists already ran, but `merge` wrote one undivided reply. Now each part gets its own section: the cited definition from the knowledge agent and the SQL-backed figure from the data agent. The `citation` and `sql_trace` events still arrive together for the Sources list and the Reasoning panel. The clarifying-question path backs up the "no confident wrong answer" rule: a vague follow-up gets a question, not a guess built from the wrong specialist.

## Modules

| Path | New / modified | Role |
|---|---|---|
| `src/plg/graph/build.py` | Modified | `ROUTE_SYSTEM`/`ROUTE_TOOL` with scored intents + `clarifying_question`; `ScoredIntent`, `RouteDecision.confident()` / `needs_clarification()`; `fan_out` with `Send`; `MERGE_SECTIONS`; `CLARIFY`; `_words` (fixed replies streamed word by word) |
| `src/plg/graph/state.py` | Modified | `PLGState.clarification` (route's question back, reset each turn) |
| `src/plg/config.py` | Modified | `route_min_confidence` setting |
| `tests/test_multi_part_api.py` | New | HTTP-seam tests: two-part answer with citation + sql_trace + run_id, parallel specialists, no sections for one part or one supported finding, clarifying question (router's own and generic), weak label dropped, reply routed with the clarification |
| `tests/conftest.py` | Modified | `route()` helper scripts scored intents (`confidence=` parameter) |
| `scripts/record_sse_fixtures.py` | Modified | `routed()` helper for the new tool shape; `multi_part` recording |
| `web/src/test/fixtures/multi_part.sse` | New | Recorded knowledge + data stream fused into two sections |
| `web/src/app/AnswerText.tsx` | New | Markdown answer → labelled sections at `## ` headings (outside code fences) |
| `web/src/app/AskScreen.tsx` | Modified | Uses `AnswerText` for the live answer and the history |
| `web/src/app/AskScreen.test.tsx`, `web/src/test/sse.ts` | Modified | Multi-part rendering tests (live + history); fixture name |
| `CLAUDE.md`, `START.md` | Modified | Map and usage notes, `PLG_ROUTE_MIN_CONFIDENCE` |

## Workflow

```
officer question
  → BFF /api/threads/{id}/runs → plg-api POST /threads/{id}/runs → stream_run
  → graph: [summarise_history] → load_memory → route (Haiku, scored intents + clarifying_question?)
        ├─ no confident intent, but unsure ─→ state.clarification ─→ merge streams the question (no Claude) ─┐
        ├─ no intent (greeting) ─────────────────────────────────→ merge (no sources) ─────────────────────────┤
        └─ Send(knowledge) ∥ Send(data) ∥ Send(drafting)                                                        │
              knowledge → citation / policy_stance events                                                       │
              data      → sql_trace events                                                                      │
              drafting  → draft event                                                                           │
              → findings fan in → merge (Sonnet; `## ` section per part when 2+ supported findings) ──────────┤
  → write_memory → done(run_id)  ←───────────────────────────────────────────────────────────────────────────┘
  → SSE → AskScreen: AnswerText renders the sections; Sources, ReasoningPanel and DraftPreview stay under the answer
```

## Next steps

- The confidences are used only inside `route`. They aren't kept in state or sent as an event, so the UI can't show how sure the routing was. A `route` event would make that possible.
- Sections are triggered by the number of supported specialists, not by the number of parts in the question. Two policy questions answered by the knowledge agent alone come back as one block.
- If one specialist fails, the whole run fails. Partial results (keeping the section that succeeded) are not handled.
- A clarifying question still shows `merge` in the trajectory; a separate `clarify` node would make the trajectory clearer.
- Check the router's confidence calibration with real Haiku on the eval set, and tune `route_min_confidence`.
