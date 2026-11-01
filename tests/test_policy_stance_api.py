"""Policy lineage and current stance through plg-api: the knowledge agent reads a policy's lineage from the entity
graph next to the corpus, and the client receives a `policy_stance` event for the card in the Sources panel.

Claude is scripted; the graph holds lineage extracted from the synced poc-data (see test_policy_lineage).
Expected positions come from `_master/planned_conflicts.json` (C1, C2, C3, C5).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import pytest

from plg.entities.local import LocalGraphStore
from plg.entities.writer import GraphWriter
from plg.ingest.lineage import LineageReport
from plg.llm import ScriptedLLMClient, text, tool_call, turn
from plg.search.lance import LanceSearchStore
from plg.search.rerank import Searcher
from tests.conftest import Api, route
from tests.test_entity_knowledge_api import tool_results
from tests.test_knowledge_api import POL_003_V1, POL_003_V2, answer_citing, search_results, shown_chunks
from tests.test_policy_lineage import graph_dir, haiku, lineage  # noqa: F401  (fixtures)

DISPLAY = "How far can a tenant display goods beyond the shopfront?"
LOD = "When do we issue a letter of demand?"
LOD_THEN = "When was the letter of demand issued before April 2026?"


@pytest.fixture
def stance_api(
    make_api: Callable[..., Api],
    searcher: Searcher,
    lineage: tuple[LocalGraphStore, GraphWriter, LineageReport],  # noqa: F811
) -> Api:
    return make_api(searcher=searcher, entities=lineage[0])


def test_display_area_answer_gives_each_unit_type_its_rule_and_streams_the_stance(
    stance_api: Api, llm: ScriptedLLMClient
) -> None:
    route(llm, DISPLAY, "knowledge")
    llm.script_turns(
        "knowledge", DISPLAY,
        turn(tool_call("policy_lineage", policy_id="PLG-POL-001")),
        answer_citing("overrides clause 7.3", "Circular 07/2026 raises it to 1.0 m for NC units from 1 August 2026."),
    )
    llm.script("merge", DISPLAY, "NC units: 1.0 m from 1 Aug 2026 [1]. Void-deck shops: 0.6 m.")

    stream = stance_api.run(stance_api.create_thread(), DISPLAY)

    [stance] = stream.of_type("policy_stance")
    assert stance["policy_id"] == "PLG-POL-001"
    assert stance["current"] == "PLG-POL-001 v3.0"
    [override] = stance["overrides"]  # type: ignore[misc]
    assert (override["circular_id"], override["clause_number"], override["scope"]) == (
        "Circular 07/2026", "7.3", "NC units only"
    )
    assert override["effective_from"] == "2026-08-01"
    [citation] = stream.of_type("citation")
    assert citation["chunk_id"] == "lineage:PLG-POL-001"
    shown = " ".join(b["text"] for m in llm.sent for r in search_results(m) for b in r["content"])
    assert "still applies to everything outside NC units only" in shown
    assert stream.events[-1]["type"] == "done"
    assert stream.of_type("policy_stance")[0]["seq"] < stream.events[-1]["seq"]  # type: ignore[operator]


def test_lod_answer_is_given_both_the_current_policy_and_the_sop_that_still_says_day_45(
    stance_api: Api, llm: ScriptedLLMClient, store: LanceSearchStore
) -> None:
    route(llm, LOD, "knowledge")
    llm.script_turns(
        "knowledge", LOD,
        turn(
            tool_call("policy_lineage", policy_id="PLG-POL-003"),
            tool_call("search_corpus", query="letter of demand days overdue"),
        ),
        answer_citing("supersedes", "POL-003 v2.0 sets it at 60 days; SOP-014 v1.2 still says 45."),
    )
    llm.script("merge", LOD, "60 days under POL-003 v2.0 [1]; SOP-014 still says day 45.")

    stream = stance_api.run(stance_api.create_thread(), LOD)

    [stance] = stream.of_type("policy_stance")
    assert [v["status"] for v in stance["versions"]] == ["superseded", "current"]  # type: ignore[attr-defined]
    paths = {c.source_path for c in shown_chunks(llm, store)}
    assert POL_003_V2 in paths and POL_003_V1 not in paths
    assert any("PLG-SOP-014" in p for p in paths), "the SOP is shown so the agent can flag it"
    assert "SOP-014" in stream.text


def test_a_question_about_an_earlier_date_gets_the_version_then_in_force(
    stance_api: Api, llm: ScriptedLLMClient, store: LanceSearchStore
) -> None:
    route(llm, LOD_THEN, "knowledge")
    llm.script_turns(
        "knowledge", LOD_THEN,
        turn(
            tool_call("policy_lineage", policy_id="PLG-POL-003"),
            tool_call("search_corpus", query="letter of demand days overdue", as_of="2026-03-01"),
        ),
        answer_citing("45 days", "Before 1 April 2026 the trigger was 45 days overdue."),
    )
    llm.script("merge", LOD_THEN, "45 days overdue under POL-003 v1.0 [1].")

    stream = stance_api.run(stance_api.create_thread(), LOD_THEN)

    paths = {c.source_path for c in shown_chunks(llm, store)}
    assert POL_003_V1 in paths and POL_003_V2 not in paths
    [stance] = stream.of_type("policy_stance")
    v1 = stance["versions"][0]  # type: ignore[index]
    assert date.fromisoformat(v1["effective_to"]) < date(2026, 4, 1)


def test_an_unknown_policy_id_tells_the_agent_to_search_instead(
    stance_api: Api, llm: ScriptedLLMClient
) -> None:
    question = "What is policy POL-999?"
    route(llm, question, "knowledge")
    llm.script_turns(
        "knowledge", question,
        turn(tool_call("policy_lineage", policy_id="PLG-POL-999")),
        turn(text("No such policy.")),
    )

    stream = stance_api.run(stance_api.create_thread(), question)

    results = [b["content"] for m in llm.sent for b in tool_results(m)]
    assert any("No controlled document has the ID 'PLG-POL-999'" in str(c) for c in results)
    assert stream.of_type("policy_stance") == []


def test_the_stance_for_an_earlier_date_marks_the_version_then_in_force_as_current(
    stance_api: Api, llm: ScriptedLLMClient
) -> None:
    route(llm, LOD_THEN, "knowledge")
    llm.script_turns(
        "knowledge", LOD_THEN,
        turn(tool_call("policy_lineage", policy_id="PLG-POL-003", as_of="2026-03-01")),
        answer_citing("is the current version", "On 1 March 2026 v1.0 was in force."),
    )
    llm.script("merge", LOD_THEN, "v1.0 was in force [1].")

    stream = stance_api.run(stance_api.create_thread(), LOD_THEN)

    [stance] = stream.of_type("policy_stance")
    assert stance["current"] == "PLG-POL-003 v1.0"
    assert [v["status"] for v in stance["versions"]] == ["current", "superseded"]  # type: ignore[attr-defined]


def test_void_deck_shops_keep_the_original_clause(stance_api: Api, llm: ScriptedLLMClient) -> None:
    route(llm, DISPLAY, "knowledge")
    llm.script_turns(
        "knowledge", DISPLAY,
        turn(tool_call("policy_lineage", policy_id="PLG-POL-001")),
        answer_citing("still applies", "Clause 7.3 (0.6 m) still applies outside NC units."),
    )
    llm.script("merge", DISPLAY, "Void-deck shops keep 0.6 m [1].")

    stream = stance_api.run(stance_api.create_thread(), DISPLAY)

    [citation] = stream.of_type("citation")
    assert "Clause 7.3 of v3.0 still applies to everything outside NC units only" in str(citation["quote"])
