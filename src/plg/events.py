"""Run events streamed to clients as SSE. Pydantic models, so they can be published in OpenAPI (#3)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from plg.agents.runtime import Citation
from plg.data.trace import SqlTrace
from plg.drafting.model import Draft


class NodeEvent(BaseModel):
    """A graph node started or finished, for the trajectory view."""

    type: Literal["node"] = "node"
    seq: int
    node: str
    status: Literal["started", "finished"]


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    seq: int
    node: str
    text: str


class CitationEvent(Citation):
    """A source the answer cites. `index` is the number of its `[n]` marker in the answer text."""

    type: Literal["citation"] = "citation"
    seq: int
    index: int


class SqlTraceEvent(SqlTrace):
    """One query the data agent sent: its plan, SQL, result summary and the glossary terms it relied on."""

    type: Literal["sql_trace"] = "sql_trace"
    seq: int


class DraftEvent(Draft):
    """A letter drafted from an approved template: HTML preview, open slots and personal-data flags. Not sent."""

    type: Literal["draft"] = "draft"
    seq: int


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"
    seq: int
    run_id: str


class ErrorEvent(BaseModel):
    """The run failed. Any answer streamed so far is partial and must not be trusted."""

    type: Literal["error"] = "error"
    seq: int
    run_id: str
    message: str


RunEvent = Annotated[
    NodeEvent | TokenEvent | CitationEvent | SqlTraceEvent | DraftEvent | DoneEvent | ErrorEvent, Field(discriminator="type")
]
