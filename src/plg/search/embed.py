"""`Embedder`: text -> vectors. Voyage AI for real; a hashing embedder for offline tests."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Literal, Protocol

import httpx2

from plg.config import Settings


class Embedder(Protocol):
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class VoyageEmbedder:
    """Voyage AI embeddings over its REST API. Documents and queries use different input types."""

    batch_size = 64

    def __init__(self, settings: Settings, api_key: str, http_client: httpx2.Client | None = None) -> None:
        self.dim = settings.embed_dim
        self._model = settings.embed_model
        self._url = f"{settings.voyage_base_url.rstrip('/')}/embeddings"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._http = http_client or httpx2.Client(timeout=60.0)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed(texts[start : start + self.batch_size], "document"))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]

    def _embed(self, texts: Sequence[str], input_type: Literal["document", "query"]) -> list[list[float]]:
        response = self._http.post(
            self._url,
            headers=self._headers,
            json={
                "model": self._model,
                "input": list(texts),
                "input_type": input_type,
                "output_dimension": self.dim,
            },
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda d: d["index"])
        return [[float(x) for x in d["embedding"]] for d in data]


class HashingEmbedder:
    """Deterministic bag-of-words feature hashing. No network: for tests and offline runs only."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for word in re.findall(r"[a-z0-9]+", text.casefold()):
            digest = hashlib.blake2b(word.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dim
            vector[bucket] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]
