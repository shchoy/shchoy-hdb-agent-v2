"""What a data question did: the plan, the SQL, a summary of its result, and the glossary terms it used."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from plg.data.warehouse import Cell


class ConceptUsed(BaseModel):
    """A glossary term version a query relied on, with the dates it was in force."""

    id: str
    concept: str
    version: int
    label: str
    effective_from: date | None
    effective_to: date | None


class ResultSummary(BaseModel):
    columns: list[str]
    row_count: int
    truncated: bool
    """True when the result had more rows than are fetched; row_count is then a lower bound."""
    sample: list[list[Cell]]
    """The first rows."""


class SqlTrace(BaseModel):
    plan: str
    sql: str
    as_of: date
    status: Literal["ok", "rejected"]
    error: str | None
    result: ResultSummary | None
    concepts: list[ConceptUsed]
    warnings: list[str]
    explanation: str
    """The agent's answer, carried by the last trace of a run; empty on the others."""
