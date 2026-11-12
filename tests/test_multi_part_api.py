"""Multi-part questions through plg-api: the router labels every part of a question with a specialist and how sure it
is; the specialists run in parallel and `merge` fuses their findings into one answer in sections. A request the router
can't place gets a clarifying question instead of an answer.

Claude is scripted. The vacancy figure comes from poc-data/_master/units.json (9 Bayshore Vale units with status
Vacant); the definition from the PLG glossary note in the corpus.
"""

from __future__ import annotations

from typing import Any

from plg.llm import ScriptedLLMClient, text, tool_call, turn
from tests.conftest import Api, route
from tests.test_knowledge_api import answer_citing

QUESTION = "How many vacant units are there in Bayshore Vale, and how is vacancy defined?"
VACANT_IN_BAYSHORE_VALE = """\
SELECT COUNT(*) AS vacant_units
FROM units u JOIN blocks b ON b.block_id = u.block_id
WHERE u.status = 'Vacant' AND u.vacant_since <= $as_of AND b.town_code = 'BV'"""
DEFINITION = "A vacant unit is a lettable unit with no active or committed tenancy, excluding units under tender."
COUNT = "9 units in Bayshore Vale were vacant on 2026-09-30 under Vacant v2 (effective 2026-04-15)."
ANSWER = f"## Vacant units in Bayshore Vale\n\n{COUNT}\n\n## How vacancy is defined\n\n{DEFINITION} [1]"


def script_both_parts(llm: ScriptedLLMClient) -> None:
    route(llm, QUESTION, "knowledge", "data")
    llm.script_turns(
        "knowledge", QUESTION,
        turn(tool_call("search_corpus", query="vacant unit definition")),
        answer_citing("excluding units under tender", DEFINITION),
    )
    llm.script_turns(
        "data", QUESTION,
        turn(tool_call("run_sql", plan="Count vacant units in Bayshore Vale", sql=VACANT_IN_BAYSHORE_VALE,
                       concepts=["plg:Vacant_v2"])),
        turn(text(COUNT)),
    )
    llm.script("merge", QUESTION, ANSWER)


def node_events(stream: Any, node: str) -> list[int]:
    return [e["seq"] for e in stream.of_type("node") if e["node"] == node]


def test_two_part_question_gets_both_sections_with_citations_and_sql_traces(
    knowledge_api: Api, llm: ScriptedLLMClient
) -> None:
    script_both_parts(llm)

    stream = knowledge_api.run(knowledge_api.create_thread(), QUESTION)

    assert stream.text == ANSWER
    assert {e["node"] for e in stream.of_type("token")} == {"merge"}
    [citation] = stream.of_type("citation")
    assert citation["index"] == 1
    assert "excluding units under tender" in citation["quote"]
    [trace] = stream.of_type("sql_trace")
    assert trace["status"] == "ok"
    assert trace["result"]["rows"] == [[9]]
    done = stream.events[-1]
    assert done["type"] == "done" and done["run_id"]

    # merge was handed both findings and told to answer each part in its own section
    system = llm.streamed[-1].system
    assert DEFINITION in system and COUNT in system
    assert "section" in system.lower()


def test_specialists_of_a_multi_part_question_run_in_parallel(knowledge_api: Api, llm: ScriptedLLMClient) -> None:
    script_both_parts(llm)

    stream = knowledge_api.run(knowledge_api.create_thread(), QUESTION)

    knowledge_started, knowledge_finished = node_events(stream, "knowledge")
    data_started, data_finished = node_events(stream, "data")
    assert max(knowledge_started, data_started) < min(knowledge_finished, data_finished)
    [merge_started, _] = node_events(stream, "merge")
    assert merge_started > max(knowledge_finished, data_finished)


def test_single_part_question_is_not_split_into_sections(api: Api, llm: ScriptedLLMClient) -> None:
    question = "How many units are vacant?"
    route(llm, question, "data")
    llm.script_turns(
        "data", question,
        turn(tool_call("run_sql", plan="Count vacant units", sql="SELECT COUNT(*) AS n FROM units WHERE status = 'Vacant'",
                       concepts=["plg:Vacant_v2"])),
        turn(text("Some units are vacant.")),
    )
    llm.script("merge", question, "Some units are vacant.")

    api.run(api.create_thread(), question)

    assert "section" not in llm.streamed[-1].system.lower()


def test_ambiguous_request_gets_a_clarifying_question_and_no_specialist_runs(
    api: Api, llm: ScriptedLLMClient
) -> None:
    question = "What about the one at Blk 675?"
    clarify = "Which unit at Blk 675 do you mean, and do you want its tenancy, arrears or inspection history?"
    llm.script_turns("route", question, turn(tool_call(
        "route", intents=[{"intent": "knowledge", "confidence": 0.3}, {"intent": "data", "confidence": 0.35}],
        clarifying_question=clarify,
    )))

    stream = api.run(api.create_thread(), question)

    assert stream.text == clarify
    assert {e["node"] for e in stream.of_type("node")} <= {"load_memory", "route", "merge", "write_memory"}
    assert stream.of_type("citation") == [] and stream.of_type("sql_trace") == []
    assert llm.streamed == []  # merge asks the question as the router wrote it; no Claude call
    assert stream.events[-1]["type"] == "done"


def test_answer_to_a_clarifying_question_is_routed_with_it_in_the_conversation(
    api: Api, llm: ScriptedLLMClient
) -> None:
    question = "What about it?"
    clarify = "What would you like to know, and about which unit or tenant?"
    llm.script_turns("route", question, turn(tool_call(
        "route", intents=[], clarifying_question=clarify,
    )))
    thread_id = api.create_thread()
    api.run(thread_id, question)
    reply = "Hello, just saying hi"
    route(llm, reply)
    llm.script("merge", reply, "Hello!")

    api.run(thread_id, reply)

    route_messages = [m for m in llm.sent if m[-1]["content"] == reply][0]
    assert [m["content"] for m in route_messages] == [question, clarify, reply]


def test_greeting_with_no_specialist_and_no_question_is_answered_directly(api: Api, llm: ScriptedLLMClient) -> None:
    question = "hello there"
    llm.script_turns("route", question, turn(tool_call("route", intents=[])))
    llm.script("merge", question, "Hello! How can I help?")

    stream = api.run(api.create_thread(), question)

    assert stream.text == "Hello! How can I help?"
