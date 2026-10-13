"""StateGraph wiring.

Walking skeleton: `merge` answers the question directly. Routing, specialists and the
`Send()` fan-out slot in ahead of it later; `merge` stays the only node that streams tokens.
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from plg.graph.state import PLGGraph, PLGState
from plg.llm import LLMClient

MERGE = "merge"
MERGE_SYSTEM = (
    "You are the PLG Super-Librarian, an assistant for officers of the Properties & Land Group. "
    "Answer clearly and concisely using PLG's own terms."
)


def build_graph(llm: LLMClient) -> PLGGraph:
    async def merge(state: PLGState) -> PLGState:
        write = get_stream_writer()
        parts: list[str] = []
        async for text in llm.stream_text(
            node=MERGE, tier="sonnet", system=MERGE_SYSTEM, messages=state["messages"]
        ):
            parts.append(text)
            write({"node": MERGE, "token": text})
        answer = "".join(parts)
        return {"answer": answer, "messages": [{"role": "assistant", "content": answer}]}

    graph = StateGraph(PLGState)
    graph.add_node(MERGE, merge)
    graph.add_edge(START, MERGE)
    graph.add_edge(MERGE, END)
    return graph.compile(checkpointer=InMemorySaver())
