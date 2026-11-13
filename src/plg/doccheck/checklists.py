"""Checklists per application type, from the ontology's vocabularies (seeded from Tenancy Management's checklists)."""

from __future__ import annotations

from dataclasses import dataclass

from plg.ontology.generated.models import ApplicationType, SubmissionDocumentType
from plg.ontology.vocab import VocabIndex


@dataclass(frozen=True)
class Required:
    doc_code: str
    label: str
    description: str
    mandatory: bool


@dataclass(frozen=True)
class Checklist:
    app_type: str
    label: str
    documents: list[Required]


class Checklists:
    def __init__(self, checklists: list[Checklist], labels: dict[str, str]) -> None:
        self._checklists = {c.app_type: c for c in checklists}
        self.labels = labels
        """Every submission document type's label, by code."""

    def get(self, app_type: str) -> Checklist | None:
        return self._checklists.get(app_type)


def load_checklists(vocab: VocabIndex) -> Checklists:
    labels = {
        d.notation or d.id.rsplit("/", 1)[-1]: d.pref_label
        for d in vocab.concepts("plg:submission_document_types", SubmissionDocumentType)
    }
    return Checklists(
        [
            Checklist(
                app_type=a.notation or a.id.rsplit("/", 1)[-1], label=a.pref_label,
                documents=[
                    Required(r.document_type, labels.get(r.document_type, r.document_type), r.description or "", r.mandatory)
                    for r in a.required_documents or []
                ],
            )
            for a in vocab.concepts("plg:application_types", ApplicationType)
        ],
        labels,
    )
