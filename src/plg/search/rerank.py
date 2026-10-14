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


class Retriever(Protocol):
    """What agents search through: `Searcher`, or a stand-in."""

    def search(self, query: str, *, filters: SearchFilter | None = None, k: int = 8) -> list[SearchHit]: ...


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


def open_searcher(settings: Settings) -> Searcher:
    """The `plg sync` index, Voyage query embeddings and the local cross-encoder."""
    import os

    from plg.search.embed import VoyageEmbedder
    from plg.search.lance import LanceSearchStore

    api_key = os.environ.get("VOYAGE_API_KEY")
    if not api_key:
        raise RuntimeError("VOYAGE_API_KEY is not set. Add it to .env at the repo root.")
    embedder = VoyageEmbedder(settings, api_key)
    store = LanceSearchStore(settings.search_db, dim=embedder.dim, vector_weight=settings.vector_weight)
    return Searcher(store, embedder, CrossEncoderReranker(settings), candidates=settings.search_candidates)


class LazySearcher:
    """Opens the real searcher on first search, so plg-api starts (and prints OpenAPI) without the index or keys."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._searcher: Searcher | None = None

    def search(self, query: str, *, filters: SearchFilter | None = None, k: int = 8) -> list[SearchHit]:
        self._searcher = self._searcher or open_searcher(self._settings)
        return self._searcher.search(query, filters=filters, k=k)
