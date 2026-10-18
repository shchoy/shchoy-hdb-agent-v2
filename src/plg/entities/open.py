"""Opening the entity graph from settings: the spine is built from PLG Records the first time it is needed."""

from __future__ import annotations

import threading

from plg.config import Settings
from plg.entities.local import LocalGraphStore
from plg.entities.spine import write_spine
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
