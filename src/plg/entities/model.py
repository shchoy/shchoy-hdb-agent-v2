"""Graph data shared by the spine builder, the writer and the stores."""

from __future__ import annotations

from pydantic import BaseModel

from plg.entities.ids import search_name

Scalar = str | int | float | bool
"""Property values are scalars only: Neptune's bulk loader has no list or map columns."""


class Node(BaseModel):
    id: str
    label: str
    """The node's one label: a class from the ontology allow-list, e.g. `Tenant`."""
    name: str
    """Human-readable name, e.g. "Golden Leaf Minimart Pte Ltd"."""
    props: dict[str, Scalar] = {}

    @property
    def search_name(self) -> str:
        return search_name(self.name, self.id)


class Edge(BaseModel):
    type: str
    """`UPPER_SNAKE` relationship type from the allow-list."""
    start: str
    end: str

    @property
    def id(self) -> str:
        return f"{self.type}:{self.start}->{self.end}"


class GraphData(BaseModel):
    nodes: dict[str, Node] = {}
    edges: dict[str, Edge] = {}

    def add_node(self, node: Node) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        self.edges[edge.id] = edge
