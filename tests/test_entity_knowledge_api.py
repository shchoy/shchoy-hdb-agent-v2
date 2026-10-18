"""\"Tell me about this tenant/unit\" through plg-api: the knowledge agent resolves a name or ID in the entity
graph, reads its context as record passages and cites them. Claude is scripted; expected IDs come from `_master`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from plg.entities.local import LocalGraphStore
from plg.llm import ScriptedLLMClient, text, tool_call, turn
from tests.conftest import Api, route
from tests.test_entity_graph import GOLDEN_LEAF, graph, graph_dir, spine  # noqa: F401  (fixtures)
from tests.test_knowledge_api import answer_citing, search_results

QUESTION = "Tell me about Golden Leaf Minimart Pte Ltd"


@pytest.fixture
def entity_api(make_api: Callable[..., Api], graph: LocalGraphStore) -> Api:
    return make_api(entities=graph)


def tool_results(messages: list[Any]) -> Iterator[Any]:
    for message in messages:
        if message["role"] == "user" and not isinstance(message["content"], str):
            for block in message["content"]:
                if block["type"] == "tool_result":
                    yield block


def test_tenant_question_resolves_walks_the_graph_and_cites_records(
    entity_api: Api, llm: ScriptedLLMClient
) -> None:
    route(llm, QUESTION, "knowledge")
    llm.script_turns(
        "knowledge", QUESTION,
        turn(tool_call("resolve_entities", text="Golden Leaf Minimart Pte Ltd")),
        turn(tool_call("entity_context", entity_id=GOLDEN_LEAF["tenant"])),
        answer_citing("Minimart", "Golden Leaf Minimart rents unit U-BV214-01-32 under TA-2024-00542."),
    )
    llm.script("merge", QUESTION, "Golden Leaf Minimart holds tenancy TA-2024-00542 [1].")

    stream = entity_api.run(entity_api.create_thread(), QUESTION)

    assert stream.events[-1]["type"] == "done"
    citations = stream.of_type("citation")
    assert citations, "record facts are cited like documents"
    assert all(str(c["chunk_id"]).startswith("record:") for c in citations)
    shown = {r["source"] for messages in llm.sent for r in search_results(messages)}
    assert {GOLDEN_LEAF["tenant"], GOLDEN_LEAF["tenancy"], GOLDEN_LEAF["lod"]} <= {s.removeprefix("record:") for s in shown}
    assert "TA-2024-00542" in stream.text


def test_unknown_id_tells_the_agent_to_resolve_it_first(entity_api: Api, llm: ScriptedLLMClient) -> None:
    question = "What do we know about T-00000?"
    route(llm, question, "knowledge")
    llm.script_turns(
        "knowledge", question,
        turn(tool_call("entity_context", entity_id="T-00000")),
        turn(text("No such tenant.")),
    )

    stream = entity_api.run(entity_api.create_thread(), question)

    results = [b["content"] for m in llm.sent for b in tool_results(m)]
    assert any("Use resolve_entities" in str(c) for c in results)
    assert "don't cover this question" in stream.text


def test_the_agent_can_only_read_the_graph(entity_api: Api, llm: ScriptedLLMClient) -> None:
    route(llm, QUESTION, "knowledge")
    llm.script_turns("knowledge", QUESTION, turn(text("Nothing.")))

    entity_api.run(entity_api.create_thread(), QUESTION)

    tools = {t["name"] for _, request_tools in llm.requests for t in request_tools}
    assert tools == {"route", "search_corpus", "resolve_entities", "entity_context"}
