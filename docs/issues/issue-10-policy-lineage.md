# Issue #10 - Policy lineage and current stance

## Summary of what was built
- **Edge evidence:** `Edge.props`. Edge CSVs carry typed property columns and `GraphWriter` rewrites them whole, so extracted edges keep `evidence_chunk_id`, `evidence_quote` and `scope`.
- **Extraction (`plg graph lineage`):** Policy/Sop/Circular/Clause/Precedent nodes are derived from index metadata. Haiku proposes SUPERSEDES / OVERRIDES / APPLIES through a forced `record_edges` tool. An edge is kept only with a verbatim quote from a chunk of the batch read and known, allowed endpoints; the rest are dropped and reported. Written through `GraphWriter`; re-runs add nothing new.
- **`policy_lineage(policy_id, as_of?)`:** versions with effective dates, supersessions, circular overrides with unit scope. `as_of` marks the version then in force as current. Cypher templates sit beside the in-memory implementation.
- **Knowledge agent:** a `policy_lineage` tool returning one citable passage (`lineage:<policy_id>`), plus prompt rules: state the rule per unit type, use `as_of` for earlier dates, flag SOPs/guides/FAQs/emails contradicting current policy.
- **Stream and web:** `policy_stance` SSE event; `PolicyStanceCard` at the top of the Sources panel.

## How it contributes to the project
Before this, the knowledge agent could cite documents in force today but had no structured view of how policies relate. Now the graph holds the version chain and overriding circulars with evidence, so answers state the current position, its effective date, what it replaced and which unit types a circular changes. A questioner asking about an earlier date gets the version then in force. The card gives the officer the same lineage at a glance, with the quotes it was read from.

## Module breakdown
| Path | New / modified | Role |
|---|---|---|
| `src/plg/entities/policy.py` | new | `PolicyLineage`, `PolicyVersion`, `Supersession`, `Override`, `build_lineage` |
| `src/plg/entities/model.py`, `csvio.py`, `writer.py` | modified | `Edge.props`, typed edge columns, edge file rewritten whole |
| `src/plg/entities/store.py`, `local.py`, `open.py`, `cypher.py` | modified | `policy_lineage` on the protocol, in-memory read, lazy delegate, `POLICY_*` templates |
| `src/plg/ingest/lineage.py` | new | node derivation, Haiku extraction, evidence validation |
| `src/plg/agents/entities.py`, `knowledge.py` | modified | `policy_lineage` tool, `on_lineage` callback, prompt rules |
| `src/plg/events.py`, `runs.py`, `graph/build.py` | modified | `PolicyStanceEvent`, stream mapping, knowledge node emits stances |
| `src/plg/cli.py`, `search/lance.py` | modified | `plg graph lineage`; `LanceSearchStore.path` |
| `web/src/app/PolicyStanceCard.tsx`, `AskScreen.tsx`, `ask.module.css`, `lib/events.ts` | new/modified | card and event handling |
| `web/openapi.json`, `lib/api/schema.d.ts`, `test/fixtures/*.sse`, `scripts/record_sse_fixtures.py` | regenerated/modified | contract and recorded fixtures |
| `tests/test_policy_lineage.py`, `tests/test_policy_stance_api.py` | new | extraction, lineage reads, API-level behaviour |

## Workflow map
Build time (`plg sync` then `plg graph lineage`):
```
SearchStore (chunks + doc metadata) -> ingest/lineage.py
  -> nodes: document_node / clause_nodes / precedent_nodes
  -> LLMClient.complete(node extract_lineage, haiku, forced record_edges)
  -> validate (verbatim quote, known + allowed endpoints) -> drops reported
  -> GraphWriter.write (allow-list check, delta CSVs, swap into LocalGraphStore)
```
Question time:
```
browser -> BFF -> POST /threads/{id}/runs -> stream_run -> graph
  route -> knowledge agent: search_corpus (as_of) + policy_lineage(policy_id, as_of)
             policy_lineage -> GraphStore.policy_lineage -> PolicyLineage
               -> lineage:<id> passage (cited)  +  on_lineage -> stances
  knowledge_node: writes citation chunks + policy_stance chunks
  merge (streams answer) -> events: node, citation, policy_stance, token, done
  runs.py -> PolicyStanceEvent -> SSE -> AskScreen -> PolicyStanceCard (Sources panel)
```

## Next steps / known gaps
- Run `plg graph lineage` on the real corpus with a live key. Scripted tests can't show the model flags the outdated FAQ, guide and email (deposit, renewal lead-time).
- Node properties (e.g. status after a new version) aren't refreshed on re-run; edges with the same type and endpoints share an ID, so the first evidence wins.
- Cypher templates are tested as text only (no Neptune).
- `npm run build` exits 1 here only because the Next.js advisory lookup is offline.
