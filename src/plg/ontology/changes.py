"""Approved glossary changes, layered over the generated glossary and semantic layer at run time (issue #25).

The committed glossary (`make ontology`) is the baseline. A change approved through the approval flow is appended
to a JSON-lines file: the new version (status current) and the version it supersedes, which keeps every field but
gets `effective_to` (the day before the new one starts) and status superseded. Nothing is ever deleted: reading
the file back replaces the old version's record by ID and adds the new one. A change brings its own SQL binding,
or the new version takes over the binding of the one it supersedes.
"""

from __future__ import annotations

import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from plg.data.semantic import Binding, SemanticLayer
from plg.ontology.generated.models import GlossaryTerm
from plg.ontology.glossary import Glossary
from plg.ontology.validate import supersedes_errors

TermStatus = Literal["proposed", "current", "superseded"]


class TermSource(BaseModel):
    """Where a definition comes from."""

    document_id: str | None = None
    locator: str | None = None
    quote: str | None = None


class GlossaryVersion(BaseModel):
    """One version of a business term, as the API shows it (a plain mirror of the generated GlossaryTerm)."""

    id: str
    concept: str
    version: int
    pref_label: str
    alt_labels: list[str] = []
    definition: str
    value: str | None = None
    source: TermSource
    owned_by: str
    """Staff ID of the term owner: the only one who approves changes to it."""
    effective_from: date | None
    effective_to: date | None = None
    supersedes: str | None = None
    status: TermStatus
    in_scheme: str = "plg:glossary"

    @classmethod
    def of(cls, term: GlossaryTerm) -> GlossaryVersion:
        return cls.model_validate(
            {**term.model_dump(mode="json"), "alt_labels": term.alt_labels or []}
        )

    def term(self) -> GlossaryTerm:
        return GlossaryTerm.model_validate(self.model_dump(mode="json", exclude_none=True))


class GlossaryChange(BaseModel):
    """One approved change: the new current version and the version it supersedes, as it now stands."""

    term: GlossaryVersion
    previous: GlossaryVersion
    sql: str | None
    """The new version's own SQL binding, or None: it takes over the previous version's binding."""
    action_id: str
    approved_by: str
    at: str


def superseded(previous: GlossaryVersion, successor_from: date) -> GlossaryVersion:
    """`previous` ending the day before its successor starts."""
    return previous.model_copy(update={"status": "superseded", "effective_to": successor_from - timedelta(days=1)})


class GlossaryChanges:
    """Append-only JSON lines of approved changes. Recording a change of an already changed version is a no-op."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def entries(self) -> list[GlossaryChange]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [GlossaryChange.model_validate_json(line) for line in lines if line.strip()]

    def glossary(self, base: Glossary) -> Glossary:
        """The baseline with every approved change applied, in order."""
        return Glossary(_applied(base.terms, self.entries()))

    def layer(self, base: SemanticLayer) -> SemanticLayer:
        """The baseline semantic layer with each new version's binding: its own SQL, or its predecessor's."""
        bindings = [b.model_copy(deep=True) for b in base.bindings]
        for change in self.entries():
            if change.sql:
                note = f"Approved glossary change {change.action_id}."
                bindings.append(Binding(concepts=[change.term.id], sql=change.sql, note=note))
                continue
            inherited = next((b for b in bindings if change.previous.id in b.concepts), None)
            if inherited is not None:
                inherited.concepts.append(change.term.id)
        return base.model_copy(update={"bindings": bindings})

    def approve(self, change: GlossaryChange, base: Glossary) -> None:
        """Record `change` if its predecessor is still the current version and the result keeps every supersedes
        chain valid; raises ValueError otherwise (nothing is written)."""
        with self._lock:
            entries = self.entries()
            if any(e.action_id == change.action_id for e in entries):
                return
            now = Glossary(_applied(base.terms, entries))
            current = now.current(change.term.concept)
            if current is None or current.id != change.previous.id:
                raise ValueError(f"{change.previous.id} is no longer the current version of {change.term.concept}")
            errors = supersedes_errors(_applied(base.terms, [*entries, change]))
            if errors:
                raise ValueError("; ".join(errors))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as log:
                log.write(change.model_dump_json() + "\n")


def _applied(terms: list[GlossaryTerm], changes: list[GlossaryChange]) -> list[GlossaryTerm]:
    by_id = {t.id: t for t in terms}
    for change in changes:
        by_id[change.previous.id] = change.previous.term()
        by_id[change.term.id] = change.term.term()
    return list(by_id.values())
