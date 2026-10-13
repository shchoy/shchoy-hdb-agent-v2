"""Graph state. Grows with later tickets (intents, results, citations, proposed actions, ...)."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from plg.llm import Message


class PLGState(TypedDict, total=False):
    messages: Annotated[list[Message], operator.add]
    answer: str
