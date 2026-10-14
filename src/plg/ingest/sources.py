"""`DocumentSource` adapters: the SharePoint and Lotus Notes mocks, both reading the corpus folders."""

from __future__ import annotations

import email
import email.policy
import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from plg.ingest.extract import TEXT_SUFFIXES
from plg.search.models import SourceSystem

SHAREPOINT_LISTING = Path("exports/sharepoint_document_listing.json")
NOTES_MAILBOX = Path("emails")
# Application bundles are checked per application by the doc-check flow, not searched as library knowledge.
EXCLUDED_LIBRARIES = {"Tenant Submissions"}


@dataclass(frozen=True)
class SourceDocument:
    doc_id: str
    source_system: SourceSystem
    path: Path
    rel_path: str
    """Path relative to the corpus root."""
    title: str | None


@dataclass(frozen=True)
class Skipped:
    rel_path: str
    reason: str


class DocumentSource(Protocol):
    def documents(self) -> Iterator[SourceDocument | Skipped]: ...


def generator_artefact(rel_path: str) -> bool:
    """Generator ground truth and manifests (`_master/`, `_report.md`, ...) are never indexed."""
    return any(part.startswith("_") for part in Path(rel_path).parts)


def _admit(doc: SourceDocument) -> SourceDocument | Skipped:
    if generator_artefact(doc.rel_path):
        return Skipped(doc.rel_path, "generator ground truth, never indexed")
    if not doc.path.is_file():
        return Skipped(doc.rel_path, "listed but missing")
    return doc


class SharePointSource:
    """Mock SharePoint: the library listing export, with each item's file under the corpus root."""

    def __init__(self, corpus_dir: Path) -> None:
        self._root = corpus_dir

    def documents(self) -> Iterator[SourceDocument | Skipped]:
        listing = json.loads((self._root / SHAREPOINT_LISTING).read_text())
        for item in listing["items"]:
            rel_path = item["corpusPath"]
            # Spreadsheets are structured data, loaded into DuckDB rather than searched as text.
            if item["library"] in EXCLUDED_LIBRARIES or Path(rel_path).suffix.lower() not in TEXT_SUFFIXES:
                continue
            yield _admit(SourceDocument(
                doc_id=item["itemId"], source_system="sharepoint", path=self._root / rel_path,
                rel_path=rel_path, title=item["title"],
            ))


class LotusNotesSource:
    """Mock Lotus Notes: one .eml per message, one folder per thread. IDs derive from the Message-ID."""

    def __init__(self, corpus_dir: Path) -> None:
        self._root = corpus_dir

    def documents(self) -> Iterator[SourceDocument | Skipped]:
        for path in sorted((self._root / NOTES_MAILBOX).rglob("*.eml")):
            message = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
            rel_path = path.relative_to(self._root).as_posix()
            message_id = str(message["Message-ID"] or rel_path)
            yield _admit(SourceDocument(
                doc_id="LN-" + hashlib.sha1(message_id.encode()).hexdigest()[:12],
                source_system="lotus_notes", path=path, rel_path=rel_path,
                title=str(message["Subject"] or path.stem),
            ))
