"""Precedent search over the entity graph: `GraphStore.find_precedents` contract tests.

The graph holds the precedents read from the synced compendium by `plg graph lineage` (Haiku scripted, see
test_policy_lineage). Expected cases come from `_master/key_entities.json` (bubble_tea_nc = NC-PI-1), the
`_report.md` precedent questions and the Mutiara change-of-trade email thread.
"""

from __future__ import annotations

import re
from datetime import date

from plg.entities import cypher
from plg.entities.local import LocalGraphStore
from plg.entities.writer import GraphWriter
from plg.ingest.lineage import LineageReport
from tests.test_policy_lineage import graph_dir, haiku, lineage  # noqa: F401  (fixtures)

Lineage = tuple[LocalGraphStore, GraphWriter, LineageReport]


def test_bubble_tea_precedents_for_nc_pi_1(lineage: Lineage) -> None:  # noqa: F811
    graph, _, _ = lineage
    found = graph.find_precedents(trade="Bubble Tea", nc="NC-PI-1", issue="change of trade")

    same_nc, other_nc = found[:2]
    assert same_nc.precedent_id == "PC-2024-009"
    assert set(same_nc.matched_on) == {"trade", "nc", "issue"}
    assert same_nc.decided_on == date(2024, 5, 14)
    assert same_nc.decision == "Rejected."
    assert "concentration limit of 2 per NC (POL-001 cl. 5.1)" in same_nc.reasoning
    assert same_nc.nc_id == "NC-PI-1"

    assert other_nc.precedent_id == "PC-2025-014"
    assert set(other_nc.matched_on) == {"trade", "issue"}
    assert other_nc.decision == "Approved."
    assert other_nc.nc_id == "NC-BV-3"
    assert "Within the concentration limit (2nd outlet)" in other_nc.reasoning


def test_each_precedent_points_at_its_compendium_page(lineage: Lineage) -> None:  # noqa: F811
    graph, _, _ = lineage
    [first, *_] = graph.find_precedents(trade="Bubble Tea", nc="NC-PI-1")
    assert first.precedent_id == "PC-2024-009"
    assert first.location.endswith("(p. 5)")
    assert first.chunk_id.startswith(f"{first.doc_id}#")
    assert "Provision shop at Pasir Indah Central NC" in first.facts


def test_other_change_of_trade_cases_follow_the_bubble_tea_ones(lineage: Lineage) -> None:  # noqa: F811
    graph, _, _ = lineage
    ids = [p.precedent_id for p in graph.find_precedents(trade="Bubble Tea", nc="NC-PI-1", issue="change of trade")]
    assert ids[:2] == ["PC-2024-009", "PC-2025-014"]
    assert {"PC-2024-034", "PC-2025-035", "PC-2026-044"} <= set(ids[2:])
    assert "PC-2026-039" not in ids  # an unauthorised trade in the same town is not a change of trade


def test_names_resolve_like_ids(lineage: Lineage) -> None:  # noqa: F811
    graph, _, _ = lineage
    by_name = graph.find_precedents(trade="bubble tea", nc="Pasir Indah Central NC")
    assert [p.precedent_id for p in by_name[:2]] == ["PC-2024-009", "PC-2025-014"]


def test_the_fire_rebate_precedent_records_why_the_rebate_was_given(lineage: Lineage) -> None:  # noqa: F811
    graph, _, _ = lineage
    [first, *_] = graph.find_precedents(issue="fire rent rebate")
    assert first.precedent_id == "PC-2025-019"
    assert first.decision == "50% rent rebate for one month approved."
    assert "did not result from tenant negligence" in first.reasoning


def test_nothing_matches_an_unrelated_situation(lineage: Lineage) -> None:  # noqa: F811
    graph, _, _ = lineage
    assert graph.find_precedents(issue="parking season ticket") == []
    assert graph.find_precedents() == []


def test_a_sublet_salon_finds_the_unauthorised_subletting_precedent(lineage: Lineage) -> None:  # noqa: F811
    graph, _, _ = lineage
    [first, *_] = graph.find_precedents(trade="Hair Salon", issue="sublet")
    assert first.precedent_id == "PC-2024-021"
    assert first.decision == "Composition fee S$500; ordered to regularise within 14 days."


def test_the_precedent_cypher_takes_the_resolved_trade_and_nc() -> None:
    text = cypher.TEMPLATES["find_precedents"]
    assert {"$trade", "$nc", "$issue_given"} <= set(re.findall(r"\$\w+", text))
    assert "$nc" in cypher.TEMPLATES["nc_town"]
