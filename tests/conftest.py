"""HTTP-seam harness: an in-process plg-api driven by a scripted LLMClient."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner, Result

from plg import cli
from plg.api.app import create_app
from plg.config import REPO_ROOT, Settings
from plg.llm import ScriptedLLMClient, tool_call, turn
from plg.search.embed import HashingEmbedder
from plg.search.lance import LanceSearchStore
from plg.search.models import DocumentMeta
from plg.search.rerank import CrossEncoderReranker, Searcher


@dataclass
class SseStream:
    """A received SSE stream, split into data events and heartbeat comments."""

    events: list[dict[str, object]] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)

    def of_type(self, kind: str) -> list[dict[str, object]]:
        return [e for e in self.events if e["type"] == kind]

    @property
    def text(self) -> str:
        return "".join(str(e["text"]) for e in self.of_type("token"))


def parse_sse(body: str) -> SseStream:
    stream = SseStream()
    for frame in body.replace("\r\n", "\n").split("\n\n"):
        data: list[str] = []
        for line in frame.split("\n"):
            if line.startswith(":"):
                stream.comments.append(line[1:].strip())
            elif line.startswith("data:"):
                data.append(line[5:].strip())
            elif line.startswith("id:"):
                stream.ids.append(line[3:].strip())
        if data:
            stream.events.append(json.loads("\n".join(data)))
    return stream


USER = {"X-PLG-User": "S05"}
"""A signed-in leasing officer, as forwarded by the BFF."""


@dataclass
class Api:
    client: TestClient

    def create_thread(self) -> str:
        response = self.client.post("/threads", headers=USER)
        assert response.status_code == 201
        return str(response.json()["thread_id"])

    def run(self, thread_id: str, message: str) -> SseStream:
        with self.client.stream(
            "POST", f"/threads/{thread_id}/runs", json={"message": message}, headers=USER
        ) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            return parse_sse(r.read().decode())


def route(llm: ScriptedLLMClient, question: str, *intents: str) -> None:
    """Script the router: `question` goes to these specialists (none: merge answers it directly)."""
    llm.script_turns("route", question, turn(tool_call("route", intents=list(intents))))


@pytest.fixture
def llm() -> ScriptedLLMClient:
    return ScriptedLLMClient()


@pytest.fixture
def make_api(llm: ScriptedLLMClient) -> Iterator[Callable[..., Api]]:
    clients: list[TestClient] = []

    def factory(searcher: Searcher | None = None, **settings: object) -> Api:
        app = create_app(Settings(**settings), llm=llm, searcher=searcher)  # type: ignore[arg-type]
        client = TestClient(app)
        clients.append(client.__enter__())
        return Api(client)

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def api(make_api: Callable[..., Api]) -> Api:
    return make_api()


# ---------------------------------------------------------------- search index over poc-data

CORPUS = REPO_ROOT / "poc-data"


class CountingEmbedder(HashingEmbedder):
    """The offline embedder, recording every text it is asked to embed."""

    def __init__(self) -> None:
        super().__init__(dim=128)
        self.embedded: list[str] = []

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return super().embed_documents(texts)


def run_sync(embedder: HashingEmbedder, index: Path, corpus: Path = CORPUS, *args: str) -> Result:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cli, "make_embedder", lambda settings: embedder)
        env = {"PLG_SEARCH_DB": str(index), "PLG_CORPUS_DIR": str(corpus)}
        result = CliRunner().invoke(cli.app, ["sync", *args], env=env)
    assert result.exit_code == 0, result.output
    return result


def open_store(index: Path, embedder: HashingEmbedder) -> LanceSearchStore:
    return LanceSearchStore(index, dim=embedder.dim)


def by_path(store: LanceSearchStore) -> dict[str, DocumentMeta]:
    return {d.source_path: d for d in store.documents()}


@pytest.fixture(scope="session")
def corpus_index(tmp_path_factory: pytest.TempPathFactory) -> tuple[LanceSearchStore, str]:
    """The whole poc-data corpus, synced once per test session."""
    embedder = CountingEmbedder()
    index = tmp_path_factory.mktemp("index")
    result = run_sync(embedder, index)
    return open_store(index, embedder), result.output


@pytest.fixture
def store(corpus_index: tuple[LanceSearchStore, str]) -> LanceSearchStore:
    return corpus_index[0]


@pytest.fixture(scope="session")
def reranker() -> CrossEncoderReranker:
    return CrossEncoderReranker(Settings())


@pytest.fixture
def searcher(store: LanceSearchStore, reranker: CrossEncoderReranker) -> Searcher:
    """Hybrid search with the real cross-encoder over the synced corpus, embedding queries offline."""
    return Searcher(store, HashingEmbedder(dim=128), reranker, candidates=50)


@pytest.fixture
def knowledge_api(make_api: Callable[..., Api], searcher: Searcher) -> Api:
    """plg-api whose knowledge agent searches the synced poc-data corpus."""
    return make_api(searcher=searcher)
