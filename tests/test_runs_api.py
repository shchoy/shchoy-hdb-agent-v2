"""plg-api threads/runs contract, exercised in-process with a scripted LLMClient."""

from __future__ import annotations

from collections.abc import Callable

from plg.llm import ScriptedLLMClient
from tests.conftest import USER, Api


def test_question_streams_answer_tokens_and_finishes_with_run_id(
    api: Api, llm: ScriptedLLMClient
) -> None:
    llm.script("merge", "hello", "Hello! How can I help with PLG today?")
    thread_id = api.create_thread()

    stream = api.run(thread_id, "hello")

    assert stream.text == "Hello! How can I help with PLG today?"
    assert len(stream.of_type("token")) > 1
    assert stream.events[-1]["type"] == "done"
    assert stream.events[-1]["run_id"]


def test_failure_mid_answer_ends_the_stream_with_an_error_event(
    api: Api, llm: ScriptedLLMClient
) -> None:
    llm.script(
        "merge", "hello", "The letter of demand is", error=ConnectionError("Claude unavailable")
    )
    stream = api.run(api.create_thread(), "hello")

    assert stream.text == "The letter of demand is"
    assert stream.of_type("done") == []
    error = stream.events[-1]
    assert error["type"] == "error"
    assert error["message"]
    assert error["run_id"]
    assert error["seq"] == len(stream.events)


def test_slow_run_sends_heartbeat_comments(
    make_api: Callable[..., Api], llm: ScriptedLLMClient
) -> None:
    api = make_api(heartbeat_seconds=0.05)
    llm.script("merge", "hello", "one two three four five", delay=0.05)

    stream = api.run(api.create_thread(), "hello")

    assert stream.comments
    assert stream.text == "one two three four five"


def test_run_on_unknown_thread_is_not_found(api: Api) -> None:
    response = api.client.post(
        "/threads/no-such-thread/runs", json={"message": "hello"}, headers=USER
    )

    assert response.status_code == 404


def test_every_event_carries_an_increasing_sequence_number(
    api: Api, llm: ScriptedLLMClient
) -> None:
    llm.script("merge", "hello", "Hi there, officer.")
    stream = api.run(api.create_thread(), "hello")

    seqs = [e["seq"] for e in stream.events]
    assert seqs == list(range(1, len(stream.events) + 1))
    assert stream.ids == [str(s) for s in seqs]


def test_node_events_bracket_the_streamed_answer(api: Api, llm: ScriptedLLMClient) -> None:
    llm.script("merge", "hello", "Hi there, officer.")
    stream = api.run(api.create_thread(), "hello")

    trajectory = [(e["type"], e.get("node"), e.get("status")) for e in stream.events]
    tokens = [("token", "merge", None)] * len(stream.of_type("token"))
    assert trajectory == [
        ("node", "merge", "started"),
        *tokens,
        ("node", "merge", "finished"),
        ("done", None, None),
    ]


def test_retrying_a_failed_question_asks_claude_it_only_once(
    api: Api, llm: ScriptedLLMClient
) -> None:
    llm.script("merge", "hello", "Hi", error=ConnectionError("Claude unavailable"))
    thread_id = api.create_thread()
    api.run(thread_id, "hello")
    llm.script("merge", "hello", "Hi there, officer.")

    retried = api.run(thread_id, "hello")

    assert retried.text == "Hi there, officer."
    assert llm.sent[-1] == [{"role": "user", "content": "hello"}]


def test_follow_up_question_carries_the_earlier_exchange(
    api: Api, llm: ScriptedLLMClient
) -> None:
    llm.script("merge", "hello", "Hi there, officer.")
    llm.script("merge", "and?", "That's all.")
    thread_id = api.create_thread()
    api.run(thread_id, "hello")

    api.run(thread_id, "and?")

    assert llm.sent[-1] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hi there, officer."},
        {"role": "user", "content": "and?"},
    ]
