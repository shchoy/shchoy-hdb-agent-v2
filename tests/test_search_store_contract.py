"""`SearchStore` contract. Every backend (LanceDB now, OpenSearch at migration) must pass this suite."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from plg.search.embed import HashingEmbedder
from plg.search.lance import LanceSearchStore
from plg.search.models import Chunk, EntityRecord, MemoryItem, SearchFilter
from plg.search.store import SearchStore

EMBED = HashingEmbedder(dim=64)

STORES: dict[str, Callable[[Path], SearchStore]] = {
    "lancedb": lambda path: LanceSearchStore(path, dim=EMBED.dim),
}


@pytest.fixture(params=sorted(STORES))
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[SearchStore]:
    yield STORES[request.param](tmp_path / "index")


def chunk(doc_id: str, seq: int, text: str, **meta: Any) -> Chunk:
    fields: dict[str, Any] = {
        "doc_type": "policy", "title": f"Doc {doc_id}", "source_system": "sharepoint",
        "source_path": f"docs/{doc_id}.docx", "content_hash": f"hash-{doc_id}", "header": f"Doc {doc_id}",
        "location": f"section {seq}", **meta,
    }
    return Chunk(
        chunk_id=f"{doc_id}#{seq:03d}", doc_id=doc_id, seq=seq, text=text,
        vector=EMBED.embed_query(f"{fields['header']}\n{text}"), **fields,
    )


def search(store: SearchStore, query: str, limit: int = 10, **filters: Any) -> list[str]:
    hits = store.search(query, EMBED.embed_query(query), filters=SearchFilter(**filters), limit=limit)
    return [h.chunk.chunk_id for h in hits]


def test_replacing_a_document_swaps_its_chunks_and_leaves_others(store: SearchStore) -> None:
    store.replace_document("A", [chunk("A", 0, "old one"), chunk("A", 1, "old two")])
    store.replace_document("B", [chunk("B", 0, "other doc")])

    store.replace_document("A", [chunk("A", 0, "new text", content_hash="hash-A2")])

    assert [c.text for c in store.chunks("A")] == ["new text"]
    assert [c.text for c in store.chunks("B")] == ["other doc"]
    assert {d.doc_id: d.content_hash for d in store.documents()} == {"A": "hash-A2", "B": "hash-B"}


def test_chunks_round_trip_with_all_metadata(store: SearchStore) -> None:
    original = chunk(
        "POL", 0, "Letter of Demand at 60 days.", policy_id="PLG-POL-003", version="2.0",
        effective_from=date(2026, 4, 1), effective_to=None, status="current", category="arrears",
        town=["BV"], nc=["NC-BV-1"], trade=["Minimart"], entity_ids=["PLG-POL-003", "TA-2024-00542"],
    )
    store.replace_document("POL", [original])

    stored = store.get_chunk("POL#000")
    assert stored is not None
    assert stored.model_dump(exclude={"vector"}) == original.model_dump(exclude={"vector"})
    assert stored.vector == pytest.approx(original.vector, abs=1e-6)  # backends may store float32
    assert store.get_chunk("missing#000") is None


def test_removing_a_document(store: SearchStore) -> None:
    store.replace_document("A", [chunk("A", 0, "text")])
    store.replace_document("A", [])

    assert store.documents() == []
    assert store.chunks("A") == []


def test_lifecycle_update_marks_every_chunk_superseded(store: SearchStore) -> None:
    store.replace_document("V1", [chunk("V1", i, f"part {i}", effective_from=date(2024, 3, 1)) for i in range(3)])

    store.set_lifecycle("V1", status="superseded", effective_to=date(2026, 3, 31))

    assert {(c.status, c.effective_to) for c in store.chunks("V1")} == {("superseded", date(2026, 3, 31))}
    assert store.documents()[0].status == "superseded"


def test_hybrid_search_ranks_the_matching_chunk_first(store: SearchStore) -> None:
    store.replace_document("A", [
        chunk("A", 0, "Letter of Demand is issued when rent is 60 days overdue."),
        chunk("A", 1, "Display of goods beyond the shopfront is limited to 0.6 m."),
        chunk("A", 2, "Inspections are carried out every six months."),
    ])

    assert search(store, "letter of demand overdue rent")[0] == "A#000"
    assert search(store, "display goods shopfront")[0] == "A#001"


def test_search_respects_the_limit(store: SearchStore) -> None:
    store.replace_document("A", [chunk("A", i, f"rent arrears note {i}") for i in range(8)])

    assert len(search(store, "rent arrears", limit=3)) == 3


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"status": "current"}, {"NEW#000", "EML#000", "SOP#000"}),
        ({"status": "superseded"}, {"OLD#000"}),
        ({"doc_type": ["email"]}, {"EML#000"}),
        ({"doc_type": ["email", "sop"]}, {"EML#000", "SOP#000"}),
        ({"policy_id": "PLG-POL-003"}, {"OLD#000", "NEW#000"}),
        ({"source_system": "lotus_notes"}, {"EML#000"}),
        ({"category": "arrears"}, {"SOP#000"}),
        ({"town": ["BV"]}, {"EML#000"}),
        ({"nc": ["NC-PI-1", "NC-XX-9"]}, {"SOP#000"}),
        ({"trade": ["Minimart"]}, {"EML#000", "SOP#000"}),
        ({"entity_ids": ["TA-2024-00542"]}, {"EML#000"}),
        ({"doc_ids": ["OLD", "EML"]}, {"OLD#000", "EML#000"}),
        ({"in_force_on": date(2025, 1, 1)}, {"OLD#000", "EML#000", "SOP#000"}),
        ({"in_force_on": date(2026, 4, 1)}, {"NEW#000", "EML#000", "SOP#000"}),
        ({"policy_id": "PLG-POL-003", "in_force_on": date(2026, 3, 31)}, {"OLD#000"}),
    ],
)
def test_pre_filters(store: SearchStore, filters: dict[str, Any], expected: set[str]) -> None:
    store.replace_document("OLD", [chunk(
        "OLD", 0, "Letter of demand after 45 days of rent arrears.", policy_id="PLG-POL-003", version="1.0",
        effective_from=date(2024, 3, 1), effective_to=date(2026, 3, 31), status="superseded",
    )])
    store.replace_document("NEW", [chunk(
        "NEW", 0, "Letter of demand after 60 days of rent arrears.", policy_id="PLG-POL-003", version="2.0",
        effective_from=date(2026, 4, 1),
    )])
    store.replace_document("EML", [chunk(
        "EML", 0, "Golden Leaf rent arrears, letter of demand?", doc_type="email", source_system="lotus_notes",
        town=["BV"], trade=["Minimart"], entity_ids=["TA-2024-00542", "U-BV214-01-32"],
    )])
    store.replace_document("SOP", [chunk(
        "SOP", 0, "Arrears recovery steps: letter of demand at day 45.", doc_type="sop", category="arrears",
        nc=["NC-PI-1"], trade=["Minimart", "Bakery"],
    )])

    assert set(search(store, "letter of demand rent arrears", **filters)) == expected


def test_pre_filter_applies_before_the_limit(store: SearchStore) -> None:
    store.replace_document("A", [chunk("A", i, "letter of demand rent arrears overdue") for i in range(20)])
    store.replace_document("Z", [chunk("Z", 0, "unrelated text about kiosks", entity_ids=["T-10974"])])

    assert search(store, "letter of demand rent arrears", limit=5, entity_ids=["T-10974"]) == ["Z#000"]


def test_entities_are_found_by_any_name_variant(store: SearchStore) -> None:
    store.replace_entities([
        EntityRecord(entity_id="T-11108", entity_type="Tenant", name="Golden Leaf Minimart",
                     variants=["Golden Leaf Minimart", "Golden Leaf"]),
        EntityRecord(entity_id="NC-BV-1", entity_type="NeighbourhoodCentre", name="Bayshore Vale Central NC",
                     variants=["Bayshore Vale Central NC"]),
    ])

    assert [e.entity_id for e in store.find_entities("golden leaf")][:1] == ["T-11108"]
    assert [e.entity_id for e in store.find_entities("Bayshore Vale Central")][:1] == ["NC-BV-1"]


def test_replacing_entities_drops_the_old_set(store: SearchStore) -> None:
    store.replace_entities([EntityRecord(entity_id="X", entity_type="Tenant", name="Old Name", variants=[])])
    store.replace_entities([EntityRecord(entity_id="Y", entity_type="Tenant", name="New Name", variants=[])])

    assert [e.entity_id for e in store.find_entities("name")] == ["Y"]


NOW = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)


def memory(namespace: tuple[str, ...], key: str, text: str, **fields: Any) -> MemoryItem:
    values: dict[str, Any] = {
        "value": {"note": text}, "provenance": "test", "created_at": NOW, "updated_at": NOW, **fields,
    }
    return MemoryItem(namespace=namespace, key=key, text=text, vector=EMBED.embed_query(text), **values)


def test_memory_put_replaces_by_namespace_and_key(store: SearchStore) -> None:
    store.put_memory(memory(("user", "S05"), "pref", "prefers short answers"))
    store.put_memory(memory(("user", "S05"), "pref", "prefers tables", confidence=0.8))

    item = store.get_memory(("user", "S05"), "pref")
    assert item is not None and item.text == "prefers tables" and item.confidence == 0.8
    assert store.get_memory(("user", "S06"), "pref") is None


def test_memory_delete(store: SearchStore) -> None:
    store.put_memory(memory(("user", "S05"), "pref", "prefers short answers"))
    store.delete_memory(("user", "S05"), "pref")

    assert store.get_memory(("user", "S05"), "pref") is None


def test_memory_search_is_scoped_to_the_namespace_and_skips_inactive_or_expired(store: SearchStore) -> None:
    store.put_memory(memory(("user", "S05", "episodes"), "a", "golden leaf arrears follow up"))
    store.put_memory(memory(("user", "S05", "episodes"), "b", "golden leaf arrears retired", status="retired"))
    store.put_memory(memory(("user", "S05", "episodes"), "c", "golden leaf arrears expired",
                            expires_at=NOW - timedelta(days=1)))
    store.put_memory(memory(("user", "S050"), "d", "golden leaf arrears other user"))
    store.put_memory(memory(("user", "S06"), "e", "golden leaf arrears other user"))

    found = store.search_memory(("user", "S05"), EMBED.embed_query("golden leaf arrears"), now=NOW)

    assert [m.key for m in found] == ["a"]
