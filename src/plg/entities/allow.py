"""The ontology allow-list: which node labels and typed edges the graph may hold."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from plg.ontology import GENERATED


@dataclass(frozen=True)
class AllowList:
    node_labels: frozenset[str]
    edges: dict[str, list[tuple[frozenset[str], frozenset[str]]]]
    """Per edge type, each permitted (start labels, end labels) pairing."""

    def permits_edge(self, edge_type: str, start_label: str, end_label: str) -> bool:
        return any(start_label in s and end_label in e for s, e in self.edges.get(edge_type, []))


@cache
def load_allow_list(path: Path = GENERATED / "allow_list.json") -> AllowList:
    raw = json.loads(path.read_text())
    edges: dict[str, list[tuple[frozenset[str], frozenset[str]]]] = {}
    for e in raw["edges"]:
        edges.setdefault(e["type"], []).append((frozenset(e["domain_labels"]), frozenset(e["range_labels"])))
    return AllowList(frozenset(raw["node_labels"]), edges)
