"""Precedent questions through plg-api: the knowledge agent finds past cases in the entity graph and is shown each
case's compendium page and the emails that discuss it, so the answer cites the page or email.

Claude is scripted; the graph holds the precedents read from the synced compendium (see test_precedents).
Expected cases come from `_report.md` (precedent questions 5 and 7) and the Mutiara change-of-trade thread.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from plg.entities.local import LocalGraphStore
from plg.entities.writer import GraphWriter
from plg.ingest.lineage import LineageReport
from plg.llm import ScriptedLLMClient, tool_call, turn
from plg.search.lance import LanceSearchStore
from plg.search.rerank import Searcher
from tests.conftest import Api, route
from tests.test_entity_knowledge_api import tool_results
from tests.test_knowledge_api import answer_citing, shown_chunks
from tests.test_policy_lineage import graph_dir, haiku, lineage  # noqa: F401  (fixtures)

BUBBLE_TEA = "Any precedents for a provision shop in Pasir Indah Central NC changing to bubble tea?"
FIRE = "Should Sin Hock Eating House get a rent rebate after the May fire?"


@pytest.fixture
def precedent_api(
    make_api: Callable[..., Api],
    searcher: Searcher,
    lineage: tuple[LocalGraphStore, GraphWriter, LineageReport],  # noqa: F811
) -> Api:
    return make_api(searcher=searcher, entities=lineage[0])


def notes(llm: ScriptedLLMClient) -> str:
    """The plain-text parts of every tool result the knowledge agent was shown."""
    parts: list[str] = []
    for messages in llm.sent:
        for result in tool_results(messages):
            content: Any = result["content"]
            if isinstance(content, str):
                parts.append(content)
            else:
                parts += [b["text"] for b in content if b["type"] == "text"]
    return "\n".join(parts)


def find_bubble_tea(llm: ScriptedLLMClient, phrase: str, answer: str) -> None:
    route(llm, BUBBLE_TEA, "knowledge")
    llm.script_turns(
        "knowledge", BUBBLE_TEA,
        turn(tool_call("find_precedents", trade="Bubble Tea", nc="NC-PI-1", issue="change of trade")),
        answer_citing(phrase, answer),
    )
    llm.script("merge", BUBBLE_TEA, f"{answer} [1]")


def test_a_precedent_is_cited_to_its_compendium_page(
    precedent_api: Api, llm: ScriptedLLMClient, store: LanceSearchStore
) -> None:
    find_bubble_tea(llm, "concentration limit of 2 per NC", "PC-2024-009 was rejected: a 3rd outlet exceeds the limit.")

    stream = precedent_api.run(precedent_api.create_thread(), BUBBLE_TEA)

    [citation] = stream.of_type("citation")
    assert citation["title"] == "PLG Precedent Case Compendium 2023-2026"
    assert citation["location"] == "PC-2024-009 - Change of trade (Pasir Indah) (p. 5)"
    assert "concentration limit of 2 per NC" in str(citation["quote"])
    shown = shown_chunks(llm, store)
    assert {c.location for c in shown if c.doc_type == "precedent_compendium"} == {
        "PC-2024-009 - Change of trade (Pasir Indah) (p. 5)", "PC-2025-014 - Change of trade (Bayshore Vale) (p. 8)",
        "PC-2024-034 - Change of trade (Pasir Indah) (p. 5)", "PC-2025-035 - Change of trade (Rimba Heights) (p. 8)",
        "PC-2026-044 - Change of trade (Rimba Heights) (p. 12)",
    }
    assert stream.events[-1]["type"] == "done"


def test_a_precedent_can_be_cited_to_the_email_that_discusses_it(
    precedent_api: Api, llm: ScriptedLLMClient
) -> None:
    find_bubble_tea(llm, "APPROVED, but that was only t", "PC-2025-014 was approved only as the 2nd outlet.")

    stream = precedent_api.run(precedent_api.create_thread(), BUBBLE_TEA)

    [citation] = stream.of_type("citation")
    assert str(citation["title"]).startswith("RE: Change of trade application - Mutiara Provision Shop")


def test_the_agent_is_told_what_each_precedent_shares_with_the_case_and_how_it_differs(
    precedent_api: Api, llm: ScriptedLLMClient
) -> None:
    find_bubble_tea(llm, "concentration limit of 2 per NC", "PC-2024-009 was rejected.")

    precedent_api.run(precedent_api.create_thread(), BUBBLE_TEA)

    shown = notes(llm)
    first, second = shown.index("PC-2024-009"), shown.index("PC-2025-014")
    assert first < second
    same_nc = shown[first:second]
    assert "same trade (Bubble Tea)" in same_nc and "same NC (NC-PI-1" in same_nc
    assert "Rejected." not in shown  # decisions are cited from the compendium page, never from the note
    assert "different NC: NC-BV-3" in shown[second:].split("\n")[0]


def test_the_fire_precedent_is_shown_with_its_reasoning_so_the_differences_can_be_explained(
    precedent_api: Api, llm: ScriptedLLMClient, store: LanceSearchStore
) -> None:
    route(llm, FIRE, "knowledge")
    llm.script_turns(
        "knowledge", FIRE,
        turn(
            tool_call("find_precedents", issue="fire rent rebate"),
            tool_call("search_corpus", query="Sin Hock fire cause and rent rebate"),
        ),
        answer_citing(
            "did not result from tenant negligence",
            "No: PC-2025-019's rebate was given because the fire was not the tenant's fault; Sin Hock's was.",
        ),
    )
    llm.script("merge", FIRE, "No rebate: unlike PC-2025-019, the fire was tenant-caused [1].")

    stream = precedent_api.run(precedent_api.create_thread(), FIRE)

    [citation] = stream.of_type("citation")
    assert citation["location"] == "PC-2025-019 - Fire incident / rent rebate (Kebun Raya) (p. 9)"
    shown = {c.source_path for c in shown_chunks(llm, store)}
    # The precedent's page and the current case's own evidence, so the two causes can be set side by side.
    assert "pdfs/Incident_Report_PLG-INC-2026-011_Fire_Sin_Hock.pdf" in shown
    tools = {t["name"] for _, tools in llm.requests for t in tools}
    assert "find_precedents" in tools
    system = " ".join(b["text"] for blocks, _ in llm.requests for b in blocks)
    assert "how the officer's case differs" in system


def test_no_matching_precedent_tells_the_agent_to_search_instead(
    precedent_api: Api, llm: ScriptedLLMClient
) -> None:
    question = "Any precedent for a parking season ticket refund?"
    route(llm, question, "knowledge")
    llm.script_turns(
        "knowledge", question, turn(tool_call("find_precedents", issue="parking season ticket")),
        answer_citing("nothing", "The indexed sources don't cover it."),
    )
    llm.script("merge", question, "The indexed sources don't cover it.")

    precedent_api.run(precedent_api.create_thread(), question)

    assert "No precedent" in notes(llm)
