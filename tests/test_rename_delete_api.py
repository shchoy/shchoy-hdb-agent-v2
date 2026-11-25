"""Rename and delete a conversation (#99): PATCH /threads/{id} sets its title, DELETE /threads/{id} removes it (and its
checkpoint) once nothing is running or pending. Audit entries outlive it; another officer's thread is 404."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from plg.llm import ScriptedLLMClient
from tests.conftest import USER, Api, route
from tests.test_approvals_api import audit, decide, propose
from tests.test_cancel_api import LONG, asking, cancel, stopped

OTHER = {"X-PLG-User": "S01"}


def ask(api: Api, llm: ScriptedLLMClient, question: str = "hello", answer: str = "Hi there, officer.") -> str:
    route(llm, question)
    llm.script("merge", question, answer)
    thread_id = api.create_thread()
    api.run(thread_id, question)
    return thread_id


def rename(api: Api, thread_id: str, title: str, headers: dict[str, str] = USER) -> int:
    return api.client.patch(f"/threads/{thread_id}", json={"title": title}, headers=headers).status_code


def delete(api: Api, thread_id: str, headers: dict[str, str] = USER) -> tuple[int, str]:
    r = api.client.delete(f"/threads/{thread_id}", headers=headers)
    return r.status_code, r.json().get("detail", "") if r.content else ""


def titles(api: Api, headers: dict[str, str] = USER) -> list[str]:
    return [t["title"] for t in api.client.get("/threads", headers=headers).json()]


def checkpoints(db: Path, thread_id: str) -> int:
    """The thread's rows in the LangGraph checkpoint table: #99 requires the checkpoint itself to go, which no HTTP
    response can show (a deleted thread is 404 before the checkpoint is read)."""
    with sqlite3.connect(db) as conn:
        (count,) = conn.execute("SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?", (thread_id,)).fetchone()
    return int(count)


# ---------------------------------------------------------------- rename


def test_renaming_changes_the_title_listed_and_shown(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = ask(api, llm)

    response = api.client.patch(f"/threads/{thread_id}", json={"title": "  Golden   Leaf arrears  "}, headers=USER)

    assert response.status_code == 200
    assert response.json()["title"] == "Golden Leaf arrears"
    assert titles(api) == ["Golden Leaf arrears"]
    assert api.client.get(f"/threads/{thread_id}", headers=USER).json()["title"] == "Golden Leaf arrears"


def test_a_renamed_title_is_kept_by_later_questions_and_a_restart(
    make_api: Callable[..., Api], llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    db = tmp_path / "restart.sqlite"
    first = make_api(threads_db=db)
    thread_id = ask(first, llm)
    assert rename(first, thread_id, "Arrears") == 200
    route(llm, "and?")
    llm.script("merge", "and?", "That's all.")
    first.run(thread_id, "and?")
    first.client.__exit__(None, None, None)

    second = make_api(threads_db=db)

    assert titles(second) == ["Arrears"]


def test_a_blank_or_overlong_title_is_refused(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = ask(api, llm)

    assert rename(api, thread_id, "   ") == 422
    assert rename(api, thread_id, "x" * 81) == 422
    assert titles(api) == ["hello"]


def test_another_officers_conversation_cannot_be_renamed(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = ask(api, llm)

    assert rename(api, thread_id, "Mine now", OTHER) == 404
    assert rename(api, "nope", "Anything") == 404
    assert titles(api) == ["hello"]


# ---------------------------------------------------------------- delete


def test_a_deleted_conversation_is_gone_everywhere(api: Api, llm: ScriptedLLMClient, tmp_path: Path) -> None:
    thread_id = ask(api, llm)
    run_id = api.client.get(f"/threads/{thread_id}", headers=USER).json()["turns"][0]["run_id"]
    assert checkpoints(tmp_path / "threads.sqlite", thread_id) > 0

    assert delete(api, thread_id)[0] == 204

    assert titles(api) == []
    assert checkpoints(tmp_path / "threads.sqlite", thread_id) == 0
    get = api.client.get
    post = api.client.post
    assert get(f"/threads/{thread_id}", headers=USER).status_code == 404
    assert post(f"/threads/{thread_id}/runs", json={"message": "hi"}, headers=USER).status_code == 404
    assert get(f"/threads/{thread_id}/runs/latest", headers=USER).status_code == 404
    assert cancel(api, thread_id) == 404
    assert api.resume(thread_id, {"action_id": "a", "version": 1, "decision": "approve"}) == 404
    assert get(f"/threads/{thread_id}/runs/{run_id}/trace", headers={"X-PLG-User": "S08"}).status_code == 404
    feedback = {"thread_id": thread_id, "run_id": run_id, "score": "up"}
    assert post("/feedback", json=feedback, headers=USER).status_code == 404
    assert rename(api, thread_id, "Back") == 404
    assert delete(api, thread_id)[0] == 404


def test_deleting_keeps_the_audit_entries_of_the_conversation(
    api: Api, llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    thread_id, stream = propose(api, llm)
    (action,) = stream.of_type("proposed_action")
    api.resume(thread_id, decide(action, "reject", reason="Paid yesterday."))

    assert delete(api, thread_id)[0] == 204

    (entry,) = audit(tmp_path).entries()
    assert entry.thread_id == thread_id
    assert [e["action_id"] for e in api.client.get("/audit", headers=USER).json()] == [action["action_id"]]


def test_a_conversation_with_a_pending_action_cannot_be_deleted(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id, _ = propose(api, llm)

    status, detail = delete(api, thread_id)

    assert status == 409
    assert "approval" in detail
    assert len(titles(api)) == 1
    assert api.client.get("/approvals", headers=USER).json()


def test_a_conversation_still_answering_cannot_be_deleted(api: Api, llm: ScriptedLLMClient) -> None:
    route(llm, "hello")
    llm.script("merge", "hello", LONG, delay=0.02)
    thread_id = api.create_thread()
    worker, _ = asking(api, thread_id, "hello")

    status, detail = delete(api, thread_id)
    cancel(api, thread_id)
    stopped(worker)

    assert status == 409
    assert "answering" in detail
    assert api.client.get(f"/threads/{thread_id}", headers=USER).status_code == 200


def test_another_officers_conversation_cannot_be_deleted(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = ask(api, llm)

    assert delete(api, thread_id, OTHER)[0] == 404
    assert titles(api) == ["hello"]
