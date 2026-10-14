"""`SearchStore` on embedded LanceDB: `chunks`, `entities` and `memory` tables in one directory."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

import lancedb
import pyarrow as pa
from lancedb.index import FTS
from lancedb.query import LanceHybridQueryBuilder, LanceVectorQueryBuilder
from lancedb.rerankers import LinearCombinationReranker
from lancedb.table import Table

from plg.search.models import Chunk, DocStatus, DocumentMeta, EntityRecord, MemoryItem, SearchFilter, SearchHit

_STRINGS = pa.list_(pa.string())


def _chunk_schema(dim: int) -> pa.Schema:
    return pa.schema([
        ("chunk_id", pa.string()), ("doc_id", pa.string()), ("seq", pa.int32()),
        ("doc_type", pa.string()), ("title", pa.string()), ("source_system", pa.string()),
        ("source_path", pa.string()), ("policy_id", pa.string()), ("version", pa.string()),
        ("effective_from", pa.date32()), ("effective_to", pa.date32()), ("status", pa.string()),
        ("category", pa.string()), ("content_hash", pa.string()), ("header", pa.string()),
        ("text", pa.string()), ("location", pa.string()), ("town", _STRINGS), ("nc", _STRINGS),
        ("trade", _STRINGS), ("entity_ids", _STRINGS), ("fts_text", pa.string()),
        ("vector", pa.list_(pa.float32(), dim)),
    ])


_ENTITY_SCHEMA = pa.schema([
    ("entity_id", pa.string()), ("entity_type", pa.string()), ("name", pa.string()),
    ("variants", _STRINGS), ("fts_text", pa.string()),
])


def _memory_schema(dim: int) -> pa.Schema:
    return pa.schema([
        ("namespace", pa.string()), ("key", pa.string()), ("value", pa.string()), ("text", pa.string()),
        ("status", pa.string()), ("provenance", pa.string()), ("confidence", pa.float64()),
        ("created_at", pa.timestamp("us", tz="UTC")), ("updated_at", pa.timestamp("us", tz="UTC")),
        ("expires_at", pa.timestamp("us", tz="UTC")), ("vector", pa.list_(pa.float32(), dim)),
    ])


def _q(value: str) -> str:
    """A SQL string literal."""
    return "'" + value.replace("'", "''") + "'"


def _list(values: Sequence[str]) -> str:
    return "[" + ", ".join(_q(v) for v in values) + "]"


def _where(f: SearchFilter | None) -> str | None:
    if f is None:
        return None
    clauses: list[str] = []
    for column in ("doc_ids", "doc_type"):
        values: list[str] | None = getattr(f, column)
        if values is not None:
            clauses.append(f"{column.removesuffix('s')} IN ({', '.join(_q(v) for v in values) or 'NULL'})")
    for column in ("policy_id", "status", "source_system", "category"):
        value: str | None = getattr(f, column)
        if value is not None:
            clauses.append(f"{column} = {_q(value)}")
    for column in ("town", "nc", "trade", "entity_ids"):
        values = getattr(f, column)
        if values is not None:
            clauses.append(f"array_has_any({column}, {_list(values)})")
    if f.in_force_on is not None:
        day = f"date {_q(f.in_force_on.isoformat())}"
        clauses.append(f"(effective_from IS NULL OR effective_from <= {day})")
        clauses.append(f"(effective_to IS NULL OR effective_to >= {day})")
    return " AND ".join(clauses) or None


def _ns(namespace: tuple[str, ...]) -> str:
    return "/".join(namespace)


class LanceSearchStore:
    def __init__(self, path: Path, *, dim: int, vector_weight: float = 0.7) -> None:
        self._vector_weight = vector_weight
        path.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(path)
        self._chunks = self._open("chunks", _chunk_schema(dim))
        self._entities = self._open("entities", _ENTITY_SCHEMA)
        self._memory = self._open("memory", _memory_schema(dim))
        for name, table in (("chunks", self._chunks), ("memory", self._memory)):
            existing = table.schema.field("vector").type.list_size
            if existing != dim:
                raise ValueError(
                    f"{path}: the {name} table holds {existing}-d vectors but the embedder makes {dim}-d ones; "
                    "rebuild the index with `plg sync --full`"
                )

    def _open(self, name: str, schema: pa.Schema) -> Table:
        return self._db.create_table(name, schema=schema, exist_ok=True)

    @staticmethod
    def _ensure_fts(table: Table) -> None:
        # Rows added after the index was built are still searched (unindexed rows are scanned).
        if not any(i.index_type == "FTS" for i in table.list_indices()):
            table.create_index("fts_text", config=FTS(), replace=True)

    def optimize(self) -> None:
        """Fold rows written since the last build into the indexes. Optional: search works without it."""
        for table in (self._chunks, self._entities):
            table.create_index("fts_text", config=FTS(), replace=True)

    # ------------------------------------------------------------------ chunks
    def replace_document(self, doc_id: str, chunks: Sequence[Chunk]) -> None:
        self._chunks.delete(f"doc_id = {_q(doc_id)}")
        if chunks:
            self._chunks.add([{**c.model_dump(), "fts_text": c.fts_text} for c in chunks])

    def documents(self) -> list[DocumentMeta]:
        rows = self._chunks.search().where("seq = 0").limit(None).to_arrow().to_pylist()
        return sorted((DocumentMeta.model_validate(r) for r in rows), key=lambda d: d.doc_id)

    def set_lifecycle(self, doc_id: str, *, status: DocStatus, effective_to: date | None) -> None:
        self._chunks.update(
            where=f"doc_id = {_q(doc_id)}", values={"status": status, "effective_to": effective_to}
        )

    def chunks(self, doc_id: str) -> list[Chunk]:
        rows = self._chunks.search().where(f"doc_id = {_q(doc_id)}").limit(None).to_arrow().to_pylist()
        return sorted((Chunk.model_validate(r) for r in rows), key=lambda c: c.seq)

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        rows = self._chunks.search().where(f"chunk_id = {_q(chunk_id)}").limit(1).to_arrow().to_pylist()
        return Chunk.model_validate(rows[0]) if rows else None

    def search(
        self,
        text: str,
        vector: Sequence[float],
        *,
        filters: SearchFilter | None = None,
        limit: int = 50,
    ) -> list[SearchHit]:
        if self._chunks.count_rows() == 0:
            return []
        self._ensure_fts(self._chunks)
        hybrid = cast(LanceHybridQueryBuilder, self._chunks.search(query_type="hybrid", fts_columns="fts_text"))
        query = (
            hybrid.vector(list(vector))
            .text(text)
            .distance_type("cosine")
        )
        where = _where(filters)
        if where:
            query = query.where(where, prefilter=True)
        rows = (
            query.rerank(LinearCombinationReranker(weight=self._vector_weight)).limit(limit).to_arrow().to_pylist()
        )
        return [SearchHit(chunk=Chunk.model_validate(r), score=r["_relevance_score"]) for r in rows]

    # ------------------------------------------------------------------ entities
    def replace_entities(self, entities: Sequence[EntityRecord]) -> None:
        self._entities.delete("true")
        if entities:
            self._entities.add([
                {**e.model_dump(), "fts_text": "\n".join(dict.fromkeys([e.name, *e.variants]))}
                for e in entities
            ])
            self._entities.create_index("fts_text", config=FTS(), replace=True)

    def find_entities(self, text: str, *, limit: int = 10) -> list[EntityRecord]:
        if self._entities.count_rows() == 0:
            return []
        self._ensure_fts(self._entities)
        rows = self._entities.search(text, query_type="fts", fts_columns="fts_text").limit(limit)
        return [EntityRecord.model_validate(r) for r in rows.to_arrow().to_pylist()]

    # ------------------------------------------------------------------ memory
    def put_memory(self, item: MemoryItem) -> None:
        row = {**item.model_dump(), "namespace": _ns(item.namespace), "value": json.dumps(item.value)}
        (
            self._memory.merge_insert(["namespace", "key"])
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute([row])
        )

    def _memory_where(self, namespace: tuple[str, ...], key: str) -> str:
        return f"namespace = {_q(_ns(namespace))} AND key = {_q(key)}"

    def get_memory(self, namespace: tuple[str, ...], key: str) -> MemoryItem | None:
        rows = self._memory.search().where(self._memory_where(namespace, key)).limit(1).to_arrow().to_pylist()
        return self._to_memory(rows[0]) if rows else None

    def delete_memory(self, namespace: tuple[str, ...], key: str) -> None:
        self._memory.delete(self._memory_where(namespace, key))

    def search_memory(
        self,
        namespace_prefix: tuple[str, ...],
        vector: Sequence[float],
        *,
        now: datetime,
        limit: int = 10,
    ) -> list[MemoryItem]:
        prefix = _ns(namespace_prefix)
        stamp = f"timestamp {_q(now.isoformat())}"
        where = (
            f"(namespace = {_q(prefix)} OR starts_with(namespace, {_q(prefix + '/')})) "
            f"AND status = 'active' AND (expires_at IS NULL OR expires_at > {stamp})"
        )
        nearest = cast(LanceVectorQueryBuilder, self._memory.search(list(vector)))
        rows = nearest.distance_type("cosine").where(where, prefilter=True).limit(limit)
        return [self._to_memory(r) for r in rows.to_arrow().to_pylist()]

    @staticmethod
    def _to_memory(row: dict[str, Any]) -> MemoryItem:
        return MemoryItem.model_validate(
            {**row, "namespace": tuple(row["namespace"].split("/")), "value": json.loads(row["value"])}
        )
