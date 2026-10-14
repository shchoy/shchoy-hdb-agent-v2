"""Hybrid search with metadata pre-filters and the local cross-encoder rerank, over the synced poc-data corpus.

Questions and expected sources come from `_report.md` section 5. The cross-encoder is real (downloaded once into
the model cache); query embeddings come from the offline hashing embedder the index was built with.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from plg.search.lance import LanceSearchStore
from plg.search.models import SearchFilter, SearchHit
from plg.search.rerank import Searcher

LOD_QUESTION = "When does PLG issue a Letter of Demand for rental arrears?"
POL_003_V1 = "docs/PLG-POL-003_Rental_Arrears_Management_Policy_v1.0.docx"
POL_003_V2 = "docs/PLG-POL-003_Rental_Arrears_Management_Policy_v2.0.docx"


def search(searcher: Searcher, query: str, k: int = 5, **filters: Any) -> list[SearchHit]:
    return searcher.search(query, filters=SearchFilter(**filters), k=k)


def test_lod_question_finds_the_current_policy_clause_and_never_the_superseded_one(searcher: Searcher) -> None:
    hits = search(searcher, LOD_QUESTION, status="current")

    sources = [(h.chunk.source_path, h.chunk.location) for h in hits]
    assert (POL_003_V2, "4. Policy Statements > 4.5 Letter of Demand") in sources[:3]
    assert all(h.chunk.source_path != POL_003_V1 for h in hits)


def test_a_past_date_finds_the_policy_version_in_force_then(searcher: Searcher) -> None:
    hits = search(searcher, LOD_QUESTION, policy_id="PLG-POL-003", in_force_on=date(2025, 6, 1))

    assert hits
    assert {h.chunk.source_path for h in hits} == {POL_003_V1}
    assert "Letter of Demand" in hits[0].chunk.location


def test_display_area_question_finds_the_nc_circular(searcher: Searcher) -> None:
    hits = search(searcher, "What is PLG's current stance on displaying goods outside the shopfront?")

    assert "pdfs/PLG_Circular_07-2026_NC_Display_Area_Pilot.pdf" in [h.chunk.source_path for h in hits[:3]]


def test_records_question_finds_the_audit_finding(searcher: Searcher) -> None:
    hits = search(searcher, "What did internal audit find about rent master data?")

    top = hits[0].chunk
    assert top.source_path == "pdfs/Internal_Audit_Report_IA-2026-07_Tenancy_Management.pdf"
    assert "IA-02" in top.fts_text


def test_entity_filter_narrows_to_documents_about_that_tenancy(searcher: Searcher) -> None:
    hits = search(searcher, "rent outstanding letter of demand", k=10, entity_ids=["TA-2024-00542"])

    assert hits
    assert all("TA-2024-00542" in h.chunk.entity_ids for h in hits)
    assert "pdfs/LOD_TA-2024-00542_Golden_Leaf_Minimart.pdf" in {h.chunk.source_path for h in hits}


def test_rerank_orders_hits_by_cross_encoder_score(searcher: Searcher) -> None:
    hits = search(searcher, LOD_QUESTION, k=8)

    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert len(hits) == 8
