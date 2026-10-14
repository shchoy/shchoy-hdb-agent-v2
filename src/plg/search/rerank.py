"""Local cross-encoder rerank, and `Searcher`: embed the query, hybrid-search the store, rerank."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from plg.config import Settings
from plg.search.embed import Embedder
from plg.search.models import SearchFilter, SearchHit
from plg.search.store import SearchStore


class Reranker(Protocol):
    def rerank(self, query: str, hits: Sequence[SearchHit]) -> list[SearchHit]:
        """The hits rescored against the query, best first."""
        ...


class CrossEncoderReranker:
    """An ONNX cross-encoder run locally (fastembed). The model downloads once into the model cache."""

    def __init__(self, settings: Settings) -> None:
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self._model = TextCrossEncoder(settings.rerank_model, cache_dir=str(settings.model_cache))

    def rerank(self, query: str, hits: Sequence[SearchHit]) -> list[SearchHit]:
        if not hits:
            return []
        scores = self._model.rerank(query, [h.chunk.fts_text for h in hits])
        rescored = [h.model_copy(update={"score": float(s)}) for h, s in zip(hits, scores, strict=True)]
        return sorted(rescored, key=lambda h: h.score, reverse=True)


class Searcher:
    def __init__(
        self, store: SearchStore, embedder: Embedder, reranker: Reranker, *, candidates: int = 50
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._reranker = reranker
        self._candidates = candidates

    def search(self, query: str, *, filters: SearchFilter | None = None, k: int = 8) -> list[SearchHit]:
        candidates = self._store.search(
            query, self._embedder.embed_query(query), filters=filters, limit=self._candidates
        )
        return self._reranker.rerank(query, candidates)[:k]
