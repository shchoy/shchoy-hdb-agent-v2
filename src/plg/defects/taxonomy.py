"""The defect taxonomy as the classifier and the i-EMS tickets use it: each feedback category with its routing team,
term-contract vendor and default severity, from the ontology's vocabularies. i-EMS categories are maintenance
defects; the others (hygiene, encroachment, noise, common area, enquiries) are handled without a ticket."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from plg.ontology.generated.models import DefectCategory, Team, Vendor
from plg.ontology.vocab import VocabIndex

Severity = Literal["Low", "Medium", "High", "Critical"]

SEVERITY_RANK: dict[Severity, int] = {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}

SLA_DAYS: dict[Severity, int] = {"Critical": 1, "High": 3, "Medium": 7, "Low": 14}
"""i-EMS completion SLA by ticket priority, as every ticket in PLG Records applies it."""


class Category(BaseModel):
    code: str
    label: str
    examples: str
    team: str
    vendor: str | None
    default_severity: Severity
    iems: bool
    """A maintenance defect, raised as an i-EMS ticket."""


class Taxonomy:
    def __init__(self, categories: list[Category]) -> None:
        self.categories = {c.code: c for c in categories}

    def get(self, code: str) -> Category | None:
        return self.categories.get(code)

    @property
    def codes(self) -> list[str]:
        return list(self.categories)

    def describe(self) -> str:
        """One line per category, for the classifier's prompt."""
        return "\n".join(
            f"- {c.code} {c.label} (e.g. {c.examples}): {'i-EMS defect' if c.iems else 'not a maintenance defect'}, "
            f"default severity {c.default_severity}, handled by {c.team}"
            for c in self.categories.values()
        )


def load_taxonomy(vocab: VocabIndex) -> Taxonomy:
    teams = {t.id: t.pref_label for t in vocab.concepts("plg:teams", Team)}
    vendors = {v.id: v.pref_label for v in vocab.concepts("plg:vendors", Vendor)}
    return Taxonomy([
        Category(
            code=c.notation or c.id.rsplit("/", 1)[-1], label=c.pref_label, examples=c.examples or "",
            team=teams[str(c.handled_by)], vendor=vendors.get(str(c.default_vendor)) if c.default_vendor else None,
            default_severity=str(c.default_severity),  # type: ignore[arg-type]
            iems=bool(c.iems),
        )
        for c in vocab.concepts("plg:defect_categories", DefectCategory)
    ])
