"""Source viewer API: the source document and where a cited span sits in it."""

from __future__ import annotations

from typing import Any

import pytest

from plg.search.embed import HashingEmbedder
from plg.search.lance import LanceSearchStore
from plg.search.models import Chunk
from tests.conftest import USER, Api, by_path

POLICY_DOCX = "docs/PLG-POL-003_Rental_Arrears_Management_Policy_v2.0.docx"
GUIDELINES_PDF = "pdfs/Guidelines_AA_Works_Commercial_Tenants_2025.pdf"
EMAIL = "emails/prima_deposit/01_20260723.eml"
MARKDOWN = "docs/notes/onboarding_guide_new_officers.md"


def doc_id(store: LanceSearchStore, path: str) -> str:
    return by_path(store)[path].doc_id


def get(api: Api, url: str, **params: object) -> Any:
    return api.client.get(url, params=params, headers=USER)


def a_sentence(store: LanceSearchStore, doc: str, containing: str = "") -> tuple[str, str, int, int]:
    """(chunk_id, quote, start, end) of a line of the document's chunks, as a citation would give it."""
    for chunk in store.chunks(doc):
        start = chunk.text.find(containing) if containing else 0
        if start >= 0:
            end = chunk.text.find("\n", start)
            end = len(chunk.text) if end < 0 else end
            return chunk.chunk_id, chunk.text[start:end], start, end
    raise AssertionError(f"no chunk of {doc} contains {containing!r}")


@pytest.mark.parametrize(
    ("path", "kind", "content_type"),
    [
        (POLICY_DOCX, "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        (GUIDELINES_PDF, "pdf", "application/pdf"),
        (EMAIL, "email", "message/rfc822"),
        (MARKDOWN, "markdown", "text/markdown"),
    ],
)
def test_document_returns_its_text_blocks_and_file_details(
    documents_api: Api, store: LanceSearchStore, path: str, kind: str, content_type: str
) -> None:
    doc = doc_id(store, path)

    body = get(documents_api, f"/documents/{doc}").json()

    assert body["doc_id"] == doc
    assert body["kind"] == kind
    assert body["content_type"] == content_type
    assert body["filename"] == path.rsplit("/", 1)[1]
    assert body["title"]
    assert len(body["blocks"]) > 3
    assert all(b["text"] for b in body["blocks"])


def test_pdf_blocks_carry_their_page(documents_api: Api, store: LanceSearchStore) -> None:
    blocks = get(documents_api, f"/documents/{doc_id(store, GUIDELINES_PDF)}").json()["blocks"]

    assert {b["page"] for b in blocks} >= {1, 2}


def test_document_file_is_the_source_file(documents_api: Api, store: LanceSearchStore) -> None:
    response = get(documents_api, f"/documents/{doc_id(store, GUIDELINES_PDF)}/file")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_only_pdfs_are_displayed_inline(documents_api: Api, store: LanceSearchStore) -> None:
    pdf = get(documents_api, f"/documents/{doc_id(store, GUIDELINES_PDF)}/file")
    eml = get(documents_api, f"/documents/{doc_id(store, EMAIL)}/file")

    assert pdf.headers["content-disposition"].startswith("inline")
    assert eml.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in eml.headers["content-security-policy"]


@pytest.mark.parametrize("path", [POLICY_DOCX, GUIDELINES_PDF, EMAIL, MARKDOWN])
def test_chunk_locates_the_cited_span_in_the_documents_blocks(
    documents_api: Api, store: LanceSearchStore, path: str
) -> None:
    doc = doc_id(store, path)
    chunk_id, quote, start, end = a_sentence(store, doc)

    document = get(documents_api, f"/documents/{doc}").json()
    located = get(documents_api, f"/documents/{doc}/chunks/{chunk_id.replace('#', '%23')}", start=start, end=end).json()

    assert located["chunk_id"] == chunk_id
    assert located["quote"] == quote
    assert located["highlights"], "the quote is found in the document"
    highlighted = "".join(
        document["blocks"][h["block"]]["text"][h["start"] : h["end"]] for h in located["highlights"]
    )
    assert highlighted.split() == quote.split()


def test_pdf_chunk_names_the_page_of_the_span(documents_api: Api, store: LanceSearchStore) -> None:
    doc = doc_id(store, GUIDELINES_PDF)
    last = store.chunks(doc)[-1]

    located = get(documents_api, f"/documents/{doc}/chunks/{last.chunk_id.replace('#', '%23')}").json()

    blocks = get(documents_api, f"/documents/{doc}").json()["blocks"]
    assert located["page"] == blocks[located["highlights"][0]["block"]]["page"]
    assert located["page"] > 1


def test_span_may_cross_blocks(documents_api: Api, store: LanceSearchStore) -> None:
    doc = doc_id(store, POLICY_DOCX)
    chunk = next(c for c in store.chunks(doc) if "\n" in c.text)

    located = get(
        documents_api, f"/documents/{doc}/chunks/{chunk.chunk_id.replace('#', '%23')}",
        start=0, end=len(chunk.text),
    ).json()

    assert len({h["block"] for h in located["highlights"]}) > 1


def test_without_a_span_the_whole_chunk_is_highlighted(documents_api: Api, store: LanceSearchStore) -> None:
    doc = doc_id(store, POLICY_DOCX)
    chunk = store.chunks(doc)[0]

    located = get(documents_api, f"/documents/{doc}/chunks/{chunk.chunk_id.replace('#', '%23')}").json()

    assert located["quote"] == chunk.text


def test_raw_html_in_a_document_is_returned_as_plain_text(tmp_path: Any, make_api: Any) -> None:
    """The API never interprets markup: a script in an email body is just characters in a block."""
    corpus = tmp_path / "corpus"
    (corpus / "emails").mkdir(parents=True)
    (corpus / "emails" / "x.eml").write_text(
        "From: a@x.sg\nTo: b@x.sg\nSubject: Hello\nDate: Mon, 1 Jun 2026 09:00:00 +0800\n"
        "Message-ID: <x@x>\nContent-Type: text/html\n\n<p>Hi</p><script>alert(1)</script>\n"
    )
    embedder = HashingEmbedder(dim=128)
    index = LanceSearchStore(tmp_path / "idx", dim=128)
    index.replace_document("LN-x", [Chunk(
        chunk_id="LN-x#000", doc_id="LN-x", seq=0, doc_type="email", title="Hello", source_system="lotus_notes",
        source_path="emails/x.eml", content_hash="h", header="Hello", text="x", location="(body)",
        vector=embedder.embed_query("x"),
    )])
    api = make_api(store=index, corpus_dir=corpus)

    blocks = get(api, "/documents/LN-x").json()["blocks"]

    assert any("<script>alert(1)</script>" in b["text"] for b in blocks)


def test_unknown_document_or_chunk_is_404(documents_api: Api, store: LanceSearchStore) -> None:
    doc = doc_id(store, POLICY_DOCX)
    other = store.chunks(doc_id(store, EMAIL))[0].chunk_id.replace("#", "%23")

    assert get(documents_api, "/documents/NOPE").status_code == 404
    assert get(documents_api, "/documents/NOPE/file").status_code == 404
    assert get(documents_api, f"/documents/{doc}/chunks/{doc}%23999").status_code == 404
    assert get(documents_api, f"/documents/{doc}/chunks/{other}").status_code == 404, "chunk of another document"


def test_source_path_cannot_escape_the_corpus(tmp_path: Any, make_api: Any) -> None:
    secret = tmp_path / "secret.md"
    secret.write_text("# secret\nhidden\n")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    index = LanceSearchStore(tmp_path / "idx", dim=128)
    index.replace_document("D", [Chunk(
        chunk_id="D#000", doc_id="D", seq=0, doc_type="x", title="t", source_system="sharepoint",
        source_path="../secret.md", content_hash="h", header="t", text="x", location="(body)",
        vector=HashingEmbedder(dim=128).embed_query("x"),
    )])
    api = make_api(store=index, corpus_dir=corpus)

    assert get(api, "/documents/D").status_code == 404
    assert get(api, "/documents/D/file").status_code == 404


def test_documents_need_a_signed_in_user(documents_api: Api, store: LanceSearchStore) -> None:
    doc = doc_id(store, POLICY_DOCX)
    chunk = store.chunks(doc)[0].chunk_id.replace("#", "%23")

    for url in (f"/documents/{doc}", f"/documents/{doc}/file", f"/documents/{doc}/chunks/{chunk}"):
        assert documents_api.client.get(url).status_code == 401
