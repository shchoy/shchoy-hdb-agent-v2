"""Document completeness check through plg-api (issue #21): a leasing officer names an application and gets a ✓/✗
checklist for its application type (`doc_check` event), with every submitted file identified by its content (scans
are read by Claude through PDF input) and expired, wrong-unit and illegible documents flagged. An incomplete bundle
gets a missing-documents notice from the approved template, proposed for approval: nothing reaches the Outbox until
the officer approves it.

Claude (route, scan identification and merge) is scripted; the bundles are the 20 in poc-data/pdfs/submissions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from plg.actions.outbox import LocalOutbox
from plg.doccheck.identify import IDENTIFY_NODE, identify_prompt
from plg.llm import ScriptedLLMClient, tool_call, turn
from tests.conftest import CORPUS, USER, Api, SseStream, route

GROUND_TRUTH: list[dict[str, Any]] = json.loads((CORPUS / "_master" / "submission_bundles_ground_truth.json").read_text())

KNOWN_GT_DEVIATIONS = {("APP-2026-0278", "INS"), ("APP-2026-0288", "INS"), ("APP-2026-0268", "INS")}
"""Renewals whose insurance ends before the new term starts (the current tenancy's expiry + 1 day), which the ground
truth nevertheless marks valid: the generator shaped them exactly like the two it marks expired (APP-2026-0272,
APP-2026-0289). The check follows the documented rule ("insurance must cover the new term") and flags all of them."""

SCANS: dict[str, dict[str, Any]] = {
    "NRIC": {
        "document_type": "NRIC", "legible": True, "title": "Identity card (copy) - masked",
        "text": "IDENTITY CARD (COPY) - MASKED\nName: [masked]\nID No.: SXXXX123A\n[photo]\nCertified true copy",
    },
    "GIRO": {
        "document_type": "GIRO", "legible": False, "title": "GIRO authorisation form (HEB rent)",
        "text": "GIRO AUTHORISATION FORM (HEB RENT)\nAccount holder: [illegible]\nAccount no.: [illegible]\nSigned: [illegible]",
    },
}
"""What Claude reads off the bundles' image-only scans: masked identity cards, and one GIRO form too faint to read."""


def bundle(application_id: str) -> dict[str, Any]:
    return next(b for b in GROUND_TRUTH if b["application_id"] == application_id)


def is_scan(file: dict[str, Any]) -> bool:
    return bool(file["doc_code"] == "NRIC" or file["problem"] == "illegible_scan")


def name(file: dict[str, Any]) -> str:
    return str(file["file"]).rsplit("/", 1)[-1]


def check(api: Api, llm: ScriptedLLMClient, application_id: str, headers: dict[str, str] = USER) -> tuple[str, SseStream]:
    """Ask for the check in a new thread; Claude reads the bundle's scans."""
    question = f"Is application {application_id} complete? Check the submitted documents."
    route(llm, question, "doc_check")
    for file in bundle(application_id)["files"]:
        if is_scan(file):
            reading = SCANS["GIRO" if file["problem"] == "illegible_scan" else "NRIC"]
            llm.script_turns(IDENTIFY_NODE, identify_prompt(application_id, name(file)), turn(tool_call("record_document", **reading)))
    llm.script("merge", question, "Here is the document check.")
    thread_id = api.create_thread(headers)
    return thread_id, api.run(thread_id, question, headers)


def decide(action: dict[str, Any], decision: str, **extra: Any) -> dict[str, Any]:
    return {"action_id": action["action_id"], "version": action["version"], "decision": decision, **extra}


def test_results_for_the_20_submission_bundles_match_the_ground_truth(make_api: Any, llm: ScriptedLLMClient) -> None:
    api = make_api()
    for expected in GROUND_TRUTH:
        app = expected["application_id"]
        _, stream = check(api, llm, app)
        (found,) = stream.of_type("doc_check")
        assert found["application_id"] == app and found["app_type"] == expected["app_type"]
        lines = {line["doc_code"]: line for line in found["checklist"]}  # type: ignore[union-attr]
        assert [c for c, line in lines.items() if line["mandatory"]] == expected["expected"], app
        assert [c for c, line in lines.items() if not line["mandatory"]] == expected["optional"], app
        assert {f["doc_code"] for f in found["files"]} == set(expected["present"]), app  # type: ignore[union-attr]
        identified = {f["file"]: f["doc_code"] for f in found["files"]}  # type: ignore[index]
        assert identified == {name(f): f["doc_code"] for f in expected["files"]}, app
        assert found["missing"] == sorted(expected["missing_mandatory"]), app
        flagged = {code: p for code, p in found["problems"].items() if (app, code) not in KNOWN_GT_DEVIATIONS}  # type: ignore[attr-defined]
        assert flagged == expected["problems"], app
        for code in found["problems"]:  # type: ignore[union-attr]
            assert code in expected["problems"] or (app, code) in KNOWN_GT_DEVIATIONS, app
        for deviation_app, code in KNOWN_GT_DEVIATIONS:
            if deviation_app == app:
                assert found["problems"][code] == "expired", app  # type: ignore[index]


def test_the_checklist_follows_the_application_type_with_a_tick_or_cross_per_document(api: Api, llm: ScriptedLLMClient) -> None:
    _, stream = check(api, llm, "APP-2026-0256")  # change of trade, layout plan missing

    (found,) = stream.of_type("doc_check")
    lines = {line["doc_code"]: line for line in found["checklist"]}  # type: ignore[union-attr]
    assert list(lines) == ["COT", "PLAN", "LAYOUT", "LIC"]
    assert {c: (line["mandatory"], line["status"]) for c, line in lines.items()} == {
        "COT": (True, "ok"), "PLAN": (True, "ok"), "LAYOUT": (True, "missing"), "LIC": (False, "ok"),
    }
    assert lines["PLAN"]["files"] == ["plan.pdf"]
    assert not found["complete"]
    assert found["tenant_name"] == "Mutiara Provision Shop" and found["unit_id"] == "U-PI627-01-08"


def test_misnamed_files_and_scans_are_identified_by_content(api: Api, llm: ScriptedLLMClient) -> None:
    _, stream = check(api, llm, "APP-2026-0228")  # scan_0006.pdf is the LOA acceptance; nric.pdf an image-only scan

    (found,) = stream.of_type("doc_check")
    files = {f["file"]: f for f in found["files"]}  # type: ignore[union-attr]
    assert (files["scan_0006.pdf"]["doc_code"], files["scan_0006.pdf"]["read_by"]) == ("LOA", "text")
    assert (files["nric.pdf"]["doc_code"], files["nric.pdf"]["read_by"]) == ("NRIC", "scan")
    (pdf,) = [b for m in llm.sent for b in m[-1]["content"] if isinstance(b, dict) and b.get("type") == "document"]
    assert pdf["source"]["media_type"] == "application/pdf"  # Claude read the scan itself, not its file name


def test_expired_wrong_unit_and_illegible_documents_are_flagged_with_reasons(make_api: Any, llm: ScriptedLLMClient) -> None:
    api = make_api()
    _, expired = check(api, llm, "APP-2026-0293")
    _, wrong_unit = check(api, llm, "APP-2026-0299")
    _, illegible = check(api, llm, "APP-2026-0288")

    def line(stream: SseStream, code: str) -> dict[str, Any]:
        (found,) = stream.of_type("doc_check")
        return next(x for x in found["checklist"] if x["doc_code"] == code)  # type: ignore[union-attr]

    ins = line(expired, "INS")
    assert (ins["status"], ins["problem"]) == ("problem", "expired")
    assert "30 November 2026" in ins["reason"] and "1 January 2027" in ins["reason"]  # ends before the new term
    asg = line(wrong_unit, "ASG")
    assert (asg["status"], asg["problem"]) == ("problem", "wrong_unit")
    assert "U-BV214-01-30" in asg["reason"] and "U-BV214-01-29" in asg["reason"]
    giro = line(illegible, "GIRO")
    assert (giro["status"], giro["problem"]) == ("problem", "illegible_scan")


def test_an_incomplete_bundle_proposes_the_missing_documents_notice_and_nothing_is_sent_until_approved(
    api: Api, llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    thread_id, stream = check(api, llm, "APP-2026-0294")  # A&A: method statement and insurance missing

    (draft,) = stream.of_type("draft")
    assert draft["template_id"] == "TPL-DOC-02"
    listed = str(draft["slots"]["missing_documents_list"])  # type: ignore[index]
    assert "Method statement and work schedule" in listed and "Contractor's all-risk insurance certificate" in listed
    assert "Layout and elevation drawings" not in listed
    assert draft["slots"]["application_id"] == "APP-2026-0294"  # type: ignore[index]
    assert [u["slot"] for u in draft["unfilled"]] == ["letter_ref"]  # type: ignore[union-attr]
    (action,) = stream.of_type("proposed_action")
    assert action["action_type"] == "send_letter" and action["payload"]["template_id"] == "TPL-DOC-02"  # type: ignore[index]
    assert stream.of_type("interrupt")
    outbox = LocalOutbox(tmp_path / "outbox")
    assert outbox.items() == []

    resumed = api.resume(thread_id, decide(action, "edit", edits={"letter_ref": "PLG/TM/APP-2026-0294"}))
    assert isinstance(resumed, SseStream)
    (sent,) = outbox.items()
    assert sent.slots["letter_ref"] == "PLG/TM/APP-2026-0294" and "Method statement" in sent.slots["missing_documents_list"]


def test_problem_documents_are_listed_in_the_notice_with_what_is_wrong(api: Api, llm: ScriptedLLMClient) -> None:
    _, stream = check(api, llm, "APP-2026-0238")  # A&A form names another unit

    (draft,) = stream.of_type("draft")
    listed = str(draft["slots"]["missing_documents_list"])  # type: ignore[index]
    assert "Application for alteration & addition (A&A) works" in listed and "U-KR330-02-06" in listed


def test_a_complete_bundle_gets_all_ticks_and_no_notice(api: Api, llm: ScriptedLLMClient) -> None:
    _, stream = check(api, llm, "APP-2026-0234")

    (found,) = stream.of_type("doc_check")
    assert found["complete"] and found["missing"] == [] and found["problems"] == {}
    assert all(line["status"] == "ok" for line in found["checklist"])  # type: ignore[union-attr]
    assert stream.of_type("proposed_action") == [] and stream.of_type("draft") == []
    assert "complete" in llm.streamed[-1].system


def test_an_application_without_a_bundle_says_so(api: Api, llm: ScriptedLLMClient) -> None:
    question = "Check the documents for APP-2025-0001."
    route(llm, question, "doc_check")
    llm.script("merge", question, "No bundle.")
    stream = api.run(api.create_thread(), question)

    assert stream.of_type("doc_check") == [] and stream.of_type("proposed_action") == []
    assert "no submission bundle" in llm.streamed[-1].system.lower()


@pytest.mark.parametrize("headers", [{}, {"X-PLG-User": "S99"}])
def test_submissions_lists_the_bundles_to_pick_from_for_signed_in_officers(api: Api, headers: dict[str, str]) -> None:
    assert api.client.get("/submissions", headers=headers).status_code == 401
    listed = api.client.get("/submissions", headers=USER).json()
    assert len(listed) == 20
    first = next(s for s in listed if s["application_id"] == "APP-2026-0256")
    assert first == {
        "application_id": "APP-2026-0256", "app_type": "CHANGE_OF_TRADE", "app_type_label": "Change of trade",
        "tenant_name": "Mutiara Provision Shop", "unit_id": "U-PI627-01-08", "submitted_date": "2026-08-24",
        "status": first["status"], "files": 3,
    }
