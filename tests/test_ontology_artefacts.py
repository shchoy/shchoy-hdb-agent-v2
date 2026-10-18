"""The artefacts `make ontology` committed under plg/ontology/generated, checked against poc-data ground truth.

These read the generated files; they never re-run the generator.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from plg.config import REPO_ROOT, Settings
from plg.ontology.generated.models import ApplicationType, DefectCategory, Trade
from plg.ontology.glossary import Glossary, load_glossary
from plg.ontology.validate import supersedes_errors
from plg.ontology import GENERATED
from plg.ontology.vocab import VocabIndex, load_vocab

MASTER = REPO_ROOT / "poc-data" / "_master"


def master(name: str) -> Any:
    return json.loads((MASTER / f"{name}.json").read_text())


def records(sql: str) -> list[tuple[Any, ...]]:
    with sqlite3.connect(f"file:{Settings.from_env().records_db}?mode=ro", uri=True) as db:
        return db.execute(sql).fetchall()


def generated(name: str) -> Any:
    return json.loads((GENERATED / name).read_text())


@pytest.fixture(scope="module")
def vocab() -> VocabIndex:
    return load_vocab()


@pytest.fixture(scope="module")
def glossary() -> Glossary:
    return load_glossary()


# ---------------------------------------------------------------- vocabularies


def test_defect_categories_match_the_taxonomy(vocab: VocabIndex) -> None:
    teams = {c.id: c.pref_label for c in vocab.scheme("plg:teams")}
    vendors = {c.id: c.pref_label for c in vocab.scheme("plg:vendors")}
    categories = vocab.concepts("plg:defect_categories", DefectCategory)

    actual = [
        {
            "code": c.notation,
            "category": c.pref_label,
            "examples": c.examples,
            "team": teams[c.handled_by],
            "vendor": vendors[c.default_vendor] if c.default_vendor else "",
            "default_severity": c.default_severity,
            "iems": c.iems,
        }
        for c in categories
    ]
    assert actual == master("taxonomy_and_checklists")["taxonomy"]


def test_application_types_require_the_checklist_documents(vocab: VocabIndex) -> None:
    submission_docs = {c.notation for c in vocab.scheme("plg:submission_document_types")}
    app_types = vocab.concepts("plg:application_types", ApplicationType)

    actual = {
        a.notation: [[d.document_type, d.description, d.mandatory] for d in a.required_documents or []]
        for a in app_types
    }
    assert actual == master("taxonomy_and_checklists")["checklists"]
    assert {d[0] for items in actual.values() for d in items} == submission_docs


def test_trades_match_plg_records(vocab: VocabIndex) -> None:
    trades = vocab.concepts("plg:trades", Trade)

    actual = {(t.pref_label, t.trade_group, "|".join(t.allowed_unit_types or [])) for t in trades}
    assert actual == set(records("SELECT trade, trade_group, allowed_unit_types FROM trades"))


@pytest.mark.parametrize(
    ("scheme", "sql"),
    [
        ("plg:unit_statuses", "SELECT DISTINCT status FROM units"),
        ("plg:unit_types", "SELECT DISTINCT unit_type FROM units"),
        ("plg:letter_types", "SELECT DISTINCT letter_type FROM letters"),
    ],
)
def test_record_code_lists_match_plg_records(vocab: VocabIndex, scheme: str, sql: str) -> None:
    assert {c.notation for c in vocab.scheme(scheme)} == {row[0] for row in records(sql)}


# ---------------------------------------------------------------- synonyms


@pytest.mark.parametrize(
    ("text", "concept"),
    [
        ("LOD", "plg:letter_type/letter-of-demand"),
        ("LOD", "plg:LodTrigger"),
        ("letter of demand", "plg:letter_type/letter-of-demand"),
        ("ceiling leak", "plg:category/SEP"),
        ("Ceiling  Leak", "plg:category/SEP"),
        ("seepage", "plg:category/SEP"),
        ("A&A", "plg:app_type/ALTERATION"),
        ("BBT", "plg:trade/bubble-tea"),
        ("vacancy", "plg:Vacant"),
        ("arrears buckets", "plg:ArrearsAgeingBucket"),
    ],
)
def test_synonyms_resolve_to_concepts(vocab: VocabIndex, text: str, concept: str) -> None:
    assert concept in [c.id for c in vocab.resolve(text)]


def test_unknown_words_resolve_to_nothing(vocab: VocabIndex) -> None:
    assert vocab.resolve("durian") == []


# ---------------------------------------------------------------- glossary


def test_glossary_terms_are_versioned_with_source_owner_and_dates(glossary: Glossary) -> None:
    staff_ids = {s["id"] for s in master("staff")}
    with (REPO_ROOT / "poc-data" / "_manifest.csv").open() as f:
        document_ids = {row["id"] for row in csv.DictReader(f)}

    assert supersedes_errors(glossary.terms) == []
    for t in glossary.terms:
        assert t.owned_by in staff_ids, t.id
        assert t.source.document_id in document_ids, t.id
    # Only the pre-April 2026 vacancy definition has no recorded start.
    assert [t.id for t in glossary.terms if t.effective_from is None] == ["plg:Vacant_v1"]


@pytest.mark.parametrize(
    ("concept", "current_value", "effective_from", "superseded_value"),
    [
        ("plg:Vacant", "excludes units under tender", date(2026, 4, 15), "includes units under tender"),
        ("plg:LodTrigger", "60 days overdue", date(2026, 4, 1), "45 days overdue"),
        ("plg:DisplayArea", "1.0 m (NC units); 0.6 m (void-deck shops)", date(2026, 8, 1), "0.6 m"),
        ("plg:ArrearsTerminationThreshold", "arrears > 3 x monthly rent x 1.09", date(2026, 4, 1),
         "arrears > 2 x monthly rent x 1.09"),
    ],
)
def test_redefined_terms_keep_their_history(
    glossary: Glossary, concept: str, current_value: str, effective_from: date, superseded_value: str
) -> None:
    v1, v2 = glossary.versions(concept)

    assert glossary.current(concept) == v2
    assert (v2.value, v2.effective_from, v2.supersedes) == (current_value, effective_from, v1.id)
    assert (v1.value, v1.status) == (superseded_value, "superseded")


def test_the_definition_in_force_depends_on_the_date(glossary: Glossary) -> None:
    def vacant_on(day: date) -> str | None:
        term = glossary.in_force("plg:Vacant", day)
        return term.id if term else None

    assert vacant_on(date(2020, 1, 1)) == "plg:Vacant_v1"
    assert vacant_on(date(2026, 4, 14)) == "plg:Vacant_v1"
    assert vacant_on(date(2026, 8, 31)) == "plg:Vacant_v2"


def test_the_seed_covers_the_design_terms(glossary: Glossary) -> None:
    seed = {"plg:Vacant", "plg:ArrearsAgeingBucket", "plg:LodTrigger", "plg:DisplayArea", "plg:Arrears",
            "plg:ArrearsTerminationThreshold", "plg:OccupancyRate", "plg:UnderTender", "plg:NotLettable"}

    assert seed <= set(glossary.concepts())
    assert glossary.versions("plg:ArrearsAgeingBucket")[0].value == "0-30, 31-60, 61-90, >90 days overdue"


# ---------------------------------------------------------------- graph allow-list, schemas, card


def test_allow_list_admits_only_ontology_relations() -> None:
    allow = generated("allow_list.json")
    labels = set(allow["node_labels"])
    triples = {(e["domain"], e["type"], e["range"]) for e in allow["edges"]}

    assert 20 <= len(labels) <= 30
    assert len({e["type"] for e in allow["edges"]}) >= 30
    assert {"Entity", "Document", "Concept"}.isdisjoint(labels)
    for edge in allow["edges"]:
        assert set(edge["domain_labels"]) | set(edge["range_labels"]) <= labels, edge
    assert {
        ("Document", "SUPERSEDES", "Document"),
        ("GlossaryTerm", "SUPERSEDES", "GlossaryTerm"),
        ("Circular", "OVERRIDES", "Clause"),
        ("Precedent", "APPLIES", "Clause"),
        ("Staff", "WORKED_ON", "Entity"),
        ("FeedbackCase", "IN_CATEGORY", "DefectCategory"),
    } <= triples
    supersedes = next(e for e in allow["edges"] if e["type"] == "SUPERSEDES" and e["domain"] == "Document")
    assert {"Policy", "Sop", "Circular", "Template"} <= set(supersedes["domain_labels"])
    assert supersedes["cardinality"] == "0..1"


def test_extraction_schemas_cover_the_extracted_edges_with_evidence() -> None:
    allow = generated("allow_list.json")
    extracted = sorted({e["type"] for e in allow["edges"] if e["extracted"]})

    assert extracted == ["APPLIES", "OVERRIDES", "SUPERSEDES"]
    for edge in extracted:
        schema = generated(f"extraction/{edge.lower()}.json")
        item = schema["properties"]["edges"]["items"]
        assert item["properties"]["type"]["const"] == edge
        assert {"source_id", "target_id", "evidence_chunk_id", "evidence_quote"} <= set(item["required"])


def test_tool_io_json_schema_defines_every_class() -> None:
    schema = generated("plg.schema.json")

    assert {"GlossaryTerm", "Tenancy", "DefectCategory", "SourceCitation"} <= set(schema["$defs"])


def test_ontology_card_is_compact_and_current(glossary: Glossary) -> None:
    card = (GENERATED / "ontology_card.md").read_text()
    allow = generated("allow_list.json")

    assert len(card) < 12_000
    for label in allow["node_labels"]:
        assert label in card
    for edge in allow["edges"]:
        assert edge["type"] in card
    assert "plg:LodTrigger_v2" in card and "[60 days overdue]" in card
    for term in glossary.terms:
        assert (term.id in card) == (term.status == "current"), term.id


def test_generated_models_reject_values_outside_the_ontology() -> None:
    with pytest.raises(ValueError):
        DefectCategory.model_validate(
            {"id": "plg:category/X", "pref_label": "X", "in_scheme": "plg:defect_categories",
             "default_severity": "Urgent", "handled_by": "plg:team/m-e"}
        )


def test_generated_files_are_marked_generated() -> None:
    for path in [GENERATED / "models.py", GENERATED / "ontology_card.md"]:
        assert "make ontology" in Path(path).read_text().splitlines()[0]
