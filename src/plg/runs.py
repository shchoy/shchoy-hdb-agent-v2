"""Drive one graph run and turn its stream into numbered `RunEvent`s. Shared by plg-api and the CLI."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from plg.actions.model import ApprovalDecision
from plg.events import (
    ActionResultEvent, CitationEvent, ClassificationEvent, DocCheckEvent, DoneEvent, DraftEvent, ErrorEvent, InterruptEvent, NodeEvent, PolicyStanceEvent,
    ProposedActionEvent, RunEvent, SqlTraceEvent, TokenEvent,
)
from plg.graph.state import RUN_ID, PLGGraph, PLGState
from plg.identity import UserCtx

logger = logging.getLogger(__name__)


async def stream_run(
    graph: PLGGraph, thread_id: str, message: str, user: UserCtx | None = None,
    *, decision: ApprovalDecision | None = None,
) -> AsyncIterator[RunEvent]:
    """Answer `message`, or, given a `decision`, resume the thread's pending approval with it."""
    run_id = uuid.uuid4()
    config: RunnableConfig = {"configurable": {"thread_id": thread_id, RUN_ID: str(run_id)}, "run_id": run_id}
    seq = 0
    inputs: PLGState | Command[None]
    if decision is not None:
        inputs = Command(resume=decision.model_dump(mode="json"))
    else:
        inputs = {"question": message}
        if user is not None:
            inputs["user"] = user

    def next_seq() -> int:
        nonlocal seq
        seq += 1
        return seq

    try:
        async for mode, chunk in graph.astream(
            inputs,
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
                for paused in chunk.get("interrupts") or []:  # waiting for the officer's decision on actions
                    for proposed in paused["value"]:
                        action = ProposedActionEvent(seq=next_seq(), **proposed)
                        yield action
                        yield InterruptEvent(
                            seq=next_seq(), action_id=action.action_id, version=action.version,
                            approver_roles=action.approver_roles,
                        )
            elif mode == "custom" and "token" in chunk:
                yield TokenEvent(seq=next_seq(), node=chunk["node"], text=chunk["token"])
            elif mode == "custom" and "citation" in chunk:
                yield CitationEvent(seq=next_seq(), index=chunk["index"], **chunk["citation"])
            elif mode == "custom" and "sql_trace" in chunk:
                yield SqlTraceEvent(seq=next_seq(), **chunk["sql_trace"])
            elif mode == "custom" and "draft" in chunk:
                yield DraftEvent(seq=next_seq(), **chunk["draft"])
            elif mode == "custom" and "classification" in chunk:
                yield ClassificationEvent(seq=next_seq(), **chunk["classification"])
            elif mode == "custom" and "doc_check" in chunk:
                yield DocCheckEvent(seq=next_seq(), **chunk["doc_check"])
            elif mode == "custom" and "policy_stance" in chunk:
                yield PolicyStanceEvent(seq=next_seq(), **chunk["policy_stance"])
            elif mode == "custom" and "action_result" in chunk:
                yield ActionResultEvent(seq=next_seq(), **chunk["action_result"])
    except Exception:
        logger.exception("Run %s on thread %s failed", run_id, thread_id)
        yield ErrorEvent(
            seq=next_seq(),
            run_id=str(run_id),
            message="The run failed before the answer was complete. Please retry.",
        )
        return
    yield DoneEvent(seq=next_seq(), run_id=str(run_id))
