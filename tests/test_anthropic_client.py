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


def test_calls_are_traced_as_llm_runs_naming_node_and_tier_under_the_run(
    monkeypatch: pytest.MonkeyPatch, http_client: httpx2.AsyncClient,
) -> None:
    from tests.conftest import LangSmithApi

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    langsmith = LangSmithApi()
    tracer = langsmith.tracer()
    client = AnthropicLLMClient(Settings.from_env(), http_client=http_client)

    with tracer.run("0193a3c2-0000-7000-8000-000000000001", thread_id="t-1", user=None, channel="cli", inputs={}):
        assert collect(client, "haiku") == "Hello, officer."

    (llm_run,) = [r for r in langsmith.runs().values() if r.get("run_type") == "llm"]
    meta = llm_run["extra"]["metadata"]
    assert (meta["node"], meta["tier"], meta["thread_id"], meta["ls_model_name"]) == ("merge", "haiku", "t-1", "claude-haiku-5-5")
    assert llm_run["parent_run_id"] == "0193a3c2-0000-7000-8000-000000000001"
    assert "Hello, officer." in json.dumps(llm_run["outputs"])


def test_a_model_that_rejects_a_forced_tool_choice_is_asked_with_auto_and_nudged_once_to_call_the_tool(
    monkeypatch: pytest.MonkeyPatch, requests: list[dict[str, object]],
) -> None:
    """Sonnet/Opus 5.5 reject tool_choice "tool"/"any" (400): the call falls back to "auto" with the system prompt
    insisting on the tool, asks once more if the reply is plain text, and remembers the model so later calls skip the 400."""
    rejected = {"type": "error", "error": {"type": "invalid_request_error",
                "message": 'tool_choice: type "tool" and "any" are not supported for this model.'}}

    def message(*content: dict[str, object]) -> dict[str, object]:
        return {"id": "msg_1", "type": "message", "role": "assistant", "model": "m", "content": list(content),
                "stop_reason": "tool_use" if content[-1]["type"] == "tool_use" else "end_turn",
                "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}

    grade = {"type": "tool_use", "id": "toolu_1", "name": "grade", "input": {"score": 1}}

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        requests.append(body)
        if body.get("tool_choice", {}).get("type") in ("tool", "any"):
            return httpx2.Response(400, json=rejected)
        if len(body["messages"]) == 1 and len(requests) == 2:
            return httpx2.Response(200, json=message({"type": "text", "text": "I think it is correct."}))
        return httpx2.Response(200, json=message(grade))

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = AnthropicLLMClient(
        Settings.from_env(), http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    system = [{"type": "text", "text": "Grade it.", "cache_control": {"type": "ephemeral"}}]
    tools = [{"name": "grade", "description": "d", "input_schema": {"type": "object"}}]

    def ask() -> object:
        return asyncio.run(client.complete(
            node="eval_judge", tier="opus", system=system, messages=[{"role": "user", "content": "Q?"}],
            tools=tools, tool_choice={"type": "tool", "name": "grade"},
        ))

    reply = ask()

    assert reply.content == [grade] and reply.stop_reason == "tool_use"  # type: ignore[attr-defined]
    forced, auto, nudge = requests
    assert forced["tool_choice"] == {"type": "tool", "name": "grade"}
    assert auto["tool_choice"] == nudge["tool_choice"] == {"type": "auto"}
    assert auto["system"][0] == system[0] and "grade tool" in auto["system"][-1]["text"]  # type: ignore[index]
    assert nudge["messages"][1]["role"] == "assistant" and "grade tool" in json.dumps(nudge["messages"][2])  # type: ignore[index]

    requests.clear()
    assert ask().content == [grade]  # type: ignore[attr-defined]
    assert [r["tool_choice"] for r in requests] == [{"type": "auto"}]
