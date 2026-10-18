"""StateGraph wiring: START → route → specialists (fan-out) → merge → END.

`route` (Haiku) decides which specialists a question needs; none means `merge` answers it directly.
`merge` fuses the specialists' findings into one answer and is the only node that streams tokens.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Sequence

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from plg.agents import knowledge
from plg.agents.runtime import CACHE
from plg.entities.store import GraphStore
from plg.graph.state import Finding, Intent, PLGGraph, PLGState
from plg.llm import AgentMessage, Block, LLMClient, Message
from plg.ontology.vocab import VocabIndex, load_vocab
from plg.search.rerank import Retriever

ROUTE = "route"
KNOWLEDGE = knowledge.NODE
MERGE = "merge"

ROUTE_SYSTEM = """\
You route questions from officers of the Properties & Land Group (PLG) to specialists.
- knowledge: anything answered from PLG's documents and records, including what is known about a tenant, unit or tenancy: policies, SOPs, circulars, procedures, \
rules, limits, deadlines, what a PLG term means, audit findings, incidents, letters, emails and notes.
Choose no specialist for greetings, thanks and questions about how to use the assistant."""

ROUTE_TOOL: Block = {
    "name": ROUTE,
    "description": "Send the question to the specialists that can answer it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intents": {
                "type": "array", "items": {"type": "string", "enum": ["knowledge"]},
                "description": "The specialists needed; empty if none.",
            }
        },
        "required": ["intents"],
    },
    "cache_control": CACHE,
}

MERGE_SYSTEM = (
    "You are the PLG Super-Librarian, an assistant for officers of the Properties & Land Group. "
    "Answer clearly and concisely using PLG's own terms."
)

MERGE_FINDINGS = """
Answer the officer's question from the specialists' findings below, and only from them. Keep each citation \
marker such as [1] right after the claim it supports, exactly as written; never add, renumber or drop one. \
Do not add facts the findings don't contain.

{findings}"""

MERGE_NO_SOURCES = """
No specialist searched PLG's sources for this message. Don't state PLG policies, rules, figures, dates or \
records from memory; if the officer asks about them, say you couldn't look that up and ask them to rephrase it \
as a question about PLG's documents."""

NOT_COVERED = (
    "The indexed PLG sources don't cover this question, so I can't give you a sourced answer. "
    "Try rephrasing it, or check with the policy owner."
)


class RouteDecision(BaseModel):
    intents: list[Intent]


def build_graph(
    llm: LLMClient, retriever: Retriever, vocab: VocabIndex | None = None, entities: GraphStore | None = None
) -> PLGGraph:
    vocab = vocab or load_vocab()

    def conversation(state: PLGState) -> list[Message]:
        return [*state.get("messages", []), {"role": "user", "content": state["question"]}]

    def agent_conversation(state: PLGState) -> list[AgentMessage]:
        return [{"role": m["role"], "content": m["content"]} for m in conversation(state)]

    async def route(state: PLGState) -> PLGState:
        reply = await llm.complete(
            node=ROUTE,
            tier="haiku",
            system=[{"type": "text", "text": ROUTE_SYSTEM, "cache_control": CACHE}],
            messages=agent_conversation(state),
            tools=[ROUTE_TOOL],
            tool_choice={"type": "tool", "name": ROUTE},
        )
        call = next(b for b in reply.content if b["type"] == "tool_use")
        decision = RouteDecision.model_validate(call["input"])
        return {"intents": list(dict.fromkeys(decision.intents)), "findings": []}

    def fan_out(state: PLGState) -> Sequence[str]:
        return state.get("intents") or [MERGE]

    async def knowledge_node(state: PLGState) -> PLGState:
        result = await knowledge.answer(llm, retriever, vocab, agent_conversation(state), state["question"], entities)
        write = get_stream_writer()
        for n, citation in enumerate(result.citations, start=1):
            write({"citation": citation.model_dump(), "index": n})
        return {"findings": [Finding(specialist=KNOWLEDGE, text=result.text, citations=result.citations)]}

    async def merge(state: PLGState) -> PLGState:
        write = get_stream_writer()
        findings = state.get("findings", [])
        parts: list[str] = []
        async for text in _fuse(llm, conversation(state), findings):
            parts.append(text)
            write({"node": MERGE, "token": text})
        answer = "".join(parts)
        question: Message = {"role": "user", "content": state["question"]}
        return {"answer": answer, "messages": [question, {"role": "assistant", "content": answer}]}

    graph = StateGraph(PLGState)
    graph.add_node(ROUTE, route)
    graph.add_node(KNOWLEDGE, knowledge_node)
    graph.add_node(MERGE, merge)
    graph.add_edge(START, ROUTE)
    graph.add_conditional_edges(ROUTE, fan_out, [KNOWLEDGE, MERGE])
    graph.add_edge(KNOWLEDGE, MERGE)
    graph.add_edge(MERGE, END)
    return graph.compile(checkpointer=InMemorySaver())


async def _fuse(llm: LLMClient, messages: list[Message], findings: list[Finding]) -> AsyncIterator[str]:
    """The answer's tokens. Findings without a single citation are not an answer: say the sources don't
    cover the question rather than let Claude fill the gap."""
    if findings and not any(f.citations for f in findings):
        for token in re.findall(r"\s*\S+", NOT_COVERED):
            yield token
        return
    if findings:
        blocks = "\n\n".join(f"<{f.specialist}>\n{f.text}\n</{f.specialist}>" for f in findings)
        system = MERGE_SYSTEM + MERGE_FINDINGS.format(findings=blocks)
    else:
        system = MERGE_SYSTEM + MERGE_NO_SOURCES
    async for text in llm.stream_text(node=MERGE, tier="sonnet", system=system, messages=messages):
        yield text
