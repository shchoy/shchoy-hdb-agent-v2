"""`LLMClient`: the only path to Claude. It is the test seam and the on-prem swap point."""

from __future__ import annotations

import asyncio
import itertools
import re
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Literal, NamedTuple, Protocol, TypedDict

import httpx2
from anthropic import AsyncAnthropic, BadRequestError
from langsmith import get_tracing_context, tracing_context
from langsmith.utils import tracing_is_enabled
from langsmith.wrappers import wrap_anthropic

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
        max_tokens: int | None = None,
    ) -> AgentTurn:
        """One whole Claude reply that may call tools. System and tools are passed as blocks, cache marks included.

        `max_tokens` overrides the configured reply limit (e.g. for transcribing a long document)."""
        ...


def _traced(node: str, tier: Tier) -> AbstractContextManager[None]:
    """The Claude call's trace names the graph node and model tier (on top of the run's thread, user, ...)."""
    context = get_tracing_context()
    metadata = {**(context.get("metadata") or {}), "node": node, "tier": tier}
    return tracing_context(metadata=metadata, tags=[*(context.get("tags") or []), f"tier:{tier}"])


class AnthropicLLMClient:
    """Native Anthropic SDK client, wrapped with `wrap_anthropic`: each call is a LangSmith `llm` run (inside the
    graph run's trace when there is one) whose metadata names the graph node and model tier.

    langsmith 0.14.8's wrapper can only stream through `text_stream`, and only while tracing (untraced, it looks for
    a run that isn't there; iterating events hits `accumulate_event`'s missing `json_bufs`), so an untraced stream
    goes through the bare client."""

    def __init__(self, settings: Settings, http_client: httpx2.AsyncClient | None = None) -> None:
        self._settings = settings
        self._bare = AsyncAnthropic(http_client=http_client)
        self._client = wrap_anthropic(AsyncAnthropic(http_client=http_client))  # wraps in place: a second SDK client
        self._unforced: set[str] = set()
        """Models that rejected a forced tool_choice: later calls go straight to the "auto" fallback."""

    async def stream_text(
        self, *, node: str, tier: Tier, system: str, messages: list[Message]
    ) -> AsyncIterator[str]:
        client = self._client if tracing_is_enabled() else self._bare
        with _traced(node, tier):
            async with client.messages.stream(
                model=self._settings.model_for(tier),
                max_tokens=self._settings.max_tokens,
                system=system,
                messages=messages,  # type: ignore[arg-type]
            ) as stream:
                async for text in stream.text_stream:
                    yield text

    async def complete(
        self,
        *,
        node: str,
        tier: Tier,
        system: list[Block],
        messages: list[AgentMessage],
        tools: list[Block],
        tool_choice: Block | None = None,
        max_tokens: int | None = None,
    ) -> AgentTurn:
        model = self._settings.model_for(tier)
        forced = tool_choice is not None and tool_choice.get("type") in FORCED
        if forced and model not in self._unforced:
            try:
                return await self._create(node, tier, model, system, messages, tools, tool_choice, max_tokens)
            except BadRequestError as e:
                if "tool_choice" not in str(e):
                    raise
                self._unforced.add(model)
        if not forced:
            return await self._create(node, tier, model, system, messages, tools, tool_choice, max_tokens)
        # The model rejects a forced choice: offer the tool with "auto", insist on it, and ask once more if it answers in text.
        assert tool_choice is not None
        name = tool_choice.get("name")
        wanted = f"the {name} tool" if name else "one of the tools"
        prompt = [*system, {"type": "text", "text": f"Answer only by calling {wanted}, never in plain text."}]
        auto: Block = {"type": "auto"}
        reply = await self._create(node, tier, model, prompt, messages, tools, auto, max_tokens)
        if _calls(reply, name):
            return reply
        retry = [*messages, {"role": "assistant", "content": reply.content},
                 {"role": "user", "content": [{"type": "text", "text": f"Respond now by calling {wanted}."}]}]
        return await self._create(node, tier, model, prompt, retry, tools, auto, max_tokens)

    async def _create(
        self, node: str, tier: Tier, model: str, system: list[Block], messages: list[AgentMessage],
        tools: list[Block], tool_choice: Block | None, max_tokens: int | None,
    ) -> AgentTurn:
        extra: dict[str, Any] = {"tool_choice": tool_choice} if tool_choice else {}
        with _traced(node, tier):
            response = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens or self._settings.max_tokens,
                system=system,  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
                **extra,
            )
        return AgentTurn(
            content=[b.model_dump(mode="json", exclude_none=True) for b in response.content],
            stop_reason=response.stop_reason or "end_turn",
        )


FORCED = ("tool", "any")
"""Forced tool_choice types, which some models (Sonnet/Opus 5.5) reject with a 400."""


def _calls(turn: AgentTurn, name: str | None) -> bool:
    return any(b.get("type") == "tool_use" and (name is None or b.get("name") == name) for b in turn.content)


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
    """The latest user message written as plain text, i.e. the question rather than tool results.

    A message of blocks counts if it carries a text block and no tool results (e.g. a PDF plus an instruction)."""
    for m in reversed(messages):
        if m["role"] != "user":
            continue
        content = m["content"]
        if isinstance(content, str):
            return content
        if not any(b["type"] == "tool_result" for b in content):
            if text_block := next((b for b in content if b["type"] == "text"), None):
                return str(text_block["text"])
    raise LookupError("No plain-text user message")


class Streamed(NamedTuple):
    system: str
    messages: list[Message]


@dataclass
class ScriptedLLMClient:
    """Deterministic `LLMClient` for tests, keyed by node and the latest user message."""

    replies: dict[tuple[str, str], ScriptedReply] = field(default_factory=dict)
    turns: dict[tuple[str, str], list[ScriptedTurn]] = field(default_factory=dict)
    # The messages sent on each call, in order: what Claude would have been asked.
    sent: list[list[AgentMessage]] = field(default_factory=list)
    # The system blocks and tools sent on each `complete` call, in order.
    requests: list[tuple[list[Block], list[Block]]] = field(default_factory=list)
    tool_choices: list[Block | None] = field(default_factory=list)
    """The tool_choice of every complete() call, in order."""
    # Each `stream_text` call (the answer), in order: its system prompt and messages.
    streamed: list[Streamed] = field(default_factory=list)

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
        max_tokens: int | None = None,
    ) -> AgentTurn:
        self.sent.append(list(messages))
        self.requests.append((system, tools))
        self.tool_choices.append(tool_choice)
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
        self.streamed.append(Streamed(system, list(messages)))
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
