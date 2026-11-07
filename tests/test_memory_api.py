"""Personal long-term memory over HTTP: recall, background learning, privacy and the officer's controls."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from plg.config import REPO_ROOT
from plg.entities.local import LocalGraphStore
from plg.llm import ScriptedLLMClient, tool_call, turn
from plg.memory.service import NODE, RECORD
from plg.memory.store import MemoryStore
from plg.search.embed import HashingEmbedder
from plg.search.lance import LanceSearchStore
from tests.conftest import USER, Api, route

OTHER = {"X-PLG-User": "S01"}
GOLDEN_LEAF = json.loads((REPO_ROOT / "poc-data" / "_master" / "key_entities.json").read_text())["Golden Leaf Minimart Pte Ltd"]


def learn(llm: ScriptedLLMClient, question: str, *memories: tuple[str, str], conflicts: list[str] | None = None) -> None:
    llm.script_turns(NODE, question, turn(tool_call(
        RECORD, memories=[{"kind": k, "text": t} for k, t in memories], conflicts=conflicts or [],
    )))


def ask(api: Api, llm: ScriptedLLMClient, question: str, answer: str = "Noted.") -> None:
    route(llm, question)
    llm.script("merge", question, answer)
    api.run(api.create_thread(), question)


def listed(api: Api, headers: dict[str, str] = USER) -> list[dict[str, object]]:
    return api.client.get("/memory", headers=headers).json()  # type: ignore[no-any-return]


def wait_for(api: Api, condition: Callable[[list[dict[str, object]]], bool], headers: dict[str, str] = USER) -> list[dict[str, object]]:
    """Memory is written in the background, after the answer is done."""
    for _ in range(100):
        found = listed(api, headers)
        if condition(found):
            return found
        time.sleep(0.05)
    raise AssertionError(f"memory never settled: {listed(api, headers)}")


def texts(items: list[dict[str, object]]) -> list[object]:
    return [i["text"] for i in items]


def test_profile_is_seeded_from_staff_records(api: Api) -> None:
    [profile] = listed(api)

    assert profile["kind"] == "profile"
    assert "Siti Aishah Yusof" in str(profile["text"]) and "Leasing Officer" in str(profile["text"])
    assert profile["provenance"] == "Staff records"


def test_an_episode_is_learned_in_the_background_and_expires_after_180_days(api: Api, llm: ScriptedLLMClient) -> None:
    learn(llm, "I'm chasing arrears at Golden Leaf this week", ("episode", "Following up arrears at Golden Leaf Minimart"))
    ask(api, llm, "I'm chasing arrears at Golden Leaf this week")

    [episode] = [i for i in wait_for(api, lambda m: len(m) > 1) if i["kind"] == "episode"]

    assert episode["text"] == "Following up arrears at Golden Leaf Minimart"
    assert str(episode["provenance"]).startswith("Your conversation")
    created, expires = datetime.fromisoformat(str(episode["created_at"])), datetime.fromisoformat(str(episode["expires_at"]))
    assert (expires - created).days == 180


def test_remembered_notes_reach_the_answer_as_a_labelled_block(api: Api, llm: ScriptedLLMClient) -> None:
    learn(llm, "I cover Bedok and like tables", ("preference", "Prefers answers as tables"))
    ask(api, llm, "I cover Bedok and like tables")
    wait_for(api, lambda m: len(m) > 1)

    ask(api, llm, "hello again")

    system = llm.streamed[-1].system
    assert "<memory>" in system and "Prefers answers as tables" in system
    assert "not a source" in system and "policy wins" in system


def test_pii_is_masked_and_near_duplicates_are_merged(api: Api, llm: ScriptedLLMClient) -> None:
    learn(llm, "call me on 91234567", ("preference", "Contact S1234567D at 91234567 or a@b.sg"))
    ask(api, llm, "call me on 91234567")
    [first] = [i for i in wait_for(api, lambda m: len(m) > 1) if i["kind"] == "preference"]
    assert first["text"] == "Contact [NRIC] at [phone] or [email]"

    learn(llm, "again", ("preference", "Contact [NRIC] at [phone] or [email]"))
    ask(api, llm, "again")
    time.sleep(0.5)

    assert len([i for i in listed(api) if i["kind"] == "preference"]) == 1


def test_a_note_that_conflicts_with_current_policy_is_flagged_and_dropped_from_the_prompt(
    api: Api, llm: ScriptedLLMClient
) -> None:
    learn(llm, "LOD goes out at 90 days for me", ("preference", "Sends Letters of Demand at 90 days"))
    ask(api, llm, "LOD goes out at 90 days for me")
    [note] = [i for i in wait_for(api, lambda m: len(m) > 1) if i["kind"] == "preference"]

    learn(llm, "when is a LOD due?", conflicts=[str(note["id"])])
    ask(api, llm, "when is a LOD due?")
    flagged = wait_for(api, lambda m: any(i["status"] == "pending_review" for i in m))
    ask(api, llm, "and now?")

    assert [i["id"] for i in flagged if i["status"] == "pending_review"] == [note["id"]]
    assert "90 days" not in llm.streamed[-1].system


def test_memories_are_private(api: Api, llm: ScriptedLLMClient) -> None:
    learn(llm, "I like tables", ("preference", "Prefers answers as tables"))
    ask(api, llm, "I like tables")
    [mine] = [i for i in wait_for(api, lambda m: len(m) > 1) if i["kind"] == "preference"]

    assert all("tables" not in str(i["text"]) for i in listed(api, OTHER))
    path = f"/memory/{mine['id']}"
    assert api.client.get(path, headers=OTHER).status_code == 404
    assert api.client.patch(path, json={"text": "x"}, headers=OTHER).status_code == 404
    assert api.client.delete(path, headers=OTHER).status_code == 404
    assert api.client.get(path, headers=USER).status_code == 200


def test_officer_edits_and_forgets_a_memory(api: Api, llm: ScriptedLLMClient) -> None:
    learn(llm, "I like tables", ("preference", "Prefers answers as tables"))
    ask(api, llm, "I like tables")
    [mine] = [i for i in wait_for(api, lambda m: len(m) > 1) if i["kind"] == "preference"]
    path = f"/memory/{mine['id']}"

    edited = api.client.patch(path, json={"text": "Prefers short bullet lists"}, headers=USER).json()
    assert edited["text"] == "Prefers short bullet lists" and edited["provenance"] == "edited by you"

    assert api.client.delete(path, headers=USER).status_code == 204
    assert api.client.get(path, headers=USER).status_code == 404


def test_memory_is_never_a_citable_source(api: Api, llm: ScriptedLLMClient) -> None:
    learn(llm, "I like tables", ("preference", "Prefers answers as tables"))
    ask(api, llm, "I like tables")
    wait_for(api, lambda m: len(m) > 1)
    route(llm, "hello again")
    llm.script("merge", "hello again", "Hi.")

    stream = api.run(api.create_thread(), "hello again")

    assert stream.of_type("citation") == []


def test_work_on_an_entity_is_linked_in_the_graph(make_api: Callable[..., Api], llm: ScriptedLLMClient, tmp_path: Path) -> None:
    from plg.entities.spine import write_spine

    write_spine(REPO_ROOT / "poc-data" / "plg_records.db", tmp_path / "graph" / "spine")
    entities = LocalGraphStore.from_dirs(tmp_path / "graph" / "spine", tmp_path / "graph" / "delta")
    api = make_api(entities=entities, graph_dir=tmp_path / "graph")
    tenant = str(GOLDEN_LEAF["tenant"])
    question = f"Pull up {tenant} for me"
    learn(llm, question)

    ask(api, llm, question)

    for _ in range(100):
        context = entities.entity_context("S05", hops=1)
        if context and any(e.type == "WORKED_ON" and e.end == tenant for e in context.edges):
            break
        time.sleep(0.05)
    else:
        raise AssertionError("no WORKED_ON edge")


def scratch_memory(tmp_path: Path) -> MemoryStore:
    embedder = HashingEmbedder(dim=128)
    return MemoryStore(LanceSearchStore(tmp_path / "scratch-memory", dim=embedder.dim), embedder)


def test_past_work_is_recalled_even_when_there_are_many_standing_notes(
    make_api: Callable[..., Api], llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    memory = scratch_memory(tmp_path)
    api = make_api(memory=memory)
    for town in ["Bedok", "Tampines", "Pasir Ris", "Yishun", "Woodlands", "Jurong", "Clementi"]:
        memory.remember("S05", "preference", f"Covers {town} neighbourhood centre", provenance="test")
    memory.remember("S05", "episode", "Following up arrears at Golden Leaf Minimart", provenance="test")
    learn(llm, "Covers neighbourhood centre?")

    ask(api, llm, "Covers neighbourhood centre?")

    assert "Following up arrears at Golden Leaf Minimart" in llm.streamed[-1].system


def test_a_retired_note_stays_retired_when_the_same_thing_is_learned_again(
    make_api: Callable[..., Api], llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    memory = scratch_memory(tmp_path)
    api = make_api(memory=memory)
    note = memory.remember("S05", "preference", "Prefers answers as tables", provenance="test")
    assert api.client.patch(f"/memory/{note.id}", json={"status": "retired"}, headers=USER).status_code == 200
    learn(llm, "I like tables", ("preference", "Prefers answers as tables"))

    ask(api, llm, "I like tables")
    time.sleep(0.5)

    [kept] = [i for i in listed(api) if i["kind"] == "preference"]
    assert kept["status"] == "retired"


def test_a_flagged_note_cannot_be_put_back_over_policy_only_reworded_or_forgotten(
    make_api: Callable[..., Api], tmp_path: Path
) -> None:
    memory = scratch_memory(tmp_path)
    api = make_api(memory=memory)
    note = memory.remember("S05", "preference", "Sends Letters of Demand at 90 days", provenance="test")
    memory.edit("S05", note.id, text=None, status="pending_review")
    path = f"/memory/{note.id}"

    refused = api.client.patch(path, json={"status": "active"}, headers=USER)
    assert refused.status_code == 409
    assert "Edit or forget it" in refused.json()["detail"]
    assert api.client.get(path, headers=USER).json()["status"] == "pending_review"

    reworded = api.client.patch(
        path, json={"text": "For NC units, display limit is 1.0 m under Circular 07/2026"}, headers=USER
    ).json()
    assert reworded["status"] == "active" and reworded["provenance"] == "edited by you"


def test_a_retired_note_can_be_used_again(make_api: Callable[..., Api], tmp_path: Path) -> None:
    memory = scratch_memory(tmp_path)
    api = make_api(memory=memory)
    note = memory.remember("S05", "preference", "Prefers answers as tables", provenance="test")
    path = f"/memory/{note.id}"
    api.client.patch(path, json={"status": "retired"}, headers=USER)

    assert api.client.patch(path, json={"status": "active"}, headers=USER).json()["status"] == "active"
