"""StateGraph wiring.

Walking skeleton: `merge` answers the question directly. Routing, specialists and the
`Send()` fan-out slot in ahead of it later; `merge` stays the only node that streams tokens.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from plg.graph.state import PLGState
from plg.llm import LLMClient

MERGE_SYSTEM = (
    "You are the PLG Super-Librarian, an assistant for officers of the Properties & Land Group. "
    "Answer clearly and concisely using PLG's own terms."
)


def build_graph(
    llm: LLMClient, checkpointer: BaseCheckpointSaver[Any] | None = None
) -> CompiledStateGraph[PLGState, Any, PLGState, PLGState]:
    async def merge(state: PLGState) -> PLGState:
        write = get_stream_writer()
        parts: list[str] = []
        async for text in llm.stream_text(
            node="merge", tier="sonnet", system=MERGE_SYSTEM, messages=state["messages"]
        ):
            parts.append(text)
            write({"node": "merge", "token": text})
        answer = "".join(parts)
        return {"answer": answer, "messages": [{"role": "assistant", "content": answer}]}

    graph = StateGraph(PLGState)
    graph.add_node("merge", merge)
    graph.add_edge(START, "merge")
    graph.add_edge("merge", END)
    return graph.compile(checkpointer=checkpointer or InMemorySaver())
