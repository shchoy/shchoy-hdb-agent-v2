"""`LanceUploadIndex`: every officer's uploaded passages in one LanceDB table of its own, apart from the shared Library
index, each row carrying its owner. Every read is filtered on the owner, so one officer's uploads never reach another."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path
from typing import cast

import lancedb
import pyarrow as pa
from lancedb.index import FTS
from lancedb.query import LanceHybridQueryBuilder
from lancedb.rerankers import LinearCombinationReranker

from plg.search.lance import _chunk_schema, _q, _where
from plg.search.models import Chunk, SearchFilter, SearchHit


class LanceUploadIndex:
    def __init__(self, path: Path, *, dim: int, vector_weight: float = 0.7) -> None:
        path.mkdir(parents=True, exist_ok=True)
        self._vector_weight = vector_weight
        db = lancedb.connect(path, read_consistency_interval=timedelta(0))
        schema = _chunk_schema(dim).append(pa.field("owner", pa.string()))
        self._table = db.create_table("uploads", schema=schema, exist_ok=True)
        self._writing = threading.Lock()  # one write at a time: concurrent index builds conflict in LanceDB

    def add(self, owner: str, chunks: Sequence[Chunk]) -> None:
        if not chunks:
            return
        with self._writing:
            self._table.add([{**c.model_dump(), "fts_text": c.fts_text, "owner": owner} for c in chunks])
            self._table.create_index("fts_text", config=FTS(), replace=True)

    def remove(self, doc_id: str) -> None:
        with self._writing:
            self._table.delete(f"doc_id = {_q(doc_id)}")

    def _rows(self, where: str) -> list[Chunk]:
        rows = self._table.search().where(where).limit(None).to_arrow().to_pylist()
        return sorted((Chunk.model_validate(r) for r in rows), key=lambda c: c.seq)

    def chunks(self, owner: str, doc_id: str) -> list[Chunk]:
        return self._rows(f"owner = {_q(owner)} AND doc_id = {_q(doc_id)}")

    def get_chunk(self, owner: str, chunk_id: str) -> Chunk | None:
        found = self._rows(f"owner = {_q(owner)} AND chunk_id = {_q(chunk_id)}")
        return found[0] if found else None

    def search(
        self, owner: str, text: str, vector: Sequence[float], *, filters: SearchFilter | None = None, limit: int = 50
    ) -> list[SearchHit]:
        where = " AND ".join(w for w in (f"owner = {_q(owner)}", _where(filters)) if w)
        if self._table.count_rows(where) == 0:
            return []
        hybrid = cast(LanceHybridQueryBuilder, self._table.search(query_type="hybrid", fts_columns="fts_text"))
        query = hybrid.vector(list(vector)).text(text).distance_type("cosine").where(where, prefilter=True)
        rows = query.rerank(LinearCombinationReranker(weight=self._vector_weight)).limit(limit).to_arrow().to_pylist()
        return [SearchHit(chunk=Chunk.model_validate(r), score=r["_relevance_score"]) for r in rows]
