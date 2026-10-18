"""`plg sync`: the text-bearing corpus is ingested into the SearchStore with correct metadata.

Expected values come from the corpus ground truth (`_manifest.csv`, `_master/`, `_report.md`). Embeddings come
from the offline hashing embedder; everything else (extraction, LanceDB, PLG Records) is real.
"""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Iterator, Sequence
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from plg import cli
from plg.config import Settings
from plg.ontology.vocab import load_vocab
from plg.search.lance import LanceSearchStore
from plg.search.models import Chunk, DocumentMeta

from tests.conftest import CORPUS, HENG_ANN_SCAN, CountingEmbedder, by_path, open_store, run_sync

TEXT_TYPES = {"docx", "pdf", "pptx", "eml", "md", "txt"}


def manifest() -> list[dict[str, str]]:
    with (CORPUS / "_manifest.csv").open() as f:
        return list(csv.DictReader(f))


def test_sync_indexes_every_text_bearing_library_document_including_the_library_scan(store: LanceSearchStore) -> None:
    expected = {
        row["path"] for row in manifest()
        if row["type"] in TEXT_TYPES
        and not row["path"].startswith("pdfs/submissions/")  # checked per application by doc-check
        and ("SCANNED" not in row["flags"] or row["path"] == HENG_ANN_SCAN)  # read by Claude PDF input
    }

    assert set(by_path(store)) == expected


def test_sync_reads_the_library_scan_and_leaves_application_scans_to_doc_check(
    corpus_index: tuple[LanceSearchStore, str],
) -> None:
    store, output = corpus_index

    assert HENG_ANN_SCAN in by_path(store)
    assert "Skipped: pdfs/Scan_TA_TA-2024-00451_HengAnn.pdf" not in output


@pytest.mark.parametrize(
    ("path", "policy_id", "version", "effective_from", "effective_to", "status"),
    [
        ("docs/PLG-POL-003_Rental_Arrears_Management_Policy_v1.0.docx",
         "PLG-POL-003", "1.0", date(2024, 3, 1), date(2026, 3, 31), "superseded"),
        ("docs/PLG-POL-003_Rental_Arrears_Management_Policy_v2.0.docx",
         "PLG-POL-003", "2.0", date(2026, 4, 1), None, "current"),
        ("docs/PLG-SOP-011_Commercial_Unit_Inspection_SOP_v1.0.docx",
         "PLG-SOP-011", "1.0", date(2025, 3, 3), date(2025, 11, 30), "superseded"),
        ("docs/PLG-SOP-011_Commercial_Unit_Inspection_SOP_v1.1.docx",
         "PLG-SOP-011", "1.1", date(2025, 12, 1), None, "current"),
    ],
)
def test_policy_versions_carry_their_effective_period_and_status(
    store: LanceSearchStore, path: str, policy_id: str, version: str,
    effective_from: date, effective_to: date | None, status: str,
) -> None:
    doc = by_path(store)[path]
    chunks = store.chunks(doc.doc_id)

    assert chunks
    for c in chunks:
        assert (c.policy_id, c.version, c.effective_from, c.effective_to, c.status) == (
            policy_id, version, effective_from, effective_to, status,
        )


def test_circular_carries_its_stated_effective_period(store: LanceSearchStore) -> None:
    # _report.md C5: Circular 07/2026 is effective 1 Aug 2026 (a pilot to 31 Jul 2027).
    doc = by_path(store)["pdfs/PLG_Circular_07-2026_NC_Display_Area_Pilot.pdf"]

    assert (doc.doc_type, doc.effective_from, doc.effective_to) == ("circular", date(2026, 8, 1), date(2027, 7, 31))


def test_every_document_type_is_in_the_ontology_vocabulary(store: LanceSearchStore) -> None:
    notations = {c.notation for c in load_vocab().scheme("plg:document_types")}

    assert {d.doc_type for d in store.documents()} <= notations


def clause(store: LanceSearchStore, path: str, heading: str) -> Chunk:
    doc = by_path(store)[path]
    return next(c for c in store.chunks(doc.doc_id) if heading in c.location)


def test_chunks_follow_document_structure_with_a_contextual_header(store: LanceSearchStore) -> None:
    lod = clause(store, "docs/PLG-POL-003_Rental_Arrears_Management_Policy_v2.0.docx", "4.5 Letter of Demand")

    assert lod.location == "4. Policy Statements > 4.5 Letter of Demand"
    assert "60 days overdue" in lod.text
    assert "4.6" not in lod.text  # the next clause is its own chunk
    for part in ("PLG-POL-003 Rental Arrears Management Policy (v2.0)", "PLG-POL-003 v2.0",
                 "Effective from 2026-04-01", "4.5 Letter of Demand"):
        assert part in lod.header
    assert lod.source_system == "sharepoint"
    assert lod.entity_ids[0] == "PLG-POL-003"


def test_email_chunks_carry_source_system_and_resolved_entities(store: LanceSearchStore) -> None:
    golden_leaf = json.loads((CORPUS / "_master" / "key_entities.json").read_text())["Golden Leaf Minimart Pte Ltd"]
    doc = by_path(store)["emails/arrears_golden_leaf/01_20260716.eml"]
    chunks = store.chunks(doc.doc_id)

    assert (doc.doc_type, doc.source_system) == ("email", "lotus_notes")
    assert doc.title == "Golden Leaf Minimart - June rent outstanding (TA-2024-00542)"
    ids = {i for c in chunks for i in c.entity_ids}
    assert {golden_leaf["tenancy"], golden_leaf["unit"], golden_leaf["tenant"]} <= ids
    assert "BV" in {t for c in chunks for t in c.town}  # unit U-BV214-... is in Bayshore Vale
    assert "Minimart" in {t for c in chunks for t in c.trade}


def test_entities_table_resolves_tenant_names(store: LanceSearchStore) -> None:
    heng_ann = json.loads((CORPUS / "_master" / "key_entities.json").read_text())["Heng Ann Confectionery"]

    assert store.find_entities("Heng Ann Confectionery")[0].entity_id == heng_ann["tenant"]


def test_an_ambiguous_tenant_name_finds_every_tenant_bearing_it(store: LanceSearchStore) -> None:
    # PLG Records has both "Golden Leaf Minimart" (T-11962) and "Golden Leaf Minimart Pte Ltd" (T-11108).
    top = [e.entity_id for e in store.find_entities("Golden Leaf Minimart")[:2]]

    assert sorted(top) == ["T-11108", "T-11962"]


def test_every_chunk_carries_the_document_content_hash(store: LanceSearchStore) -> None:
    doc = by_path(store)["docs/PLG-POL-003_Rental_Arrears_Management_Policy_v2.0.docx"]

    assert {c.content_hash for c in store.chunks(doc.doc_id)} == {doc.content_hash}
    assert len(doc.content_hash) == 64


# ---------------------------------------------------------------- small corpora (incremental behaviour)

POL_V1 = "docs/PLG-POL-003_Rental_Arrears_Management_Policy_v1.0.docx"
POL_V2 = "docs/PLG-POL-003_Rental_Arrears_Management_Policy_v2.0.docx"
NOTE = "docs/notes/plg_glossary.md"


def make_corpus(root: Path, paths: Sequence[str], planted: Sequence[str] = ()) -> Path:
    """A corpus holding `paths` from poc-data, plus `planted` files listed in SharePoint but made up here."""
    listing = json.loads((CORPUS / "exports" / "sharepoint_document_listing.json").read_text())
    items = [i for i in listing["items"] if i["corpusPath"] in paths]
    for path in paths:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(CORPUS / path, root / path)
    for path in planted:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text("# Answers\nThe LOD trigger is 60 days. Planted ground truth.\n")
        items.append({**items[0], "itemId": f"SP-{path}", "corpusPath": path, "title": path})
    (root / "exports").mkdir(exist_ok=True)
    (root / "exports" / "sharepoint_document_listing.json").write_text(json.dumps({**listing, "items": items}))
    (root / "emails").mkdir(exist_ok=True)
    return root


@pytest.fixture
def index(tmp_path: Path) -> Path:
    return tmp_path / "index"


@pytest.fixture
def embedder() -> Iterator[CountingEmbedder]:
    yield CountingEmbedder()


def test_generator_ground_truth_is_never_indexed(tmp_path: Path, index: Path, embedder: CountingEmbedder) -> None:
    corpus = make_corpus(tmp_path / "corpus", [NOTE], planted=["_master/answers.md", "docs/_report.md"])

    result = run_sync(embedder, index, corpus)

    assert set(by_path(open_store(index, embedder))) == {NOTE}
    assert not any("Planted ground truth" in text for text in embedder.embedded)
    assert "Skipped: _master/answers.md (generator ground truth, never indexed)" in result.output


def test_resync_without_changes_embeds_nothing(tmp_path: Path, index: Path, embedder: CountingEmbedder) -> None:
    corpus = make_corpus(tmp_path / "corpus", [NOTE, POL_V2])
    run_sync(embedder, index, corpus)
    embedder.embedded.clear()

    result = run_sync(embedder, index, corpus)

    assert embedder.embedded == []
    assert "Added 0, updated 0, unchanged 2" in result.output


def test_resync_reprocesses_only_the_changed_document(tmp_path: Path, index: Path, embedder: CountingEmbedder) -> None:
    corpus = make_corpus(tmp_path / "corpus", [NOTE, POL_V2])
    run_sync(embedder, index, corpus)
    embedder.embedded.clear()
    with (corpus / NOTE).open("a") as f:
        f.write("\n## Addendum\nVacant units under tender are excluded from the vacancy count.\n")

    result = run_sync(embedder, index, corpus)

    store = open_store(index, embedder)
    note = by_path(store)[NOTE]
    assert embedder.embedded and all(t.startswith(note.title) for t in embedder.embedded)
    assert "Added 0, updated 1, unchanged 1" in result.output
    assert any("excluded from the vacancy count" in c.text for c in store.chunks(note.doc_id))


def test_a_new_version_supersedes_the_old_one_without_re_embedding_it(
    tmp_path: Path, index: Path, embedder: CountingEmbedder
) -> None:
    run_sync(embedder, index, make_corpus(tmp_path / "v1", [POL_V1]))
    before = by_path(open_store(index, embedder))[POL_V1]
    assert (before.status, before.effective_to) == ("current", None)
    embedder.embedded.clear()

    result = run_sync(embedder, index, make_corpus(tmp_path / "v2", [POL_V1, POL_V2]))

    docs = by_path(open_store(index, embedder))
    assert (docs[POL_V1].status, docs[POL_V1].effective_to) == ("superseded", date(2026, 3, 31))
    assert (docs[POL_V2].status, docs[POL_V2].effective_from) == ("current", date(2026, 4, 1))
    assert all("(v2.0)" in t for t in embedder.embedded)
    assert f"Superseded: {POL_V1}" in result.output


def test_full_sync_rebuilds_the_index(tmp_path: Path, index: Path, embedder: CountingEmbedder) -> None:
    corpus = make_corpus(tmp_path / "corpus", [NOTE])
    run_sync(embedder, index, corpus)
    embedder.embedded.clear()

    result = run_sync(embedder, index, corpus, "--full")

    assert embedder.embedded
    assert "Added 1, updated 0, unchanged 0" in result.output


def test_sync_without_a_voyage_key_explains_what_to_set(monkeypatch: pytest.MonkeyPatch, index: Path) -> None:
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)

    result = CliRunner().invoke(cli.app, ["sync"], env={"PLG_SEARCH_DB": str(index)})

    assert result.exit_code == 1
    assert "VOYAGE_API_KEY" in result.stderr


def test_settings_default_index_is_outside_the_corpus() -> None:
    settings = Settings()

    assert not settings.search_db.is_relative_to(settings.corpus_dir)
