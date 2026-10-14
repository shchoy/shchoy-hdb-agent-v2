"""`run_agent`: the tool-use loop every agent node runs. Its scratchpad is discarded when the node finishes;
only the compact `AgentResult` (answer text with citation markers, and the citations) leaves it.

Tools are read-only. A search tool returns `Source`s; they reach Claude as `search_result` blocks with
citations enabled, so every claim Claude cites points at whole sentences of a chunk the run actually retrieved.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from plg.config import Tier
from plg.llm import AgentMessage, Block, LLMClient
from plg.search.models import Chunk

MAX_TURNS = 8
"""Tool rounds before an agent must answer. A loop that runs past it fails the run rather than spinning."""

CACHE: Block = {"type": "ephemeral"}


class Span(BaseModel):
    """Character offsets into the chunk's text: `text[start:end]` is the cited quote."""

    start: int
    end: int


class Citation(BaseModel):
    """A claim's source: the exact span of one chunk, and where to find it in the document."""

    doc_id: str
    chunk_id: str
    title: str
    version: str | None
    location: str
    quote: str
    span: Span


class AgentResult(BaseModel):
    text: str
    """The answer, with `[n]` after each cited passage; `n` is the 1-based position in `citations`."""
    citations: list[Citation]


@dataclass
class Source:
    """A retrieved chunk, as shown to Claude: titled, and split into sentences so citations are exact spans."""

    chunk: Chunk
    title: str
    sentences: list[tuple[int, int]] = field(init=False)

    def __post_init__(self) -> None:
        self.sentences = sentence_spans(self.chunk.text)

    def block(self) -> Block:
        return {
            "type": "search_result",
            "source": self.chunk.chunk_id,
            "title": self.title,
            "content": [{"type": "text", "text": self.chunk.text[s:e]} for s, e in self.sentences],
            "citations": {"enabled": True},
        }


ToolOutput = str | list[Source]


@dataclass
class Tool:
    """A read-only tool: its Messages API definition, and the function that runs it."""

    name: str
    description: str
    input_schema: dict[str, Any]
    run: Callable[[dict[str, Any]], Awaitable[ToolOutput]]

    def definition(self) -> Block:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence or line of `text`, without surrounding whitespace."""
    spans = []
    for m in re.finditer(r"[^\n]+?(?:[.!?](?=\s)|$)", text, flags=re.MULTILINE):
        start, end = m.start(), m.end()
        while start < end and text[start].isspace():
            start += 1
        if start < end:
            spans.append((start, end))
    return spans or [(0, len(text))]


async def run_agent(
    llm: LLMClient,
    *,
    node: str,
    system: str,
    context: str = "",
    tools: Sequence[Tool],
    messages: list[AgentMessage],
    tier: Tier = "sonnet",
) -> AgentResult:
    """Loop while Claude asks for tools, running each round's calls in parallel.

    The system prompt and tool definitions are marked for prompt caching; `context` is per-run system
    text placed after the cache mark.
    """
    system_blocks: list[Block] = [{"type": "text", "text": system, "cache_control": CACHE}]
    if context:
        system_blocks.append({"type": "text", "text": context})
    definitions = [t.definition() for t in tools]
    if definitions:
        definitions[-1] = {**definitions[-1], "cache_control": CACHE}
    by_name = {t.name: t for t in tools}
    retrieved: dict[str, Source] = {}
    scratchpad = list(messages)

    for _ in range(MAX_TURNS):
        reply = await llm.complete(node=node, tier=tier, system=system_blocks, messages=scratchpad, tools=definitions)
        calls = [b for b in reply.content if b["type"] == "tool_use"]
        if reply.stop_reason != "tool_use" or not calls:
            return _result(reply.content, retrieved)
        outputs = await asyncio.gather(*(_call(by_name, c) for c in calls))
        results: list[Block] = []
        for call, output in zip(calls, outputs, strict=True):
            if isinstance(output, str):
                content: str | list[Block] = output
            else:
                retrieved.update((s.chunk.chunk_id, s) for s in output)
                content = [s.block() for s in output] or "No matching sources."
            results.append({"type": "tool_result", "tool_use_id": call["id"], "content": content})
        scratchpad += [{"role": "assistant", "content": reply.content}, {"role": "user", "content": results}]
    raise RuntimeError(f"{node} did not answer within {MAX_TURNS} tool rounds")


async def _call(tools: dict[str, Tool], call: Block) -> ToolOutput:
    tool = tools.get(call["name"])
    if tool is None:
        return f"Unknown tool {call['name']!r}."
    return await tool.run(call["input"])


def _result(content: list[Block], retrieved: dict[str, Source]) -> AgentResult:
    """The final text with `[n]` markers, keeping only citations of chunks this run retrieved."""
    citations: list[Citation] = []
    parts: list[str] = []
    for block in content:
        if block["type"] != "text":
            continue
        parts.append(block["text"])
        markers: list[int] = []
        for raw in block.get("citations") or []:
            citation = _citation(raw, retrieved)
            if citation is None:
                continue
            if citation not in citations:
                citations.append(citation)
            n = citations.index(citation) + 1
            if n not in markers:
                markers.append(n)
        if markers:
            parts.append(" " + "".join(f"[{n}]" for n in markers))
    return AgentResult(text="".join(parts).strip(), citations=citations)


def _citation(raw: Block, retrieved: dict[str, Source]) -> Citation | None:
    source = retrieved.get(raw.get("source", ""))
    if raw.get("type") != "search_result_location" or source is None:
        return None
    start, end = raw["start_block_index"], raw["end_block_index"]
    if not 0 <= start < end <= len(source.sentences):
        return None
    span = Span(start=source.sentences[start][0], end=source.sentences[end - 1][1])
    chunk = source.chunk
    return Citation(
        doc_id=chunk.doc_id, chunk_id=chunk.chunk_id, title=chunk.title, version=chunk.version,
        location=chunk.location, quote=chunk.text[span.start:span.end], span=span,
    )
