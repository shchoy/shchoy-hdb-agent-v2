"""Records held by a `SearchStore`: corpus chunks, entity name variants and long-term memory items."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DocStatus = Literal["current", "superseded"]
SourceSystem = Literal["sharepoint", "lotus_notes"]
MemoryStatus = Literal["active", "pending_review", "retired"]


class DocumentMeta(BaseModel):
    """Document-level metadata, copied onto every chunk so search can pre-filter on it."""

    doc_id: str
    doc_type: str
    title: str
    source_system: SourceSystem
    source_path: str
    policy_id: str | None = None
    version: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    status: DocStatus = "current"
    category: str | None = None
    content_hash: str


class Chunk(DocumentMeta):
    chunk_id: str
    seq: int
    header: str
    """Contextual header (document, version, section) prepended to the text for FTS and embedding."""
    text: str
    location: str
    """Where the chunk sits in its source: section path, page or slide."""
    town: list[str] = Field(default_factory=list)
    nc: list[str] = Field(default_factory=list)
    trade: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    vector: list[float]

    @property
    def fts_text(self) -> str:
        return f"{self.header}\n{self.text}"


class SearchFilter(BaseModel):
    """Metadata pre-filters, applied before ranking. List fields match if any value matches."""

    doc_ids: list[str] | None = None
    doc_type: list[str] | None = None
    policy_id: str | None = None
    status: DocStatus | None = None
    source_system: SourceSystem | None = None
    category: str | None = None
    town: list[str] | None = None
    nc: list[str] | None = None
    trade: list[str] | None = None
    entity_ids: list[str] | None = None
    in_force_on: date | None = None
    """Only documents in force on this date (undated documents always pass)."""


class SearchHit(BaseModel):
    chunk: Chunk
    score: float
    """Hybrid (linear combination) score, replaced by the cross-encoder score after reranking."""


class EntityRecord(BaseModel):
    """Name variants of a graph node, so free text can be resolved to its ID."""

    entity_id: str
    entity_type: str
    name: str
    variants: list[str] = Field(default_factory=list)


class MemoryItem(BaseModel):
    namespace: tuple[str, ...]
    key: str
    value: dict[str, Any]
    text: str
    """What the item says, in words; it is embedded for semantic recall."""
    vector: list[float]
    status: MemoryStatus = "active"
    provenance: str
    confidence: float = 1.0
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
