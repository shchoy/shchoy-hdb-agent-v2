"""Approvals through plg-api: a drafted letter is only *proposed* (`proposed_action` + `interrupt` events). Nothing
reaches the outbox until the officer resumes the thread with an approval of the exact pending version; a rejection
leaves nothing; an edit sends the edited letter. Every executed action has exactly one audit entry.

Claude is scripted; the outbox and audit log are the local adapters, writing to the test's temp directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plg.actions.audit import AuditLog
from plg.actions.outbox import LocalOutbox
from plg.llm import ScriptedLLMClient, text, tool_call, turn
from tests.conftest import USER, Api, SseStream, route

REMINDER = "Draft a first reminder letter for Golden Leaf Minimart Pte Ltd's overdue rent"

SLOTS = {
    "letter_ref": "PLG/REM/2026/001",
    "letter_date": "30 September 2026",
    "tenant_name": "Golden Leaf Minimart Pte Ltd",
    "tenant_address": "#01-32, Blk 214 Bayshore Vale Drive, Singapore 460214",
    "unit_address": "Blk 214 Bayshore Vale Drive #01-32",
    "tenancy_id": "TA-2024-00542",
    "notice_level": "FIRST",
    "invoice_table": "INV-1 | 2026-08 | due 2026-08-01 | S$3,924.00",
    "total_due": "S$3,924.00",
    "pay_by_date": "14 October 2026",
    "officer_name": "Siti Aishah Yusof",
    "officer_phone": "+65 6100 2058",
}


def outbox(tmp_path: Path) -> LocalOutbox:
    return LocalOutbox(tmp_path / "outbox")


def audit(tmp_path: Path) -> AuditLog:
    return AuditLog(tmp_path / "audit.jsonl")


def propose(
    api: Api, llm: ScriptedLLMClient, question: str = REMINDER, slots: dict[str, str] | None = None,
    headers: dict[str, str] = USER,
) -> tuple[str, SseStream]:
    """Ask for a reminder letter in a new thread; the drafting agent submits it with `slots`."""
    route(llm, question, "drafting")
    llm.script_turns("drafting", question, turn(tool_call("submit_draft", template_id="TPL-REM-01", slots=slots or SLOTS)), turn(text("Drafted.")))
    llm.script("merge", question, "Your draft is ready for your approval.")
    thread_id = api.create_thread(headers)
    return thread_id, api.run(thread_id, question, headers)


def decide(action: dict[str, Any], decision: str, **extra: Any) -> dict[str, Any]:
    return {"action_id": action["action_id"], "version": action["version"], "decision": decision, **extra}


def test_a_drafted_letter_is_proposed_and_nothing_is_sent_until_approved(
    api: Api, llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    thread_id, stream = propose(api, llm)

    (action,) = stream.of_type("proposed_action")
    (paused,) = stream.of_type("interrupt")
    assert action["action_type"] == "send_letter"
    assert (paused["action_id"], paused["version"]) == (action["action_id"], action["version"])
    assert "Golden Leaf Minimart Pte Ltd" in str(action["preview"])
    assert stream.of_type("done")
    assert outbox(tmp_path).items() == []
    assert audit(tmp_path).entries() == []

    resumed = api.resume(thread_id, decide(action, "approve"))

    assert isinstance(resumed, SseStream)
    (sent,) = outbox(tmp_path).items()
    assert sent.action_id == action["action_id"]
    assert "Golden Leaf Minimart Pte Ltd" in sent.html
    (entry,) = audit(tmp_path).entries()
    assert (entry.action_id, entry.decision, entry.approver) == (action["action_id"], "approve", "S05")
    assert entry.outbox_id == sent.item_id
    assert entry.run_id == resumed.of_type("done")[0]["run_id"]
    assert entry.at


def test_a_rejection_sends_nothing_and_records_the_reason(api: Api, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")

    resumed = api.resume(thread_id, decide(action, "reject", reason="The tenant paid yesterday."))

    assert isinstance(resumed, SseStream)
    (result,) = resumed.of_type("action_result")
    assert (result["decision"], result["outbox_id"]) == ("reject", None)
    assert outbox(tmp_path).items() == []
    (entry,) = audit(tmp_path).entries()
    assert (entry.decision, entry.reason, entry.outbox_id) == ("reject", "The tenant paid yesterday.", None)
    assert api.client.get("/approvals", headers=USER).json() == []


def test_a_rejection_needs_a_reason(api: Api, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")

    assert api.resume(thread_id, decide(action, "reject")) == 422
    assert audit(tmp_path).entries() == []
    assert len(api.client.get("/approvals", headers=USER).json()) == 1


def test_an_edit_sends_the_edited_letter(api: Api, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")

    resumed = api.resume(thread_id, decide(action, "edit", edits={"pay_by_date": "21 October 2026"}))

    assert isinstance(resumed, SseStream)
    (sent,) = outbox(tmp_path).items()
    assert "21 October 2026" in sent.html and "14 October 2026" not in sent.html
    assert sent.slots["pay_by_date"] == "21 October 2026"
    assert sent.version == action["version"] + 1
    (entry,) = audit(tmp_path).entries()
    assert (entry.decision, entry.version, entry.edits) == ("edit", action["version"], {"pay_by_date": "21 October 2026"})


def test_a_letter_with_open_slots_is_sent_only_once_they_are_filled(
    api: Api, llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    slots = {k: v for k, v in SLOTS.items() if k != "letter_ref"}
    thread_id, stream = propose(api, llm, slots=slots)
    (action,) = stream.of_type("proposed_action")

    assert api.resume(thread_id, decide(action, "approve")) == 422
    assert api.resume(thread_id, decide(action, "edit", edits={"tenant_name": "Golden Leaf"})) == 422
    assert outbox(tmp_path).items() == []

    api.resume(thread_id, decide(action, "edit", edits={"letter_ref": "PLG/REM/2026/007"}))
    (sent,) = outbox(tmp_path).items()
    assert "PLG/REM/2026/007" in sent.html


def test_only_the_exact_pending_version_can_be_approved_once(
    api: Api, llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")

    assert api.resume(thread_id, {**decide(action, "approve"), "version": action["version"] + 1}) == 409
    assert api.resume(thread_id, {**decide(action, "approve"), "action_id": "not-an-action"}) == 409
    assert outbox(tmp_path).items() == []

    assert isinstance(api.resume(thread_id, decide(action, "approve")), SseStream)
    assert api.resume(thread_id, decide(action, "approve")) == 409  # replayed
    assert len(outbox(tmp_path).items()) == 1
    assert len(audit(tmp_path).entries()) == 1


def test_another_officer_cannot_decide_or_see_the_action(api: Api, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")
    manager = {"X-PLG-User": "S03"}  # outranks the owner, but it isn't their conversation

    assert api.resume(thread_id, decide(action, "approve"), headers=manager) == 404
    assert api.client.get("/approvals", headers=manager).json() == []
    assert outbox(tmp_path).items() == []
    assert audit(tmp_path).entries() == []


def test_a_role_without_authority_cannot_send_a_letter(api: Api, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    analyst = {"X-PLG-User": "S08"}
    thread_id, stream = propose(api, llm, headers=analyst)
    (action,) = stream.of_type("proposed_action")
    assert "analyst" not in action["approver_roles"]

    assert api.resume(thread_id, decide(action, "approve"), headers=analyst) == 403
    assert outbox(tmp_path).items() == []
    assert audit(tmp_path).entries() == []


def test_pending_approvals_are_listed_across_conversations(api: Api, llm: ScriptedLLMClient) -> None:
    first, _ = propose(api, llm)
    other = "Draft a second reminder letter for Golden Leaf Minimart Pte Ltd"
    second, _ = propose(api, llm, question=other)

    listed = api.client.get("/approvals", params={"status": "pending"}, headers=USER).json()

    assert [a["thread_id"] for a in listed] == [first, second]
    assert all(a["action_type"] == "send_letter" and a["status"] == "pending" for a in listed)
    assert [a["action_id"] for a in api.client.get(f"/threads/{first}", headers=USER).json()["pending"]] == [listed[0]["action_id"]]


def test_a_pending_approval_survives_an_api_restart(
    make_api: Any, llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    thread_id, stream = propose(make_api(), llm)
    (action,) = stream.of_type("proposed_action")

    restarted = make_api()  # same threads_db, new process state
    (listed,) = restarted.client.get("/approvals", headers=USER).json()
    assert (listed["action_id"], listed["version"]) == (action["action_id"], action["version"])

    assert isinstance(restarted.resume(thread_id, decide(action, "approve")), SseStream)
    assert len(outbox(tmp_path).items()) == 1


def test_a_redraft_replaces_the_pending_version(api: Api, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    thread_id, stream = propose(api, llm)
    (first,) = stream.of_type("proposed_action")
    again = "Make the pay-by date 28 October 2026"
    route(llm, again, "drafting")
    llm.script_turns("drafting", again, turn(tool_call("submit_draft", template_id="TPL-REM-01", slots={**SLOTS, "pay_by_date": "28 October 2026"})), turn(text("Redrafted.")))
    llm.script("merge", again, "Here is the revised draft.")

    (second,) = api.run(thread_id, again).of_type("proposed_action")

    assert (second["action_id"], second["version"]) == (first["action_id"], first["version"] + 1)
    assert api.resume(thread_id, decide(first, "approve")) == 409  # what the officer saw first is no longer pending
    api.resume(thread_id, decide(second, "approve"))
    (sent,) = outbox(tmp_path).items()
    assert "28 October 2026" in sent.html


def test_no_model_is_offered_a_tool_that_acts(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")
    api.resume(thread_id, decide(action, "approve"))

    offered = {tool["name"] for _, tools in llm.requests for tool in tools}
    assert offered <= {"route", "get_template", "lookup_records", "submit_draft", "record_memory"}


def test_an_edit_cannot_blank_a_slot_of_the_letter(api: Api, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")

    assert api.resume(thread_id, decide(action, "edit", edits={"tenant_name": " "})) == 422
    assert outbox(tmp_path).items() == []


def test_an_officer_can_reject_an_action_their_role_cannot_approve(
    api: Api, llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    analyst = {"X-PLG-User": "S08"}
    thread_id, stream = propose(api, llm, headers=analyst)
    (action,) = stream.of_type("proposed_action")

    assert isinstance(api.resume(thread_id, decide(action, "reject", reason="Not mine to send."), headers=analyst), SseStream)
    assert outbox(tmp_path).items() == []
    assert api.client.get("/approvals", headers=analyst).json() == []


NOTICE = "Draft a missing documents notice for APP-2025-0012"
NOTICE_SLOTS = {
    "letter_ref": "PLG/DOC/2026/001", "letter_date": "30 September 2026", "tenant_name": "Example Pte Ltd",
    "contact_person": "Ms Tan", "application_id": "APP-2025-0012", "application_type": "NEW TENANCY",
    "unit_address": "Blk 1 #01-01", "missing_documents_list": "1. ACRA profile (missing)",
    "submit_by_date": "14 October 2026", "officer_name": "Siti Aishah Yusof",
    "officer_email": "siti.aishah@heb.example.org",
}


def test_every_pending_action_of_a_thread_can_be_decided(api: Api, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    thread_id, stream = propose(api, llm)
    (reminder,) = stream.of_type("proposed_action")
    route(llm, NOTICE, "drafting")
    llm.script_turns("drafting", NOTICE, turn(tool_call("submit_draft", template_id="TPL-DOC-02", slots=NOTICE_SLOTS)), turn(text("Drafted.")))
    llm.script("merge", NOTICE, "Your notice is ready for your approval.")
    api.run(thread_id, NOTICE)

    listed = api.client.get("/approvals", headers=USER).json()
    notice = next(a for a in listed if a["action_id"] != reminder["action_id"])
    assert len(listed) == 2

    api.resume(thread_id, decide(notice, "approve"))  # the later one first
    api.resume(thread_id, decide(reminder, "approve"))
    assert {i.action_id for i in outbox(tmp_path).items()} == {reminder["action_id"], notice["action_id"]}
