"""The real LLMClient against a fake Anthropic Messages endpoint: model IDs come from config."""

from __future__ import annotations

import asyncio
import json

import httpx2
import pytest

from plg.config import Settings
from plg.llm import AnthropicLLMClient


def anthropic_sse(*texts: str) -> bytes:
    events: list[tuple[str, dict[str, object]]] = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_1", "type": "message", "role": "assistant", "model": "m", "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        *[("content_block_delta", {"type": "content_block_delta", "index": 0,
                                   "delta": {"type": "text_delta", "text": t}}) for t in texts],
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta",
                           "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": len(texts)}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events).encode()


@pytest.fixture
def requests() -> list[dict[str, object]]:
    return []


@pytest.fixture
def http_client(requests: list[dict[str, object]]) -> httpx2.AsyncClient:
    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(
            200, content=anthropic_sse("Hello", ", officer."),
            headers={"content-type": "text/event-stream"},
        )

    return httpx2.AsyncClient(transport=httpx2.MockTransport(handler))


def collect(client: AnthropicLLMClient, tier: str) -> str:
    async def run() -> str:
        parts = [t async for t in client.stream_text(
            node="merge", tier=tier, system="sys",  # type: ignore[arg-type]
            messages=[{"role": "user", "content": "hello"}],
        )]
        return "".join(parts)

    return asyncio.run(run())


def test_streams_text_using_the_configured_model_for_each_tier(
    monkeypatch: pytest.MonkeyPatch, http_client: httpx2.AsyncClient,
    requests: list[dict[str, object]],
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("PLG_MODEL_SONNET", "claude-sonnet-custom")
    client = AnthropicLLMClient(Settings.from_env(), http_client=http_client)

    assert collect(client, "sonnet") == "Hello, officer."
    assert collect(client, "haiku") == "Hello, officer."
    assert collect(client, "opus") == "Hello, officer."
    assert [r["model"] for r in requests] == [
        "claude-sonnet-custom", "claude-haiku-5-5", "claude-opus-5-5",
    ]
