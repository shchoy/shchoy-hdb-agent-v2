"""Drive one graph run and turn its stream into numbered `RunEvent`s. Shared by plg-api and the CLI."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any, cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from plg.actions.model import ApprovalDecision
from plg.events import (
    ActionResultEvent, CitationEvent, ClassificationEvent, DocCheckEvent, DoneEvent, DraftEvent, ErrorEvent, InjectionEvent, InterruptEvent, NodeEvent, PolicyStanceEvent,
    ProposedActionEvent, RunEvent, SqlTraceEvent, TasksEvent, TokenEvent,
)
from plg.graph.state import RUN_ID, RUN_STARTED, PLGGraph, PLGState
from plg.identity import UserCtx
from plg.tracing import Channel, Tracer

logger = logging.getLogger(__name__)


async def stream_run(
    graph: PLGGraph, thread_id: str, message: str, user: UserCtx | None = None,
    *, decision: ApprovalDecision | None = None, tracer: Tracer | None = None, channel: Channel = "api",
    run_id: uuid.UUID | None = None, attachments: list[str] | None = None,
) -> AsyncIterator[RunEvent]:
    """Answer `message`, or, given a `decision`, resume the thread's pending approval with it.

    With a `tracer`, the run is one LangSmith trace whose root carries the run ID reported in `done`/`error`.
    `run_id`: use this ID (a caller reporting the run's cancellation itself names it). `attachments`: IDs of the
    officer's uploads sent with the question (#103)."""
    run_id = run_id or uuid.uuid4()
    if tracer is None:
        async for event in _stream(graph, run_id, thread_id, message, user, decision, attachments=attachments):
            yield event
        return
    if decision is None:
        inputs: dict[str, Any] = {"question": message, **({"attachments": attachments} if attachments else {})}
        extra: dict[str, Any] = {"kind": "question"}
    else:
        inputs = {"decision": decision.model_dump(mode="json")}
        extra = {"kind": "resume", "action_id": decision.action_id, "decision": decision.decision}
    with tracer.run(str(run_id), thread_id=thread_id, user=user, channel=channel, inputs=inputs, extra=extra) as root:
        answer: list[str] = []
        waiting: list[str] = []  # actions the run stopped at (the approval interrupt)
        failed: str | None = None
        started = root.start_time.isoformat()
        try:
            async for event in _stream(
                graph, run_id, thread_id, message, user, decision, root.add_metadata, started, attachments=attachments
            ):
                if isinstance(event, TokenEvent):
                    answer.append(event.text)
                elif isinstance(event, InterruptEvent):
                    waiting.append(f"{event.action_id} v{event.version}")
                elif isinstance(event, ErrorEvent):
                    failed = event.message
                yield event
        except asyncio.CancelledError:  # the officer stopped it
            root.add_metadata({"cancelled": True})
            root.end(outputs={"answer": "".join(answer), "awaiting_approval": []})  # the trace records the error
            raise
        if waiting:
            root.add_metadata({"interrupted": True})
        root.end(outputs={"answer": "".join(answer), "awaiting_approval": waiting}, error=failed)


async def _stream(
    graph: PLGGraph, run_id: uuid.UUID, thread_id: str, message: str, user: UserCtx | None,
    decision: ApprovalDecision | None, annotate: Callable[[dict[str, Any]], None] | None = None,
    started: str | None = None, *, attachments: list[str] | None = None,
) -> AsyncIterator[RunEvent]:
    """`annotate` adds trace metadata as the run learns what it is about (its intents, once routed); `started` is the
    traced root run's start time."""
    # The run ID is carried in `configurable`, not as LangGraph's own run ID: a traced run's root is `plg_run`.
    config: RunnableConfig = {"configurable": {"thread_id": thread_id, RUN_ID: str(run_id), RUN_STARTED: started}}
    seq = 0
    inputs: PLGState | Command[None]
    if decision is not None:
        inputs = Command(resume=decision.model_dump(mode="json"))
    else:
        inputs = {"question": message, "attachments": list(attachments or [])}
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
                if annotate is not None and chunk["name"] == "route" and "result" in chunk:
                    routed = dict(chunk["result"])
                    annotate({"intents": list(routed.get("intents") or [])})
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
            elif mode == "custom" and "tasks" in chunk:
                yield TasksEvent(seq=next_seq(), **chunk["tasks"])
            elif mode == "custom" and "injection" in chunk:
                yield InjectionEvent(seq=next_seq(), **chunk["injection"])
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
