"""Keyword search over the officer's own conversations (#107): an SQLite FTS5 table beside plg_threads.

One row per conversation title (message_index NULL) and one per answered turn (its question and answer). ThreadStore
keeps it in step (first question, rename, answered turns, delete), so a renamed title or a new answer is found at once
and a deleted conversation never is. No model is called: words are matched by prefix, as the officer types.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel

from plg.feedback.model import AnsweredTurn

LIMIT = 20
"""Conversations returned per search."""

_OPEN, _CLOSE = "\x02", "\x03"
"""Snippet highlight markers: control characters, so no text can fake them."""

_TITLE = "replace(replace(title, char(2), ''), char(3), '')"
"""A title as indexed: without the highlight markers."""

_WORD = re.compile(r"\w+")
_MARKER = re.compile(r"\[\d+\]")
"""An answer's citation markers: not words the officer searches for."""
_MARKUP = re.compile(r"[#*`>|]+")


class SnippetPart(BaseModel):
    text: str
    match: bool = False
    """One of the searched words: shown highlighted."""


class ConversationHit(BaseModel):
    """One of the officer's conversations matching a search, at its best-matching place."""

    thread_id: str
    title: str
    """Its current title."""
    updated_at: str
    group_id: str | None = None
    group_name: str | None = None
    pinned: int | None = None
    """Its place in Pinned (None: not pinned), as in ThreadSummary."""
    matched: Literal["title", "question", "answer"]
    message_index: int | None = None
    """The matching turn: its question's index in ThreadView.messages (the answer follows it). None: the title matched."""
    snippet: list[SnippetPart]


def create_schema(db: sqlite3.Connection) -> bool:
    """Creates the index; True when it is new (an older threads.sqlite: its conversations need indexing)."""
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name = 'plg_search'").fetchone() is not None
    if not exists:
        db.execute(
            "CREATE VIRTUAL TABLE plg_search USING fts5(title, question, answer, thread_id UNINDEXED, "
            "message_index UNINDEXED, tokenize = 'unicode61 remove_diacritics 2')"
        )
        db.execute(
            "INSERT INTO plg_search (title, question, answer, thread_id) "
            f"SELECT {_TITLE}, '', '', thread_id FROM plg_threads WHERE title IS NOT NULL"
        )
    return not exists


def set_title(db: sqlite3.Connection, thread_id: str) -> None:
    """Re-indexes the conversation's current title."""
    db.execute("DELETE FROM plg_search WHERE thread_id = ? AND message_index IS NULL", (thread_id,))
    db.execute(
        "INSERT INTO plg_search (title, question, answer, thread_id) "
        f"SELECT {_TITLE}, '', '', thread_id FROM plg_threads WHERE thread_id = ? AND title IS NOT NULL",
        (thread_id,),
    )


def set_turns(db: sqlite3.Connection, thread_id: str, turns: Iterable[AnsweredTurn]) -> None:
    """Replaces the conversation's indexed turns with these (all its answered turns)."""
    db.execute("DELETE FROM plg_search WHERE thread_id = ? AND message_index IS NOT NULL", (thread_id,))
    db.executemany(
        "INSERT INTO plg_search (title, question, answer, thread_id, message_index) VALUES ('', ?, ?, ?, ?)",
        # message_index here = the turn's question (just before its answer, AnsweredTurn.message_index).
        [(_clean(t.question), _clean(_plain(t.answer)), thread_id, max(t.message_index - 1, 0)) for t in turns],
    )


def drop(db: sqlite3.Connection, thread_id: str) -> None:
    db.execute("DELETE FROM plg_search WHERE thread_id = ?", (thread_id,))


def search(db: sqlite3.Connection, staff_id: str, q: str, limit: int = LIMIT) -> list[ConversationHit]:
    """The officer's conversations matching every word of `q` (each as a prefix), best first, each once."""
    words = [w.lower() for w in _WORD.findall(q)]
    if not words:
        return []
    query = " ".join(f'"{w}"*' for w in words)  # quoted: FTS5 operators (AND, NEAR, -) are just words here
    rows = db.execute(
        "SELECT s.thread_id, s.message_index, t.title, t.updated_at, t.group_id, g.name, t.pinned, "
        f"snippet(plg_search, -1, '{_OPEN}', '{_CLOSE}', '…', 16), "
        f"instr(highlight(plg_search, 0, '{_OPEN}', ''), '{_OPEN}') > 0, "
        f"instr(highlight(plg_search, 1, '{_OPEN}', ''), '{_OPEN}') > 0 "
        "FROM plg_search s JOIN plg_threads t ON t.thread_id = s.thread_id "
        "LEFT JOIN plg_groups g ON g.group_id = t.group_id AND g.staff_id = t.staff_id "
        "WHERE plg_search MATCH ? AND t.staff_id = ? AND t.title IS NOT NULL "
        "ORDER BY bm25(plg_search, 2.0, 1.5, 1.0), t.updated_at DESC LIMIT 500",
        (query, staff_id),
    ).fetchall()
    # Best first, each conversation once, at its best-matching turn: its title only when no turn matches (a title
    # starts as the first question, which should open at that question).
    hits: dict[str, ConversationHit] = {}
    for thread_id, index, title, updated_at, group_id, group_name, pinned, snippet, in_title, in_question in rows:
        found = hits.get(thread_id)
        if found is not None and (found.message_index is not None or index is None):
            continue
        hits[thread_id] = ConversationHit(
            thread_id=thread_id, title=title, updated_at=updated_at, group_id=group_id if group_name else None,
            group_name=group_name, pinned=pinned, message_index=index,
            matched="title" if in_title else "question" if in_question else "answer", snippet=_parts(snippet),
        )
    return list(hits.values())[:limit]


def _plain(answer: str) -> str:
    """An answer as searchable text: no citation markers or markdown symbols."""
    return " ".join(_MARKUP.sub(" ", _MARKER.sub("", answer)).split())


def _clean(text: str) -> str:
    return text.replace(_OPEN, "").replace(_CLOSE, "")


def _parts(snippet: str) -> list[SnippetPart]:
    parts: list[SnippetPart] = []
    for i, piece in enumerate(re.split(f"[{_OPEN}{_CLOSE}]", snippet)):
        if piece:
            parts.append(SnippetPart(text=piece, match=i % 2 == 1))
    return parts
