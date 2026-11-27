"""Searching approvals, decisions and memories (#109): GET /search?q= also finds the pending actions the officer may
decide (by title and by what they would send or raise), their own past decisions (title, reason, edits, what was sent)
and their own memories, by keyword prefixes as in the other groups. Nothing of another officer's is returned, except a
change a term owner's Approvals inbox already shows them. No Claude or Voyage call is made."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from plg.llm import ScriptedLLMClient
from tests.conftest import USER, Api
from tests.test_approvals_api import decide, propose
from tests.test_glossary_api import BYSTANDER, POLICY_OWNER, TERM_OWNER
from tests.test_glossary_api import propose as propose_change
from tests.test_memory_api import scratch_memory
from tests.test_rename_delete_api import OTHER


def search(api: Api, q: str, headers: dict[str, str] = USER) -> dict[str, Any]:
    response = api.client.get("/search", params={"q": q}, headers=headers)
    assert response.status_code == 200
    return dict(response.json())


def marked(hit: dict[str, Any]) -> list[str]:
    return [part["text"] for part in hit["snippet"] if part["match"]]


def test_a_pending_action_is_found_by_title_and_by_its_content(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")
    title_word = action["title"].split()[0]

    [by_content] = search(api, "bayshore vale")["approvals"]
    assert (by_content["action_id"], by_content["version"], by_content["thread_id"]) == (
        action["action_id"], action["version"], thread_id,
    )
    assert by_content["matched"] == "content"
    assert set(marked(by_content)) == {"Bayshore", "Vale"}
    assert by_content["title"] == action["title"]
    assert by_content["thread_title"] == api.client.get(f"/threads/{thread_id}", headers=USER).json()["title"]
    assert by_content["action_type"] == "send_letter"

    [by_title] = search(api, title_word[:4].lower())["approvals"]
    assert by_title["matched"] == "title"
    assert search(api, "bayshore nowhere")["approvals"] == []


def test_another_officers_pending_action_is_not_found(api: Api, llm: ScriptedLLMClient) -> None:
    propose(api, llm)

    assert search(api, "bayshore", headers=OTHER)["approvals"] == []


def test_a_term_owner_finds_a_change_to_their_term_as_their_inbox_shows_it(api: Api, llm: ScriptedLLMClient) -> None:
    _, stream = propose_change(api, llm)
    (action,) = stream.of_type("proposed_action")

    [hit] = search(api, "vacant", headers=TERM_OWNER)["approvals"]
    assert (hit["action_id"], hit["thread_title"]) == (action["action_id"], "Proposed by S02")
    assert [h["action_id"] for h in search(api, "vacant", headers=POLICY_OWNER)["approvals"]] == [action["action_id"]]
    assert search(api, "vacant", headers=BYSTANDER)["approvals"] == []


def test_a_decision_is_found_by_its_reason_and_no_longer_as_pending(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")
    api.resume(thread_id, decide(action, "reject", reason="The tenant paid yesterday."))

    found = search(api, "paid yester")
    [hit] = found["decisions"]
    assert (hit["action_id"], hit["version"], hit["decision"], hit["matched"]) == (
        action["action_id"], action["version"], "reject", "reason",
    )
    assert marked(hit) == ["paid", "yesterday"]
    assert hit["title"] == action["title"]
    assert search(api, "bayshore")["approvals"] == []
    assert search(api, "paid", headers=OTHER)["decisions"] == []


def test_a_decision_is_found_by_its_edits_and_what_it_sent(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")
    api.resume(thread_id, decide(action, "edit", edits={"pay_by_date": "21 October 2026"}))
    [entry] = api.client.get("/audit", headers=USER).json()

    [by_edit] = search(api, "21 octo")["decisions"]
    assert (by_edit["matched"], by_edit["decision"]) == ("edits", "edit")
    [by_reference] = search(api, entry["outbox_id"])["decisions"]
    assert by_reference["matched"] == "reference"


def test_own_memories_are_found_and_no_one_elses(
    make_api: Callable[..., Api], llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    memory = scratch_memory(tmp_path)
    api = make_api(memory=memory)
    mine = memory.remember("S05", "preference", "Prefers answers as tables with the tenancy ID first", provenance="test")
    memory.remember("S05", "episode", "Following up arrears at Golden Leaf Minimart", provenance="test")
    memory.remember("S01", "preference", "Prefers tables for every tenancy answer", provenance="test")

    [hit] = search(api, "tabl tenan")["memories"]
    assert (hit["id"], hit["kind"], hit["status"]) == (mine.id, "preference", "active")
    assert marked(hit) == ["tables", "tenancy"]
    [theirs] = search(api, "tabl tenan", headers=OTHER)["memories"]
    assert theirs["id"] != mine.id


def test_searching_items_calls_no_model(api: Api, llm: ScriptedLLMClient) -> None:
    propose(api, llm)
    calls = len(llm.sent)

    assert search(api, "bayshore")["approvals"]
    assert search(api, "  ")["approvals"] == []
    assert len(llm.sent) == calls
