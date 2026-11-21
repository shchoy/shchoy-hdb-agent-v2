# Issue #9 — Entity graph and "tell me about this tenant/unit"

Tracking: https://github.com/shchoy/shchoy-hdb-agent-v2/issues/9 (parent #1, blocked by #6).

## What was built

- **Spine**: `plg graph build` turns PLG Records into typed nodes/edges (all allow-list labels with a records source) and writes Neptune openCypher bulk-load CSVs under `.plg/graph/spine`. Malformed IDs or disallowed edges are skipped and reported. Only invoices a letter was issued for become nodes.
- **GraphStore**: `resolve_entities(text, labels, limit)` (business ID first, then name/unit-number token match) and `entity_context(id, hops<=2)`. `LocalGraphStore` (frozen networkx) implements it; `cypher.py` holds the matching parameterised templates. Shared reference nodes (town, block, trade, staff, ...) are shown next to an entity but never walked through.
- **GraphWriter**: validates a whole batch against the ontology allow-list, appends delta CSVs under an `flock`, swaps in a newly frozen graph. Nothing exposes it to the agent.
- **Agent**: the knowledge agent gets read-only `resolve_entities` and `entity_context`. Context returns citable record passages, so record facts carry citations like documents. The LLM never writes graph queries.
- **Tests**: `tests/test_entity_graph.py` (_master ground-truth contract, Neptune-rule lint of CSVs and templates, writer, concurrency), `tests/test_entity_knowledge_api.py` (HTTP seam).

## Module map

| Path | Role |
|---|---|
| `src/plg/entities/ids.py` | strict ID regexes, `find_ids`, `search_name` |
| `src/plg/entities/{model,allow,csvio}.py` | data types, allow-list, Neptune CSV read/write |
| `src/plg/entities/spine.py` | deterministic build from PLG Records |
| `src/plg/entities/{store,local,cypher}.py` | interface, networkx store, Cypher templates |
| `src/plg/entities/writer.py` | validated, locked, atomic-swap writes |
| `src/plg/entities/open.py` | `open_graph`, `LazyGraph` |
| `src/plg/agents/entities.py` | agent tools and record passages |
| `src/plg/cli.py` | `plg graph build`, `plg graph show` |

## Next steps / known gaps

- Cited record passages have no document behind them: the source viewer's `/documents/{id}` will 404 for `doc_id` = an entity ID. Needs a record view or a non-openable chip in the web app.
- Cypher templates are not executed against Neptune or compared with `LocalGraphStore` automatically; `nodes(p)[1..-1]` and truncation behaviour should be checked on a real engine.
- A tenant's context stops at 2 hops, so feedback/tickets need a second `entity_context` call on the unit (the agent prompt says so).
- Ambiguous names (e.g. two "Golden Leaf Minimart" tenants) are returned as candidates; the agent is told to name them.
- Branch is stacked on `feat/8-scanned-pdf-ingestion` (main lacks #4–#8).
