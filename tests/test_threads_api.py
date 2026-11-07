"""Conversations persist: thread listing and ownership, restart, long-history summary, reconnect."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from plg.graph.summary import transcript
from plg.llm import ScriptedLLMClient, text, turn
from tests.conftest import USER, Api, parse_sse, route

OTHER = {"X-PLG-User": "S01"}


def ask(api: Api, llm: ScriptedLLMClient, thread_id: str, question: str, answer: str) -> None:
    route(llm, question)
    llm.script("merge", question, answer)
    api.run(thread_id, question)


def test_threads_list_only_own_and_titled_by_first_question(api: Api, llm: ScriptedLLMClient) -> None:
    mine = api.create_thread()
    ask(api, llm, mine, "hello", "Hi there, officer.")
    other = api.client.post("/threads", headers=OTHER).json()["thread_id"]

    listed = api.client.get("/threads", headers=USER).json()

    assert [t["thread_id"] for t in listed] == [mine]
    assert listed[0]["title"] == "hello"
    assert api.client.get("/threads", headers=OTHER).json() == []
    assert other not in [t["thread_id"] for t in listed]


def test_thread_history_is_rebuilt_from_the_checkpoint(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = api.create_thread()
    ask(api, llm, thread_id, "hello", "Hi there, officer.")
    ask(api, llm, thread_id, "and?", "That's all.")

    thread = api.client.get(f"/threads/{thread_id}", headers=USER).json()

    assert thread["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi there, officer."},
        {"role": "user", "content": "and?"},
        {"role": "assistant", "content": "That's all."},
    ]
    assert thread["summary"] == ""


def test_other_users_cannot_read_or_continue_a_thread(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = api.create_thread()
    ask(api, llm, thread_id, "hello", "Hi there, officer.")

    assert api.client.get(f"/threads/{thread_id}", headers=OTHER).status_code == 404
    run = api.client.post(f"/threads/{thread_id}/runs", json={"message": "hi"}, headers=OTHER)
    assert run.status_code == 404
    assert api.client.get(f"/threads/{thread_id}/runs/latest", headers=OTHER).status_code == 404
    assert api.client.get("/threads").status_code == 401


def test_unknown_thread_is_not_found(api: Api) -> None:
    assert api.client.get("/threads/nope", headers=USER).status_code == 404


def test_thread_survives_an_api_restart(
    make_api: Callable[..., Api], llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    db = tmp_path / "restart.sqlite"
    first = make_api(threads_db=db)
    thread_id = first.create_thread()
    ask(first, llm, thread_id, "hello", "Hi there, officer.")
    first.client.__exit__(None, None, None)

    second = make_api(threads_db=db)
    assert [t["thread_id"] for t in second.client.get("/threads", headers=USER).json()] == [thread_id]
    route(llm, "and?")
    llm.script("merge", "and?", "That's all.")
    second.run(thread_id, "and?")

    assert llm.streamed[-1].messages == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi there, officer."},
        {"role": "user", "content": "and?"},
    ]


def test_long_history_is_folded_into_a_summary_keeping_entity_ids(
    make_api: Callable[..., Api], llm: ScriptedLLMClient
) -> None:
    api = make_api(history_token_threshold=20, history_keep_messages=2)
    thread_id = api.create_thread()
    ask(api, llm, thread_id, "Is TA-2024-00451 in arrears for Cendana?", "Tenancy TA-2024-00451 is not in arrears.")
    ask(api, llm, thread_id, "thanks", "You're welcome.")
    folded = [
        {"role": "user", "content": "Is TA-2024-00451 in arrears for Cendana?"},
        {"role": "assistant", "content": "Tenancy TA-2024-00451 is not in arrears."},
    ]
    # The summary the model writes forgets the ID; the system must keep it verbatim.
    llm.script_turns("summarise_history", transcript(folded), turn(text("The officer asked about Cendana's arrears.")))
    route(llm, "and for Cendana?")
    llm.script("merge", "and for Cendana?", "Same answer.")

    api.run(thread_id, "and for Cendana?")

    sent = llm.streamed[-1].messages
    assert "TA-2024-00451" in str(sent[0]["content"])
    assert "Cendana" in str(sent[0]["content"])
    assert sent[-1] == {"role": "user", "content": "and for Cendana?"}
    assert "Is TA-2024-00451 in arrears" not in str(sent[1:])
    thread = api.client.get(f"/threads/{thread_id}", headers=USER).json()
    assert "TA-2024-00451" in thread["summary"]
    assert len(thread["messages"]) == 6  # the full history stays readable


def test_reconnecting_replays_events_after_the_last_one_seen(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = api.create_thread()
    route(llm, "hello")
    llm.script("merge", "hello", "Hi there, officer.")
    full = api.run(thread_id, "hello")

    with api.client.stream(
        "GET", f"/threads/{thread_id}/runs/latest", headers={**USER, "Last-Event-ID": "3"}
    ) as r:
        assert r.status_code == 200
        resumed = parse_sse(r.read().decode())

    assert [e["seq"] for e in resumed.events] == [e["seq"] for e in full.events if e["seq"] > 3]
    assert resumed.events[-1]["type"] == "done"


def test_run_goes_on_without_its_client_and_can_be_picked_up(
    make_api: Callable[..., Api], llm: ScriptedLLMClient
) -> None:
    api = make_api()
    thread_id = api.create_thread()
    route(llm, "hello")
    llm.script("merge", "hello", "one two three four", delay=0.02)
    with api.client.stream("POST", f"/threads/{thread_id}/runs", json={"message": "hello"}, headers=USER) as r:
        lines = r.iter_lines()
        seen = [next(lines) for _ in range(3)]  # then the browser goes away
        assert seen
    with api.client.stream("GET", f"/threads/{thread_id}/runs/latest", headers=USER) as r:
        resumed = parse_sse(r.read().decode())

    assert resumed.text == "one two three four"
    assert resumed.events[-1]["type"] == "done"


def test_no_run_to_resume_is_not_found(api: Api) -> None:
    thread_id = api.create_thread()
    assert api.client.get(f"/threads/{thread_id}/runs/latest", headers=USER).status_code == 404


def test_thread_reports_the_question_of_a_run_still_in_progress(
    make_api: Callable[..., Api], llm: ScriptedLLMClient
) -> None:
    api = make_api()
    thread_id = api.create_thread()
    route(llm, "hello")
    llm.script("merge", "hello", "one two three four five six", delay=0.05)
    asking = threading.Thread(target=api.run, args=(thread_id, "hello"))
    asking.start()
    busy = {}
    for _ in range(100):
        busy = api.client.get(f"/threads/{thread_id}", headers=USER).json()
        if busy["running"]:
            break
        time.sleep(0.01)
    again = api.client.post(f"/threads/{thread_id}/runs", json={"message": "x"}, headers=USER)
    asking.join()

    assert busy["running"] == "hello"
    assert again.status_code == 409
    assert api.client.get(f"/threads/{thread_id}", headers=USER).json()["running"] is None
