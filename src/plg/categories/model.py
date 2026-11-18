"""The Library's document categories: the saved output of `plg categorise`, read by plg-api and `category_summary`."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from plg.search.models import DocStatus, DocumentMeta


class CategoryDocument(BaseModel):
    """A document as the Library lists it."""

    doc_id: str
    title: str
    doc_type: str
    status: DocStatus

    @classmethod
    def of(cls, doc: DocumentMeta) -> CategoryDocument:
        return cls(doc_id=doc.doc_id, title=doc.title, doc_type=doc.doc_type, status=doc.status)


class Category(BaseModel):
    id: str
    """`CAT-` + a hash of its members: the same group of documents keeps its ID across runs."""
    name: str
    description: str
    """One sentence: what the documents are about."""
    summary: str
    """A few sentences on what the documents say, written when the category was named."""
    documents: list[CategoryDocument]


class Categorisation(BaseModel):
    categorised_at: datetime | None = None
    """When `plg categorise` last ran; None if it never has."""
    categories: list[Category] = []
    uncategorised: list[CategoryDocument] = []
    """Documents no category took (too unlike the rest), or indexed since the last run."""

    def overlay(self, documents: list[DocumentMeta]) -> Categorisation:
        """This categorisation with each document's title and status as the index holds them now; documents indexed
        since the run are uncategorised."""
        live = {d.doc_id: CategoryDocument.of(d) for d in documents}
        placed = {doc.doc_id for c in self.categories for doc in c.documents}
        categories = [
            c.model_copy(update={"documents": [live[d.doc_id] for d in c.documents if d.doc_id in live]})
            for c in self.categories
        ]
        uncategorised = [doc for doc_id, doc in live.items() if doc_id not in placed]
        return self.model_copy(update={"categories": categories, "uncategorised": uncategorised})


def load_categorisation(path: Path) -> Categorisation:
    """The saved categorisation, or an empty one if `plg categorise` has not run."""
    if not path.is_file():
        return Categorisation()
    return Categorisation.model_validate_json(path.read_text())


def save_categorisation(path: Path, categorisation: Categorisation) -> None:
    """Replaced atomically, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(categorisation.model_dump_json(indent=2))
    os.replace(tmp, path)
