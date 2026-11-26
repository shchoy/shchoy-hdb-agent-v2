"""Officers' private libraries (#103): documents an officer uploads into a conversation.

An upload is kept as its file and a metadata JSON under `uploads_dir/<staff ID>/<upload ID>/`, and its passages go
into `LanceUploadIndex` (never the shared Library index). It is screened for prompt injection like an email at
ingestion: planted spans are replaced by the ingestion marker before chunking, and the upload reports the flag.
Everything is scoped to its owner: another officer's upload is "not found".

Limits: `upload_max_bytes` per file, `upload_quota_bytes` per officer. PDFs, Word, text, Markdown, email files and
PNG/JPEG images. A scanned PDF (no text layer, at most `SCAN_MAX_PAGES` pages) or an image is transcribed by Claude
(#104) once: the transcript is saved by file hash, so the same file uploaded again, the source viewer and any
re-indexing reuse it. The transcript is screened and chunked like any text; a scan's chunks are located by page.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import shutil
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from plg.documents import KINDS, ChunkLocation, DocumentBlock, DocumentKind, DocumentView, SourceFile, highlights_of
from plg.guardrails.injection import RULES, InjectionFlag, flags_in
from plg.ingest.chunking import location, sections, split
from plg.ingest.extract import ParsedDoc, extract
from plg.ingest.scans import IMAGE_TYPES, SCAN_MAX_PAGES, ScanError, TranscriptStore, transcribe
from plg.ingest.sync import screened
from plg.llm import LLMClient
from plg.search.embed import Embedder
from plg.search.models import Chunk
from plg.search.rerank import UploadScope
from plg.uploads.index import LanceUploadIndex

ACCEPTED = (".pdf", ".docx", ".txt", ".md", ".eml", *IMAGE_TYPES)
"""What can be uploaded: PDFs (text layer or scanned), Word documents, plain text, Markdown, emails and images."""

UNSUPPORTED = (
    "Only PDF, Word (.docx), text (.txt, .md), email (.eml) and image (.png, .jpg) files can be uploaded."
)
IMAGE_MAX_BYTES = 5 * 1024 * 1024 * 3 // 4
"""The largest image Claude's vision input takes: 5 MB once base64-encoded."""
_SIGNATURES = {"image/png": (b"\x89PNG\r\n\x1a\n",), "image/jpeg": (b"\xff\xd8\xff",)}
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
        llm: LLMClient | None = None,
    ) -> None:
        self._root = root
        self._embedder = embedder
        self._llm = llm
        """Transcribes scans and images; without it they are refused."""
        self._transcripts = TranscriptStore(root / "transcripts")
        self._transcribing: dict[str, asyncio.Lock] = {}
        """One lock per file hash being transcribed."""
        self.max_bytes = max_bytes
        self._quota = quota_bytes
        self._vector_weight = vector_weight
        self._index: LanceUploadIndex | None = None
        self._lock = threading.Lock()
        self._reserved: dict[str, int] = {}
        """Bytes of each officer's uploads still being read: counted against the space until they are recorded."""

    @property
    def index(self) -> LanceUploadIndex:
        """Opened on first use, so plg-api starts without touching it."""
        with self._lock:  # one index (and so one write lock) however many uploads arrive at once
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
            content_type=item.content_type, blocks=self._blocks(source.path), upload=True,
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
        blocks = self._blocks(source.path)
        highlights = highlights_of(blocks, chunk, begin, finish)
        page = next((blocks[h.block].page for h in highlights if blocks[h.block].page is not None), None)
        return ChunkLocation(
            doc_id=upload_id, chunk_id=chunk_id, location=chunk.location, quote=chunk.text[begin:finish], page=page,
            highlights=highlights,
        )

    @property
    def quota_bytes(self) -> int:
        return self._quota

    # ------------------------------------------------------------------ managing (#106)
    def rename(self, owner: str, upload_id: str, title: str) -> Upload | None:
        """Give the upload the officer's own title: shown in My documents, the source viewer, and the passages new
        searches and citations carry."""
        index = self.index  # opened outside the lock: opening takes it
        with self._lock:
            item = self.get(owner, upload_id)
            if item is None:
                return None
            item = item.model_copy(update={"title": title})
            index.retitle(owner, upload_id, title)
            _write_meta(self._dir(owner, upload_id) / _META, item)
        return item

    def delete(self, owner: str, upload_id: str) -> bool:
        """Remove the upload: its passages leave search, its file and metadata go, and so does its transcript unless
        another upload holds the same file. False if the officer has no such upload."""
        index = self.index
        with self._lock:
            source = self.file(owner, upload_id)
            if self.get(owner, upload_id) is None:
                return False
            digest = hashlib.sha256(source.path.read_bytes()).hexdigest() if source is not None else None
            index.remove(owner, upload_id)  # first: should it fail, the upload is still listed and can be deleted again
            folder = self._dir(owner, upload_id)
            (folder / _META).unlink()  # from here on it is not found, so nothing new can attach or open it
            shutil.rmtree(folder, ignore_errors=True)
            adding = any(self._reserved.values())
        # An upload still being read may need the transcript, and another may hold the same file: then it stays.
        if digest is not None and not adding and not self._shared(digest):
            self._transcripts.remove_digest(digest)
        return True

    def _shared(self, digest: str) -> bool:
        """Whether a remaining upload (any officer's) is the file with this hash. Compared here, never shown."""
        for meta in self._root.glob(f"*/upload-*/{_META}"):
            other = meta.parent / Upload.model_validate_json(meta.read_text()).filename
            if other.is_file() and hashlib.sha256(other.read_bytes()).hexdigest() == digest:
                return True
        return False

    # ------------------------------------------------------------------ adding
    def too_large(self, filename: str) -> str:
        return f"{filename} is larger than {size_label(self.max_bytes)}, the most one file may be."

    async def add(self, owner: str, filename: str, data: bytes) -> Upload:
        """Store, screen, chunk and index the file; `UploadRefused` says why it can't be taken."""
        name = _clean(filename)
        suffix = Path(name).suffix.lower()
        if not name or suffix not in ACCEPTED:
            raise UploadRefused(415, UNSUPPORTED)
        if len(data) > self.max_bytes:
            raise UploadRefused(413, self.too_large(name))
        upload_id = f"upload-{uuid.uuid4().hex[:16]}"
        folder = self._dir(owner, upload_id)
        path = await asyncio.to_thread(self._store, owner, folder / name, data)
        try:
            item = await self._ingest(owner, upload_id, path, len(data))
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        finally:  # recorded (its upload.json now counts) or removed
            with self._lock:
                self._reserved[owner] -= len(data)
        return item

    def _store(self, owner: str, path: Path, data: bytes) -> Path:
        """Write the file, if the officer's space allows it (off the event loop: the lock is a thread lock)."""
        name = path.name
        with self._lock:  # the space check and the reservation are one step, so uploads sent at once can't overrun it
            used = sum(u.size for u in self.of(owner)) + self._reserved.get(owner, 0)
            if used + len(data) > self._quota:
                left = max(self._quota - used, 0)
                raise UploadRefused(
                    413,
                    f"Not enough space for {name}: your uploads may take {size_label(self._quota)} in all "
                    f"and {size_label(left)} is left.",
                )
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
            self._reserved[owner] = self._reserved.get(owner, 0) + len(data)
        return path

    async def _ingest(self, owner: str, upload_id: str, path: Path, size: int) -> Upload:
        parsed = await self._read(path)
        return await asyncio.to_thread(self._index_parsed, owner, upload_id, path, size, parsed)

    async def _read(self, path: Path) -> ParsedDoc:
        """The file's text: extracted, or Claude's transcript for a scan or an image."""
        suffix = path.suffix.lower()
        if suffix in IMAGE_TYPES:
            data = await asyncio.to_thread(path.read_bytes)
            if not data.startswith(_SIGNATURES[IMAGE_TYPES[suffix]]):
                raise UploadRefused(422, f"{path.name} could not be read. Is it a valid {suffix} image?")
            if len(data) > IMAGE_MAX_BYTES:
                raise UploadRefused(
                    413, f"{path.name} is larger than {size_label(IMAGE_MAX_BYTES)}, the most an image may be."
                )
            return await self._transcript(path, paged=False)
        try:
            parsed = await asyncio.to_thread(extract, path)
        except Exception:
            raise UploadRefused(422, f"{path.name} could not be read. Is it a valid {path.suffix} file?") from None
        if parsed.blocks:
            return parsed
        if suffix != ".pdf":
            raise UploadRefused(422, f"{path.name} has no text.")
        try:
            pages = await asyncio.to_thread(_page_count, path)
        except Exception:
            raise UploadRefused(422, f"{path.name} could not be read. Is it a valid .pdf file?") from None
        if pages > SCAN_MAX_PAGES:
            raise UploadRefused(
                422, f"{path.name} is a scan of {pages} pages; scans of at most {SCAN_MAX_PAGES} pages can be read."
            )
        return await self._transcript(path, paged=True)

    async def _transcript(self, path: Path, *, paged: bool) -> ParsedDoc:
        """Read once: a file transcribed before (by any upload with the same content) is never sent again. The same
        file uploaded twice at once waits for the first transcription instead of starting a second."""
        digest = await asyncio.to_thread(lambda: hashlib.sha256(path.read_bytes()).hexdigest())
        lock = self._transcribing.setdefault(digest, asyncio.Lock())
        async with lock:
            return await self._transcript_once(path, paged=paged)

    async def _transcript_once(self, path: Path, *, paged: bool) -> ParsedDoc:
        saved = await asyncio.to_thread(self._transcripts.get, path)
        if saved is None:
            if self._llm is None:
                raise UploadRefused(422, f"{path.name} is a scan or image, and none can be read here.")
            try:
                saved = await transcribe(self._llm, path)
            except ScanError as exc:
                raise UploadRefused(422, f"{path.name} could not be read: {exc}. Try a clearer copy.") from None
            except Exception:
                raise UploadRefused(
                    422, f"{path.name} could not be read: the transcription failed. Try again or a clearer copy."
                ) from None
            await asyncio.to_thread(self._transcripts.put, path, saved)
        return saved.parsed(paged=paged)

    def _blocks(self, path: Path) -> list[DocumentBlock]:
        """The upload's blocks as indexed: screened, so planted instructions show as the marker and spans line up.
        A scan or image shows its saved transcript (Claude is never called here)."""
        suffix = path.suffix.lower()
        parsed = extract(path) if suffix not in IMAGE_TYPES else ParsedDoc([])
        if not parsed.blocks and (suffix == ".pdf" or suffix in IMAGE_TYPES):
            saved = self._transcripts.get(path)
            parsed = saved.parsed(paged=suffix == ".pdf") if saved else parsed
        parsed, _ = screened(parsed)
        return [DocumentBlock(text=b.text, level=b.level, page=b.page) for b in parsed.blocks]

    def _index_parsed(self, owner: str, upload_id: str, path: Path, size: int, parsed: ParsedDoc) -> Upload:
        parsed, flagged = screened(parsed)
        kind, content_type = KINDS[path.suffix.lower()]
        title = parsed.title or path.name
        chunks = self._chunks(upload_id, title, path.name, parsed)
        flag = None
        if flagged:
            found = {r for c in chunks for r in flags_in(c.text) or []}
            rules = [r for r in RULES if r in found]
            flag = InjectionFlag(source="document", rules=rules, doc_id=upload_id, title=title)
        item = Upload(
            upload_id=upload_id, filename=path.name, title=title, kind=kind, content_type=content_type, size=size,
            uploaded_at=datetime.now(UTC), chunks=len(chunks), injection=flag,
        )
        self.index.add(owner, chunks)
        _write_meta(path.parent / _META, item)
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


def _write_meta(path: Path, item: Upload) -> None:
    """Replaced in one step: a reader never sees half of it."""
    partial = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    partial.write_text(item.model_dump_json())
    partial.replace(path)


def _page_count(path: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(path).pages)
