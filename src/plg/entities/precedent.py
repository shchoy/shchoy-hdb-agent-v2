"""Precedents: decided cases from the compendium, matched to a situation by trade, NC and issue.

A precedent node carries the case as read from its compendium page (date, category, town, facts, decision,
reasoning, outcome, and the chunk it came from); CONCERNS_TRADE and IN_NC edges link it to the trades and the NC
the case names. `rank_precedents` is the one ranking both `GraphStore` implementations apply to what they read.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel

from plg.entities.model import Node

Criterion = Literal["trade", "nc", "town", "issue"]

WEIGHTS: dict[Criterion, int] = {"trade": 2, "nc": 2, "issue": 2, "town": 1}
"""Same NC and same trade weigh as much as the same issue; the same town only breaks ties."""

ISSUE_OVERLAP = 0.5
"""Share of the words of the issue and the case category, taken together, that both must use, unless every word
of the issue is in the category ("sublet" is an "Unauthorised subletting" case)."""

STEM = 6
"""Words are compared on their first letters, so "sublet" and "subletting" are the same word."""

_STOP = {"a", "an", "and", "the", "of", "to", "for", "in", "on", "at", "by", "with", "after", "case", "cases"}


class Precedent(BaseModel):
    precedent_id: str
    title: str
    """`PC-2024-009 Change of trade (Pasir Indah)`."""
    decided_on: date | None = None
    category: str
    town: str
    """The town the compendium files the case under."""
    nc_id: str | None = None
    trades: list[str]
    facts: str
    decision: str
    reasoning: str
    outcome: str
    doc_id: str
    chunk_id: str
    """The compendium chunk the case is read from."""
    location: str
    """Its section and page, e.g. `PC-2024-009 - Change of trade (Pasir Indah) (p. 5)`."""


class PrecedentMatch(Precedent):
    matched_on: list[Criterion]
    """What the case shares with the situation asked about: trade, nc, issue, then town."""


@dataclass(frozen=True)
class Situation:
    """What the officer's case is, resolved to graph IDs. Any part may be unknown."""

    trade: str | None = None
    nc: str | None = None
    town: str | None = None
    """Name of the NC's town, so a case in the same town ranks above one elsewhere."""
    issue: str | None = None


def words(text: str) -> set[str]:
    return {w.removesuffix("s")[:STEM] for w in re.findall(r"[a-z0-9]+", text.casefold()) if w not in _STOP}


def same_issue(issue: str, category: str) -> bool:
    asked, filed = words(issue), words(category)
    if not (asked and filed):
        return False
    return asked <= filed or len(asked & filed) / len(asked | filed) >= ISSUE_OVERLAP


def precedent(node: Node, trades: Iterable[str], nc_id: str | None) -> Precedent:
    p = node.props
    decided = str(p.get("decided_on", ""))
    return Precedent(
        precedent_id=node.id, title=node.name, decided_on=date.fromisoformat(decided) if decided else None,
        category=str(p.get("category", "")), town=str(p.get("town", "")), nc_id=nc_id, trades=sorted(trades),
        facts=str(p.get("facts", "")), decision=str(p.get("decision", "")), reasoning=str(p.get("reasoning", "")),
        outcome=str(p.get("outcome", "")), doc_id=str(p.get("doc_id", "")), chunk_id=str(p.get("chunk_id", "")),
        location=str(p.get("location", "")),
    )


def rank_precedents(cases: Iterable[Precedent], situation: Situation, limit: int = 8) -> list[PrecedentMatch]:
    """Cases sharing the trade, NC or issue, best first (then newest). The same town alone is not a match."""
    scored: list[tuple[int, date, PrecedentMatch]] = []
    for case in cases:
        matched: list[Criterion] = []
        if situation.trade and situation.trade in case.trades:
            matched.append("trade")
        if situation.nc and situation.nc == case.nc_id:
            matched.append("nc")
        if situation.issue and same_issue(situation.issue, case.category):
            matched.append("issue")
        if not matched:
            continue
        if "nc" not in matched and situation.town and situation.town.casefold() == case.town.casefold():
            matched.append("town")
        score = sum(WEIGHTS[m] for m in matched)
        scored.append((score, case.decided_on or date.min, PrecedentMatch(**case.model_dump(), matched_on=matched)))
    scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
    return [m for *_, m in scored[:limit]]
