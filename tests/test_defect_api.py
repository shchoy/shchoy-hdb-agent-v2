"""Defect classification through plg-api (issue #20): pasted feedback is classified into the defect taxonomy
(`classification` event: category, severity, team, confidence, rationale). A maintenance defect gets a proposed
i-EMS ticket for the category's team and vendor with the SLA of its severity; nothing reaches the i-EMS mock until
the officer approves it, and the raised ticket links back to the feedback case. Non-defect complaints get no ticket.

Claude (route, the Haiku classifier and merge) is scripted; the i-EMS mock and audit log write to the test's temp
directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plg.actions.audit import AuditLog
from plg.defects.tickets import LocalTicketSystem
from plg.llm import ScriptedLLMClient, tool_call, turn
from tests.conftest import USER, Api, SseStream, route

CR_OFFICER = {"X-PLG-User": "S11"}
"""Grace Chua, Customer Relations Officer."""

RATS_FEEDBACK = "Many rats running around the bin area behind the minimart at Blk 371, U-KR371-01-06."
RATS = f"Classify this feedback: {RATS_FEEDBACK}"
WET_CEILING = "Classify: 'Ceiling near the shop wet and lights flickering, scared got short circuit'"
KARAOKE = "Classify this feedback: the karaoke at the coffeeshop downstairs is so loud every night until 2am."
CASE = "Classify feedback case FB-2025-00003 and route it."


def ems(tmp_path: Path) -> LocalTicketSystem:
    return LocalTicketSystem(tmp_path / "iems")


def audit(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit.jsonl")


def classify(
    api: Api, llm: ScriptedLLMClient, question: str, categories: dict[str, float], rationale: str = "Because.",
    headers: dict[str, str] = CR_OFFICER,
) -> tuple[str, SseStream]:
    """Ask in a new thread; the classifier names `categories` with these confidences."""
    route(llm, question, "defect")
    scored = [{"code": code, "confidence": c} for code, c in categories.items()]
    feedback = question.split(":", 1)[-1].strip()
    llm.script_turns("defect", question, turn(tool_call("classify_feedback", categories=scored, rationale=rationale, feedback=feedback)))
    llm.script("merge", question, "Here is the classification.")
    thread_id = api.create_thread(headers)
    return thread_id, api.run(thread_id, question, headers)


def decide(action: dict[str, Any], decision: str, **extra: Any) -> dict[str, Any]:
    return {"action_id": action["action_id"], "version": action["version"], "decision": decision, **extra}


def test_a_defect_is_classified_and_a_ticket_proposed_for_its_team_vendor_and_sla(
    make_api: Any, llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    api = make_api(iems_dir=tmp_path / "iems")
    _, stream = classify(api, llm, RATS, {"PST": 0.95}, rationale="Rats are a pest infestation.")

    (found,) = stream.of_type("classification")
    assert (found["category_code"], found["category"], found["severity"]) == ("PST", "Pest", "Medium")
    assert (found["team"], found["vendor"]) == ("Pest Control", "PestAway Solutions")
    assert found["confidence"] == 0.95 and not found["low_confidence"]
    assert found["is_defect"] and found["rationale"] == "Rats are a pest infestation."
    (action,) = stream.of_type("proposed_action")
    assert action["action_type"] == "raise_ticket"
    ticket = action["payload"]
    assert (ticket["team"], ticket["vendor"], ticket["severity"], ticket["sla_days"]) == (
        "Pest Control", "PestAway Solutions", "Medium", 7
    )
    assert ticket["unit_id"] == "U-KR371-01-06"
    assert ticket["description"] == RATS_FEEDBACK  # the feedback, not the officer's request
    assert "Pest Control" in str(action["preview"])
    assert stream.of_type("interrupt")
    assert ems(tmp_path).tickets() == []


def test_nothing_reaches_i_ems_until_approved_and_the_ticket_links_back_to_the_feedback_case(
    make_api: Any, llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    api = make_api(iems_dir=tmp_path / "iems")
    thread_id, stream = classify(api, llm, CASE, {"PST": 0.9})
    (action,) = stream.of_type("proposed_action")
    assert action["payload"]["feedback_id"] == "FB-2025-00003"
    assert action["payload"]["unit_id"] == "U-KR371-01-06"  # read from the case in PLG Records
    assert ems(tmp_path).tickets() == []

    resumed = api.resume(thread_id, decide(action, "approve"), headers=CR_OFFICER)

    assert isinstance(resumed, SseStream)
    (raised,) = ems(tmp_path).tickets()
    assert (raised.feedback_id, raised.category_code, raised.team, raised.sla_days) == ("FB-2025-00003", "PST", "Pest Control", 7)
    assert ems(tmp_path).for_feedback("FB-2025-00003") == [raised]
    (result,) = resumed.of_type("action_result")
    assert (result["decision"], result["ticket_id"], result["outbox_id"]) == ("approve", raised.ticket_id, None)
    (entry,) = audit(tmp_path).entries()
    assert (entry.action_type, entry.ticket_id, entry.approver) == ("raise_ticket", raised.ticket_id, "S11")
    (record,) = api.client.get("/audit", headers=CR_OFFICER).json()
    assert record["ticket"]["ticket_id"] == raised.ticket_id and record["sent"] is None


def test_ambiguous_feedback_is_low_confidence_and_resolves_to_the_higher_severity_category(
    make_api: Any, llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    api = make_api(iems_dir=tmp_path / "iems")
    _, stream = classify(api, llm, WET_CEILING, {"SEP": 0.6, "ELE": 0.5})

    (found,) = stream.of_type("classification")
    assert (found["category_code"], found["severity"], found["team"]) == ("ELE", "High", "M&E")
    assert found["low_confidence"] and found["confidence"] < 0.6
    assert {c["code"] for c in found["candidates"]} == {"SEP", "ELE"}  # type: ignore[index]
    (action,) = stream.of_type("proposed_action")
    assert (action["payload"]["category_code"], action["payload"]["sla_days"]) == ("ELE", 3)
    assert action["payload"]["low_confidence"]


def test_a_non_defect_complaint_is_not_routed_to_maintenance(
    make_api: Any, llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    api = make_api(iems_dir=tmp_path / "iems")
    _, stream = classify(api, llm, KARAOKE, {"NOI": 0.9})

    (found,) = stream.of_type("classification")
    assert (found["category_code"], found["team"], found["is_defect"]) == ("NOI", "Estate Compliance", False)
    assert found["vendor"] is None and found["sla_days"] is None
    assert stream.of_type("proposed_action") == [] and stream.of_type("interrupt") == []
    assert stream.text == "Here is the classification."
    assert ems(tmp_path).tickets() == []


def test_a_rejected_ticket_is_never_raised(make_api: Any, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    api = make_api(iems_dir=tmp_path / "iems")
    thread_id, stream = classify(api, llm, RATS, {"PST": 0.95})
    (action,) = stream.of_type("proposed_action")

    resumed = api.resume(thread_id, decide(action, "reject", reason="Already raised by the hotline."), headers=CR_OFFICER)

    assert isinstance(resumed, SseStream)
    assert ems(tmp_path).tickets() == []
    (entry,) = audit(tmp_path).entries()
    assert (entry.decision, entry.ticket_id) == ("reject", None)


def test_an_edited_ticket_is_raised_as_edited_with_the_sla_of_its_new_severity(
    make_api: Any, llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    api = make_api(iems_dir=tmp_path / "iems")
    thread_id, stream = classify(api, llm, WET_CEILING, {"SEP": 0.6, "ELE": 0.5})
    (action,) = stream.of_type("proposed_action")

    assert api.resume(thread_id, decide(action, "edit", edits={"priority": "Urgent"}), headers=CR_OFFICER) == 422
    assert api.resume(thread_id, decide(action, "edit", edits={"severity": "Urgent"}), headers=CR_OFFICER) == 422
    assert api.resume(thread_id, decide(action, "edit", edits={"category_code": "NOI"}), headers=CR_OFFICER) == 422
    edits = {"category_code": "SEP", "severity": "High", "unit_id": "U-PI675-02-07"}
    resumed = api.resume(thread_id, decide(action, "edit", edits=edits), headers=CR_OFFICER)

    assert isinstance(resumed, SseStream)
    (raised,) = ems(tmp_path).tickets()
    assert (raised.category_code, raised.team, raised.vendor) == ("SEP", "Civil & Structural", "Kemas Building Works Pte Ltd")
    assert (raised.severity, raised.sla_days, raised.unit_id) == ("High", 3, "U-PI675-02-07")
    assert raised.version == action["version"] + 1


def test_an_analyst_cannot_raise_a_ticket(make_api: Any, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    api = make_api(iems_dir=tmp_path / "iems")
    analyst = {"X-PLG-User": "S08"}
    thread_id, stream = classify(api, llm, RATS, {"PST": 0.95}, headers=analyst)
    (action,) = stream.of_type("proposed_action")

    assert api.resume(thread_id, decide(action, "approve"), headers=analyst) == 403
    assert ems(tmp_path).tickets() == []


def test_a_pending_ticket_is_listed_with_pending_letters(make_api: Any, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    api = make_api(iems_dir=tmp_path / "iems")
    classify(api, llm, RATS, {"PST": 0.95}, headers=USER)

    (listed,) = api.client.get("/approvals", headers=USER).json()
    assert listed["action_type"] == "raise_ticket" and listed["payload"]["kind"] == "ticket"
