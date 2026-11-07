"""Opening the entity graph from settings: the spine is built from PLG Records the first time it is needed."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date

from plg.config import Settings
from plg.entities.local import LocalGraphStore
from plg.entities.spine import write_spine
from plg.entities.policy import PolicyLineage
from plg.entities.writer import GraphWriteError, GraphWriter
from plg.entities.model import Edge
from plg.entities.store import EntityContext, EntityRef


def open_graph(settings: Settings, rebuild: bool = False) -> LocalGraphStore:
    spine = settings.graph_dir / "spine"
    if rebuild or not any(spine.glob("nodes_*.csv")):
        write_spine(settings.records_db, spine)
    return LocalGraphStore.from_dirs(spine, settings.graph_dir / "delta")


class LazyGraph:
    """A `GraphStore` opened on first use, so `plg-api` starts and prints its OpenAPI without PLG Records built."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._store: LocalGraphStore | None = None
        self._lock = threading.Lock()

    def _open(self) -> LocalGraphStore:
        with self._lock:
            if self._store is None:
                self._store = open_graph(self._settings)
            return self._store

    def resolve_entities(self, text: str, labels: list[str] | None = None, limit: int = 10) -> list[EntityRef]:
        return self._open().resolve_entities(text, labels, limit)

    def entity_context(self, entity_id: str, hops: int = 2) -> EntityContext | None:
        return self._open().entity_context(entity_id, hops)

    def policy_lineage(self, policy_id: str, as_of: date | None = None) -> PolicyLineage | None:
        return self._open().policy_lineage(policy_id, as_of)

    def writer(self) -> GraphWriter:
        return GraphWriter(self._settings.graph_dir, self._open())


def work_linker(writer: Callable[[], GraphWriter]) -> Callable[[str, list[str]], None]:
    """Record `WORKED_ON` edges from a staff member to entities they asked about; IDs the graph can't link are skipped."""

    def link(staff_id: str, entity_ids: list[str]) -> None:
        graph = writer()
        for entity_id in entity_ids:
            try:
                graph.write(edges=[Edge(type="WORKED_ON", start=staff_id, end=entity_id)])
            except GraphWriteError:
                continue

    return link
