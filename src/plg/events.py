"""Run events streamed to clients as SSE. Pydantic models, so they can be published in OpenAPI (#3)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


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
    NodeEvent | TokenEvent | DoneEvent | ErrorEvent, Field(discriminator="type")
]
