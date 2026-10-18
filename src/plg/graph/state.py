"""Graph state. Grows with later tickets (sql traces, proposed actions, ...)."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel

from plg.agents.runtime import Citation
from plg.identity import UserCtx
from plg.llm import Message

Intent = Literal["knowledge", "data"]
"""What kind of question it is. Grows with the specialists (data, drafting, defect, ...)."""


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
    question: str
    user: UserCtx
    intents: list[Intent]
    findings: Annotated[list[Finding], add_findings]
    answer: str


PLGGraph = CompiledStateGraph[PLGState, Any, PLGState, PLGState]
