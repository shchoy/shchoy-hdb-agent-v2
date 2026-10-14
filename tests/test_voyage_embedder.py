"""The real Voyage AI embedder against a fake embeddings endpoint: model, dimension and input types."""

from __future__ import annotations

import json

import httpx2
import pytest

from plg.config import Settings
from plg.search.embed import VoyageEmbedder


@pytest.fixture
def requests() -> list[httpx2.Request]:
    return []


@pytest.fixture
def embedder(requests: list[httpx2.Request]) -> VoyageEmbedder:
    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        texts = json.loads(request.content)["input"]
        # Return out of order: the client must restore input order from `index`.
        data = [{"object": "embedding", "index": i, "embedding": [float(i), 0.5]} for i in range(len(texts))]
        return httpx2.Response(200, json={"object": "list", "data": data[::-1], "model": "m"})

    settings = Settings(embed_model="voyage-test", embed_dim=2, voyage_base_url="https://voyage.test/v1")
    return VoyageEmbedder(settings, "vk-test", httpx2.Client(transport=httpx2.MockTransport(handler)))


def test_documents_are_embedded_in_batches_in_input_order(
    embedder: VoyageEmbedder, requests: list[httpx2.Request]
) -> None:
    vectors = embedder.embed_documents([f"chunk {i}" for i in range(70)])

    assert [v[0] for v in vectors] == [float(i) for i in range(64)] + [float(i) for i in range(6)]
    bodies = [json.loads(r.content) for r in requests]
    assert [len(b["input"]) for b in bodies] == [64, 6]
    assert {(b["model"], b["input_type"], b["output_dimension"]) for b in bodies} == {("voyage-test", "document", 2)}
    assert {str(r.url) for r in requests} == {"https://voyage.test/v1/embeddings"}
    assert {r.headers["authorization"] for r in requests} == {"Bearer vk-test"}


def test_queries_use_the_query_input_type(embedder: VoyageEmbedder, requests: list[httpx2.Request]) -> None:
    assert embedder.embed_query("when is an LOD issued?") == [0.0, 0.5]
    assert json.loads(requests[0].content)["input_type"] == "query"


def test_an_api_error_is_raised(requests: list[httpx2.Request]) -> None:
    client = httpx2.Client(transport=httpx2.MockTransport(lambda r: httpx2.Response(401, json={"detail": "bad key"})))
    embedder = VoyageEmbedder(Settings(), "wrong", client)

    with pytest.raises(httpx2.HTTPStatusError):
        embedder.embed_query("hello")
