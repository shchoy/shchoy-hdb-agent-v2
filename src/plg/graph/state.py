"""Graph state."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from plg.actions.model import ApprovalDecision, ProposedAction, upsert_actions
from plg.agents.runtime import Citation
from plg.identity import UserCtx
from plg.llm import Message

Intent = Literal["knowledge", "data", "drafting", "defect", "doc_check"]
"""What kind of question it is. Grows with the specialists (tasks, ...)."""


class Finding(BaseModel):
    """A specialist's answer to its part of the question, for `merge` to fuse."""

    specialist: str
    text: str
    citations: list[Citation]
    traced: bool = False
    """The finding rests on a query that ran (the data specialist's counterpart of a citation)."""


def add_findings(left: list[Finding], right: list[Finding]) -> list[Finding]:
    """Specialists fan in by appending. An empty update (from `route`) starts the turn afresh."""
    return [*left, *right] if right else []


class PLGState(TypedDict, total=False):
    # Completed exchanges only. A turn joins the history when it is answered, so a failed run leaves nothing
    # behind and retrying it doesn't repeat the question.
    messages: Annotated[list[Message], operator.add]
    # Older turns folded by `summarise_history`: the first `summarised` messages are replaced by `summary`.
    summary: str
    summarised: int
    question: str
    user: UserCtx
    intents: list[Intent]
    # The question `route` asks back when it can't tell what the officer needs; empty when it routed the question.
    clarification: str
    findings: Annotated[list[Finding], add_findings]
    answer: str
    # The labelled block of the officer's private notes for this turn (see plg.memory).
    memory: str
    # Everything the thread has proposed to do outside the system, by action ID; pending ones wait at `approval`.
    proposed_actions: Annotated[list[ProposedAction], upsert_actions]
    # The officer's decision `approval` received, for `execute_action` to carry out.
    decision: ApprovalDecision | None


RUN_ID = "plg_run_id"
"""Configurable key carrying the run's (LangSmith) run ID to the nodes, e.g. for the audit log."""

PLGGraph = CompiledStateGraph[PLGState, Any, PLGState, PLGState]
