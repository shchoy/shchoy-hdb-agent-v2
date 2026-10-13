"""HTTP-seam harness: an in-process plg-api driven by a scripted LLMClient."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from plg.api.app import create_app
from plg.config import Settings
from plg.llm import ScriptedLLMClient


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


@dataclass
class Api:
    client: TestClient

    def create_thread(self) -> str:
        response = self.client.post("/threads")
        assert response.status_code == 201
        return str(response.json()["thread_id"])

    def run(self, thread_id: str, message: str) -> SseStream:
        with self.client.stream("POST", f"/threads/{thread_id}/runs", json={"message": message}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            return parse_sse(r.read().decode())


@pytest.fixture
def llm() -> ScriptedLLMClient:
    return ScriptedLLMClient()


@pytest.fixture
def make_api(llm: ScriptedLLMClient) -> Iterator[Callable[..., Api]]:
    clients: list[TestClient] = []

    def factory(**settings: object) -> Api:
        client = TestClient(create_app(Settings(**settings), llm=llm))  # type: ignore[arg-type]
        clients.append(client.__enter__())
        return Api(client)

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def api(make_api: Callable[..., Api]) -> Api:
    return make_api()
