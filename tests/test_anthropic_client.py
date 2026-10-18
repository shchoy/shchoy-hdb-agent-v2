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


def test_complete_sends_cached_system_and_tools_and_returns_cited_text_and_tool_calls(
    monkeypatch: pytest.MonkeyPatch, requests: list[dict[str, object]],
) -> None:
    citation = {
        "type": "search_result_location", "source": "DOC#004", "title": "POL-003", "cited_text": "60 days.",
        "search_result_index": 0, "start_block_index": 1, "end_block_index": 2,
    }
    message = {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "m",
        "content": [
            {"type": "text", "text": "At 60 days.", "citations": [citation]},
            {"type": "tool_use", "id": "toolu_1", "name": "search_corpus", "input": {"query": "LOD"}},
        ],
        "stop_reason": "tool_use", "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        return httpx2.Response(200, json=message)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = AnthropicLLMClient(
        Settings.from_env(), http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    system = [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}]
    tools = [{"name": "search_corpus", "description": "d", "input_schema": {"type": "object"},
              "cache_control": {"type": "ephemeral"}}]

    reply = asyncio.run(client.complete(
        node="knowledge", tier="sonnet", system=system, messages=[{"role": "user", "content": "LOD?"}],
        tools=tools, tool_choice={"type": "tool", "name": "search_corpus"},
    ))

    assert reply.stop_reason == "tool_use"
    assert reply.content[0]["citations"] == [citation]
    assert reply.content[1]["input"] == {"query": "LOD"}
    sent = requests[0]
    assert sent["model"] == "claude-sonnet-5-5"
    assert sent["system"] == system
    assert sent["tools"] == tools
    assert sent["tool_choice"] == {"type": "tool", "name": "search_corpus"}
