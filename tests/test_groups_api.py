"""Conversation groups (#100): flat, private groups an officer creates (POST /groups), renames and deletes, and moves
their conversations into (PUT /threads/{id}/group). A conversation is in at most one group; deleting a group returns
its conversations to Recent (group_id null) and never deletes them. Another officer's groups are 404."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

from plg.llm import ScriptedLLMClient
from tests.conftest import USER, Api
from tests.test_rename_delete_api import OTHER, ask


def create(api: Api, name: str, headers: dict[str, str] = USER) -> dict[str, Any]:
    response = api.client.post("/groups", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


def groups(api: Api, headers: dict[str, str] = USER) -> list[str]:
    return [g["name"] for g in api.client.get("/groups", headers=headers).json()]


def move(api: Api, thread_id: str, group_id: str | None, headers: dict[str, str] = USER) -> int:
    return api.client.put(f"/threads/{thread_id}/group", json={"group_id": group_id}, headers=headers).status_code


def membership(api: Api, headers: dict[str, str] = USER) -> dict[str, str | None]:
    return {t["thread_id"]: t["group_id"] for t in api.client.get("/threads", headers=headers).json()}


# ---------------------------------------------------------------- groups


def test_groups_are_created_listed_in_creation_order_renamed_and_deleted(api: Api) -> None:
    arrears = create(api, "  Arrears   cases ")
    create(api, "Renewals")

    assert arrears["name"] == "Arrears cases"
    assert groups(api) == ["Arrears cases", "Renewals"]

    renamed = api.client.patch(f"/groups/{arrears['group_id']}", json={"name": "Arrears"}, headers=USER)
    assert renamed.status_code == 200
    assert renamed.json() == {"group_id": arrears["group_id"], "name": "Arrears"}
    assert groups(api) == ["Arrears", "Renewals"]

    assert api.client.delete(f"/groups/{arrears['group_id']}", headers=USER).status_code == 204
    assert groups(api) == ["Renewals"]


def test_a_blank_or_overlong_group_name_is_refused(api: Api) -> None:
    assert api.client.post("/groups", json={"name": "   "}, headers=USER).status_code == 422
    assert api.client.post("/groups", json={"name": "x" * 81}, headers=USER).status_code == 422
    group = create(api, "Arrears")
    assert api.client.patch(f"/groups/{group['group_id']}", json={"name": ""}, headers=USER).status_code == 422
    assert groups(api) == ["Arrears"]


def test_groups_are_private_to_their_officer(api: Api) -> None:
    group = create(api, "Arrears")
    url = f"/groups/{group['group_id']}"

    assert groups(api, OTHER) == []
    assert api.client.patch(url, json={"name": "Mine"}, headers=OTHER).status_code == 404
    assert api.client.delete(url, headers=OTHER).status_code == 404
    assert groups(api) == ["Arrears"]
    assert api.client.patch("/groups/no-such-group", json={"name": "x"}, headers=USER).status_code == 404
    assert api.client.delete("/groups/no-such-group", headers=USER).status_code == 404


# ---------------------------------------------------------------- moving conversations


def test_a_conversation_moves_into_a_group_between_groups_and_back_to_recent(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = ask(api, llm)
    arrears, renewals = create(api, "Arrears"), create(api, "Renewals")
    assert membership(api) == {thread_id: None}

    response = api.client.put(f"/threads/{thread_id}/group", json={"group_id": arrears["group_id"]}, headers=USER)
    assert response.status_code == 200
    assert response.json()["group_id"] == arrears["group_id"]
    assert membership(api) == {thread_id: arrears["group_id"]}

    assert move(api, thread_id, renewals["group_id"]) == 200
    assert membership(api) == {thread_id: renewals["group_id"]}

    assert move(api, thread_id, None) == 200
    assert membership(api) == {thread_id: None}


def test_a_moved_conversation_keeps_its_title_and_recency_order(api: Api, llm: ScriptedLLMClient) -> None:
    older = ask(api, llm, "older question")
    newer = ask(api, llm, "newer question")
    group = create(api, "Arrears")

    assert move(api, older, group["group_id"]) == 200
    assert move(api, newer, group["group_id"]) == 200

    listed = api.client.get("/threads", headers=USER).json()
    assert [(t["thread_id"], t["title"]) for t in listed] == [(newer, "newer question"), (older, "older question")]


def test_deleting_a_group_returns_its_conversations_to_recent(api: Api, llm: ScriptedLLMClient) -> None:
    first, second = ask(api, llm, "first"), ask(api, llm, "second")
    group = create(api, "Arrears")
    move(api, first, group["group_id"])
    move(api, second, group["group_id"])

    assert api.client.delete(f"/groups/{group['group_id']}", headers=USER).status_code == 204

    assert membership(api) == {first: None, second: None}
    assert api.client.get(f"/threads/{first}", headers=USER).status_code == 200


def test_moving_needs_your_own_conversation_and_your_own_group(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = ask(api, llm)
    mine = create(api, "Arrears")
    theirs = create(api, "Theirs", OTHER)

    assert move(api, thread_id, theirs["group_id"]) == 404
    assert move(api, thread_id, "no-such-group") == 404
    assert move(api, thread_id, mine["group_id"], OTHER) == 404
    assert membership(api) == {thread_id: None}


def test_groups_and_memberships_survive_a_restart(
    make_api: Callable[..., Api], llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    db = tmp_path / "restart.sqlite"
    first = make_api(threads_db=db)
    thread_id = ask(first, llm)
    group = create(first, "Arrears")
    move(first, thread_id, group["group_id"])
    first.client.__exit__(None, None, None)

    second = make_api(threads_db=db)

    assert groups(second) == ["Arrears"]
    assert membership(second) == {thread_id: group["group_id"]}


def test_a_threads_db_from_before_groups_is_upgraded(make_api: Callable[..., Api], tmp_path: Path) -> None:
    """A threads.sqlite written before #100 (no group_id column) still opens; its conversations are under Recent."""
    db = tmp_path / "old.sqlite"
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute(
            "CREATE TABLE plg_threads (thread_id TEXT PRIMARY KEY, staff_id TEXT NOT NULL, title TEXT, updated_at TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO plg_threads VALUES ('t1', 'S05', 'Old', '2026-11-01T00:00:00+00:00')")

    api = make_api(threads_db=db)

    assert membership(api) == {"t1": None}
