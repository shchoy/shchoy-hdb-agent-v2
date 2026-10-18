"""`LLMClient`: the only path to Claude. It is the test seam and the on-prem swap point."""

from __future__ import annotations

import asyncio
import itertools
import re
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict

import httpx2
from anthropic import AsyncAnthropic
from langsmith import traceable

from plg.config import Settings, Tier


class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: str


AgentMessage = dict[str, Any]
"""A Messages API message whose content may be a list of blocks (tool_use, tool_result, search_result, ...)."""

Block = dict[str, Any]
"""A Messages API content block, as JSON."""


@dataclass
class AgentTurn:
    """One complete Claude reply: its content blocks (text, possibly cited, and tool_use) and why it stopped."""

    content: list[Block]
    stop_reason: str


class LLMClient(Protocol):
    def stream_text(
        self, *, node: str, tier: Tier, system: str, messages: list[Message]
    ) -> AsyncIterator[str]:
        """Stream the text of one Claude reply. `node` names the graph node making the call."""
        ...

    async def complete(
        self,
        *,
        node: str,
        tier: Tier,
        system: list[Block],
        messages: list[AgentMessage],
        tools: list[Block],
        tool_choice: Block | None = None,
    ) -> AgentTurn:
        """One whole Claude reply that may call tools. System and tools are passed as blocks, cache marks included."""
        ...


def _join_text(chunks: Sequence[Any]) -> dict[Any, Any]:
    return {"output": "".join(chunks)}


def _drop_self(inputs: dict[Any, Any]) -> dict[Any, Any]:
    return {k: v for k, v in inputs.items() if k != "self"}


class AnthropicLLMClient:
    """Native Anthropic SDK client. Each call is traced to LangSmith as an `llm` run.

    Streaming is traced with `@traceable` rather than `wrap_anthropic`: langsmith 0.14.8's
    stream reducer is incompatible with anthropic 1.13 (`accumulate_event` needs `json_bufs`).
    """

    def __init__(self, settings: Settings, http_client: httpx2.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = AsyncAnthropic(http_client=http_client)

    @traceable(
        run_type="llm", name="ChatAnthropic", reduce_fn=_join_text, process_inputs=_drop_self
    )
    async def stream_text(
        self, *, node: str, tier: Tier, system: str, messages: list[Message]
    ) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self._settings.model_for(tier),
            max_tokens=self._settings.max_tokens,
            system=system,
            messages=messages,  # type: ignore[arg-type]
        ) as stream:
            async for text in stream.text_stream:
                yield text

    @traceable(run_type="llm", name="ChatAnthropic", process_inputs=_drop_self)
    async def complete(
        self,
        *,
        node: str,
        tier: Tier,
        system: list[Block],
        messages: list[AgentMessage],
        tools: list[Block],
        tool_choice: Block | None = None,
    ) -> AgentTurn:
        extra: dict[str, Any] = {"tool_choice": tool_choice} if tool_choice else {}
        response = await self._client.messages.create(
            model=self._settings.model_for(tier),
            max_tokens=self._settings.max_tokens,
            system=system,  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
            **extra,
        )
        return AgentTurn(
            content=[b.model_dump(mode="json", exclude_none=True) for b in response.content],
            stop_reason=response.stop_reason or "end_turn",
        )


@dataclass
class ScriptedReply:
    """A canned reply: tokens streamed in order, then optionally an error raised mid-stream."""

    tokens: list[str]
    error: Exception | None = None
    delay: float = 0.0


_tool_ids = itertools.count(1)


def tool_call(name: str, **tool_input: Any) -> Block:
    """A scripted tool_use block."""
    return {"type": "tool_use", "id": f"toolu_{next(_tool_ids):04d}", "name": name, "input": tool_input}


def text(content: str, *citations: Block) -> Block:
    """A scripted text block, optionally carrying citations."""
    block: Block = {"type": "text", "text": content}
    if citations:
        block["citations"] = list(citations)
    return block


def turn(*blocks: Block) -> AgentTurn:
    """A scripted reply. It stops for tool use if any block calls a tool."""
    tool_use = any(b["type"] == "tool_use" for b in blocks)
    return AgentTurn(content=list(blocks), stop_reason="tool_use" if tool_use else "end_turn")


ScriptedTurn = AgentTurn | Callable[[list[AgentMessage]], AgentTurn]
"""A canned reply, or one computed from what Claude was sent (e.g. to cite a search result it was shown)."""


def _latest_question(messages: Sequence[AgentMessage]) -> str:
    """The latest user message written as plain text, i.e. the question rather than tool results."""
    return str(next(m["content"] for m in reversed(messages) if m["role"] == "user" and isinstance(m["content"], str)))


@dataclass
class ScriptedLLMClient:
    """Deterministic `LLMClient` for tests, keyed by node and the latest user message."""

    replies: dict[tuple[str, str], ScriptedReply] = field(default_factory=dict)
    turns: dict[tuple[str, str], list[ScriptedTurn]] = field(default_factory=dict)
    # The messages sent on each call, in order: what Claude would have been asked.
    sent: list[list[AgentMessage]] = field(default_factory=list)
    # The system blocks and tools sent on each `complete` call, in order.
    requests: list[tuple[list[Block], list[Block]]] = field(default_factory=list)

    def script(
        self,
        node: str,
        user_input: str,
        reply: str,
        *,
        error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        tokens = re.findall(r"\s*\S+", reply)
        self.replies[(node, user_input)] = ScriptedReply(tokens, error, delay)

    def script_turns(self, node: str, user_input: str, *turns: ScriptedTurn) -> None:
        """Replies to successive `complete` calls from `node` while it handles `user_input`."""
        self.turns[(node, user_input)] = list(turns)

    async def complete(
        self,
        *,
        node: str,
        tier: Tier,
        system: list[Block],
        messages: list[AgentMessage],
        tools: list[Block],
        tool_choice: Block | None = None,
    ) -> AgentTurn:
        self.sent.append(list(messages))
        self.requests.append((system, tools))
        user_input = _latest_question(messages)
        pending = self.turns.get((node, user_input))
        if not pending:
            raise LookupError(f"No scripted turn for node={node!r} input={user_input!r}")
        reply = pending.pop(0)
        return reply if isinstance(reply, AgentTurn) else reply(messages)

    async def stream_text(
        self, *, node: str, tier: Tier, system: str, messages: list[Message]
    ) -> AsyncIterator[str]:
        self.sent.append(list(messages))  # type: ignore[arg-type]
        user_input = _latest_question(messages)  # type: ignore[arg-type]
        try:
            reply = self.replies[(node, user_input)]
        except KeyError:
            raise LookupError(f"No scripted reply for node={node!r} input={user_input!r}") from None
        for token in reply.tokens:
            if reply.delay:
                await asyncio.sleep(reply.delay)
            yield token
        if reply.error is not None:
            raise reply.error
