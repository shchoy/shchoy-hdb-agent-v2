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

LINEAGE_LABELS = ("Policy", "Sop", "Template")
"""Passed as `$lineage_labels` to `policy_versions`."""

POLICY_VERSIONS = """\
MATCH (v)
WHERE labels(v)[0] IN $lineage_labels AND v.policy_id = $policy_id
RETURN id(v) AS id, labels(v)[0] AS label, v.name AS name, properties(v) AS props"""

POLICY_SUPERSEDES = """\
MATCH (a)-[r:SUPERSEDES]->(b)
WHERE a.policy_id = $policy_id AND b.policy_id = $policy_id
RETURN id(a) AS newer, id(b) AS older, properties(r) AS props"""

POLICY_OVERRIDES = """\
MATCH (c:Circular)-[r:OVERRIDES]->(cl:Clause)
WHERE cl.policy_id = $policy_id
RETURN id(c) AS circular, properties(c) AS circular_props, id(cl) AS clause, properties(cl) AS clause_props,
       properties(r) AS props
ORDER BY clause, circular"""

TEMPLATES: dict[str, str] = {
    "resolve_entities": RESOLVE_ENTITIES,
    **{f"entity_context_{hops}": text for hops, text in ENTITY_CONTEXT.items()},
    "node_properties": NODE_PROPERTIES,
    "policy_versions": POLICY_VERSIONS,
    "policy_supersedes": POLICY_SUPERSEDES,
    "policy_overrides": POLICY_OVERRIDES,
}
