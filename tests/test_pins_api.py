"""Pins (#102): an officer pins their own conversations and groups (PUT /threads/{id}/pin, PUT /groups/{id}/pin,
{pinned: bool}). ThreadSummary.pinned / Group.pinned is the item's place in the Pinned section (lower first, in the
order pinned, conversations and groups together); null: not pinned. Pinning keeps a conversation's group, so unpinning
puts it back there. Pins are stored server-side, private and survive a restart."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

from plg.llm import ScriptedLLMClient
from tests.conftest import USER, Api
from tests.test_groups_api import create, move
from tests.test_rename_delete_api import OTHER, ask


def pin_thread(api: Api, thread_id: str, pinned: bool = True, headers: dict[str, str] = USER) -> Any:
    return api.client.put(f"/threads/{thread_id}/pin", json={"pinned": pinned}, headers=headers)


def pin_group(api: Api, group_id: str, pinned: bool = True, headers: dict[str, str] = USER) -> Any:
    return api.client.put(f"/groups/{group_id}/pin", json={"pinned": pinned}, headers=headers)


def pinned(api: Api, headers: dict[str, str] = USER) -> list[str]:
    """Pinned items (thread IDs and group names), in pin order."""
    items: list[tuple[int, str]] = [
        (t["pinned"], t["thread_id"]) for t in api.client.get("/threads", headers=headers).json() if t["pinned"] is not None
    ]
    items += [(g["pinned"], g["name"]) for g in api.client.get("/groups", headers=headers).json() if g["pinned"] is not None]
    return [name for _, name in sorted(items)]


def test_conversations_and_groups_are_pinned_in_pin_order(api: Api, llm: ScriptedLLMClient) -> None:
    first, second = ask(api, llm, "first"), ask(api, llm, "second")
    arrears = create(api, "Arrears")
    assert pinned(api) == []

    response = pin_thread(api, second)
    assert response.status_code == 200
    assert response.json()["thread_id"] == second and response.json()["pinned"] is not None
    group = pin_group(api, arrears["group_id"])
    assert group.status_code == 200
    assert group.json()["group_id"] == arrears["group_id"] and group.json()["pinned"] is not None
    assert pin_thread(api, first).status_code == 200

    assert pinned(api) == [second, "Arrears", first]


def test_pinning_again_keeps_the_place_and_unpinning_removes_it(api: Api, llm: ScriptedLLMClient) -> None:
    first, second = ask(api, llm, "first"), ask(api, llm, "second")
    pin_thread(api, first)
    pin_thread(api, second)

    assert pin_thread(api, first).status_code == 200
    assert pinned(api) == [first, second]

    response = pin_thread(api, first, pinned=False)
    assert response.status_code == 200 and response.json()["pinned"] is None
    assert pinned(api) == [second]
    assert pin_thread(api, first, pinned=False).status_code == 200
    pin_thread(api, first)
    assert pinned(api) == [second, first]


def test_a_pinned_conversation_keeps_its_group_so_unpinning_puts_it_back(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = ask(api, llm)
    group = create(api, "Arrears")
    move(api, thread_id, group["group_id"])

    pin_thread(api, thread_id)
    [listed] = api.client.get("/threads", headers=USER).json()
    assert listed["group_id"] == group["group_id"]

    pin_thread(api, thread_id, pinned=False)
    [listed] = api.client.get("/threads", headers=USER).json()
    assert (listed["group_id"], listed["pinned"]) == (group["group_id"], None)


def test_deleting_a_pinned_group_or_conversation_drops_its_pin(api: Api, llm: ScriptedLLMClient) -> None:
    first, second = ask(api, llm, "first"), ask(api, llm, "second")
    group = create(api, "Arrears")
    move(api, first, group["group_id"])
    pin_thread(api, first)
    pin_group(api, group["group_id"])
    pin_thread(api, second)

    assert api.client.delete(f"/groups/{group['group_id']}", headers=USER).status_code == 204
    assert api.client.delete(f"/threads/{second}", headers=USER).status_code == 204

    assert pinned(api) == [first]


def test_pins_are_private_to_their_officer(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = ask(api, llm)
    group = create(api, "Arrears")
    theirs = create(api, "Theirs", OTHER)
    pin_group(api, theirs["group_id"], headers=OTHER)

    assert pin_thread(api, thread_id, headers=OTHER).status_code == 404
    assert pin_group(api, group["group_id"], headers=OTHER).status_code == 404
    assert pin_group(api, theirs["group_id"]).status_code == 404
    assert pin_thread(api, "no-such-thread").status_code == 404
    assert pin_group(api, "no-such-group").status_code == 404
    assert pinned(api) == []
    assert pinned(api, OTHER) == ["Theirs"]


def test_pins_survive_a_restart(make_api: Callable[..., Api], llm: ScriptedLLMClient, tmp_path: Path) -> None:
    db = tmp_path / "pins.sqlite"
    first = make_api(threads_db=db)
    thread_id = ask(first, llm)
    group = create(first, "Arrears")
    pin_group(first, group["group_id"])
    pin_thread(first, thread_id)
    first.client.__exit__(None, None, None)

    assert pinned(make_api(threads_db=db)) == ["Arrears", thread_id]


def test_a_threads_db_from_before_pins_is_upgraded(make_api: Callable[..., Api], tmp_path: Path) -> None:
    """A threads.sqlite written before #102 (no pinned columns) still opens with nothing pinned."""
    db = tmp_path / "pre102.sqlite"
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute(
            "CREATE TABLE plg_threads (thread_id TEXT PRIMARY KEY, staff_id TEXT NOT NULL, title TEXT, "
            "updated_at TEXT NOT NULL, group_id TEXT)"
        )
        conn.execute(
            "CREATE TABLE plg_groups (group_id TEXT PRIMARY KEY, staff_id TEXT NOT NULL, name TEXT NOT NULL, "
            "created_at TEXT NOT NULL, position INTEGER)"
        )
        conn.execute("INSERT INTO plg_threads VALUES ('t1', 'S05', 'Old', '2026-11-01T00:00:00+00:00', 'g1')")
        conn.execute("INSERT INTO plg_groups VALUES ('g1', 'S05', 'Old group', '2026-11-01T00:00:00+00:00', 0)")

    api = make_api(threads_db=db)

    assert pinned(api) == []
    assert pin_thread(api, "t1").status_code == 200
    assert pin_group(api, "g1").status_code == 200
    assert pinned(api) == ["t1", "Old group"]
