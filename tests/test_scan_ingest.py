"""Scanned PDFs: image-only files are read by Claude (PDF input) during `plg sync`, then searched and cited by page.

The reader is the scripted LLMClient; extraction, chunking, LanceDB and the source viewer API are real.
"""

from __future__ import annotations

import base64
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from plg.ingest.scans import SCAN_PROMPT
from plg.llm import ScriptedLLMClient
from plg.search.lance import LanceSearchStore
from tests.conftest import (
    CORPUS, HENG_ANN_SCAN, USER, Api, CountingEmbedder, by_path, open_store, run_sync, scan_llm,
)

LISTING = '{"items": [{"itemId": "PDF-011", "library": "Reports & Circulars", "title": null, "corpusPath": "%s"}]}'


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    (root / "exports").mkdir(parents=True)
    (root / "pdfs").mkdir()
    shutil.copy(CORPUS / HENG_ANN_SCAN, root / HENG_ANN_SCAN)
    (root / "exports/sharepoint_document_listing.json").write_text(LISTING % HENG_ANN_SCAN)
    return root


@pytest.fixture
def index(tmp_path: Path) -> Path:
    return tmp_path / "index"


def test_scan_is_indexed_with_text_and_page_locations(corpus: Path, index: Path) -> None:
    embedder = CountingEmbedder()

    result = run_sync(embedder, index, corpus)

    store = open_store(index, embedder)
    doc = by_path(store)[HENG_ANN_SCAN]
    chunks = store.chunks(doc.doc_id)
    assert "Added 1" in result.output
    assert "Skipped" not in result.output
    assert doc.title == "Tenancy Agreement TA-2024-00451 (Heng Ann Confectionery)"
    rent = next(c for c in chunks if "S$4,580" in c.text)
    assert "(p. 2)" in rent.location
    assert {c.location for c in chunks} == {"Page 1 (p. 1)", "Page 2 (p. 2)", "Page 3 (p. 3)"}
    assert all("TA-2024-00451" in c.entity_ids for c in chunks if "TA-2024-00451" in c.text)
    assert any("TA-2024-00451" in c.entity_ids for c in chunks)


def test_scan_is_sent_to_claude_as_pdf_input_for_identification(corpus: Path, index: Path) -> None:
    llm = scan_llm()

    run_sync(CountingEmbedder(), index, corpus, llm=llm)

    [messages] = llm.sent
    blocks = messages[-1]["content"]
    document = next(b for b in blocks if b["type"] == "document")
    assert document["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(document["source"]["data"]) == (corpus / HENG_ANN_SCAN).read_bytes()
    assert {"type": "text", "text": SCAN_PROMPT} in blocks


def test_resync_does_not_reprocess_an_unchanged_scan(corpus: Path, index: Path) -> None:
    embedder = CountingEmbedder()
    run_sync(embedder, index, corpus)
    embedder.embedded.clear()
    llm = ScriptedLLMClient()  # no scripted turns: any call raises

    result = run_sync(embedder, index, corpus, llm=llm)

    assert llm.sent == []
    assert embedder.embedded == []
    assert "unchanged 1" in result.output


def test_full_resync_reuses_the_saved_transcript(corpus: Path, index: Path) -> None:
    run_sync(CountingEmbedder(), index, corpus)
    llm = ScriptedLLMClient()

    run_sync(CountingEmbedder(), index, corpus, "--full", llm=llm)

    assert llm.sent == []


def test_unreadable_scan_is_skipped_with_a_reason(corpus: Path, index: Path) -> None:
    embedder = CountingEmbedder()
    llm = ScriptedLLMClient()  # the reader fails

    result = run_sync(embedder, index, corpus, llm=llm)

    assert HENG_ANN_SCAN not in by_path(open_store(index, embedder))
    assert f"Skipped: {HENG_ANN_SCAN} (scan could not be read" in result.output


@pytest.fixture
def scan_api(make_api: Callable[..., Api], corpus: Path, index: Path) -> tuple[Api, LanceSearchStore]:
    embedder = CountingEmbedder()
    run_sync(embedder, index, corpus)
    store = open_store(index, embedder)
    return make_api(store=store, corpus_dir=corpus, search_db=index), store


def test_scan_opens_in_the_source_viewer_with_the_cited_span_highlighted(
    scan_api: tuple[Api, LanceSearchStore],
) -> None:
    api, store = scan_api
    doc = by_path(store)[HENG_ANN_SCAN].doc_id
    chunk = next(c for c in store.chunks(doc) if "S$4,580" in c.text)
    start = chunk.text.index("The monthly rent")
    end = start + len("The monthly rent is S$4,580")

    view = api.client.get(f"/documents/{doc}", headers=USER).json()
    located = api.client.get(
        f"/documents/{doc}/chunks/{chunk.chunk_id.replace('#', '%23')}", params={"start": start, "end": end}, headers=USER
    ).json()

    assert view["kind"] == "pdf"
    assert {b["page"] for b in view["blocks"]} == {1, 2, 3}
    assert located["page"] == 2
    [h] = located["highlights"]
    assert view["blocks"][h["block"]]["text"][h["start"]:h["end"]] == "The monthly rent is S$4,580"
