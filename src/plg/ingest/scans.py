"""Image-only (scanned) PDFs: Claude reads the pages through PDF input and identifies the document.

The transcript is saved by file hash, so a scan is read once: re-syncing an unchanged scan, rebuilding the
index, and opening the scan in the source viewer all reuse it.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
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
SCAN_MAX_TOKENS = 16000

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

    def parsed(self) -> ParsedDoc:
        """One level-1 heading per page, so every chunk of a scan is located by its page."""
        blocks: list[Block] = []
        for page in sorted(self.pages, key=lambda p: p.page):
            lines = [ln.strip() for ln in page.text.splitlines() if ln.strip()]
            if lines:
                blocks.append(Block(f"Page {page.page}", 1, page.page))
                blocks.extend(Block(ln, 0, page.page) for ln in lines)
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
        self._path(scan).write_text(transcript.model_dump_json(indent=2))


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
                transcript = asyncio.run(self._transcribe(scan))
            except ScanError:
                raise
            except Exception as exc:
                raise ScanError(str(exc) or type(exc).__name__) from exc
            self._store.put(scan, transcript)
        return transcript.parsed()

    async def _transcribe(self, scan: Path) -> Transcript:
        pdf = base64.standard_b64encode(scan.read_bytes()).decode()
        turn = await self._llm.complete(
            node=SCAN_NODE, tier="sonnet",
            system=[{"type": "text", "text": "You transcribe scanned documents for a search index."}],
            messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf}},
                {"type": "text", "text": SCAN_PROMPT},
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
