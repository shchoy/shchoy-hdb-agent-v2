"""Image-only (scanned) PDFs and photos: Claude reads them through PDF input or vision and identifies the document.

The transcript is saved by file hash, so a scan is read once: re-syncing an unchanged scan, rebuilding the
index, uploading the same file again (#104) and opening it in the source viewer all reuse it.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
from pathlib import Path

from pydantic import BaseModel, Field

from plg.ingest.extract import Block, ParsedDoc
from plg.llm import LLMClient

SCAN_NODE = "ingest_scan"
SCAN_PROMPT = (
    "This PDF is a scan of a document held by the Properties & Land Group. Transcribe every page faithfully, "
    "page by page, keeping headings, clause numbers and figures exactly as printed. Do not summarise, translate "
    "or correct. Mark text you cannot read as [illegible]. Then identify the document: its title and, where the "
    "scan shows them, its document-control fields (Document ID, Version, Effective date, Date). "
    "Record the result with the record_transcript tool."
)
IMAGE_PROMPT = (
    "This image is a photo or scan of a page, notice or whiteboard an officer of the Properties & Land Group "
    "uploaded. Transcribe all of its text faithfully, keeping headings, numbers and figures exactly as shown, "
    "as page 1. Do not summarise, translate or correct. Mark text you cannot read as [illegible]. Then give it a "
    "title a reader would cite it by. Record the result with the record_transcript tool."
)
SCAN_MAX_TOKENS = 16000
SCAN_MAX_PAGES = 100
"""The most pages Claude's PDF input reads in one request: longer scans are refused before any call."""
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

TRANSCRIPT_TOOL = {
    "name": "record_transcript",
    "description": "Record the transcription and identification of the scanned document.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "The document's title as a reader would cite it."},
            "fields": {
                "type": "object",
                "description": "Document-control fields shown on the scan, e.g. Document ID, Version, Effective date, Date.",
                "additionalProperties": {"type": "string"},
            },
            "pages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "page": {"type": "integer", "description": "1-based page number in the PDF."},
                        "text": {"type": "string", "description": "The page's text, one line per printed line."},
                    },
                    "required": ["page", "text"],
                },
            },
        },
        "required": ["title", "pages"],
    },
}


class TranscriptPage(BaseModel):
    page: int
    text: str


class Transcript(BaseModel):
    title: str
    fields: dict[str, str] = Field(default_factory=dict)
    pages: list[TranscriptPage]

    def parsed(self, *, paged: bool = True) -> ParsedDoc:
        """One level-1 heading per page, so every chunk of a scan is located by its page. A photo (`paged=False`)
        has no pages: its lines only."""
        blocks: list[Block] = []
        for page in sorted(self.pages, key=lambda p: p.page):
            lines = [ln.strip() for ln in page.text.splitlines() if ln.strip()]
            if lines and paged:
                blocks.append(Block(f"Page {page.page}", 1, page.page))
            blocks.extend(Block(ln, 0, page.page if paged else None) for ln in lines)
        return ParsedDoc(blocks, dict(self.fields), self.title)


class TranscriptStore:
    """Transcripts on disk, one JSON file per scan, named by the scan's content hash."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory

    def _path(self, scan: Path) -> Path:
        return self._dir / f"{hashlib.sha256(scan.read_bytes()).hexdigest()}.json"

    def get(self, scan: Path) -> Transcript | None:
        path = self._path(scan)
        return Transcript.model_validate_json(path.read_text()) if path.is_file() else None

    def put(self, scan: Path, transcript: Transcript) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path(scan)
        partial = path.with_suffix(f".{uuid.uuid4().hex}.tmp")  # replaced in one step: a reader never sees half of it
        partial.write_text(transcript.model_dump_json(indent=2))
        partial.replace(path)


class SavedScans:
    """Saved transcripts only, never calling Claude: what the source viewer shows for a scan."""

    def __init__(self, store: TranscriptStore) -> None:
        self._store = store

    def read(self, scan: Path) -> ParsedDoc:
        transcript = self._store.get(scan)
        return transcript.parsed() if transcript else ParsedDoc([])


class ScanError(Exception):
    """A scan could not be turned into a transcript (Claude failed, or returned nothing usable)."""


class ScanReader:
    """Reads scans through `LLMClient`, or from the saved transcript if the scan was read before."""

    def __init__(self, llm: LLMClient, store: TranscriptStore) -> None:
        self._llm = llm
        self._store = store

    def read(self, scan: Path) -> ParsedDoc:
        transcript = self._store.get(scan)
        if transcript is None:
            try:
                transcript = asyncio.run(transcribe(self._llm, scan))
            except ScanError:
                raise
            except Exception as exc:
                raise ScanError(str(exc) or type(exc).__name__) from exc
            self._store.put(scan, transcript)
        return transcript.parsed()

def media_block(path: Path) -> dict[str, object]:
    """The file as a Messages API input block: a PDF document, or an image for vision."""
    data = base64.standard_b64encode(path.read_bytes()).decode()
    image = IMAGE_TYPES.get(path.suffix.lower())
    if image is not None:
        return {"type": "image", "source": {"type": "base64", "media_type": image, "data": data}}
    return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data}}


async def transcribe(llm: LLMClient, path: Path) -> Transcript:
    """Claude's transcript of a scanned PDF or an image; `ScanError` when it returns nothing usable."""
    image = path.suffix.lower() in IMAGE_TYPES
    media = await asyncio.to_thread(media_block, path)  # up to 20 MB read and encoded: off the event loop
    turn = await llm.complete(
        node=SCAN_NODE, tier="sonnet",
        system=[{"type": "text", "text": "You transcribe scanned documents for a search index."}],
        messages=[{"role": "user", "content": [
            media, {"type": "text", "text": IMAGE_PROMPT if image else SCAN_PROMPT},
        ]}],
        tools=[TRANSCRIPT_TOOL],
        tool_choice={"type": "tool", "name": TRANSCRIPT_TOOL["name"]},
        max_tokens=SCAN_MAX_TOKENS,
    )
    call = next((b for b in turn.content if b["type"] == "tool_use" and b["name"] == TRANSCRIPT_TOOL["name"]), None)
    if call is None:
        raise ScanError("Claude returned no transcript")
    transcript = Transcript.model_validate(call["input"])
    if not transcript.parsed().blocks:
        raise ScanError("the transcript has no text")
    return transcript
