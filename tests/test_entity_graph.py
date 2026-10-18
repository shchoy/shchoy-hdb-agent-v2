"""The entity graph over PLG Records: spine CSVs, name/ID resolution, entity context and the writer.

Expected entities and links come from `_master` ground truth, not from the graph under test.
"""

from __future__ import annotations

import csv
import json
import re
import threading
from pathlib import Path

import pytest

from plg.config import REPO_ROOT, Settings
from plg.entities import cypher
from plg.entities.csvio import NEPTUNE_TYPES
from plg.entities.ids import is_valid_id
from plg.entities.local import LocalGraphStore
from plg.entities.model import Edge, Node
from plg.entities.open import open_graph
from plg.entities.spine import write_spine
from plg.entities.writer import GraphWriteError, GraphWriter

MASTER = REPO_ROOT / "poc-data" / "_master"
RECORDS = REPO_ROOT / "poc-data" / "plg_records.db"
GOLDEN_LEAF = json.loads((MASTER / "key_entities.json").read_text())["Golden Leaf Minimart Pte Ltd"]


def master(name: str) -> list[dict[str, object]]:
    return json.loads((MASTER / f"{name}.json").read_text())  # type: ignore[no-any-return]


@pytest.fixture(scope="session")
def graph_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("graph")
    build = write_spine(RECORDS, path / "spine")
    assert build.skipped == []
    return path


@pytest.fixture(scope="session")
def spine(graph_dir: Path) -> Path:
    return graph_dir / "spine"


@pytest.fixture(scope="session")
def graph(spine: Path) -> LocalGraphStore:
    return LocalGraphStore.from_dirs(spine)


def ids(entities: list[Node]) -> set[str]:
    return {n.id for n in entities}


# ---------------------------------------------------------------- resolution

def test_name_resolves_to_the_tenant(graph: LocalGraphStore) -> None:
    found = graph.resolve_entities("Golden Leaf Minimart Pte Ltd")
    assert [(e.id, e.label) for e in found] == [(GOLDEN_LEAF["tenant"], "Tenant")]


def test_name_in_other_case_and_punctuation_resolves(graph: LocalGraphStore) -> None:
    assert graph.resolve_entities("golden leaf  minimart, pte ltd")[0].id == GOLDEN_LEAF["tenant"]


def test_an_ambiguous_name_returns_every_close_match(graph: LocalGraphStore) -> None:
    found = {e.id for e in graph.resolve_entities("Golden Leaf Minimart", labels=["Tenant"])}
    assert {GOLDEN_LEAF["tenant"], "T-11962"} <= found


@pytest.mark.parametrize(
    ("text", "label", "expected"),
    [
        (GOLDEN_LEAF["tenancy"], "Tenancy", GOLDEN_LEAF["tenancy"]),
        (GOLDEN_LEAF["tenant"], "Tenant", GOLDEN_LEAF["tenant"]),
        (GOLDEN_LEAF["unit"], "Unit", GOLDEN_LEAF["unit"]),
        (GOLDEN_LEAF["lod"], "Letter", GOLDEN_LEAF["lod"]),
        ("see ticket IEMS-2606-0011 please", "IemsTicket", "IEMS-2606-0011"),
    ],
)
def test_business_id_resolves_first(graph: LocalGraphStore, text: str, label: str, expected: str) -> None:
    first = graph.resolve_entities(text)[0]
    assert (first.id, first.label) == (expected, label)


def test_unit_number_resolves_to_the_unit(graph: LocalGraphStore) -> None:
    assert graph.resolve_entities("Blk 214 #01-32", labels=["Unit"])[0].id == GOLDEN_LEAF["unit"]


def test_unknown_name_resolves_to_nothing(graph: LocalGraphStore) -> None:
    assert graph.resolve_entities("Nonexistent Trading Co") == []


# ---------------------------------------------------------------- entity context

def test_tenant_context_lists_tenancy_unit_letters_and_staff(graph: LocalGraphStore) -> None:
    context = graph.entity_context(str(GOLDEN_LEAF["tenant"]))
    assert context is not None
    expected_letters = {str(r["letter_id"]) for r in master("letters") if r["tenant_id"] == GOLDEN_LEAF["tenant"]}
    expected_tenancies = {str(r["tenancy_id"]) for r in master("tenancies") if r["tenant_id"] == GOLDEN_LEAF["tenant"]}
    by_label = {label: ids([n for n in context.nodes if n.label == label]) for label in {n.label for n in context.nodes}}
    assert by_label["Letter"] == expected_letters
    assert by_label["Tenancy"] == expected_tenancies
    assert GOLDEN_LEAF["unit"] in by_label["Unit"]
    authors = {str(r["author_id"]) for r in master("letters") if r["letter_id"] in expected_letters}
    assert authors <= by_label["Staff"]
    assert GOLDEN_LEAF["lod"] in by_label["Letter"]


def test_unit_context_lists_open_feedback_ticket_and_inspections(graph: LocalGraphStore) -> None:
    unit = str(GOLDEN_LEAF["unit"])
    context = graph.entity_context(unit)
    assert context is not None
    for label, rows, key in [
        ("FeedbackCase", master("feedback"), "feedback_id"),
        ("Inspection", master("inspections"), "inspection_id"),
    ]:
        assert {n.id for n in context.nodes if n.label == label} == {str(r[key]) for r in rows if r["unit_id"] == unit}
    assert {n.id for n in context.nodes if n.label == "IemsTicket"} == {
        str(r["ticket_id"]) for r in master("tickets") if r["unit_id"] == unit
    }
    assert {GOLDEN_LEAF["tenancy"], GOLDEN_LEAF["tenant"]} <= ids(context.nodes)


def test_one_hop_stays_close_and_two_hops_reach_further(graph: LocalGraphStore) -> None:
    unit = str(GOLDEN_LEAF["unit"])
    near, far = graph.entity_context(unit, hops=1), graph.entity_context(unit, hops=2)
    assert near and far
    assert GOLDEN_LEAF["tenant"] not in ids(near.nodes)
    assert GOLDEN_LEAF["tenant"] in ids(far.nodes)


def test_shared_reference_nodes_are_listed_but_not_walked_through(graph: LocalGraphStore) -> None:
    context = graph.entity_context(str(GOLDEN_LEAF["tenancy"]))
    assert context is not None
    assert "Trade" in {n.label for n in context.nodes}
    # Walking through the trade or block would pull in every other tenancy of that trade or block.
    others = {n.id for n in context.nodes if n.label == "Tenancy"}
    assert others <= {GOLDEN_LEAF["tenancy"]} | {str(r["tenancy_id"]) for r in master("tenancies") if r["unit_id"] == GOLDEN_LEAF["unit"]}


def test_unknown_entity_has_no_context(graph: LocalGraphStore) -> None:
    assert graph.entity_context("T-99999") is None


def test_the_graph_holds_entities_not_aggregates(spine: Path) -> None:
    columns = {c.split(":")[0] for f in spine.glob("nodes_*.csv") for c in next(csv.reader(f.open()))}
    assert not {c for c in columns if re.search(r"(^|_)(count|total|sum|avg|average|num)(_|$)", c)}


# ---------------------------------------------------------------- Neptune data rules

ID_PATTERN = re.compile(r"[^\s,]+")


def test_node_csvs_follow_neptune_rules(spine: Path) -> None:
    for file in spine.glob("nodes_*.csv"):
        label = file.stem.removeprefix("nodes_")
        with file.open(newline="") as f:
            reader = csv.reader(f)
            header = next(reader)
            assert header[:2] == [":ID", ":LABEL"], file.name
            for column in header[2:]:
                name, kind = column.rsplit(":", 1)
                assert kind in NEPTUNE_TYPES, f"{file.name}: {column} is not a scalar Neptune type"
                assert re.fullmatch(r"[a-z][a-z0-9_]*", name), f"{file.name}: bad property name {name}"
            for row in reader:
                assert row[0] and row[1] == label, f"{file.name}: one label per node, string ID"
                assert is_valid_id(label, row[0]), f"{file.name}: {row[0]} is not a valid {label} ID"
                assert not row[0].startswith("["), row


def test_edge_csv_follows_neptune_rules(spine: Path, graph: LocalGraphStore) -> None:
    with (spine / "edges.csv").open(newline="") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == [":ID", ":START_ID", ":END_ID", ":TYPE"]
        seen = set()
        for row in reader:
            assert re.fullmatch(r"[A-Z]+(_[A-Z]+)*", row[":TYPE"]), row
            assert row[":ID"] not in seen
            seen.add(row[":ID"])
            assert graph.node(row[":START_ID"]) and graph.node(row[":END_ID"]), row


def test_cypher_templates_are_parameterised_and_one_per_method() -> None:
    assert {"resolve_entities", "entity_context_1", "entity_context_2"} <= set(cypher.TEMPLATES)
    for name, text in cypher.TEMPLATES.items():
        assert text.lstrip().startswith("MATCH"), name
        assert not re.search(r"['\"]", text), f"{name}: literal values belong in $parameters"
        assert not re.search(r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DETACH)\b", text), f"{name}: read-only"
        assert re.search(r"\$\w+", text), name
    for hops, text in cypher.ENTITY_CONTEXT.items():
        assert f"[*1..{hops}]" in text


# ---------------------------------------------------------------- writer

@pytest.fixture
def writable(graph_dir: Path, tmp_path: Path) -> tuple[GraphWriter, LocalGraphStore]:
    import shutil

    shutil.copytree(graph_dir / "spine", tmp_path / "spine")
    store = LocalGraphStore.from_dirs(tmp_path / "spine")
    return GraphWriter(tmp_path, store), store


def new_letter(n: int = 99999) -> tuple[Node, Edge, Edge]:
    letter = Node(id=f"LTR-2026-{n:05d}", label="Letter", name="Reminder", props={"letter_type": "Arrears Reminder (1st)"})
    return (
        letter,
        Edge(type="ISSUED_FOR", start=letter.id, end=str(GOLDEN_LEAF["tenancy"])),
        Edge(type="ADDRESSED_TO", start=letter.id, end=str(GOLDEN_LEAF["tenant"])),
    )


def test_valid_write_is_visible_immediately_and_survives_reload(writable: tuple[GraphWriter, LocalGraphStore], tmp_path: Path) -> None:
    writer, store = writable
    letter, *edges = new_letter()
    writer.write([letter], edges)
    assert store.resolve_entities(letter.id)[0].id == letter.id
    context = store.entity_context(str(GOLDEN_LEAF["tenant"]))
    assert context and letter.id in ids(context.nodes)
    reloaded = LocalGraphStore.from_dirs(tmp_path / "spine", tmp_path / "delta")
    assert reloaded.node(letter.id) is not None


@pytest.mark.parametrize(
    ("node", "edge", "problem"),
    [
        (Node(id="LTR-2026-99998", label="Spaceship", name="x"), None, "not an ontology node label"),
        (Node(id="LTR-26-1", label="Letter", name="x"), None, "not a valid Letter ID"),
        (Node(id="T-11108", label="Tenant", name="again"), None, "already in the graph"),
        (None, Edge(type="LOVES", start="T-11108", end="U-BV214-01-32"), "not an ontology edge type"),
        (None, Edge(type="HELD_BY", start="T-11108", end="U-BV214-01-32"), "does not run from"),
        (None, Edge(type="HELD_BY", start="TA-2024-00542", end="T-00000"), "not in the graph"),
    ],
)
def test_invalid_writes_are_rejected_and_leave_the_graph_untouched(
    writable: tuple[GraphWriter, LocalGraphStore], tmp_path: Path, node: Node | None, edge: Edge | None, problem: str
) -> None:
    writer, store = writable
    good, *_ = new_letter(99997)
    with pytest.raises(GraphWriteError, match=problem):
        writer.write([good, *([node] if node else [])], [edge] if edge else [])
    assert store.node(good.id) is None
    assert not list((tmp_path / "delta").glob("nodes_*.csv"))


def test_property_names_cannot_break_the_csv_header(writable: tuple[GraphWriter, LocalGraphStore]) -> None:
    writer, _ = writable
    letter = Node(id="LTR-2026-99996", label="Letter", name="x", props={"a:b": "x"})
    with pytest.raises(GraphWriteError, match="lower_snake_case"):
        writer.write([letter])


def test_a_new_property_widens_the_delta_and_the_delta_passes_the_lint(
    writable: tuple[GraphWriter, LocalGraphStore], tmp_path: Path
) -> None:
    writer, store = writable
    first, *_ = new_letter(99001)
    second = Node(id="LTR-2026-99002", label="Letter", name="x", props={"remarks_text": "late"})
    writer.write([first])
    writer.write([second])
    assert store.node(first.id) and store.node(second.id)
    header = next(csv.reader((tmp_path / "delta" / "nodes_Letter.csv").open()))
    assert "remarks_text:String" in header and "letter_type:String" in header


def test_concurrent_writers_lose_nothing(writable: tuple[GraphWriter, LocalGraphStore], tmp_path: Path) -> None:
    writer, store = writable
    other = GraphWriter(tmp_path, LocalGraphStore.from_dirs(tmp_path / "spine"))
    errors: list[Exception] = []

    def work(w: GraphWriter, start: int) -> None:
        try:
            for n in range(start, start + 10):
                letter, *edges = new_letter(n)
                w.write([letter], edges)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=work, args=(w, s)) for w, s in [(writer, 90000), (other, 91000)]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    final = LocalGraphStore.from_dirs(tmp_path / "spine", tmp_path / "delta")
    assert all(final.node(f"LTR-2026-{n:05d}") for n in [*range(90000, 90010), *range(91000, 91010)])


def test_open_graph_builds_the_spine_on_first_use(tmp_path: Path) -> None:
    settings = Settings(graph_dir=tmp_path / "g")
    store = open_graph(settings)
    assert (tmp_path / "g" / "spine" / "edges.csv").exists()
    assert store.resolve_entities(str(GOLDEN_LEAF["tenant"]))[0].id == GOLDEN_LEAF["tenant"]
