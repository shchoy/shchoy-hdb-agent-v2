"""Library → My documents (issue #106): an officer manages their uploads.

`GET /my-documents` lists the officer's uploads with the conversations that used them (attached to a question, or
cited in an answer) and the space used against the cap. `PATCH /uploads/{id}` renames one, `DELETE /uploads/{id}`
removes it from search; answers that cited it show the source as removed. Deleting a conversation keeps its uploads.

Claude is scripted; search runs over the synced poc-data corpus with the real local cross-encoder.
"""

from __future__ import annotations

from typing import Any

from plg.ingest.scans import SCAN_NODE, SCAN_PROMPT
from plg.llm import ScriptedLLMClient, tool_call, turn
from tests.conftest import USER, Api, SseStream
from tests.test_uploads_api import (
    NOTE, OTHER, QUESTION, SCAN, SCAN_PAGES, ask, scan_calls, script_search, shown_doc_ids, uploaded,
    uploads_api,  # noqa: F401 (fixture)
)


def my_documents(api: Api, headers: dict[str, str] = USER) -> dict[str, Any]:
    response = api.client.get("/my-documents", headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


def entry(api: Api, upload_id: str) -> dict[str, Any]:
    return next(u for u in my_documents(api)["uploads"] if u["upload_id"] == upload_id)


def asked_with(api: Api, llm: ScriptedLLMClient, attachments: list[str], question: str = QUESTION) -> str:
    script_search(llm, question, "kiosk 01-17 follow-up", "follow-up visit", "A follow-up visit on 14 October 2026.")
    thread = api.create_thread()
    stream = ask(api, thread, question, attachments)
    assert isinstance(stream, SseStream)
    return thread


# ---------------------------------------------------------------- listing


def test_uploads_are_listed_with_space_used_against_the_cap(uploads_api: Api) -> None:
    first = uploaded(uploads_api, "site-visit.txt", NOTE.encode())
    second = uploaded(uploads_api, "notes.md", b"# Kiosk 01-17\n\nFollow-up visit on 14 October 2026.\n")

    listing = my_documents(uploads_api)

    assert [u["upload_id"] for u in listing["uploads"]] == [second["upload_id"], first["upload_id"]]
    item = listing["uploads"][1]
    assert (item["filename"], item["kind"], item["size"]) == ("site-visit.txt", "text", len(NOTE.encode()))
    assert item["uploaded_at"]
    assert item["conversations"] == []  # uploaded from the Library: no conversation yet
    assert listing["used_bytes"] == first["size"] + second["size"]
    assert listing["quota_bytes"] == 200 * 1024 * 1024
    assert my_documents(uploads_api, OTHER) == {"uploads": [], "used_bytes": 0, "quota_bytes": 200 * 1024 * 1024}


def test_a_conversation_the_upload_was_attached_to_is_listed(uploads_api: Api, llm: ScriptedLLMClient) -> None:
    item = uploaded(uploads_api, "site-visit.txt", NOTE.encode())

    thread = asked_with(uploads_api, llm, [item["upload_id"]])

    assert entry(uploads_api, item["upload_id"])["conversations"] == [{"thread_id": thread, "title": QUESTION}]


def test_a_conversation_whose_answer_cited_the_upload_is_listed(uploads_api: Api, llm: ScriptedLLMClient) -> None:
    item = uploaded(uploads_api, "site-visit.txt", NOTE.encode())

    thread = asked_with(uploads_api, llm, [])  # not attached: found by the search and cited

    assert [c["thread_id"] for c in entry(uploads_api, item["upload_id"])["conversations"]] == [thread]


# ---------------------------------------------------------------- renaming


def test_an_upload_can_be_renamed(uploads_api: Api, llm: ScriptedLLMClient) -> None:
    item = uploaded(uploads_api, "site-visit.txt", NOTE.encode())

    response = uploads_api.client.patch(
        f"/uploads/{item['upload_id']}", json={"title": "  Kiosk   01-17 visit "}, headers=USER
    )

    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Kiosk 01-17 visit"
    assert entry(uploads_api, item["upload_id"])["title"] == "Kiosk 01-17 visit"
    assert uploads_api.client.get(f"/documents/{item['upload_id']}", headers=USER).json()["title"] == "Kiosk 01-17 visit"
    script_search(llm, QUESTION, "kiosk 01-17 follow-up", "follow-up visit", "A follow-up visit.")
    stream = ask(uploads_api, uploads_api.create_thread(), QUESTION, [item["upload_id"]])
    assert isinstance(stream, SseStream)
    assert [c["title"] for c in stream.of_type("citation")] == ["Kiosk 01-17 visit"]


def test_a_blank_name_or_someone_elses_upload_is_refused(uploads_api: Api) -> None:
    item = uploaded(uploads_api, "site-visit.txt", NOTE.encode())
    path = f"/uploads/{item['upload_id']}"

    assert uploads_api.client.patch(path, json={"title": "   "}, headers=USER).status_code == 422
    assert uploads_api.client.patch(path, json={"title": "x" * 121}, headers=USER).status_code == 422
    assert uploads_api.client.patch(path, json={"title": "Mine now"}, headers=OTHER).status_code == 404
    assert uploads_api.client.patch("/uploads/upload-0000000000000000", json={"title": "A"}, headers=USER).status_code == 404
    assert entry(uploads_api, item["upload_id"])["title"] == "site-visit.txt"


# ---------------------------------------------------------------- deleting


def test_a_deleted_upload_leaves_search_and_frees_its_space(uploads_api: Api, llm: ScriptedLLMClient) -> None:
    item = uploaded(uploads_api, "site-visit.txt", NOTE.encode())
    doc = item["upload_id"]

    assert uploads_api.client.delete(f"/uploads/{doc}", headers=USER).status_code == 204

    assert my_documents(uploads_api)["uploads"] == []
    assert my_documents(uploads_api)["used_bytes"] == 0
    assert uploads_api.client.get("/uploads", headers=USER).json() == []
    assert uploads_api.client.get(f"/documents/{doc}", headers=USER).status_code == 404
    assert uploads_api.client.get(f"/documents/{doc}/file", headers=USER).status_code == 404
    assert uploads_api.client.get(f"/documents/{doc}/chunks/{doc}%23000", headers=USER).status_code == 404
    script_search(llm, QUESTION, "kiosk shutter jammed walkway crates", "follow-up visit", "A follow-up visit.")
    ask(uploads_api, uploads_api.create_thread(), QUESTION, [])
    assert doc not in shown_doc_ids(llm)
    assert ask(uploads_api, uploads_api.create_thread(), QUESTION, [doc]) == 404
    assert uploads_api.client.delete(f"/uploads/{doc}", headers=USER).status_code == 404


def test_only_the_owner_can_delete_an_upload(uploads_api: Api) -> None:
    item = uploaded(uploads_api, "site-visit.txt", NOTE.encode())

    assert uploads_api.client.delete(f"/uploads/{item['upload_id']}", headers=OTHER).status_code == 404
    assert [u["upload_id"] for u in my_documents(uploads_api)["uploads"]] == [item["upload_id"]]


def test_answers_that_cited_a_deleted_upload_show_the_source_as_removed(uploads_api: Api, llm: ScriptedLLMClient) -> None:
    item = uploaded(uploads_api, "site-visit.txt", NOTE.encode())
    thread = asked_with(uploads_api, llm, [item["upload_id"]])
    before = uploads_api.client.get(f"/threads/{thread}", headers=USER).json()
    assert [c["removed"] for t in before["turns"] for c in t["citations"]] == [False]

    uploads_api.client.delete(f"/uploads/{item['upload_id']}", headers=USER)

    after = uploads_api.client.get(f"/threads/{thread}", headers=USER).json()
    (citation,) = [c for t in after["turns"] for c in t["citations"]]
    assert (citation["upload"], citation["removed"]) == (True, True)
    assert after["messages"] == before["messages"]  # the answer itself is kept


def test_a_deleted_scan_is_read_again_if_uploaded_again(uploads_api: Api, llm: ScriptedLLMClient) -> None:
    reply = turn(tool_call("record_transcript", title="Tenancy Agreement TA-2024-00451", pages=SCAN_PAGES))
    llm.script_turns(SCAN_NODE, SCAN_PROMPT, reply, reply)  # two replies: one per time the scan is read
    first = uploaded(uploads_api, SCAN.name, SCAN.read_bytes())
    copy = uploaded(uploads_api, "copy.pdf", SCAN.read_bytes())

    uploads_api.client.delete(f"/uploads/{first['upload_id']}", headers=USER)
    assert uploads_api.client.get(f"/documents/{copy['upload_id']}", headers=USER).json()["blocks"]  # still shared
    assert scan_calls(llm) == 1
    uploads_api.client.delete(f"/uploads/{copy['upload_id']}", headers=USER)  # the last one: its transcript goes too
    uploaded(uploads_api, SCAN.name, SCAN.read_bytes())

    assert scan_calls(llm) == 2


def test_deleting_a_conversation_keeps_its_uploads(uploads_api: Api, llm: ScriptedLLMClient) -> None:
    item = uploaded(uploads_api, "site-visit.txt", NOTE.encode())
    thread = asked_with(uploads_api, llm, [item["upload_id"]])

    assert uploads_api.client.delete(f"/threads/{thread}", headers=USER).status_code == 204

    assert entry(uploads_api, item["upload_id"])["conversations"] == []
    assert uploads_api.client.get(f"/documents/{item['upload_id']}", headers=USER).status_code == 200
