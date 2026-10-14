# Issue #6: Policy Q&A with citations

Parent: #1 · Blocked by: #3 (Ask screen), #5 (corpus ingestion and hybrid search) · Branch: `feat/6-policy-qa-citations`

## What was built

A PLG officer asks a policy or records question and gets PLG's current stance. Every claim is cited to an exact sentence span of an indexed chunk, and the citations are shown as chips in the Ask screen and listed under the answer by `plg ask`. When the sources don't cover the question, the assistant says so instead of inventing an answer.

```
question ─▶ route (Haiku, forced `route` tool) ──intents──▶ knowledge (Sonnet agent) ──findings──▶ merge (Sonnet, streams) ─▶ answer
                    └── no specialist ─────────────────────────────────────────────────────────▶ merge
```

| Acceptance criterion | How |
|---|---|
| Shared `run_agent` helper | `plg/agents/runtime.py`. Tool-use loop while `stop_reason == "tool_use"` (at most 8 rounds). Each round's tool calls run in parallel (`asyncio.gather`). System prompt and tool definitions carry `cache_control`. Returns `AgentResult(text, citations)`; the scratchpad is discarded. |
| `route` → `knowledge`, read-only tools only | `plg/graph/build.py`. `route` returns intents (`knowledge`, or none). The knowledge agent's only tool is `search_corpus` (read-only hybrid search + rerank). |
| `citation` events with document ID, chunk ID, span and location | `CitationEvent` (`plg/events.py`): `doc_id`, `chunk_id`, `title`, `version`, `location`, `quote`, `span {start, end}` (offsets into the chunk text), and `index` (the `[n]` marker). Emitted by the knowledge node before merge streams. |
| LOD → 60 days, cites POL-003 v2.0, not v1.0 | Searches default to `status = current`, so v1.0 is never shown unless Claude passes `as_of`. A test checks that the citations are POL-003 v2.0 chunks and that v1.0 was never shown. A live run answered 60 days, citing §4.5, and flagged SOP-014's stale Day 45. |
| Out-of-corpus → explicit "not covered" | If no finding keeps a citation, `merge` streams a fixed "The indexed PLG sources don't cover this question…" without calling Claude. Citations of chunks the run never retrieved are dropped first. When no specialist is routed, merge is told not to state PLG facts from memory. |
| PLG terms and synonyms (LOD, NC, A&A) | `VocabIndex.find_terms` spots capitalised abbreviations and multi-word labels. Their preferred labels are added to each search query, and the terms are listed in the agent's per-run context. NC and void deck were added as the `plg:place_types` vocabulary. |
| Citation chips in the Ask screen | `web/src/app/AskScreen.tsx`. A Sources list under the answer, one `<details>` chip per citation (`[n]`, title, section), opening to the quoted span. |

### How citations stay exact

Each retrieved chunk is sent to Claude as a Messages API `search_result` block with citations enabled, split into one text block per sentence. Claude's cited text blocks return `search_result_location` (`source` = chunk ID, start and end block). `run_agent` maps those back to character offsets in the chunk. A citation is kept only if its chunk was retrieved in this run. The agent's text gets `[n]` markers, and merge is told to keep them.

## Module map

```
src/plg/
├── llm.py                 + LLMClient.complete(): one whole reply with tools (AgentTurn = content blocks + stop_reason).
│                            ScriptedLLMClient.script_turns() (turns may be callables of the messages), `requests`;
│                            turn / text / tool_call builders.
├── agents/                NEW
│   ├── runtime.py         run_agent, Tool, Source (chunk → search_result block), AgentResult, Citation, Span.
│   └── knowledge.py       Knowledge system prompt, search_corpus tool (current by default, as_of, doc_types),
│                            query expansion with vocabulary terms, result titles with version/status/dates.
├── graph/state.py         + intents, findings (Finding: specialist, text, citations; reset by route each turn).
├── graph/build.py         route → knowledge → merge wiring, NOT_COVERED guard, merge prompt with findings.
├── events.py              + CitationEvent.
├── runs.py                Maps the knowledge node's `citation` stream chunks to CitationEvents.
├── search/rerank.py       + Retriever protocol, open_searcher(settings), LazySearcher.
├── ontology/vocab.py      + VocabIndex.find_terms, TermMatch.
├── api/app.py             create_app(settings, llm, searcher); defaults to LazySearcher.
└── cli.py                 `plg ask` prints the Sources after the answer.

ontology/plg.yaml          + PlaceType concept class.  ontology/vocab/place_types.yaml NEW (NC, void deck).
scripts/record_sse_fixtures.py   Syncs the corpus into a temp index; records answer / not_covered / error.
web/src/lib/events.ts      + citation in the zod RunEvent schema (checked against the generated OpenAPI type).
web/src/app/AskScreen.tsx  Collects citation events and renders the Sources chips.
```

## Tests

- `tests/test_knowledge_api.py` (HTTP seam, scripted Claude, real index and cross-encoder):
  - LOD cites v2.0 and never shows v1.0.
  - Trajectory is route → knowledge → merge, with citations before tokens.
  - Not-covered answer.
  - A fabricated citation is dropped.
  - Parallel tool calls run.
  - Prompt-cache marks are set.
  - The bare "LOD" query ranks POL-003 v2.0 §4.5 first. This one fails without the vocabulary expansion.
- `tests/test_anthropic_client.py`: `complete()` sends cached system and tools plus `tool_choice`, and parses cited text and tool calls.
- Existing run and CLI tests now script the router (`route(llm, question)` in `conftest.py`).
- Web:
  - Citation chips render with title, section and the quote (hidden until opened).
  - A not-covered answer shows no chips.
  - The parser accepts citation frames.
  - The trajectory shows three nodes.
- Totals: pytest 135 passed, vitest 32 passed, mypy strict, `tsc`, eslint clean.

## Next steps and known gaps

- **Search latency.** The cross-encoder rerank (from #5) takes 4 to 6 s per search over 50 candidates, so a live knowledge answer takes 30 to 60 s. Options: fewer candidates, a shorter `fts_text` passed to the reranker, or batching.
- **Merge fidelity.** Merge is asked to keep the `[n]` markers but nothing verifies it. Consider checking the streamed answer for unknown markers, or passing the cited sentences to merge.
- **Multiple specialists.** Citation numbering starts at 1 per specialist, and the "no citations → not covered" rule assumes every specialist cites. Both need revisiting when the data agent (SQL traces) and the `Send()` fan-out arrive.
- **Highlighting.** `span` offsets are relative to the chunk. The Sources panel ticket will need the chunk's location in the source document (`GET /documents/{doc_id}/chunks/{chunk_id}`).
- **Read-only tools.** Read-only is a convention in `Tool`, not an enforced flag.
- **Review smells left as is.**
  - Shared search-result citation builders in the fixture recorder and the tests.
  - `open_searcher` duplicating the CLI's embedder and searcher setup.
  - Key-sniffing of custom stream chunks in `runs.py`.
- **SOP contradiction warnings.** These rely on the agent prompt only. #1 story 17 is not fully covered here.
