"""Business glossary: every version of every term, and which one is in force on a date."""

from __future__ import annotations

import json
from datetime import date
from functools import cache
from pathlib import Path

from plg.ontology.generated.models import GlossaryTerm
from plg.ontology import GENERATED
from plg.ontology.vocab import normalise


class Glossary:
    def __init__(self, terms: list[GlossaryTerm]) -> None:
        self.terms = terms

    def concepts(self) -> list[str]:
        return list(dict.fromkeys(t.concept for t in self.terms))

    def versions(self, concept: str) -> list[GlossaryTerm]:
        return sorted((t for t in self.terms if t.concept == concept), key=lambda t: t.version)

    def current(self, concept: str) -> GlossaryTerm | None:
        return next((t for t in self.versions(concept) if t.status == "current"), None)

    def in_force(self, concept: str, on: date) -> GlossaryTerm | None:
        """The approved version whose effective dates cover `on`. A missing start means "since before records"."""
        for t in self.versions(concept):
            started = t.effective_from is None or t.effective_from <= on
            if t.status != "proposed" and started and (t.effective_to is None or on <= t.effective_to):
                return t
        return None

    def find(self, query: str) -> str | None:
        """The concept a query names: a concept or version ID, or a label or synonym of any version."""
        for t in self.terms:
            if query in (t.id, t.concept):
                return t.concept
        wanted = normalise(query)
        for t in self.terms:
            labels = [t.pref_label, *(t.alt_labels or []), t.concept.removeprefix("plg:")]
            if wanted in {normalise(label) for label in labels}:
                return t.concept
        return None


@cache
def load_glossary(path: Path = GENERATED / "glossary_index.json") -> Glossary:
    data = json.loads(path.read_text())
    return Glossary([GlossaryTerm.model_validate(t) for t in data["terms"]])
