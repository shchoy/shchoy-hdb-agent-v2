"""Keyword search over the officer's own items (#109): pending approvals they may decide, their past decisions (the
audit trail) and their memories. Few enough to match in Python as they are read (no index, no model): every searched
word must start a word in one of the item's fields, as in the Documents search; the hit names the first field that
matched and shows it as a snippet with the words marked. Items matching every word in their title come first."""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Literal, TypeVar

from pydantic import BaseModel

from plg.actions.audit import AuditEntry
from plg.actions.model import ActionType, Decision, ProposedAction
from plg.memory.store import Kind, MemoryView
from plg.search.models import MemoryStatus
from plg.search.keyword import excerpt, starts, whole, words
from plg.thread_search import SnippetPart

LIMIT = 10
"""Items returned per group."""

_TAG = re.compile(r"<[^>]+>")
_SHORT = 120
"""A field this short (a title) is shown whole; a longer one as the passage around its first match."""


class ApprovalHit(BaseModel):
    """A pending action the officer may decide (as GET /approvals lists it), matching a search."""

    action_id: str
    version: int
    action_type: ActionType
    title: str
    thread_id: str
    thread_title: str
    proposed_by: str
    proposed_at: str
    matched: Literal["title", "content"]
    """The action's title, or what it would send or raise (its preview)."""
    snippet: list[SnippetPart]


class DecisionHit(BaseModel):
    """One of the officer's own decisions (an entry of GET /audit), matching a search."""

    action_id: str
    version: int
    action_type: ActionType
    title: str
    decision: Decision
    at: str
    matched: Literal["title", "reason", "edits", "reference"]
    """The action's title, the officer's reason, their edits, or what it produced (outbox item, ticket, term ID)."""
    snippet: list[SnippetPart]


class MemoryHit(BaseModel):
    """One of the officer's own memories (as GET /memory lists it), matching a search."""

    id: str
    kind: Kind
    status: MemoryStatus
    updated_at: datetime
    snippet: list[SnippetPart]


F = TypeVar("F", bound=str)
H = TypeVar("H", bound=BaseModel)


def match(q: str, fields: Sequence[tuple[F, str]]) -> tuple[F, list[SnippetPart], bool] | None:
    """Every word of `q` as the start of a word somewhere in the fields: the first field holding one, its snippet and
    whether the first field (the title) holds them all; None if a word is in no field."""
    patterns = [starts(w) for w in words(q)]
    if not patterns or any(not any(p.search(text) for _, text in fields) for p in patterns):
        return None
    name, text = next((n, t) for n, t in fields if any(p.search(t) for p in patterns))
    found = [p for p in patterns if p.search(text)]
    snippet = whole(_flat(text), found) if len(text) <= _SHORT else excerpt(_flat(text), found)[0]
    return name, snippet, all(p.search(fields[0][1]) for p in patterns)


def plain(fragment: str) -> str:
    """An escaped HTML fragment (an action's preview) as text."""
    return " ".join(html.unescape(_TAG.sub(" ", fragment)).split())


def approvals(q: str, pending: Iterable[tuple[ProposedAction, str, str]]) -> list[ApprovalHit]:
    """`pending`: each action with its thread ID and title as the officer's inbox shows it; newest first."""
    hits: list[tuple[bool, ApprovalHit]] = []
    for action, thread_id, thread_title in sorted(pending, key=lambda p: p[0].proposed_at, reverse=True):
        fields: list[tuple[Literal["title", "content"], str]] = [
            ("title", action.title), ("content", plain(action.preview)),
        ]
        found = match(q, fields)
        if found:
            name, snippet, titled = found
            hits.append((titled, ApprovalHit(
                action_id=action.action_id, version=action.version, action_type=action.action_type, title=action.title,
                thread_id=thread_id, thread_title=thread_title, proposed_by=action.proposed_by,
                proposed_at=action.proposed_at, matched=name, snippet=snippet,
            )))
    return _ranked(hits)


def decisions(q: str, entries: Iterable[AuditEntry]) -> list[DecisionHit]:
    """`entries`: the officer's own decisions, newest first (as AuditLog.decided_by)."""
    hits: list[tuple[bool, DecisionHit]] = []
    for e in entries:
        reference = " ".join(i for i in (e.outbox_id, e.ticket_id, e.term_id, e.action_id) if i)
        edits = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in e.edits.items())
        fields: list[tuple[Literal["title", "reason", "edits", "reference"], str]] = [
            ("title", e.title), ("reason", e.reason), ("edits", edits), ("reference", reference),
        ]
        found = match(q, fields)
        if found:
            name, snippet, titled = found
            hits.append((titled, DecisionHit(
                action_id=e.action_id, version=e.version, action_type=e.action_type, title=e.title, decision=e.decision,
                at=e.at, matched=name, snippet=snippet,
            )))
    return _ranked(hits)


def memories(q: str, notes: Iterable[MemoryView]) -> list[MemoryHit]:
    """The officer's own memories matching, most recently updated first."""
    hits: list[tuple[bool, MemoryHit]] = []
    for note in sorted(notes, key=lambda n: n.updated_at, reverse=True):
        found = match(q, [("text", note.text)])
        if found:
            hits.append((True, MemoryHit(
                id=note.id, kind=note.kind, status=note.status, updated_at=note.updated_at, snippet=found[1],
            )))
    return _ranked(hits)


def _ranked(hits: list[tuple[bool, H]]) -> list[H]:
    """Title matches first, otherwise in the order given (stable)."""
    return [hit for _, hit in sorted(hits, key=lambda h: not h[0])][:LIMIT]


def _flat(text: str) -> str:
    return " ".join(text.split())
