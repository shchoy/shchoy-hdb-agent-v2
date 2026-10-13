"""`make ontology` refuses glossary versions whose `supersedes` chains are broken."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from plg.ontology.generated.models import GlossaryTerm
from plg.ontology.validate import supersedes_errors


def term(version: int, status: str, **overrides: Any) -> GlossaryTerm:
    fields: dict[str, Any] = {
        "id": f"plg:LodTrigger_v{version}",
        "concept": "plg:LodTrigger",
        "version": version,
        "pref_label": "Letter of Demand trigger",
        "in_scheme": "plg:glossary",
        "definition": f"LOD rule v{version}",
        "source": {"document_id": "DOC-002"},
        "owned_by": "S07",
        "effective_from": date(2024, 3, 1) if version == 1 else date(2026, 4, 1),
        "status": status,
    }
    if version > 1:
        fields["supersedes"] = f"plg:LodTrigger_v{version - 1}"
    fields.update(overrides)
    return GlossaryTerm.model_validate(fields)


V1_SUPERSEDED = {"effective_to": date(2026, 3, 31)}


def test_a_contiguous_chain_is_valid() -> None:
    assert supersedes_errors([term(1, "superseded", **V1_SUPERSEDED), term(2, "current")]) == []


def test_a_first_version_may_have_no_recorded_start() -> None:
    assert supersedes_errors([term(1, "superseded", effective_from=None, **V1_SUPERSEDED), term(2, "current")]) == []


def test_a_proposal_may_supersede_the_current_version() -> None:
    assert supersedes_errors([term(1, "current"), term(2, "proposed")]) == []


@pytest.mark.parametrize(
    ("terms", "problem"),
    [
        ([term(2, "current")], "plg:LodTrigger_v1, which does not exist"),
        ([term(1, "superseded", **V1_SUPERSEDED), term(2, "current", supersedes=None)], "must supersede"),
        (
            [term(1, "superseded", **V1_SUPERSEDED), term(2, "current", supersedes="plg:Vacant_v1"),
             term(1, "current", id="plg:Vacant_v1", concept="plg:Vacant")],
            "another concept",
        ),
        ([term(1, "current"), term(2, "current")], "2 current versions"),
        ([term(1, "superseded"), term(2, "current")], "no effective_to"),
        (
            [term(1, "superseded", effective_to=date(2026, 4, 30)), term(2, "current")],
            "should end on 2026-03-31",
        ),
        ([term(1, "superseded", **V1_SUPERSEDED)], "nothing supersedes it"),
        (
            [term(1, "superseded", **V1_SUPERSEDED), term(2, "current"), term(2, "proposed", id="plg:LodTrigger_v2b")],
            "superseded by both",
        ),
        ([term(1, "current", id="plg:LodTrigger_1")], "should be plg:LodTrigger_v1"),
        ([term(1, "current"), term(1, "current")], "duplicate id"),
        ([term(1, "superseded", **V1_SUPERSEDED), term(2, "current", effective_from=None)], "needs effective_from"),
    ],
)
def test_a_broken_chain_is_reported(terms: list[GlossaryTerm], problem: str) -> None:
    errors = supersedes_errors(terms)

    assert any(problem in error for error in errors), errors
