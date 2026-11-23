"""Stop generating (#80): the thread's owner cancels its running run in plg-api. The stream ends with a `cancelled`
event, the turn leaves no trace (no history, no proposed action), and the thread can be asked again at once."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from plg.llm import ScriptedLLMClient, text, tool_call, turn
from tests.conftest import USER, Api, LangSmithApi, SseStream, route
from tests.test_approvals_api import REMINDER, SLOTS

OTHER = {"X-PLG-User": "S01"}
LONG = " ".join(f"word{i}" for i in range(200))
"""An answer that takes seconds to stream at 0.02s a token: long enough to be stopped half way."""


def asking(api: Api, thread_id: str, question: str) -> tuple[threading.Thread, list[SseStream]]:
    """Ask in the background (the browser waiting on the stream); return once the answer is streaming."""
    received: list[SseStream] = []
    worker = threading.Thread(target=lambda: received.append(api.run(thread_id, question)))
    worker.start()
    for _ in range(500):
        if api.client.get(f"/threads/{thread_id}", headers=USER).json()["running"]:
            break
        time.sleep(0.01)
    else:
        raise AssertionError("the question never started")
    time.sleep(0.3)  # into merge's answer (0.02s a token: 4s in all)
    return worker, received


def stopped(worker: threading.Thread) -> None:
    worker.join(timeout=10)
    assert not worker.is_alive(), "the stream never ended"


def cancel(api: Api, thread_id: str, headers: dict[str, str] = USER) -> int:
    return api.client.post(f"/threads/{thread_id}/runs/latest/cancel", headers=headers).status_code


def test_cancelling_a_running_answer_ends_its_stream_with_a_cancelled_event(
    api: Api, llm: ScriptedLLMClient
) -> None:
    route(llm, "hello")
    llm.script("merge", "hello", LONG, delay=0.02)
    thread_id = api.create_thread()
    worker, received = asking(api, thread_id, "hello")

    status = cancel(api, thread_id)
    stopped(worker)

    assert status == 204
    (stream,) = received
    assert stream.of_type("done") == []
    last = stream.events[-1]
    assert last["type"] == "cancelled"
    assert last["run_id"]
    assert last["seq"] == len(stream.events)
    assert 0 < len(stream.of_type("token")) < 200
    assert api.client.get(f"/threads/{thread_id}", headers=USER).json()["running"] is None


def test_a_cancelled_turn_leaves_no_history_and_the_thread_answers_the_next_question(
    api: Api, llm: ScriptedLLMClient
) -> None:
    route(llm, "hello")
    llm.script("merge", "hello", LONG, delay=0.02)
    thread_id = api.create_thread()
    worker, _ = asking(api, thread_id, "hello")
    assert cancel(api, thread_id) == 204
    stopped(worker)

    assert api.client.get(f"/threads/{thread_id}", headers=USER).json()["messages"] == []

    route(llm, "thanks")
    llm.script("merge", "thanks", "You're welcome.")
    again = api.run(thread_id, "thanks")

    assert again.text == "You're welcome."
    assert again.events[-1]["type"] == "done"
    messages = api.client.get(f"/threads/{thread_id}", headers=USER).json()["messages"]
    assert [m["content"] for m in messages] == ["thanks", "You're welcome."]


def test_a_cancelled_drafting_turn_proposes_nothing(api: Api, llm: ScriptedLLMClient) -> None:
    route(llm, REMINDER, "drafting")
    llm.script_turns(
        "drafting", REMINDER,
        turn(tool_call("submit_draft", template_id="TPL-REM-01", slots=SLOTS)), turn(text("Drafted.")),
    )
    llm.script("merge", REMINDER, LONG, delay=0.02)
    thread_id = api.create_thread()
    worker, received = asking(api, thread_id, REMINDER)

    assert cancel(api, thread_id) == 204
    stopped(worker)

    (stream,) = received
    assert stream.of_type("interrupt") == []
    assert api.client.get("/approvals", headers=USER).json() == []
    assert api.client.get(f"/threads/{thread_id}", headers=USER).json()["pending"] == []


def test_only_the_owner_can_cancel_and_nothing_running_is_a_conflict(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = api.create_thread()
    assert cancel(api, thread_id) == 409  # never asked

    route(llm, "hello")
    llm.script("merge", "hello", LONG, delay=0.02)
    worker, received = asking(api, thread_id, "hello")

    assert cancel(api, thread_id, OTHER) == 404
    assert cancel(api, "no-such-thread") == 404
    assert cancel(api, thread_id) == 204
    stopped(worker)
    assert cancel(api, thread_id) == 409  # already stopped
    assert received[0].events[-1]["type"] == "cancelled"


def test_a_finished_run_cannot_be_cancelled(api: Api, llm: ScriptedLLMClient) -> None:
    route(llm, "hello")
    llm.script("merge", "hello", "Hello.")
    thread_id = api.create_thread()
    api.run(thread_id, "hello")

    assert cancel(api, thread_id) == 409
    assert api.client.get(f"/threads/{thread_id}", headers=USER).json()["messages"][-1]["content"] == "Hello."


def test_a_cancelled_run_is_traced_as_cancelled(make_api: Callable[..., Api], llm: ScriptedLLMClient) -> None:
    langsmith = LangSmithApi()
    api = make_api(tracer=langsmith.tracer())
    route(llm, "hello")
    llm.script("merge", "hello", LONG, delay=0.02)
    thread_id = api.create_thread()
    worker, received = asking(api, thread_id, "hello")
    assert cancel(api, thread_id) == 204
    stopped(worker)

    root = langsmith.root(str(received[0].events[-1]["run_id"]))
    assert root["extra"]["metadata"]["cancelled"] is True
    assert "CancelledError" in root["error"]
    assert root["outputs"]["answer"].startswith("word0")
