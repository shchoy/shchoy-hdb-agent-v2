"""Drafts made in this process, for download. The POC keeps them in memory; each belongs to the officer who asked."""

from __future__ import annotations

from dataclasses import dataclass

from plg.drafting.model import Draft


@dataclass
class StoredDraft:
    owner: str
    draft: Draft
    docx: bytes

    @property
    def filename(self) -> str:
        return f"{self.draft.template_id}_{self.draft.draft_id[:8]}.docx"


class DraftStore:
    def __init__(self) -> None:
        self._drafts: dict[str, StoredDraft] = {}

    def add(self, owner: str, draft: Draft, docx: bytes) -> None:
        self._drafts[draft.draft_id] = StoredDraft(owner, draft, docx)

    def get(self, draft_id: str, owner: str) -> StoredDraft | None:
        stored = self._drafts.get(draft_id)
        return stored if stored and stored.owner == owner else None
