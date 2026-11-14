"""Glossary questions and controlled definition changes through plg-api (issue #25).

An officer asks what a business term means now and earlier: the knowledge agent reads every version of the term
(`glossary_definitions`) as one citable passage naming each version's dates and source. A policy owner proposes a
change in conversation (`glossary` intent): it becomes a `proposed` term version inside an `approve_glossary_term`
action that only the term owner can approve. The owner (the term's curator) sees it in GET /approvals and decides
through the same approval flow; approval supersedes the old version (never deleted: it gets `effective_to`) and the
data agent's get_definition / run_sql use the new version and its SQL binding from its effective date.

Claude is scripted; approved changes land in the test's temp glossary_changes file, the audit log beside it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plg.actions.audit import AuditLog
from plg.llm import ScriptedLLMClient, text, tool_call, turn
from tests.conftest import Api, SseStream, route
from tests.test_approvals_api import REMINDER, SLOTS, decide
from tests.test_data_api import binding, count_of, sql_turn
from tests.test_knowledge_api import answer_citing

POLICY_OWNER = {"X-PLG-User": "S02"}  # Deputy Director, Leasing Policy & Planning
TERM_OWNER = {"X-PLG-User": "S08"}  # Kelvin Goh, Ops Analytics: owns plg:Vacant
BYSTANDER = {"X-PLG-User": "S05"}

PROPOSAL = "Propose a glossary change: from 1 Oct 2026 units under tender count as vacant again"
CHANGE: dict[str, Any] = {
    "concept": "vacant",
    "definition": "Lettable unit with no active or committed tenancy, including units under tender.",
    "value": "includes units under tender",
    "effective_from": "2026-10-01",
    "reason": "Management Meeting 5/2026 aligned the monthly report with the QBR.",
    "sql": binding("plg:Vacant_v1"),
}


def audit(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit.jsonl")


def propose(api: Api, llm: ScriptedLLMClient, question: str = PROPOSAL, **change: Any) -> tuple[str, SseStream]:
    """The policy owner proposes `CHANGE` (overridden by `change`) in a new thread."""
    route(llm, question, "glossary")
    llm.script_turns("glossary", question, turn(tool_call("propose_glossary_change", **{**CHANGE, **change})))
    llm.script("merge", question, "Your proposal is waiting for the term owner.")
    thread_id = api.create_thread(POLICY_OWNER)
    return thread_id, api.run(thread_id, question, POLICY_OWNER)


def tool_results(llm: ScriptedLLMClient) -> list[str]:
    """The tool results of the latest agent request that had any, in order."""
    last = next(m for m in reversed(llm.sent) if any(isinstance(x["content"], list) for x in m))
    return [
        str(b["content"]) for m in last if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"] if b["type"] == "tool_result"
    ]


def definition_on(api: Api, llm: ScriptedLLMClient, on: str, question: str, **lookup: Any) -> str:
    """What the data agent's get_definition shows for plg:Vacant on `on` (or a `version`)."""
    route(llm, question, "data")
    args = {"concept": "plg:Vacant", **({"version": lookup["version"]} if "version" in lookup else {"as_of": on})}
    llm.script_turns("data", question, turn(tool_call("get_definition", **args)), turn(text("Noted.")))
    llm.script("merge", question, "Done.")
    api.run(api.create_thread(BYSTANDER), question, BYSTANDER)
    return tool_results(llm)[0]


# ---------------------------------------------------------------- glossary questions


def test_a_glossary_question_gets_current_and_historical_definitions_with_their_source(
    api: Api, llm: ScriptedLLMClient
) -> None:
    question = "What does vacant mean now, and what did it mean before April 2026?"
    route(llm, question, "knowledge")
    llm.script_turns(
        "knowledge", question,
        turn(tool_call("glossary_definitions", term="vacant")),
        answer_citing("excluding units under tender", "Vacant now excludes units under tender."),
    )
    llm.script("merge", question, "Vacant now excludes units under tender [1].")

    stream = api.run(api.create_thread(), question)

    (citation,) = stream.of_type("citation")
    assert citation["chunk_id"] == "glossary:plg:Vacant"
    assert "excluding units under tender" in str(citation["quote"])
    shown = "\n".join(tool_results(llm))
    assert "plg:Vacant_v2 is the current version, in force from 2026-04-15" in shown
    assert "plg:Vacant_v1 is superseded, in force since before records began to 2026-04-14" in shown
    assert "including units under tender" in shown
    assert "DOC-012, Minutes of PLG Management Meeting" in shown
    assert stream.of_type("done") and not stream.of_type("error")


def test_an_unknown_term_is_not_a_definition(api: Api, llm: ScriptedLLMClient) -> None:
    question = "What does 'flux capacity' mean?"
    route(llm, question, "knowledge")
    llm.script_turns(
        "knowledge", question, turn(tool_call("glossary_definitions", term="flux capacity")), turn(text("Not defined."))
    )
    llm.script("merge", question, "unused")

    stream = api.run(api.create_thread(), question)

    assert "No glossary term matches" in tool_results(llm)[0]
    assert not stream.of_type("citation")


# ---------------------------------------------------------------- proposing a change


def test_a_change_is_proposed_as_a_proposed_term_that_only_the_term_owner_can_approve(
    api: Api, llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    _, stream = propose(api, llm)

    (action,) = stream.of_type("proposed_action")
    (paused,) = stream.of_type("interrupt")
    assert action["action_type"] == "approve_glossary_term"
    assert action["approvers"] == ["S08"]
    assert action["proposed_by"] == "S02"
    payload = action["payload"]
    assert payload["kind"] == "glossary"
    term = payload["term"]
    assert (term["id"], term["concept"], term["version"], term["status"]) == ("plg:Vacant_v3", "plg:Vacant", 3, "proposed")
    assert (term["supersedes"], term["effective_from"], term["owned_by"]) == ("plg:Vacant_v2", "2026-10-01", "S08")
    assert term["definition"] == CHANGE["definition"]
    assert payload["previous"]["id"] == "plg:Vacant_v2"
    assert payload["owner_name"] == "Kelvin Goh"
    assert "including units under tender" in str(action["preview"])
    assert (paused["action_id"], paused["version"]) == (action["action_id"], action["version"])
    assert audit(tmp_path).entries() == []
    # Nothing changes until it is approved.
    assert "plg:Vacant_v2 (Vacant unit), current" in definition_on(api, llm, "2026-10-15", "Vacant units on 15 Oct 2026?")


def test_the_term_owner_sees_the_proposal_and_others_do_not(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")

    (listed,) = api.client.get("/approvals", headers=TERM_OWNER).json()
    assert (listed["action_id"], listed["thread_id"]) == (action["action_id"], thread_id)
    assert [a["action_id"] for a in api.client.get("/approvals", headers=POLICY_OWNER).json()] == [action["action_id"]]
    assert api.client.get("/approvals", headers=BYSTANDER).json() == []
    # The curator decides on the action, but the conversation stays the proposer's own.
    assert api.client.get(f"/threads/{thread_id}", headers=TERM_OWNER).status_code == 404


def test_only_the_term_owner_can_approve(api: Api, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")

    assert api.resume(thread_id, decide(action, "approve"), headers=POLICY_OWNER) == 403  # outranks the owner, still no
    assert api.resume(thread_id, decide(action, "approve"), headers=BYSTANDER) == 404
    assert audit(tmp_path).entries() == []
    assert "plg:Vacant_v2 (Vacant unit), current" in definition_on(api, llm, "2026-10-15", "Vacant on 15 Oct?")


def test_an_approved_change_supersedes_the_old_version_and_the_data_agent_uses_the_new_one(
    api: Api, llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")

    resumed = api.resume(thread_id, decide(action, "approve"), headers=TERM_OWNER)

    assert isinstance(resumed, SseStream)
    (result,) = resumed.of_type("action_result")
    assert (result["decision"], result["term_id"]) == ("approve", "plg:Vacant_v3")
    (entry,) = audit(tmp_path).entries()
    assert (entry.action_type, entry.decision, entry.approver, entry.approver_role) == (
        "approve_glossary_term", "approve", "S08", "analyst",
    )
    assert entry.term_id == "plg:Vacant_v3" and entry.thread_id == thread_id
    assert api.client.get("/approvals", headers=TERM_OWNER).json() == []
    assert [a["term_id"] for a in api.client.get("/audit", headers=TERM_OWNER).json()] == ["plg:Vacant_v3"]

    after = definition_on(api, llm, "2026-10-15", "Vacant units on 15 Oct 2026?")
    assert "plg:Vacant_v3 (Vacant unit), current, in force from 2026-10-01" in after
    assert "including units under tender" in after
    assert "WHERE u.status IN ('Vacant', 'Under Tender')" in after  # its own SQL binding
    old = definition_on(api, llm, "2026-08-31", "Vacant units on 31 Aug 2026?")
    assert "plg:Vacant_v2 (Vacant unit), superseded, in force from 2026-04-15 to 2026-09-30" in old
    first = definition_on(api, llm, "", "And the first vacant definition?", version=1)
    assert "plg:Vacant_v1 (Vacant unit), superseded" in first  # never deleted

    question = "How many units are vacant on 15 Oct 2026?"
    route(llm, question, "data")
    llm.script_turns(
        "data", question,
        sql_turn("Count vacant units", count_of("plg:Vacant_v1"), ["plg:Vacant"], "2026-10-15"),
        turn(text("52 units are vacant under Vacant v3, effective 2026-10-01.")),
    )
    llm.script("merge", question, "52.")
    (trace,) = api.run(api.create_thread(), question).of_type("sql_trace")
    (used,) = trace["concepts"]  # type: ignore[misc]
    assert (used["id"], used["version"], used["effective_from"]) == ("plg:Vacant_v3", 3, "2026-10-01")


def test_a_glossary_question_after_approval_shows_all_three_versions(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")
    api.resume(thread_id, decide(action, "approve"), headers=TERM_OWNER)

    question = "What does vacant mean?"
    route(llm, question, "knowledge")
    llm.script_turns(
        "knowledge", question, turn(tool_call("glossary_definitions", term="plg:Vacant")), turn(text("See above."))
    )
    llm.script("merge", question, "unused")
    api.run(api.create_thread(), question)

    shown = tool_results(llm)[0]
    assert "plg:Vacant_v3 is the current version, in force from 2026-10-01" in shown
    assert "plg:Vacant_v2 is superseded, in force from 2026-04-15 to 2026-09-30" in shown
    assert "plg:Vacant_v1 is superseded" in shown


def test_an_approved_change_survives_an_api_restart(make_api: Any, llm: ScriptedLLMClient) -> None:
    api = make_api()
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")
    api.resume(thread_id, decide(action, "approve"), headers=TERM_OWNER)

    restarted = make_api()
    assert "plg:Vacant_v3 (Vacant unit), current" in definition_on(restarted, llm, "2026-10-15", "Vacant now?")


def test_a_rejection_changes_nothing_and_is_audited(api: Api, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")

    resumed = api.resume(thread_id, decide(action, "reject", reason="Keep the April definition."), headers=TERM_OWNER)

    assert isinstance(resumed, SseStream)
    (result,) = resumed.of_type("action_result")
    assert (result["decision"], result["term_id"]) == ("reject", None)
    (entry,) = audit(tmp_path).entries()
    assert (entry.decision, entry.reason, entry.term_id) == ("reject", "Keep the April definition.", None)
    assert "plg:Vacant_v2 (Vacant unit), current" in definition_on(api, llm, "2026-10-15", "Vacant now?")


def test_the_proposer_can_withdraw_but_not_approve(api: Api, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")

    assert isinstance(api.resume(thread_id, decide(action, "reject", reason="Withdrawn."), headers=POLICY_OWNER), SseStream)
    assert api.client.get("/approvals", headers=TERM_OWNER).json() == []
    (entry,) = audit(tmp_path).entries()
    assert (entry.decision, entry.approver) == ("reject", "S02")


def test_the_term_owner_can_edit_the_proposal_before_approving_it(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")

    assert api.resume(thread_id, decide(action, "edit", edits={"owned_by": "S05"}), headers=TERM_OWNER) == 422
    assert api.resume(thread_id, decide(action, "edit", edits={"effective_from": "2026-04-01"}), headers=TERM_OWNER) == 422
    edited = api.resume(thread_id, decide(action, "edit", edits={"effective_from": "2026-11-01"}), headers=TERM_OWNER)

    assert isinstance(edited, SseStream)
    assert "in force from 2026-11-01" in definition_on(api, llm, "2026-11-15", "Vacant in November?")
    october = definition_on(api, llm, "2026-10-15", "Vacant in October?")
    assert "plg:Vacant_v2 (Vacant unit), superseded, in force from 2026-04-15 to 2026-10-31" in october


def test_an_approval_of_a_stale_proposal_is_refused(api: Api, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    first_thread, first = propose(api, llm)
    other = "Propose a glossary change: vacant should include units under tender from 1 Nov 2026"
    second_thread, second = propose(api, llm, question=other, effective_from="2026-11-01")
    (a,) = first.of_type("proposed_action")
    (b,) = second.of_type("proposed_action")

    assert isinstance(api.resume(first_thread, decide(a, "approve"), headers=TERM_OWNER), SseStream)
    # Both proposed v3 of a term that has moved on since: the second can only be rejected now.
    assert api.resume(second_thread, decide(b, "approve"), headers=TERM_OWNER) == 409
    assert len(audit(tmp_path).entries()) == 1


def test_an_invalid_change_is_not_proposed(api: Api, llm: ScriptedLLMClient) -> None:
    _, early = propose(api, llm, effective_from="2026-01-01")
    assert not early.of_type("proposed_action")
    assert "must start after" in str(llm.streamed[-1])

    unknown = "Propose a glossary change to flux capacity"
    _, stream = propose(api, llm, question=unknown, concept="flux capacity")
    assert not stream.of_type("proposed_action")

    broken = "Propose a vacant definition with new SQL"
    _, stream = propose(api, llm, question=broken, sql="DELETE FROM units")
    assert not stream.of_type("proposed_action")
    assert stream.of_type("done") and not stream.of_type("error")


def test_a_proposal_without_sql_keeps_the_previous_binding(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id, stream = propose(api, llm, sql=None, definition="Lettable unit with no active or committed tenancy, "
                                "excluding units under tender, counted at month end.")
    (action,) = stream.of_type("proposed_action")
    api.resume(thread_id, decide(action, "approve"), headers=TERM_OWNER)

    after = definition_on(api, llm, "2026-10-15", "Vacant on 15 Oct?")
    assert "plg:Vacant_v3" in after and "counted at month end" in after
    assert "WHERE u.status = 'Vacant'" in after


def test_the_curator_sees_nothing_else_of_the_proposers_conversation(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id, stream = propose(api, llm)
    (change,) = stream.of_type("proposed_action")
    route(llm, REMINDER, "drafting")
    llm.script_turns("drafting", REMINDER, turn(tool_call("submit_draft", template_id="TPL-REM-01", slots=SLOTS)), turn(text("Drafted.")))
    llm.script("merge", REMINDER, "Your draft is ready.")
    api.run(thread_id, REMINDER, POLICY_OWNER)

    (listed,) = api.client.get("/approvals", headers=TERM_OWNER).json()
    assert listed["action_id"] == change["action_id"]
    assert PROPOSAL not in listed["thread_title"]  # the proposer's question stays theirs

    resumed = api.resume(thread_id, decide(change, "approve"), headers=TERM_OWNER)

    assert isinstance(resumed, SseStream)
    assert resumed.of_type("action_result")
    assert not resumed.of_type("proposed_action") and not resumed.of_type("interrupt")  # the letter still waits, unseen
    assert "Golden Leaf" not in str(resumed.events)
    (letter,) = api.client.get("/approvals", headers=POLICY_OWNER).json()
    assert letter["action_type"] == "send_letter"
