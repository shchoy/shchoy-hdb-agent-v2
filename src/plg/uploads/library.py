"""Officers' private libraries (#103): documents an officer uploads into a conversation.

An upload is kept as its file and a metadata JSON under `uploads_dir/<staff ID>/<upload ID>/`, and its passages go
into `LanceUploadIndex` (never the shared Library index). It is screened for prompt injection like an email at
ingestion: planted spans are replaced by the ingestion marker before chunking, and the upload reports the flag.
Everything is scoped to its owner: another officer's upload is "not found".

Limits: `upload_max_bytes` per file, `upload_quota_bytes` per officer. Text-bearing PDFs, Word, text, Markdown and
email files only; a PDF without a text layer (a scan) is refused.
"""

from __future__ import annotations

import re
import shutil
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from plg.documents import KINDS, ChunkLocation, DocumentBlock, DocumentKind, DocumentView, SourceFile, highlights_of
from plg.guardrails.injection import InjectionFlag, flags_in
from plg.ingest.chunking import location, sections, split
from plg.ingest.extract import ParsedDoc, extract
from plg.ingest.sync import screened
from plg.search.embed import Embedder
from plg.search.models import Chunk
from plg.search.rerank import UploadScope
from plg.uploads.index import LanceUploadIndex

ACCEPTED = (".pdf", ".docx", ".txt", ".md", ".eml")
"""What can be uploaded: text-layer PDFs, Word documents, plain text, Markdown and emails."""

UNSUPPORTED = (
    "Only PDF (with a text layer), Word (.docx), text (.txt, .md) and email (.eml) files can be uploaded."
)
DOC_TYPE = "upload"
_ID = re.compile(r"^upload-[0-9a-f]{16}$")
_OWNER = re.compile(r"^[A-Za-z0-9_-]+$")
_META = "upload.json"


class Upload(BaseModel):
    upload_id: str
    """Also the document ID its passages and citations carry."""
    filename: str
    title: str
    kind: DocumentKind
    content_type: str
    size: int
    """Bytes."""
    uploaded_at: datetime
    chunks: int
    injection: InjectionFlag | None = None
    """Set when planted instructions were found and removed from it."""


class UploadRefused(Exception):
    def __init__(self, status: Literal[413, 415, 422], detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def size_label(n: int) -> str:
    mb = 1024 * 1024
    return f"{n // mb} MB" if n >= mb and n % mb == 0 else f"{n / mb:.1f} MB" if n >= mb else f"{n} bytes"


class UploadLibrary:
    def __init__(
        self, root: Path, embedder: Embedder, *, max_bytes: int, quota_bytes: int, vector_weight: float = 0.7,
    ) -> None:
        self._root = root
        self._embedder = embedder
        self.max_bytes = max_bytes
        self._quota = quota_bytes
        self._vector_weight = vector_weight
        self._index: LanceUploadIndex | None = None
        self._lock = threading.Lock()

    @property
    def index(self) -> LanceUploadIndex:
        """Opened on first use, so plg-api starts without touching it."""
        if self._index is None:
            self._index = LanceUploadIndex(
                self._root / "index", dim=self._embedder.dim, vector_weight=self._vector_weight
            )
        return self._index

    # ------------------------------------------------------------------ reading
    def _dir(self, owner: str, upload_id: str | None = None) -> Path:
        if not _OWNER.match(owner):
            raise ValueError(f"not a staff ID: {owner!r}")
        return self._root / owner / upload_id if upload_id else self._root / owner

    def of(self, owner: str) -> list[Upload]:
        """The officer's uploads, newest first."""
        folder = self._dir(owner)
        found = [Upload.model_validate_json(p.read_text()) for p in folder.glob(f"upload-*/{_META}")]
        return sorted(found, key=lambda u: u.uploaded_at, reverse=True)

    def get(self, owner: str, upload_id: str) -> Upload | None:
        if not _ID.match(upload_id):
            return None
        meta = self._dir(owner, upload_id) / _META
        return Upload.model_validate_json(meta.read_text()) if meta.is_file() else None

    def scope(self, owner: str, attached: list[str]) -> UploadScope:
        """Searches cover this officer's uploads; the ones attached to the current message are boosted."""
        return UploadScope(self.index, owner, frozenset(attached))

    def file(self, owner: str, upload_id: str) -> SourceFile | None:
        item = self.get(owner, upload_id)
        if item is None:
            return None
        path = self._dir(owner, upload_id) / item.filename
        return SourceFile(path, item.filename, item.content_type, item.kind) if path.is_file() else None

    def view(self, owner: str, upload_id: str) -> DocumentView | None:
        item, source = self.get(owner, upload_id), self.file(owner, upload_id)
        if item is None or source is None:
            return None
        return DocumentView(
            doc_id=upload_id, title=item.title, version=None, kind=item.kind, filename=item.filename,
            content_type=item.content_type, blocks=_blocks(source.path), upload=True,
        )

    def locate(
        self, owner: str, upload_id: str, chunk_id: str, start: int | None, end: int | None
    ) -> ChunkLocation | None:
        source = self.file(owner, upload_id)
        chunk = self.index.get_chunk(owner, chunk_id) if source is not None else None
        if source is None or chunk is None or chunk.doc_id != upload_id:
            return None
        begin = min(max(start or 0, 0), len(chunk.text))
        finish = min(max(len(chunk.text) if end is None else end, begin), len(chunk.text))
        blocks = _blocks(source.path)
        highlights = highlights_of(blocks, chunk, begin, finish)
        page = next((blocks[h.block].page for h in highlights if blocks[h.block].page is not None), None)
        return ChunkLocation(
            doc_id=upload_id, chunk_id=chunk_id, location=chunk.location, quote=chunk.text[begin:finish], page=page,
            highlights=highlights,
        )

    # ------------------------------------------------------------------ adding
    def add(self, owner: str, filename: str, data: bytes) -> Upload:
        """Store, screen, chunk and index the file; `UploadRefused` says why it can't be taken."""
        name = _clean(filename)
        suffix = Path(name).suffix.lower()
        if not name or suffix not in ACCEPTED:
            raise UploadRefused(415, UNSUPPORTED)
        if len(data) > self.max_bytes:
            raise UploadRefused(413, f"{name} is larger than {size_label(self.max_bytes)}, the most one file may be.")
        upload_id = f"upload-{uuid.uuid4().hex[:16]}"
        folder = self._dir(owner, upload_id)
        with self._lock:  # the quota check and the write are one step
            used = sum(u.size for u in self.of(owner))
            if used + len(data) > self._quota:
                left = max(self._quota - used, 0)
                raise UploadRefused(
                    413,
                    f"Not enough space for {name}: your uploads may take {size_label(self._quota)} in all "
                    f"and {size_label(left)} is left.",
                )
            folder.mkdir(parents=True)
            path = folder / name
            path.write_bytes(data)
        try:
            item = self._ingest(owner, upload_id, path, len(data))
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return item

    def _ingest(self, owner: str, upload_id: str, path: Path, size: int) -> Upload:
        try:
            parsed = extract(path)
        except Exception:
            raise UploadRefused(422, f"{path.name} could not be read. Is it a valid {path.suffix} file?") from None
        if not parsed.blocks:
            if path.suffix.lower() == ".pdf":
                raise UploadRefused(422, f"{path.name} has no text layer (a scan); scanned PDFs can't be read yet.")
            raise UploadRefused(422, f"{path.name} has no text.")
        parsed, flagged = screened(parsed)
        kind, content_type = KINDS[path.suffix.lower()]
        title = parsed.title or path.name
        chunks = self._chunks(upload_id, title, path.name, parsed)
        flag = None
        if flagged:
            rules = next((r for c in chunks if (r := flags_in(c.text))), [])
            flag = InjectionFlag(source="document", rules=rules, doc_id=upload_id, title=title)
        item = Upload(
            upload_id=upload_id, filename=path.name, title=title, kind=kind, content_type=content_type, size=size,
            uploaded_at=datetime.now(UTC), chunks=len(chunks), injection=flag,
        )
        self.index.add(owner, chunks)
        (path.parent / _META).write_text(item.model_dump_json())
        return item

    def _chunks(self, upload_id: str, title: str, filename: str, parsed: ParsedDoc) -> list[Chunk]:
        pending: list[dict[str, object]] = []
        for section in sections(parsed.blocks):
            pieces = split(section.text)
            for part, text in enumerate(pieces):
                where = location(section, part, len(pieces))
                seq = len(pending)
                pending.append({
                    "doc_id": upload_id, "doc_type": DOC_TYPE, "title": title, "source_system": "upload",
                    "source_path": filename, "content_hash": upload_id, "chunk_id": f"{upload_id}#{seq:03d}",
                    "seq": seq, "header": f"{title} | Type: Your upload | Section: {where}", "text": text,
                    "location": where,
                })
        vectors = self._embedder.embed_documents([f"{c['header']}\n{c['text']}" for c in pending])
        return [Chunk.model_validate({**c, "vector": v}) for c, v in zip(pending, vectors, strict=True)]


def _clean(filename: str) -> str:
    """The file's own name: no folders, no control characters, at most 120 characters."""
    name = Path(filename.replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().lstrip(".")
    if len(name) > 120:
        stem, suffix = Path(name).stem, Path(name).suffix
        name = stem[: 120 - len(suffix)] + suffix
    return name


def _blocks(path: Path) -> list[DocumentBlock]:
    """The upload's blocks as indexed: screened, so planted instructions show as the marker and spans line up."""
    parsed, _ = screened(extract(path))
    return [DocumentBlock(text=b.text, level=b.level, page=b.page) for b in parsed.blocks]
