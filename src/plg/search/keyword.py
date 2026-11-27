"""Keyword search over indexed chunks (#108): the search dialog's Documents and My uploads, with no Claude or Voyage
call. LanceDB full-text indexes on `title` and `text` (character n-grams, so a word is found while it is still being
typed) give the candidates; each is then checked here for every searched word as the start of a word, in its title or
text, and given a snippet with the matched words marked and the span of the match in its chunk's text (where the
source viewer highlights it). One hit per document, at its best chunk; current documents before superseded ones."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal

from lancedb.index import FTS
from lancedb.query import BooleanQuery, FullTextOperator, MatchQuery, Occur
from lancedb.table import Table
from pydantic import BaseModel

from plg.search.models import DocStatus
from plg.thread_search import SnippetPart

LIMIT = 10
"""Documents returned per search (per group: Library documents, uploads)."""

CANDIDATES = 500
"""Chunks the full-text indexes are asked for, before the word check."""

COLUMNS = ("title", "text")
"""Indexed for keyword search, apart from `fts_text` (the knowledge agent's stemmed word index)."""

_CONFIG = FTS(
    base_tokenizer="ngram", ngram_min_length=2, ngram_max_length=3, prefix_only=False,
    stem=False, remove_stop_words=False,
)
_WORD = re.compile(r"\w+")
_BEFORE, _AFTER = 60, 160
"""Snippet: characters of context kept before the first match and after it."""
_MAX_SPAN = 300
"""A highlighted span longer than this is cut to its first match."""


class MatchSpan(BaseModel):
    """Offsets of the match in the chunk's text (as a citation's span)."""

    start: int
    end: int


class DocumentHit(BaseModel):
    """A document (a Library document or one of the officer's uploads) matching a keyword search."""

    doc_id: str
    chunk_id: str
    """Its best-matching chunk: where the source viewer opens."""
    title: str
    doc_type: str
    version: str | None = None
    status: DocStatus = "current"
    location: str
    upload: bool = False
    """One of the officer's own uploads."""
    matched: Literal["title", "content"]
    snippet: list[SnippetPart]
    """The title (a title match) or the passage around the match, with the matched words marked."""
    span: MatchSpan | None = None
    """The match in the chunk's text; None for a title match."""


def words(q: str) -> list[str]:
    return list(dict.fromkeys(w.lower() for w in _WORD.findall(q)))


def indexed(table: Table) -> bool:
    """The keyword indexes exist (an index synced before #108 has none until the next `plg sync`)."""
    built = {c for i in table.list_indices() if i.index_type == "FTS" for c in i.columns}
    return all(c in built for c in COLUMNS)


def build_indexes(table: Table) -> None:
    """(Re)builds the keyword indexes. Rows written after a build are still searched: unindexed rows are scanned."""
    for column in COLUMNS:
        table.create_index(column, config=_CONFIG, replace=True)


def search(table: Table, q: str, *, where: str | None = None, upload: bool = False, limit: int = LIMIT) -> list[DocumentHit]:
    """Documents with chunks matching every word of `q` (each as the start of a word), best first."""
    wanted = words(q)
    indexable = [w for w in wanted if len(w) >= 2]
    if not indexable or table.count_rows(where) == 0 or not indexed(table):
        return []  # never written here: the shared Library index is built by `plg sync`
    query = BooleanQuery([
        (Occur.MUST, BooleanQuery([(Occur.SHOULD, _match(w, c)) for c in COLUMNS]))
        for w in indexable
    ])
    builder = table.search(query, query_type="fts")
    if where:
        builder = builder.where(where, prefilter=True)
    rows = builder.select(["doc_id", "chunk_id", "seq", "title", "doc_type", "version", "status", "location", "text", "_score"])
    best: dict[str, tuple[tuple[float, float], DocumentHit]] = {}
    scores: dict[str, float] = {}
    for row in rows.limit(CANDIDATES).to_list():
        found = _hit(row, wanted, upload)
        if found is None:
            continue
        hit, in_text = found
        score = float(row["_score"])
        scores[hit.doc_id] = max(score, scores.get(hit.doc_id, score))
        # The chunk whose text holds the most of the words (so the viewer highlights them), best score first; a
        # title-only match opens at the document's start.
        rank = (float(in_text), score) if in_text else (0.0, -float(row["seq"]))
        kept = best.get(hit.doc_id)
        if kept is None or rank > kept[0]:
            best[hit.doc_id] = (rank, hit)
    titled = {h.doc_id for _, h in best.values() if all(_starts(w).search(h.title) for w in wanted)}
    # Current documents first; then a title naming every word; then the full-text score.
    ordered = sorted(
        (hit for _, hit in best.values()),
        key=lambda h: (h.status != "current", h.doc_id not in titled, -scores[h.doc_id], h.title),
    )
    return ordered[:limit]


def _match(word: str, column: str) -> MatchQuery:
    """Every n-gram of the word in the column (its defaults spelled out: mypy reads them all as required)."""
    return MatchQuery(
        word, column, boost=1.0, fuzziness=0, max_expansions=50, operator=FullTextOperator.AND, prefix_length=0,
        document_granularity=None,
    )


def _starts(word: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(word)}\w*", re.IGNORECASE)


def _hit(row: dict[str, Any], wanted: Sequence[str], upload: bool) -> tuple[DocumentHit, int] | None:
    """The row as a hit, with how many of the words its text holds; None if a word is in neither title nor text."""
    title, text = str(row["title"]), str(row["text"])
    patterns = [_starts(w) for w in wanted]
    in_text = [p for p in patterns if p.search(text)]
    in_title = [p for p in patterns if p.search(title)]
    if any(p not in in_text and p not in in_title for p in patterns):
        return None  # an n-gram candidate without one of the words
    common = {
        "doc_id": row["doc_id"], "chunk_id": row["chunk_id"], "title": title, "doc_type": row["doc_type"],
        "version": row["version"], "status": row["status"], "location": row["location"], "upload": upload,
    }
    if not in_text:
        return DocumentHit(**common, matched="title", snippet=_snippet(title, patterns, 0, len(title))), 0
    matches = sorted((m.start(), m.end()) for p in in_text for m in p.finditer(text))
    anchor = matches[0][0]
    start = 0 if anchor <= _BEFORE else text.find(" ", anchor - _BEFORE, anchor) + 1 or anchor - _BEFORE
    end = len(text)
    if anchor + _AFTER < len(text):
        space = text.rfind(" ", anchor, anchor + _AFTER)
        end = space if space > 0 else anchor + _AFTER
    end = max(end, matches[0][1])
    shown = [m for m in matches if m[1] <= end]
    span = MatchSpan(start=shown[0][0], end=shown[-1][1])
    if span.end - span.start > _MAX_SPAN:
        span = MatchSpan(start=shown[0][0], end=shown[0][1])
    snippet = _snippet(text, patterns, start, end)
    if start > 0:
        snippet.insert(0, SnippetPart(text="…"))
    if end < len(text):
        snippet.append(SnippetPart(text="…"))
    return DocumentHit(**common, matched="content", snippet=snippet, span=span), len(in_text)


def _snippet(text: str, patterns: Sequence[re.Pattern[str]], start: int, end: int) -> list[SnippetPart]:
    window = text[start:end]
    marks = sorted({(m.start(), m.end()) for p in patterns for m in p.finditer(window)})
    parts: list[SnippetPart] = []
    at = 0
    for s, e in marks:
        if s < at:
            continue  # overlapping matches (one word a prefix of another): the first stands
        if s > at:
            parts.append(SnippetPart(text=_flat(window[at:s])))
        parts.append(SnippetPart(text=window[s:e], match=True))
        at = e
    if at < len(window):
        parts.append(SnippetPart(text=_flat(window[at:])))
    return [p for p in parts if p.text]


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)
