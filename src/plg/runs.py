"""Drive one graph run and turn its stream into numbered `RunEvent`s. Shared by plg-api and the CLI."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from plg.events import DoneEvent, ErrorEvent, NodeEvent, RunEvent, TokenEvent
from plg.graph.state import PLGState

logger = logging.getLogger(__name__)


async def stream_run(
    graph: CompiledStateGraph[PLGState, Any, PLGState, PLGState], thread_id: str, message: str
) -> AsyncIterator[RunEvent]:
    run_id = str(uuid.uuid4())
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}, "run_id": uuid.UUID(run_id)}
    seq = 0

    def next_seq() -> int:
        nonlocal seq
        seq += 1
        return seq

    try:
        async for mode, chunk in graph.astream(
            {"messages": [{"role": "user", "content": message}]},
            config,
            stream_mode=["tasks", "custom"],
        ):
            chunk = cast(dict[str, Any], chunk)
            if mode == "tasks":
                if chunk.get("error"):
                    continue  # reported once, as the run's error event below
                yield NodeEvent(
                    seq=next_seq(),
                    node=chunk["name"],
                    status="finished" if "result" in chunk else "started",
                )
            elif mode == "custom" and "token" in chunk:
                yield TokenEvent(seq=next_seq(), node=chunk["node"], text=chunk["token"])
    except Exception:
        logger.exception("Run %s on thread %s failed", run_id, thread_id)
        yield ErrorEvent(
            seq=next_seq(),
            run_id=run_id,
            message="The run failed before the answer was complete. Please retry.",
        )
        return
    yield DoneEvent(seq=next_seq(), run_id=run_id)
