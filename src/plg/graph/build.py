"""StateGraph wiring: START → route → specialists (fan-out) → merge → END.

`route` (Haiku) decides which specialists a question needs; none means `merge` answers it directly.
`merge` fuses the specialists' findings into one answer and is the only node that streams tokens.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from plg.agents import data, drafting, knowledge
from plg.agents.runtime import CACHE
from plg.config import Settings
from plg.data.semantic import SemanticLayer, load_semantic_layer
from plg.data.warehouse import Warehouse
from plg.drafting.store import DraftStore
from plg.drafting.templates import TemplateLibrary
from plg.entities.policy import PolicyLineage
from plg.entities.store import GraphStore
from plg.graph import summary as history
from plg.graph.state import Finding, Intent, PLGGraph, PLGState
from plg.memory.service import MemoryService
from plg.llm import AgentMessage, Block, LLMClient, Message
from plg.ontology.glossary import Glossary, load_glossary
from plg.ontology.vocab import VocabIndex, load_vocab
from plg.search.rerank import Retriever

ROUTE = "route"
KNOWLEDGE = knowledge.NODE
DATA = data.NODE
DRAFTING = drafting.NODE
MERGE = "merge"
SUMMARISE = history.NODE
LOAD_MEMORY = "load_memory"
WRITE_MEMORY = "write_memory"

ROUTE_SYSTEM = """\
You route questions from officers of the Properties & Land Group (PLG) to specialists.
- knowledge: anything answered from PLG's documents and records, including what is known about a tenant, unit or tenancy: policies, SOPs, circulars, procedures, \
rules, limits, deadlines, what a PLG term means, precedents (past cases and decisions), audit findings, incidents, letters, emails and notes.
- data: numeric questions answered by querying PLG Records and the Excel trackers (vacancy report, arrears ageing, \
rent roll, renewals pipeline, inspection and officer task trackers, trade mix, feedback statistics): counts, totals, \
rates and lists of units, tenancies, arrears, invoices, inspections, feedback, tickets and tasks; and why two \
reported figures differ.
- drafting: the officer asks for a standard letter or notice to be drafted: an arrears reminder, a missing-documents \
notice, or an update reply to someone who gave feedback.
A question can need both. Choose no specialist for greetings, thanks and questions about how to use the assistant."""

ROUTE_TOOL: Block = {
    "name": ROUTE,
    "description": "Send the question to the specialists that can answer it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "intents": {
                "type": "array", "items": {"type": "string", "enum": ["knowledge", "data", "drafting"]},
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
Figures from the data specialist carry no marker: keep them exact and keep the business definition and \
effective date it names. Do not add facts the findings don't contain.

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
    llm: LLMClient,
    retriever: Retriever,
    vocab: VocabIndex | None = None,
    entities: GraphStore | None = None,
    *,
    warehouse: Warehouse,
    glossary: Glossary | None = None,
    layer: SemanticLayer | None = None,
    templates: TemplateLibrary | None = None,
    drafts: DraftStore | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    settings: Settings | None = None,
    memory: MemoryService | None = None,
) -> PLGGraph:
    vocab = vocab or load_vocab()
    glossary = glossary or load_glossary()
    layer = layer or load_semantic_layer()
    settings = settings or Settings.from_env()
    templates = templates or TemplateLibrary(settings.corpus_dir)
    drafts = drafts or DraftStore()
    first = LOAD_MEMORY if memory else ROUTE  # memory is recalled before routing when the graph has one

    def unsummarised(state: PLGState) -> list[Message]:
        return state.get("messages", [])[state.get("summarised", 0):]

    def conversation(state: PLGState) -> list[Message]:
        recent = unsummarised(state)
        earlier: list[Message] = (
            [{"role": "user", "content": history.SUMMARY_LEAD + state["summary"]}] if state.get("summary") else []
        )
        return [*earlier, *recent, {"role": "user", "content": state["question"]}]

    def start(state: PLGState) -> str:
        recent = unsummarised(state)
        too_long = history.estimate_tokens(recent, state.get("summary", "")) > settings.history_token_threshold
        return SUMMARISE if too_long and len(recent) > settings.history_keep_messages else first

    async def summarise_history(state: PLGState) -> PLGState:
        recent = unsummarised(state)
        cut = len(recent) - settings.history_keep_messages
        folded = await history.fold(llm, recent[:cut], state.get("summary", ""))
        return {"summary": folded, "summarised": state.get("summarised", 0) + cut}

    def agent_conversation(state: PLGState) -> list[AgentMessage]:
        return [{"role": m["role"], "content": m["content"]} for m in conversation(state)]

    async def load_memory(state: PLGState) -> PLGState:
        """The officer's private notes for this turn, as one labelled block (never a source)."""
        user = state.get("user")
        notes = await asyncio.to_thread(memory.context, user, state["question"]) if memory and user else ""
        return {"memory": notes}

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
        stances: dict[str, PolicyLineage] = {}

        def remember(found: PolicyLineage) -> None:
            stances.setdefault(found.policy_id, found)

        result = await knowledge.answer(
            llm, retriever, vocab, agent_conversation(state), state["question"], entities,
            on_lineage=remember,
        )
        write = get_stream_writer()
        for stance in stances.values():
            write({"policy_stance": stance.model_dump(mode="json")})
        for n, citation in enumerate(result.citations, start=1):
            write({"citation": citation.model_dump(), "index": n})
        return {"findings": [Finding(specialist=KNOWLEDGE, text=result.text, citations=result.citations)]}

    async def data_node(state: PLGState) -> PLGState:
        result = await data.answer(
            llm, warehouse, glossary, layer, vocab, agent_conversation(state), state["question"]
        )
        write = get_stream_writer()
        for trace in result.traces:
            write({"sql_trace": trace.model_dump(mode="json")})
        ran = any(t.status == "ok" for t in result.traces)
        return {"findings": [Finding(specialist=DATA, text=result.text, citations=[], traced=ran)]}

    async def drafting_node(state: PLGState) -> PLGState:
        result = await drafting.answer(
            llm, warehouse, layer, templates, drafts, agent_conversation(state), state.get("user")
        )
        if result.draft:
            get_stream_writer()({"draft": result.draft.model_dump()})
        return {"findings": [Finding(specialist=DRAFTING, text=result.text, citations=[], traced=result.draft is not None)]}

    async def merge(state: PLGState) -> PLGState:
        write = get_stream_writer()
        findings = state.get("findings", [])
        parts: list[str] = []
        async for text in _fuse(llm, conversation(state), findings, state.get("memory", "")):
            parts.append(text)
            write({"node": MERGE, "token": text})
        answer = "".join(parts)
        question: Message = {"role": "user", "content": state["question"]}
        return {"answer": answer, "messages": [question, {"role": "assistant", "content": answer}]}

    async def write_memory(state: PLGState, config: RunnableConfig) -> PLGState:
        """Learn from the answered turn in the background: only the officer's own words and verified findings."""
        user = state.get("user")
        if memory and user:
            verified = "\n".join(f.text for f in state.get("findings", []) if f.citations or f.traced)
            thread_id = str(config.get("configurable", {}).get("thread_id", ""))
            memory.learn_in_background(user, thread_id, state["question"], verified)
        return {}

    graph = StateGraph(PLGState)
    graph.add_node(ROUTE, route)
    graph.add_node(KNOWLEDGE, knowledge_node)
    graph.add_node(DATA, data_node)
    graph.add_node(DRAFTING, drafting_node)
    graph.add_node(MERGE, merge)
    graph.add_node(SUMMARISE, summarise_history)
    graph.add_conditional_edges(START, start, [SUMMARISE, first])
    graph.add_edge(SUMMARISE, first)
    if memory:
        graph.add_node(LOAD_MEMORY, load_memory)
        graph.add_node(WRITE_MEMORY, write_memory)
        graph.add_edge(LOAD_MEMORY, ROUTE)
    graph.add_conditional_edges(ROUTE, fan_out, [KNOWLEDGE, DATA, DRAFTING, MERGE])
    graph.add_edge(KNOWLEDGE, MERGE)
    graph.add_edge(DATA, MERGE)
    graph.add_edge(DRAFTING, MERGE)
    if memory:
        graph.add_edge(MERGE, WRITE_MEMORY)
        graph.add_edge(WRITE_MEMORY, END)
    else:
        graph.add_edge(MERGE, END)
    return graph.compile(checkpointer=checkpointer or InMemorySaver())


async def _fuse(
    llm: LLMClient, messages: list[Message], findings: list[Finding], memory: str = ""
) -> AsyncIterator[str]:
    """The answer's tokens. Findings without a single citation are not an answer: say the sources don't
    cover the question rather than let Claude fill the gap."""
    if findings and not any(f.citations or f.traced for f in findings):
        for token in re.findall(r"\s*\S+", NOT_COVERED):
            yield token
        return
    if findings:
        blocks = "\n\n".join(f"<{f.specialist}>\n{f.text}\n</{f.specialist}>" for f in findings)
        system = MERGE_SYSTEM + MERGE_FINDINGS.format(findings=blocks)
    else:
        system = MERGE_SYSTEM + MERGE_NO_SOURCES
    if memory:
        system += "\n\n" + memory
    async for text in llm.stream_text(node=MERGE, tier="sonnet", system=system, messages=messages):
        yield text
