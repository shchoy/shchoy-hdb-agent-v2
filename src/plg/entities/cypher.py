"""The openCypher templates a Neptune-backed `GraphStore` runs: one per `GraphStore` method.

They are fixed text with `$parameters`: nothing the model writes is ever spliced into a query, and the LLM
never sees or writes Cypher. `LocalGraphStore` computes the same results in memory.
"""

from __future__ import annotations

HUB_LABELS = ("Town", "NeighbourhoodCentre", "Block", "Trade", "DefectCategory", "Team", "Vendor", "Staff")
"""Reference nodes that many entities share. A walk lists them next to the entity but never walks through
them, otherwise one shared town or officer would pull in half the estate."""

MAX_HOPS = 2
MAX_CONTEXT_EDGES = 300

RESOLVE_ENTITIES = """\
MATCH (n)
WHERE (id(n) IN $ids OR ALL(t IN $tokens WHERE n.search_name CONTAINS t))
  AND (size($labels) = 0 OR labels(n)[0] IN $labels)
RETURN id(n) AS id, labels(n)[0] AS label, n.name AS name
ORDER BY CASE WHEN id(n) IN $ids THEN 0 WHEN n.search_name = $text THEN 1 WHEN n.search_name CONTAINS $text THEN 2 ELSE 3 END, size(n.name), n.name
LIMIT $limit"""

ENTITY_CONTEXT = {
    hops: f"""\
MATCH p = (s)-[*1..{hops}]-(n)
WHERE id(s) = $id AND ALL(m IN nodes(p)[1..-1] WHERE NOT labels(m)[0] IN $hub_labels)
UNWIND relationships(p) AS r
WITH DISTINCT r
RETURN id(startNode(r)) AS start, type(r) AS type, id(endNode(r)) AS end
LIMIT $limit"""
    for hops in range(1, MAX_HOPS + 1)
}

NODE_PROPERTIES = """\
MATCH (n)
WHERE id(n) IN $ids
RETURN id(n) AS id, labels(n)[0] AS label, n.name AS name, properties(n) AS props"""

TEMPLATES: dict[str, str] = {
    "resolve_entities": RESOLVE_ENTITIES,
    **{f"entity_context_{hops}": text for hops, text in ENTITY_CONTEXT.items()},
    "node_properties": NODE_PROPERTIES,
}
