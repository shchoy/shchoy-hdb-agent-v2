"""Graph state. Grows with later tickets (intents, results, citations, proposed actions, ...)."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph.state import CompiledStateGraph

from plg.identity import UserCtx
from plg.llm import Message


class PLGState(TypedDict, total=False):
    # Completed exchanges only. A turn joins the history when it is answered, so a failed
    # run leaves nothing behind and retrying it doesn't repeat the question.
    messages: Annotated[list[Message], operator.add]
    question: str
    user: UserCtx
    answer: str


PLGGraph = CompiledStateGraph[PLGState, Any, PLGState, PLGState]
