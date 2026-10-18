"""`GraphWriter`: the only way to add to the entity graph after the spine is built.

A write is validated as a whole against the ontology allow-list (known label, strict ID, scalar properties,
permitted edge types and endpoints) before anything touches disk; one bad item rejects the batch. Accepted
writes are appended to delta CSVs under a file lock, then the graph is rebuilt from spine + deltas and swapped
into the store as a newly frozen graph. The agents have no tool that reaches this class.
"""

from __future__ import annotations

import fcntl
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from plg.entities.allow import AllowList, load_allow_list
from plg.entities.csvio import read_graph, write_edges, write_nodes
from plg.entities.ids import is_valid_id
from plg.entities.local import LocalGraphStore, freeze
from plg.entities.model import Edge, GraphData, Node

DELTA = "delta"


class GraphWriteError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class GraphWriter:
    def __init__(self, graph_dir: Path, store: LocalGraphStore, allow: AllowList | None = None) -> None:
        self.spine = graph_dir / "spine"
        self.delta = graph_dir / DELTA
        self.lock_path = graph_dir / ".lock"
        self.store = store
        self.allow = allow or load_allow_list()

    def write(self, nodes: Sequence[Node] = (), edges: Sequence[Edge] = ()) -> None:
        """Add nodes and edges, or raise `GraphWriteError` listing every problem and write nothing."""
        self.delta.mkdir(parents=True, exist_ok=True)
        with self._locked():
            current = read_graph(self.spine, self.delta)
            problems = self.problems(current, nodes, edges)
            if problems:
                raise GraphWriteError(problems)
            by_label: dict[str, list[Node]] = {}
            for node in nodes:
                by_label.setdefault(node.label, []).append(node)
            earlier = read_graph(self.delta)
            for label, group in by_label.items():
                # Rewritten whole, so a new property widens the header instead of failing half-way.
                before = [n for n in earlier.nodes.values() if n.label == label]
                write_nodes(self.delta, label, [*before, *group])
            fresh = {e.id: e for e in edges if e.id not in current.edges}
            if fresh:
                write_edges(self.delta, list(fresh.values()), append=True)
            self.store.swap(freeze(read_graph(self.spine, self.delta)))

    def problems(self, current: GraphData, nodes: Sequence[Node], edges: Sequence[Edge]) -> list[str]:
        problems: list[str] = []
        labels = {n.id: n.label for n in current.nodes.values()}
        for node in nodes:
            if node.label not in self.allow.node_labels:
                problems.append(f"{node.id}: {node.label!r} is not an ontology node label")
            elif not is_valid_id(node.label, node.id):
                problems.append(f"{node.id}: not a valid {node.label} ID")
            elif node.id in labels:
                problems.append(f"{node.id}: already in the graph")
            else:
                labels[node.id] = node.label
            for key, value in node.props.items():
                if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
                    problems.append(f"{node.id}.{key}: property names are lower_snake_case")
                if not isinstance(value, str | int | float | bool):
                    problems.append(f"{node.id}.{key}: properties must be scalar")
        for edge in edges:
            start, end = labels.get(edge.start), labels.get(edge.end)
            if edge.type not in self.allow.edges:
                problems.append(f"{edge.id}: {edge.type} is not an ontology edge type")
            elif start is None or end is None:
                problems.append(f"{edge.id}: endpoint is not in the graph")
            elif not self.allow.permits_edge(edge.type, start, end):
                problems.append(f"{edge.id}: {edge.type} does not run from {start} to {end}")
        return problems

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
