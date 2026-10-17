"""Source viewer: a cited document as plain text blocks, and where a cited span sits among them.

Nothing here interprets markup: block text is whatever the file holds, shown as text by the client.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from plg.ingest.extract import extract
from plg.search.models import Chunk
from plg.search.store import SearchStore

DocumentKind = Literal["pdf", "docx", "pptx", "email", "markdown", "text"]

_KINDS: dict[str, tuple[DocumentKind, str]] = {
    ".pdf": ("pdf", "application/pdf"),
    ".docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".pptx": ("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ".eml": ("email", "message/rfc822"),
    ".md": ("markdown", "text/markdown"),
    ".txt": ("text", "text/plain"),
}


class DocumentBlock(BaseModel):
    text: str
    level: int
    """0 for body text, else the heading level (1 = top)."""
    page: int | None
    """1-based page (PDF) or slide (PPTX)."""


class DocumentView(BaseModel):
    doc_id: str
    title: str
    version: str | None
    kind: DocumentKind
    filename: str
    content_type: str
    blocks: list[DocumentBlock]


class Highlight(BaseModel):
    """`blocks[block].text[start:end]` is part of the cited span."""

    block: int
    start: int
    end: int


class ChunkLocation(BaseModel):
    """Where a cited span sits in its document."""

    doc_id: str
    chunk_id: str
    location: str
    quote: str
    page: int | None
    highlights: list[Highlight]
    """Empty if the quote can no longer be found in the source file (it changed since indexing)."""


@dataclass(frozen=True)
class SourceFile:
    path: Path
    filename: str
    content_type: str
    kind: DocumentKind


class DocumentLibrary:
    """Reads indexed documents back from the corpus. The store is opened on first use."""

    def __init__(self, open_store: Callable[[], SearchStore], corpus_dir: Path) -> None:
        self._open_store = open_store
        self._store: SearchStore | None = None
        self._corpus = corpus_dir.resolve()

    @property
    def store(self) -> SearchStore:
        self._store = self._store or self._open_store()
        return self._store

    def file(self, doc_id: str) -> SourceFile | None:
        """The document's source file, or None if it is not indexed, missing, or outside the corpus."""
        chunks = self.store.chunks(doc_id)
        return self._file(chunks[0]) if chunks else None

    def _file(self, first: Chunk) -> SourceFile | None:
        path = (self._corpus / first.source_path).resolve()
        if not path.is_relative_to(self._corpus) or not path.is_file() or path.suffix.lower() not in _KINDS:
            return None
        kind, content_type = _KINDS[path.suffix.lower()]
        return SourceFile(path, path.name, content_type, kind)

    def view(self, doc_id: str) -> DocumentView | None:
        chunks = self.store.chunks(doc_id)
        source = self._file(chunks[0]) if chunks else None
        if source is None:
            return None
        first = chunks[0]
        return DocumentView(
            doc_id=doc_id, title=first.title, version=first.version, kind=source.kind,
            filename=source.filename, content_type=source.content_type, blocks=_blocks(source.path),
        )

    def locate(self, doc_id: str, chunk_id: str, start: int | None, end: int | None) -> ChunkLocation | None:
        """The span `start:end` of the chunk's text (default: all of it) among the document's blocks."""
        chunk = self.store.get_chunk(chunk_id)
        source = self.file(doc_id)
        if chunk is None or chunk.doc_id != doc_id or source is None:
            return None
        begin = min(max(start or 0, 0), len(chunk.text))
        finish = min(max(len(chunk.text) if end is None else end, begin), len(chunk.text))
        quote = chunk.text[begin:finish]
        blocks = _blocks(source.path)
        highlights = _highlights(blocks, chunk, begin, finish)
        page = next((blocks[h.block].page for h in highlights if blocks[h.block].page is not None), None)
        return ChunkLocation(
            doc_id=doc_id, chunk_id=chunk_id, location=chunk.location, quote=quote, page=page,
            highlights=highlights,
        )


def _blocks(path: Path) -> list[DocumentBlock]:
    return [DocumentBlock(text=b.text, level=b.level, page=b.page) for b in extract(path).blocks]


def _highlights(blocks: list[DocumentBlock], chunk: Chunk, begin: int, finish: int) -> list[Highlight]:
    """Block ranges of chunk.text[begin:finish]. A chunk's text is its body blocks joined by newlines."""
    if begin == finish:
        return []
    full = "\n".join(b.text for b in blocks)
    at = full.find(chunk.text)
    if at >= 0:
        first = at + begin
    else:  # the chunk no longer lines up with the file: look for the quote alone
        first = full.find(chunk.text[begin:finish])
        if first < 0:
            return []
    last = first + (finish - begin)
    highlights: list[Highlight] = []
    offset = 0
    for index, block in enumerate(blocks):
        lo, hi = max(first, offset), min(last, offset + len(block.text))
        if lo < hi:
            highlights.append(Highlight(block=index, start=lo - offset, end=hi - offset))
        offset += len(block.text) + 1
    return highlights
