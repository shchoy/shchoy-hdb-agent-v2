"""Document search (#108): GET /search?q= also finds Library documents and the officer's own uploads by keyword
(LanceDB full-text, word prefixes as the officer types; no Claude or Voyage call). Each hit names the document once, at
its best-matching chunk, with a snippet whose matched words are marked and the span of the match in that chunk's text,
so the source viewer can open there with it highlighted. Current documents come before superseded ones."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

from plg.llm import ScriptedLLMClient
from plg.search.embed import HashingEmbedder
from plg.search.lance import LanceSearchStore
from plg.search.models import Chunk
from tests.conftest import USER, Api
from tests.test_rename_delete_api import OTHER
from tests.test_uploads_api import uploaded

NOTE = (
    "Site visit to the kiosk at unit 01-17.\n\n"
    "The roller shutter is jammed half-way and the tenant stacks crates along the walkway.\n"
)


def found(api: Api, q: str, headers: dict[str, str] = USER) -> dict[str, list[dict[str, Any]]]:
    response = api.client.get("/search", params={"q": q}, headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


def marked(hit: dict[str, Any]) -> list[str]:
    return [part["text"] for part in hit["snippet"] if part["match"]]


def titles(hits: list[dict[str, Any]]) -> list[str]:
    return [h["title"] for h in hits]


@pytest.fixture
def docs_api(make_api: Callable[..., Api], store: LanceSearchStore) -> Api:
    return make_api(store=store)


def test_library_documents_match_on_content_current_versions_first(docs_api: Api) -> None:
    hits = found(docs_api, "structurally unsaf")["documents"]

    inspection = [h for h in hits if h["title"].startswith("PLG-SOP-011")]
    assert [(h["version"], h["status"]) for h in inspection] == [("1.1", "current"), ("1.0", "superseded")]
    current = inspection[0]
    assert current["matched"] == "content" and current["upload"] is False
    assert [w.lower() for w in marked(current)] == ["structurally", "unsafe"]
    assert all(h["status"] == "current" for h in hits[: hits.index(inspection[1])])  # superseded ones come last


def test_library_documents_match_on_title(docs_api: Api) -> None:
    hits = found(docs_api, "rental arrears manag")["documents"]

    policy = [h for h in hits if h["title"].startswith("PLG-POL-003")]
    assert [(h["version"], h["status"]) for h in policy] == [("2.0", "current"), ("1.0", "superseded")]
    assert {w.lower() for w in marked(policy[0])} <= {"rental", "arrears", "management"}
    # A title naming every word ranks the document above ones that only mention them.
    assert hits[0] == policy[0]


def test_every_word_must_match(docs_api: Api) -> None:
    hits = found(docs_api, "rimba tablet")["documents"]  # of the SOP, only v1.1 records Rimba inspections on a tablet

    assert [h["version"] for h in hits if h["title"].startswith("PLG-SOP-011")] == ["1.1"]
    assert found(docs_api, "rimba zzzqqq")["documents"] == []


def test_the_match_is_located_in_its_chunk_for_the_source_viewer(docs_api: Api) -> None:
    hit = found(docs_api, "structurally unsafe")["documents"][0]

    chunk = docs_api.client.get(
        f"/documents/{hit['doc_id']}/chunks/{quote(hit['chunk_id'], safe='')}",
        params={"start": hit["span"]["start"], "end": hit["span"]["end"]}, headers=USER,
    ).json()
    assert chunk["quote"].lower() == "structurally unsafe"
    document = docs_api.client.get(f"/documents/{hit['doc_id']}", headers=USER).json()
    [highlight] = chunk["highlights"]
    shown = document["blocks"][highlight["block"]]["text"][highlight["start"]:highlight["end"]]
    assert shown.lower() == "structurally unsafe"


def test_uploads_are_found_only_by_their_owner(docs_api: Api) -> None:
    item = uploaded(docs_api, "kiosk-visit.txt", NOTE.encode())

    results = found(docs_api, "roller shutt")
    [hit] = results["uploads"]
    assert hit["doc_id"] == item["upload_id"] and hit["upload"] is True and hit["matched"] == "content"
    assert [w.lower() for w in marked(hit)] == ["roller", "shutter"]
    assert item["upload_id"] not in str(results["documents"])
    assert found(docs_api, "roller shutt", headers=OTHER)["uploads"] == []

    chunk = docs_api.client.get(
        f"/documents/{hit['doc_id']}/chunks/{quote(hit['chunk_id'], safe='')}",
        params={"start": hit["span"]["start"], "end": hit["span"]["end"]}, headers=USER,
    ).json()
    assert chunk["quote"].lower() == "roller shutter"


def test_a_renamed_upload_is_found_by_its_new_title_and_a_deleted_one_not_at_all(docs_api: Api) -> None:
    item = uploaded(docs_api, "kiosk-visit.txt", NOTE.encode())
    upload_id = item["upload_id"]
    assert docs_api.client.patch(f"/uploads/{upload_id}", json={"title": "Bedok kiosk notes"}, headers=USER).is_success

    [hit] = found(docs_api, "bedok notes")["uploads"]  # words only its new title holds
    assert hit["title"] == "Bedok kiosk notes" and hit["matched"] == "title"

    assert docs_api.client.delete(f"/uploads/{upload_id}", headers=USER).status_code == 204
    assert found(docs_api, "shutter")["uploads"] == []


def test_no_model_is_called_and_odd_queries_are_plain_words(docs_api: Api, llm: ScriptedLLMClient) -> None:
    for q in ["", "  ", "-", "inspection OR", '"unsafe', "NEAR(a b)", "*", "a"]:
        results = found(docs_api, q)
        assert set(results) == {"conversations", "documents", "uploads", "approvals", "decisions", "memories"}, q
    assert found(docs_api, "")["documents"] == []
    assert llm.sent == []


def test_an_index_synced_before_keyword_search_is_searched_after_the_next_sync(
    make_api: Callable[..., Api], tmp_path: Path
) -> None:
    """plg-api never writes the shared Library index: an index without the keyword indexes finds no documents until
    `plg sync` (its optimize step) builds them."""
    store = LanceSearchStore(tmp_path / "index", dim=8)
    vector = HashingEmbedder(dim=8).embed_documents(["x"])[0]
    store.replace_document("SP-1", [Chunk(
        doc_id="SP-1", doc_type="sop", title="Kiosk Guide", source_system="sharepoint", source_path="a.docx",
        content_hash="h", chunk_id="SP-1#000", seq=0, header="Kiosk Guide", location="1",
        text="Shutters must be kept clear of crates.", vector=vector,
    )])
    api = make_api(store=store)
    assert found(api, "shutter")["documents"] == []

    store.optimize()

    [hit] = found(api, "shutter")["documents"]
    assert hit["doc_id"] == "SP-1" and marked(hit) == ["Shutters"]
    assert (hit["span"]["start"], hit["span"]["end"]) == (0, len("Shutters"))
