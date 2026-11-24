# Issue #81: Inline `[n]` citations and sources side panel

Parent: #74 · Blocked by: #77 (chat thread layout and composer)

## What was built

- **Inline citation markers.** Each `[n]` in an answer is now a small button, in both the streamed answer and earlier answers in the conversation. Its accessible name is `[n] <source title>`. A marker inside code stays text, and so does a marker with no known source.
- **Sources panel** (`SourcesPanel.tsx`). Activating a marker, or the new "Sources (n)" button under an answer, opens the panel for that answer at source n. The panel scrolls to that source and moves focus to it.
  - The answer's policy stance cards sit at the top.
  - Each source shows its title, version and location, a Quote to expand, and "Open source", which opens the document in the existing viewer with the span highlighted.
  - Escape or "Close sources" closes the panel and puts focus back on the marker that opened it.
  - From 64rem up it is a sticky column beside the conversation, so it never covers the composer. Below 64rem it is a bottom sheet.
- **The citation chips under the answer are removed.** The panel replaces them.
- **Earlier answers keep their sources** (backend). Before this change a reopened thread had no citations. Now each `AnsweredTurn` (`ThreadView.turns`) records its numbered citations (`NumberedCitation`, numbered exactly as the `citation` events were) and its policy stances (`Finding.stances`, filled by the knowledge node). `CitationEvent` now extends `NumberedCitation`.

## How it fits the product

Every knowledge answer must be cited (a project convention). This change puts the evidence one click from the claim it supports, instead of in a list under the answer. Officers can check a claim against its source document (version, location, highlighted span) without losing their place in the chat. This now works after a reload or when a past conversation is reopened. The policy stance card stays next to the sources, so superseded versions and circular overrides are seen alongside the citation.

## Module breakdown

| Path | New / modified | Role |
|---|---|---|
| `src/plg/feedback/model.py` | Modified | `NumberedCitation` (Citation + `index`); `AnsweredTurn.citations` / `.stances` |
| `src/plg/graph/state.py` | Modified | `Finding.stances`: the policy stances a specialist read |
| `src/plg/graph/build.py` | Modified | knowledge_node puts its stances on the finding; merge copies the numbered citations and stances onto the `AnsweredTurn` |
| `src/plg/events.py` | Modified | `CitationEvent` extends `NumberedCitation` |
| `tests/test_policy_stance_api.py` | Modified | a reopened thread keeps each answer's citations (same as streamed) and stance; an answer without sources keeps none |
| `web/src/app/SourcesPanel.tsx` | New | the panel: stances, sources, quote, SourceViewer, focus on open, Escape/Close |
| `web/src/app/AnswerText.tsx` | Modified | rehype plugin `[n]` → `CitationMarker` button (stable component + context, so focus can return to it) |
| `web/src/app/AskScreen.tsx` | Modified | panel state (sources, index, opener), sources of each earlier answer from `ThreadView.turns`, "Sources (n)" button; old chips removed |
| `web/src/app/SourceViewer.tsx`, `PolicyStanceCard.tsx` | Modified | accept the schema types shared by live events and stored turns |
| `web/src/app/ask.module.css` | Modified | marker, panel (side column ≥ 64rem / bottom sheet), source items |
| `web/openapi.json`, `web/src/lib/api/schema.d.ts` | Regenerated | new `NumberedCitation`, turn fields |
| `web/src/app/AskScreen.test.tsx` | Modified | marker names, panel at source n with focus, Escape/Close focus return, open source with highlight, stance card in panel, earlier answer's markers, `[n]` in code stays text |
| `web/e2e/journeys.spec.ts`, `accessibility.spec.ts`, `helpers.ts` | Modified | cited-answer journey via the panel (beside the composer, Escape → marker, reopened answer), phone bottom sheet, axe in both themes |

## Workflow

```
knowledge_node ──(policy_stance, citation[index n] events)──► SSE ──► AskScreen (live Answer: citations, stances)
      │ Finding(citations, stances)
      ▼
merge ── AnsweredTurn(citations numbered 1..n, stances) ──► checkpoint (graph state `turns`)
                                                             │
GET /threads/{id} ── ThreadView.turns ──► BFF ──► AskScreen.open(): sourcesOf[message_index]

AnswerText (rehype: [n] → CitationMarker) ──click──► AskScreen.cite(sources)(n, opener)
      ──► SourcesPanel(sources, index n) ── PolicyStanceCard, source list ── SourceViewer ──► /api/documents/... (highlight)
      ◄── Escape / Close sources ── focus back to the opener
```

## Notes and next steps

- Between 48rem and 64rem (small laptops and tablets) the panel is a bottom sheet and covers the composer. The side column would be too narrow there.
- The bottom sheet is not modal: no focus trap and no inert background, unlike the sidebar drawer.
- Only `[n]` markers are turned into buttons. Grouped forms such as `[1, 2]` stay text. The merge prompt asks for `[n]`.
- Citation numbering assumes only the knowledge specialist cites, which is true today. If another specialist starts citing, merge must number all citations across findings.
