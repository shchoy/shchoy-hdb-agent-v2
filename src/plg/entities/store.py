"""`GraphStore`: the read interface of the entity graph, and the shapes it returns."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from plg.entities.model import Edge, Node


class EntityRef(BaseModel):
    id: str
    label: str
    name: str


class EntityContext(BaseModel):
    """An entity and what surrounds it within `hops` edges. Entities and relationships only, never totals."""

    root: Node
    nodes: list[Node]
    """Every node reached, the root excluded."""
    edges: list[Edge]
    truncated: bool = False
    """True when the neighbourhood was cut short at the size limit."""


class GraphStore(Protocol):
    def resolve_entities(self, text: str, labels: list[str] | None = None, limit: int = 10) -> list[EntityRef]:
        """Entities a name, unit number or business ID refers to, best match first."""
        ...

    def entity_context(self, entity_id: str, hops: int = 2) -> EntityContext | None:
        """The entity and its neighbourhood within `hops` (1 or 2) edges, or None for an unknown ID."""
        ...
