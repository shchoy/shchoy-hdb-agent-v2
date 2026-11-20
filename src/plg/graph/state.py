"""Graph state."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict, TypeVar

from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from plg.actions.model import ApprovalDecision, ProposedAction, upsert_actions
from plg.agents.runtime import Citation
from plg.feedback.model import AnsweredTurn
from plg.guardrails.injection import InjectionFlag
from plg.identity import UserCtx
from plg.llm import Message

Intent = Literal["knowledge", "data", "drafting", "defect", "doc_check", "tasks", "glossary", "category_summary"]
"""What kind of question it is: one label per specialist."""


class Finding(BaseModel):
    """A specialist's answer to its part of the question, for `merge` to fuse."""

    specialist: str
    text: str
    citations: list[Citation]
    traced: bool = False
    """The finding rests on a query that ran (the data specialist's counterpart of a citation)."""
    sql: str | None = None
    """The last query that ran for it (data specialist), offered to curators as a question → SQL example on a 👍."""
    top_score: float | None = None
    """The best retrieval score of the passages the specialist was shown (knowledge), for the question log."""


T = TypeVar("T")


def per_turn(left: list[T], right: list[T]) -> list[T]:
    """Specialists fan in by appending. An empty update (from `screen_input` or `route`) starts the turn afresh."""
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
    findings: Annotated[list[Finding], per_turn]
    # Prompt-injection attempts met this turn: in the officer's message (`screen_input`; such a message reaches no
    # specialist), and in the documents the specialists read (flagged at ingestion).
    screened: list[InjectionFlag]
    injections: Annotated[list[InjectionFlag], per_turn]
    answer: str
    # Every answered turn with the run that answered it, so feedback can name an answer by its run ID (see plg.feedback).
    turns: Annotated[list[AnsweredTurn], operator.add]
    # The labelled block of the officer's private notes for this turn (see plg.memory).
    memory: str
    # What this turn's specialists propose; `merge` commits it to `proposed_actions` unless the turn met an injection.
    proposals: Annotated[list[ProposedAction], per_turn]
    # Everything the thread has proposed to do outside the system, by action ID; pending ones wait at `approval`.
    proposed_actions: Annotated[list[ProposedAction], upsert_actions]
    # The officer's decision `approval` received, for `execute_action` to carry out.
    decision: ApprovalDecision | None


RUN_ID = "plg_run_id"
"""Configurable key carrying the run's (LangSmith) run ID to the nodes, e.g. for the audit log."""
RUN_STARTED = "plg_run_started"
"""Configurable key carrying a traced run's start time (ISO 8601, the root run's `start_time`): with the project, the
lookup key LangSmith needs to find the run again (annotation queue items, feedback)."""

PLGGraph = CompiledStateGraph[PLGState, Any, PLGState, PLGState]
