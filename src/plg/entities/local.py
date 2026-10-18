"""`LocalGraphStore`: the entity graph in memory (networkx), frozen so readers never see a half-built graph."""

from __future__ import annotations

import threading
from pathlib import Path

import networkx as nx

from plg.entities import cypher
from plg.entities.csvio import read_graph
from plg.entities.ids import find_ids, search_name
from plg.entities.model import Edge, GraphData, Node
from plg.entities.store import EntityContext, EntityRef


def freeze(data: GraphData) -> nx.MultiDiGraph:
    graph: nx.MultiDiGraph = nx.MultiDiGraph()
    for node in data.nodes.values():
        graph.add_node(node.id, node=node)
    for edge in data.edges.values():
        graph.add_edge(edge.start, edge.end, key=edge.type, edge=edge)
    return nx.freeze(graph)


class LocalGraphStore:
    def __init__(self, graph: nx.MultiDiGraph | None = None) -> None:
        self._graph = graph if graph is not None else freeze(GraphData())
        self._swap = threading.Lock()

    @classmethod
    def from_dirs(cls, *dirs: Path) -> LocalGraphStore:
        return cls(freeze(read_graph(*dirs)))

    def swap(self, graph: nx.MultiDiGraph) -> None:
        """Replace the whole graph with a newly frozen one."""
        with self._swap:
            self._graph = graph

    def node(self, node_id: str) -> Node | None:
        graph = self._graph
        return graph.nodes[node_id]["node"] if node_id in graph else None

    def resolve_entities(self, text: str, labels: list[str] | None = None, limit: int = 10) -> list[EntityRef]:
        graph = self._graph
        wanted = search_name(text)
        tokens = wanted.split()
        ids = find_ids(text) + ([text.strip()] if text.strip() in graph else [])
        ranked: list[tuple[int, int, str, Node]] = []
        for node_id, attrs in graph.nodes(data=True):
            node: Node = attrs["node"]
            if labels and node.label not in labels:
                continue
            if node_id in ids:
                rank = 0
            elif not tokens or not all(t in node.search_name for t in tokens):
                continue
            elif node.search_name == wanted:
                rank = 1
            else:
                rank = 2 if wanted in node.search_name else 3
            ranked.append((rank, len(node.name), node.name, node))
        ranked.sort(key=lambda r: r[:3])
        return [EntityRef(id=n.id, label=n.label, name=n.name) for *_, n in ranked[:limit]]

    def entity_context(self, entity_id: str, hops: int = 2) -> EntityContext | None:
        graph = self._graph
        if entity_id not in graph:
            return None
        hops = max(1, min(hops, cypher.MAX_HOPS))
        edges: dict[str, Edge] = {}
        reached = {entity_id}
        frontier = [entity_id]
        truncated = False
        for _ in range(hops):
            following: list[str] = []
            for current in frontier:
                around = [
                    *graph.out_edges(current, data="edge"),
                    *graph.in_edges(current, data="edge"),
                ]
                for _, _, edge in around:
                    other = edge.end if edge.start == current else edge.start
                    if len(edges) >= cypher.MAX_CONTEXT_EDGES and edge.id not in edges:
                        truncated = True
                        continue
                    edges[edge.id] = edge
                    if other not in reached:
                        reached.add(other)
                        if graph.nodes[other]["node"].label not in cypher.HUB_LABELS:
                            following.append(other)
            frontier = following
        nodes = [graph.nodes[i]["node"] for i in reached if i != entity_id]
        nodes.sort(key=lambda n: (n.label, n.id))
        return EntityContext(
            root=graph.nodes[entity_id]["node"], nodes=nodes, edges=sorted(edges.values(), key=lambda e: e.id),
            truncated=truncated,
        )
