"""Policy lineage in the entity graph: Haiku-extracted SUPERSEDES / OVERRIDES / APPLIES edges with evidence,
written through `GraphWriter`, and the `policy_lineage` read. Expected facts come from `_master` (planned conflicts C1, C5)
and the policy documents; Haiku is scripted, and the validation of what it returns is real.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from plg.entities import cypher
from plg.entities.local import LocalGraphStore
from plg.entities.policy import PolicyLineage
from plg.entities.writer import GraphWriter
from plg.ingest.lineage import LineageReport, NODE, extract_lineage
from plg.llm import AgentTurn, ScriptedLLMClient, tool_call, turn
from plg.entities.spine import write_spine
from plg.search.lance import LanceSearchStore
from tests.conftest import CORPUS
from tests.test_entity_graph import RECORDS

Chunks = list[tuple[str, str]]
"""(chunk id, text) pairs of the batch Haiku was shown."""

Edges = Callable[[Chunks], list[dict[str, Any]]]


def edge(kind: str, source: tuple[str, str], target: tuple[str, str], chunk: str, quote: str, **extra: str) -> dict[str, Any]:
    return {
        "type": kind, "source_id": source[0], "source_label": source[1], "target_id": target[0],
        "target_label": target[1], "evidence_chunk_id": chunk, "evidence_quote": quote, **extra,
    }


def find(chunks: Chunks, needle: str) -> tuple[str, str]:
    """The chunk containing `needle`, and the line of it that does."""
    for chunk_id, text in chunks:
        for line in text.splitlines():
            if needle in line:
                return chunk_id, line.strip()
    raise AssertionError(f"{needle!r} is in none of the {len(chunks)} chunks shown")


class Haiku(ScriptedLLMClient):
    """Replies to extraction requests by document title; everything else is scripted as usual."""

    def __init__(self) -> None:
        super().__init__()
        self.by_title: dict[str, Edges] = {}
        self.extractions: list[str] = []

    async def complete(self, *, node: str, **kwargs: Any) -> AgentTurn:
        if node != NODE:
            return await super().complete(node=node, **kwargs)
        prompt = str(kwargs["messages"][-1]["content"])
        self.sent.append(list(kwargs["messages"]))
        title = prompt.split("\n", 1)[0].removeprefix("Document: ")
        self.extractions.append(title)
        shown = re.findall(r'<chunk id="([^"]+)" location="[^"]*">\n(.*?)\n</chunk>', prompt, flags=re.S)
        for key, edges in self.by_title.items():
            if key in title:
                return turn(tool_call("record_edges", edges=edges(shown)))
        return turn(tool_call("record_edges", edges=[]))


POL003 = ("PLG-POL-003 v2.0", "Policy"), ("PLG-POL-003 v1.0", "Policy")
POL001_73 = ("PLG-POL-001 v3.0 cl. 7.3", "Clause")
CIRCULAR_07 = ("Circular 07/2026", "Circular")


def supersedes(chunks: Chunks) -> list[dict[str, Any]]:
    chunk, line = find(chunks, "Supersedes")
    return [edge("SUPERSEDES", POL003[0], POL003[1], chunk, line)]


def overrides(chunks: Chunks) -> list[dict[str, Any]]:
    chunk, _ = find(chunks, "replaces the 0.6 m limit")
    quote = "replaces the 0.6 m limit in clause 7.3 of PLG-POL-001 Trade Mix & Usage Policy v3.0 for NC units"
    return [
        edge("OVERRIDES", CIRCULAR_07, POL001_73, chunk, quote, scope="NC units only"),
        # Made up: the text never says this, so the quote can't be found.
        edge("OVERRIDES", CIRCULAR_07, ("PLG-POL-001 v3.0 cl. 7.1", "Clause"), chunk, "replaces clause 7.1 entirely"),
    ]


def applies(chunks: Chunks) -> list[dict[str, Any]]:
    if not any("(POL-002 cl. 4.4)" in text for _, text in chunks):
        return []  # the compendium is read in batches; this case is in one of them
    chunk, line = find(chunks, "(POL-002 cl. 4.4)")
    return [edge("APPLIES", ("PC-2023-018", "Precedent"), ("PLG-POL-002 v2.1 cl. 4.4", "Clause"), chunk, line)]


@pytest.fixture
def haiku() -> Haiku:
    client = Haiku()
    client.by_title = {"Rental Arrears Management Policy (v2.0)": supersedes, "Circular 07": overrides, "Precedent Case": applies}
    return client


@pytest.fixture
def graph_dir(tmp_path: Path) -> Path:
    write_spine(RECORDS, tmp_path / "spine")
    return tmp_path


@pytest.fixture
def lineage(
    store: LanceSearchStore, haiku: Haiku, graph_dir: Path
) -> tuple[LocalGraphStore, GraphWriter, LineageReport]:
    graph = LocalGraphStore.from_dirs(graph_dir / "spine")
    writer = GraphWriter(graph_dir, graph)
    report = asyncio.run(extract_lineage(haiku, store, writer))
    return graph, writer, report


# ---------------------------------------------------------------- extraction

def test_extracted_edges_carry_their_evidence_chunk_and_quote(
    lineage: tuple[LocalGraphStore, GraphWriter, LineageReport], store: LanceSearchStore
) -> None:
    graph, _, report = lineage
    context = graph.entity_context("PLG-POL-003 v2.0", 1)
    assert context is not None
    link = next(e for e in context.edges if e.type == "SUPERSEDES")
    assert (link.start, link.end) == ("PLG-POL-003 v2.0", "PLG-POL-003 v1.0")
    chunk = store.get_chunk(str(link.props["evidence_chunk_id"]))
    assert chunk is not None and str(link.props["evidence_quote"]) in chunk.text
    assert report.edges >= 2


def test_an_edge_whose_quote_is_not_in_the_chunk_is_dropped_and_reported(
    lineage: tuple[LocalGraphStore, GraphWriter, LineageReport],
) -> None:
    graph, _, report = lineage
    assert any("cl. 7.1" in d and "verbatim" in d for d in report.dropped)
    context = graph.entity_context("Circular 07/2026", 1)
    assert context is not None
    assert [e.end for e in context.edges if e.type == "OVERRIDES"] == [POL001_73[0]]


def test_an_edge_to_an_unknown_node_is_dropped(
    store: LanceSearchStore, haiku: Haiku, graph_dir: Path
) -> None:
    def invented(chunks: Chunks) -> list[dict[str, Any]]:
        chunk, line = find(chunks, "Supersedes")
        return [edge("SUPERSEDES", POL003[0], ("PLG-POL-003 v0.1", "Policy"), chunk, line)]

    haiku.by_title = {"Rental Arrears Management Policy (v2.0)": invented}
    graph = LocalGraphStore.from_dirs(graph_dir / "spine")
    report = asyncio.run(extract_lineage(haiku, store, GraphWriter(graph_dir, graph)))
    assert any("not a known node" in d for d in report.dropped)
    assert graph.policy_lineage("PLG-POL-003") is not None
    assert graph.policy_lineage("PLG-POL-003").supersessions == []  # type: ignore[union-attr]


def test_extracting_again_changes_nothing(
    lineage: tuple[LocalGraphStore, GraphWriter, LineageReport], store: LanceSearchStore, haiku: Haiku
) -> None:
    graph, writer, first = lineage
    before = graph.policy_lineage("PLG-POL-001")
    second = asyncio.run(extract_lineage(haiku, store, writer))
    assert second.nodes == 0
    assert graph.policy_lineage("PLG-POL-001") == before
    assert first.nodes > 0


def test_lineage_and_its_evidence_survive_a_reload(
    lineage: tuple[LocalGraphStore, GraphWriter, LineageReport], graph_dir: Path
) -> None:
    graph, _, _ = lineage
    reloaded = LocalGraphStore.from_dirs(graph_dir / "spine", graph_dir / "delta")
    assert reloaded.policy_lineage("PLG-POL-001") == graph.policy_lineage("PLG-POL-001")


# ---------------------------------------------------------------- policy_lineage

def test_pol_003_lineage_lists_both_versions_and_what_superseded_what(
    lineage: tuple[LocalGraphStore, GraphWriter, LineageReport],
) -> None:
    graph, _, _ = lineage
    found = graph.policy_lineage("PLG-POL-003")
    assert found is not None
    assert [(v.version, v.status) for v in found.versions] == [("1.0", "superseded"), ("2.0", "current")]
    v1, v2 = found.versions
    assert v2.effective_from == date(2026, 4, 1)
    assert v1.effective_to == date(2026, 3, 31)
    assert found.current == v2.id
    assert [(s.newer, s.older) for s in found.supersessions] == [(v2.id, v1.id)]


def test_circular_07_2026_overrides_pol_001_clause_7_3_for_nc_units(
    lineage: tuple[LocalGraphStore, GraphWriter, LineageReport],
) -> None:
    graph, _, _ = lineage
    found = graph.policy_lineage("PLG-POL-001")
    assert found is not None
    [override] = found.overrides
    assert (override.circular_id, override.clause_number, override.policy_version) == ("Circular 07/2026", "7.3", "3.0")
    assert override.scope == "NC units only"
    assert (override.effective_from, override.effective_to) == (date(2026, 8, 1), date(2027, 7, 31))
    assert override.evidence_quote.startswith("replaces the 0.6 m limit")


def test_policy_lineage_accepts_the_short_form_and_returns_none_when_unknown(
    lineage: tuple[LocalGraphStore, GraphWriter, LineageReport],
) -> None:
    graph, _, _ = lineage
    assert isinstance(graph.policy_lineage("pol-003"), PolicyLineage)
    assert graph.policy_lineage("PLG-POL-999") is None


def test_the_lineage_cypher_is_fixed_text_with_parameters() -> None:
    for name in ("policy_versions", "policy_supersedes", "policy_overrides"):
        assert "$policy_id" in cypher.TEMPLATES[name]


def test_a_precedent_applies_the_policy_clause_it_relied_on(
    lineage: tuple[LocalGraphStore, GraphWriter, LineageReport],
) -> None:
    graph, _, _ = lineage
    context = graph.entity_context("PC-2023-018", 1)
    assert context is not None
    [link] = [e for e in context.edges if e.type == "APPLIES"]
    assert link.end == "PLG-POL-002 v2.1 cl. 4.4"
    assert "cl. 4.4" in str(link.props["evidence_quote"])


def test_graph_lineage_command_writes_the_edges_and_reports_what_it_dropped(
    corpus_index: tuple[LanceSearchStore, str], haiku: Haiku, graph_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from plg import cli
    from plg.search.embed import HashingEmbedder

    store = corpus_index[0]
    monkeypatch.setattr(cli, "make_llm", lambda settings: haiku)
    monkeypatch.setattr(cli, "make_embedder", lambda settings: HashingEmbedder(dim=128))
    env = {"PLG_SEARCH_DB": str(store.path), "PLG_GRAPH_DIR": str(graph_dir), "PLG_RECORDS_DB": str(RECORDS)}

    result = CliRunner().invoke(cli.app, ["graph", "lineage"], env=env)

    assert result.exit_code == 0, result.output
    assert "edges to" in result.stdout
    assert "verbatim" in result.output  # the made-up OVERRIDES was dropped, with its reason
    reloaded = LocalGraphStore.from_dirs(graph_dir / "spine", graph_dir / "delta")
    assert reloaded.policy_lineage("PLG-POL-001") is not None
