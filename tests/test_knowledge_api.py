"""Policy Q&A through plg-api: the router sends knowledge questions to the knowledge agent, which searches the
synced poc-data corpus; citations reach the client as `citation` events.

Claude is scripted. Expected sources come from `_report.md` section 5 and the POL-003 lineage in `_master`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from plg.llm import AgentMessage, AgentTurn, ScriptedLLMClient, text, tool_call, turn
from plg.search.lance import LanceSearchStore
from plg.search.models import Chunk
from tests.conftest import Api, route

LOD_QUESTION = "When do we issue a letter of demand?"
POL_003_V1 = "docs/PLG-POL-003_Rental_Arrears_Management_Policy_v1.0.docx"
POL_003_V2 = "docs/PLG-POL-003_Rental_Arrears_Management_Policy_v2.0.docx"


def search_results(messages: list[AgentMessage]) -> Iterator[dict[str, Any]]:
    """Every search_result block Claude was shown, in request order."""
    for message in messages:
        if message["role"] != "user" or isinstance(message["content"], str):
            continue
        for block in message["content"]:
            if block["type"] == "tool_result" and isinstance(block["content"], list):
                yield from (b for b in block["content"] if b["type"] == "search_result")


def answer_citing(phrase: str, answer: str) -> Callable[[list[AgentMessage]], AgentTurn]:
    """A final turn citing the first block of the search results that contains `phrase`, as Claude would."""

    def reply(messages: list[AgentMessage]) -> AgentTurn:
        for index, result in enumerate(search_results(messages)):
            for i, block in enumerate(result["content"]):
                if phrase in block["text"]:
                    citation = {
                        "type": "search_result_location", "source": result["source"], "title": result["title"],
                        "cited_text": block["text"], "search_result_index": index,
                        "start_block_index": i, "end_block_index": i + 1,
                    }
                    return turn(text(answer, citation))
        return turn(text("The sources don't cover this."))

    return reply


def shown_chunks(llm: ScriptedLLMClient, store: LanceSearchStore) -> list[Chunk]:
    """Every chunk the knowledge agent was shown as a search result."""
    return [
        chunk
        for messages in llm.sent
        for result in search_results(messages)
        if (chunk := store.get_chunk(result["source"])) is not None
    ]


def shown_sources(llm: ScriptedLLMClient, store: LanceSearchStore) -> set[str]:
    return {c.source_path for c in shown_chunks(llm, store)}


def test_lod_question_cites_pol_003_v2_and_never_the_superseded_v1(
    knowledge_api: Api, llm: ScriptedLLMClient, store: LanceSearchStore
) -> None:
    route(llm, LOD_QUESTION, "knowledge")
    llm.script_turns(
        "knowledge", LOD_QUESTION,
        turn(tool_call("search_corpus", query="letter of demand arrears trigger")),
        answer_citing("60 days", "A letter of demand is issued when arrears reach 60 days."),
    )
    llm.script("merge", LOD_QUESTION, "Under POL-003 v2.0, a letter of demand is issued at 60 days [1].")

    stream = knowledge_api.run(knowledge_api.create_thread(), LOD_QUESTION)

    citations = stream.of_type("citation")
    assert citations
    for c in citations:
        chunk = store.get_chunk(str(c["chunk_id"]))
        assert chunk is not None
        assert chunk.source_path == POL_003_V2
        assert c["doc_id"] == chunk.doc_id
        assert c["location"] == chunk.location
        span: dict[str, int] = c["span"]  # type: ignore[assignment]
        assert chunk.text[span["start"]:span["end"]] == c["quote"]
        assert "60 days" in str(c["quote"])
    assert POL_003_V1 not in shown_sources(llm, store)
    assert stream.events[-1]["type"] == "done"


def test_knowledge_question_runs_route_then_knowledge_then_merge(knowledge_api: Api, llm: ScriptedLLMClient) -> None:
    route(llm, LOD_QUESTION, "knowledge")
    llm.script_turns(
        "knowledge", LOD_QUESTION,
        turn(tool_call("search_corpus", query="letter of demand")),
        answer_citing("60 days", "A letter of demand is issued at 60 days."),
    )
    llm.script("merge", LOD_QUESTION, "At 60 days [1].")

    stream = knowledge_api.run(knowledge_api.create_thread(), LOD_QUESTION)

    started = [e["node"] for e in stream.of_type("node") if e["status"] == "started"]
    assert started == ["route", "knowledge", "merge"]
    first_token = next(i for i, e in enumerate(stream.events) if e["type"] == "token")
    assert all(i < first_token for i, e in enumerate(stream.events) if e["type"] == "citation")


def test_citation_of_a_passage_the_agent_never_retrieved_is_dropped(
    knowledge_api: Api, llm: ScriptedLLMClient, store: LanceSearchStore
) -> None:
    v1_chunk = next(c for d in store.documents() if d.source_path == POL_003_V1 for c in store.chunks(d.doc_id))
    invented = {
        "type": "search_result_location", "source": v1_chunk.chunk_id, "title": v1_chunk.title,
        "cited_text": v1_chunk.text, "search_result_index": 0, "start_block_index": 0, "end_block_index": 1,
    }
    route(llm, LOD_QUESTION, "knowledge")
    llm.script_turns(
        "knowledge", LOD_QUESTION,
        turn(tool_call("search_corpus", query="letter of demand")),
        turn(text("A letter of demand is issued at 45 days.", invented)),
    )

    stream = knowledge_api.run(knowledge_api.create_thread(), LOD_QUESTION)

    assert stream.of_type("citation") == []
    assert "don't cover this question" in stream.text


def test_tool_calls_in_one_turn_all_run_and_return_together(
    knowledge_api: Api, llm: ScriptedLLMClient, store: LanceSearchStore
) -> None:
    question = "How has the LOD trigger changed since 2025?"
    route(llm, question, "knowledge")
    llm.script_turns(
        "knowledge", question,
        turn(
            tool_call("search_corpus", query="letter of demand trigger"),
            tool_call("search_corpus", query="letter of demand trigger", as_of="2025-06-01"),
        ),
        turn(text("Noted.")),
    )

    knowledge_api.run(knowledge_api.create_thread(), question)

    results = llm.sent[-1][-1]["content"]
    assert [r["type"] for r in results] == ["tool_result", "tool_result"]
    assert {POL_003_V1, POL_003_V2} <= shown_sources(llm, store)


def test_agent_system_prompt_and_tools_are_marked_for_prompt_caching(
    knowledge_api: Api, llm: ScriptedLLMClient
) -> None:
    route(llm, LOD_QUESTION, "knowledge")
    llm.script_turns("knowledge", LOD_QUESTION, turn(text("Noted.")))

    knowledge_api.run(knowledge_api.create_thread(), LOD_QUESTION)

    system, tools = llm.requests[-1]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert tools[-1]["cache_control"] == {"type": "ephemeral"}


def test_question_the_sources_dont_cover_gets_an_explicit_not_covered_answer(
    knowledge_api: Api, llm: ScriptedLLMClient
) -> None:
    question = "What is the GST rate on season parking for lorries?"
    route(llm, question, "knowledge")
    llm.script_turns(
        "knowledge", question,
        turn(tool_call("search_corpus", query="GST rate season parking lorries")),
        # Uncited, so not an answer from the sources, however confident it sounds.
        turn(text("Season parking for lorries attracts GST at 9%.")),
    )

    stream = knowledge_api.run(knowledge_api.create_thread(), question)

    assert stream.events[-1]["type"] == "done"
    assert "don't cover this question" in stream.text
    assert "9%" not in stream.text
    assert stream.of_type("citation") == []


def test_lod_abbreviation_ranks_the_letter_of_demand_clause_of_the_current_policy_first(
    knowledge_api: Api, llm: ScriptedLLMClient, store: LanceSearchStore
) -> None:
    question = "When is an LOD issued?"
    route(llm, question, "knowledge")
    llm.script_turns("knowledge", question, turn(tool_call("search_corpus", query="LOD")), turn(text("Noted.")))

    knowledge_api.run(knowledge_api.create_thread(), question)

    top = shown_chunks(llm, store)[0]
    assert (top.source_path, top.location) == (POL_003_V2, "4. Policy Statements > 4.5 Letter of Demand")
