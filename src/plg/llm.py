"""`LLMClient`: the only path to Claude. It is the test seam and the on-prem swap point."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict

import httpx2
from anthropic import AsyncAnthropic
from langsmith import traceable

from plg.config import Settings, Tier


class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class LLMClient(Protocol):
    def stream_text(
        self, *, node: str, tier: Tier, system: str, messages: list[Message]
    ) -> AsyncIterator[str]:
        """Stream the text of one Claude reply. `node` names the graph node making the call."""
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


@dataclass
class ScriptedReply:
    """A canned reply: tokens streamed in order, then optionally an error raised mid-stream."""

    tokens: list[str]
    error: Exception | None = None
    delay: float = 0.0


@dataclass
class ScriptedLLMClient:
    """Deterministic `LLMClient` for tests, keyed by node and the latest user message."""

    replies: dict[tuple[str, str], ScriptedReply] = field(default_factory=dict)
    # The messages sent on each call, in order: what Claude would have been asked.
    sent: list[list[Message]] = field(default_factory=list)

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

    async def stream_text(
        self, *, node: str, tier: Tier, system: str, messages: list[Message]
    ) -> AsyncIterator[str]:
        self.sent.append(list(messages))
        user_input = next(m["content"] for m in reversed(messages) if m["role"] == "user")
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
