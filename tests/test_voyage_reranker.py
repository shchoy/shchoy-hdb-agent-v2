"""The Voyage AI reranker against a fake rerank endpoint: request shape, score mapping and fallback on errors."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx2
import pytest

from plg.config import Settings
from plg.search.models import Chunk, SearchHit
from plg.search.rerank import CrossEncoderReranker, VoyageReranker, make_reranker


def hit(chunk_id: str, score: float) -> SearchHit:
    chunk = Chunk(
        doc_id="D1", doc_type="policy", title="Policy", source_system="sharepoint", source_path="p.docx",
        content_hash="h", chunk_id=chunk_id, seq=0, header=f"header {chunk_id}", text=f"text {chunk_id}",
        location="1", vector=[0.0],
    )
    return SearchHit(chunk=chunk, score=score)


@pytest.fixture
def requests() -> list[httpx2.Request]:
    return []


def reranker_with(
    handler: Callable[[httpx2.Request], httpx2.Response], requests: list[httpx2.Request]
) -> VoyageReranker:
    def recording(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return handler(request)

    settings = Settings(voyage_rerank_model="rerank-test", voyage_base_url="https://voyage.test/v1")
    return VoyageReranker(settings, "vk-test", httpx2.Client(transport=httpx2.MockTransport(recording)))


def test_hits_are_rescored_by_relevance_and_sorted_best_first(requests: list[httpx2.Request]) -> None:
    # Voyage returns results best first, each pointing at its document by index.
    def handler(request: httpx2.Request) -> httpx2.Response:
        results = [{"index": 2, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.4},
                   {"index": 1, "relevance_score": 0.1}]
        return httpx2.Response(200, json={"object": "list", "data": results, "model": "m"})

    hits = [hit("a", 5.0), hit("b", 4.0), hit("c", 3.0)]

    reranked = reranker_with(handler, requests).rerank("when is an LOD issued?", hits)

    assert [(h.chunk.chunk_id, h.score) for h in reranked] == [("c", 0.9), ("a", 0.4), ("b", 0.1)]
    body = json.loads(requests[0].content)
    assert body["query"] == "when is an LOD issued?"
    assert body["documents"] == ["header a\ntext a", "header b\ntext b", "header c\ntext c"]
    assert body["model"] == "rerank-test"
    assert str(requests[0].url) == "https://voyage.test/v1/rerank"
    assert requests[0].headers["authorization"] == "Bearer vk-test"


def test_no_hits_makes_no_request(requests: list[httpx2.Request]) -> None:
    reranker = reranker_with(lambda r: httpx2.Response(500), requests)

    assert reranker.rerank("anything", []) == []
    assert requests == []


@pytest.mark.parametrize("status", [429, 500])
def test_an_api_error_falls_back_to_the_hybrid_order(status: int, requests: list[httpx2.Request]) -> None:
    reranker = reranker_with(lambda r: httpx2.Response(status, json={"detail": "nope"}), requests)
    hits = [hit("a", 5.0), hit("b", 4.0)]

    assert reranker.rerank("q", hits) == hits


def test_a_network_error_falls_back_to_the_hybrid_order(requests: list[httpx2.Request]) -> None:
    def down(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("unreachable")

    hits = [hit("a", 5.0), hit("b", 4.0)]

    assert reranker_with(down, requests).rerank("q", hits) == hits


def test_the_backend_is_chosen_with_plg_rerank_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLG_RERANK_BACKEND", raising=False)
    assert Settings.from_env().rerank_backend == "voyage"

    monkeypatch.setenv("PLG_RERANK_BACKEND", "local")
    assert Settings.from_env().rerank_backend == "local"


def test_make_reranker_builds_the_configured_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOYAGE_API_KEY", "vk-test")

    assert isinstance(make_reranker(Settings(rerank_backend="voyage")), VoyageReranker)
    assert isinstance(make_reranker(Settings(rerank_backend="local")), CrossEncoderReranker)


def test_the_voyage_backend_needs_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="VOYAGE_API_KEY"):
        make_reranker(Settings(rerank_backend="voyage"))


@pytest.mark.parametrize(
    "body",
    [{"data": [{"index": 7, "relevance_score": 0.5}]}, {"unexpected": []}, {"data": [{"index": 0}]}],
)
def test_a_malformed_response_falls_back_to_the_hybrid_order(body: dict[str, object], requests: list[httpx2.Request]) -> None:
    hits = [hit("a", 5.0), hit("b", 4.0)]

    assert reranker_with(lambda r: httpx2.Response(200, json=body), requests).rerank("q", hits) == hits
