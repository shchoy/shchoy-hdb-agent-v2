"""Conversation search (#107): GET /search?q= finds the officer's own conversations by keyword (SQLite FTS: titles,
questions and answers; prefixes, so results come as the officer types). Each hit names the conversation once, with its
current title, group and pin, the matching turn (the question's index in ThreadView.messages; None for a title match)
and a snippet whose matched words are marked. No Claude or Voyage call is made."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from plg.llm import ScriptedLLMClient
from tests.conftest import USER, Api, route
from tests.test_groups_api import create, move
from tests.test_pins_api import pin_thread
from tests.test_rename_delete_api import OTHER, ask, delete, rename


def search(api: Api, q: str, headers: dict[str, str] = USER) -> list[dict[str, Any]]:
    response = api.client.get("/search", params={"q": q}, headers=headers)
    assert response.status_code == 200
    return list(response.json()["conversations"])


def marked(hit: dict[str, Any]) -> list[str]:
    """The snippet's highlighted words."""
    return [part["text"] for part in hit["snippet"] if part["match"]]


def follow_up(api: Api, llm: ScriptedLLMClient, thread_id: str, question: str, answer: str) -> None:
    route(llm, question)
    llm.script("merge", question, answer)
    api.run(thread_id, question)


def test_answers_questions_and_titles_are_found_by_prefix(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = ask(api, llm, "When is the rent review due?", "The tenancy at Blk 123 is reviewed in March [1].")
    ask(api, llm, "Unrelated question", "Nothing about it.")

    [hit] = search(api, "tenan")
    assert hit["thread_id"] == thread_id
    assert hit["title"] == "When is the rent review due?"
    assert hit["matched"] == "answer"
    assert hit["message_index"] == 0  # the question opening the matching turn
    assert marked(hit) == ["tenancy"]
    assert "[1]" not in "".join(p["text"] for p in hit["snippet"])

    [by_question] = search(api, "review due")
    assert (by_question["thread_id"], by_question["matched"]) == (thread_id, "question")


def test_the_matching_turn_of_a_longer_conversation_is_named(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = ask(api, llm, "first question", "About arrears.")
    follow_up(api, llm, thread_id, "second question", "About the void deck renovation.")

    [hit] = search(api, "renovation")
    assert (hit["thread_id"], hit["message_index"]) == (thread_id, 2)


def test_renamed_titles_and_new_answers_are_found(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = ask(api, llm, "hello", "Hi there, officer.")
    assert rename(api, thread_id, "Lucky Star arrears") == 200

    [hit] = search(api, "lucky")
    assert (hit["title"], hit["matched"], hit["message_index"]) == ("Lucky Star arrears", "title", None)
    assert search(api, "hello")[0]["title"] == "Lucky Star arrears"  # the first question is still found

    follow_up(api, llm, thread_id, "anything else?", "The licence lapses in October.")
    [hit] = search(api, "licence")
    assert hit["thread_id"] == thread_id and hit["message_index"] == 2


def test_each_conversation_is_listed_once_with_its_group_and_pin(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = ask(api, llm, "arrears at Blk 5", "The arrears are S$4,000.")
    group = create(api, "Arrears")
    move(api, thread_id, group["group_id"])
    pin_thread(api, thread_id)

    [hit] = search(api, "arrears")
    assert hit["group_id"] == group["group_id"] and hit["group_name"] == "Arrears"
    assert hit["pinned"] is not None


def test_only_the_officers_own_conversations_are_searched(api: Api, llm: ScriptedLLMClient) -> None:
    ask(api, llm, "arrears at Blk 5", "The arrears are S$4,000.")

    assert search(api, "arrears", headers=OTHER) == []
    assert api.client.get("/search", params={"q": "arrears"}).status_code == 401


def test_a_deleted_conversation_drops_out_at_once(api: Api, llm: ScriptedLLMClient) -> None:
    thread_id = ask(api, llm, "arrears at Blk 5", "The arrears are S$4,000.")
    assert search(api, "arrears")

    assert delete(api, thread_id)[0] == 204
    assert search(api, "arrears") == []


def test_blank_or_punctuation_only_queries_find_nothing_and_never_fail(api: Api, llm: ScriptedLLMClient) -> None:
    ask(api, llm, "arrears", "The arrears are S$4,000.")

    for q in ["", "   ", '"', "*", "(", "AND", "NEAR(", "-"]:
        assert search(api, q) == [], q


def test_no_claude_call_is_made(api: Api, llm: ScriptedLLMClient) -> None:
    ask(api, llm, "arrears", "The arrears are S$4,000.")
    calls = len(llm.sent)

    search(api, "arrears")
    assert len(llm.sent) == calls


def test_conversations_from_before_the_index_are_found_after_a_restart(
    make_api: Callable[..., Api], llm: ScriptedLLMClient, tmp_path: Path
) -> None:
    import sqlite3
    from contextlib import closing

    api = make_api()
    thread_id = ask(api, llm, "arrears at Blk 5", "The arrears are S$4,000.")
    with closing(sqlite3.connect(tmp_path / "threads.sqlite")) as db, db:
        db.execute("DROP TABLE plg_search")  # as in a threads.sqlite from before #107

    restarted = make_api()
    assert [h["thread_id"] for h in search(restarted, "arrears")] == [thread_id]
