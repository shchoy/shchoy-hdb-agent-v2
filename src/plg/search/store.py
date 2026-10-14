"""`SearchStore`: the retrieval index. LanceDB in the POC; OpenSearch later, behind the same contract."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol

from plg.search.models import Chunk, DocStatus, DocumentMeta, EntityRecord, MemoryItem, SearchFilter, SearchHit


class SearchStore(Protocol):
    # ------------------------------------------------------------------ chunks
    def replace_document(self, doc_id: str, chunks: Sequence[Chunk]) -> None:
        """Make `chunks` the document's only chunks (an empty list removes the document)."""
        ...

    def documents(self) -> list[DocumentMeta]:
        """One entry per indexed document, in doc_id order."""
        ...

    def set_lifecycle(self, doc_id: str, *, status: DocStatus, effective_to: date | None) -> None:
        """Update a document's status and end date on all its chunks, without re-embedding them."""
        ...

    def chunks(self, doc_id: str) -> list[Chunk]:
        """A document's chunks in reading order."""
        ...

    def get_chunk(self, chunk_id: str) -> Chunk | None: ...

    def search(
        self, text: str, vector: Sequence[float], *, filters: SearchFilter | None = None, limit: int = 50
    ) -> list[SearchHit]:
        """Hybrid search: full-text and vector scores combined linearly, over pre-filtered chunks."""
        ...

    # ------------------------------------------------------------------ entities
    def replace_entities(self, entities: Sequence[EntityRecord]) -> None: ...

    def find_entities(self, text: str, *, limit: int = 10) -> list[EntityRecord]:
        """Entities with a name variant matching `text`, best match first."""
        ...

    # ------------------------------------------------------------------ memory
    def put_memory(self, item: MemoryItem) -> None:
        """Insert or replace the item with the same namespace and key."""
        ...

    def get_memory(self, namespace: tuple[str, ...], key: str) -> MemoryItem | None: ...

    def delete_memory(self, namespace: tuple[str, ...], key: str) -> None: ...

    def search_memory(
        self,
        namespace_prefix: tuple[str, ...],
        vector: Sequence[float],
        *,
        now: datetime,
        limit: int = 10,
    ) -> list[MemoryItem]:
        """Active, unexpired items under the namespace prefix, nearest first."""
        ...
