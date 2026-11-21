# Issue #11: Precedent search

## What was built

Officers can ask for precedents ("any precedent for a provision shop in Pasir Indah Central NC changing to bubble
tea?"). The answer lists past cases matched by **trade, NC and issue**, gives each case's decision and reasoning,
says **how the officer's case differs**, and **cites the compendium page or the email** the precedent came from.

- **Precedent cases in the graph.** `plg graph lineage` now parses each compendium case into its Precedent node,
  with no LLM involved. Each node holds the date of decision, category, town, facts, decision, reasoning, outcome,
  and the chunk and page it was read from. Each node is linked by `CONCERNS_TRADE` to the trades its chunk is
  tagged with, and by `IN_NC` to the NC it names. `IN_NC` is a new Precedent edge in the ontology; `make ontology`
  was re-run.
- **`GraphStore.find_precedents(trade?, nc?, issue?, limit)`** is implemented in `LocalGraphStore` and `LazyGraph`,
  with the `FIND_PRECEDENTS` and `NC_TOWN` openCypher templates.
  - Trade and NC names are resolved to IDs.
  - Cases are ranked by `rank_precedents`: same trade, NC or issue each score 2, and the same town scores 1 as a
    tie-break.
  - The issue is matched on word overlap with the case category, comparing word stems, so "sublet" finds
    "Unauthorised subletting".
- **The knowledge agent's `find_precedents` tool** returns two things:
  - A plain-text note per match saying what the case shares with the officer's case and how it differs. The note
    is not citable and deliberately holds no decision text.
  - Each case's compendium page, plus every email or document naming its PC ID, as citable search results.
- **Runtime:** a tool may now return plain-text notes alongside its citable sources.
- **Prompts:** the knowledge prompt now covers precedent questions: compare against the facts of the current case,
  cite the page or email, and remember that precedents guide but don't bind. The router counts precedents as
  `knowledge`.

## How it fits the overall functionality

This delivers user stories 28–31 (DC4) of #1. It adds the third fixed `GraphStore` method (after `resolve_entities`,
`entity_context` and `policy_lineage`), with its contract test on the bubble-tea precedents for NC-PI-1.
Precedent answers flow through the same citation path as policy answers: an answer whose claims lose their
citations still becomes the fixed "not covered" answer.

## Module breakdown

| Path | New / modified | Role |
|---|---|---|
| `src/plg/entities/precedent.py` | New | `Precedent`, `PrecedentMatch`, `Situation`; `rank_precedents` and issue matching, shared by every store |
| `src/plg/entities/store.py` | Modified | `GraphStore.find_precedents` protocol method |
| `src/plg/entities/local.py` | Modified | `LocalGraphStore.find_precedents` (resolve, town of the NC, candidates, rank) |
| `src/plg/entities/open.py` | Modified | `LazyGraph.find_precedents` |
| `src/plg/entities/cypher.py` | Modified | `FIND_PRECEDENTS`, `NC_TOWN` templates |
| `src/plg/ingest/lineage.py` | Modified | `case_fields`, richer `precedent_nodes`, `precedent_edges` (CONCERNS_TRADE / IN_NC) |
| `src/plg/agents/entities.py` | Modified | `precedent_tool`: match notes + compendium page and email passages |
| `src/plg/agents/knowledge.py` | Modified | Wires `find_precedents` in when a graph is given; precedent rule in the prompt |
| `src/plg/agents/runtime.py` | Modified | `ToolOutput` may mix plain-text notes with `Source`s |
| `src/plg/graph/build.py` | Modified | Router: precedents are `knowledge` |
| `ontology/plg.yaml`, `src/plg/ontology/generated/*` | Modified | `Precedent -IN_NC-> NeighbourhoodCentre` |
| `tests/test_precedents.py` | New | GraphStore contract tests (NC-PI-1 bubble tea, fire rebate, sublet, no match, Cypher params) |
| `tests/test_precedent_api.py` | New | HTTP/SSE seam: citations to compendium page and email, match notes, fire case evidence |
| `tests/test_entity_knowledge_api.py` | Modified | Read-only tool list includes `find_precedents` |

## Workflow map

```
plg sync ──> LanceDB chunks (compendium chunks tagged: PC ID, trade, NC, town)
                │
plg graph lineage ──> precedent_nodes + precedent_edges ──> GraphWriter ──> Precedent nodes
                                                                         + CONCERNS_TRADE / IN_NC edges

question ─> route (knowledge) ─> knowledge agent ─> find_precedents tool
                                    │                 ├─ GraphStore.find_precedents
                                    │                 │    resolve_entities → NC town → candidates → rank_precedents
                                    │                 ├─ note: shares / differs per case (not citable)
                                    │                 └─ Retriever.search(entity_ids=[PC ID]) per case
                                    │                       → compendium page + emails (search_result blocks)
                                    ├─ search_corpus (facts of the officer's own case, e.g. incident report)
                                    └─ answer with [n] citations ─> merge ─> SSE citation / token events
```

## Next steps

- If an earlier `plg graph lineage` run already wrote bare Precedent nodes, the writer never updates them, so their
  case fields stay empty. Clear `.plg/graph/delta` and re-run `plg graph lineage` to fill them in.
- Precedents are only cited to emails that name the PC number. Emails that discuss a case without naming it are
  reachable only through `search_corpus`.
- Issue matching uses word overlap. If the evals show misses, map case categories to a vocabulary scheme.
- A UI card for precedents (similar to PolicyStanceCard) was not asked for, and no SSE event was added.
- Neptune adapter: run `resolve_entities` → `nc_town` → `find_precedents`, then `rank_precedents`.
